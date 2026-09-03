# =============================================================================
# METADATA MERGER
# =============================================================================
# Per-source metadata application functions that merge scraped data into
# the unified metadata dict. Extracted from hybrid_scraper.py.
#
# Contains:
#   - apply_tgdb_to_metadata()
#   - apply_igdb_to_metadata()
#   - apply_rawg_to_metadata()
#   - apply_screenscraper_to_metadata()
#   - apply_ai_to_metadata()
#   - load_scraper_settings()
#
# Shared helpers live in sibling modules:
#   - scraper.image_dedup         — dHash + post-download dedup check
#   - scraper.metadata_normalizer — normalize_title, normalize_esrb_rating,
#                                   alt_title_entry, merge_alt_titles
# =============================================================================

import os
import re
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import IMAGE_PATH, STATIC_PATH
from services.image_utils import (
    preferred_image_extension,
    finalize_downloaded_image,
)
from services.normalization import normalize_genre, normalize_modes
from scraper.image_dedup import (
    compute_dhash,
    get_existing_screenshot_hashes,
    keep_screenshot_if_unique,
)
from scraper.metadata_normalizer import (
    normalize_title,
    normalize_esrb_rating,
    alt_title_entry,
    merge_alt_titles,
)
# Pass 38.2 — canonical scraper-settings loader (defaults from config.py +
# 30 s cache). Re-exported here so existing
# `from scraper.metadata_merger import load_scraper_settings` callers get
# the same fully-populated dict; this module previously shipped a divergent
# loader that returned an empty `enabled: {}` on miss, so upstream
# enabled-lookups silently disagreed with scraper_manager's view.
from scraper.scraper_manager import load_scraper_settings

logger = logging.getLogger(__name__)


def _download_and_finalize(url, local_path, image_type, *, timeout=15):
    """Pass 32.15 — hardened image download helper.

    Downstream of every TGDB / IGDB / RAWG / SS / ESDE boxart+screenshot+
    fanart call. Previously every site did:

        r = requests.get(url, timeout=X)
        f.write(r.content)
        finalize_downloaded_image(local_path, ...)  # best-effort

    which (a) had no `raise_for_status`, so 403/500 HTML bodies got written
    as .jpg; (b) buffered the entire response in memory before write;
    (c) swallowed `finalize_downloaded_image` errors but still committed
    the filename to the metadata dict, leaving a broken reference on disk.

    This helper:
      - SSRF-validates the URL and its redirect chain (Pass 32.6)
      - streams with an explicit size cap (MAX_MEDIA_DOWNLOAD_BYTES)
      - raises for non-200 upstream responses
      - writes atomically (tmp + os.replace)
      - runs finalize_downloaded_image; if it fails, deletes the file and
        returns False so the caller does NOT set metadata[field]

    Returns True on success, False on any failure.
    """
    import tempfile
    from services.ssrf import validate_outbound_url, validate_and_pin_url, pin_host_ip
    from scraper.base_scraper import _http_session
    from urllib.parse import urlparse as _urlparse

    if not url or not local_path:
        return False

    ok, _, _ = validate_outbound_url(url)
    if not ok:
        logger.warning(f"SSRF block: refusing to fetch {url}")
        return False
    # Pass 45.2: walk redirect chain + capture IP for DNS-rebinding pin.
    safe_url, pinned_ip, err = validate_and_pin_url(
        _http_session, url, max_redirects=3, timeout=5,
    )
    if err:
        logger.warning(f"SSRF block: redirect chain rejected for {url} ({err})")
        return False
    pinned_host = _urlparse(safe_url).hostname

    try:
        import config as _config
        max_bytes = getattr(_config, 'MAX_MEDIA_DOWNLOAD_BYTES', 50 * 1024 * 1024)
    except Exception:
        max_bytes = 50 * 1024 * 1024

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    dirname = os.path.dirname(local_path) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.dl_', dir=dirname)
    os.close(fd)
    try:
        # Pass 51.3: reuse the pooled base_scraper session (mirrors
        # base_scraper.download_image) so a game's images don't each pay a
        # fresh TCP+TLS handshake. pin_host_ip still forces getaddrinfo for
        # pinned_host to pinned_ip for the duration, so the DNS-rebinding
        # guarantee is unchanged.
        with pin_host_ip(pinned_host, pinned_ip), _http_session.get(safe_url, timeout=timeout, stream=True, allow_redirects=False) as r:
            if r.status_code != 200:
                logger.warning(f"Download failed: HTTP {r.status_code} — {safe_url}")
                return False
            declared = int(r.headers.get('Content-Length', 0) or 0)
            if declared and declared > max_bytes:
                logger.warning(
                    f"Download rejected: {safe_url} declared {declared} bytes > {max_bytes}"
                )
                return False
            written = 0
            with open(tmp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        logger.warning(
                            f"Download aborted: {safe_url} exceeded {max_bytes} bytes"
                        )
                        return False
                    f.write(chunk)
        os.replace(tmp_path, local_path)
    except Exception as e:
        logger.warning(f"Download error for {url}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False

    try:
        finalize_downloaded_image(local_path, image_type)
    except Exception as e:
        # If we can't finalize the bytes we just wrote (non-image content,
        # bad encoding, decoder crash), remove the file so the caller does
        # NOT set the metadata field to an invalid path.
        logger.warning(f"finalize_downloaded_image failed for {local_path}: {e}")
        try:
            os.remove(local_path)
        except OSError:
            pass
        return False

    return True


# Bounded concurrency for a game's screenshot downloads. ES-DE fetches a game's
# media files all at once (Scraper.cpp / MediaDownloadHandle) rather than
# one-by-one; this is the Python analogue. Capped so a burst never floods a
# single host or trips a per-account quota (e.g. ScreenScraper's daily limit).
_MEDIA_DOWNLOAD_WORKERS = 4


def _download_screenshots_parallel(download_jobs, existing_hashes, source_label):
    """Two-phase screenshot fetch: download every candidate concurrently, then
    run the perceptual-hash dedup SEQUENTIALLY in the original order.

    Only the network fetch is parallelised. The dedup decision
    (`keep_screenshot_if_unique`, which mutates the shared `existing_hashes` set
    and deletes duplicate files) stays single-threaded and in order, so *which*
    duplicate survives is deterministic and the hash set is never raced — the
    exact concern that made a naive parallel screenshot loop unsafe.

    Args:
        download_jobs: list of zero-arg callables, in the caller's preference
            order. Each performs one screenshot download to a distinct filename
            and returns that filename (str) on success, or a falsy value on
            failure. Distinct filenames mean the concurrent downloads never
            collide (each `_download_and_finalize` writes its own tempfile then
            os.replace()s into its own path).
        existing_hashes: mutable set of dHashes already on the game; grown in
            place as unique new screenshots are kept.
        source_label: e.g. 'IGDB' — forwarded to keep_screenshot_if_unique.

    Returns:
        list[str]: kept screenshot filenames, in the original job order.
    """
    if not download_jobs:
        return []

    # Phase 1 — download all candidates at once (bounded pool over the shared
    # base_scraper session). results[i] is the filename jobs[i] produced, or None.
    results = [None] * len(download_jobs)

    def _run(idx):
        return idx, download_jobs[idx]()

    workers = min(_MEDIA_DOWNLOAD_WORKERS, len(download_jobs))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='ss-dl') as ex:
        for fut in as_completed([ex.submit(_run, i) for i in range(len(download_jobs))]):
            try:
                idx, filename = fut.result()
                results[idx] = filename or None
            except Exception as e:
                logger.warning(f"{source_label} screenshot download worker crashed: {e}")

    # Phase 2 — dedup in the original order (single-threaded; grows existing_hashes).
    kept = []
    for filename in results:
        if not filename:
            continue
        local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)
        if keep_screenshot_if_unique(local_path, filename, existing_hashes, source_label):
            kept.append(filename)
    return kept


