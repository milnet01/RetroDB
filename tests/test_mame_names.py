"""PASS-59-227 — MAME games get real names while their files keep their own."""
import json
import os
import zipfile

import pytest

from services import mame_names
from services.game_utils import arcade_search_title, is_arcade_set

LIST = """<?xml version="1.0"?>
<!DOCTYPE mame [<!ELEMENT mame (machine+)>]>
<mame>
  <machine name="dyger"><description>Dyger (Korea set 1)</description><year>1989</year>
    <manufacturer>Philko</manufacturer><rom name="a.bin"/></machine>
  <machine name="neogeo" isbios="yes"><description>Neo-Geo MV-6F</description><year>1990</year>
    <manufacturer>SNK</manufacturer></machine>
  <machine name="amp"><description>Tom &amp; Jerry</description><year>19??</year>
    <manufacturer>&lt;unknown&gt;</manufacturer></machine>
  <machine name="notmine"><description>Not Mine</description></machine>
</mame>
"""
WANTED = {'dyger', 'neogeo', 'amp'}


def _row(**cols):
    row = {'title': 'dyger', 'rom_path': '/r/mame/dyger.zip', 'release_date': None,
           'publisher': None, 'title_locked': 0, 'alternate_titles': None,
           'arcade_category': None, 'scrape_history': None}
    row.update(cols)
    return row


def test_reads_a_plain_list_and_skips_what_is_not_wanted(tmp_path):
    path = tmp_path / 'list.xml'
    path.write_text(LIST)
    got = mame_names.read_machines(str(path), WANTED)
    assert set(got) == WANTED
    assert got['dyger'] == {'description': 'Dyger (Korea set 1)', 'year': '1989',
                            'manufacturer': 'Philko', 'bios': False}
    assert got['neogeo']['bios'] is True
    assert got['amp']['description'] == 'Tom & Jerry'


def test_reads_a_list_inside_a_zip(tmp_path):
    path = tmp_path / 'dat.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('MAME.xml', LIST.replace('machine', 'game'))
    assert mame_names.read_machines(str(path), {'dyger'})['dyger']['year'] == '1989'


def test_a_zip_with_no_list_is_refused(tmp_path):
    path = tmp_path / 'roms.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('a.bin', 'x')
    with pytest.raises(ValueError):
        mame_names.read_machines(str(path), WANTED)


def test_the_first_list_wins_and_the_second_fills_gaps(tmp_path):
    first = tmp_path / 'a.xml'
    first.write_text('<mame><machine name="x"><description>First</description></machine></mame>')
    second = tmp_path / 'b.xml'
    second.write_text('<mame><machine name="x" isbios="yes"><description>Second</description>'
                      '<year>1990</year></machine></mame>')
    got = mame_names.read_machines(str(first), {'x'})
    mame_names.read_machines(str(second), {'x'}, got)
    assert got['x']['description'] == 'First'
    assert got['x']['year'] == '1990'
    assert got['x']['bios'] is True


def test_categories_come_from_the_category_section_only(tmp_path):
    path = tmp_path / 'catver.ini'
    path.write_text('[FOLDER_SETTINGS]\nRootFolderIcon=x\n[Category]\n'
                    'dyger=Shooter / Flying Vertical\nslot=Slot Machine / Reels * Mature *\n'
                    '[VerAdded]\ndyger=0.35b12\nlate=0.200\n')
    assert mame_names.read_categories(str(path), {'dyger', 'slot', 'late'}) == {
        'dyger': 'Shooter', 'slot': 'Slot Machine'}


def test_a_short_name_becomes_the_real_name_and_is_kept_as_an_alternate():
    machine = {'description': 'Dyger (Korea set 1)', 'year': '1989',
               'manufacturer': 'Philko', 'bios': False}
    changes = mame_names.changes_for(_row(), machine, 'Shooter')
    assert changes['title'] == 'Dyger (Korea set 1)'
    assert changes['sort_title']
    assert changes['title_locked'] == 1
    assert changes['release_date'] == '1989'
    assert changes['publisher'] == 'Philko'
    assert changes['arcade_category'] == 'Shooter'
    assert 'rom_path' not in changes
    assert [a['title'] for a in json.loads(changes['alternate_titles'])] == ['dyger']


@pytest.mark.parametrize('cols', [
    {'title': 'My Own Name'},
    {'title_locked': 1},
])
def test_a_title_the_user_chose_is_kept(cols):
    machine = {'description': 'Dyger (Korea set 1)', 'bios': False}
    assert 'title' not in mame_names.changes_for(_row(**cols), machine, None)


def test_filled_fields_are_left_and_a_second_run_changes_nothing():
    machine = {'description': 'Dyger (Korea set 1)', 'year': '1989',
               'manufacturer': 'Philko', 'bios': False}
    row = _row(title='Dyger (Korea set 1)', title_locked=1, release_date='1990-03',
               publisher='Someone', arcade_category='Shooter')
    assert mame_names.changes_for(row, machine, 'Shooter') == {}


def test_bios_wins_over_a_category_and_unknown_details_are_skipped():
    changes = mame_names.changes_for(
        _row(title='neogeo', rom_path='/r/mame/neogeo.zip'),
        {'description': 'Neo-Geo', 'year': '19??', 'manufacturer': '<unknown>', 'bios': True},
        'Shooter')
    assert changes['arcade_category'] == mame_names.BIOS
    assert 'release_date' not in changes and 'publisher' not in changes


def test_a_game_in_no_list_changes_nothing():
    assert mame_names.changes_for(_row(), {}, None) == {}


