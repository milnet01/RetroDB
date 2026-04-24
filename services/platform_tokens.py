# =============================================================================
# RETRODB - Per-user platform OAuth token store (Pass 27.2)
# =============================================================================
# PSN and Xbox sync used to share one JSON file each (data/psn_tokens.json,
# data/xbox_tokens.json) — installs with multiple users leaked the first user
# to authenticate to everyone else. Tokens now live in the
# `user_platform_tokens` table keyed by `(user_id, platform)`; this module is
# the single shared accessor so adding a third platform (Steam OAuth, etc.)
# only needs to wire a new value through these helpers.
#
# Tokens are stored as JSON-encoded text. The threat model matches the legacy
# files: the DB is 0o600 on disk so plaintext storage is acceptable. If a
# future hardening pass adds at-rest encryption, swap json.dumps/json.loads
# below for the encrypted equivalents — call sites do not need to change.
# =============================================================================

import json
import logging

from services.database import query, execute

logger = logging.getLogger(__name__)


def load_tokens(user_id, platform):
    """Return the cached OAuth token dict for (user_id, platform), or None.

    Args:
        user_id: integer users.id of the owner.
        platform: 'psn' or 'xbox'.
    """
    if not user_id:
        return None
    row = query(
        "SELECT tokens FROM user_platform_tokens WHERE user_id = ? AND platform = ?",
        (user_id, platform), one=True,
    )
    if not row:
        return None
    try:
        return json.loads(row['tokens'])
    except (TypeError, ValueError) as e:
        logger.warning("Could not decode %s tokens for user=%d: %s", platform, user_id, e)
        return None


def save_tokens(user_id, platform, tokens):
    """Persist an OAuth token dict for (user_id, platform), replacing any prior."""
    if not user_id:
        logger.warning("save_tokens called with no user_id (platform=%s) — refusing", platform)
        return
    payload = json.dumps(dict(tokens))
    execute(
        "INSERT INTO user_platform_tokens (user_id, platform, tokens, updated_at) "
        "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
        "ON CONFLICT(user_id, platform) DO UPDATE SET "
        "    tokens = excluded.tokens, "
        "    updated_at = excluded.updated_at",
        (user_id, platform, payload),
    )


def clear_tokens(user_id, platform):
    """Remove the cached tokens for (user_id, platform)."""
    if not user_id:
        return
    execute(
        "DELETE FROM user_platform_tokens WHERE user_id = ? AND platform = ?",
        (user_id, platform),
    )
