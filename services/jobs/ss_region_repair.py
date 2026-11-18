# =============================================================================
# RETRODB - ScreenScraper Region Repair Job
# =============================================================================
# Scrapes before PASS-59-202 took the first box, 3D box and manual in
# ScreenScraper's alphabetical region list, and media is fill-only, so those
# games keep the wrong region's picture. This job looks each one up again and
# swaps the file where the right choice is not the first listed; where it is,
# the stored file is already right and nothing is downloaded.
#
# Only files a scrape named `<id>_ss_boxart.*`, `<id>_ss_boxart3d.*` or
# `<id>_ss_manual.*` are touched, so a picture from anywhere else is safe. A
# swapped file's name gains its region. The old file goes only after the new
# one is saved and recorded.
#
# ScreenScraper is asked only where a file may be wrong, and once per game:
# `games.ss_region_checked` marks a game whose files are settled, and a game
# first scraped after this job first ran was scraped by region already, so it
# is marked without asking.
# =============================================================================

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import config
from scraper import service_limits
from scraper.metadata_merger import (
    _download_and_finalize, _MEDIA_EXTS, download_ss_media, load_scraper_settings,
)
from scraper.scrape_screenscraper import get_game_by_id, get_system_id
from scraper.ss_regions import by_region, own_region
from services.database import query
from services.game_media_service import remove_media_file
from services.image_utils import preferred_image_extension
from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)

# (column, ScreenScraper types, media folder, name stem, default format)
_KINDS = (
    ('boxart', ('box-2D', 'boite-2D'), 'boxart', 'ss_boxart', 'png'),
    ('boxart_3d', ('box-3D',), 'boxart_3d', 'ss_boxart3d', 'png'),
    ('manual', ('manuel',), 'manuals', 'ss_manual', 'pdf'),
)

# Every manual stored so far begins with one of these. A refused media request
# is answered with a short text such as NOMEDIA, which must not replace a manual.
_MANUAL_MAGIC = (b'%PDF', b'PK', b'Rar!', b'7z')


def _is_old_name(filename, stem):
    """True for the name a pre-repair scrape gave this kind of file."""
    return bool(filename) and re.search(rf'_{stem}\.[^./]+$', filename) is not None


def _new_name(game_id, stem, column, chosen, default_ext):
    """The file name for a swapped file; region and format come off the wire."""
    region = re.sub(r'[^a-z0-9]', '', (chosen.get('region') or '').lower()) or 'any'
    ext = str(chosen.get('format') or '').lower()
    ext = ext if ext in _MEDIA_EXTS else default_ext
    suffix = f'.{ext}' if column == 'manual' else preferred_image_extension(column, f'.{ext}')
    return f'{game_id}_{stem}_{region}{suffix}'


def _swapped_region(filename, stem):
    """The region code a swapped file's name carries, else None."""
    match = re.search(rf'_{stem}_([a-z0-9]+)\.[^./]+$', filename or '')
    return match.group(1) if match else None


def swapped_games():
    """Every game holding a file this job swapped, by console then title.

    Each row has `changes`, a list of (column, region code). The old file is
    gone, so only the new region is known.
    """
    rows = query("""
        SELECT g.id, g.title, g.region, g.boxart, g.boxart_3d, g.manual,
               s.name AS system_name
        FROM games g JOIN systems s ON g.system_id = s.id
        WHERE g.boxart GLOB '*_ss_boxart_*' OR g.boxart_3d GLOB '*_ss_boxart3d_*'
           OR g.manual GLOB '*_ss_manual_*'
        ORDER BY s.name COLLATE NOCASE, COALESCE(g.sort_title, g.title) COLLATE NOCASE
    """)
    games = []
    for row in rows:
        changes = [(column, _swapped_region(row[column], stem))
                   for column, _t, _d, stem, _e in _KINDS]
        changes = [(column, code) for column, code in changes if code]
        if changes:
            games.append({**dict(row), 'changes': changes})
    return games


