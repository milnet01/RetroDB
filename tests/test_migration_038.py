# PASS-59-240 — migration 038 deletes the plaintext token files 015 kept.
import contextlib
import json
import sqlite3

import pytest

from tests.test_migration_015 import _load


@pytest.fixture
def install(tmp_path):
    """The shipped layout after 015: <base>/database/roms.db beside <base>/data/."""
    (tmp_path / 'database').mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    conn = sqlite3.connect(str(tmp_path / 'database' / 'roms.db'))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users (id, username, role) VALUES (7, 'admin', 'admin')")
    _load('006_per_user_platform_tokens').apply(conn)
    conn.commit()
    with contextlib.closing(conn):
        yield conn, tmp_path


def _kept(directory, name):
    path = directory / f'{name}.migrated-015'
    path.write_text(json.dumps({'npsso': 'legacy'}), encoding='utf-8')
    return path


def _row(conn, platform):
    conn.execute("INSERT INTO user_platform_tokens (user_id, platform, tokens) VALUES (7, ?, '{}')",
                 (platform,))


def test_deletes_kept_files_whose_tokens_are_in_the_database(install):
    conn, base = install
    _row(conn, 'psn')
    _row(conn, 'xbox')
    psn = _kept(base / 'data', 'psn_tokens.json')
    xbox = _kept(base / 'database', 'xbox_tokens.json')

    _load('038_delete_kept_token_files').apply(conn)

    assert not psn.exists()
    assert not xbox.exists()


def test_keeps_a_file_that_is_the_only_copy(install):
    """015 renamed after its INSERT; had that INSERT rolled back, the kept file
    is the only copy of the token. No row for the platform → leave it."""
    conn, base = install
    psn = _kept(base / 'data', 'psn_tokens.json')

    _load('038_delete_kept_token_files').apply(conn)

    assert psn.exists()


def test_nothing_to_do_is_fine(install):
    conn, _base = install
    _load('038_delete_kept_token_files').apply(conn)


def test_is_registered():
    from services.migrations import MIGRATIONS
    assert MIGRATIONS[-1] == '038_delete_kept_token_files'