def test_search_title_drops_brackets():
    assert arcade_search_title('Dyger (Korea set 1)') == 'Dyger'
    assert arcade_search_title('Super Zaxxon (315-5013)') == 'Super Zaxxon'
    assert arcade_search_title('dyger') == 'dyger'
    assert arcade_search_title('(Only brackets)') == '(Only brackets)'
    assert is_arcade_set('MAME') and not is_arcade_set('snes')


def test_screenscraper_looks_a_set_up_by_its_file_name(monkeypatch):
    from scraper import scrape_screenscraper as ss
    asked = []

    def reply(_url, params, timeout=None):
        asked.append(dict(params))
        return {'rom': {'romfilename': 'dyger.zip'}, 'id': '41065'}
    monkeypatch.setattr(ss, '_ss_request_with_retry', reply)
    monkeypatch.setattr(ss, '_jeu_from_reply', lambda r: r)
    monkeypatch.setattr(ss, '_is_a_game', lambda r: True)
    got = ss.identify_by_file('/r/mame/dyger.zip', 'mame', None, 'u', 'p')
    assert got['_matched_file'] is True
    assert asked[0]['romnom'] == 'dyger.zip' and 'crc' not in asked[0]


def test_screenscraper_answering_for_another_file_is_no_match(monkeypatch):
    from scraper import scrape_screenscraper as ss
    monkeypatch.setattr(ss, '_ss_request_with_retry',
                        lambda *a, **k: {'rom': {'romfilename': 'other.zip'}})
    monkeypatch.setattr(ss, '_jeu_from_reply', lambda r: r)
    monkeypatch.setattr(ss, '_is_a_game', lambda r: True)
    assert ss.identify_by_file('/r/mame/dyger.zip', 'mame', None, 'u', 'p') is None


# Against the throwaway database conftest points RETRODB_DB_PATH at.

@pytest.fixture
def mame_db():
    import app as app_module  # noqa: F401 — builds the schema
    import sqlite3
    import config
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    sid = conn.execute("INSERT INTO systems (name, folder) VALUES ('MAME test', 'mame') "
                       "ON CONFLICT DO NOTHING RETURNING id").fetchone()
    sid = sid[0] if sid else conn.execute(
        "SELECT id FROM systems WHERE folder = 'mame'").fetchone()[0]
    ids = {}
    for name in ('dyger', 'neogeo', 'amp', 'lost'):
        ids[name] = conn.execute(
            "INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
            (sid, name, f'/r/mame/{name}.zip')).lastrowid
    conn.commit()
    yield conn, sid, ids
    conn.execute("DELETE FROM games WHERE id IN ({})".format(','.join(map(str, ids.values()))))
    conn.commit()
    conn.close()


def _run_job(paths, category=None):
    from services.jobs.mame_names import MameNamesJob
    job = MameNamesJob()
    assert job.start(paths, category)['success']
    job._thread.join(20)
    status = job.get_status()
    assert status['completed'] and not status['error'], status
    return status


def test_the_job_names_games_and_never_touches_the_path(tmp_path, mame_db):
    conn, _sid, ids = mame_db
    path = tmp_path / 'list.xml'
    path.write_text(LIST)
    status = _run_job([str(path)])
    assert status['named'] == 3
    assert status['not_listed'] == 1
    row = conn.execute("SELECT * FROM games WHERE id = ?", (ids['dyger'],)).fetchone()
    assert row['title'] == 'Dyger (Korea set 1)'
    assert row['rom_path'] == '/r/mame/dyger.zip'
    assert row['title_locked'] == 1
    assert json.loads(row['scrape_history'])[-1]['primary_source'] == mame_names.SOURCE
    lost = conn.execute("SELECT * FROM games WHERE id = ?", (ids['lost'],)).fetchone()
    assert lost['title'] == 'lost' and lost['scrape_history'] is None


def test_a_bios_set_is_hidden_until_asked_for(tmp_path, mame_db):
    from services.game_query import _build_games_query
    conn, sid, ids = mame_db
    conn.execute("UPDATE games SET arcade_category = 'BIOS' WHERE id = ?", (ids['neogeo'],))
    conn.commit()

    def listed(**params):
        sql, values = _build_games_query({'system': sid, **params}, ids_only=True)
        return {r[0] for r in conn.execute(sql, values)}
    assert ids['neogeo'] not in listed()
    assert ids['dyger'] in listed()
    assert ids['neogeo'] in listed(arcade_category=['BIOS'])


def test_renaming_a_mame_file_is_refused(mame_db, admin_test_client):
    _conn, _sid, ids = mame_db
    client, csrf = admin_test_client()
    for url, body in (('/api/reports/rename-to-scraped', {'game_id': ids['dyger']}),
                      ('/api/reports/rename-rom', {'game_id': ids['dyger'], 'new_name': 'x.zip'})):
        resp = client.post(url, json=body, headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 400, (url, resp.status_code)


def test_routes_refuse_a_viewer_and_a_missing_file(admin_test_client):
    client, csrf = admin_test_client(user={'id': 1, 'username': 'v', 'role': 'viewer'})
    assert client.get('/tools/mame-names').status_code in (302, 403)
    assert client.post('/api/mame-names/start', json={},
                       headers={'X-CSRF-Token': csrf}).status_code in (302, 403)
    client, csrf = admin_test_client()
    page = client.get('/tools/mame-names')
    assert page.status_code == 200 and 'id="mameListPath"' in page.get_data(as_text=True)
    assert os.path.exists('static/js/mame-names.js')
    for body in ({}, {'list_path': '/no/such/file.xml'}):
        resp = client.post('/api/mame-names/start', json=body, headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 400
