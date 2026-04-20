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
#   - load_scraper_settings()
#   - Image hashing / duplicate detection helpers
#   - normalize_title(), normalize_esrb_rating()
# =============================================================================

import os
import re
import json
import logging
import requests
from PIL import Image

from config import IMAGE_PATH, STATIC_PATH
from services.normalization import normalize_genre, normalize_modes

logger = logging.getLogger(__name__)


# =============================================================================
# PERCEPTUAL HASHING (dHash) FOR DUPLICATE SCREENSHOT DETECTION
# =============================================================================

def _compute_dhash(image_path, hash_size=8):
    """Compute a difference hash (dHash) for an image. Returns a 64-bit integer or None on error."""
    try:
        img = Image.open(image_path).convert('L').resize((hash_size + 1, hash_size), Image.LANCZOS)
        try:
            pixels = list(img.getdata())
            diff = 0
            for row in range(hash_size):
                for col in range(hash_size):
                    offset = row * (hash_size + 1) + col
                    if pixels[offset] > pixels[offset + 1]:
                        diff |= 1 << (row * hash_size + col)
            return diff
        finally:
            img.close()
    except (OSError, ValueError):
        return None

def _get_existing_screenshot_hashes(filenames):
    """Compute dHash for each existing screenshot file. Returns list of (filename, hash_int) tuples."""
    hashes = []
    for fname in filenames:
        path = os.path.join(IMAGE_PATH, 'screenshots', fname)
        h = _compute_dhash(path)
        if h is not None:
            hashes.append((fname, h))
    return hashes

def _is_visual_duplicate(new_path, existing_hashes, threshold=10):
    """Check if a newly downloaded screenshot is a visual duplicate of any existing one.
    Returns (True, matching_filename) or (False, None)."""
    new_hash = _compute_dhash(new_path)
    if new_hash is None:
        return False, None
    for fname, h in existing_hashes:
        distance = bin(new_hash ^ h).count('1')
        if distance <= threshold:
            return True, fname
    return False, None


# =============================================================================
# TITLE AND RATING NORMALIZATION
# =============================================================================

def normalize_title(title):
    """Normalize title - fix spacing around colons, commas and other punctuation,
    and convert first dash-separated subtitle to colon format when appropriate."""
    if not title:
        return title

    # If title already has a colon, just fix spacing issues
    if ':' not in title:
        # Common franchise patterns that use colon subtitles
        # Convert first " - " to ": " for subtitle pattern (e.g., "Call of Duty - World at War" -> "Call of Duty: World at War")
        # Only apply if the pattern looks like a subtitle (word - word, not abbreviations)
        match = re.match(r'^([A-Za-z0-9][A-Za-z0-9\s\'\&\!\.]+?)\s+-\s+([A-Z][a-zA-Z0-9\s\-\'\&\!\.]+)$', title)
        if match:
            # Verify it's likely a subtitle pattern (base name is 2+ words or known franchise)
            base_name = match.group(1).strip()
            subtitle = match.group(2).strip()
            # Apply colon conversion for reasonable subtitle patterns
            if len(base_name) >= 3 and len(subtitle) >= 3:
                title = f"{base_name}: {subtitle}"

    # Normalize colon formatting: " : " -> ": " first, then " :" -> ":"
    title = title.replace(' : ', ': ')
    # Remove space before colon (e.g., "Game :" -> "Game:")
    title = title.replace(' :', ':')
    # Remove space before comma (e.g., "Game , Part 2" -> "Game, Part 2")
    title = title.replace(' ,', ',')
    # Ensure space after colon if followed by a letter
    title = re.sub(r':([A-Za-z])', r': \1', title)
    # Ensure space after comma if followed by a letter
    title = re.sub(r',([A-Za-z])', r', \1', title)
    # Apply article placement setting (beginning or end)
    from services.game_utils import apply_article_placement
    title = apply_article_placement(title)
    return title.strip()


