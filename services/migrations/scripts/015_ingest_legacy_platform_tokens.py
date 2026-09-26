# =============================================================================
# Migration 015 — finish migration 006's legacy token ingest (Pass 59.44)
# =============================================================================
# Migration 006 looked for `psn_tokens.json` / `xbox_tokens.json` beside the
# database file. On the shipped layout the database is `<BASE>/database/roms.db`
# and the token files are in `<BASE>/data/`, so 006 never found them: nothing
# was ingested, and the plaintext OAuth token files stayed on disk.
#
# 006 is landed and immutable (docs/specs/migrations.md §4), so this repeats
# the ingest correctly:
#   * it probes the database's own directory AND a sibling `data/` directory;
#   * it never overwrites a row the user has saved since (INSERT OR IGNORE);
#   * it RENAMES an ingested file instead of deleting it. The runner owns the
#     transaction, so a later failure rolls the INSERT back — a deleted file
#     would then be lost, a renamed one is still recoverable.
#
# It deliberately does not import `config`: tests migrate throwaway databases,
# and a config-derived path would point every test run at the real `data/`.
# =============================================================================

import json
import logging
import os

from services.migrations._helpers import _admin_user_id, _table_exists

logger = logging.getLogger(__name__)

_LEGACY_FILES = (('psn_tokens.json', 'psn'), ('xbox_tokens.json', 'xbox'))
MIGRATED_SUFFIX = '.migrated-015'


def _candidate_dirs(cursor):
    """The database's directory, then its sibling `data/` directory."""
    row = cursor.execute("PRAGMA database_list").fetchone()
    db_path = row[2] if row else None
    if not db_path:
        return []
    db_dir = os.path.dirname(os.path.abspath(db_path))
    dirs = [db_dir, os.path.join(os.path.dirname(db_dir), 'data')]
    return list(dict.fromkeys(dirs))


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'user_platform_tokens'):
        return
    admin_id = _admin_user_id(cursor)
    if admin_id is None:
        return

    for directory in _candidate_dirs(cursor):
        for filename, platform in _LEGACY_FILES:
            path = os.path.join(directory, filename)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                json.loads(raw)  # validate; store the original text
            except (OSError, ValueError) as e:
                logger.warning("Could not ingest %s: %s", path, e)
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO user_platform_tokens (user_id, platform, tokens) "
                "VALUES (?, ?, ?)",
                (admin_id, platform, raw),
            )
            try:
                os.replace(path, path + MIGRATED_SUFFIX)
                logger.info("Ingested %s into user_platform_tokens (user=%d); kept as %s",
                            path, admin_id, path + MIGRATED_SUFFIX)
            except OSError as e:
                logger.warning("Ingested %s but could not rename it: %s", path, e)
