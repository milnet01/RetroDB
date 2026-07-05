# =============================================================================
# Pass 38.1 (partial) — _save_game_row helper
# =============================================================================
# The SAVE TO DATABASE block of apply_hybrid_metadata pops the internal
# `_boxart_source` tracking key, JSON-encodes alternate_titles, then issues
# the COALESCE-guarded fill-only UPDATE. Pass 38.1 (partial) extracted it
# into a helper that takes the caller's cursor (the caller still owns the
# commit). These tests pin the contract:
#   - COALESCE fill-only: a None metadata field preserves the existing DB
#     value; a non-None field overwrites.
#   - scraped flips to 1, scrape_history written verbatim.
#   - alternate_titles list → JSON text in the column.
#   - `_boxart_source` is popped from metadata (and never reaches SQL).
# =============================================================================

import json
import sqlite3

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)

# Every column the helper's UPDATE touches, so the in-memory table matches
# the production schema surface the helper writes to.
_COLUMNS = [
    'title', 'sort_title', 'publisher', 'developer', 'release_date', 'genre',
    'description', 'players', 'modes', 'esrb_rating', 'pegi_rating',
    'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating', 'grac_rating',
    'classind_rating', 'china_rating', 'boxart', 'boxart_3d', 'screenshots', 'fanart',
    'video', 'manual', 'region', 'franchise', 'similar_games',
    'playtime_estimate', 'controller_support', 'save_type', 'game_structure',
    'perspective', 'dimension', 'edition', 'campaign', 'other_platforms',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
    'alternate_titles', 'scrape_history',
]


def _full_metadata(**overrides):
    """A metadata dict with every key the helper bracket-accesses set to
    None, then apply overrides. Mirrors the dict apply_hybrid_metadata
    builds so the helper never KeyErrors on a missing field."""
    md = {col: None for col in _COLUMNS}
    md.pop('scrape_history', None)  # not a metadata key — passed separately
    md.update(overrides)
    return md


@pytest.fixture
def connection(tmp_path):
    db_path = tmp_path / 'test.db'
    conn = sqlite3.connect(str(db_path))
    cols_sql = ', '.join(f'{c} TEXT' for c in _COLUMNS)
    conn.execute(f"CREATE TABLE games (id INTEGER PRIMARY KEY, {cols_sql}, scraped INTEGER DEFAULT 0)")
    try:
        yield conn
    finally:
        conn.close()


class TestSaveGameRow:
    def test_fill_only_preserves_existing_and_fills_empty(self, connection):
        from scraper import hybrid_scraper

        # Existing row: publisher curated, title empty.
        connection.execute(
            "INSERT INTO games (id, publisher, title) VALUES (1, 'CuratedPub', NULL)"
        )
        connection.commit()
        c = connection.cursor()

        metadata = _full_metadata(title='New Title', publisher=None)
        hybrid_scraper._save_game_row(c, metadata, '[]', 1)
        connection.commit()

        row = connection.execute(
            "SELECT publisher, title FROM games WHERE id = 1"
        ).fetchone()
        assert row[0] == 'CuratedPub'   # None metadata → existing preserved
        assert row[1] == 'New Title'    # non-None metadata → overwritten

    def test_scraped_flag_and_history_written(self, connection):
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id, scraped) VALUES (1, 0)")
        connection.commit()
        c = connection.cursor()

        history = json.dumps([{'primary_source': 'igdb'}])
        hybrid_scraper._save_game_row(c, _full_metadata(), history, 1)
        connection.commit()

        row = connection.execute(
            "SELECT scraped, scrape_history FROM games WHERE id = 1"
        ).fetchone()
        assert row[0] == 1
        assert row[1] == history

    def test_alternate_titles_encoded_to_json(self, connection):
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id) VALUES (1)")
        connection.commit()
        c = connection.cursor()

        metadata = _full_metadata(alternate_titles=['Alt One', 'Alt Two'])
        hybrid_scraper._save_game_row(c, metadata, '[]', 1)
        connection.commit()

        stored = connection.execute(
            "SELECT alternate_titles FROM games WHERE id = 1"
        ).fetchone()[0]
        assert json.loads(stored) == ['Alt One', 'Alt Two']

    def test_boxart_source_popped_and_not_persisted(self, connection):
        """`_boxart_source` is an internal tracking key — it must be removed
        from metadata before the UPDATE (no such column exists)."""
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id) VALUES (1)")
        connection.commit()
        c = connection.cursor()

        metadata = _full_metadata(boxart='cover.webp')
        metadata['_boxart_source'] = 'esde'
        # Must not raise (would if it tried to bind a non-existent column).
        hybrid_scraper._save_game_row(c, metadata, '[]', 1)
        connection.commit()
        assert '_boxart_source' not in metadata
