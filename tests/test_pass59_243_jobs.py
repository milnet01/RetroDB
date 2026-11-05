"""PASS-59-243: background jobs survive one bad game."""
import sqlite3

from tests.test_ai_fill_bulk import _game, _run, db  # noqa: F401  (db is a fixture)
from tests.test_pass59_202_ss_regions import ROM, _run_job, library  # noqa: F401


def test_one_game_raising_does_not_end_the_ai_fill_run(db, monkeypatch):  # noqa: F811
    for title in ('A', 'B', 'C'):
        _game(db, title)

    def answer(title):
        if title == 'B':
            raise RuntimeError('provider fell over')
        return {'units_sold': '5000'}
    status = _run(monkeypatch, db.sids[0], answer)
    assert (status['success'], status['failed'], status['error']) == (2, 1, None)


def test_one_game_raising_does_not_end_the_region_repair(library, monkeypatch):  # noqa: F811
    import config
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("INSERT INTO games (id, system_id, title, rom_path, screenscraper_id, boxart) "
                 "VALUES (2, 1, 'Sonic 2', ?, 78, '2_ss_boxart.webp')",
                 (ROM.replace('Sonic', 'Sonic 2'),))
    conn.commit()
    conn.close()
    from services.jobs import ss_region_repair as mod
    seen = []

    def search(title, folder, *a, **k):
        seen.append(title)
        if title == 'Sonic':
            raise ConnectionError('network down')
        return None
    monkeypatch.setattr(mod, 'search_game', search)
    job = mod.SsRegionRepairJob()
    job.running = True
    job._worker({'screenscraper_username': 'u', 'screenscraper_password': 'p'})
    assert sorted(seen) == ['Sonic', 'Sonic 2']
    assert job.error_message is None
    assert job.failed_count == 1
