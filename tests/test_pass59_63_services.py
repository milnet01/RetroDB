"""PASS-59-63 — services / scraper sub-findings.

Each class pins one sub-finding of the roadmap item. None of these tests
touch the real library DB or media: conftest points both at throwaway dirs,
and the DB-shaped tests below use private in-memory SQLite connections.
"""

import json
import queue
import sqlite3
import struct
import threading
import zipfile

import pytest


# ---------------------------------------------------------------------------
# 1. services/image_utils.py — bounded wait on the GPU queue
# ---------------------------------------------------------------------------

class TestGpuRunTimeout:
    def test_wedged_gpu_worker_raises_instead_of_blocking(self, monkeypatch):
        from services import image_utils

        # A queue nobody drains stands in for a wedged ROCm session.
        monkeypatch.setattr(image_utils, '_gpu_queue', queue.Queue())
        monkeypatch.setattr(image_utils, '_GPU_RUN_TIMEOUT', 0.05, raising=False)

        outcome = {}

        def _call():
            try:
                image_utils._gpu_run(object(), {})
            except BaseException as e:  # noqa: BLE001 — recording the type
                outcome['exc'] = e

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=2)
        assert not t.is_alive(), "_gpu_run blocked forever on a wedged GPU worker"
        assert isinstance(outcome.get('exc'), TimeoutError)


# ---------------------------------------------------------------------------
# 3. scraper/trophy_parser.py — truncated TROPUSR.DAT
# ---------------------------------------------------------------------------

def _tropusr_bytes(entries_size):
    from scraper.trophy_parser import TROPUSR_MAGIC
    header = struct.pack('>I', TROPUSR_MAGIC) + b'\0' * 4 + struct.pack('>I', 1)
    header = header.ljust(0x30, b'\0')
    table_hdr = (struct.pack('>I', 6) + struct.pack('>I', entries_size)
                 + b'\0' * 4 + struct.pack('>I', 1) + struct.pack('>Q', 0x50))
    table_hdr = table_hdr.ljust(32, b'\0')
    body = struct.pack('>I', 6).ljust(0x40, b'\0')
    return header + table_hdr + body


class TestTrophyParserTruncated:
    def test_small_entry_size_does_not_raise(self, tmp_path):
        from scraper.trophy_parser import TROPUSRParser
        p = tmp_path / 'TROPUSR.DAT'
        p.write_bytes(_tropusr_bytes(entries_size=0))
        assert TROPUSRParser().parse(str(p)) == {}

    def test_one_bad_set_does_not_drop_the_others(self, tmp_path, monkeypatch):
        from scraper import trophy_parser
        (tmp_path / 'NPWR00001_00').mkdir()
        (tmp_path / 'NPWR00002_00').mkdir()
        manager = trophy_parser.TrophyManager(str(tmp_path))

        def _load(self, npwr_id):
            if npwr_id == 'NPWR00001_00':
                raise struct.error('unpack requires a buffer of 4 bytes')
            self.trophy_sets[npwr_id] = 'ok'
            return 'ok'

        monkeypatch.setattr(trophy_parser.TrophyManager, 'load_trophy_set', _load)
        assert manager.load_all_trophy_sets() == {'NPWR00002_00': 'ok'}


# ---------------------------------------------------------------------------
# 4. scraper/rom_tools.py — empty pattern list, unanchored globs
# ---------------------------------------------------------------------------

def _scanner():
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    return ArchiveScanner(ROMToolsConfig())


class TestUnwantedPatterns:
    def test_empty_custom_list_deletes_nothing(self):
        s = _scanner()
        assert s._find_unwanted_files(['Game (USA).bin', 'info.txt'], []) == []

    def test_empty_scan_list_is_kept_as_empty(self, tmp_path):
        from scraper.rom_tools import TaskStatus
        s = _scanner()
        s.scan_for_issues(str(tmp_path), TaskStatus('t', 'scan'), unwanted_patterns=[])
        assert s._find_unwanted_files(['info.txt']) == []

    def test_default_globs_do_not_match_rom_names(self):
        s = _scanner()
        roms = ['Release of the Dragon (USA).bin', 'Readme Quest (Japan).iso']
        assert s._find_unwanted_files(roms) == []

    def test_default_globs_still_match_readme_files(self):
        s = _scanner()
        junk = ['README', 'readme.1st', 'Release.nfo']
        assert sorted(s._find_unwanted_files(junk)) == sorted(junk)


