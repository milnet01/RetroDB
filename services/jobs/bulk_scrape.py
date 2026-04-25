# =============================================================================
# RETRODB - Bulk Scrape Job Manager
# =============================================================================
# Backend-driven bulk metadata scraping with queue support.
# =============================================================================

import threading
import time
import sqlite3
import logging
from collections import deque
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, persist_job_start, persist_job_progress, persist_job_complete,
    persist_job_queued, remove_queued_job, resolve_terminal_status,
    acquire_job_singleton_lock, release_job_singleton_lock,
)

logger = logging.getLogger(__name__)


def _extract_year_from_result(result):
    """Extract release year from a search result (handles all scraper formats)."""
    import re

    # IGDB: first_release_date is a Unix timestamp
    ts = result.get('first_release_date')
    if ts and isinstance(ts, (int, float)):
        try:
            from datetime import timezone
            return str(datetime.fromtimestamp(ts, tz=timezone.utc).year)
        except (OSError, ValueError, OverflowError):
            pass

    # TGDB/RAWG/ScreenScraper: release_date is a date string
    date_str = result.get('release_date') or result.get('released') or ''
    if date_str:
        m = re.search(r'(19|20)\d{2}', str(date_str))
        if m:
            return m.group(0)

    return None


class BulkScrapeJob:
    """Manages bulk scrape jobs with queue support for multiple requests"""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._queue = []  # Queue of pending jobs
        # Pass 41.6.A — cross-process advisory lock FD; None when no chain
        # is active. Acquired in start(), released in _start_next_queued()
        # when the queue empties.
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset current job state (not the queue)"""
        self.job_id = None
        self.game_ids = []
        self.system_id = None
        self.system_name = None
        self.return_url = None
        self.scrape_mode = 'fill_missing'  # 'fill_missing' or 'full_rescrape'
        self.running = False
        self.paused = False
        self.cancelled = False
        self.completed = False
        self.current_index = 0
        self.current_game_title = ""
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self._recently_scraped = deque(maxlen=20)  # Ring buffer of recently scraped game IDs

    def _get_system_name(self, system_id):
        """Get system name from system_id, returns 'Multi-System' if None"""
        if system_id is None:
            return 'Multi-System'
        conn = None
        try:
            conn = _get_conn()
            c = conn.cursor()
            c.execute("SELECT name FROM systems WHERE id = ?", (system_id,))
            row = c.fetchone()
            return row[0] if row else 'Unknown System'
        except Exception as e:
            logger.warning(f"Failed to get system name for id {system_id}: {e}")
            return 'Unknown System'
        finally:
            if conn:
                conn.close()

    @staticmethod
    def _stamp_bulk_scraped(game_id):
        """Update last_bulk_scraped timestamp for a game"""
        conn = None
        try:
            conn = _get_conn()
            conn.execute(
                "UPDATE games SET last_bulk_scraped = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), game_id)
            )
            conn.commit()
        except Exception:
            pass  # Non-critical — don't let timestamp failures break the scrape
        finally:
            if conn:
                conn.close()

    def get_status(self):
        """Get current job status including queue info"""
        with self._lock:
            total = len(self.game_ids)
            processed = self.success_count + self.failed_count + self.skipped_count
            # Which game number is currently being processed (1-indexed, capped at total)
            processing = min(processed + 1, total) if total > 0 else 0
            percent = int((processed / total * 100)) if total > 0 else 0

            # Build queue info
            queue_info = []
            for q in self._queue:
                partial = q.get('partial_progress')
                job_info = {
                    'job_id': q['job_id'],
                    'total': len(q['game_ids']),
                    'return_url': q.get('return_url', '/games'),
                    'system_id': q.get('system_id'),
                    'system_name': q.get('system_name', 'Multi-System')
                }
                # Include partial progress info if this job was previously running
                if partial:
                    job_info['has_partial'] = True
                    job_info['original_total'] = partial.get('original_total', len(q['game_ids']))
                    job_info['completed_before'] = partial.get('completed', 0)
                queue_info.append(job_info)

            return {
                'job_id': self.job_id,
                'running': self.running,
                'paused': self.paused,
                'cancelled': self.cancelled,
                'completed': self.completed,
                'current': self.current_index,
                'processed': processed,
                'processing': processing,
                'total': total,
                'percent': percent,
                'current_game': self.current_game_title,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'return_url': self.return_url,
                'system_name': self.system_name,
                'error': self.error_message,
                'queue': queue_info,
                'queue_count': len(self._queue),
                'recently_scraped_ids': list(self._recently_scraped)
            }

    def start(self, game_ids, system_id=None, return_url=None, scrape_mode='fill_missing'):
        """Start a new bulk scrape job or queue it if one is running"""
        # Get system name before acquiring lock (database access)
        system_name = self._get_system_name(system_id)

        # Get the first game's title for immediate UI feedback
        first_game_title = None
        if game_ids:
            try:
                conn = _get_conn()
                c = conn.cursor()
                c.execute("SELECT title FROM games WHERE id = ?", (game_ids[0],))
                row = c.fetchone()
                if row:
                    first_game_title = row['title']
                conn.close()
            except Exception as e:
                logger.warning(f"Could not fetch first game title: {e}")

        with self._lock:
            new_job_id = f"bulk_{int(time.time())}_{len(self._queue)}"

            # If a job is currently running and not completed, queue this one
            if self.running and not self.completed:
                mode_label = 'Fill Missing' if scrape_mode == 'fill_missing' else 'Full Re-scrape'

                # Reject duplicate: same system + same mode already running
                if system_id is not None and system_id == self.system_id and scrape_mode == self.scrape_mode:
                    logger.info(f"Rejected duplicate bulk scrape for {system_name} (system_id={system_id}, mode={scrape_mode}) — already running")
                    return {
                        'success': False,
                        'error': f'A scrape for {system_name} is already running. Wait until it completes before starting another one for this system.'
                    }

                # Reject duplicate: same system + same mode already in queue
                for q in self._queue:
                    if system_id is not None and q.get('system_id') == system_id and q.get('scrape_mode') == scrape_mode:
                        logger.info(f"Rejected duplicate bulk scrape for {system_name} (system_id={system_id}, mode={scrape_mode}) — already queued")
                        return {
                            'success': False,
                            'error': f'A scrape for {system_name} is already queued. Wait until it completes before starting another one for this system.'
                        }

                queued_job = {
                    'job_id': new_job_id,
                    'game_ids': game_ids,
                    'system_id': system_id,
                    'system_name': system_name,
                    'return_url': return_url,
                    'scrape_mode': scrape_mode
                }
                self._queue.append(queued_job)

                # Persist queued job to DB so it survives server restarts
                db_queue_id = persist_job_queued('bulk_scrape', {
                    'game_ids': game_ids,
                    'game_count': len(game_ids),
                    'system_id': system_id,
                    'system_name': system_name,
                    'return_url': return_url,
                    'scrape_mode': scrape_mode
                })
                queued_job['db_queue_id'] = db_queue_id

                logger.info(f"Queued bulk scrape job {new_job_id} with {len(game_ids)} games for {system_name} (queue position: {len(self._queue)}, mode: {scrape_mode})")
                return {
                    'success': True,
                    'queued': True,
                    'job_id': new_job_id,
                    'total': len(game_ids),
                    'queue_position': len(self._queue)
                }

            # No job running, start immediately. Pass 41.6.A — try the
            # cross-process advisory lock first. If another worker is
            # already running bulk_scrape (multi-worker WSGI deploy), the
            # acquire returns None and we refuse the start. Held FD lives
            # on `self._singleton_fd` for the whole queue-chain; released
            # in `_start_next_queued` when the queue empties.
            singleton_fd = acquire_job_singleton_lock('bulk_scrape')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'A bulk scrape is already running on another worker process. Wait for it to complete or stop the other worker.',
                }
            self._singleton_fd = singleton_fd

            self.reset()
            self.job_id = new_job_id
            self.game_ids = game_ids
            self.system_id = system_id
            self.system_name = system_name
            self.return_url = return_url
            self.scrape_mode = scrape_mode
            self.running = True
            self.start_time = datetime.now()
            # Set first game title immediately for UI feedback
            self.current_game_title = first_game_title
            self.current_index = 0

        # Start background thread
        self._thread = threading.Thread(target=self._run_scrape, daemon=True)
        self._thread.start()

        return {
            'success': True,
            'queued': False,
            'job_id': self.job_id,
            'total': len(game_ids),
            'first_game': first_game_title,
            'system_name': system_name
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

    def cancel_queued(self, job_id):
        """Cancel a specific queued job"""
        with self._lock:
            for i, q in enumerate(self._queue):
                if q['job_id'] == job_id:
                    self._queue.pop(i)
                    remove_queued_job(q.get('db_queue_id'))
                    logger.info(f"Cancelled queued job {job_id}")
                    return {'success': True}
            return {'success': False, 'error': 'Queued job not found'}

    def cancel_all_queued(self):
        """Cancel all queued jobs"""
        with self._lock:
            count = len(self._queue)
            for q in self._queue:
                remove_queued_job(q.get('db_queue_id'))
            self._queue.clear()
            logger.info(f"Cancelled {count} queued jobs")
            return {'success': True, 'cancelled_count': count}

    def promote_queued(self, job_id):
        """Move a queued job up in the queue (run sooner)"""
        with self._lock:
            for i, job in enumerate(self._queue):
                if job['job_id'] == job_id:
                    if i == 0:
                        # Already at front of queue
                        return {'success': True, 'message': 'Already next in queue'}
                    # Swap with previous job
                    self._queue[i], self._queue[i-1] = self._queue[i-1], self._queue[i]
                    logger.info(f"Promoted queued job {job_id} from position {i+1} to {i}")
                    return {'success': True}
            return {'success': False, 'error': 'Job not found in queue'}

    def demote_queued(self, job_id):
        """Move a queued job down in the queue (run later)"""
        with self._lock:
            for i, job in enumerate(self._queue):
                if job['job_id'] == job_id:
                    if i == len(self._queue) - 1:
                        # Already at back of queue
                        return {'success': True, 'message': 'Already last in queue'}
                    # Swap with next job
                    self._queue[i], self._queue[i+1] = self._queue[i+1], self._queue[i]
                    logger.info(f"Demoted queued job {job_id} from position {i+1} to {i+2}")
                    return {'success': True}
            return {'success': False, 'error': 'Job not found in queue'}

    def swap_with_running(self, job_id):
        """Swap a queued job with the currently running job"""
        with self._lock:
            if not self.running or self.completed:
                return {'success': False, 'error': 'No running job to swap'}

            # Find the queued job
            queued_index = None
            for i, job in enumerate(self._queue):
                if job['job_id'] == job_id:
                    queued_index = i
                    break

            if queued_index is None:
                return {'success': False, 'error': 'Queued job not found'}

            # Save current running job state
            running_job = {
                'job_id': self.job_id,
                'game_ids': self.game_ids[self.current_index:],  # Remaining games only
                'system_id': self.system_id,
                'system_name': self.system_name,
                'return_url': self.return_url,
                'scrape_mode': self.scrape_mode,
                'partial_progress': {
                    'original_total': len(self.game_ids),
                    'completed': self.current_index,
                    'success': self.success_count,
                    'failed': self.failed_count,
                    'skipped': self.skipped_count
                }
            }

            # Get the queued job we're promoting
            new_running_job = self._queue.pop(queued_index)

            # Insert the old running job at position 0 (will run next after the new one completes)
            self._queue.insert(0, running_job)

            # Cancel current job (this will cause _run_scrape to exit)
            self.cancelled = True
            self.paused = False
            old_thread = self._thread

            logger.info(f"Swapping running job {self.job_id} with queued job {job_id}")

        # Wait for the old worker to actually exit its current iteration
        # before we mutate state for the new job.  A bare `time.sleep(0.5)`
        # used to race here: the worker could wake after reset() and treat
        # the next game as still belonging to the old job, mixing counters.
        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=60.0)
            if old_thread.is_alive():
                logger.warning(
                    "Old bulk-scrape worker did not exit within 60s of cancel; "
                    "proceeding with swap (state mixing possible)"
                )

        # Start the new job
        with self._lock:
            self.reset()
            self.job_id = new_running_job['job_id']
            self.game_ids = new_running_job['game_ids']
            self.system_id = new_running_job.get('system_id')
            self.system_name = new_running_job.get('system_name', 'Multi-System')
            self.return_url = new_running_job.get('return_url')
            self.scrape_mode = new_running_job.get('scrape_mode', 'fill_missing')
            self.running = True
            self.start_time = datetime.now()

            # Restore partial progress if this job was previously demoted
            partial = new_running_job.get('partial_progress')
            if partial:
                remaining_count = len(self.game_ids)
                completed_before = partial.get('completed', 0)

                if completed_before > 0:
                    placeholder_ids = [None] * completed_before
                    self.game_ids = placeholder_ids + self.game_ids
                    self.current_index = completed_before

                self.success_count = partial.get('success', 0)
                self.failed_count = partial.get('failed', 0)
                self.skipped_count = partial.get('skipped', 0)

                logger.info(f"Restored partial progress for promoted job: {completed_before} done, continuing with {remaining_count} remaining")

        # Start the new job's background thread
        self._thread = threading.Thread(target=self._run_scrape, daemon=True)
        self._thread.start()

        return {'success': True, 'new_job_id': new_running_job['job_id']}

    def demote_running(self):
        """Demote the running job to queue position 1 and start the next queued job"""
        with self._lock:
            if not self.running or self.completed:
                return {'success': False, 'error': 'No running job to demote'}

            if not self._queue:
                return {'success': False, 'error': 'No queued jobs to swap with'}

            # Save current running job state
            running_job = {
                'job_id': self.job_id,
                'game_ids': self.game_ids[self.current_index:],  # Remaining games only
                'system_id': self.system_id,
                'system_name': self.system_name,
                'return_url': self.return_url,
                'scrape_mode': self.scrape_mode,
                'partial_progress': {
                    'original_total': len(self.game_ids),
                    'completed': self.current_index,
                    'success': self.success_count,
                    'failed': self.failed_count,
                    'skipped': self.skipped_count
                }
            }

            # Get the first queued job
            new_running_job = self._queue.pop(0)

            # Insert the old running job at position 0 (front of queue)
            self._queue.insert(0, running_job)

            # Cancel current job
            self.cancelled = True
            self.paused = False
            old_thread = self._thread

            logger.info(f"Demoting running job {self.job_id}, promoting {new_running_job['job_id']}")

        # Same race as swap_with_running — wait for the worker to exit
        # before we mutate state for the new job.
        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=60.0)
            if old_thread.is_alive():
                logger.warning(
                    "Old bulk-scrape worker did not exit within 60s of cancel; "
                    "proceeding with demote (state mixing possible)"
                )

        # Start the new job
        with self._lock:
            self.reset()
            self.job_id = new_running_job['job_id']
            self.game_ids = new_running_job['game_ids']
            self.system_id = new_running_job.get('system_id')
            self.system_name = new_running_job.get('system_name', 'Multi-System')
            self.return_url = new_running_job.get('return_url')
            self.scrape_mode = new_running_job.get('scrape_mode', 'fill_missing')
            self.running = True
            self.start_time = datetime.now()

            # Restore partial progress if this job was previously demoted
            partial = new_running_job.get('partial_progress')
            if partial:
                remaining_count = len(self.game_ids)
                completed_before = partial.get('completed', 0)

                if completed_before > 0:
                    placeholder_ids = [None] * completed_before
                    self.game_ids = placeholder_ids + self.game_ids
                    self.current_index = completed_before

                self.success_count = partial.get('success', 0)
                self.failed_count = partial.get('failed', 0)
                self.skipped_count = partial.get('skipped', 0)

                logger.info(f"Restored partial progress for promoted job: {completed_before} done, continuing with {remaining_count} remaining")

        # Start background thread
        self._thread = threading.Thread(target=self._run_scrape, daemon=True)
        self._thread.start()

        return {'success': True, 'new_job_id': new_running_job['job_id']}

    def resume_from_params(self, params, progress=None):
        """Resume a bulk scrape from persisted params after server restart.

        Follows the same pattern as _start_next_queued with partial_progress:
        uses persisted game_ids and progress to continue from where it left off,
        prepending None placeholders for already-processed items and restoring counts.
        """
        system_id = params.get('system_id')
        scrape_mode = params.get('scrape_mode', 'fill_missing')
        return_url = params.get('return_url')

        # Use persisted game_ids if available, fallback to re-query for old jobs
        game_ids = params.get('game_ids')
        if not game_ids:
            conn = _get_conn()
            try:
                if system_id:
                    games = conn.execute(
                        "SELECT id FROM games WHERE system_id = ? ORDER BY title",
                        (system_id,)
                    ).fetchall()
                else:
                    games = conn.execute("SELECT id FROM games ORDER BY title").fetchall()
            finally:
                conn.close()
            game_ids = [g['id'] for g in games]
        if not game_ids:
            return False

        # If we have progress with items already processed, do a proper resume
        resume_index = progress.get('current', 0) if progress else 0
        if resume_index > 0 and game_ids:
            system_name = params.get('system_name') or self._get_system_name(system_id)
            remaining_ids = game_ids[resume_index:]

            with self._lock:
                # If a job is already running, queue this one with partial progress
                # (happens when "Resume All" fires multiple requests in parallel)
                if self.running and not self.completed:
                    new_job_id = f"bulk_{int(time.time())}_{len(self._queue)}"
                    queued_job = {
                        'job_id': new_job_id,
                        'game_ids': remaining_ids,
                        'system_id': system_id,
                        'system_name': system_name,
                        'return_url': return_url,
                        'scrape_mode': scrape_mode,
                        'partial_progress': {
                            'original_total': len(game_ids),
                            'completed': resume_index,
                            'success': progress.get('success', 0),
                            'failed': progress.get('failed', 0),
                            'skipped': progress.get('skipped', 0)
                        }
                    }
                    self._queue.append(queued_job)
                    logger.info(
                        f"Queued interrupted bulk scrape for {system_name}: "
                        f"{resume_index}/{len(game_ids)} done, "
                        f"{len(remaining_ids)} remaining (queue position: {len(self._queue)})"
                    )
                    return True

                self.reset()
                self.job_id = f"bulk_{int(time.time())}_resume"
                self.game_ids = [None] * resume_index + remaining_ids
                self.system_id = system_id
                self.system_name = system_name
                self.return_url = return_url
                self.scrape_mode = scrape_mode
                self.running = True
                self.start_time = datetime.now()
                self.current_index = resume_index
                self.success_count = progress.get('success', 0)
                self.failed_count = progress.get('failed', 0)
                self.skipped_count = progress.get('skipped', 0)

            self._thread = threading.Thread(target=self._run_scrape, daemon=True)
            self._thread.start()

            logger.info(
                f"Resumed bulk scrape for {system_name}: {resume_index}/{len(game_ids)} done "
                f"({self.success_count}ok/{self.failed_count}fail/{self.skipped_count}skip), "
                f"continuing with {len(remaining_ids)} remaining"
            )
            return True

        # No progress or starting fresh — use normal start path
        result = self.start(game_ids, system_id, return_url=return_url, scrape_mode=scrape_mode)
        if result.get('success'):
            logger.info(f"Auto-resumed bulk scrape for system {system_id} with {len(game_ids)} games (fresh start)")
        return result.get('success', False)

    def _start_next_queued(self):
        """Start the next job from the queue (called after current job completes).

        Pass 41.6.A — when the queue is empty, releases the cross-process
        singleton FD held since the original `start()`. Subsequent
        `start()` calls will acquire a fresh lock.
        """
        with self._lock:
            if not self._queue:
                fd = getattr(self, '_singleton_fd', None)
                if fd is not None:
                    release_job_singleton_lock(fd)
                    self._singleton_fd = None
                return False

            # Get next job from queue
            next_job = self._queue.pop(0)
            remove_queued_job(next_job.get('db_queue_id'))

            # Reset and set up the new job
            self.reset()
            self.job_id = next_job['job_id']
            self.game_ids = next_job['game_ids']
            self.system_id = next_job.get('system_id')
            self.system_name = next_job.get('system_name', 'Multi-System')
            self.return_url = next_job.get('return_url')
            self.scrape_mode = next_job.get('scrape_mode', 'fill_missing')
            self.running = True
            self.start_time = datetime.now()

            # Restore partial progress if this job was previously demoted
            partial = next_job.get('partial_progress')
            if partial:
                # Restore the original total by prepending placeholder IDs
                # The actual game_ids only contains remaining games
                remaining_count = len(self.game_ids)
                original_total = partial.get('original_total', remaining_count)
                completed_before = partial.get('completed', 0)

                # Prepend placeholder IDs so total matches original
                # These won't be processed since current_index will skip them
                if completed_before > 0:
                    placeholder_ids = [None] * completed_before
                    self.game_ids = placeholder_ids + self.game_ids
                    self.current_index = completed_before  # Start after the already-completed ones

                # Restore counts
                self.success_count = partial.get('success', 0)
                self.failed_count = partial.get('failed', 0)
                self.skipped_count = partial.get('skipped', 0)

                logger.info(f"Restored partial progress for job {self.job_id}: {completed_before}/{original_total} done, continuing with {remaining_count} remaining")

            logger.info(f"Starting queued job {self.job_id} with {len(self.game_ids)} games for {self.system_name} ({len(self._queue)} remaining in queue, mode: {self.scrape_mode})")

        # Start background thread for the new job
        self._thread = threading.Thread(target=self._run_scrape, daemon=True)
        self._thread.start()
        return True

    def _run_scrape(self):
        """Background thread that runs the actual scraping"""
        from scraper.scraper_manager import scraper_manager, load_scraper_settings, get_match_settings, passes_match_filter
        from services.game_metadata_service import apply_hybrid_metadata_to_game
        from services.game_utils import get_system_type

        # Snapshot immutable job parameters at thread start — prevents corruption
        # if self is modified before this thread begins executing
        _game_ids = list(self.game_ids)
        _scrape_mode = self.scrape_mode
        _job_id = self.job_id

        logger.info(f"Starting bulk scrape job {_job_id} with {len(_game_ids)} games")

        SOURCE_NAME_MAP = {
            'thegamesdb': 'tgdb',
            'screenscraper': 'screenscraper',
            'esde': 'esde',
            'igdb': 'igdb'
        }

        # Persist job start for crash recovery
        persist_id = persist_job_start('bulk_scrape', {
            'game_ids': _game_ids,
            'game_count': len(_game_ids),
            'system_id': self.system_id,
            'system_name': self.system_name,
            'return_url': self.return_url,
            'scrape_mode': _scrape_mode
        })
        _last_persist_time = time.time()
        _last_optimize_time = _last_persist_time

        # Long-lived connection for progress persistence: avoids opening a
        # fresh sqlite connection (6 PRAGMAs) on every ~10-item progress tick.
        # Closed in both the success and exception branches below.
        try:
            _progress_conn = _get_conn()
        except sqlite3.Error as e:
            logger.warning(f"Could not open persistent progress connection, falling back to per-tick opens: {e}")
            _progress_conn = None

        # Pre-fetch all game data in one query to avoid N individual DB connections
        valid_game_ids = [gid for gid in _game_ids if gid is not None]
        _prefetched_games = {}
        if valid_game_ids:
            try:
                conn = _get_conn()
                c = conn.cursor()
                for batch_start in range(0, len(valid_game_ids), 500):
                    batch = valid_game_ids[batch_start:batch_start + 500]
                    placeholders = ','.join('?' * len(batch))
                    c.execute(f"""
                        SELECT g.*, s.name as system_name, s.folder as system_folder
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.id IN ({placeholders})
                    """, batch)
                    for row in c.fetchall():
                        _prefetched_games[row['id']] = dict(row)
                conn.close()
                logger.info(f"Pre-fetched {len(_prefetched_games)} games for bulk scrape")
            except sqlite3.Error as e:
                logger.warning(f"Pre-fetch failed, will fall back to per-game queries: {e}")

        # Load scraper settings once before the loop
        scraper_settings = load_scraper_settings()
        enabled_scrapers = scraper_settings.get('enabled', {})
        match_settings = get_match_settings()

        try:
            for i, game_id in enumerate(_game_ids):
                # Check for cancel
                with self._lock:
                    if self.cancelled:
                        logger.info(f"Bulk scrape cancelled at game {i+1}/{len(_game_ids)}")
                        break
                    self.current_index = i

                # Persist progress every 10 items or 30 seconds
                _now = time.time()
                if (i % 10 == 0 or _now - _last_persist_time >= 30) and i > 0:
                    with self._lock:
                        _progress = {
                            'current': i, 'total': len(_game_ids),
                            'success': self.success_count, 'failed': self.failed_count,
                            'skipped': self.skipped_count,
                            'current_item': self.current_game_title
                        }
                    persist_job_progress(persist_id, _progress, conn=_progress_conn)
                    _last_persist_time = _now
                    # Periodic ANALYZE for stale-table stats on the long-lived
                    # connection.  Cheap after the 0x10002 hint in _get_conn().
                    if _progress_conn is not None and (_now - _last_optimize_time) >= 1800:
                        try:
                            _progress_conn.execute("PRAGMA optimize")
                            _last_optimize_time = _now
                        except sqlite3.Error:
                            pass

                # Check for pause - wait until resumed
                while True:
                    with self._lock:
                        if not self.paused or self.cancelled:
                            break
                    time.sleep(0.2)

                # Double-check cancel after pause
                with self._lock:
                    if self.cancelled:
                        break

                # Skip placeholder IDs (used for restored partial progress)
                if game_id is None:
                    continue

                # Fetch game info (use pre-fetched data, fall back to individual query)
                try:
                    game_dict = _prefetched_games.get(game_id)

                    if game_dict is None:
                        conn = _get_conn()
                        c = conn.cursor()
                        c.execute("""
                            SELECT g.*, s.name as system_name, s.folder as system_folder
                            FROM games g
                            JOIN systems s ON g.system_id = s.id
                            WHERE g.id = ?
                        """, (game_id,))
                        game = c.fetchone()
                        conn.close()
                        if not game:
                            logger.warning(f"Game {game_id} not found, skipping")
                            with self._lock:
                                self.skipped_count += 1
                            continue
                        game_dict = dict(game)

                    if not game_dict:
                        logger.warning(f"Game {game_id} not found, skipping")
                        with self._lock:
                            self.skipped_count += 1
                        continue
                    title = game_dict.get('title', 'Unknown')

                    with self._lock:
                        self.current_game_title = title

                    # Check 24-hour bulk scrape cooldown (skip in full_rescrape mode).
                    # All new timestamps are UTC-aware; treat pre-Pass-30 naive
                    # strings as UTC so legacy rows don't trip the aware-vs-naive
                    # TypeError on subtraction.
                    if _scrape_mode != 'full_rescrape':
                        last_bulk = game_dict.get('last_bulk_scraped')
                        if last_bulk:
                            try:
                                last_dt = datetime.fromisoformat(last_bulk)
                                if last_dt.tzinfo is None:
                                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                                hours_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                                if hours_ago < 24:
                                    logger.info(f"Skipping {title} - bulk scraped {hours_ago:.1f}h ago (cooldown 24h)")
                                    with self._lock:
                                        self.skipped_count += 1
                                    continue
                            except (ValueError, TypeError):
                                pass  # Invalid timestamp, proceed with scrape

                    # Check if should skip (fill_missing mode)
                    if _scrape_mode == 'fill_missing':
                        fill_missing_fields = [
                            'description', 'publisher', 'developer', 'genre',
                            'release_date', 'esrb_rating', 'pegi_rating',
                            'boxart', 'boxart_3d', 'screenshots', 'fanart',
                            'players', 'modes',
                        ]
                        missing = [f for f in fill_missing_fields if not game_dict.get(f)]
                        if not missing:
                            logger.info(f"Skipping {title} - all metadata fields populated")
                            self._stamp_bulk_scraped(game_id)
                            with self._lock:
                                self.skipped_count += 1
                            continue
                        logger.info(f"Fill-missing for {title} - missing: {', '.join(missing)}")

                    # Determine if computer system
                    system_folder = game_dict.get('system_folder', '').lower()
                    system_type = get_system_type(system_folder)

                    # Search for metadata
                    system_name = game_dict.get('system_name', 'Unknown')
                    logger.info(f"Scraping: {title} for {system_name}")

                    results = scraper_manager.search_games(title, system_name, system_folder)

                    # --- Filename-hint disambiguation ---
                    # When identical titles compete (e.g. two "Cabal" games on C64),
                    # use the year from the ROM filename to pick the correct edition.
                    rom_path = game_dict.get('rom_path', '')
                    if rom_path and results:
                        from services.game_utils import extract_filename_hints
                        hints = extract_filename_hints(rom_path)
                        hint_year = hints.get('year')
                        if hint_year:
                            for r in results:
                                result_year = _extract_year_from_result(r)
                                if result_year and result_year == hint_year:
                                    r['score'] = r.get('score', 0) + 50
                                    logger.info(f"  Year-match bonus +50: '{r.get('name', '')}' ({r.get('source', '')}) year={result_year}")

                    if results:
                        # Sort by score only — priority boost is already baked in
                        sorted_results = sorted(results, key=lambda r: -r.get('score', 0))

                        # Filter out results that don't pass the configured match filter
                        sorted_results = [r for r in sorted_results if passes_match_filter(r, match_settings)]

                        if not sorted_results:
                            logger.warning(f"No results passed match filter ({match_settings['mode']} mode) for {title}")
                            self._stamp_bulk_scraped(game_id)
                            with self._lock:
                                self.failed_count += 1
                            continue

                        # Find best match from enabled scraper
                        best_match = None
                        for result in sorted_results:
                            src = result.get('source', result.get('scraper', 'unknown'))
                            normalized = SOURCE_NAME_MAP.get(src, src)
                            if enabled_scrapers.get(normalized, True):
                                best_match = result
                                break

                        if not best_match:
                            best_match = sorted_results[0]

                        source = best_match.get('source', best_match.get('scraper', 'tgdb'))
                        source_id = best_match.get('id')

                        logger.info(f"Selected {source} match: {best_match.get('name', 'Unknown')} (ID: {source_id})")

                        # Build secondary_sources from other top results (best per scraper)
                        # so gap-filling can reuse already-matched IDs instead of re-searching.
                        # Include 'name' so _pick_best_secondary can do title matching,
                        # and 'title_score' so poor matches can be filtered out.
                        secondary_sources = []
                        seen_sources = {SOURCE_NAME_MAP.get(source, source)}
                        for r in sorted_results:
                            r_src = SOURCE_NAME_MAP.get(r.get('source', ''), r.get('source', ''))
                            if r_src not in seen_sources:
                                seen_sources.add(r_src)
                                secondary_sources.append({
                                    'source': r_src,
                                    'id': r.get('id'),
                                    'name': r.get('name', ''),
                                    'title_score': r.get('title_score', 0),
                                })

                        # Apply hybrid metadata via the shared orchestrator.
                        result = apply_hybrid_metadata_to_game(
                            db_game_id=game_id,
                            primary_source=source,
                            primary_id=source_id,
                            system_folder=system_folder,
                            fill_gaps=True,
                            force_overwrite=(_scrape_mode == 'full_rescrape'),
                            primary_data=best_match,
                            secondary_sources=secondary_sources,
                        )

                        if result.get('success'):
                            filled = len(result.get('filled_fields', []))
                            sources_used = ', '.join(result.get('sources_used', []))
                            logger.info(f"Updated {title} with {filled} fields from {sources_used}")
                            self._stamp_bulk_scraped(game_id)
                            with self._lock:
                                self.success_count += 1
                                self._recently_scraped.append(game_id)
                        else:
                            logger.info(f"No updates for {title}")
                            self._stamp_bulk_scraped(game_id)
                            with self._lock:
                                self.skipped_count += 1
                    else:
                        logger.info(f"No results for {title}")
                        self._stamp_bulk_scraped(game_id)
                        with self._lock:
                            self.failed_count += 1

                except Exception as e:
                    logger.error(f"Error scraping game {game_id}: {e}")
                    with self._lock:
                        self.failed_count += 1

            # Job complete — release prefetched data to free memory
            _prefetched_games.clear()

            with self._lock:
                self.completed = True
                self.running = False
                self.end_time = datetime.now()
                _final_status = resolve_terminal_status(self.cancelled)
                logger.info(f"Bulk scrape completed: {self.success_count} success, {self.failed_count} failed, {self.skipped_count} skipped")

            if _progress_conn is not None:
                try:
                    _progress_conn.execute("PRAGMA optimize")
                except sqlite3.Error:
                    pass
                try:
                    _progress_conn.close()
                except sqlite3.Error:
                    pass
                _progress_conn = None

            persist_job_complete(persist_id, status=_final_status)

            # Game metadata changed en masse — drop dependent caches so the
            # next /games + /analytics load reflects the new genres, filter
            # options, rating distribution etc. instead of serving up to 60s
            # of stale filter dropdowns or 300s of stale analytics.
            try:
                from services.game_query import invalidate_filter_cache
                from services.analytics import invalidate_analytics_cache
                invalidate_filter_cache()
                invalidate_analytics_cache()
            except Exception as cache_err:
                logger.debug(f"Cache invalidation after bulk scrape failed: {cache_err}")

            # Start next queued job if any
            self._start_next_queued()

        except Exception as e:
            logger.error(f"Bulk scrape error: {e}")
            _prefetched_games.clear()
            if _progress_conn is not None:
                try:
                    _progress_conn.close()
                except sqlite3.Error:
                    pass
                _progress_conn = None
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            persist_job_complete(persist_id, status='failed', error=str(e))
            # Even on error, try to start the next queued job
            self._start_next_queued()
