"""Migration 042 (PASS-59-261): Xbox rows from the retired Microsoft sign-in
are deleted; a row holding an OpenXBL key, and every PSN row, stay."""
import json
import sqlite3

from tests.test_migration_015 import _load


def test_only_old_xbox_sign_ins_are_deleted():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE user_platform_tokens "
                 "(user_id INTEGER, platform TEXT, tokens TEXT NOT NULL)")
    conn.executemany("INSERT INTO user_platform_tokens VALUES (?, ?, ?)", [
        (1, 'xbox', json.dumps({'access_token': 'a', 'refresh_token': 'r'})),
        (2, 'xbox', json.dumps({'api_key': 'k', 'xuid': '1'})),
        (3, 'xbox', 'not json'),
        (1, 'psn', json.dumps({'npsso': 'n'})),
    ])
    migration = _load('042_drop_xbox_oauth_tokens')
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    rows = conn.execute("SELECT user_id, platform FROM user_platform_tokens "
                        "ORDER BY platform, user_id").fetchall()
    assert rows == [(1, 'psn'), (2, 'xbox')]