# ---------------------------------------------------------------------------
# 5. scraper/rom_tools.py — Create M3U must not clobber existing work
# ---------------------------------------------------------------------------

def _make_multi_disc_zip(folder):
    archive = folder / 'Game (USA).zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('Game (Disc 1).bin', b'one')
        zf.writestr('Game (Disc 2).bin', b'two')
    return archive


class TestCreateM3uRefusesExisting:
    def test_existing_m3u_is_not_overwritten(self, tmp_path):
        archive = _make_multi_disc_zip(tmp_path)
        m3u = tmp_path / 'Game (USA).m3u'
        m3u.write_text('Game (USA)/hand-edited.cue\n', encoding='utf-8')

        result = _scanner().create_m3u_playlist(str(archive), move_to_staging=False)

        assert result['success'] is False
        assert m3u.read_text(encoding='utf-8') == 'Game (USA)/hand-edited.cue\n'
        assert not (tmp_path / 'Game (USA)').exists()

    def test_existing_extract_folder_is_not_overwritten(self, tmp_path):
        archive = _make_multi_disc_zip(tmp_path)
        folder = tmp_path / 'Game (USA)'
        folder.mkdir()
        (folder / 'Game (Disc 1).bin').write_bytes(b'patched')

        result = _scanner().create_m3u_playlist(str(archive), move_to_staging=False)

        assert result['success'] is False
        assert (folder / 'Game (Disc 1).bin').read_bytes() == b'patched'
        assert not (tmp_path / 'Game (USA).m3u').exists()

    def test_fresh_target_still_builds(self, tmp_path):
        archive = _make_multi_disc_zip(tmp_path)
        result = _scanner().create_m3u_playlist(str(archive), move_to_staging=False)
        assert result['success'] is True, result
        assert (tmp_path / 'Game (USA).m3u').exists()


# ---------------------------------------------------------------------------
# 6. scraper/scrape_ai.py — region reduced to one value
# ---------------------------------------------------------------------------

class TestAiRegionSingleValue:
    def test_multi_value_region_is_normalised(self, monkeypatch):
        import settings_manager
        monkeypatch.setattr(settings_manager, 'load_settings', lambda: {
            'region_options': ['USA', 'Europe', 'Japan'], 'default_region': 'Europe'})
        from scraper.scrape_ai import _validate_all_fields
        assert _validate_all_fields({'region': 'Japan, USA'}) == {'region': 'Japan'}

    def test_unmatched_multi_value_falls_back_to_default(self, monkeypatch):
        import settings_manager
        monkeypatch.setattr(settings_manager, 'load_settings', lambda: {
            'region_options': ['USA', 'Europe'], 'default_region': 'Europe'})
        from scraper.scrape_ai import _validate_field
        assert _validate_field('region', 'Mars, Venus') == 'Europe'


# ---------------------------------------------------------------------------
# 7. services/rom_tools_validators.py — duplicate_method allowlist
# ---------------------------------------------------------------------------

class TestDuplicateMethodAllowlist:
    def test_both_is_accepted(self):
        from services.rom_tools_validators import validate_rom_tools_value
        ok, _, value = validate_rom_tools_value('duplicate_method', 'both')
        assert ok and value == 'both'

    def test_size_is_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value
        ok, _, _ = validate_rom_tools_value('duplicate_method', 'size')
        assert not ok


# ---------------------------------------------------------------------------
# 8. services/settings_validators.py — dead scraper keys
# ---------------------------------------------------------------------------

class TestDeadScraperSettingKeys:
    @pytest.mark.parametrize('key', ['scraper_priority', 'scraper_enabled'])
    def test_key_is_not_accepted_by_general_settings(self, key):
        from services import settings_validators
        import settings_manager
        assert key not in settings_validators._VALIDATORS
        assert key not in settings_manager.DEFAULT_SETTINGS


# ---------------------------------------------------------------------------
# 9 + 10. services/analytics.py — rating buckets, playtime regex
# ---------------------------------------------------------------------------

_RATING_COLS = ['esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
                'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
                'china_rating']


def _analytics_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, "
                 + ", ".join(f"{c} TEXT" for c in _RATING_COLS) + ")")
    conn.execute("INSERT INTO systems VALUES (1, 'Console')")
    for _ in range(5):
        conn.execute("INSERT INTO games (system_id, esrb_rating, pegi_rating) "
                     "VALUES (1, 'M', 'PEGI 16')")
    return conn


