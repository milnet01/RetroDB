# =============================================================================
# RETRODB - HLTB Bulk Lookup Job
# =============================================================================
# Walks every game (optionally only those without an existing HLTB match),
# runs lookup_playtime with each game's alternate_titles, and:
#
#   - auto-applies primary-title matches at or above the confidence threshold
#   - queues everything else (alt-title matches + low-confidence primaries) into
#     hltb_pending_matches for user review on /hltb/review
#
# The reasoning: primary-title + high confidence == obvious match, no need to
# interrupt the user. Alt-title matches are exceptional by nature and deserve
# a human glance. Low-confidence matches might be the wrong game entirely.
# =============================================================================

import json
import logging
import threading
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)


def classify_match(result, primary_title, confidence_threshold):
    """Decide whether an HLTB result should be auto-applied or queued.

    Returns one of: 'auto_apply', 'queue_alt', 'queue_low_conf', 'skip_no_result'.
    Pure logic, no I/O — factored out so it can be unit-tested without mocking.
    """
    if not result:
        return 'skip_no_result'
    confidence = result.get('match_confidence', 0) or 0
    via_alt = bool(result.get('matched_via_alternate'))
    if via_alt:
        return 'queue_alt'
    if confidence < confidence_threshold:
        return 'queue_low_conf'
    return 'auto_apply'


def _format_playtime_str(main_story, main_extra, completionist):
    """Produce the 'Main: 6.5 hrs | Main+Extras: 8 hrs | 100%: 12 hrs' string."""
    from scraper.hltb_lookup import format_playtime
    parts = []
    if main_story:
        parts.append(f"Main: {format_playtime(main_story)}")
    if main_extra:
        parts.append(f"Main+Extras: {format_playtime(main_extra)}")
    if completionist:
        parts.append(f"100%: {format_playtime(completionist)}")
    return ' | '.join(parts) if parts else None


