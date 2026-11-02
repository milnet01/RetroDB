# =============================================================================
# RETRODB - Steam Web API Scraper
# =============================================================================
# Functions for fetching game libraries and achievement data from Steam.
# Uses the Steam Web API: https://developer.valvesoftware.com/wiki/Steam_Web_API
# =============================================================================

import logging

import requests  # only for requests.exceptions.HTTPError reference

from . import service_limits
from .base_scraper import http_get

logger = logging.getLogger(__name__)

BASE_URL = 'https://api.steampowered.com'
STORE_URL = 'https://store.steampowered.com/api'
ART_URL = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps'
STORE_STOP_SECONDS = 300


def resolve_vanity_url(api_key, vanity_name):
    """Resolve a Steam vanity URL name to a 64-bit Steam ID.

    Args:
        api_key: Steam Web API key
        vanity_name: Custom URL name (e.g. 'gabelogannewell')

    Returns:
        str: 64-bit Steam ID, or None on failure
    """
    try:
        resp = http_get(f'{BASE_URL}/ISteamUser/ResolveVanityURL/v1/', params={
            'key': api_key,
            'vanityurl': vanity_name,
        }, timeout=15)
        if resp is None:
            return None
        resp.raise_for_status()
        data = resp.json().get('response', {})
        if data.get('success') == 1:
            return data.get('steamid')
        logger.warning(f"Steam vanity URL resolve failed: {data.get('message', 'Unknown error')}")
        return None
    except Exception as e:
        logger.error(f"Steam vanity URL resolve error: {e}")
        return None


def get_owned_games(api_key, steam_id):
    """Get all games owned by a Steam user.

    Args:
        api_key: Steam Web API key
        steam_id: 64-bit Steam ID

    Returns:
        list: Game dicts with keys: appid, name, playtime_forever,
              rtime_last_played, img_icon_url
    """
    try:
        resp = http_get(f'{BASE_URL}/IPlayerService/GetOwnedGames/v1/', params={
            'key': api_key,
            'steamid': steam_id,
            'include_appinfo': 1,
            'include_played_free_games': 1,
            'format': 'json',
        }, timeout=30)
        if resp is None:
            return []
        resp.raise_for_status()
        data = resp.json().get('response', {})
        games = data.get('games', [])
        logger.info(f"Steam: Fetched {len(games)} owned games for user {steam_id}")
        return games
    except Exception as e:
        logger.error(f"Steam get_owned_games error: {e}")
        return []


def get_player_achievements(api_key, steam_id, app_id):
    """Get a player's achievements for a specific game.

    Args:
        api_key: Steam Web API key
        steam_id: 64-bit Steam ID
        app_id: Steam app ID

    Returns:
        dict: {achievements: [...], total: int, earned: int} or None on error
    """
    try:
        resp = http_get(f'{BASE_URL}/ISteamUserStats/GetPlayerAchievements/v1/', params={
            'key': api_key,
            'steamid': steam_id,
            'appid': app_id,
            'l': 'english',
        }, timeout=15)
        if resp is None:
            return None

        if resp.status_code == 400:
            # Game has no achievements or profile is private
            return None

        resp.raise_for_status()
        data = resp.json().get('playerstats', {})

        if not data.get('success'):
            return None

        achievements = data.get('achievements', [])
        earned = sum(1 for a in achievements if a.get('achieved'))
        return {
            'achievements': achievements,
            'total': len(achievements),
            'earned': earned,
            'game_name': data.get('gameName', ''),
        }
    except requests.exceptions.HTTPError:
        return None
    except Exception as e:
        logger.error(f"Steam get_player_achievements error (app {app_id}): {e}")
        return None


def get_achievement_schema(api_key, app_id):
    """Get achievement definitions (names, descriptions, icons) for a game.

    Args:
        api_key: Steam Web API key
        app_id: Steam app ID

    Returns:
        list: Achievement schema dicts, or empty list on error
    """
    try:
        resp = http_get(f'{BASE_URL}/ISteamUserStats/GetSchemaForGame/v2/', params={
            'key': api_key,
            'appid': app_id,
            'l': 'english',
        }, timeout=15)
        if resp is None:
            return []
        resp.raise_for_status()
        data = resp.json().get('game', {})
        return data.get('availableGameStats', {}).get('achievements', [])
    except Exception as e:
        logger.error(f"Steam get_achievement_schema error (app {app_id}): {e}")
        return []


def get_player_summary(api_key, steam_id):
    """Get Steam player profile summary.

    Args:
        api_key: Steam Web API key
        steam_id: 64-bit Steam ID

    Returns:
        dict: Player profile data, or None on error
    """
    try:
        resp = http_get(f'{BASE_URL}/ISteamUser/GetPlayerSummaries/v2/', params={
            'key': api_key,
            'steamids': steam_id,
        }, timeout=15)
        if resp is None:
            return None
        resp.raise_for_status()
        players = resp.json().get('response', {}).get('players', [])
        if players:
            return players[0]
        return None
    except Exception as e:
        logger.error(f"Steam get_player_summary error: {e}")
        return None


def get_app_details(app_id):
    """Get store page details for a Steam app (no API key needed).

    Args:
        app_id: Steam app ID

    Returns:
        dict: App details including header_image, or None on error, when the
        store has no such app, or when the store has said stop.
    """
    if not service_limits.wait_for_turn(service_limits.STEAM_STORE):
        return None
    try:
        resp = http_get(f'{STORE_URL}/appdetails', params={
            'appids': app_id,
            'l': 'english',
        }, timeout=15)
        if resp is None:
            return None
        if resp.status_code in (403, 429):
            service_limits.stop(service_limits.STEAM_STORE, STORE_STOP_SECONDS)
            return None
        resp.raise_for_status()
        data = resp.json()
        app_data = data.get(str(app_id), {})
        if app_data.get('success'):
            return app_data.get('data')
        return None
    except Exception as e:
        logger.error(f"Steam get_app_details error (app {app_id}): {e}")
        return None


def box_art_urls(app_id):
    """Addresses to try for an app's upright cover, best first. The store's
    reply does not name them, and a newer app may keep them elsewhere."""
    return [f'{ART_URL}/{app_id}/library_600x900_2x.jpg',
            f'{ART_URL}/{app_id}/library_600x900.jpg']


def fanart_urls(app_id, details):
    """Addresses to try for wide background art, best first."""
    return [url for url in (f'{ART_URL}/{app_id}/library_hero.jpg',
                            details.get('background_raw')) if url]