def normalize_esrb_rating(rating):
    """
    Normalize ESRB rating values for consistency.
    Handles legacy ratings like KA (Kids to Adults) -> E (Everyone).
    """
    if not rating:
        return rating

    rating_upper = rating.upper().strip()

    # ESRB rating normalization map
    ESRB_NORMALIZATION = {
        # KA (Kids to Adults) was replaced by E (Everyone) in 1998
        'KA': 'E',
        'K-A': 'E',
        'KIDS TO ADULTS': 'E',
        # Ensure consistent formatting
        'E10': 'E10+',
        'EVERYONE 10+': 'E10+',
        'EVERYONE 10': 'E10+',
        'EVERYONE': 'E',
        'TEEN': 'T',
        'MATURE': 'M',
        'MATURE 17+': 'M',
        'ADULTS ONLY': 'AO',
        'ADULTS ONLY 18+': 'AO',
        'RATING PENDING': 'RP',
        'EARLY CHILDHOOD': 'EC',
    }

    # Check for direct match
    if rating_upper in ESRB_NORMALIZATION:
        return ESRB_NORMALIZATION[rating_upper]

    # Return original if already in standard format
    return rating


# =============================================================================
# SCRAPER SETTINGS
# =============================================================================

def load_scraper_settings():
    """Load scraper settings from file"""
    settings_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scraper_settings.json')

    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load scraper_settings.json: {e}")

    return {'api_keys': {}, 'enabled': {}, 'priority': []}


# =============================================================================
# TGDB METADATA APPLICATION
# =============================================================================

