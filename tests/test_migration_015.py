# Pass 59.44 — migration 015 ingests the legacy token files 006 never found.
import contextlib
import importlib.util
import json
import pathlib
import sqlite3

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    p = _REPO_ROOT / 'services' / 'migrations' / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, p)
    if spec is None:
        raise FileNotFoundError(f"Migration file not found: {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def install(tmp_path):
    """The shipped layout: <base>/database/roms.db beside <base>/data/."""
    (tmp_path / 'database').mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    conn = sqlite3.connect(str(tmp_path / 'database' / 'roms.db'))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users (id, username, role) VALUES (7, 'admin', 'admin')")
    _load('006_per_user_platform_tokens').apply(conn)
    conn.commit()
    with contextlib.closing(conn):
        yield conn, data


def _tokens(conn, platform):
    row = conn.execute("SELECT tokens FROM user_platform_tokens WHERE user_id = 7 AND platform = ?",
                       (platform,)).fetchone()
    return json.loads(row[0]) if row else None


def test_ingests_from_the_sibling_data_dir_and_renames(install):
    conn, data = install
    (data / 'psn_tokens.json').write_text(json.dumps({'npsso': 'legacy'}), encoding='utf-8')
    (data / 'xbox_tokens.json').write_text(json.dumps({'access': 'legacy'}), encoding='utf-8')

    _load('015_ingest_legacy_platform_tokens').apply(conn)

    assert _tokens(conn, 'psn') == {'npsso': 'legacy'}
    assert _tokens(conn, 'xbox') == {'access': 'legacy'}
    assert not (data / 'psn_tokens.json').exists()
    assert (data / 'psn_tokens.json.migrated-015').exists()


def test_never_overwrites_a_token_saved_since(install):
    conn, data = install
    conn.execute("INSERT INTO user_platform_tokens (user_id, platform, tokens) VALUES (7, 'psn', ?)",
                 (json.dumps({'npsso': 'fresh'}),))
    (data / 'psn_tokens.json').write_text(json.dumps({'npsso': 'stale'}), encoding='utf-8')

    _load('015_ingest_legacy_platform_tokens').apply(conn)

    assert _tokens(conn, 'psn') == {'npsso': 'fresh'}


def test_leaves_invalid_json_in_place(install):
    conn, data = install
    (data / 'psn_tokens.json').write_text('{not json', encoding='utf-8')

    _load('015_ingest_legacy_platform_tokens').apply(conn)

    assert _tokens(conn, 'psn') is None
    assert (data / 'psn_tokens.json').exists()


def test_is_registered():
    from services.migrations import MIGRATIONS
    assert MIGRATIONS[-1] == '015_ingest_legacy_platform_tokens'