# Re-export helpers through this module for backward compatibility with
# existing callers (notably `scraper.hybrid_scraper`). New code should import
# from `scraper.image_dedup` / `scraper.metadata_normalizer` directly.
__all__ = [
    'apply_tgdb_to_metadata',
    'apply_igdb_to_metadata',
    'apply_rawg_to_metadata',
    'apply_screenscraper_to_metadata',
    'apply_ai_to_metadata',
    'load_scraper_settings',
    'compute_dhash',
    'get_existing_screenshot_hashes',
    'keep_screenshot_if_unique',
    'normalize_title',
    'normalize_esrb_rating',
    'alt_title_entry',
    'merge_alt_titles',
]


# =============================================================================
# TGDB METADATA APPLICATION
# =============================================================================

def apply_tgdb_to_metadata(metadata, tgdb_data, db_game_id, result, fill_only=False):
    """Apply TGDB data to metadata dict"""
    from scraper.scrape_thegamesdb import _download_tgdb_image as download_tgdb_image

    field_map = {
        'title': 'name',
        'publisher': 'publisher',
        'developer': 'developer',
        'release_date': 'release_date',
        'description': 'summary',
    }

    for meta_field, tgdb_field in field_map.items():
        # Title: always set when primary source (fill_only=False), matching IGDB/RAWG
        # Other fields: only fill if empty (cumulative scraping)
        if meta_field == 'title':
            if not metadata[meta_field] or not fill_only:
                value = tgdb_data.get(tgdb_field)
                if value:
                    metadata[meta_field] = normalize_title(value)
                    result['filled_fields'].append(f"{meta_field} (TGDB)")
        elif not metadata[meta_field]:
            value = tgdb_data.get(tgdb_field)
            if value:
                metadata[meta_field] = value
                result['filled_fields'].append(f"{meta_field} (TGDB)")

    # Genre
    if not metadata['genre']:
        genres = tgdb_data.get('genres', [])
        if genres:
            metadata['genre'] = normalize_genre(', '.join(genres))
            result['filled_fields'].append('genre (TGDB)')

    # Players/Modes
    if not metadata['players']:
        # Coerce through the canonical normalizer: TGDB can return players as a
        # string or "1-4" range, and the old bare `players > 1` raised
        # TypeError on a str, silently aborting the entire TGDB apply. This
        # also normalizes ranges to the max int for the INTEGER column.
        from services.game_utils import normalize_players_value
        players = normalize_players_value(tgdb_data.get('players'))
        if players:
            metadata['players'] = players
            if not metadata['modes']:
                from services.normalization import modes_from_player_count
                metadata['modes'] = modes_from_player_count(players)
            result['filled_fields'].append('players (TGDB)')

    # Parse rating field into ESRB and PEGI
    rating = tgdb_data.get('rating', '') or ''
    if rating:
        # Check for ESRB rating — shared with the single-source path
        # (scrape_thegamesdb) so the two token parses cannot diverge again.
        if not metadata['esrb_rating']:
            from services.game_utils import parse_esrb_code
            esrb_val = parse_esrb_code(rating)
            if esrb_val:
                metadata['esrb_rating'] = esrb_val
                result['filled_fields'].append('esrb_rating (TGDB)')

        # Check for PEGI rating
        if not metadata['pegi_rating']:
            if 'pegi' in rating.lower():
                numbers = re.findall(r'\d+', rating)
                if numbers:
                    metadata['pegi_rating'] = f"PEGI {numbers[0]}"
                    result['filled_fields'].append('pegi_rating (TGDB)')

    # Download boxart (only if not already present — never replace existing)
    if not metadata['boxart']:
        boxart_url = tgdb_data.get('boxart_url')
        if boxart_url:
            filename = download_tgdb_image(db_game_id, boxart_url, 'boxart')
            if filename:
                metadata['boxart'] = filename
                metadata['_boxart_source'] = 'tgdb'
                result['filled_fields'].append('boxart (TGDB)')

    # Download screenshots (append to existing instead of replacing)
    ss_urls = tgdb_data.get('screenshot_urls', [])
    if ss_urls:
        existing_screenshots = metadata['screenshots'].split(',') if metadata['screenshots'] else []
        existing_screenshots = [s.strip() for s in existing_screenshots if s.strip()]
        existing_hashes = get_existing_screenshot_hashes(existing_screenshots)

        start_num = len(existing_screenshots) + 1

        def _tgdb_ss_job(url, suffix):
            # download_tgdb_image both downloads and returns the filename. Skip
            # the dedup (return None) when the name collides with an existing
            # shot, so a same-name re-download is never treated as a duplicate
            # and deleted — preserving the old `if filename in existing: continue`.
            fn = download_tgdb_image(db_game_id, url, 'screenshots', suffix=suffix)
            return fn if (fn and fn not in existing_screenshots) else None

        _jobs = [
            (lambda u=url, s=f'_ss{start_num + i}': _tgdb_ss_job(u, s))
            for i, url in enumerate(ss_urls[:5])
        ]

        # Fetch all screenshots concurrently, then dedup in order.
        new_screenshots = _download_screenshots_parallel(_jobs, existing_hashes, 'TGDB')

        if new_screenshots:
            all_screenshots = existing_screenshots + new_screenshots
            metadata['screenshots'] = ','.join(all_screenshots)
            result['filled_fields'].append(f'screenshots +{len(new_screenshots)} (TGDB)')

    # Download fanart (only if not already present)
    if not metadata['fanart']:
        fanart_urls = tgdb_data.get('fanart_urls', [])
        if fanart_urls:
            filename = download_tgdb_image(db_game_id, fanart_urls[0], 'fanart', suffix='_fanart')
            if filename:
                metadata['fanart'] = filename
                result['filled_fields'].append('fanart (TGDB)')

    # Extended data
    if tgdb_data.get('_extended'):
        ext = tgdb_data['_extended']
        # Fill-only: franchise is not a title, so even on the TGDB primary path
        # (fill_only=False) it must not overwrite an existing/curated franchise.
        # IGDB and RAWG already guard with `not metadata['franchise']` only;
        # the old `or not fill_only` here let TGDB clobber a curated value.
        if ext.get('franchise') and not metadata['franchise']:
            metadata['franchise'] = ext['franchise']
            result['filled_fields'].append('franchise (TGDB)')


