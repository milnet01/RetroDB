# =============================================================================
# RETRODB - Alternate Titles Backfill Job
# =============================================================================
# Lightweight maintenance job that walks every scraped game, re-runs the
# unified scraper search to pull back regional / alternate titles, and merges
# them into games.alternate_titles. No media, no other metadata — just names.
#
# Uses scraper_manager.search_games() which already surfaces alt titles from
# IGDB (via alternative_names.name) and ScreenScraper (via regional noms) in
# its search results at no extra API cost.
# =============================================================================

import json
import logging
import threading
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_progress, persist_job_complete,
)

logger = logging.getLogger(__name__)


class AltTitlesBackfillJob:
    """Bulk-fetch alternate titles for already-scraped games without re-scraping."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.reset()

    def reset(self):
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.current_index = 0
        self.total_games = 0
        self.updated_count = 0
        self.no_new_alts_count = 0
        self.no_match_count = 0
        self.failed_count = 0
        self.alts_added = 0
        self.current_game = ""
        self.current_system = ""
        self.start_time = None
        self.error_message = None

    def start(self, only_empty=True):
        """Start the backfill.

        Args:
            only_empty: If True (default), only process games that currently
                have no alternate_titles. If False, process every scraped game
                and merge new alts into existing lists.
        """
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Alt-titles backfill already running'}
            self.reset()
            self.job_id = f"alt_titles_backfill_{int(time.time())}"
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

        self._thread = threading.Thread(
            target=self._worker, args=(only_empty,), daemon=True,
        )
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running backfill to cancel'}

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
                'updated': self.updated_count,
                'alts_added': self.alts_added,
                'no_new_alts': self.no_new_alts_count,
                'no_match': self.no_match_count,
                'failed': self.failed_count,
                'current_game': self.current_game,
                'current_system': self.current_system,
                'error': self.error_message,
            }

    def _worker(self, only_empty):
        persist_id = None
        try:
            from scraper.scraper_manager import scraper_manager
            from scraper.metadata_merger import merge_alt_titles

            conn = _get_conn()
            c = conn.cursor()
            where_empty = "AND (g.alternate_titles IS NULL OR g.alternate_titles = '' OR g.alternate_titles = '[]')" if only_empty else ""
            c.execute(f"""
                SELECT g.id, g.title, g.alternate_titles,
                       s.name AS system_name, s.folder AS system_folder
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.scraped = 1
                  AND g.rom_path NOT LIKE 'clz_import/%'
                  {where_empty}
                ORDER BY g.id
            """)
            games = [dict(r) for r in c.fetchall()]
            conn.close()

            with self._lock:
                self.total_games = len(games)

            persist_id = persist_job_start('alt_titles_backfill', {
                'only_empty': only_empty,
                'total': len(games),
            })

            if not games:
                with self._lock:
                    self.completed = True
                    self.running = False
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

                    # Periodic progress persistence
                    if time.time() - last_persist >= 15:
                        _commit_with_retry(write_conn)
                        with self._lock:
                            persist_job_progress(persist_id, {
                                'current': i + 1, 'total': len(games),
                                'updated': self.updated_count,
                                'failed': self.failed_count,
                                'current_item': self.current_game,
                            })
                        last_persist = time.time()

                    try:
                        existing = []
                        if game.get('alternate_titles'):
                            try:
                                parsed = json.loads(game['alternate_titles'])
                                if isinstance(parsed, list):
                                    existing = parsed
                            except (ValueError, TypeError):
                                existing = []

                        # Unified search — returns results from every enabled
                        # scraper, already sorted by score. IGDB + ScreenScraper
                        # both carry alt titles in their result dicts.
                        results = scraper_manager.search_games(
                            game['title'],
                            system_name=game.get('system_name'),
                            system_folder=game.get('system_folder'),
                            limit=5,
                        )

                        if not results:
                            with self._lock:
                                self.no_match_count += 1
                            continue

                        # Take the best-scored result per source that also
                        # carries alt titles. Skip very-low-score matches that
                        # are likely wrong-game hits.
                        seen_sources = set()
                        new_alts = []
                        for r in results:
                            src = r.get('source') or ''
                            if not src or src in seen_sources:
                                continue
                            if r.get('score', 0) < 100:
                                # Below baseline — likely not the same game.
                                continue
                            alts = r.get('alternate_titles') or []
                            if not alts:
                                continue
                            seen_sources.add(src)
                            for a in alts:
                                if not isinstance(a, dict) or not a.get('title'):
                                    continue
                                new_alts.append({
                                    'title': a['title'],
                                    'region': a.get('region'),
                                    'source': src if src != 'thegamesdb' else 'tgdb',
                                })

                        if not new_alts:
                            with self._lock:
                                self.no_new_alts_count += 1
                            continue

                        merged = merge_alt_titles(existing, new_alts,
                                                  primary_title=game['title'])
                        added = len(merged) - len(existing)
                        if added <= 0:
                            with self._lock:
                                self.no_new_alts_count += 1
                            continue

                        write_conn.execute(
                            "UPDATE games SET alternate_titles = ? WHERE id = ?",
                            (json.dumps(merged), game['id']),
                        )

                        with self._lock:
                            self.updated_count += 1
                            self.alts_added += added

                        if (i + 1) % 25 == 0:
                            _commit_with_retry(write_conn)

                    except Exception as e:
                        logger.warning(f"Alt-titles backfill: failed for game {game['id']} ({game['title']}): {e}")
                        with self._lock:
                            self.failed_count += 1

                _commit_with_retry(write_conn)
            finally:
                write_conn.close()

            with self._lock:
                self.completed = True
                self.running = False
                final_status = 'cancelled' if self.cancelled else 'completed'
                logger.info(
                    f"Alt-titles backfill done: {self.updated_count} games updated "
                    f"({self.alts_added} alt titles added), "
                    f"{self.no_new_alts_count} no new, {self.no_match_count} no match, "
                    f"{self.failed_count} failed"
                )

            if persist_id:
                persist_job_complete(persist_id, status=final_status)

        except Exception as e:
            logger.error(f"Alt-titles backfill error: {e}", exc_info=True)
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
