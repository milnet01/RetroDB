# =============================================================================
# RETRODB - HowLongToBeat (HLTB) Service Layer
# =============================================================================
# Three independent concerns that used to live inside routes/games_hltb.py:
#
#   - HLTBLookup           — single-game lookup + save + clear + generic search
#   - HLTBPendingQueue     — review queue for bulk-lookup matches that need
#                            a human glance (alt-title hits, low-confidence
#                            primaries)
#   - HLTBBulkOrchestrator — thin wrapper over services.jobs.hltb_bulk_job
#                            that stitches in hltb_pending_matches queue depth
#
# Error semantics: each class raises a typed subclass of HLTBError carrying an
# HTTP status code. Routes catch HLTBError and map it to the error() envelope;
# callers from non-HTTP contexts (CLI, tests, future admin UI) can handle the
# exceptions directly without going through jsonify.
# =============================================================================

import json
import logging

from services.database import query, execute

logger = logging.getLogger(__name__)


class HLTBError(Exception):
    """Base class for HLTB service errors. Carries an HTTP-friendly status code."""

    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class GameNotFound(HLTBError):
    status_code = 404


class NoHLTBMatch(HLTBError):
    # HTTP 200 with success:false matches the existing wire contract — the
    # frontend treats "no match" as a normal outcome, not a failure state.
    status_code = 200


class MissingPlaytime(HLTBError):
    status_code = 400


class PendingMatchNotFound(HLTBError):
    status_code = 404


