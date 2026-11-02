# =============================================================================
# Migration 027 — games.ra_title, and a repair of wrong RetroAchievements links
# =============================================================================
# PASS-59-210. ra_title is RetroAchievements' own name for the linked game, so a
# wrong link can be seen on the game page.
#
# Old matching gave sequels the first game's achievements. Rows on one system
# that share a link but whose titles have different numbers cannot all be right,
# and the title alone cannot say which is, so all lose the link and their saved
# progress. Counts and points left on unlinked rows go too.
#
# An RA Refresh re-links the rows and repairs what this cannot see. It needs the
# network and a key, so it is queued for an admin to start from the dashboard.
# This file keeps its own number check: a migration never changes meaning later.
# =============================================================================

import json
import re
from datetime import datetime, timezone

from services.migrations._helpers import _add_column_if_missing, _table_exists

_ROMAN = {'ii': '2', 'iii': '3', 'iv': '4', 'v': '5', 'vi': '6', 'vii': '7',
          'viii': '8', 'ix': '9'}


def _numbers(title):
    """A title's sequel numbers, without anything in brackets."""
    words = re.findall(r'\w+', re.sub(r'[(\[].*?[)\]]', '', title.lower()))
    return frozenset(_ROMAN.get(w, str(int(w)) if w.isdecimal() else None)
                     for w in words if w in _ROMAN or w.isdecimal())


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    _add_column_if_missing(cursor, 'games', 'ra_title', 'TEXT')

    groups = {}
    for game_id, system_id, ra_game_id, title in cursor.execute(
            "SELECT id, system_id, ra_game_id, title FROM games "
            "WHERE ra_game_id IS NOT NULL").fetchall():
        groups.setdefault((system_id, ra_game_id), []).append((game_id, title or ''))

    wrong = [game_id for rows in groups.values()
             if len({_numbers(title) for _, title in rows}) > 1
             for game_id, _ in rows]
    for game_id in wrong:
        cursor.execute("UPDATE games SET ra_game_id = NULL, has_retroachievements = 0 "
                       "WHERE id = ?", (game_id,))
        if _table_exists(cursor, 'game_achievement_progress'):
            cursor.execute("DELETE FROM game_achievement_progress "
                           "WHERE game_id = ? AND COALESCE(source, 'ra') = 'ra'", (game_id,))

    cursor.execute("""
        UPDATE games SET ra_achievement_count = NULL, ra_points = NULL
        WHERE ra_game_id IS NULL
          AND (ra_achievement_count IS NOT NULL OR ra_points IS NOT NULL)
    """)

    if groups and _table_exists(cursor, 'job_queue'):
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "INSERT INTO job_queue (job_type, status, progress, created_at, updated_at) "
            "VALUES ('ra_refresh', 'queued', ?, ?, ?)",
            (json.dumps({'current': 0, 'total': 0}), now, now))
