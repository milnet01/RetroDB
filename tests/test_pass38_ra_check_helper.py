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

import sqlite3
from unittest.mock import patch

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401


@pytest.fixture
def temp_db_path(tmp_path, monkeypatch):
    """Set up a minimal games table the helper can update.

    The sqlite3 connection is wrapped in a `with` block so it commits and
    closes deterministically even if the seed fails mid-fixture (test-audit
    FIX-1). Note: a sqlite3 context manager commits on success and rolls
    back on exception — it does NOT close the connection. We close
    explicitly afterwards inside the same try/finally surface.
    """
    db_path = tmp_path / 'test.db'
    conn = sqlite3.connect(str(db_path))
    try:
        with conn:
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
    finally:
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
        self, temp_db_path, monkeypatch
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

        conn = sqlite3.connect(temp_db_path)
        try:
            row = conn.execute(
                "SELECT has_retroachievements FROM games WHERE id = 42"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 0  # no DB write

    def test_returns_false_when_has_achievements_is_false(self, temp_db_path):
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

    def test_writes_ra_columns_and_returns_true_on_match(self, temp_db_path):
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

        conn = sqlite3.connect(temp_db_path)
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

    def test_returns_false_and_swallows_exception(self, temp_db_path, caplog):
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

    @pytest.mark.parametrize('exc_factory', [
        # The two most-likely real-world exceptions from a network call —
        # `requests.Timeout` (DNS / TCP / read timeout) and
        # `requests.ConnectionError` (service down, refused) — must also
        # be caught even though they're distinct classes from RuntimeError
        # (test-audit COV-2).
        lambda: __import__('requests').exceptions.Timeout('simulated read timeout'),
        lambda: __import__('requests').exceptions.ConnectionError('simulated refused'),
    ])
    def test_returns_false_on_network_exceptions(self, temp_db_path, exc_factory):
        from scraper import hybrid_scraper

        def _boom(*_args, **_kwargs):
            raise exc_factory()

        with patch('scraper.retroachievements.check_retroachievements',
                   side_effect=_boom):
            result = hybrid_scraper._apply_retroachievements_check(
                42, 'Sonic the Hedgehog', 'genesis'
            )
        assert result is False, (
            "helper must swallow requests-network exceptions so a flaky RA "
            "host can't poison the rest of a scrape"
        )
