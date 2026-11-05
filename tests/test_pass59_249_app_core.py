"""PASS-59-249: dashboard, changelog page and app core (audit 2026-11-04 lows)."""
import json
import os
import sqlite3

import pytest


@pytest.fixture
def scratch_games(admin_test_client):
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Test 249 B', 'p249b_sys')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249b_sys'").fetchone()[0]

    def add(title, *entries):
        history = json.dumps([{'timestamp': ts, 'primary_source': src} for ts, src in entries])
        gid = conn.execute("INSERT INTO games (system_id, title, rom_path, scraped, scrape_history) "
                           "VALUES (?, ?, ?, 1, ?)", (sid, title, f'/roms/p249b/{title}', history)).lastrowid
        conn.commit()
        return gid
    client, _ = admin_test_client()
    yield client, add
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _scraped_section(html):
    return html.split('id="scraped"', 1)[1].split('</section>', 1)[0]


def test_recently_scraped_finds_an_old_game_scraped_again(scratch_games):
    # Only the 20 newest rows were read, so an old game scraped today was missed.
    client, add = scratch_games
    add('P249 Old Rescraped', ('2020-01-01T00:00:00', 'igdb'), ('2999-01-01T00:00:00', 'igdb'))
    for n in range(25):
        add(f'P249 Newer {n}', ('2020-01-02T00:00:00', 'igdb'))
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'P249 Old Rescraped' in _scraped_section(html)


def test_a_hand_edit_is_not_a_scrape(scratch_games):
    client, add = scratch_games
    add('P249 Hand Edited', ('2020-01-01T00:00:00', 'igdb'), ('2999-06-01T00:00:00', 'manual'))
    for n in range(5):
        add(f'P249 Scraped {n}', (f'2999-01-0{n + 1}T00:00:00', 'igdb'))
    section = _scraped_section(client.get('/dashboard').get_data(as_text=True))
    assert 'P249 Scraped 4' in section and 'P249 Hand Edited' not in section


def test_app_py_text_reads_name_their_encoding():
    # Windows reads a file without encoding= in its own code page, so a
    # translated changelog failed there (PASS-59-249).
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent.joinpath('app.py').read_text(encoding='utf-8')
    missing = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'open':
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else 'r'
            if 'b' not in mode and 'encoding' not in {k.arg for k in node.keywords}:
                missing.append(node.lineno)
    assert missing == []


def test_changelog_is_parsed_once_until_it_changes(admin_test_client, monkeypatch):
    import yaml
    calls = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, 'safe_load', lambda f: calls.append(1) or real(f))
    client, _ = admin_test_client()
    assert client.get('/changelog').status_code == 200
    first = len(calls)
    assert client.get('/changelog?partial=1&offset=10').status_code == 200
    assert len(calls) == first


def test_locale_list_reads_the_disk_once_until_it_changes(monkeypatch):
    # available_locales() runs on every request; it globbed the disk each time.
    from services import i18n
    calls = []
    real = i18n.glob.glob
    monkeypatch.setattr(i18n.glob, 'glob', lambda p: calls.append(p) or real(p))
    first = i18n.available_locales()
    assert i18n.available_locales() == first
    assert len(calls) <= 1
    assert 'en' in first and 'de' in first


@pytest.mark.parametrize('name', ['Cabal (1989) (UK).adf', 'Cabal (1989) (USA, Europe).adf',
                                  'Cabal (1989) (Europe, Australia).adf'])
def test_region_tags_are_not_publishers(name):
    from services.game_utils import extract_filename_hints
    assert extract_filename_hints(f'/roms/amiga/{name}') == {'year': '1989', 'publisher': None}


def test_a_real_publisher_tag_still_reads():
    from services.game_utils import extract_filename_hints
    assert extract_filename_hints('/roms/amiga/Cabal (1989) (Ocean).adf')['publisher'] == 'Ocean'