def _first_scrape(history):
    """When the game's earliest history entry was written, else None."""
    try:
        stamps = [e.get('timestamp') for e in json.loads(history or '[]')
                  if isinstance(e, dict) and e.get('timestamp')]
        return min(datetime.fromisoformat(t) for t in stamps) if stamps else None
    except (TypeError, ValueError):
        return None


def _region_aware_since(conn):
    """The earliest moment this install surely chose boxes by region.

    This job shipped with region-aware scraping, so its first recorded run
    proves it. History entries hold local time without a zone, so the answer
    does too. Job history is pruned, so a later answer only means more asking.
    """
    row = conn.execute(
        "SELECT MIN(created_at) FROM job_queue WHERE job_type = 'ss_region_repair'"
    ).fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0]).astimezone().replace(tzinfo=None)
    return datetime.now()


def _fetch(chosen, path, column):
    """Download a chosen entry to `path`; True only for a usable file."""
    if column != 'manual':
        return _download_and_finalize(chosen['url'], path, column)
    if not download_ss_media(chosen['url'], path, timeout=60):
        return False
    with open(path, 'rb') as f:
        return f.read(4).startswith(_MANUAL_MAGIC)


class SsRegionRepairJob:
    """Swap ScreenScraper boxes and manuals that came from the wrong region."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.paused = False
        self.current_index = 0
        self.total_games = 0
        self.replaced_count = 0
        self.no_match_count = 0
        self.failed_count = 0
        self.current_game = ""
        self.start_time = None
        self.error_message = None

    def start(self):
        """Start the repair. On refusal `error` is a code the route words."""
        keys = load_scraper_settings().get('api_keys', {})
        if not (keys.get('screenscraper_username') and keys.get('screenscraper_password')):
            return {'success': False, 'error': 'no_account'}
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'already_running'}
            singleton_fd = acquire_job_singleton_lock('ss_region_repair')
            if singleton_fd is None:
                return {'success': False, 'error': 'already_running'}
            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"ss_region_repair_{int(time.time())}"
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

        self._thread = threading.Thread(target=self._worker, args=(keys,), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                self.paused = False  # so the waiting loop sees the stop
                return {'success': True}
            return {'success': False, 'error': 'not_running'}

    def pause(self):
        """Hold the run after the game it is on, until resumed or stopped."""
        with self._lock:
            if self.running and not self.completed:
                self.paused = True
                return {'success': True}
            return {'success': False, 'error': 'not_running'}

    def resume(self):
        with self._lock:
            if self.running and self.paused:
                self.paused = False
                return {'success': True}
            return {'success': False, 'error': 'not_paused'}

    def _wait_while_paused(self):
        while True:
            with self._lock:
                if not self.paused or self.cancelled:
                    return
            if shutdown_requested.wait(0.5):
                return

    def get_status(self):
        with self._lock:
            percent = int(self.current_index / self.total_games * 100) if self.total_games else 0
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'paused': self.paused,
                'current': self.current_index,
                'total': self.total_games,
                'percent': percent,
                'replaced': self.replaced_count,
                'no_match': self.no_match_count,
                'failed': self.failed_count,
                'current_game': self.current_game,
                'error': self.error_message,
            }

    def _candidates(self):
        """Games holding an old-named file that may be from the wrong region.

        Marks, without asking ScreenScraper, each game first scraped after
        region-aware scraping began, and returns the rest.
        """
        conn = _get_conn()
        try:
            rows = conn.execute("""
                SELECT g.id, g.title, g.rom_path, g.region, g.screenscraper_id,
                       g.boxart, g.boxart_3d, g.manual, g.scrape_history,
                       s.folder AS system_folder
                FROM games g JOIN systems s ON g.system_id = s.id
                WHERE g.screenscraper_id IS NOT NULL AND g.ss_region_checked = 0
                ORDER BY g.id
            """).fetchall()
            since = _region_aware_since(conn)
            games, settled = [], []
            for row in rows:
                if not any(_is_old_name(row[column], stem) for column, _t, _d, stem, _e in _KINDS):
                    continue
                first = _first_scrape(row['scrape_history'])
                if first and first >= since:
                    settled.append((row['id'],))
                else:
                    games.append(dict(row))
            if settled:
                conn.executemany("UPDATE games SET ss_region_checked = 1 WHERE id = ?", settled)
                _commit_with_retry(conn)
        finally:
            conn.close()
        return games

    def _repair_kind(self, conn, game, record, kind):
        """Swap one file if a nearer region exists. True when a file changed."""
        column, types, folder, stem, default_ext = kind
        old = game[column]
        if not _is_old_name(old, stem):
            return False
        listed = [m for m in record.get('medias') or []
                  if m.get('type') in types and m.get('url')]
        ordered = by_region(listed, own_region(game))
        # The first listed is what the old scrape took, so that file is right.
        if not ordered or ordered[0] is listed[0]:
            return False

        name = _new_name(game['id'], stem, column, ordered[0], default_ext)
        path = os.path.join(config.IMAGE_PATH, folder, name)
        if not _fetch(ordered[0], path, column):
            if os.path.exists(path):
                os.remove(path)
            raise RuntimeError(f'{column} download failed')

        # The old-value check keeps an edit made during the download.
        changed = conn.execute(
            f"UPDATE games SET {column} = ? WHERE id = ? AND {column} = ?",
            (name, game['id'], old),
        ).rowcount
        _commit_with_retry(conn)
        remove_media_file(old if changed else name, folder)
        return bool(changed)

    def _repair_game(self, conn, game, keys):
        """Look one game up by its ScreenScraper id and repair it."""
        record = get_game_by_id(
            game['screenscraper_id'],
            keys['screenscraper_username'], keys['screenscraper_password'],
            keys.get('screenscraper_devid', ''), keys.get('screenscraper_devpassword', ''),
            system_id=get_system_id(game['system_folder']),
        )
        if not record or str(record.get('id')) != str(game['screenscraper_id']):
            # A lookup cut short by the day's limit says nothing about the game.
            if not service_limits.stopped(service_limits.SCREENSCRAPER):
                with self._lock:
                    self.no_match_count += 1
            return
        settled = True
        for kind in _KINDS:
            try:
                changed = self._repair_kind(conn, game, record, kind)
            except Exception as e:
                logger.warning(f"Region repair: game {game['id']}: {e}")
                settled = False
                with self._lock:
                    self.failed_count += 1
                continue
            if changed:
                with self._lock:
                    self.replaced_count += 1
        if settled:
            conn.execute("UPDATE games SET ss_region_checked = 1 WHERE id = ?", (game['id'],))
            _commit_with_retry(conn)

    def _worker(self, keys):
        persist_id = None
        try:
            games = self._candidates()
            with self._lock:
                self.total_games = len(games)
            persist_id = persist_job_start('ss_region_repair', {'total': len(games)})

            conn = _get_conn()
            last_persist = time.time()
            try:
                for i, game in enumerate(games):
                    self._wait_while_paused()
                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_index = i + 1
                        self.current_game = game['title']
                    if not get_system_id(game['system_folder']):
                        continue

                    # A snapshot, then the write outside the lock (Pass 41.6.B).
                    if time.time() - last_persist >= 15:
                        with self._lock:
                            progress = {
                                'current': i + 1, 'total': len(games),
                                'updated': self.replaced_count,
                                'failed': self.failed_count,
                                'current_item': self.current_game,
                            }
                        persist_job_progress(persist_id, progress)
                        last_persist = time.time()

                    try:
                        self._repair_game(conn, game, keys)
                    except Exception as e:
                        # One game's error, such as the network dropping,
                        # is that game's failure, not the run's (PASS-59-243).
                        logger.warning(f"Region repair: {game['title']} failed: {e}")
                        with self._lock:
                            self.failed_count += 1
                    if service_limits.stopped(service_limits.SCREENSCRAPER):
                        break
            finally:
                conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                final_status = resolve_terminal_status(self.cancelled)
                logger.info(
                    f"Region repair done: {self.replaced_count} files swapped, "
                    f"{self.no_match_count} games not found, {self.failed_count} failed"
                )
            release_singleton_fd(self)
            persist_job_complete(persist_id, status=final_status)

        except Exception as e:
            logger.error(f"Region repair error: {e}", exc_info=True)
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
