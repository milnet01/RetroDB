# =============================================================================
# RETRODB - Each person's completion status, and their play sessions
# =============================================================================
# PASS-59-332. Owns user_game_status and play_sessions (migration 048). No
# row means Not Started. A status set from the game page, the Edit window or
# bulk edit is set by hand; play moves only an untouched Not Started, and
# only to In Progress (docs/specs/PASS-59-332-play-sessions.md §3).
# =============================================================================

from services.database import execute, query

STATUSES = ('not_started', 'in_progress', 'played', 'completed', '100_percent')

# A session this long or longer counts as real play.
MIN_PLAY_SECONDS = 10 * 60

# For a games query aliased `g`: the join takes one user-id bind, and the
# column keeps the `completion_status` key the cards and pages read.
STATUS_JOIN = ("LEFT JOIN user_game_status ugs "
               "ON ugs.game_id = g.id AND ugs.user_id = ?")
STATUS_COLUMN = "COALESCE(ugs.status, 'not_started') AS completion_status"


def status_for(user_id, game_id) -> str:
    row = query("SELECT status FROM user_game_status WHERE user_id = ? AND game_id = ?",
                (user_id, game_id), one=True)
    return row['status'] if row else 'not_started'


def set_by_hand(user_id, game_ids, status) -> None:
    """Set one person's status for each game. A question still waiting is
    dropped: the person has answered it themselves."""
    for game_id in game_ids:
        execute("""
            INSERT INTO user_game_status (user_id, game_id, status, set_by, updated_at)
            VALUES (?, ?, ?, 'hand', datetime('now'))
            ON CONFLICT (user_id, game_id) DO UPDATE SET
                status = excluded.status, set_by = 'hand', ask_pending = 0,
                updated_at = excluded.updated_at
        """, (user_id, game_id, status))


def record_session(user_id, game_id, emulator_id, started_at, seconds,
                   save_changed, achievement):
    """Store one session, then apply the play rule. Returns 'moved' when it
    set In Progress, 'ask' when it left the question waiting, else None."""
    execute("""
        INSERT INTO play_sessions (user_id, game_id, emulator_id, started_at, seconds,
                                   save_changed, achievement)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, game_id, emulator_id, int(started_at), int(seconds),
          int(bool(save_changed)), int(bool(achievement))))
    if seconds < MIN_PLAY_SECONDS:
        return None
    row = query("SELECT * FROM user_game_status WHERE user_id = ? AND game_id = ?",
                (user_id, game_id), one=True)
    if row and (row['set_by'] == 'hand' or row['status'] != 'not_started'):
        return None
    if save_changed or achievement:
        execute("""
            INSERT INTO user_game_status (user_id, game_id, status, set_by, updated_at)
            VALUES (?, ?, 'in_progress', 'play', datetime('now'))
            ON CONFLICT (user_id, game_id) DO UPDATE SET
                status = 'in_progress', set_by = 'play', ask_pending = 0,
                updated_at = excluded.updated_at
        """, (user_id, game_id))
        return 'moved'
    if row and (row['asked'] or row['ask_pending']):
        return None
    execute("""
        INSERT INTO user_game_status (user_id, game_id, status, set_by, ask_pending, updated_at)
        VALUES (?, ?, 'not_started', 'play', 1, datetime('now'))
        ON CONFLICT (user_id, game_id) DO UPDATE SET
            ask_pending = 1, updated_at = excluded.updated_at
    """, (user_id, game_id))
    return 'ask'


def pending_question(user_id, game_id):
    """{'minutes': length of the last session} while the question waits,
    else None."""
    row = query("""
        SELECT (SELECT seconds FROM play_sessions
                WHERE user_id = ugs.user_id AND game_id = ugs.game_id
                ORDER BY started_at DESC, id DESC LIMIT 1) AS seconds
        FROM user_game_status ugs
        WHERE ugs.user_id = ? AND ugs.game_id = ? AND ugs.ask_pending = 1
    """, (user_id, game_id), one=True)
    if not row:
        return None
    return {'minutes': (row['seconds'] or 0) // 60}


def answer(user_id, game_id, yes: bool) -> bool:
    """Answer the waiting question; True when one was waiting. Yes sets In
    Progress as if by hand."""
    if not pending_question(user_id, game_id):
        return False
    if yes:
        execute("""
            UPDATE user_game_status
            SET status = 'in_progress', set_by = 'hand', asked = 1, ask_pending = 0,
                updated_at = datetime('now')
            WHERE user_id = ? AND game_id = ?
        """, (user_id, game_id))
    else:
        execute("""
            UPDATE user_game_status SET asked = 1, ask_pending = 0, updated_at = datetime('now')
            WHERE user_id = ? AND game_id = ?
        """, (user_id, game_id))
    return True


def play_seconds(user_id, game_id) -> int:
    row = query("SELECT SUM(seconds) AS s FROM play_sessions WHERE user_id = ? AND game_id = ?",
                (user_id, game_id), one=True)
    return int(row['s'] or 0)
