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
# swapped file's name gains its region, which also marks it as done for a later
# run. The old file goes only after the new one is saved and recorded.
# =============================================================================

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import config
from scraper.metadata_merger import (
    _download_and_finalize, _MEDIA_EXTS, download_ss_media, load_scraper_settings,
)
from scraper.scrape_screenscraper import get_system_id, search_game
from scraper.ss_regions import by_region, own_region
from services.game_media_service import remove_media_file
from services.image_utils import preferred_image_extension
from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)

# (column, ScreenScraper types, media folder, name stem, default format)
_KINDS = (
    ('boxart', ('box-2D', 'boite-2D'), 'boxart', 'ss_boxart', 'png'),
    ('boxart_3d', ('box-3D',), 'boxart_3d', 'ss_boxart3d', 'png'),
    ('manual', ('manuel',), 'manuals', 'ss_manual', 'pdf'),
)

# ScreenScraper's daily limit reply looks like "not found" until PASS-59-215,
# so this many silent searches in a row ends the run instead of spending more.
MAX_SILENT_IN_A_ROW = 25
PACE_SECONDS = 1.0

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
        self.current_index = 0
        self.total_games = 0
        self.replaced_count = 0
        self.no_match_count = 0
        self.failed_count = 0
        self.stopped_no_reply = False
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
                return {'success': True}
            return {'success': False, 'error': 'not_running'}

    def get_status(self):
        with self._lock:
            percent = int(self.current_index / self.total_games * 100) if self.total_games else 0
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'current': self.current_index,
                'total': self.total_games,
                'percent': percent,
                'replaced': self.replaced_count,
                'no_match': self.no_match_count,
                'failed': self.failed_count,
                'stopped_no_reply': self.stopped_no_reply,
                'current_game': self.current_game,
                'error': self.error_message,
            }

    def _candidates(self):
        """Games holding an old-named file and a known ScreenScraper id."""
        conn = _get_conn()
        try:
            rows = conn.execute("""
                SELECT g.id, g.title, g.rom_path, g.region, g.screenscraper_id,
                       g.boxart, g.boxart_3d, g.manual, s.folder AS system_folder
                FROM games g JOIN systems s ON g.system_id = s.id
                WHERE g.screenscraper_id IS NOT NULL
                ORDER BY g.id
            """).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows
                if any(_is_old_name(r[column], stem) for column, _t, _d, stem, _e in _KINDS)]

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
        """Look one game up and repair it. Returns False on a silent search."""
        results = search_game(
            game['title'], game['system_folder'],
            keys['screenscraper_username'], keys['screenscraper_password'],
            keys.get('screenscraper_devid', ''), keys.get('screenscraper_devpassword', ''),
        )
        if not results:
            with self._lock:
                self.no_match_count += 1
            return False
        wanted = str(game['screenscraper_id'])
        record = next((r for r in results if str(r.get('id')) == wanted), None)
        if record is None:
            with self._lock:
                self.no_match_count += 1
            return True
        for kind in _KINDS:
            try:
                changed = self._repair_kind(conn, game, record, kind)
            except Exception as e:
                logger.warning(f"Region repair: game {game['id']}: {e}")
                with self._lock:
                    self.failed_count += 1
                continue
            if changed:
                with self._lock:
                    self.replaced_count += 1
        return True

    def _worker(self, keys):
        persist_id = None
        try:
            games = self._candidates()
            with self._lock:
                self.total_games = len(games)
            persist_id = persist_job_start('ss_region_repair', {'total': len(games)})

            conn = _get_conn()
            last_persist = time.time()
            silent = 0
            try:
                for i, game in enumerate(games):
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

                    if self._repair_game(conn, game, keys):
                        silent = 0
                    else:
                        silent += 1
                        if silent >= MAX_SILENT_IN_A_ROW:
                            with self._lock:
                                self.stopped_no_reply = True
                            break
                    time.sleep(PACE_SECONDS)
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
