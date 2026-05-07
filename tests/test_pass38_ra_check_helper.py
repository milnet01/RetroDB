# =============================================================================
# Pass 38.1 (partial) — _apply_retroachievements_check helper
# =============================================================================
# Pass 38.1 plans to split the 1022-line apply_hybrid_metadata into four
# helpers (fallback loop, normalize, save, RA check). This test pins the
# RA-check piece — the smallest of the four (~31 lines inline → standalone
# helper). The helper opens its own DB connection (independent of the
# caller's transaction) and silently swallows exceptions so a missing/down
# RA service can't poison the rest of the scrape.
# =============================================================================

import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Set up a minimal games table the helper can update."""
    db_path = tmp_path / 'test.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY,
            title TEXT,
            has_retroachievements INTEGER DEFAULT 0,
            ra_game_id INTEGER,
            ra_achievement_count INTEGER,
            ra_points INTEGER
        )
    """)
    conn.execute(
        "INSERT INTO games (id, title) VALUES (?, ?)",
        (42, 'Sonic the Hedgehog'),
    )
    conn.commit()
    conn.close()

    # Point both config.DB_PATH and the scraper-conn helper at the temp DB.
    import config as _config
    monkeypatch.setattr(_config, 'DB_PATH', str(db_path))

    def _temp_conn():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        return c

    from scraper import base_scraper, hybrid_scraper
    monkeypatch.setattr(base_scraper, 'get_scraper_conn', _temp_conn)
    monkeypatch.setattr(hybrid_scraper, 'get_scraper_conn', _temp_conn)
    return str(db_path)


class TestApplyRetroachievementsCheck:
    def test_returns_false_and_no_db_write_when_check_returns_none(
        self, temp_db, monkeypatch
    ):
        """check_retroachievements may return None for unknown systems —
        helper must not write to DB and must return False so the caller
        skips appending 'retroachievements' to filled_fields."""
        from scraper import hybrid_scraper

        with patch('scraper.retroachievements.check_retroachievements',
                   return_value=None):
            result = hybrid_scraper._apply_retroachievements_check(
                42, 'Sonic the Hedgehog', 'genesis'
            )
        assert result is False

        conn = sqlite3.connect(temp_db)
        try:
            row = conn.execute(
                "SELECT has_retroachievements FROM games WHERE id = 42"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 0  # no DB write

    def test_returns_false_when_has_achievements_is_false(self, temp_db):
        """check_retroachievements returns a dict with has_achievements=False
        for games on RA-supported systems that don't themselves have an
        achievement set. No DB write, no 'retroachievements' append."""
        from scraper import hybrid_scraper

        ra_info = {'has_achievements': False, 'id': 99, 'achievement_count': 0,
                   'points': 0}
        with patch('scraper.retroachievements.check_retroachievements',
                   return_value=ra_info):
            result = hybrid_scraper._apply_retroachievements_check(
                42, 'Sonic the Hedgehog', 'genesis'
            )
        assert result is False

    def test_writes_ra_columns_and_returns_true_on_match(self, temp_db):
        """Match path — helper writes has_retroachievements=1 + the three
        RA columns and returns True (caller appends to filled_fields)."""
        from scraper import hybrid_scraper

        ra_info = {
            'has_achievements': True,
            'id': 1234,
            'achievement_count': 50,
            'points': 750,
        }
        with patch('scraper.retroachievements.check_retroachievements',
                   return_value=ra_info):
            result = hybrid_scraper._apply_retroachievements_check(
                42, 'Sonic the Hedgehog', 'genesis'
            )
        assert result is True

        conn = sqlite3.connect(temp_db)
        try:
            row = conn.execute(
                "SELECT has_retroachievements, ra_game_id, "
                "       ra_achievement_count, ra_points "
                "FROM games WHERE id = 42"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 1
        assert row[1] == 1234
        assert row[2] == 50
        assert row[3] == 750

    def test_returns_false_and_swallows_exception(self, temp_db, caplog):
        """check_retroachievements may raise (network failure, missing
        credentials, RA service down). Helper must catch and return False
        so the rest of the scrape continues — that's the contract Pass
        38.1 inherited from the inline block."""
        from scraper import hybrid_scraper

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated RA outage")

        with patch('scraper.retroachievements.check_retroachievements',
                   side_effect=_boom):
            with caplog.at_level('DEBUG', logger='scraper.hybrid_scraper'):
                result = hybrid_scraper._apply_retroachievements_check(
                    42, 'Sonic the Hedgehog', 'genesis'
                )
        assert result is False
        assert any('RetroAchievements check skipped' in rec.message
                   for rec in caplog.records)
