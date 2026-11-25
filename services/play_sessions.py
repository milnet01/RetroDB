# =============================================================================
# RETRODB - The end of a Play-button session
# =============================================================================
# PASS-59-332 §4.3. LocalLauncher's stderr thread calls session_ended() once
# the emulator has exited. It works out whether the session showed real
# play — a save file changed (the built-in player only) or a
# RetroAchievement was earned during it — and hands the session to
# services/game_status.py, which applies the rule.
# =============================================================================

import logging
from datetime import datetime, timezone

from services import game_status
from services.database import query

logger = logging.getLogger(__name__)

# RetroAchievements stamps an unlock when its server hears of it, which can
# trail the moment in the game by a little.
_RA_LATE_S = 120


def session_ended(entry, ended_at: float) -> None:
    """Record the session a registry entry ran. Raises nothing it can
    catch: a failure is logged and the session skipped (INV-8)."""
    h = entry.handle
    seconds = max(0, int(ended_at - h.started_at))
    save_changed = bool(entry.save_check and entry.save_check())
    achievement = (not save_changed and seconds >= game_status.MIN_PLAY_SECONDS
                   and _achievement_earned(entry.user_id, h.game_id, h.started_at, ended_at))
    result = game_status.record_session(entry.user_id, h.game_id, h.emulator_id,
                                        h.started_at, seconds, save_changed, achievement)
    if result == 'moved':
        from services.analytics import invalidate_analytics_cache
        invalidate_analytics_cache()
    logger.info("play session game=%s user=%s seconds=%s save=%s achievement=%s -> %s",
                h.game_id, entry.user_id, seconds, save_changed, achievement, result)


def _achievement_earned(user_id, game_id, started_at, ended_at) -> bool:
    """True when the person's RetroAchievements account shows an unlock for
    this game inside the session. No link, no account or no answer: False."""
    game = query("SELECT ra_game_id FROM games WHERE id = ?", (game_id,), one=True)
    creds = query("SELECT ra_username, ra_api_key FROM user_settings WHERE user_id = ?",
                  (user_id,), one=True)
    if not (game and game['ra_game_id'] and creds
            and creds['ra_username'] and creds['ra_api_key']):
        return False
    from scraper.retroachievements import get_user_game_progress_custom
    try:
        progress = get_user_game_progress_custom(game['ra_game_id'], creds['ra_username'],
                                                 creds['ra_api_key'])
    except Exception as e:
        logger.warning("RetroAchievements did not answer for game %s: %s", game_id, e)
        return False
    for ach in (progress or {}).get('achievements', []):
        for stamp in (ach.get('date_earned'), ach.get('date_earned_hardcore')):
            when = _ra_time(stamp)
            if when is not None and started_at <= when <= ended_at + _RA_LATE_S:
                return True
    return False


def _ra_time(stamp):
    """RetroAchievements' 'YYYY-MM-DD HH:MM:SS' (UTC) as epoch seconds."""
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S').replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