# =============================================================================
# IGDB METADATA APPLICATION
# =============================================================================

def apply_igdb_to_metadata(metadata, igdb_data, db_game_id, result, fill_only=False):
    """Apply IGDB data to metadata dict"""
    from datetime import datetime, timezone

    # Title
    if not metadata['title'] or not fill_only:
        if igdb_data.get('name'):
            metadata['title'] = normalize_title(igdb_data['name'])
            if fill_only:
                result['filled_fields'].append('title (IGDB)')

    # Alternate names — IGDB returns list of {name, comment?} where comment
    # is typically the region (e.g. "Japanese title") or platform variant.
    alt_entries = []
    for alt in igdb_data.get('alternative_names') or []:
        entry = alt_title_entry(
            alt.get('name'),
            region=alt.get('comment'),
            source='igdb',
        )
        if entry:
            alt_entries.append(entry)
    if alt_entries:
        before = len(metadata.get('alternate_titles') or [])
        metadata['alternate_titles'] = merge_alt_titles(
            metadata.get('alternate_titles'), alt_entries, primary_title=metadata.get('title')
        )
        added = len(metadata['alternate_titles']) - before
        if added > 0:
            result['filled_fields'].append(f'alternate_titles +{added} (IGDB)')

    # Publisher/Developer
    involved = igdb_data.get('involved_companies', [])
    publishers = []
    developers = []
    for comp in involved:
        name = comp.get('company', {}).get('name', '')
        if comp.get('publisher'):
            publishers.append(name)
        if comp.get('developer'):
            developers.append(name)

    if publishers and not metadata['publisher']:
        metadata['publisher'] = ', '.join(publishers)
        result['filled_fields'].append('publisher (IGDB)')

    if developers and not metadata['developer']:
        metadata['developer'] = ', '.join(developers)
        result['filled_fields'].append('developer (IGDB)')

    # Release date
    if not metadata['release_date']:
        ts = igdb_data.get('first_release_date')
        if ts:
            metadata['release_date'] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
            result['filled_fields'].append('release_date (IGDB)')

    # Genre
    if not metadata['genre']:
        genres = igdb_data.get('genres', [])
        if genres:
            metadata['genre'] = normalize_genre(', '.join(g.get('name', '') for g in genres))
            result['filled_fields'].append('genre (IGDB)')

    # Description
    if not metadata['description']:
        desc = igdb_data.get('storyline') or igdb_data.get('summary')
        if desc:
            metadata['description'] = desc
            result['filled_fields'].append('description (IGDB)')

    # Modes
    if not metadata['modes']:
        modes = igdb_data.get('game_modes', [])
        if modes:
            metadata['modes'] = normalize_modes(', '.join(m.get('name', '') for m in modes))
            result['filled_fields'].append('modes (IGDB)')

    # Players
    if not metadata['players']:
        multi = igdb_data.get('multiplayer_modes', [])
        if multi:
            max_p = max((m.get('offlinemax', 1) for m in multi), default=1)
            metadata['players'] = max_p
            result['filled_fields'].append('players (IGDB)')

    # Age ratings — IGDB categories: 1=ESRB, 2=PEGI, 3=CERO, 4=USK, 5=GRAC, 6=CLASS_IND, 7=ACB
    _igdb_rating_maps = {
        1: ('esrb_rating',     {6: 'RP', 7: 'EC', 8: 'E', 9: 'E10+', 10: 'T', 11: 'M', 12: 'AO'}),
        2: ('pegi_rating',     {1: 'PEGI 3', 2: 'PEGI 7', 3: 'PEGI 12', 4: 'PEGI 16', 5: 'PEGI 18'}),
        3: ('cero_rating',     {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'Z'}),
        4: ('usk_rating',      {1: '0', 2: '6', 3: '12', 4: '16', 5: '18'}),
        5: ('grac_rating',     {1: 'ALL', 2: '12', 3: '15', 4: '18'}),
        6: ('classind_rating', {1: 'L', 2: '10', 3: '12', 4: '14', 5: '16', 6: '18'}),
        7: ('acb_rating',      {1: 'G', 2: 'PG', 3: 'M', 4: 'MA15+', 5: 'R18+'}),
    }
    for rating in igdb_data.get('age_ratings', []):
        cat = rating.get('category')
        val = rating.get('rating')
        if cat in _igdb_rating_maps:
            field, vmap = _igdb_rating_maps[cat]
            if not metadata.get(field):
                mapped = vmap.get(val)
                if mapped:
                    metadata[field] = mapped
                    result['filled_fields'].append(f'{field} (IGDB)')

    # Download cover (only if not already present)
    if not metadata['boxart']:
        cover = igdb_data.get('cover', {})
        if cover.get('url'):
            url = cover['url'].replace('t_thumb', 't_cover_big')
            if not url.startswith('http'):
                url = f"https:{url}"
            filename = f"{db_game_id}_igdb{preferred_image_extension('boxart', '.jpg')}"
            local_path = os.path.join(IMAGE_PATH, 'boxart', filename)
            if _download_and_finalize(url, local_path, 'boxart', timeout=10):
                metadata['boxart'] = filename
                metadata['_boxart_source'] = 'igdb'
                result['filled_fields'].append('boxart (IGDB)')

    # Download screenshots (append to existing)
    screenshots = igdb_data.get('screenshots', [])
    if screenshots:
        existing_screenshots = metadata['screenshots'].split(',') if metadata['screenshots'] else []
        existing_screenshots = [s.strip() for s in existing_screenshots if s.strip()]
        existing_hashes = get_existing_screenshot_hashes(existing_screenshots)

        start_num = len(existing_screenshots) + 1
        _jobs = []

        for i, ss in enumerate(screenshots[:5]):
            if ss.get('url'):
                url = ss['url'].replace('t_thumb', 't_screenshot_big')
                if not url.startswith('http'):
                    url = f"https:{url}"
                filename = f"{db_game_id}_igdb_ss{start_num + i}{preferred_image_extension('screenshots', '.jpg')}"
                local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)

                # Skip if file already exists
                if filename in existing_screenshots or os.path.exists(local_path):
                    continue

                _jobs.append(
                    lambda u=url, p=local_path, f=filename:
                        f if _download_and_finalize(u, p, 'screenshots', timeout=10) else None
                )

        # Fetch all screenshots concurrently, then dedup in order.
        new_ss_files = _download_screenshots_parallel(_jobs, existing_hashes, 'IGDB')

        if new_ss_files:
            all_screenshots = existing_screenshots + new_ss_files
            metadata['screenshots'] = ','.join(all_screenshots)
            result['filled_fields'].append(f'screenshots +{len(new_ss_files)} (IGDB)')

    # Download fanart/artwork (only if not already present)
    if not metadata['fanart']:
        artworks = igdb_data.get('artworks', [])
        if artworks and artworks[0].get('url'):
            url = artworks[0]['url'].replace('t_thumb', 't_1080p')
            if not url.startswith('http'):
                url = f"https:{url}"
            filename = f"{db_game_id}_igdb_fanart{preferred_image_extension('fanart', '.jpg')}"
            local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
            if _download_and_finalize(url, local_path, 'fanart', timeout=15):
                metadata['fanart'] = filename
                result['filled_fields'].append('fanart (IGDB)')

    # Extended data
    if igdb_data.get('_extended'):
        ext = igdb_data['_extended']

        if ext.get('franchise') and not metadata['franchise']:
            metadata['franchise'] = ext['franchise']
            result['filled_fields'].append('franchise (IGDB)')

        if ext.get('similar_games') and not metadata['similar_games']:
            metadata['similar_games'] = ext['similar_games']
            result['filled_fields'].append('similar_games (IGDB)')

        if ext.get('playtime_estimate') and not metadata['playtime_estimate']:
            metadata['playtime_estimate'] = ext['playtime_estimate']
            result['filled_fields'].append('playtime_estimate (IGDB)')

        if ext.get('perspective') and not metadata.get('perspective'):
            metadata['perspective'] = ext['perspective']
            result['filled_fields'].append('perspective (IGDB)')

        # Critic and user scores
        if ext.get('critic_score') and not metadata.get('critic_score'):
            metadata['critic_score'] = ext['critic_score']
            metadata['critic_score_count'] = ext.get('critic_score_count')
            result['filled_fields'].append(f"critic_score (IGDB: {ext['critic_score']:.1f})")

        if ext.get('user_score') and not metadata.get('user_score'):
            metadata['user_score'] = ext['user_score']
            metadata['user_score_count'] = ext.get('user_score_count')
            result['filled_fields'].append(f"user_score (IGDB: {ext['user_score']:.1f})")


