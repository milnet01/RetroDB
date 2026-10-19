# =============================================================================
# Migration 017 — AI summary of regional-version differences (PASS-59-107)
# =============================================================================
# Additive only: four columns on `version_groups` holding the AI-written
# summary of how a group's versions differ. `ai_summary_members` is the
# member ids the summary was written for, so a group whose members change
# hides it until it is written again (services/version_groups.py).
# =============================================================================

import logging

from services.migrations._helpers import _add_column_if_missing, _table_exists

logger = logging.getLogger(__name__)


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'version_groups'):
        return
    for column in ('ai_summary', 'ai_summary_members', 'ai_summary_at', 'ai_summary_provider'):
        _add_column_if_missing(cursor, 'version_groups', column, 'TEXT')
    logger.info("version_groups AI summary columns added")