def apply_tgdb_to_metadata(metadata, tgdb_data, db_game_id, result, fill_only=False):
    """Apply TGDB data to metadata dict"""
    from datetime import datetime
    from scraper.scrape_metadata_thegamesdb import download_image as download_tgdb_image

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
        players = tgdb_data.get('players')
        if players:
            metadata['players'] = players
            if not metadata['modes']:
                metadata['modes'] = 'Single-Player, Multiplayer' if players > 1 else 'Single-Player'
            result['filled_fields'].append('players (TGDB)')

    # Parse rating field into ESRB and PEGI
    rating = tgdb_data.get('rating', '') or ''
    if rating:
        rating_lower = rating.lower()
        rating_upper = rating.upper()

        # Check for ESRB rating
        if not metadata['esrb_rating']:
            if 'esrb' in rating_lower:
                esrb_val = rating.replace('ESRB', '').replace('esrb', '').strip()
                if esrb_val:
                    metadata['esrb_rating'] = esrb_val
                    result['filled_fields'].append('esrb_rating (TGDB)')
            elif any(esrb in rating_upper for esrb in ['E ', 'E10+', 'T ', 'M ', 'AO', 'RP', 'EC']):
                for esrb in ['E10+', 'EC', 'E', 'T', 'M', 'AO', 'RP']:
                    if esrb in rating_upper:
                        metadata['esrb_rating'] = esrb
                        result['filled_fields'].append('esrb_rating (TGDB)')
                        break

        # Check for PEGI rating
        if not metadata['pegi_rating']:
            if 'pegi' in rating_lower:
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
        existing_hashes = _get_existing_screenshot_hashes(existing_screenshots)

        # Determine next screenshot number
        start_num = len(existing_screenshots) + 1
        new_screenshots = []

        for i, url in enumerate(ss_urls[:5]):
            filename = download_tgdb_image(db_game_id, url, 'screenshots', suffix=f'_ss{start_num + i}')
            if filename:
                local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)
                is_dup, match = _is_visual_duplicate(local_path, existing_hashes)
                if is_dup:
                    logger.info(f"Skipping duplicate TGDB screenshot {filename} (visually matches {match})")
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass
                elif filename not in existing_screenshots:
                    existing_hashes.append((filename, _compute_dhash(local_path)))
                    new_screenshots.append(filename)

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
        if ext.get('franchise') and (not metadata['franchise'] or not fill_only):
            metadata['franchise'] = ext['franchise']
            if fill_only:
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
            filename = f"{db_game_id}_igdb.jpg"
            local_path = os.path.join(IMAGE_PATH, 'boxart', filename)
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, 'wb') as f:
                        f.write(r.content)
                    try:
                        from services.image_utils import standardize_downloaded_image
                        standardize_downloaded_image(local_path, 'boxart')
                    except Exception:
                        pass
                    metadata['boxart'] = filename
                    metadata['_boxart_source'] = 'igdb'
                    result['filled_fields'].append('boxart (IGDB)')
            except Exception as e:
                logger.warning(f"Failed to download IGDB cover: {e}")

    # Download screenshots (append to existing)
    screenshots = igdb_data.get('screenshots', [])
    if screenshots:
        existing_screenshots = metadata['screenshots'].split(',') if metadata['screenshots'] else []
        existing_screenshots = [s.strip() for s in existing_screenshots if s.strip()]
        existing_hashes = _get_existing_screenshot_hashes(existing_screenshots)

        start_num = len(existing_screenshots) + 1
        new_ss_files = []

        for i, ss in enumerate(screenshots[:5]):
            if ss.get('url'):
                url = ss['url'].replace('t_thumb', 't_screenshot_big')
                if not url.startswith('http'):
                    url = f"https:{url}"
                filename = f"{db_game_id}_igdb_ss{start_num + i}.jpg"
                local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)

                # Skip if file already exists
                if filename in existing_screenshots or os.path.exists(local_path):
                    continue

                try:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, 'wb') as f:
                            f.write(r.content)
                        try:
                            from services.image_utils import standardize_downloaded_image
                            standardize_downloaded_image(local_path, 'screenshots')
                        except Exception:
                            pass
                        is_dup, match = _is_visual_duplicate(local_path, existing_hashes)
                        if is_dup:
                            logger.info(f"Skipping duplicate IGDB screenshot {filename} (visually matches {match})")
                            try:
                                os.remove(local_path)
                            except OSError:
                                pass
                        else:
                            existing_hashes.append((filename, _compute_dhash(local_path)))
                            new_ss_files.append(filename)
                except (requests.RequestException, OSError) as e:
                    logger.warning(f"Failed to download IGDB screenshot {filename}: {e}")

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
            filename = f"{db_game_id}_igdb_fanart.jpg"
            local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
            try:
                r = requests.get(url, timeout=15)
                if r.status_code == 200:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, 'wb') as f:
                        f.write(r.content)
                    metadata['fanart'] = filename
                    result['filled_fields'].append('fanart (IGDB)')
            except Exception as e:
                logger.warning(f"Failed to download IGDB fanart: {e}")

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

        if ext.get('themes') and not metadata.get('themes'):
            metadata['themes'] = ext['themes']
            result['filled_fields'].append('themes (IGDB)')

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

    # Description
    if rawg_data.get('description') and (not metadata['description'] or not fill_only):
        metadata['description'] = rawg_data['description']
        result['filled_fields'].append('description (RAWG)')

    # Release date
    if rawg_data.get('release_date') and (not metadata['release_date'] or not fill_only):
        release = rawg_data['release_date']
        if release and len(release) >= 10:
            metadata['release_date'] = release[:10]
            result['filled_fields'].append('release_date (RAWG)')

    # Developer
    if rawg_data.get('developer') and (not metadata['developer'] or not fill_only):
        metadata['developer'] = rawg_data['developer']
        result['filled_fields'].append('developer (RAWG)')

    # Publisher
    if rawg_data.get('publisher') and (not metadata['publisher'] or not fill_only):
        metadata['publisher'] = rawg_data['publisher']
        result['filled_fields'].append('publisher (RAWG)')

    # Genres
    if rawg_data.get('genre') and (not metadata['genre'] or not fill_only):
        metadata['genre'] = normalize_genre(rawg_data['genre'])
        result['filled_fields'].append('genre (RAWG)')

    # ESRB Rating
    if rawg_data.get('esrb_rating') and (not metadata['esrb_rating'] or not fill_only):
        metadata['esrb_rating'] = rawg_data['esrb_rating']
        result['filled_fields'].append('esrb_rating (RAWG)')

    # Players
    if rawg_data.get('players') and (not metadata['players'] or not fill_only):
        metadata['players'] = rawg_data['players']
        result['filled_fields'].append('players (RAWG)')

    # Modes
    if rawg_data.get('modes') and (not metadata['modes'] or not fill_only):
        metadata['modes'] = normalize_modes(rawg_data['modes'])
        result['filled_fields'].append('modes (RAWG)')

    # Critic score (Metacritic)
    if rawg_data.get('metacritic') and (not metadata['critic_score'] or not fill_only):
        metadata['critic_score'] = rawg_data['metacritic']
        metadata['critic_score_count'] = None  # RAWG doesn't provide review count
        result['filled_fields'].append('critic_score (RAWG)')

    # User score
    if rawg_data.get('user_score') and (not metadata['user_score'] or not fill_only):
        metadata['user_score'] = rawg_data['user_score']
        metadata['user_score_count'] = rawg_data.get('user_score_count')
        result['filled_fields'].append('user_score (RAWG)')

    # Franchise
    if rawg_data.get('franchise') and not metadata.get('franchise'):
        metadata['franchise'] = rawg_data['franchise']
        result['filled_fields'].append('franchise (RAWG)')

    # Boxart (only if not already present — never replace existing)
    if rawg_data.get('boxart_url') and not metadata['boxart']:
        url = rawg_data['boxart_url']
        if url:
            filename = f"{db_game_id}_rawg_boxart.jpg"
            local_path = os.path.join(IMAGE_PATH, 'boxart', filename)
            try:
                r = requests.get(url, timeout=15)
                if r.status_code == 200:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, 'wb') as f:
                        f.write(r.content)
                    try:
                        from services.image_utils import standardize_downloaded_image
                        standardize_downloaded_image(local_path, 'boxart')
                    except Exception:
                        pass
                    metadata['boxart'] = filename
                    metadata['_boxart_source'] = 'rawg'
                    result['filled_fields'].append('boxart (RAWG)')
            except Exception as e:
                logger.warning(f"Failed to download RAWG boxart: {e}")

    # Fanart from background_image_additional (only if not already present)
    if rawg_data.get('fanart_url') and not metadata.get('fanart'):
        url = rawg_data['fanart_url']
        filename = f"{db_game_id}_rawg_fanart.jpg"
        local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'wb') as f:
                    f.write(r.content)
                metadata['fanart'] = filename
                result['filled_fields'].append('fanart (RAWG)')
        except Exception as e:
            logger.warning(f"Failed to download RAWG fanart: {e}")

    # Screenshots (always append, never replace)
    if rawg_data.get('screenshot_urls'):
        screenshot_dir = os.path.join(IMAGE_PATH, 'screenshots')
        os.makedirs(screenshot_dir, exist_ok=True)

        existing_ss = [s.strip() for s in metadata['screenshots'].split(',') if s.strip()] if metadata['screenshots'] else []
        existing_hashes = _get_existing_screenshot_hashes(existing_ss)

        downloaded = []
        for i, url in enumerate(rawg_data['screenshot_urls'][:3]):
            if url:
                filename = f"{db_game_id}_rawg_ss{i+1}.jpg"
                local_path = os.path.join(screenshot_dir, filename)
                try:
                    r = requests.get(url, timeout=15)
                    if r.status_code == 200:
                        with open(local_path, 'wb') as f:
                            f.write(r.content)
                        try:
                            from services.image_utils import standardize_downloaded_image
                            standardize_downloaded_image(local_path, 'screenshots')
                        except Exception:
                            pass
                        is_dup, match = _is_visual_duplicate(local_path, existing_hashes)
                        if is_dup:
                            logger.info(f"Skipping duplicate RAWG screenshot {filename} (visually matches {match})")
                            try:
                                os.remove(local_path)
                            except OSError:
                                pass
                        else:
                            existing_hashes.append((filename, _compute_dhash(local_path)))
                            downloaded.append(filename)
                except Exception as e:
                    logger.warning(f"Failed to download RAWG screenshot: {e}")

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
            # Normalize ESRB rating
            esrb_upper = c_text.upper().strip()
            if esrb_upper in ['E', 'EVERYONE']:
                metadata['esrb_rating'] = 'E'
            elif esrb_upper in ['E10', 'E10+', 'EVERYONE 10+']:
                metadata['esrb_rating'] = 'E10+'
            elif esrb_upper in ['T', 'TEEN']:
                metadata['esrb_rating'] = 'T'
            elif esrb_upper in ['M', 'MATURE', 'MATURE 17+']:
                metadata['esrb_rating'] = 'M'
            elif esrb_upper in ['AO', 'ADULTS ONLY', 'ADULTS ONLY 18+']:
                metadata['esrb_rating'] = 'AO'
            elif esrb_upper in ['RP', 'RATING PENDING']:
                metadata['esrb_rating'] = 'RP'
            elif esrb_upper in ['EC', 'EARLY CHILDHOOD']:
                metadata['esrb_rating'] = 'EC'
            else:
                metadata['esrb_rating'] = c_text
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
        """Download a media file from ScreenScraper URL"""
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, 'wb') as f:
                    f.write(r.content)
                if image_type:
                    try:
                        from services.image_utils import standardize_downloaded_image
                        standardize_downloaded_image(dest_path, image_type)
                    except Exception:
                        pass
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
            filename = f"{db_game_id}_ss_boxart.{ext}"
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
            filename = f"{db_game_id}_ss_boxart3d.{ext}"
            local_path = os.path.join(IMAGE_PATH, 'boxart_3d', filename)
            if _download_ss_media(boxart_3d_url, local_path, image_type='boxart_3d'):
                metadata['boxart_3d'] = filename
                result['filled_fields'].append('boxart_3d (ScreenScraper)')

    # Screenshots - ALWAYS append, never replace
    existing_screenshots = metadata['screenshots'].split(',') if metadata['screenshots'] else []
    existing_screenshots = [s.strip() for s in existing_screenshots if s.strip()]
    existing_hashes = _get_existing_screenshot_hashes(existing_screenshots)

    ss_files = []
    ss_count = 0
    start_num = len(existing_screenshots)

    # Try parsed media first (screenshot URL)
    if parsed_media.get('screenshot') and ss_count < 5:
        url = parsed_media['screenshot']
        ext = url.rsplit('.', 1)[-1] if '.' in url else 'png'
        filename = f"{db_game_id}_ss_screenshot_{start_num + ss_count}.{ext}"
        local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)
        if filename not in existing_screenshots and not os.path.exists(local_path):
            if _download_ss_media(url, local_path, timeout=10, image_type='screenshots'):
                is_dup, match = _is_visual_duplicate(local_path, existing_hashes)
                if is_dup:
                    logger.info(f"Skipping duplicate ScreenScraper screenshot {filename} (visually matches {match})")
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass
                else:
                    existing_hashes.append((filename, _compute_dhash(local_path)))
                    ss_files.append(filename)
                    ss_count += 1

    # Also try raw medias list for additional screenshots
    for m in medias:
        if m.get('type') == 'ss' and ss_count < 5:
            url = m.get('url')
            if url:
                ext = m.get('format', 'png')
                filename = f"{db_game_id}_ss_screenshot_{start_num + ss_count}.{ext}"
                local_path = os.path.join(IMAGE_PATH, 'screenshots', filename)

                if filename in existing_screenshots or os.path.exists(local_path):
                    ss_count += 1
                    continue

                if _download_ss_media(url, local_path, timeout=10, image_type='screenshots'):
                    is_dup, match = _is_visual_duplicate(local_path, existing_hashes)
                    if is_dup:
                        logger.info(f"Skipping duplicate ScreenScraper screenshot {filename} (visually matches {match})")
                        try:
                            os.remove(local_path)
                        except OSError:
                            pass
                    else:
                        existing_hashes.append((filename, _compute_dhash(local_path)))
                        ss_files.append(filename)
                        ss_count += 1

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
            filename = f"{db_game_id}_ss_fanart.{ext}"
            local_path = os.path.join(IMAGE_PATH, 'fanart', filename)
            if _download_ss_media(fanart_url, local_path):
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
    fields in VALIDATE_FIELDS which are always applied (AI corrections).

    Args:
        metadata: The unified metadata dict being built.
        ai_data: Dict returned by scrape_ai.get_game_details().
        db_game_id: Database game ID (unused, kept for interface consistency).
        result: The result tracking dict with 'filled_fields' list.
        fill_only: If True (default), only fill empty fields (except VALIDATE_FIELDS).
    """
    if not ai_data:
        return

    from scraper.scrape_ai import VALIDATE_FIELDS

    def _should_apply(field):
        """Check if an AI field value should be applied."""
        if not metadata.get(field) or not fill_only:
            return True
        # VALIDATE_FIELDS are always applied — AI corrections override existing values
        if field in VALIDATE_FIELDS:
            return True
        return False

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
                     'grac_rating', 'classind_rating']
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