# =============================================================================
# RAWG METADATA APPLICATION
# =============================================================================

def apply_rawg_to_metadata(metadata, rawg_data, db_game_id, result, fill_only=False):
    """Apply RAWG.io data to metadata dict"""

    # Title
    if rawg_data.get('name') and (not metadata['title'] or not fill_only):
        metadata['title'] = normalize_title(rawg_data['name'])
        result['filled_fields'].append('title (RAWG)')

    # Non-title fields are fill-only regardless of fill_only flag, matching
    # TGDB / IGDB / ScreenScraper. Only title overwrites on primary source.

    # Description
    if rawg_data.get('description') and not metadata['description']:
        metadata['description'] = rawg_data['description']
        result['filled_fields'].append('description (RAWG)')

    # Release date
    if rawg_data.get('release_date') and not metadata['release_date']:
        release = rawg_data['release_date']
        if release and len(release) >= 10:
            metadata['release_date'] = release[:10]
            result['filled_fields'].append('release_date (RAWG)')

    # Developer
    if rawg_data.get('developer') and not metadata['developer']:
        metadata['developer'] = rawg_data['developer']
        result['filled_fields'].append('developer (RAWG)')

    # Publisher
    if rawg_data.get('publisher') and not metadata['publisher']:
        metadata['publisher'] = rawg_data['publisher']
        result['filled_fields'].append('publisher (RAWG)')

    # Genres
    if rawg_data.get('genre') and not metadata['genre']:
        metadata['genre'] = normalize_genre(rawg_data['genre'])
        result['filled_fields'].append('genre (RAWG)')

    # ESRB Rating
    if rawg_data.get('esrb_rating') and not metadata['esrb_rating']:
        metadata['esrb_rating'] = rawg_data['esrb_rating']
        result['filled_fields'].append('esrb_rating (RAWG)')

    # Players
    if rawg_data.get('players') and not metadata['players']:
        metadata['players'] = rawg_data['players']
        result['filled_fields'].append('players (RAWG)')

    # Modes
    if rawg_data.get('modes') and not metadata['modes']:
        metadata['modes'] = normalize_modes(rawg_data['modes'])
        result['filled_fields'].append('modes (RAWG)')

    # Critic score (Metacritic)
    if rawg_data.get('metacritic') and not metadata['critic_score']:
        metadata['critic_score'] = rawg_data['metacritic']
        metadata['critic_score_count'] = None  # RAWG doesn't provide review count
        result['filled_fields'].append('critic_score (RAWG)')

    # User score
    if rawg_data.get('user_score') and not metadata['user_score']:
        metadata['user_score'] = rawg_data['user_score']
        metadata['user_score_count'] = rawg_data.get('user_score_count')
        result['filled_fields'].append('user_score (RAWG)')

    # Franchise
    if rawg_data.get('franchise') and not metadata.get('franchise'):
        metadata['franchise'] = rawg_data['franchise']
        result['filled_fields'].append('franchise (RAWG)')

    # Alternate names — RAWG returns flat list of strings with no region info.
    alt_entries = [
        alt_title_entry(name, source='rawg')
        for name in (rawg_data.get('alternative_names') or [])
    ]
    alt_entries = [e for e in alt_entries if e]
    if alt_entries:
        before = len(metadata.get('alternate_titles') or [])
        metadata['alternate_titles'] = merge_alt_titles(
            metadata.get('alternate_titles'), alt_entries, primary_title=metadata.get('title')
        )
        added = len(metadata['alternate_titles']) - before
        if added > 0:
            result['filled_fields'].append(f'alternate_titles +{added} (RAWG)')

    # Boxart (only if not already present — never replace existing)
    if rawg_data.get('boxart_url') and not metadata['boxart']:
        url = rawg_data['boxart_url']
        if url:
            filename = f"{db_game_id}_rawg_boxart{preferred_image_extension('boxart', '.jpg')}"
            local_path = os.path.join(IMAGE_PATH, 'boxart', filename)
            if _download_and_finalize(url, local_path, 'boxart', timeout=15):
                metadata['boxart'] = filename
                metadata['_boxart_source'] = 'rawg'
                result['filled_fields'].append('boxart (RAWG)')

    # Fanart from background_image_additional (only if not already present)
    if rawg_data.get('fanart_url') and not metadata.get('fanart'):
        url = rawg_data['fanart_url']
        filename = f"{db_game_id}_rawg_fanart{preferred_image_extension('fanart', '.jpg')}"
        local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
        if _download_and_finalize(url, local_path, 'fanart', timeout=15):
            metadata['fanart'] = filename
            result['filled_fields'].append('fanart (RAWG)')

    # Screenshots (always append, never replace)
    if rawg_data.get('screenshot_urls'):
        screenshot_dir = os.path.join(IMAGE_PATH, 'screenshots')
        os.makedirs(screenshot_dir, exist_ok=True)

        existing_ss = [s.strip() for s in metadata['screenshots'].split(',') if s.strip()] if metadata['screenshots'] else []
        existing_hashes = get_existing_screenshot_hashes(existing_ss)

        # Offset by what is already stored and skip a name that exists, the
        # same guard the IGDB / TGDB / ScreenScraper loops carry. Fixed indices
        # 1-3 collided on a re-scrape: the same path was overwritten, and since
        # existing_hashes was computed BEFORE that write, the re-download was a
        # visual duplicate of itself -- so dedup deleted the file while its name
        # was still in existing_ss and still went into games.screenshots. That
        # left a good screenshot gone from disk and dangling in the DB, which
        # the next scrape's stale prune then dropped from the DB too.
        start_num = len(existing_ss) + 1

        _jobs = []
        for i, url in enumerate(rawg_data['screenshot_urls'][:3]):
            if url:
                filename = f"{db_game_id}_rawg_ss{start_num + i}{preferred_image_extension('screenshots', '.jpg')}"
                local_path = os.path.join(screenshot_dir, filename)
                if filename in existing_ss or os.path.exists(local_path):
                    continue
                _jobs.append(
                    lambda u=url, p=local_path, f=filename:
                        f if _download_and_finalize(u, p, 'screenshots', timeout=15) else None
                )

        # Fetch all screenshots concurrently, then dedup in order.
        downloaded = _download_screenshots_parallel(_jobs, existing_hashes, 'RAWG')

        if downloaded:
            if metadata['screenshots']:
                existing = [s.strip() for s in metadata['screenshots'].split(',') if s.strip()]
                downloaded = existing + downloaded
            metadata['screenshots'] = ','.join(downloaded)
            result['filled_fields'].append('screenshots (RAWG)')


