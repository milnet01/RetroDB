# =============================================================================
# RETRODB - PSN session keep-alive (Pass 50.1)
# =============================================================================
# The PSN refresh token lasts ~2 months, and PSNAWP rotates it (with a fresh
# ~2-month window) on every authenticated call. RetroDB otherwise only refreshes
# on demand — when a sync runs — so a user who syncs infrequently lets the window
# lapse and is forced to re-paste their NPSSO through the whole browser wizard.
#
# This daily background task re-arms each user's session *before* it expires, so
# NPSSO re-entry becomes rare-to-never while the app is running.
#
# It NEVER pings Sony for a session that has already expired (the refresh would
# fail and an NPSSO ping with a stale cookie is pointless / could flag the
# account). It only touches sessions in the window `now < expiry <= threshold`
# — still valid, but approaching the edge. Already-expired sessions are left for
# the user to re-link (the Settings banner / dashboard notice handles prompting).
# =============================================================================

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Refresh a session once its refresh token drops below this many days of runway.
# The window is ~60 days; a daily check with a 14-day threshold re-arms a live
# session roughly once every ~6-7 weeks — minimal Sony traffic, never lapses.
KEEPALIVE_THRESHOLD_DAYS = 14
_TICK_SECONDS = 24 * 3600
_STARTUP_DELAY_SECONDS = 60  # let startup/migrations settle before the first tick

_started = False
_lock = threading.Lock()


def run_psn_keepalive(threshold_days=KEEPALIVE_THRESHOLD_DAYS, now=None):
    """Refresh every user's PSN session that is still valid but within
    `threshold_days` of its refresh-token expiry.

    MUST be called inside a Flask app context (uses query()/execute() via the
    token helpers). Returns a (checked, refreshed, failed, skipped_expired) tuple
    for logging/tests.
    """
    # Deferred imports: this module is imported at app-start but the heavy
    # PSN/route deps shouldn't load unless the tick actually runs.
    from services.database import query
    from services.platform_tokens import load_tokens
    from routes.trophies import create_psn_client, PSNAWP_AVAILABLE

    if not PSNAWP_AVAILABLE:
        return (0, 0, 0, 0)

    now = time.time() if now is None else now
    deadline = now + threshold_days * 86400

    try:
        rows = query(
            "SELECT upt.user_id AS uid, us.psn_npsso AS npsso "
            "FROM user_platform_tokens upt "
            "LEFT JOIN user_settings us ON us.user_id = upt.user_id "
            "WHERE upt.platform = 'psn'"
        )
    except Exception as e:
        logger.warning("PSN keep-alive: could not list PSN users: %s", e)
        return (0, 0, 0, 0)

    checked = refreshed = failed = skipped_expired = 0
    for row in rows:
        uid = row['uid']
        npsso = (row['npsso'] or '').strip()
        tokens = load_tokens(uid, 'psn')
        if not tokens:
            continue
        exp = tokens.get('refresh_token_expires_at', 0) or 0
        if exp <= now:
            # Already expired — DO NOT ping. The user must re-enter NPSSO.
            skipped_expired += 1
            continue
        if exp > deadline:
            continue  # plenty of runway; leave it untouched
        # now < exp <= deadline → still valid, approaching expiry → re-arm it.
        checked += 1
        if not npsso:
            # No NPSSO stored to construct the client; can't refresh this one.
            logger.info(
                "PSN keep-alive: user %s near expiry but no NPSSO stored", uid
            )
            failed += 1
            continue
        # allow_npsso_fallback=False → refresh-token path only; never pings with
        # a (possibly stale) NPSSO even if the cached refresh fails.
        _client, err = create_psn_client(
            npsso, user_id=uid, allow_npsso_fallback=False
        )
        if err:
            logger.info("PSN keep-alive: user %s refresh failed: %s", uid, err)
            failed += 1
        else:
            refreshed += 1
            logger.info("PSN keep-alive: refreshed session for user %s", uid)

    if checked or skipped_expired:
        logger.info(
            "PSN keep-alive: %d in-window, %d refreshed, %d failed, "
            "%d already-expired (left for re-link)",
            checked, refreshed, failed, skipped_expired,
        )
    return (checked, refreshed, failed, skipped_expired)


def start_psn_keepalive_thread(app):
    """Start the daily PSN keep-alive daemon. Idempotent within a process.

    `app` is the Flask app; each tick runs inside `app.app_context()` so the
    DB helpers (query/execute via get_request_db) work off the request path.
    """
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def _loop():
        time.sleep(_STARTUP_DELAY_SECONDS)
        while True:
            try:
                with app.app_context():
                    run_psn_keepalive()
            except Exception as e:  # never let the daemon die on one bad tick
                logger.error("PSN keep-alive tick failed: %s", e, exc_info=True)
            time.sleep(_TICK_SECONDS)

    t = threading.Thread(target=_loop, name="psn-keepalive", daemon=True)
    t.start()
    logger.info(
        "PSN keep-alive thread started (every %dh, %d-day refresh threshold)",
        _TICK_SECONDS // 3600, KEEPALIVE_THRESHOLD_DAYS,
    )
