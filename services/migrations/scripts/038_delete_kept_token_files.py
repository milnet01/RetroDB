# =============================================================================
# Migration 038 — delete the plaintext token files migration 015 kept (PASS-59-240)
# =============================================================================
# 015 ingested `psn_tokens.json` / `xbox_tokens.json` into user_platform_tokens
# and renamed each to `<name>.migrated-015` rather than deleting it, so a
# rolled-back INSERT could not lose the token. Those files still hold plaintext
# OAuth tokens and nothing ever removed them.
#
# A kept file is deleted only when user_platform_tokens already holds a row for
# its platform: that row was committed by an earlier run, so the file is not
# the only copy. With no row the file may be the only copy, and stays.
#
# Like 015 it does not import `config`: the directories come from the
# database's own path, so a test's throwaway database never reaches `data/`.
# =============================================================================

import logging
import os

from services.migrations._helpers import _table_exists

logger = logging.getLogger(__name__)

_KEPT_FILES = (('psn_tokens.json.migrated-015', 'psn'),
               ('xbox_tokens.json.migrated-015', 'xbox'))


def _candidate_dirs(cursor):
    """The database's directory, then its sibling `data/` directory (as 015)."""
    row = cursor.execute("PRAGMA database_list").fetchone()
    db_path = row[2] if row else None
    if not db_path:
        return []
    db_dir = os.path.dirname(os.path.abspath(db_path))
    return list(dict.fromkeys([db_dir, os.path.join(os.path.dirname(db_dir), 'data')]))


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'user_platform_tokens'):
        return
    for directory in _candidate_dirs(cursor):
        for filename, platform in _KEPT_FILES:
            path = os.path.join(directory, filename)
            if not os.path.isfile(path):
                continue
            stored = cursor.execute(
                "SELECT 1 FROM user_platform_tokens WHERE platform = ? LIMIT 1",
                (platform,)).fetchone()
            if not stored:
                logger.warning("Kept %s: no %s token is in the database, so it may "
                               "be the only copy", path, platform)
                continue
            try:
                os.remove(path)
                logger.info("Deleted %s; its token is in user_platform_tokens", path)
            except OSError as e:
                logger.warning("Could not delete %s: %s", path, e)
