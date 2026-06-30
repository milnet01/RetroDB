"""Regression guard: a fresh-install DB (migrations 001..N only, no legacy
schema) must contain every table + column the running code SELECTs.

Migration 013 backfilled twelve `games` columns, two `systems` columns, and
three tables (`controllers`, `system_controllers`, `psn_sync_status`) that the
baseline migration never created — they existed only on the maintainer's
long-lived legacy DB, so a truly fresh install 500'd on the main library card
view (routes/games.py api_games_card_data SELECTs critic_score / user_score /
has_retroachievements + JOINs systems.system_type) and could not run the
curated-controller override or PSN sync.

tests/conftest.py points RETRODB_DB_PATH at a fresh throwaway DB built by the
migration runner alone, so the test client's DB *is* a fresh-install schema —
exactly what this asserts against.
"""

import sqlite3

import pytest

import config


@pytest.fixture(scope="module", autouse=True)
def _build_fresh_schema():
    """Import app at *run* time (not module-import / xdist-collection time) so
    ensure_user_tables() + init_database() (the migration runner) build the
    fresh-install schema against the throwaway DB tests/conftest.py points
    RETRODB_DB_PATH at. Importing app at module top runs those side effects
    during collection, which races other workers and breaks xdist.
    """
    import app  # noqa: F401


def _columns(table):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _tables():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_fresh_games_table_has_score_and_ra_columns():
    cols = _columns("games")
    for required in (
        "critic_score", "critic_score_count", "user_score", "user_score_count",
        "has_retroachievements", "ra_game_id", "ra_achievement_count", "ra_points",
        "campaign", "game_structure", "edition", "other_platforms",
    ):
        assert required in cols, f"games.{required} missing on a fresh install"


def test_fresh_systems_table_has_type_and_default_controller():
    cols = _columns("systems")
    assert "system_type" in cols, "systems.system_type missing on a fresh install"
    assert "default_controller_id" in cols, \
        "systems.default_controller_id missing on a fresh install"


def test_fresh_install_has_controller_and_psn_tables():
    tables = _tables()
    for required in ("controllers", "system_controllers", "psn_sync_status"):
        assert required in tables, f"{required} table missing on a fresh install"


def test_fresh_psn_sync_status_upsert_matches_partial_index():
    """The psn_sync_status user_id index is PARTIAL (WHERE user_id IS NOT NULL),
    so the trophy-sync upsert must name that partial conflict target — a bare
    `ON CONFLICT(user_id)` raises 'does not match any ... UNIQUE constraint' on
    every fresh install (and on the legacy DB, which carries the same index).
    This pins the routes/trophies.py upsert against the shipped index shape.
    """
    conn = sqlite3.connect(config.DB_PATH)
    try:
        for name in ("first", "second"):
            conn.execute(
                """
                INSERT INTO psn_sync_status
                    (user_id, username, sync_in_progress, last_full_sync,
                     trophy_level, avatar_url)
                VALUES (1, ?, 1, datetime('now'), 5, '')
                ON CONFLICT(user_id) WHERE user_id IS NOT NULL DO UPDATE SET
                    username = excluded.username
                """,
                (name,),
            )
        conn.commit()
        row = conn.execute(
            "SELECT username FROM psn_sync_status WHERE user_id = 1"
        ).fetchone()
        assert row[0] == "second", "upsert should have updated the existing row"
    finally:
        conn.close()