# =============================================================================
# SCREENSCRAPER METADATA APPLICATION
# =============================================================================

def apply_screenscraper_to_metadata(metadata, ss_data, db_game_id, result, fill_only=False):
    """
    Apply ScreenScraper data to metadata dict.

    IMPORTANT: This function follows the "augment, don't replace" principle:
    - Text fields are only filled if currently empty
    - Screenshots are always appended, never replaced
    - Boxart/fanart only downloaded if not already present
    """

    def get_localized(items, lang='en'):
        """Get localized text from ScreenScraper format"""
        if not items:
            return None
        # Priority: en/us, wor, ss, first available
        for region in ['us', 'eu', 'wor', 'ss']:
            for item in items:
                if item.get('region', '').lower() == region or item.get('langue', '').lower() == region:
                    return item.get('text', '')
        # Language-based
        for item in items:
            if item.get('langue', '').lower() == lang:
                return item.get('text', '')
        # Fallback
        if items and isinstance(items[0], dict):
            return items[0].get('text', '')
        return None

    # Title - always set when primary source (fill_only=False), matching IGDB/RAWG
    title = get_localized(ss_data.get('noms'))
    if title and (not metadata['title'] or not fill_only):
        metadata['title'] = normalize_title(title)
        result['filled_fields'].append('title (ScreenScraper)')

    # Alternate names — ScreenScraper's `noms` list is already region-tagged
    # with every regional release title. Keep the whole list (minus the one
    # chosen as primary title) as alt titles.
    alt_entries = []
    for nom in ss_data.get('noms') or []:
        if not isinstance(nom, dict):
            continue
        entry = alt_title_entry(
            nom.get('text'),
            region=nom.get('region') or nom.get('langue'),
            source='screenscraper',
        )
        if entry:
            alt_entries.append(entry)
    if alt_entries:
        before = len(metadata.get('alternate_titles') or [])
        metadata['alternate_titles'] = merge_alt_titles(
            metadata.get('alternate_titles'), alt_entries, primary_title=metadata.get('title')
        )
        added = len(metadata['alternate_titles']) - before
        if added > 0:
            result['filled_fields'].append(f'alternate_titles +{added} (ScreenScraper)')

    # Description - only fill if empty
    desc = get_localized(ss_data.get('synopsis'))
    if desc and not metadata['description']:
        metadata['description'] = desc
        result['filled_fields'].append('description (ScreenScraper)')

    # Release date - only fill if empty
    dates = ss_data.get('dates', [])
    if dates and not metadata['release_date']:
        date_str = get_localized(dates)
        if date_str:
            metadata['release_date'] = date_str[:10] if len(date_str) >= 10 else date_str
            result['filled_fields'].append('release_date (ScreenScraper)')

    # Developer/Publisher - only fill if empty
    if ss_data.get('developpeur') and not metadata['developer']:
        dev = ss_data['developpeur']
        if isinstance(dev, dict):
            metadata['developer'] = dev.get('text', '')
        else:
            metadata['developer'] = str(dev)
        result['filled_fields'].append('developer (ScreenScraper)')

    if ss_data.get('editeur') and not metadata['publisher']:
        pub = ss_data['editeur']
        if isinstance(pub, dict):
            metadata['publisher'] = pub.get('text', '')
        else:
            metadata['publisher'] = str(pub)
        result['filled_fields'].append('publisher (ScreenScraper)')

    # Genre - only fill if empty
    genres = ss_data.get('genres', [])
    if genres and not metadata['genre']:
        genre_names = []
        for g in genres:
            name = get_localized(g.get('noms', []))
            if name:
                genre_names.append(name)
        if genre_names:
            metadata['genre'] = normalize_genre(', '.join(genre_names))
            result['filled_fields'].append('genre (ScreenScraper)')

    # Players - only fill if empty
    if ss_data.get('joueurs') and not metadata['players']:
        players = ss_data['joueurs']
        if isinstance(players, dict):
            metadata['players'] = players.get('text', '')
        else:
            metadata['players'] = str(players)
        result['filled_fields'].append('players (ScreenScraper)')

    # Franchise/series (familles) - only fill if empty
    familles = ss_data.get('familles', [])
    if familles and not metadata.get('franchise'):
        franchise_names = []
        for f in familles:
            name = get_localized(f.get('noms', []))
            if name:
                franchise_names.append(name)
        if franchise_names:
            metadata['franchise'] = ', '.join(franchise_names)
            result['filled_fields'].append('franchise (ScreenScraper)')
    # Also check for pre-processed franchise from newer scraper format
    if ss_data.get('franchise') and not metadata.get('franchise'):
        metadata['franchise'] = ss_data['franchise']
        result['filled_fields'].append('franchise (ScreenScraper)')

    # Game modes - only fill if empty
    modes_data = ss_data.get('modes', [])
    if modes_data and not metadata.get('modes'):
        if isinstance(modes_data, str):
            metadata['modes'] = normalize_modes(modes_data)
            result['filled_fields'].append('modes (ScreenScraper)')
        elif isinstance(modes_data, list):
            mode_names = []
            for m in modes_data:
                if isinstance(m, dict):
                    name = get_localized(m.get('noms', []))
                    if name:
                        mode_names.append(name)
                elif isinstance(m, str):
                    mode_names.append(m)
            if mode_names:
                metadata['modes'] = normalize_modes(', '.join(mode_names))
                result['filled_fields'].append('modes (ScreenScraper)')

    # Ratings - only fill if empty
    classifications = ss_data.get('classifications', [])
    for c in classifications:
        c_type = c.get('type', '').upper()
        c_text = c.get('text', '')
        if c_type == 'ESRB' and c_text and not metadata['esrb_rating']:
            # Normalize ESRB rating via shared normalizer (covers E, E10+, T,
            # M, AO, RP, EC and legacy KA → E mapping).
            metadata['esrb_rating'] = normalize_esrb_rating(c_text)
            result['filled_fields'].append('esrb_rating (ScreenScraper)')
        elif c_type == 'PEGI' and c_text and not metadata.get('pegi_rating'):
            # Ensure PEGI format consistency
            if c_text.isdigit():
                metadata['pegi_rating'] = f"PEGI {c_text}"
            else:
                metadata['pegi_rating'] = c_text
            result['filled_fields'].append('pegi_rating (ScreenScraper)')
        elif c_type == 'CERO' and c_text and not metadata.get('cero_rating'):
            val = c_text.strip().upper()
            if val in ('A', 'B', 'C', 'D', 'Z'):
                metadata['cero_rating'] = val
                result['filled_fields'].append('cero_rating (ScreenScraper)')
        elif c_type == 'USK' and c_text and not metadata.get('usk_rating'):
            val = c_text.strip()
            if val in ('0', '6', '12', '16', '18'):
                metadata['usk_rating'] = val
                result['filled_fields'].append('usk_rating (ScreenScraper)')
        elif c_type == 'ACB' and c_text and not metadata.get('acb_rating'):
            metadata['acb_rating'] = c_text.strip()
            result['filled_fields'].append('acb_rating (ScreenScraper)')
        elif c_type in ('CLASSIND', 'CLASS_IND') and c_text and not metadata.get('classind_rating'):
            metadata['classind_rating'] = c_text.strip()
            result['filled_fields'].append('classind_rating (ScreenScraper)')
        elif c_type == 'GRAC' and c_text and not metadata.get('grac_rating'):
            metadata['grac_rating'] = c_text.strip()
            result['filled_fields'].append('grac_rating (ScreenScraper)')

    # Also check for pre-processed rating fields from newer scraper format
    _ss_rating_fields = ['esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
                         'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating']
    for rf in _ss_rating_fields:
        if ss_data.get(rf) and not metadata.get(rf):
            metadata[rf] = ss_data[rf]
            result['filled_fields'].append(f'{rf} (ScreenScraper)')

    # User score (community rating) - only fill if empty
    # ScreenScraper's "note" is 0-20 scale, convert to 0-100
    if ss_data.get('user_score') and not metadata.get('user_score'):
        metadata['user_score'] = ss_data['user_score']
        result['filled_fields'].append('user_score (ScreenScraper)')
    elif not metadata.get('user_score'):
        # Try raw note field (0-20 scale)
        note = ss_data.get('note', {})
        if isinstance(note, dict):
            note_text = note.get('text', '')
        else:
            note_text = str(note) if note else ''
        if note_text:
            try:
                note_value = float(note_text)
                # Convert 0-20 scale to 0-100
                metadata['user_score'] = round(note_value * 5, 1)
                result['filled_fields'].append('user_score (ScreenScraper)')
            except (ValueError, TypeError):
                pass

    # Media downloads
    # Handle both raw API format (medias list) and parsed format (media dict from parse_game_data)
    medias = ss_data.get('medias', [])
    parsed_media = ss_data.get('media', {})

    def _download_ss_media(url, dest_path, timeout=15, image_type=None):
        """Download a media file from ScreenScraper URL.

        Pass 32.15: routes through the hardened _download_and_finalize
        helper (SSRF gate, streamed size cap, atomic write, rollback on
        finalize failure) when `image_type` is provided. For manual/video
        downloads (image_type=None) we keep the legacy behaviour but still
        apply the SSRF gate and streaming size cap.
        """
        if image_type:
            return _download_and_finalize(url, dest_path, image_type, timeout=timeout)

        # Non-image media (manuals, videos) — still SSRF-validate and stream.
        from services.ssrf import validate_outbound_url, validate_and_pin_url, pin_host_ip
        from scraper.base_scraper import _http_session
        from urllib.parse import urlparse as _urlparse
        ok, _, _ = validate_outbound_url(url)
        if not ok:
            logger.warning(f"SSRF block: refusing to fetch {url}")
            return False
        # Pass 45.2: walk redirect chain + capture IP for DNS-rebinding pin.
        safe_url, pinned_ip, err = validate_and_pin_url(
            _http_session, url, max_redirects=3, timeout=5,
        )
        if err:
            logger.warning(f"SSRF block: redirect chain rejected for {url} ({err})")
            return False
        pinned_host = _urlparse(safe_url).hostname
        try:
            import config as _config
            max_bytes = getattr(_config, 'MAX_MEDIA_DOWNLOAD_BYTES', 50 * 1024 * 1024)
        except Exception:
            max_bytes = 50 * 1024 * 1024
        try:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with pin_host_ip(pinned_host, pinned_ip), _http_session.get(safe_url, timeout=timeout, stream=True, allow_redirects=False) as r:
                if r.status_code != 200:
                    return False
                declared = int(r.headers.get('Content-Length', 0) or 0)
                if declared and declared > max_bytes:
                    logger.warning(f"ScreenScraper media rejected: declared {declared} > {max_bytes}")
                    return False
                written = 0
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > max_bytes:
                            logger.warning(f"ScreenScraper media aborted: exceeded {max_bytes} bytes")
                            try:
                                f.close()
                                os.remove(dest_path)
                            except OSError:
                                pass
                            return False
                        f.write(chunk)
            return True
        except Exception as e:
            logger.warning(f"Failed to download ScreenScraper media: {e}")
        return False

    # Boxart (2D) - only download if not already present (never replace existing)
    if not metadata['boxart']:
        boxart_url = parsed_media.get('boxart_front')
        if not boxart_url:
            for m in medias:
                if m.get('type') in ['box-2D', 'boite-2D']:
                    boxart_url = m.get('url')
                    if boxart_url:
                        ext = m.get('format', 'png')
                        break
            else:
                ext = 'png'
        else:
            ext = boxart_url.rsplit('.', 1)[-1] if '.' in boxart_url else 'png'

        if boxart_url:
            filename = f"{db_game_id}_ss_boxart{preferred_image_extension('boxart', '.' + ext)}"
            local_path = os.path.join(IMAGE_PATH, 'boxart', filename)
            if _download_ss_media(boxart_url, local_path, image_type='boxart'):
                metadata['boxart'] = filename
                metadata['_boxart_source'] = 'screenscraper'
                result['filled_fields'].append('boxart (ScreenScraper)')

    # 3D Boxart - only download if not already present
    if not metadata.get('boxart_3d'):
        boxart_3d_url = parsed_media.get('boxart_3d')
        if not boxart_3d_url:
            for m in medias:
                if m.get('type') == 'box-3D':
                    boxart_3d_url = m.get('url')
                    if boxart_3d_url:
                        ext = m.get('format', 'png')
                        break
            else:
                ext = 'png'
        else:
            ext = boxart_3d_url.rsplit('.', 1)[-1] if '.' in boxart_3d_url else 'png'

        if boxart_3d_url:
            filename = f"{db_game_id}_ss_boxart3d{preferred_image_extension('boxart_3d', '.' + ext)}"
            local_path = os.path.join(IMAGE_PATH, 'boxart_3d', filename)
            if _download_ss_media(boxart_3d_url, local_path, image_type='boxart_3d'):
                metadata['boxart_3d'] = filename
                result['filled_fields'].append('boxart_3d (ScreenScraper)')

    # Screenshots - ALWAYS append, never replace
    existing_screenshots = metadata['screenshots'].split(',') if metadata['screenshots'] else []
    existing_screenshots = [s.strip() for s in existing_screenshots if s.strip()]
    existing_hashes = get_existing_screenshot_hashes(existing_screenshots)

    start_num = len(existing_screenshots)

    # Collect up to 5 candidate screenshot URLs — the parsed screenshot first,
    # then the raw medias list — assigning a distinct indexed filename to each,
    # skipping any already present. They then download concurrently.
    _ss_candidates = []
    if parsed_media.get('screenshot'):
        _u = parsed_media['screenshot']
        _ss_candidates.append((_u, _u.rsplit('.', 1)[-1] if '.' in _u else 'png'))
    for m in medias:
        if m.get('type') == 'ss' and m.get('url'):
            _ss_candidates.append((m['url'], m.get('format', 'png')))
    _ss_candidates = _ss_candidates[:5]

    _jobs = []
    for idx, (url, ext) in enumerate(_ss_candidates):
        filename = f"{db_game_id}_ss_screenshot_{start_num + idx}{preferred_image_extension('screenshots', '.' + ext)}"
        local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)
        if filename in existing_screenshots or os.path.exists(local_path):
            continue
        _jobs.append(
            lambda u=url, p=local_path, f=filename:
                f if _download_ss_media(u, p, timeout=10, image_type='screenshots') else None
        )

    # Fetch all screenshots concurrently, then dedup in order.
    ss_files = _download_screenshots_parallel(_jobs, existing_hashes, 'ScreenScraper')

    if ss_files:
        all_screenshots = existing_screenshots + ss_files
        metadata['screenshots'] = ','.join(all_screenshots)
        result['filled_fields'].append(f'screenshots +{len(ss_files)} (ScreenScraper)')

    # Fanart - only download if not already present
    if not metadata['fanart']:
        fanart_url = parsed_media.get('fanart')
        if not fanart_url:
            for m in medias:
                if m.get('type') == 'fanart':
                    fanart_url = m.get('url')
                    if fanart_url:
                        ext = m.get('format', 'jpg')
                        break
            else:
                ext = 'jpg'
        else:
            ext = fanart_url.rsplit('.', 1)[-1] if '.' in fanart_url else 'jpg'

        if fanart_url:
            filename = f"{db_game_id}_ss_fanart{preferred_image_extension('fanart', '.' + ext)}"
            local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
            if _download_ss_media(fanart_url, local_path, image_type='fanart'):
                metadata['fanart'] = filename
                result['filled_fields'].append('fanart (ScreenScraper)')

    # Video - only download if not already present
    if not metadata['video']:
        video_url = parsed_media.get('video')
        if not video_url:
            for m in medias:
                if m.get('type') in ['video', 'video-normalized']:
                    video_url = m.get('url')
                    if video_url:
                        ext = m.get('format', 'mp4')
                        break
            else:
                ext = 'mp4'
        else:
            ext = video_url.rsplit('.', 1)[-1] if '.' in video_url else 'mp4'

        if video_url:
            filename = f"{db_game_id}_ss_video.{ext}"
            video_dir = os.path.join(STATIC_PATH, 'videos')
            local_path = os.path.join(video_dir, filename)
            if _download_ss_media(video_url, local_path, timeout=60):
                metadata['video'] = filename
                result['filled_fields'].append('video (ScreenScraper)')

    # Manual - only download if not already present
    if not metadata['manual']:
        manual_url = parsed_media.get('manual')
        if not manual_url:
            for m in medias:
                if m.get('type') == 'manuel':
                    manual_url = m.get('url')
                    if manual_url:
                        ext = m.get('format', 'pdf')
                        break
            else:
                ext = 'pdf'
        else:
            ext = manual_url.rsplit('.', 1)[-1] if '.' in manual_url else 'pdf'

        if manual_url:
            filename = f"{db_game_id}_ss_manual.{ext}"
            local_path = os.path.join(IMAGE_PATH, 'manuals', filename)
            if _download_ss_media(manual_url, local_path, timeout=60):
                metadata['manual'] = filename
                result['filled_fields'].append('manual (ScreenScraper)')


