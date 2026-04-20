# =============================================================================
# RETRODB - Background Job Services: Shared Base
# =============================================================================
# Contains shared helpers used by all job types:
# - _get_conn(): SQLite connection factory for background threads
# - _get_ra_credentials(): RA API credential lookup
# - _download_psn_trophy_image(): PSN trophy image downloader
# - persist_job_start/progress/complete: Crash recovery persistence
# =============================================================================

import sqlite3
import logging
import os
import json
import time
import requests
from datetime import datetime, timezone

import config

# Get logger
logger = logging.getLogger(__name__)


def _get_conn():
    """Get a SQLite connection with WAL mode and busy timeout for background threads."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    conn.execute("PRAGMA journal_size_limit = 67108864")
    return conn


def _retry_on_locked(func, max_retries=3, base_delay=1.0):
    """Retry a function on 'database is locked' errors with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"DB locked (attempt {attempt+1}/{max_retries+1}), retrying in {delay:.1f}s")
                time.sleep(delay)
            else:
                raise


def _commit_with_retry(conn, max_retries=5, base_delay=0.5):
    """Commit a persistent connection with retry on 'database is locked'.

    Unlike _retry_on_locked (which wraps open/close connection cycles),
    this retries just the commit on a long-lived connection used by job loops.
    """
    for attempt in range(max_retries + 1):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Commit blocked (attempt {attempt+1}/{max_retries+1}), retrying in {delay:.1f}s")
                time.sleep(delay)
            else:
                raise


def _get_ra_credentials():
    """Get RA credentials via centralized scraper_manager, falling back to config.py"""
    from scraper.scraper_manager import get_api_key
    ra_api_key = get_api_key('ra_apikey', 'RETROACHIEVEMENTS_API_KEY')
    ra_username = get_api_key('ra_username', 'RETROACHIEVEMENTS_USERNAME')
    return ra_username, ra_api_key


def _download_psn_trophy_image(npwr_id, image_url, trophy_id=None):
    """Download a PSN trophy image locally (thread-safe standalone version).

    Args:
        npwr_id: NPWR ID for the game (used as folder name)
        image_url: Remote CDN URL to download from
        trophy_id: If None, downloads game icon as ICON0.PNG.
                   If int, downloads trophy icon as TROP{NNN}.PNG.
    Returns:
        Filename on success, None on failure.
    """
    if not image_url or not npwr_id:
        return None

    dest_dir = os.path.join(config.IMAGE_PATH, 'trophies', npwr_id)
    if trophy_id is not None:
        filename = f'TROP{int(trophy_id):03d}.PNG'
    else:
        filename = 'ICON0.PNG'

    dest_path = os.path.join(dest_dir, filename)

    # Skip if already downloaded
    if os.path.exists(dest_path):
        return filename

    try:
        os.makedirs(dest_dir, exist_ok=True)
        resp = requests.get(image_url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(dest_path, 'wb') as f:
                f.write(resp.content)
            return filename
    except Exception as e:
        logger.warning(f"Failed to download PSN trophy image {filename} for {npwr_id}: {e}")

    return None


# =============================================================================
# JOB PERSISTENCE HELPERS (crash recovery)
# =============================================================================

def persist_job_start(job_type, params=None):
    """Record a new job starting in the job_queue table.

    Args:
        job_type: One of 'bulk_scrape', 'ra_sync', 'ra_refresh', 'psn_refresh'
        params: Optional dict of job-specific parameters (stored as JSON)

    Returns:
        int: The job_queue row ID, or None on failure.
    """
    try:
        def _do_insert():
            now = datetime.now(timezone.utc).isoformat()
            conn = _get_conn()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO job_queue (job_type, status, progress, created_at, updated_at, params) "
                    "VALUES (?, 'running', ?, ?, ?, ?)",
                    (job_type, json.dumps({'current': 0, 'total': 0}), now, now,
                     json.dumps(params) if params else None)
                )
                row_id = c.lastrowid
                conn.commit()
                return row_id
            finally:
                conn.close()

        row_id = _retry_on_locked(_do_insert)
        logger.debug(f"Persisted job start: type={job_type}, id={row_id}")
        return row_id
    except Exception as e:
        logger.warning(f"Failed to persist job start: {e}")
        return None