def _extract_alt_titles_list(alternate_titles_json):
    """Decode alt-titles JSON column into a flat list of title strings."""
    if not alternate_titles_json:
        return []
    try:
        parsed = json.loads(alternate_titles_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out = []
    for entry in parsed:
        if isinstance(entry, dict) and isinstance(entry.get('title'), str):
            t = entry['title'].strip()
            if t:
                out.append(t)
    return out


class HLTBBulkLookupJob:
    """Bulk HLTB lookup: auto-apply obvious matches, queue the rest."""

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
        self.auto_applied_count = 0
        self.queued_count = 0
        self.no_match_count = 0
        self.failed_count = 0
        self.current_game = ""
        self.current_system = ""
        self.start_time = None
        self.error_message = None
        self.confidence_threshold = 95
        self.only_missing = True

    def start(self, only_missing=True, confidence_threshold=95):
        """Start the bulk HLTB lookup.

        Args:
            only_missing: If True (default), skip games that already have a
                stored hltb_match_name. Re-run everything if False.
            confidence_threshold: Primary-title matches at or above this
                percent are auto-applied; everything else is queued.
        """
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'HLTB bulk lookup already running'}
            singleton_fd = acquire_job_singleton_lock('hltb_bulk')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'HLTB bulk lookup is already running on another worker process.',
                }
            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"hltb_bulk_{int(time.time())}"
            self.running = True
            self.only_missing = bool(only_missing)
            self.confidence_threshold = int(confidence_threshold)
            self.start_time = datetime.now(timezone.utc).isoformat()

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running HLTB bulk lookup to cancel'}

    def get_status(self):
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
                'auto_applied': self.auto_applied_count,
                'queued': self.queued_count,
                'no_match': self.no_match_count,
                'failed': self.failed_count,
                'current_game': self.current_game,
                'current_system': self.current_system,
                'confidence_threshold': self.confidence_threshold,
                'only_missing': self.only_missing,
                'error': self.error_message,
            }

    def _worker(self):
        persist_id = None
        try:
            from scraper.hltb_lookup import lookup_playtime

            conn = _get_conn()
            c = conn.cursor()
            where_missing = "AND (g.hltb_match_name IS NULL OR g.hltb_match_name = '')" if self.only_missing else ""
            c.execute(f"""
                SELECT g.id, g.title, g.alternate_titles, g.hltb_match_name,
                       s.name AS system_name, s.folder AS system_folder
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.rom_path NOT LIKE 'clz_import/%'
                  {where_missing}
                ORDER BY g.id
            """)
            games = [dict(r) for r in c.fetchall()]
            conn.close()

            with self._lock:
                self.total_games = len(games)

            persist_id = persist_job_start('hltb_bulk', {
                'only_missing': self.only_missing,
                'confidence_threshold': self.confidence_threshold,
                'total': len(games),
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
                release_singleton_fd(self)
                persist_job_complete(persist_id, status='completed')
                return

            write_conn = _get_conn()
            last_persist = time.time()

            try:
                for i, game in enumerate(games):
                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_index = i + 1
                        self.current_game = game['title']
                        self.current_system = game.get('system_name') or ''

                    # Pass 41.6.B — snapshot under the lock, persist outside.
                    # persist_job_progress is a SQLite write (10–50ms typical,
                    # up to 30s under WAL contention) that previously blocked
                    # every status-poll request taking the same lock.
                    if time.time() - last_persist >= 15:
                        _commit_with_retry(write_conn)
                        with self._lock:
                            progress_payload = {
                                'current': i + 1, 'total': len(games),
                                'auto_applied': self.auto_applied_count,
                                'queued': self.queued_count,
                                'current_item': self.current_game,
                            }
                        persist_job_progress(persist_id, progress_payload)
                        last_persist = time.time()

                    try:
                        alt_titles = _extract_alt_titles_list(game.get('alternate_titles'))

                        result = lookup_playtime(
                            game['title'],
                            system_folder=game.get('system_folder'),
                            alternate_titles=alt_titles or None,
                        )

                        decision = classify_match(result, game['title'],
                                                  self.confidence_threshold)

                        if decision == 'skip_no_result':
                            with self._lock:
                                self.no_match_count += 1
                            continue

                        playtime_str = _format_playtime_str(
                            result.get('main_story'),
                            result.get('main_plus_sides'),
                            result.get('completionist'),
                        )

                        if decision == 'auto_apply':
                            confidence_frac = (result.get('match_confidence', 0) or 0) / 100.0
                            match_platform = result.get('match_platform')
                            if isinstance(match_platform, (list, tuple)):
                                match_platform = ', '.join(str(p) for p in match_platform) or None
                            write_conn.execute("""
                                UPDATE games SET
                                    playtime_estimate = ?,
                                    hltb_match_name = ?,
                                    hltb_match_platform = ?,
                                    hltb_match_confidence = ?
                                WHERE id = ?
                            """, (playtime_str, result.get('match_name'),
                                  match_platform, confidence_frac, game['id']))
                            with self._lock:
                                self.auto_applied_count += 1
                        else:
                            # queue_alt or queue_low_conf → insert into pending
                            reason = 'alt_title' if decision == 'queue_alt' else 'low_confidence'
                            match_platform = result.get('match_platform')
                            if isinstance(match_platform, (list, tuple)):
                                match_platform = ', '.join(str(p) for p in match_platform) or None
                            # Upsert: replace prior pending for this game if any.
                            write_conn.execute("""
                                INSERT INTO hltb_pending_matches (
                                    game_id, hltb_id, match_name, match_platform,
                                    confidence, playtime, main_story, main_plus_sides,
                                    completionist, search_term_used,
                                    matched_via_alternate, reason
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(game_id) DO UPDATE SET
                                    hltb_id = excluded.hltb_id,
                                    match_name = excluded.match_name,
                                    match_platform = excluded.match_platform,
                                    confidence = excluded.confidence,
                                    playtime = excluded.playtime,
                                    main_story = excluded.main_story,
                                    main_plus_sides = excluded.main_plus_sides,
                                    completionist = excluded.completionist,
                                    search_term_used = excluded.search_term_used,
                                    matched_via_alternate = excluded.matched_via_alternate,
                                    reason = excluded.reason,
                                    created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                            """, (
                                game['id'],
                                result.get('game_id'),
                                result.get('match_name'),
                                match_platform,
                                result.get('match_confidence'),
                                playtime_str,
                                result.get('main_story'),
                                result.get('main_plus_sides'),
                                result.get('completionist'),
                                result.get('search_term_used'),
                                1 if result.get('matched_via_alternate') else 0,
                                reason,
                            ))
                            with self._lock:
                                self.queued_count += 1

                        if (i + 1) % 25 == 0:
                            _commit_with_retry(write_conn)

                    except Exception as e:
                        logger.warning(f"HLTB bulk: failed for game {game['id']} ({game['title']}): {e}")
                        with self._lock:
                            self.failed_count += 1

                _commit_with_retry(write_conn)
            finally:
                write_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                final_status = resolve_terminal_status(self.cancelled)
                logger.info(
                    f"HLTB bulk done: {self.auto_applied_count} auto-applied, "
                    f"{self.queued_count} queued for review, "
                    f"{self.no_match_count} no match, {self.failed_count} failed"
                )
            release_singleton_fd(self)

            if persist_id:
                persist_job_complete(persist_id, status=final_status)

        except Exception as e:
            logger.error(f"HLTB bulk error: {e}", exc_info=True)
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
