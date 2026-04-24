# =============================================================================
# RETRODB - Platform Achievement Sync Job Manager
# =============================================================================
# Background sync of Steam and Xbox achievement progress data.
# =============================================================================

import threading
import time
import logging
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status,
)

logger = logging.getLogger(__name__)


def _get_steam_credentials(user_id=None):
    """Return (steam_api_key, steam_id) for the caller.

    Pass 31.4 — credentials now live in user_settings, keyed by user_id.
    When `user_id` is supplied we read directly from there. The legacy
    fallback to data/scraper_settings.json stays in place for installs that
    haven't migrated their scraper config yet, so a pre-31 admin can still
    run a sync while they move their keys to their profile.
    """
    if user_id is not None:
        try:
            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT steam_api_key, steam_id FROM user_settings "
                    "WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if row:
                    key = (row['steam_api_key'] or '') if hasattr(row, 'keys') else (row[0] or '')
                    sid = (row['steam_id'] or '') if hasattr(row, 'keys') else (row[1] or '')
                    if key and sid:
                        return key, sid
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not load per-user Steam credentials: {e}")

    import os, json
    settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'data', 'scraper_settings.json')
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                keys = settings.get('api_keys', {})
                return keys.get('steam_api_key', ''), keys.get('steam_id', '')
    except Exception as e:
        logger.warning(f"Could not load Steam credentials: {e}")
    return '', ''


def _get_xbox_credentials():
    """Get Xbox API credentials from scraper settings."""
    import os, json
    settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'data', 'scraper_settings.json')
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                settings = json.load(f)
                keys = settings.get('api_keys', {})
                return keys.get('xbox_client_id', ''), keys.get('xbox_client_secret', '')
    except Exception as e:
        logger.warning(f"Could not load Xbox credentials: {e}")
    return '', ''


def _upsert_steam_achievements(cursor, game_id, app_id, api_key, player_result, user_id):
    """Upsert individual Steam achievements for a game (Pass 31.2 — per user).

    Merges player progress with achievement schema (for icons).
    Returns the number of rows upserted.
    """
    from scraper.scrape_steam import get_achievement_schema

    achievements = player_result.get('achievements', [])
    if not achievements:
        return 0

    # Build schema lookup for icons
    schema_map = {}
    try:
        schema = get_achievement_schema(api_key, app_id)
        for s in schema:
            schema_map[s.get('name', '')] = s
    except Exception as e:
        logger.warning(f"Could not fetch schema for app {app_id}: {e}")

    count = 0
    for ach in achievements:
        apiname = ach.get('apiname', '')
        if not apiname:
            continue
        schema_entry = schema_map.get(apiname, {})
        cursor.execute("""
            INSERT INTO steam_achievements
                (game_id, user_id, apiname, name, description, icon_url, icon_locked_url, achieved, unlock_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, apiname, user_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                icon_url = excluded.icon_url,
                icon_locked_url = excluded.icon_locked_url,
                achieved = excluded.achieved,
                unlock_time = excluded.unlock_time
        """, (
            game_id,
            user_id,
            apiname,
            schema_entry.get('displayName', ach.get('name', apiname)),
            schema_entry.get('description', ach.get('description', '')),
            schema_entry.get('icon', ''),
            schema_entry.get('icongray', ''),
            1 if ach.get('achieved') else 0,
            ach.get('unlocktime', 0),
        ))
        count += 1
    return count


def _upsert_xbox_achievements(cursor, game_id, achievements, user_id):
    """Upsert individual Xbox achievements for a game (Pass 31.2 — per user).

    Returns the number of rows upserted.
    """
    count = 0
    for ach in achievements:
        ach_id = str(ach.get('id', ''))
        if not ach_id:
            continue

        name = ach.get('name', '')
        description = ach.get('description', '')
        achieved = 1 if ach.get('progressState') == 'Achieved' else 0
        unlock_time = ach.get('progression', {}).get('timeUnlocked', '') or ''

        # Extract gamerscore from rewards
        gamerscore = 0
        for reward in ach.get('rewards', []):
            if reward.get('type') == 'Gamerscore':
                try:
                    gamerscore = int(reward.get('value', 0))
                except (ValueError, TypeError):
                    pass

        # Extract icon URLs from mediaAssets
        icon_url = ''
        icon_locked_url = ''
        for asset in ach.get('mediaAssets', []):
            if asset.get('type') == 'Icon':
                icon_url = asset.get('url', '')
            elif asset.get('type') == 'LockedIcon':
                icon_locked_url = asset.get('url', '')

        cursor.execute("""
            INSERT INTO xbox_achievements
                (game_id, user_id, achievement_id, name, description, icon_url, icon_locked_url,
                 gamerscore, achieved, unlock_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, achievement_id, user_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                icon_url = excluded.icon_url,
                icon_locked_url = excluded.icon_locked_url,
                gamerscore = excluded.gamerscore,
                achieved = excluded.achieved,
                unlock_time = excluded.unlock_time
        """, (
            game_id, user_id, ach_id, name, description, icon_url, icon_locked_url,
            gamerscore, achieved, unlock_time,
        ))
        count += 1
    return count