# =============================================================================
# AI METADATA
# =============================================================================

def apply_ai_to_metadata(metadata, ai_data, db_game_id, result, fill_only=True):
    """Apply AI-generated data to metadata dict.

    AI only fills text fields — never images, screenshots, video, or manuals.
    fill_only=True by default: AI never overwrites existing data, EXCEPT for
    fill_only is honoured for every field, with no exceptions.

    Args:
        metadata: The unified metadata dict being built.
        ai_data: Dict returned by scrape_ai.get_game_details().
        db_game_id: Database game ID (unused, kept for interface consistency).
        result: The result tracking dict with 'filled_fields' list.
        fill_only: If True (default), only fill empty fields.
    """
    if not ai_data:
        return

    def _should_apply(field):
        """Check if an AI field value should be applied.

        This used to return True for every field in scrape_ai.VALIDATE_FIELDS
        regardless of fill_only -- genre, modes, publisher, developer, players,
        save_type, the nine rating columns and more. The hybrid scraper's only
        call is fill_only=True on a NORMAL scrape, so a gap-fill silently
        replaced hand-curated values in all of them: a second, undocumented
        exception to the fill-only invariant that docs/specs/scrapers.md and
        CLAUDE.md both state has exactly one (force_overwrite).

        The user-invoked AI Fill path is unaffected -- routes/games_ai.py does
        not call this function and applies its own VALIDATE_FIELDS handling,
        which is where overwriting is the point.
        """
        return not metadata.get(field) or not fill_only

    # Simple text fields — direct mapping
    simple_fields = [
        'description', 'developer', 'publisher', 'release_date',
        'players', 'region', 'franchise', 'similar_games',
        'controller_support', 'save_type', 'campaign', 'other_platforms',
        'edition',
    ]

    for field in simple_fields:
        if ai_data.get(field) and _should_apply(field):
            metadata[field] = ai_data[field]
            result['filled_fields'].append(f'{field} (AI)')

    # Normalized fields
    if ai_data.get('genre') and _should_apply('genre'):
        metadata['genre'] = normalize_genre(ai_data['genre'])
        result['filled_fields'].append('genre (AI)')

    if ai_data.get('modes') and _should_apply('modes'):
        metadata['modes'] = normalize_modes(ai_data['modes'])
        result['filled_fields'].append('modes (AI)')

    if ai_data.get('esrb_rating') and _should_apply('esrb_rating'):
        metadata['esrb_rating'] = ai_data['esrb_rating']
        result['filled_fields'].append('esrb_rating (AI)')

    if ai_data.get('pegi_rating') and _should_apply('pegi_rating'):
        metadata['pegi_rating'] = ai_data['pegi_rating']
        result['filled_fields'].append('pegi_rating (AI)')

    # Additional age rating fields
    rating_fields = ['cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
                     'grac_rating', 'classind_rating', 'china_rating']
    for field in rating_fields:
        if ai_data.get(field) and _should_apply(field):
            metadata[field] = ai_data[field]
            result['filled_fields'].append(f'{field} (AI)')

    # Multi-value text fields (already validated/normalized by scrape_ai)
    multi_fields = ['game_structure', 'perspective', 'dimension']
    for field in multi_fields:
        if ai_data.get(field) and _should_apply(field):
            metadata[field] = ai_data[field]
            result['filled_fields'].append(f'{field} (AI)')

    # Score fields — convert to int before storing
    score_fields = ['critic_score', 'critic_score_count', 'user_score', 'user_score_count']
    for field in score_fields:
        val = ai_data.get(field)
        if val and _should_apply(field):
            try:
                metadata[field] = int(float(val))
                result['filled_fields'].append(f'{field} (AI)')
            except (ValueError, TypeError):
                pass