def extract_alt_titles(alternate_titles_json):
    """Decode games.alternate_titles JSON into a flat list of title strings."""
    if not alternate_titles_json:
        return []
    try:
        parsed = json.loads(alternate_titles_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    titles = []
    for entry in parsed:
        if isinstance(entry, dict):
            t = entry.get('title')
            if isinstance(t, str) and t.strip():
                titles.append(t.strip())
    return titles


def _normalize_match_platform(match_platform):
    if isinstance(match_platform, (list, tuple)):
        return ', '.join(str(p) for p in match_platform) if match_platform else ''
    return match_platform or ''


def _normalize_confidence(confidence):
    """Accept 0-1 float, 0-100 number, or list/tuple; return a 0-1 float or None."""
    if confidence is None:
        return None
    if isinstance(confidence, (list, tuple)):
        if not confidence:
            return None
        confidence = float(confidence[0])
    else:
        confidence = float(confidence)
    if confidence > 1:
        confidence = confidence / 100.0
    return confidence


def _resolve_filter_clause(filter_value):
    """Map the UI filter to a (where_clause, params) pair."""
    if filter_value == 'alt_title':
        return ("WHERE reason = 'alt_title'", ())
    if filter_value == 'low_confidence':
        return ("WHERE reason = 'low_confidence'", ())
    return ("", ())


class HLTBLookup:
    """Single-game HLTB lookup, save, clear, and generic search."""

    def lookup(self, game_id, search_title=None, preview=False):
        """Look up playtime for one game. Writes to the DB unless preview=True.

        Raises GameNotFound if the game row doesn't exist.
        Raises NoHLTBMatch if HLTB has no match for the search title.
        """
        from scraper.hltb_lookup import lookup_playtime, format_playtime

        game = query("""
            SELECT g.*, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        if not game:
            raise GameNotFound('Game not found')

        title = search_title or game['title']
        alt_titles = extract_alt_titles(game.get('alternate_titles'))

        result = lookup_playtime(title, game['system_folder'],
                                 alternate_titles=alt_titles)

        if not result:
            raise NoHLTBMatch(f'No HLTB match found for "{title}"')

        parts = []
        if result['main_story']:
            parts.append(f"Main: {format_playtime(result['main_story'])}")
        if result['main_plus_sides']:
            parts.append(f"Main+Extras: {format_playtime(result['main_plus_sides'])}")
        if result['completionist']:
            parts.append(f"100%: {format_playtime(result['completionist'])}")
        playtime_str = ' | '.join(parts) if parts else None

        if playtime_str and not preview:
            execute("""
                UPDATE games SET playtime_estimate = ? WHERE id = ?
            """, (playtime_str, game_id))

        return {
            'playtime': playtime_str,
            'match_name': result['match_name'],
            'match_platform': _normalize_match_platform(result.get('match_platform', '')),
            'confidence': result['match_confidence'],
            'main_story': result['main_story'],
            'main_plus_sides': result['main_plus_sides'],
            'completionist': result['completionist'],
            'search_term_used': result.get('search_term_used'),
            'matched_via_alternate': result.get('matched_via_alternate', False),
        }

    def search(self, search_query, system_folder, year=None,
               alternate_titles=None, game_id=None):
        """Generic HLTB search by title. Does not write to the DB.

        If `alternate_titles` is omitted and `game_id` is supplied, the game's
        stored alt titles are loaded from the DB as a fallback.

        Raises HLTBError(200) if no search query is provided.
        Raises NoHLTBMatch if HLTB has no match.
        """
        from scraper.hltb_lookup import lookup_playtime, format_playtime

        q = str(search_query or '').strip()
        if not q:
            raise HLTBError('No search query provided', status_code=200)

        alts = [str(t).strip() for t in alternate_titles if str(t).strip()] \
            if isinstance(alternate_titles, list) else []

        if not alts and game_id is not None:
            try:
                row = query(
                    "SELECT alternate_titles FROM games WHERE id = ?",
                    (int(game_id),), one=True,
                )
                if row:
                    alts = extract_alt_titles(row.get('alternate_titles'))
            except (ValueError, TypeError):
                pass

        # Default folder 'ps4' preserves legacy behaviour — PSN trophy pages
        # call this endpoint without knowing the system folder.
        folder = (str(system_folder) if system_folder is not None else '').strip() or 'ps4'
        year_str = (str(year) if year is not None else '').strip() or None

        result = lookup_playtime(q, folder, year=year_str,
                                 alternate_titles=alts or None)

        if not result:
            raise NoHLTBMatch(f'No HLTB match found for "{q}"')

        return {
            'hltb_id': result.get('game_id'),
            'main_story': format_playtime(result['main_story']) if result.get('main_story') else None,
            'main_extra': format_playtime(result['main_plus_sides']) if result.get('main_plus_sides') else None,
            'completionist': format_playtime(result['completionist']) if result.get('completionist') else None,
            'match_name': result.get('match_name', ''),
            'match_platform': result.get('match_platform', ''),
            'confidence': result.get('match_confidence', 0),
            'platform_mismatch': result.get('platform_mismatch', False),
            'release_year': result.get('release_world'),
            'developer': result.get('profile_dev'),
            'search_term_used': result.get('search_term_used'),
            'matched_via_alternate': result.get('matched_via_alternate', False),
        }

    def save_result(self, game_id, payload):
        """Persist HLTB playtime + match info onto the games row.

        Raises MissingPlaytime if `payload['playtime']` is missing / empty.
        """
        playtime = payload.get('playtime')
        if not playtime:
            raise MissingPlaytime('No playtime provided')

        match_name = payload.get('match_name')
        match_platform = payload.get('match_platform')
        if isinstance(match_platform, (list, tuple)):
            match_platform = ', '.join(str(p) for p in match_platform) if match_platform else None

        confidence = _normalize_confidence(payload.get('confidence'))

        execute("""
            UPDATE games SET
                playtime_estimate = ?,
                hltb_match_name = ?,
                hltb_match_platform = ?,
                hltb_match_confidence = ?
            WHERE id = ?
        """, (playtime, match_name, match_platform, confidence, game_id))

    def clear(self, game_id):
        """Clear HLTB playtime + match fields on a games row."""
        execute("""
            UPDATE games SET
                playtime_estimate = NULL,
                hltb_match_name = NULL,
                hltb_match_platform = NULL,
                hltb_match_confidence = NULL
            WHERE id = ?
        """, (game_id,))


class HLTBPendingQueue:
    """Pending-match review queue: list, approve / reject, approve-all / reject-all."""

    def list(self):
        """Return every queued pending match, joined with game + system info."""
        rows = query("""
            SELECT p.id, p.game_id, p.hltb_id, p.match_name, p.match_platform,
                   p.confidence, p.playtime, p.main_story, p.main_plus_sides,
                   p.completionist, p.search_term_used, p.matched_via_alternate,
                   p.reason, p.created_at,
                   g.title AS game_title, s.name AS system_name
            FROM hltb_pending_matches p
            JOIN games g ON p.game_id = g.id
            JOIN systems s ON g.system_id = s.id
            ORDER BY p.reason, g.title
        """)
        items = []
        for r in rows or []:
            d = dict(r)
            d['matched_via_alternate'] = bool(d.get('matched_via_alternate'))
            items.append(d)
        return items

    def _apply(self, pending_row):
        confidence_frac = None
        if pending_row.get('confidence') is not None:
            try:
                c = float(pending_row['confidence'])
                confidence_frac = c / 100.0 if c > 1 else c
            except (ValueError, TypeError):
                confidence_frac = None
        execute("""
            UPDATE games SET
                playtime_estimate = ?,
                hltb_match_name = ?,
                hltb_match_platform = ?,
                hltb_match_confidence = ?
            WHERE id = ?
        """, (pending_row.get('playtime'), pending_row.get('match_name'),
              pending_row.get('match_platform'), confidence_frac,
              pending_row['game_id']))
        execute("DELETE FROM hltb_pending_matches WHERE id = ?", (pending_row['id'],))

    def approve(self, pending_id):
        """Apply one pending match to its game row and drop it from the queue.

        Raises PendingMatchNotFound if the queue row is missing.
        """
        row = query("SELECT * FROM hltb_pending_matches WHERE id = ?",
                    (pending_id,), one=True)
        if not row:
            raise PendingMatchNotFound('Pending match not found')
        self._apply(dict(row))

    def reject(self, pending_id):
        """Drop one pending match from the queue."""
        execute("DELETE FROM hltb_pending_matches WHERE id = ?", (pending_id,))

    def approve_all(self, filter_value):
        """Apply every pending match matching the filter. Returns the count applied."""
        where, params = _resolve_filter_clause(filter_value)
        rows = query(f"SELECT * FROM hltb_pending_matches {where}", params)
        applied = 0
        for r in rows or []:
            self._apply(dict(r))
            applied += 1
        return applied

    def reject_all(self, filter_value):
        """Drop every pending match matching the filter. Returns the count dropped."""
        where, params = _resolve_filter_clause(filter_value)
        count_row = query(f"SELECT COUNT(*) AS c FROM hltb_pending_matches {where}",
                          params, one=True)
        count = count_row['c'] if count_row else 0
        execute(f"DELETE FROM hltb_pending_matches {where}", params)
        return count


class HLTBBulkOrchestrator:
    """Thin wrapper around services.jobs.hltb_bulk_job that stitches in queue depth."""

    def start(self, only_missing=True, confidence_threshold=95):
        from services.jobs import hltb_bulk_job
        return hltb_bulk_job.start(only_missing=only_missing,
                                   confidence_threshold=confidence_threshold)

    def status(self):
        from services.jobs import hltb_bulk_job
        status = hltb_bulk_job.get_status()
        queue_row = query("SELECT COUNT(*) AS c FROM hltb_pending_matches",
                          (), one=True)
        status['pending_review'] = queue_row['c'] if queue_row else 0
        return status

    def cancel(self):
        from services.jobs import hltb_bulk_job
        return hltb_bulk_job.cancel()


# Module-level singletons. Stateless classes, so one shared instance is fine.
lookup_service = HLTBLookup()
pending_queue = HLTBPendingQueue()
bulk_orchestrator = HLTBBulkOrchestrator()