class SteamSyncJob:
    """Manages Steam achievement sync jobs in background"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.reset()

    def reset(self):
        """Reset job state"""
        self.job_id = None
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
        self._user_id = None  # Pass 31.4 — caller's user_id for credential lookup

    def get_status(self):
        """Get current sync status"""
        with self._lock:
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
                'error': self.error_message,
            }

    def start(self, user_id=None):
        """Start Steam achievement sync for all Steam-imported games.

        Pass 31.4 — `user_id` selects whose stored Steam credentials to use.
        Legacy callers without a user_id fall back to the scraper_settings.json
        keys (single-tenant compat).
        """
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Sync already running'}
            self.reset()
            self.job_id = f"steam_sync_{int(time.time())}"
            self.running = True
            self._user_id = user_id

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
        """Resume Steam sync from persisted params after server restart.

        Uses persisted game_ids, user_id, and progress to continue from where
        it left off. Pre-31 jobs without a user_id fall back to the shared
        scraper_settings.json credentials (single-tenant compat).
        """
        game_ids = params.get('game_ids')
        resume_index = progress.get('current', 0) if progress else 0
        user_id = params.get('user_id')

        if resume_index > 0 and game_ids:
            remaining_ids = game_ids[resume_index:]

            with self._lock:
                if self.running:
                    return False
                self.reset()
                self.job_id = f"steam_sync_{int(time.time())}_resume"
                self._resume_game_ids = [None] * resume_index + remaining_ids
                self.running = True
                self._user_id = user_id
                self.current_index = resume_index
                self.success_count = progress.get('success', 0)
                self.failed_count = progress.get('failed', 0)
                self.skipped_count = progress.get('skipped', 0)

            self._thread = threading.Thread(target=self._run_sync, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed Steam sync: {resume_index}/{len(game_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress data — start from scratch for the originating user.
        result = self.start(user_id=user_id)
        if result.get('success'):
            logger.info("Auto-resumed Steam achievement sync (from start)")
        return result.get('success', False)

    def _run_sync(self):
        """Background sync thread"""
        from scraper.scrape_steam import get_player_achievements, get_achievement_schema

        _last_persist_time = time.time()
        persist_id = None

        try:
            steam_api_key, steam_id = _get_steam_credentials(user_id=self._user_id)
            if not steam_api_key or not steam_id:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "Steam API key or Steam ID not configured"
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
                        SELECT id, title, steam_app_id FROM games
                        WHERE id IN ({placeholders})
                    """, real_ids)
                    for row in c.fetchall():
                        id_map[row['id']] = dict(row)
                conn.close()

                games = [id_map.get(gid) if gid is not None else None for gid in game_ids]
            else:
                conn = _get_conn()
                c = conn.cursor()
                c.execute("""
                    SELECT id, title, steam_app_id FROM games
                    WHERE steam_app_id IS NOT NULL AND steam_app_id != ''
                """)
                games = [dict(row) for row in c.fetchall()]
                conn.close()

            with self._lock:
                self.total_games = len(games)

            # Persist job start for crash recovery (include game IDs + user_id
            # for resume; Pass 31.4 keeps credentials bound to the originating
            # user across restarts).
            persist_id = persist_job_start('steam_sync', {
                'game_ids': [g['id'] if g is not None else None for g in games],
                'user_id': self._user_id,
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "No Steam games found to sync"
                persist_job_complete(persist_id, status='completed', error="No Steam games found")
                return

            sync_conn = _get_conn()
            try:
                sync_cursor = sync_conn.cursor()
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

                    # Persist progress periodically
                    _now = time.time()
                    if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                        if _pending_commits > 0:
                            _commit_with_retry(sync_conn)
                            _pending_commits = 0
                        with self._lock:
                            _progress = {
                                'current': i + 1, 'total': len(games),
                                'success': self.success_count, 'failed': self.failed_count,
                                'skipped': self.skipped_count,
                                'current_item': self.current_game_title,
                            }
                        persist_job_progress(persist_id, _progress)
                        _last_persist_time = _now

                    try:
                        result = get_player_achievements(steam_api_key, steam_id, game['steam_app_id'])
                        if result is None:
                            with self._lock:
                                self.skipped_count += 1
                            continue

                        # Upsert into game_achievement_progress (Pass 31.2 — per user).
                        sync_cursor.execute("""
                            INSERT INTO game_achievement_progress
                                (game_id, user_id, earned_achievements, total_achievements,
                                 completion_percentage, last_synced, steam_app_id, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'steam')
                            ON CONFLICT(game_id, user_id) DO UPDATE SET
                                earned_achievements = excluded.earned_achievements,
                                total_achievements = excluded.total_achievements,
                                completion_percentage = excluded.completion_percentage,
                                last_synced = excluded.last_synced,
                                steam_app_id = excluded.steam_app_id,
                                source = 'steam'
                        """, (
                            game['id'],
                            self._user_id,
                            result['earned'],
                            result['total'],
                            round(result['earned'] / result['total'] * 100, 1) if result['total'] > 0 else 0,
                            datetime.now(timezone.utc).isoformat(),
                            game['steam_app_id'],
                        ))
                        _pending_commits += 1

                        # Save individual achievements
                        _pending_commits += _upsert_steam_achievements(
                            sync_cursor, game['id'], game['steam_app_id'],
                            steam_api_key, result, self._user_id)

                        if _pending_commits >= 3:
                            _commit_with_retry(sync_conn)
                            _pending_commits = 0

                        with self._lock:
                            self.success_count += 1

                    except Exception as e:
                        logger.error(f"Error syncing Steam achievements for game {game['id']}: {e}")
                        try:
                            sync_conn.rollback()
                        except Exception:
                            pass
                        _pending_commits = 0
                        with self._lock:
                            self.failed_count += 1

                    # Rate limit: 1 request per second
                    time.sleep(1.0)

                if _pending_commits > 0:
                    _commit_with_retry(sync_conn)
            finally:
                sync_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                _final_status = resolve_terminal_status(self.cancelled)

            if persist_id:
                persist_job_complete(persist_id, status=_final_status)

        except Exception as e:
            logger.error(f"Steam sync error: {e}")
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))