def persist_job_progress(job_id, progress_dict):
    """Update progress JSON for a running job.

    Args:
        job_id: The job_queue row ID returned by persist_job_start.
        progress_dict: Dict with progress info (current, total, current_item, etc.)
    """
    if job_id is None:
        return
    try:
        def _do_update():
            now = datetime.now(timezone.utc).isoformat()
            conn = _get_conn()
            try:
                conn.execute(
                    "UPDATE job_queue SET progress = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(progress_dict), now, job_id)
                )
                conn.commit()
            finally:
                conn.close()

        _retry_on_locked(_do_update, max_retries=5, base_delay=0.5)
    except Exception as e:
        logger.warning(f"Failed to persist job progress: {e}")


def get_interrupted_jobs():
    """Get jobs that were running when the server stopped.

    Returns list of dicts with id, job_type, params, progress.
    """
    try:
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT id, job_type, params, progress
                FROM job_queue WHERE status = 'running'
                ORDER BY created_at ASC
            """)
            jobs = []
            for row in c.fetchall():
                jobs.append({
                    'id': row['id'],
                    'job_type': row['job_type'],
                    'params': json.loads(row['params']) if row['params'] else {},
                    'progress': json.loads(row['progress']) if row['progress'] else {}
                })
            return jobs
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to get interrupted jobs: {e}")
        return []


def mark_interrupted_job_failed(job_id):
    """Mark a specific interrupted job as failed (when resume isn't possible)."""
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE job_queue SET status = 'failed', error_message = 'Could not auto-resume after restart', "
                "completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), job_id)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to mark job {job_id} as failed: {e}")


def mark_jobs_interrupted():
    """Mark all 'running' and 'queued' jobs as 'interrupted' at startup.

    Both running and queued jobs are orphaned after a server restart — the
    in-memory state (threads, queue) is lost.  Marking them all as
    'interrupted' lets the dashboard recovery banner show a clean, accurate
    list without stale duplicates accumulating across restarts.

    Returns list of dicts (id, job_type, status) for logging purposes.
    """
    try:
        conn = _get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            c = conn.cursor()
            c.execute("SELECT id, job_type, status FROM job_queue WHERE status IN ('running', 'queued')")
            rows = c.fetchall()
            affected = []
            for row in rows:
                c.execute(
                    "UPDATE job_queue SET status = 'interrupted', updated_at = ? WHERE id = ?",
                    (now, row['id'])
                )
                affected.append({'id': row['id'], 'job_type': row['job_type'], 'status': row['status']})
            conn.commit()
            return affected
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to mark jobs interrupted: {e}")
        return []


