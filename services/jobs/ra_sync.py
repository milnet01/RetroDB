# =============================================================================
# RETRODB - RetroAchievements Sync Job Manager
# =============================================================================
# Background sync of RetroAchievements user progress data.
# =============================================================================

import threading
import time
import sqlite3
import logging
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, _commit_with_retry, _get_ra_credentials,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
    pad_resume_game_ids, restore_progress_counts,
    try_acquire_singleton_or_warn,
)

logger = logging.getLogger(__name__)


class RASyncJob:
    """Manages RetroAchievements sync jobs in background"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset job state"""
        self.job_id = None
        self.system_id = None
        self.system_name = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.current_index = 0
        self.total_games = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.current_game_title = ""
        self.error_message = None
        self._resume_game_ids = None  # Set by resume_from_params for proper resume
        self._preset_game_ids = None  # Set by start() when caller provides game IDs
        self._user_id = None  # Pass 31.2 — caller for per-user progress rows

    def get_status(self):
        """Get current sync status"""
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
                'system_id': self.system_id,
                'system_name': self.system_name,
                'error': self.error_message
            }

    def start(self, system_id, game_ids=None, system_name=None, user_id=None):
        """Start RA sync for a system (Pass 31.2 — user_id selects whose
        game_achievement_progress rows to upsert)."""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Sync already running'}

            singleton_fd = acquire_job_singleton_lock('ra_sync')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'RA sync is already running on another worker process.',
                }

            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"ra_sync_{int(time.time())}"
            self.system_id = system_id
            self.running = True
            self._user_id = user_id
            if game_ids is not None:
                self._preset_game_ids = game_ids

        # Use provided system name or look it up
        if system_name:
            self.system_name = system_name
        else:
            try:
                conn = _get_conn()
                c = conn.cursor()
                c.execute("SELECT name FROM systems WHERE id = ?", (system_id,))
                row = c.fetchone()
                self.system_name = row[0] if row else 'Unknown System'
                conn.close()
            except sqlite3.Error as e:
                logger.warning(f"Failed to get system name for RA sync: {e}")
                self.system_name = 'Unknown System'

        # Start background thread
        self._thread = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()

        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        """Cancel the sync"""
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running sync to cancel'}

    def resume_from_params(self, params, progress=None):
        """Resume RA sync from persisted params after server restart.

        Uses persisted game_ids and progress to continue from where it left off,
        prepending None placeholders for already-processed items and restoring counts.
        """
        system_id = params.get('system_id')
        if not system_id:
            return False

        game_ids = params.get('game_ids')
        user_id = params.get('user_id')
        resume_index = progress.get('current', 0) if progress else 0

        if resume_index > 0 and game_ids:
            remaining_ids = game_ids[resume_index:]
            system_name = params.get('system_name', 'Unknown System')

            with self._lock:
                if self.running:
                    return False
                singleton_fd = try_acquire_singleton_or_warn('ra_sync')
                if singleton_fd is None:
                    return False
                self.reset()
                self._singleton_fd = singleton_fd
                self.job_id = f"ra_sync_{int(time.time())}_resume"
                self.system_id = system_id
                self.system_name = system_name
                self._user_id = user_id
                self._resume_game_ids = pad_resume_game_ids(resume_index, remaining_ids)
                self.running = True
                restore_progress_counts(self, resume_index, progress)

            self._thread = threading.Thread(target=self._run_sync, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed RA sync for {system_name}: {resume_index}/{len(game_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress data — start from scratch
        result = self.start(system_id, user_id=user_id)
        if result.get('success'):
            logger.info(f"Auto-resumed RA sync for system {system_id} (from start)")
        return result.get('success', False)

    def _run_sync(self):
        """Background sync thread"""
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

            # Use pre-set game IDs from resume, preset from start(), or query from DB
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
                        SELECT id, title, ra_game_id FROM games
                        WHERE id IN ({placeholders})
                    """, real_ids)
                    for row in c.fetchall():
                        id_map[row['id']] = dict(row)
                conn.close()

                # Build games list preserving None placeholders
                games = [id_map.get(gid) if gid is not None else None for gid in game_ids]
            elif self._preset_game_ids is not None:
                preset_ids = self._preset_game_ids
                self._preset_game_ids = None

                conn = _get_conn()
                c = conn.cursor()
                placeholders = ','.join('?' * len(preset_ids))
                c.execute(f"""
                    SELECT id, title, ra_game_id FROM games
                    WHERE id IN ({placeholders}) AND ra_game_id IS NOT NULL AND ra_game_id != ''
                """, preset_ids)
                games = [dict(row) for row in c.fetchall()]
                conn.close()
            else:
                conn = _get_conn()
                c = conn.cursor()
                c.execute("""
                    SELECT id, title, ra_game_id FROM games
                    WHERE system_id = ? AND ra_game_id IS NOT NULL AND ra_game_id != ''
                """, (self.system_id,))
                games = [dict(row) for row in c.fetchall()]
                conn.close()

            with self._lock:
                self.total_games = len(games)

            # Persist job start for crash recovery (include game IDs + user_id
            # for resume; Pass 31.2 binds each upsert to the originating user).
            persist_id = persist_job_start('ra_sync', {
                'system_id': self.system_id,
                'system_name': self.system_name,
                'game_ids': [g['id'] if g is not None else None for g in games],
                'user_id': self._user_id,
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "No games with RA IDs in this system"
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='completed', error="No games with RA IDs in this system")
                return

            # Reuse a single connection for all DB writes, commit every 10 games
            ra_conn = _get_conn()
            try:
                ra_cursor = ra_conn.cursor()
                _pending_commits = 0

                for i, game in enumerate(games):
                    # Skip None placeholders (already-processed items from resume)
                    if game is None:
                        continue

                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_index = i + 1
                        self.current_game_title = game['title']

                    # Persist progress every 10 items or 30 seconds
                    # Commit pending writes first to release write lock before persist
                    # opens its own connection (SQLite allows only one writer at a time)
                    _now = time.time()
                    if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                        if _pending_commits > 0:
                            _commit_with_retry(ra_conn)
                            _pending_commits = 0
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
                        # Fetch user progress from RA API
                        ra_game_id = game['ra_game_id']
                        url = "https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php"
                        params = {
                            'z': ra_username,
                            'y': ra_api_key,
                            'u': ra_username,
                            'g': ra_game_id
                        }

                        response = requests.get(url, params=params, timeout=30)
                        if response.status_code == 200:
                            data = response.json()

                            # Update game with achievement data
                            total_achievements = data.get('NumAchievements', 0)
                            earned = data.get('NumAwardedToUser', 0)
                            now_iso = datetime.now(timezone.utc).isoformat()
                            pct = round(earned / total_achievements * 100, 1) if total_achievements > 0 else 0

                            # Calculate points from individual achievements
                            achievements = data.get('Achievements', {})
                            if isinstance(achievements, dict):
                                achievements = list(achievements.values())
                            else:
                                achievements = list(achievements or [])
                            total_points = sum(int(a.get('Points', 0)) for a in achievements)
                            earned_points = sum(int(a.get('Points', 0)) for a in achievements
                                                if a.get('DateEarned') is not None)

                            # Pass 48.4 — when the API omits the per-achievement
                            # Achievements payload but the game does have
                            # achievements (total_achievements > 0), the points
                            # sums collapse to 0. Skip the points columns on the
                            # UPDATE path so a transient empty payload can't wipe
                            # a previously-synced good value. (A brand-new row
                            # still inserts 0 — there's no prior value to keep.)
                            skip_points = 1 if (not achievements and total_achievements > 0) else 0

                            # Update total count on games table
                            ra_cursor.execute(
                                "UPDATE games SET ra_achievement_count = ? WHERE id = ?",
                                (total_achievements, game['id']))

                            # Upsert into game_achievement_progress (Pass 31.2 — per user).
                            ra_cursor.execute("""
                                INSERT INTO game_achievement_progress
                                    (game_id, user_id, ra_game_id, earned_achievements, total_achievements,
                                     earned_points, total_points, completion_percentage, last_synced, source)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ra')
                                ON CONFLICT(game_id, user_id) DO UPDATE SET
                                    ra_game_id = excluded.ra_game_id,
                                    earned_achievements = excluded.earned_achievements,
                                    total_achievements = excluded.total_achievements,
                                    earned_points = CASE WHEN ? THEN game_achievement_progress.earned_points ELSE excluded.earned_points END,
                                    total_points = CASE WHEN ? THEN game_achievement_progress.total_points ELSE excluded.total_points END,
                                    completion_percentage = excluded.completion_percentage,
                                    last_synced = excluded.last_synced,
                                    source = 'ra'
                            """, (game['id'], self._user_id, game['ra_game_id'], earned, total_achievements,
                                  earned_points, total_points, pct, now_iso, skip_points, skip_points))
                            _pending_commits += 2

                            # Batch commit every 3 successful writes to minimize lock hold time
                            if _pending_commits >= 3:
                                _commit_with_retry(ra_conn)
                                _pending_commits = 0

                            with self._lock:
                                self.success_count += 1
                        else:
                            logger.warning(f"RA API returned {response.status_code} for game {game['id']} (ra_game_id={game['ra_game_id']})")
                            with self._lock:
                                self.failed_count += 1

                    except Exception as e:
                        logger.error(f"Error syncing RA for game {game['id']}: {e}")
                        try:
                            ra_conn.rollback()
                        except Exception:
                            pass
                        _pending_commits = 0
                        with self._lock:
                            self.failed_count += 1

                    # Rate limit — Pass 40.10: shutdown-aware sleep.
                    shutdown_requested.wait(0.5)

                # Flush any remaining uncommitted writes
                if _pending_commits > 0:
                    _commit_with_retry(ra_conn)
            finally:
                ra_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                _final_status = resolve_terminal_status(self.cancelled)
            release_singleton_fd(self)

            if persist_id:
                persist_job_complete(persist_id, status=_final_status)

        except Exception as e:
            logger.error(f"RA Sync error: {e}")
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