class XboxSyncJob:
    """Manages Xbox achievement sync jobs in background.

    Pass 27.3 — OAuth refresh tokens live in `user_platform_tokens` keyed by
    user_id (Pass 27.2), so the job must know whose tokens to authenticate
    with. `start(user_id=…)` captures that at dispatch time and the worker
    thread reaches back through `self.user_id`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.reset()

    def reset(self):
        """Reset job state"""
        self.job_id = None
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
        self.user_id = None  # Pass 27.3 — whose Xbox tokens to authenticate with

    def get_status(self):
        """Get current sync status"""
        with self._lock:
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
                'error': self.error_message,
            }

    def start(self, user_id=None):
        """Start Xbox achievement sync for all Xbox-imported games.

        Args:
            user_id: RetroDB users.id whose Xbox OAuth tokens authenticate
                the XBL/XSTS handshake (Pass 27.3). Required for new starts;
                resume paths read it back from persisted params.
        """
        if not user_id:
            return {'success': False, 'error': 'user_id required for Xbox sync'}
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Sync already running'}
            self.reset()
            self.job_id = f"xbox_sync_{int(time.time())}"
            self.user_id = user_id
            self.running = True

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
        """Resume Xbox sync from persisted params after server restart.

        Uses persisted game_ids and progress to continue from where it left off,
        prepending None placeholders for already-processed items and restoring counts.

        `params['user_id']` is the owner whose tokens to authenticate with
        (persisted by `persist_job_start` in `_run_sync`). Pre-Pass-27
        snapshots predate the field; those are dropped rather than
        resumed-under-admin because tokens may have rotated or been
        disconnected since the snapshot was taken.
        """
        game_ids = params.get('game_ids')
        user_id = params.get('user_id')
        resume_index = progress.get('current', 0) if progress else 0

        if not user_id:
            logger.info("Xbox sync resume skipped: params missing user_id (pre-Pass-27 snapshot)")
            return False

        if resume_index > 0 and game_ids:
            remaining_ids = game_ids[resume_index:]

            with self._lock:
                if self.running:
                    return False
                self.reset()
                self.job_id = f"xbox_sync_{int(time.time())}_resume"
                self.user_id = user_id
                self._resume_game_ids = [None] * resume_index + remaining_ids
                self.running = True
                self.current_index = resume_index
                self.success_count = progress.get('success', 0)
                self.failed_count = progress.get('failed', 0)
                self.skipped_count = progress.get('skipped', 0)

            self._thread = threading.Thread(target=self._run_sync, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed Xbox sync: {resume_index}/{len(game_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress data — start from scratch using the persisted user_id.
        result = self.start(user_id=user_id)
        if result.get('success'):
            logger.info("Auto-resumed Xbox achievement sync (from start)")
        return result.get('success', False)

    def _run_sync(self):
        """Background sync thread"""
        from scraper.scrape_xbox import get_authenticated_session, get_achievements

        _last_persist_time = time.time()
        persist_id = None

        try:
            xbox_client_id, xbox_client_secret = _get_xbox_credentials()
            if not xbox_client_id or not xbox_client_secret:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "Xbox credentials not configured"
                return

            session = get_authenticated_session(xbox_client_id, xbox_client_secret, self.user_id)
            if not session:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "Xbox authentication failed — please re-connect your Xbox account"
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
                        SELECT id, title, xbox_title_id FROM games
                        WHERE id IN ({placeholders})
                    """, real_ids)
                    for row in c.fetchall():
                        id_map[row['id']] = dict(row)
                conn.close()

                games = [id_map.get(gid) if gid is not None else None for gid in game_ids]
            else:
                conn = _get_conn()
                c = conn.cursor()
                c.execute("""
                    SELECT id, title, xbox_title_id FROM games
                    WHERE xbox_title_id IS NOT NULL AND xbox_title_id != ''
                """)
                games = [dict(row) for row in c.fetchall()]
                conn.close()

            with self._lock:
                self.total_games = len(games)

            # Persist job start for crash recovery (include game IDs for
            # resume plus the owner whose tokens kicked off this sync — Pass
            # 27.3 — so resume_from_params can re-authenticate as the right
            # user rather than silently defaulting to admin).
            persist_id = persist_job_start('xbox_sync', {
                'game_ids': [g['id'] if g is not None else None for g in games],
                'user_id': self.user_id,
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "No Xbox games found to sync"
                persist_job_complete(persist_id, status='completed', error="No Xbox games found")
                return

            sync_conn = _get_conn()
            try:
                sync_cursor = sync_conn.cursor()
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

                    _now = time.time()
                    if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                        if _pending_commits > 0:
                            _commit_with_retry(sync_conn)
                            _pending_commits = 0
                        with self._lock:
                            _progress = {
                                'current': i + 1, 'total': len(games),
                                'success': self.success_count, 'failed': self.failed_count,
                                'skipped': self.skipped_count,
                                'current_item': self.current_game_title,
                            }
                        persist_job_progress(persist_id, _progress)
                        _last_persist_time = _now

                    try:
                        result = get_achievements(
                            session['auth_header'], session['xuid'], game['xbox_title_id'])

                        if result is None:
                            with self._lock:
                                self.skipped_count += 1
                            continue

                        sync_cursor.execute("""
                            INSERT INTO game_achievement_progress
                                (game_id, user_id, earned_achievements, total_achievements,
                                 completion_percentage, last_synced, xbox_title_id, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'xbox')
                            ON CONFLICT(game_id, user_id) DO UPDATE SET
                                earned_achievements = excluded.earned_achievements,
                                total_achievements = excluded.total_achievements,
                                completion_percentage = excluded.completion_percentage,
                                last_synced = excluded.last_synced,
                                xbox_title_id = excluded.xbox_title_id,
                                source = 'xbox'
                        """, (
                            game['id'],
                            self.user_id,
                            result['earned'],
                            result['total'],
                            round(result['earned'] / result['total'] * 100, 1) if result['total'] > 0 else 0,
                            datetime.now(timezone.utc).isoformat(),
                            game['xbox_title_id'],
                        ))
                        _pending_commits += 1

                        # Save individual achievements
                        _pending_commits += _upsert_xbox_achievements(
                            sync_cursor, game['id'], result.get('achievements', []), self.user_id)

                        if _pending_commits >= 3:
                            _commit_with_retry(sync_conn)
                            _pending_commits = 0

                        with self._lock:
                            self.success_count += 1

                    except Exception as e:
                        logger.error(f"Error syncing Xbox achievements for game {game['id']}: {e}")
                        try:
                            sync_conn.rollback()
                        except Exception:
                            pass
                        _pending_commits = 0
                        with self._lock:
                            self.failed_count += 1

                    time.sleep(0.5)

                if _pending_commits > 0:
                    _commit_with_retry(sync_conn)
            finally:
                sync_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                _final_status = resolve_terminal_status(self.cancelled)

            if persist_id:
                persist_job_complete(persist_id, status=_final_status)

        except Exception as e:
            logger.error(f"Xbox sync error: {e}")
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