def get_recoverable_jobs():
    """Get deduplicated recoverable jobs, ordered by created_at ASC.

    For bulk_scrape, multiple records for the same system can accumulate across
    restarts.  We keep only the one with the most progress (or the newest if
    tied) and auto-dismiss the rest so the dashboard stays clean.

    Returns list of dicts: id, job_type, status, params (parsed), progress (parsed), created_at.
    """
    try:
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT id, job_type, status, params, progress, created_at
                FROM job_queue
                WHERE status = 'interrupted'
                ORDER BY created_at ASC
            """)
            all_jobs = []
            for row in c.fetchall():
                all_jobs.append({
                    'id': row['id'],
                    'job_type': row['job_type'],
                    'status': row['status'],
                    'params': json.loads(row['params']) if row['params'] else {},
                    'progress': json.loads(row['progress']) if row['progress'] else {},
                    'created_at': row['created_at']
                })

            # Deduplicate: for bulk_scrape, keep only the best record per
            # (system_id, scrape_mode) — prefer most progress, then newest
            best = {}  # key -> job
            dismiss_ids = []
            jobs = []

            for job in all_jobs:
                if job['job_type'] == 'bulk_scrape':
                    sid = job['params'].get('system_id')
                    mode = job['params'].get('scrape_mode', 'fill_missing')
                    key = (sid, mode)
                    prev = best.get(key)
                    if prev is None:
                        best[key] = job
                    else:
                        # Keep the one with more progress; if tied, keep newest
                        prev_progress = prev['progress'].get('current', 0)
                        this_progress = job['progress'].get('current', 0)
                        if this_progress > prev_progress or (
                            this_progress == prev_progress and job['created_at'] > prev['created_at']
                        ):
                            dismiss_ids.append(prev['id'])
                            best[key] = job
                        else:
                            dismiss_ids.append(job['id'])
                else:
                    jobs.append(job)

            # Auto-dismiss duplicates
            if dismiss_ids:
                now = datetime.now(timezone.utc).isoformat()
                for did in dismiss_ids:
                    c.execute(
                        "UPDATE job_queue SET status = 'dismissed', completed_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, did)
                    )
                conn.commit()
                logger.info(f"Auto-dismissed {len(dismiss_ids)} duplicate recoverable job(s)")

            # Merge: non-bulk_scrape jobs + deduplicated bulk_scrape jobs
            jobs.extend(best.values())
            jobs.sort(key=lambda j: j['created_at'])
            return jobs
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to get recoverable jobs: {e}")
        return []


def dismiss_job(job_id):
    """Dismiss an interrupted or queued job so it no longer appears on the dashboard."""
    try:
        conn = _get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE job_queue SET status = 'dismissed', completed_at = ?, updated_at = ? "
                "WHERE id = ? AND status IN ('interrupted', 'queued')",
                (now, now, job_id)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to dismiss job {job_id}: {e}")


def persist_job_queued(job_type, params=None):
    """Persist a queued job to the database (survives restarts).

    Same pattern as persist_job_start but with status='queued'.
    Returns the job_queue row ID, or None on failure.
    """
    try:
        def _do_insert():
            now = datetime.now(timezone.utc).isoformat()
            conn = _get_conn()
            try:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO job_queue (job_type, status, progress, created_at, updated_at, params) "
                    "VALUES (?, 'queued', ?, ?, ?, ?)",
                    (job_type, json.dumps({'current': 0, 'total': 0}), now, now,
                     json.dumps(params) if params else None)
                )
                row_id = c.lastrowid
                conn.commit()
                return row_id
            finally:
                conn.close()

        row_id = _retry_on_locked(_do_insert)
        logger.debug(f"Persisted queued job: type={job_type}, id={row_id}")
        return row_id
    except Exception as e:
        logger.warning(f"Failed to persist queued job: {e}")
        return None


def remove_queued_job(job_id):
    """Remove a queued job from the database (when it starts running or is cancelled)."""
    if job_id is None:
        return
    try:
        def _do_delete():
            conn = _get_conn()
            try:
                conn.execute(
                    "DELETE FROM job_queue WHERE id = ? AND status = 'queued'",
                    (job_id,)
                )
                conn.commit()
            finally:
                conn.close()

        _retry_on_locked(_do_delete)
        logger.debug(f"Removed queued job: id={job_id}")
    except Exception as e:
        logger.warning(f"Failed to remove queued job {job_id}: {e}")


def persist_job_complete(job_id, status='completed', error=None):
    """Mark a job as completed, failed, or cancelled.

    Args:
        job_id: The job_queue row ID returned by persist_job_start.
        status: Final status ('completed', 'failed', 'cancelled')
        error: Optional error message string.
    """
    if job_id is None:
        return
    try:
        def _do_complete():
            now = datetime.now(timezone.utc).isoformat()
            conn = _get_conn()
            try:
                conn.execute(
                    "UPDATE job_queue SET status = ?, completed_at = ?, error_message = ?, updated_at = ? WHERE id = ?",
                    (status, now, error, now, job_id)
                )
                conn.commit()
            finally:
                conn.close()

        _retry_on_locked(_do_complete)
        logger.debug(f"Persisted job complete: id={job_id}, status={status}")
    except Exception as e:
        logger.warning(f"Failed to persist job completion: {e}")
