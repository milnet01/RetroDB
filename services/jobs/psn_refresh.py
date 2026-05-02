# =============================================================================
# RETRODB - PSN Trophy Refresh Job
# =============================================================================
# Bulk sync of individual PSN trophy data with rate limiting.
# =============================================================================

import threading
import time
import logging
import requests
from datetime import datetime

from services.jobs.base import (
    _get_conn, _commit_with_retry, _download_psn_trophy_image,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)


class PSNRefreshJob:
    """Background job for syncing individual PSN trophy data with rate limiting"""

    # PSN API rate limit protection: delay between games (seconds)
    RATE_LIMIT_DELAY = 2.5

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset job state"""
        self.job_id = None
        self.npwr_ids = []
        self.running = False
        self.paused = False
        self.completed = False
        self.cancelled = False
        self.current_index = 0
        self.current_game_title = ""
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.current_npwr = None
        self.error_message = None
        self.return_url = None
        self.start_time = None
        # Store user credentials for background thread
        self._npsso = None
        # Pass 31.1 / 31.5 — the user on whose behalf the refresh runs. Every
        # psn_games / psn_trophies write scopes to this id so user B's refresh
        # can't overwrite user A's rows, and resume-from-params refuses to
        # silently pick up someone else's NPSSO.
        self._user_id = None

    def get_status(self):
        """Get current job status"""
        with self._lock:
            total = len(self.npwr_ids)
            processed = self.success_count + self.failed_count + self.skipped_count
            percent = int((processed / total * 100)) if total > 0 else 0

            return {
                'job_id': self.job_id,
                'running': self.running,
                'paused': self.paused,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'current': self.current_index,
                'processed': processed,
                'total': total,
                'percent': percent,
                'current_game': self.current_game_title,
                'current_npwr': self.current_npwr,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'error': self.error_message,
                'return_url': self.return_url
            }

    def start(self, npwr_ids, npsso, return_url=None, user_id=None):
        """Start a new PSN trophy refresh job (Pass 31.1 — user_id required
        to scope every psn_games / psn_trophies write to the caller)."""
        if not npwr_ids:
            return {'success': False, 'error': 'No games to refresh'}

        if not npsso:
            return {'success': False, 'error': 'PSN NPSSO not configured'}

        if not user_id:
            return {'success': False, 'error': 'PSN refresh requires a caller user_id'}

        # Get the first game's title for immediate UI feedback
        first_game_title = None
        if npwr_ids:
            try:
                conn = _get_conn()
                c = conn.cursor()
                c.execute(
                    "SELECT title FROM psn_games WHERE npwr_id = ? AND user_id = ?",
                    (npwr_ids[0], user_id),
                )
                row = c.fetchone()
                if row:
                    first_game_title = row['title']
                conn.close()
            except Exception as e:
                logger.warning(f"Could not fetch first PSN game title: {e}")

        with self._lock:
            if self.running and not self.completed:
                return {'success': False, 'error': 'PSN refresh already running'}

            singleton_fd = acquire_job_singleton_lock('psn_refresh')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'PSN refresh is already running on another worker process.',
                }

            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"psn_refresh_{int(time.time())}"
            self.npwr_ids = npwr_ids
            self._npsso = npsso
            self._user_id = user_id
            self.return_url = return_url
            self.running = True
            self.start_time = datetime.now()
            self.current_game_title = first_game_title or 'Starting...'

        # Start background thread
        self._thread = threading.Thread(target=self._run_refresh, daemon=True)
        self._thread.start()

        return {
            'success': True,
            'job_id': self.job_id,
            'total': len(npwr_ids),
            'first_game': first_game_title
        }

    def pause(self):
        """Pause the current job"""
        with self._lock:
            if self.running and not self.completed:
                self.paused = True
                return {'success': True}
            return {'success': False, 'error': 'No running job to pause'}

    def resume(self):
        """Resume the current job"""
        with self._lock:
            if self.running and self.paused:
                self.paused = False
                return {'success': True}
            return {'success': False, 'error': 'No paused job to resume'}

    def cancel(self):
        """Cancel the current job"""
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                self.paused = False  # Unpause so the loop can exit
                return {'success': True}
            return {'success': False, 'error': 'No running job to cancel'}

    def resume_from_params(self, params, progress=None):
        """Resume PSN refresh from persisted params after server restart.

        Uses persisted npwr_ids, user_id, and progress to continue from where
        it left off.  Pass 31.5 — refuses to resume if the originating user is
        missing from the params (pre-31 jobs) or no longer has an NPSSO
        configured.  Picking an NPSSO from any user row (the old "first
        configured user wins" behavior) would silently resume user A's job
        under user B's credentials, which is exactly the cross-user leak
        this pass fixes.
        """
        npwr_ids = params.get('npwr_ids', [])
        if not npwr_ids:
            return False

        user_id = params.get('user_id')
        if not user_id:
            logger.warning(
                "Cannot auto-resume PSN refresh: job params predate Pass 31.5 "
                "(no user_id). Rerunning the sync manually re-binds it."
            )
            return False

        # Pass 31.5 — fetch the ORIGINATING user's NPSSO, not the first user
        # who happens to have one configured.
        try:
            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT psn_npsso FROM user_settings "
                    "WHERE user_id = ? AND psn_npsso IS NOT NULL AND psn_npsso != ''",
                    (user_id,),
                ).fetchone()
                npsso = row['psn_npsso'] if row else ''
            finally:
                conn.close()
        except Exception:
            npsso = ''

        if not npsso:
            logger.warning(
                "Cannot auto-resume PSN refresh for user_id=%s: NPSSO no "
                "longer configured for that user (user may have been removed "
                "or rotated credentials).",
                user_id,
            )
            return False

        resume_index = progress.get('current', 0) if progress else 0
        return_url = params.get('return_url')

        if resume_index > 0:
            # Proper resume: prepend None placeholders for already-processed items
            remaining_ids = npwr_ids[resume_index:]

            with self._lock:
                if self.running and not self.completed:
                    return False

                singleton_fd = acquire_job_singleton_lock('psn_refresh')
                if singleton_fd is None:
                    logger.warning(
                        "PSN refresh resume refused: lock held by another worker process"
                    )
                    return False

                self.reset()
                self._singleton_fd = singleton_fd
                self.job_id = f"psn_refresh_{int(time.time())}_resume"
                self.npwr_ids = [None] * resume_index + remaining_ids
                self._npsso = npsso
                self._user_id = user_id
                self.return_url = return_url
                self.running = True
                self.start_time = datetime.now()
                self.current_index = resume_index
                self.success_count = progress.get('success', 0)
                self.failed_count = progress.get('failed', 0)
                self.skipped_count = progress.get('skipped', 0)
                self.current_game_title = 'Resuming...'

            self._thread = threading.Thread(target=self._run_refresh, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed PSN refresh for user {user_id}: {resume_index}/{len(npwr_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress data — start from scratch for the originating user.
        result = self.start(npwr_ids, npsso, return_url, user_id=user_id)
        if result.get('success'):
            logger.info(f"Auto-resumed PSN refresh with {len(npwr_ids)} games (from start)")
        return result.get('success', False)

    def _run_refresh(self):
        """Background thread that runs the PSN trophy refresh"""
        # Persist job start for crash recovery (include npwr_ids + return_url +
        # user_id for resume; Pass 31.5 keeps the originating user bound to the
        # job so a restart can refuse to pick up someone else's NPSSO).
        persist_id = persist_job_start('psn_refresh', {
            'game_count': len(self.npwr_ids),
            'npwr_ids': list(self.npwr_ids),
            'return_url': self.return_url,
            'user_id': self._user_id,
        })
        _last_persist_time = time.time()

        try:
            # Authenticate via cached tokens or NPSSO
            try:
                from routes.trophies import create_psn_client
            except ImportError:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = "PSNAWP library not installed"
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='failed', error="PSNAWP library not installed")
                return

            try:
                logger.info("PSN refresh: authenticating with PSN API...")
                with self._lock:
                    self.current_game_title = 'Authenticating with PSN...'
                psnawp, error = create_psn_client(self._npsso)
                if error:
                    raise Exception(error)
                client = psnawp.me()
                logger.info("PSN refresh: authentication successful")
            except Exception as e:
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = f"PSN authentication failed: {str(e)}"
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='failed', error=f"PSN authentication failed: {str(e)}")
                return

            # Get trophy titles once (paginated — can be slow for large libraries)
            FETCH_TIMEOUT = 300  # 5 minutes max for trophy list fetch
            try:
                with self._lock:
                    self.current_game_title = 'Fetching PSN trophy list...'
                logger.info("PSN refresh: fetching all trophy titles from PSN API...")

                # Use a timeout thread to abort if PSN API hangs
                trophy_titles = {}
                fetch_error = [None]  # mutable for closure
                fetch_count = [0]  # mutable counter for progress
                # Pass 41.6.C — explicit cancel event for the inner thread.
                # Previously the inner thread read `self.cancelled` directly
                # (without the lock) and the outer 300s join was the only
                # way to stop it. If the join timed out, the abandoned
                # thread kept iterating `client.trophy_titles()` and
                # mutating shared state (trophy_titles dict, fetch_count,
                # self.current_game_title). The event below is set both on
                # user-cancel and on timeout, so the abandoned thread sees
                # the signal on its next iteration and exits without
                # writing further.
                fetch_cancelled = threading.Event()

                def _fetch_titles():
                    try:
                        for t in client.trophy_titles():
                            if fetch_cancelled.is_set() or self.cancelled:
                                logger.info("PSN refresh: trophy title fetch cancelled")
                                break
                            trophy_titles[t.np_communication_id] = t
                            fetch_count[0] += 1
                            if fetch_count[0] % 25 == 0:
                                logger.info(f"PSN refresh: fetched {fetch_count[0]} trophy titles so far...")
                            # Drop the broadcast progress write on the floor
                            # if we've already been told to stop — saves a
                            # last gratuitous lock acquire after cancel.
                            if fetch_cancelled.is_set():
                                break
                            with self._lock:
                                self.current_game_title = f'Fetching PSN trophy list... ({fetch_count[0]} found)'
                    except Exception as e:
                        logger.error(f"PSN refresh: error during trophy title fetch after {fetch_count[0]} titles: {e}")
                        fetch_error[0] = e

                fetch_thread = threading.Thread(target=_fetch_titles, daemon=True)
                fetch_thread.start()
                fetch_thread.join(timeout=FETCH_TIMEOUT)

                if fetch_thread.is_alive():
                    # Pass 41.6.C — tell the abandoned inner thread to stop
                    # writing to shared state on its next iteration. We
                    # don't wait on it (daemon thread; process exit will
                    # reap if it's truly stuck on a network read).
                    fetch_cancelled.set()
                    logger.error(f"PSN refresh: trophy list fetch timed out after {FETCH_TIMEOUT}s (fetched {fetch_count[0]} so far); abandoned thread told to exit")
                    with self._lock:
                        self.completed = True
                        self.running = False
                        self.error_message = f"PSN trophy list fetch timed out after {FETCH_TIMEOUT}s — Sony API may be slow or unresponsive"
                    release_singleton_fd(self)
                    persist_job_complete(persist_id, status='failed', error=f"Trophy list fetch timed out ({fetch_count[0]} fetched)")
                    return

                if fetch_error[0]:
                    raise fetch_error[0]

                if not trophy_titles:
                    logger.warning("PSN refresh: no trophy titles returned from API")
                    with self._lock:
                        self.completed = True
                        self.running = False
                        self.error_message = "No PSN trophy titles found"
                    release_singleton_fd(self)
                    persist_job_complete(persist_id, status='failed', error="No trophy titles found")
                    return

                logger.info(f"PSN refresh: fetched {len(trophy_titles)} trophy titles successfully")
            except Exception as e:
                logger.error(f"PSN refresh: failed to fetch trophy titles: {e}")
                import traceback
                logger.error(traceback.format_exc())
                with self._lock:
                    self.completed = True
                    self.running = False
                    self.error_message = f"Failed to fetch trophy titles: {str(e)}"
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='failed', error=f"Failed to fetch trophy titles: {str(e)}")
                return

            logger.info(f"Starting PSN refresh job {self.job_id} with {len(self.npwr_ids)} games")

            # Open a single write connection for all DB updates (reduces lock contention)
            write_conn = _get_conn()
            try:
                for i, npwr_id in enumerate(self.npwr_ids):
                    # Skip None placeholders (already-processed items from resume)
                    if npwr_id is None:
                        continue

                    # Check for cancel
                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_index = i + 1

                    # Persist progress every 10 items or 30 seconds
                    # Commit pending writes first to release write lock before persist
                    # opens its own connection (SQLite allows only one writer at a time)
                    _now = time.time()
                    if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                        _commit_with_retry(write_conn)
                        with self._lock:
                            _progress = {
                                'current': i + 1, 'total': len(self.npwr_ids),
                                'success': self.success_count, 'failed': self.failed_count,
                                'skipped': self.skipped_count,
                                'current_item': self.current_game_title
                            }
                        persist_job_progress(persist_id, _progress)
                        _last_persist_time = _now

                    # Check for pause - wait until resumed (outside lock to avoid deadlock).
                    # Pass 40.10 — wait on shutdown_requested so a SIGTERM
                    # short-circuits the pause loop instead of leaving the
                    # daemon thread hanging until the next 0.2s tick.
                    while True:
                        with self._lock:
                            if not self.paused or self.cancelled:
                                break
                        if shutdown_requested.wait(0.2):
                            break

                    with self._lock:
                        if self.cancelled:
                            break

                    # Get game info from database (Pass 31.1 — per user)
                    try:
                        c = write_conn.cursor()
                        c.execute(
                            "SELECT id, title FROM psn_games WHERE npwr_id = ? AND user_id = ?",
                            (npwr_id, self._user_id),
                        )
                        psn_game = c.fetchone()

                        if not psn_game:
                            logger.debug(f"PSN refresh: skipping {npwr_id} — not found in psn_games table")
                            with self._lock:
                                self.skipped_count += 1
                            continue

                        psn_game = dict(psn_game)
                        with self._lock:
                            self.current_game_title = psn_game['title']
                            self.current_npwr = npwr_id
                    except Exception as e:
                        logger.warning(f"Error getting PSN game {npwr_id}: {e}")
                        with self._lock:
                            self.failed_count += 1
                        continue

                    # Find trophy title
                    target_title = trophy_titles.get(npwr_id)
                    if not target_title:
                        logger.debug(f"PSN refresh: skipping {npwr_id} ({psn_game['title']}) — no matching trophy title from API")
                        with self._lock:
                            self.skipped_count += 1
                        # Pass 40.10 — wait on shutdown_requested so SIGTERM
                        # collapses the rate-limit delay instead of blocking.
                        shutdown_requested.wait(self.RATE_LIMIT_DELAY)
                        continue

                    try:
                        # Sync trophies (similar to api_psn_sync_game logic)
                        trophies_synced = self._sync_game_trophies(
                            client, npwr_id, psn_game, target_title, write_conn
                        )

                        with self._lock:
                            self.success_count += 1

                        logger.info(f"PSN Refresh: Synced {trophies_synced} trophies for {psn_game['title']}")

                    except Exception as e:
                        logger.warning(f"Error syncing PSN trophies for {npwr_id} ({psn_game['title']}): {e}")
                        import traceback
                        logger.debug(traceback.format_exc())
                        try:
                            write_conn.rollback()
                        except Exception:
                            pass
                        with self._lock:
                            self.failed_count += 1

                    # Rate limit delay — Pass 40.10: shutdown-aware sleep.
                    shutdown_requested.wait(self.RATE_LIMIT_DELAY)
            finally:
                write_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                _final_status = resolve_terminal_status(self.cancelled)
                logger.info(f"PSN Refresh completed: {self.success_count} success, {self.failed_count} failed, {self.skipped_count} skipped")
            release_singleton_fd(self)

            persist_job_complete(persist_id, status=_final_status)

        except Exception as e:
            logger.error(f"PSN Refresh error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            release_singleton_fd(self)
            persist_job_complete(persist_id, status='failed', error=str(e))

    def _sync_game_trophies(self, client, npwr_id, psn_game, target_title, conn):
        """Sync individual trophies for a game (extracted from trophies.py logic)

        All network I/O (API calls, image downloads) is performed BEFORE any DB
        writes to minimize the time the SQLite write lock is held.  This prevents
        lock contention when other background jobs run concurrently.

        Args:
            conn: Persistent SQLite connection from the caller (avoids per-game connection churn)
        """
        # =====================================================================
        # PHASE 1: Gather data (CPU + network I/O, NO DB writes)
        # =====================================================================

        # Get trophy counts (CPU only — reads from in-memory target_title object)
        earned_counts = {
            'platinum': target_title.earned_trophies.platinum if target_title.earned_trophies else 0,
            'gold': target_title.earned_trophies.gold if target_title.earned_trophies else 0,
            'silver': target_title.earned_trophies.silver if target_title.earned_trophies else 0,
            'bronze': target_title.earned_trophies.bronze if target_title.earned_trophies else 0
        }

        total_counts = {
            'platinum': target_title.defined_trophies.platinum if target_title.defined_trophies else 0,
            'gold': target_title.defined_trophies.gold if target_title.defined_trophies else 0,
            'silver': target_title.defined_trophies.silver if target_title.defined_trophies else 0,
            'bronze': target_title.defined_trophies.bronze if target_title.defined_trophies else 0
        }

        total_earned = sum(earned_counts.values())
        total_trophies = sum(total_counts.values())
        progress = int((total_earned / total_trophies * 100) if total_trophies > 0 else 0)

        # Download game icon (network I/O, no lock)
        icon_url = target_title.title_icon_url if hasattr(target_title, 'title_icon_url') else None
        if icon_url:
            _download_psn_trophy_image(npwr_id, icon_url)

        # Get platform for API call
        title_platform = target_title.title_platform
        if not title_platform or len(title_platform) == 0:
            # No trophies to fetch — still update counts via a quick write
            c = conn.cursor()
            c.execute("""
                UPDATE psn_games SET
                    progress = ?, earned_platinum = ?, earned_gold = ?,
                    earned_silver = ?, earned_bronze = ?, total_platinum = ?,
                    total_gold = ?, total_silver = ?, total_bronze = ?,
                    total_trophies = ?, earned_trophies = ?,
                    last_updated = datetime('now'), trophies_synced = 1
                WHERE npwr_id = ? AND user_id = ?
            """, (
                progress,
                earned_counts['platinum'], earned_counts['gold'],
                earned_counts['silver'], earned_counts['bronze'],
                total_counts['platinum'], total_counts['gold'],
                total_counts['silver'], total_counts['bronze'],
                total_trophies, total_earned, npwr_id, self._user_id
            ))
            _commit_with_retry(conn)
            return 0

        platform_enum = next(iter(title_platform))

        # Fetch all trophies from PSN API (network I/O, no lock)
        trophies = list(client.trophies(
            np_communication_id=npwr_id,
            platform=platform_enum,
            trophy_group_id="all",
            include_progress=True
        ))

        # Get trophy group names (network I/O, no lock)
        group_names = {'default': 'Base Game'}
        try:
            groups_summary = client.trophy_groups_summary(npwr_id, platform=platform_enum)
            if hasattr(groups_summary, 'trophy_groups'):
                for g in groups_summary.trophy_groups:
                    gid = getattr(g, 'trophy_group_id', None)
                    gname = getattr(g, 'trophy_group_name', None)
                    if gid and gname:
                        group_names[gid] = gname
        except (requests.RequestException, OSError, ValueError) as e:
            logger.warning(f"Failed to fetch trophy group names for {npwr_id}: {e}")

        # Process each trophy: download icons + prepare DB params (network I/O + CPU, no lock)
        trophy_rows = []
        first_trophy_date = None
        last_trophy_date = None

        for trophy in trophies:
            try:
                trophy_id = trophy.trophy_id if hasattr(trophy, 'trophy_id') else None
                if trophy_id is None:
                    continue

                group_id = getattr(trophy, 'trophy_group_id', None) or 'default'
                group_name = group_names.get(group_id, 'DLC' if group_id != 'default' else 'Base Game')

                trophy_name = getattr(trophy, 'trophy_name', '') or ''
                trophy_detail = getattr(trophy, 'trophy_detail', '') or ''

                # Trophy type
                trophy_type_raw = getattr(trophy, 'trophy_type', None)
                trophy_type_str = 'bronze'
                if trophy_type_raw is not None:
                    if hasattr(trophy_type_raw, 'name'):
                        trophy_type_str = trophy_type_raw.name.lower()
                    elif hasattr(trophy_type_raw, 'value'):
                        trophy_type_str = str(trophy_type_raw.value).lower()
                    else:
                        trophy_type_str = str(trophy_type_raw).lower()
                        if '.' in trophy_type_str:
                            trophy_type_str = trophy_type_str.split('.')[-1].lower()

                trophy_type = {'platinum': 'P', 'gold': 'G', 'silver': 'S', 'bronze': 'B'}.get(trophy_type_str, 'B')
                trophy_icon = getattr(trophy, 'trophy_icon_url', None)

                # Download trophy icon (network I/O, no lock)
                if trophy_icon:
                    _download_psn_trophy_image(npwr_id, trophy_icon, trophy_id=trophy_id)

                # Earned status
                earned = getattr(trophy, 'earned', None)
                if earned is None:
                    earned = getattr(trophy, 'is_earned', None)
                if earned is None:
                    earned = False

                earned_date = None
                if hasattr(trophy, 'earned_date_time') and trophy.earned_date_time:
                    earned_date = trophy.earned_date_time.isoformat()
                    earned = True

                if earned and earned_date:
                    if first_trophy_date is None or earned_date < first_trophy_date:
                        first_trophy_date = earned_date
                    if last_trophy_date is None or earned_date > last_trophy_date:
                        last_trophy_date = earned_date

                rarity = getattr(trophy, 'trophy_earn_rate', None)
                rarity_label = 'Common'
                if rarity is not None:
                    try:
                        rarity = float(rarity)
                        if rarity <= 5:
                            rarity_label = 'Ultra Rare'
                        elif rarity <= 15:
                            rarity_label = 'Very Rare'
                        elif rarity <= 30:
                            rarity_label = 'Rare'
                    except (ValueError, TypeError):
                        pass

                # Collect params for batch INSERT (no DB write yet).
                # Pass 31.1 — user_id on psn_trophies for direct filtering.
                trophy_rows.append((
                    psn_game['id'], self._user_id, trophy_id, group_id, group_name,
                    trophy_name, trophy_detail, trophy_type, trophy_icon,
                    rarity, rarity_label, 1 if earned else 0, earned_date
                ))

            except Exception as te:
                logger.warning(f"Error processing trophy: {te}")
                continue

        # =====================================================================
        # PHASE 2: Batch DB write (lock held only during fast in-memory writes)
        # =====================================================================

        c = conn.cursor()

        # Update game counts (Pass 31.1 — per user)
        c.execute("""
            UPDATE psn_games SET
                progress = ?, earned_platinum = ?, earned_gold = ?,
                earned_silver = ?, earned_bronze = ?, total_platinum = ?,
                total_gold = ?, total_silver = ?, total_bronze = ?,
                total_trophies = ?, earned_trophies = ?,
                last_updated = datetime('now'), trophies_synced = 1
            WHERE npwr_id = ? AND user_id = ?
        """, (
            progress,
            earned_counts['platinum'], earned_counts['gold'],
            earned_counts['silver'], earned_counts['bronze'],
            total_counts['platinum'], total_counts['gold'],
            total_counts['silver'], total_counts['bronze'],
            total_trophies, total_earned, npwr_id, self._user_id
        ))

        # Batch upsert all trophies
        for row in trophy_rows:
            c.execute("""
                INSERT INTO psn_trophies (
                    psn_game_id, user_id, trophy_id, group_id, group_name,
                    name, description, trophy_type, icon_url,
                    rarity, rarity_label, earned, earned_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(psn_game_id, trophy_id) DO UPDATE SET
                    group_id = excluded.group_id,
                    group_name = excluded.group_name,
                    name = excluded.name,
                    description = excluded.description,
                    trophy_type = excluded.trophy_type,
                    icon_url = excluded.icon_url,
                    rarity = excluded.rarity,
                    rarity_label = excluded.rarity_label,
                    earned = excluded.earned,
                    earned_date = excluded.earned_date
            """, row)

        # Update first/last trophy dates (Pass 31.1 — per user)
        if first_trophy_date or last_trophy_date:
            c.execute("""
                UPDATE psn_games SET
                    first_trophy_earned = COALESCE(?, first_trophy_earned),
                    last_trophy_earned = COALESCE(?, last_trophy_earned)
                WHERE npwr_id = ? AND user_id = ?
            """, (first_trophy_date, last_trophy_date, npwr_id, self._user_id))

        # Commit all changes for this game — lock held only for this brief batch
        _commit_with_retry(conn)

        return len(trophy_rows)
