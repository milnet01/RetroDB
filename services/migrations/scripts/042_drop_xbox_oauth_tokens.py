# =============================================================================
# Migration 042 — delete Xbox sign-ins left by the retired Microsoft OAuth
# =============================================================================
# PASS-59-261. Xbox now reaches RetroDB through each user's own OpenXBL key,
# stored as {'api_key', ...} under platform 'xbox'. A row from the old
# Microsoft sign-in holds OAuth tokens nothing can use any more, so it goes.
# A row that holds an api_key is kept.
# =============================================================================

import json

from services.migrations._helpers import _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'user_platform_tokens'):
        return
    rows = cursor.execute(
        "SELECT user_id, tokens FROM user_platform_tokens WHERE platform = 'xbox'"
    ).fetchall()
    for user_id, tokens in rows:
        try:
            stored = json.loads(tokens)
        except (TypeError, ValueError):
            stored = None
        if isinstance(stored, dict) and stored.get('api_key'):
            continue
        cursor.execute(
            "DELETE FROM user_platform_tokens WHERE platform = 'xbox' AND user_id = ?",
            (user_id,))