def _query_on(conn):
    def _query(sql, args=(), one=False):
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        return (rows[0] if rows else None) if one else rows
    return _query


class TestAnalyticsRatingBuckets:
    def test_game_with_two_ratings_counted_once(self, monkeypatch):
        from services import analytics
        import settings_manager
        monkeypatch.setattr(analytics, 'query', _query_on(_analytics_db()))
        monkeypatch.setattr(settings_manager, 'load_settings',
                            lambda: {'preferred_rating_system': 'esrb'})
        data = analytics._get_rating_data()
        labels, family, teen, mature = data[8], data[9], data[10], data[11]
        assert labels == ['Console']
        assert family[0] + teen[0] + mature[0] == 5
        assert mature == [5]

    def test_preferred_system_decides_the_bucket(self, monkeypatch):
        from services import analytics
        import settings_manager
        monkeypatch.setattr(analytics, 'query', _query_on(_analytics_db()))
        monkeypatch.setattr(settings_manager, 'load_settings',
                            lambda: {'preferred_rating_system': 'pegi'})
        data = analytics._get_rating_data()
        assert data[10] == [5] and data[11] == [0]


class TestAnalyticsPlaytimeRegex:
    def test_main_extras_is_not_read_as_main(self, monkeypatch):
        from services import analytics
        monkeypatch.setattr(analytics, 'query', lambda *a, **k: [
            {'playtime_estimate': 'Main+Extras: 50 hrs | 100%: 90 hrs'},
            {'playtime_estimate': 'Main: 6½ hrs | Main+Extras: 8 hrs | 100%: 12 hrs'},
        ])
        _labels, _data, avg, count = analytics._get_playtime_data()
        assert count == 1
        assert avg == 6.5


# ---------------------------------------------------------------------------
# 11. services/database.py — safe_column refuses a str allowlist
# ---------------------------------------------------------------------------

class TestSafeColumnStrAllowlist:
    def test_substring_of_str_allowlist_is_refused(self):
        from services.database import safe_column
        with pytest.raises((TypeError, ValueError)):
            safe_column('itl', 'title')

    def test_set_allowlist_still_works(self):
        from services.database import safe_column
        assert safe_column('title', {'title', 'year'}) == 'title'


# ---------------------------------------------------------------------------
# 12. Background connections enforce foreign keys
# ---------------------------------------------------------------------------

class TestBackgroundConnectionsForeignKeys:
    def test_job_connection(self):
        from services.jobs.base import _get_conn
        conn = _get_conn()
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()

    def test_scraper_connection(self):
        from scraper.base_scraper import get_scraper_conn
        conn = get_scraper_conn()
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 13. routes/museum.py — single-system generate uses the job's top-games logic
# ---------------------------------------------------------------------------

class TestMuseumRouteTopGames:
    def test_route_stores_what_the_shared_job_function_returns(
            self, admin_test_client, monkeypatch):
        import routes.museum as museum_route
        import scraper.scrape_ai as scrape_ai
        from services.jobs.museum import MuseumGenerateJob

        conn = sqlite3.connect(':memory:', check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT)")
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, "
                     "title TEXT, critic_score INTEGER)")
        conn.execute("CREATE TABLE system_museum (system_id INTEGER PRIMARY KEY, "
                     "history TEXT, summary TEXT, top_games TEXT, generated_at TEXT, "
                     "generated_by TEXT)")
        conn.execute("INSERT INTO systems VALUES (7, 'Console', 'console')")
        monkeypatch.setattr(museum_route, 'get_request_db', lambda: conn)

        monkeypatch.setattr(scrape_ai, '_get_active_provider', lambda: {
            'provider': 'gemini', 'api_key': 'k', 'model': 'm'})
        monkeypatch.setattr(scrape_ai, '_call_gemini', lambda *a, **k: json.dumps(
            {'history': 'h', 'summary': 's'}))

        sentinel = json.dumps([{'title': 'Shared', 'rank': 1, 'source': 'ai'}])
        calls = []

        def _shared(self, system_id, system_name, call_fn, api_key, model, c, call_kwargs=None):
            calls.append(system_id)
            return sentinel

        monkeypatch.setattr(MuseumGenerateJob, '_generate_top_games', _shared)

        client, csrf = admin_test_client()
        resp = client.post('/api/museum/generate/7', headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert calls == [7]
        stored = conn.execute(
            "SELECT top_games FROM system_museum WHERE system_id = 7").fetchone()[0]
        assert stored == sentinel
