# =============================================================================
# SERVICE LIMITS (PASS-59-215)
# =============================================================================
# How fast each online service may be called, and which have told RetroDB to
# stop. One process holds this in memory, so a stop reaches every job and
# search at once, and a restart forgets it: the next call asks again, and a
# service still at its limit says so once more.
#
# A stopped service's sender returns its usual "nothing" without calling, so
# scrapers need no new return shape. Whoever must tell "no answer" from "no
# such game" asks stopped().
# =============================================================================

import logging
import threading
import time

logger = logging.getLogger(__name__)

SCREENSCRAPER = 'screenscraper'
THEGAMESDB = 'tgdb'
RAWG = 'rawg'
IGDB = 'igdb'
MOBYGAMES = 'mobygames'
HOWLONGTOBEAT = 'hltb'
STEAM_STORE = 'steam_store'
GEMINI = 'gemini'
OPENAI = 'openai'
CLAUDE = 'claude'

NAMES = {
    SCREENSCRAPER: 'ScreenScraper',
    THEGAMESDB: 'TheGamesDB',
    RAWG: 'RAWG',
    IGDB: 'IGDB',
    MOBYGAMES: 'MobyGames',
    HOWLONGTOBEAT: 'HowLongToBeat',
    STEAM_STORE: 'Steam',
    GEMINI: 'Gemini',
    OPENAI: 'OpenAI',
    CLAUDE: 'Claude',
}

# The services a game scrape searches.
SCRAPE_SOURCES = (SCREENSCRAPER, THEGAMESDB, RAWG, IGDB, MOBYGAMES)
# The AI providers, named as scraper_settings.json's ai_provider names them.
AI_SOURCES = (GEMINI, OPENAI, CLAUDE)

# Why a service stopped. Words for each are in services/service_stop_text.py.
LIMIT_REACHED = 'limit_reached'
KEY_REFUSED = 'key_refused'
KEY_REJECTED = 'key_rejected'
PAYMENT_NEEDED = 'payment_needed'
UNAVAILABLE = 'unavailable'  # not answering; waiting will help

# Seconds between calls. IGDB's limit is 4 a second. ScreenScraper's replies
# state the account's own rate, which replaces this figure. RAWG and
# HowLongToBeat publish no rate. TheGamesDB limits only the month's total.
# Steam's store documents neither the call nor a limit; about 200 calls in five
# minutes is the figure usually reported, unchecked, and this keeps within it.
# MobyGames states its rate in every reply (PASS-59-183); five seconds is what
# it gave a Hobbyist key on 2026-11-21, used until the first reply says more,
# plus the half-second margin scrape_mobygames.PACE_MARGIN explains.
_DEFAULT_PACE = {
    SCREENSCRAPER: 0.1,
    RAWG: 0.3,
    IGDB: 0.26,
    MOBYGAMES: 5.5,
    HOWLONGTOBEAT: 1.0,
    STEAM_STORE: 1.5,
}
SLOWEST_PACE = 8.0

_lock = threading.Lock()
_pace = dict(_DEFAULT_PACE)
_next_turn = {}
_stops = {}
_slowed = set()


def stop(source, seconds, reason=LIMIT_REACHED):
    """Make no more calls to this service for this many seconds."""
    until = time.time() + seconds
    with _lock:
        known = _stops.get(source)
        _stops[source] = {'until': until, 'reason': reason}
    if not known:
        logger.warning('%s: stopped calling for %d minutes (%s)',
                       NAMES.get(source, source), seconds // 60, reason)


def stopped(source):
    """The stop in force for this service as {'until', 'reason'}, or None."""
    with _lock:
        entry = _stops.get(source)
        if entry and entry['until'] <= time.time():
            del _stops[source]
            return None
        return dict(entry) if entry else None


def wait_for_turn(source):
    """Hold a call until its turn. False when the service has said stop."""
    if stopped(source):
        return False
    take_turn(source)
    return True


def take_turn(source):
    """Hold a call until its turn, whatever stop is in force. For the Settings
    and Dashboard checks, which must not make the next scrape too soon."""
    gap = _pace.get(source, 0)
    if gap <= 0:
        return
    # Take the next free slot under the lock and sleep outside it, so one
    # service's wait never holds up another's.
    with _lock:
        now = time.monotonic()
        turn = max(now, _next_turn.get(source, 0.0))
        _next_turn[source] = turn + gap
    if turn > now:
        time.sleep(turn - now)


def gap_from_now(source):
    """Start the next call's gap now, for a service that counts it from the
    reply (MobyGames, PASS-59-183 §4.2) rather than from when the call left."""
    with _lock:
        now = time.monotonic()
        _next_turn[source] = max(_next_turn.get(source, 0.0), now + _pace.get(source, 0))


def set_pace(source, seconds):
    """Use the pace a service states, unless it has since said too fast."""
    with _lock:
        if source not in _slowed:
            _pace[source] = seconds


def slow_down(source):
    """A service said too fast: double the gap, up to SLOWEST_PACE."""
    with _lock:
        _slowed.add(source)
        _pace[source] = min(max(_pace.get(source, 0) * 2, 0.5), SLOWEST_PACE)


def clear_stops():
    """Lift every stop, after keys are saved. The line stays: a call already
    waiting its turn would otherwise be refused for one sent at once."""
    with _lock:
        _stops.clear()


def clear():
    """Forget every stop and pace. For tests."""
    with _lock:
        _pace.clear()
        _pace.update(_DEFAULT_PACE)
        _next_turn.clear()
        _stops.clear()
        _slowed.clear()
