# =============================================================================
# RETRODB - PSN session keep-alive (Pass 50.1)
# =============================================================================
# PSNAWP renews the PSN sign-in with the refresh token once the access token has
# run out, and Sony replaces the refresh token each time. RetroDB otherwise only
# renews on demand, when a sync runs.
#
# This daily background task renews each user's sign-in as it nears expiry. Whether
# that buys more time is Sony's call: Sony's refresh token lasts 10 days and a
# renewal does not move that date (PASS-59-226, PASS-59-111). A lapsed session
# signs in again from the NPSSO on the next sync; this task never uses the
# NPSSO. Renewing from a copy of the database can use up the live row's
# refresh token: Sony then refuses it, and the row is marked expired.
#
# It NEVER pings Sony for a session that has already expired (the refresh would
# fail and an NPSSO ping with a stale cookie is pointless / could flag the
# account). It only touches sessions in the window `now < expiry <= threshold`
# — still valid, but approaching the edge. Already-expired sessions are left for
# the next sync, which signs in from the NPSSO; the Settings and dashboard
# banners speak up only if Sony refuses that NPSSO.
# =============================================================================

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Refresh a session once its refresh token drops below this many days of runway.
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
            "%d already-expired (left for the next sync)",
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
