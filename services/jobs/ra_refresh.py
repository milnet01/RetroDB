# =============================================================================
# RETRODB - RA Refresh Job (Scan for RetroAchievements Support)
# =============================================================================
# Background job for scanning games to check if they have RetroAchievements.
# =============================================================================

import threading
import time
import logging

from services.achievement_linking import match_ra_game
from services.jobs.base import (
    _get_conn, _commit_with_retry, _get_ra_credentials,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
    pad_resume_game_ids, restore_progress_counts,
    try_acquire_singleton_or_warn,
)

logger = logging.getLogger(__name__)


class RARefreshJob:
    """Background job for scanning games to check if they have RetroAchievements"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset job state"""
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.system_id = None
        self.system_name = None
        self.current_index = 0
        self.total_games = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.current_game_title = ""
        self.current_system_name = ""
        self.error_message = None
        self._resume_game_ids = None  # Set by resume_from_params for proper resume

    def get_status(self):
        """Get current job status"""
        with self._lock:
            # Calculate percent for toast progress bar
            percent = int((self.current_index / self.total_games * 100)) if self.total_games > 0 else 0

            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'current': self.current_index,
                'total': self.total_games,
                'percent': percent,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'current_game': self.current_game_title,
                'current_system': self.current_system_name,
                'system_name': self.system_name or 'All Systems',
                'error': self.error_message
            }

    def start(self, system_id=None):
        """Start RA refresh scan"""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Refresh already running'}

            singleton_fd = acquire_job_singleton_lock('ra_refresh')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'RA refresh is already running on another worker process.',
                }

            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"ra_refresh_{int(time.time())}"
            self.system_id = system_id
            self.running = True

        # Start background thread
        self._thread = threading.Thread(target=self._run_refresh, daemon=True)
        self._thread.start()

        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        """Cancel the refresh"""
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running refresh to cancel'}

    def resume_from_params(self, params, progress=None):
        """Resume RA refresh from persisted params after server restart.

        Uses persisted game_ids and progress to continue from where it left off,
        prepending None placeholders for already-processed items and restoring counts.
        """
        system_id = params.get('system_id')  # None = all systems
        game_ids = params.get('game_ids')
        resume_index = progress.get('current', 0) if progress else 0

        if resume_index > 0 and game_ids:
            remaining_ids = game_ids[resume_index:]
            system_name = params.get('system_name', 'All Systems')

            with self._lock:
                if self.running:
                    return False
                singleton_fd = try_acquire_singleton_or_warn('ra_refresh')
                if singleton_fd is None:
                    return False
                self.reset()
                self._singleton_fd = singleton_fd
                self.job_id = f"ra_refresh_{int(time.time())}_resume"
                self.system_id = system_id
                self.system_name = system_name
                self._resume_game_ids = pad_resume_game_ids(resume_index, remaining_ids)
                self.running = True
                restore_progress_counts(self, resume_index, progress)

            self._thread = threading.Thread(target=self._run_refresh, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed RA refresh: {resume_index}/{len(game_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress data — start from scratch
        result = self.start(system_id=system_id)
        if result.get('success'):
            logger.info(f"Auto-resumed RA refresh (system_id={system_id}, from start)")
        return result.get('success', False)

    def _run_refresh(self):
        """Background refresh thread"""
        import requests

        _last_persist_time = time.time()
        persist_id = None

        try:
            # Get RA credentials
            ra_username, ra_api_key = _get_ra_credentials()

            if not ra_api_key or not ra_username:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "RA API key or username not configured"
                release_singleton_fd(self)
                return

            # Import RA console mapping
            try:
                from scraper.retroachievements import RA_CONSOLE_MAP
            except ImportError:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "RetroAchievements scraper not available"
                release_singleton_fd(self)
                return

            # Use pre-set game IDs from resume, or query from DB
            if self._resume_game_ids is not None:
                game_ids = self._resume_game_ids
                self._resume_game_ids = None

                # Fetch full game rows for non-None IDs
                conn = _get_conn()
                c = conn.cursor()
                id_map = {}
                real_ids = [gid for gid in game_ids if gid is not None]
                if real_ids:
                    placeholders = ','.join('?' * len(real_ids))
                    c.execute(f"""
                        SELECT g.id, g.title, g.rom_path, s.folder as system_folder, s.name as system_name
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.id IN ({placeholders})
                    """, real_ids)
                    for row in c.fetchall():
                        g = dict(row)
                        folder = g['system_folder'].lower() if g['system_folder'] else ''
                        if folder in RA_CONSOLE_MAP:
                            g['ra_console_id'] = RA_CONSOLE_MAP[folder]
                        id_map[g['id']] = g
                conn.close()

                # Build games list preserving None placeholders
                games = [id_map.get(gid) if gid is not None else None for gid in game_ids]
            else:
                # Build query - get games with system folder for RA_CONSOLE_MAP lookup
                conn = _get_conn()
                c = conn.cursor()

                if self.system_id:
                    # Get system name for status display
                    c.execute("SELECT name FROM systems WHERE id = ?", (self.system_id,))
                    row = c.fetchone()
                    with self._lock:
                        self.system_name = row['name'] if row else 'Unknown'

                    c.execute("""
                        SELECT g.id, g.title, g.rom_path, s.folder as system_folder, s.name as system_name
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.system_id = ?
                          AND g.rom_path NOT LIKE 'clz_import/%'
                    """, (self.system_id,))
                else:
                    with self._lock:
                        self.system_name = 'All Systems'
                    c.execute("""
                        SELECT g.id, g.title, g.rom_path, s.folder as system_folder, s.name as system_name
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.rom_path NOT LIKE 'clz_import/%'
                    """)

                all_games = c.fetchall()
                conn.close()

                # Filter to only games on RA-supported systems
                games = []
                for g in all_games:
                    folder = g['system_folder'].lower() if g['system_folder'] else ''
                    if folder in RA_CONSOLE_MAP:
                        games.append(dict(g))
                        games[-1]['ra_console_id'] = RA_CONSOLE_MAP[folder]

            with self._lock:
                self.total_games = len(games)

            # Persist job start for crash recovery (include game IDs for resume)
            persist_id = persist_job_start('ra_refresh', {
                'system_id': self.system_id,
                'system_name': self.system_name,
                'game_ids': [g['id'] if g is not None else None for g in games]
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='completed')
                return

            # Cache for RA game lists by console
            ra_console_cache = {}

            # Open a single write connection for all updates (reduces lock contention)
            write_conn = _get_conn()
            try:
                for i, game in enumerate(games):
                    # Skip None placeholders (already-processed items from resume)
                    if game is None:
                        continue

                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_index = i + 1
                        self.current_game_title = game['title']
                        self.current_system_name = game.get('system_name', '')

                    # Persist progress every 10 items or 30 seconds
                    # Commit write_conn first to release write lock before persist
                    # opens its own connection (SQLite allows only one writer at a time)
                    _now = time.time()
                    if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                        _commit_with_retry(write_conn)
                        with self._lock:
                            _progress = {
                                'current': i + 1, 'total': len(games),
                                'success': self.success_count, 'failed': self.failed_count,
                                'skipped': self.skipped_count,
                                'current_item': self.current_game_title
                            }
                        persist_job_progress(persist_id, _progress)
                        _last_persist_time = _now

                    try:
                        console_id = game['ra_console_id']

                        # Fetch console game list if not cached
                        if console_id not in ra_console_cache:
                            url = f"https://retroachievements.org/API/API_GetGameList.php"
                            params = {
                                'z': ra_username,
                                'y': ra_api_key,
                                'i': console_id,
                                'h': 1  # Only games with achievements
                            }

                            response = requests.get(url, params=params, timeout=60)
                            if response.status_code == 200:
                                ra_console_cache[console_id] = response.json()
                            else:
                                ra_console_cache[console_id] = []

                            # Rate limit after fetching console list —
                            # Pass 40.10: shutdown-aware sleep.
                            shutdown_requested.wait(1)

                        ra_games = ra_console_cache.get(console_id, [])

                        rom_name = game['rom_path'].split('/')[-1].rsplit('.', 1)[0] if game['rom_path'] else ''
                        ra_match = match_ra_game(game['title'], rom_name, ra_games)

                        if ra_match:
                            # Update game with RA info
                            write_conn.execute("""
                                UPDATE games SET
                                    ra_game_id = ?,
                                    ra_achievement_count = ?,
                                    has_retroachievements = 1
                                WHERE id = ?
                            """, (ra_match.get('ID'), ra_match.get('NumAchievements', 0), game['id']))

                            with self._lock:
                                self.success_count += 1
                        else:
                            # Mark as no RA support
                            write_conn.execute("UPDATE games SET has_retroachievements = 0 WHERE id = ?", (game['id'],))

                            with self._lock:
                                self.skipped_count += 1

                        # Batch commit every 25 games to reduce write lock frequency
                        if (i + 1) % 25 == 0:
                            _commit_with_retry(write_conn)

                    except Exception as e:
                        logger.error(f"Error checking RA for game {game['id']}: {e}")
                        try:
                            write_conn.rollback()
                        except Exception:
                            pass
                        with self._lock:
                            self.failed_count += 1

                # Final commit for remaining updates
                _commit_with_retry(write_conn)

                # Clean up stale RA entries
                if not self.cancelled:
                    wc = write_conn.cursor()
                    wc.execute("""
                        UPDATE games SET ra_game_id = NULL, has_retroachievements = 0
                        WHERE ra_game_id IS NOT NULL AND has_retroachievements = 0
                    """)
                    cleaned = wc.rowcount
                    _commit_with_retry(write_conn)
                    if cleaned > 0:
                        logger.info(f"RA Refresh: Cleaned {cleaned} stale RA entries")
            finally:
                write_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                _final_status = resolve_terminal_status(self.cancelled)
                logger.info(f"RA Refresh: Completed - Found {self.success_count} games with RA, {self.skipped_count} without, {self.failed_count} errors")
            release_singleton_fd(self)

            if persist_id:
                persist_job_complete(persist_id, status=_final_status)

        except Exception as e:
            logger.error(f"RA Refresh error: {e}")
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
