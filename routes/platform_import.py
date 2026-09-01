# =============================================================================
# RETRODB - Platform Import Blueprint (Steam, Xbox & PSN)
# =============================================================================
# Handles importing game libraries and achievement data from Steam, Xbox, and PSN.
#
# Routes:
#   GET  /platform-import                  - Import page
#   POST /api/steam/fetch-library          - Fetch Steam library
#   POST /api/steam/import                 - Import selected Steam games
#   POST /api/steam/sync-achievements      - Bulk achievement sync (background)
#   GET  /api/steam/sync-status            - Achievement sync job status
#   POST /api/steam/cancel-sync            - Cancel achievement sync
#   GET  /api/xbox/auth-url                - Get Xbox OAuth URL
#   GET  /api/xbox/callback                - Xbox OAuth callback
#   GET  /api/xbox/status                  - Check Xbox auth status
#   POST /api/xbox/disconnect              - Disconnect Xbox account
#   POST /api/xbox/fetch-library           - Fetch Xbox library
#   POST /api/xbox/import                  - Import selected Xbox games
#   POST /api/xbox/sync-achievements       - Bulk achievement sync (background)
#   GET  /api/xbox/sync-status             - Achievement sync job status
#   POST /api/xbox/cancel-sync             - Cancel achievement sync
#   GET  /api/psn/import/status            - Check PSN import readiness
#   POST /api/psn/fetch-library            - Fetch PSN game library
#   POST /api/psn/import                   - Import selected PSN games
# =============================================================================

import os
import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, redirect, url_for, g, session as flask_session
from flask_babel import gettext as _
import secrets as _secrets

import config
from services.achievement_linking import normalize_title_for_dedup as normalize_title
from services.database import get_db, query, execute
from services.auth import login_required, editor_required
from routes.scraper import get_saved_api_keys

logger = logging.getLogger(__name__)

bp = Blueprint('platform_import', __name__)


# =============================================================================
# HELPERS
# =============================================================================

def _ensure_system_exists(folder, name=None):
    """Ensure a system exists in the DB, auto-creating if needed.

    Returns:
        dict: {id, name, folder} or None
    """
    row = query("SELECT id, name, folder FROM systems WHERE folder = ?", (folder,), one=True)
    if row:
        return dict(row)

    system_name = name or config.SYSTEM_NAME_MAP.get(folder, folder.upper())
    logo = f"{folder}.png" if os.path.isfile(
        os.path.join(config.IMAGE_PATH, 'systems', f'{folder}.png')) else None
    try:
        execute("INSERT OR IGNORE INTO systems (name, folder, logo) VALUES (?, ?, ?)",
                (system_name, folder, logo))
        row = query("SELECT id, name, folder FROM systems WHERE folder = ?", (folder,), one=True)
        if row:
            logger.info(f"Platform Import: Auto-created system '{system_name}' (folder: {folder})")
            return dict(row)
    except Exception as e:
        logger.warning(f"Platform Import: Failed to auto-create system '{folder}': {e}")
    return None


def _check_duplicate(title, system_id, platform_field=None, platform_value=None):
    """Check if a game already exists by platform ID or normalized title.

    Args:
        title: Game title to check
        system_id: System ID to check against
        platform_field: Column name for platform-specific ID (e.g. 'steam_app_id')
        platform_value: Value of the platform-specific ID

    Returns:
        int or None: Existing game_id if found, else None
    """
    # 1. Exact platform ID match
    if platform_field and platform_value:
        allowed_fields = ('steam_app_id', 'xbox_title_id', 'psn_npwr_id')
        if platform_field not in allowed_fields:
            return None
        row = query(f"SELECT id FROM games WHERE {platform_field} = ?", (platform_value,), one=True)
        if row:
            return row['id']

    # 2. Normalized title match on same system
    norm = normalize_title(title)
    if norm and system_id:
        games = query("SELECT id, title FROM games WHERE system_id = ?", (system_id,))
        for game in games:
            if normalize_title(game['title']) == norm:
                return game['id']

    return None


# =============================================================================
# IMPORT PAGE
# =============================================================================

@bp.route('/platform-import')
@login_required
def platform_import():
    """Steam & Xbox Import — redirect to unified Game Imports page."""
    return redirect(url_for('game_imports.game_imports_page', tab='steam'))


# =============================================================================
# STEAM ENDPOINTS
# =============================================================================

@bp.route('/api/steam/fetch-library', methods=['POST'])
@login_required
def api_steam_fetch_library():
    """Fetch the user's Steam library with duplicate detection."""
    from scraper.scrape_steam import get_owned_games, get_player_summary, resolve_vanity_url

    # Per-user, not install-wide. This read get_saved_api_keys(), which
    # resolves the SHARED scraper_settings.json -- so whichever household
    # member's Steam credentials were in that blob were used for every
    # caller's library fetch, and a user whose credentials live only in
    # user_settings got "not configured" here while their sync job worked.
    # auth.md calls the RA fallback the only install-wide read permitted.
    # services/jobs/platform_sync.py::_get_steam_credentials is the correct
    # helper and two other call sites already use it.
    from services.jobs.platform_sync import _get_steam_credentials
    steam_api_key, steam_id = _get_steam_credentials(user_id=g.user['id'])

    # Allow overriding from request body
    data = request.get_json() or {}
    steam_api_key = data.get('steam_api_key') or steam_api_key
    steam_id = data.get('steam_id') or steam_id

    if not steam_api_key:
        return jsonify({'success': False, 'error': _('Steam API key not configured. Add it in Settings → API Keys.')}), 400
    if not steam_id:
        return jsonify({'success': False, 'error': _('Steam ID not configured. Add it in Settings → API Keys.')}), 400

    # Resolve vanity URL if not numeric
    if not steam_id.isdigit():
        resolved = resolve_vanity_url(steam_api_key, steam_id)
        if not resolved:
            return jsonify({'success': False, 'error': _('Could not resolve Steam vanity URL "%(steam_id)s". Use your 17-digit Steam ID instead.') % {'steam_id': steam_id}}), 400
        steam_id = resolved

    # Fetch library
    games = get_owned_games(steam_api_key, steam_id)
    if not games:
        return jsonify({'success': False, 'error': _('No games found. Check that your Steam profile and game details are set to Public.')})

    # Fetch profile info
    profile = get_player_summary(steam_api_key, steam_id)

    # Ensure "windows" system exists
    system = _ensure_system_exists('windows', 'Microsoft Windows')
    system_id = system['id'] if system else None

    # Check duplicates for each game
    result_games = []
    for game in games:
        app_id = str(game.get('appid', ''))
        name = game.get('name', '')
        playtime = game.get('playtime_forever', 0)
        last_played = game.get('rtime_last_played', 0)

        existing_id = _check_duplicate(name, system_id, 'steam_app_id', app_id)

        result_games.append({
            'appid': app_id,
            'name': name,
            'playtime': playtime,
            'last_played': last_played,
            'already_imported': existing_id is not None,
            'existing_game_id': existing_id,
            'icon_url': f"https://media.steampowered.com/steamcommunity/public/images/apps/{app_id}/{game.get('img_icon_url', '')}.jpg" if game.get('img_icon_url') else None,
        })

    # Sort by name
    result_games.sort(key=lambda g: g['name'].lower())

    return jsonify({
        'success': True,
        'games': result_games,
        'total': len(result_games),
        'already_imported': sum(1 for g in result_games if g['already_imported']),
        'profile': {
            'personaname': profile.get('personaname', '') if profile else '',
            'avatarfull': profile.get('avatarfull', '') if profile else '',
            'steamid': steam_id,
        } if profile else None,
    })


@bp.route('/api/steam/import', methods=['POST'])
@editor_required
def api_steam_import():
    """Import selected Steam games into the library."""
    data = request.get_json(silent=True) or {}
    selected_games = data.get('games', [])

    if not selected_games:
        return jsonify({'success': False, 'error': _('No games selected')})

    # Ensure "windows" system exists
    system = _ensure_system_exists('windows', 'Microsoft Windows')
    if not system:
        return jsonify({'success': False, 'error': _('Could not create Windows system entry')})

    system_id = system['id']
    imported = 0
    skipped = 0
    failed = 0

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        # Build lookup for duplicate detection
        existing_steam_ids = set()
        existing_norm = set()
        for row in c.execute("SELECT steam_app_id, title, system_id FROM games").fetchall():
            if row['steam_app_id']:
                existing_steam_ids.add(row['steam_app_id'])
            existing_norm.add((normalize_title(row['title']), row['system_id']))

        for game in selected_games:
            try:
                app_id = str(game.get('appid', ''))
                title = game.get('name', '').strip()
                if not title:
                    failed += 1
                    continue

                # Check duplicates
                if app_id in existing_steam_ids:
                    skipped += 1
                    continue
                if (normalize_title(title), system_id) in existing_norm:
                    skipped += 1
                    continue

                # Generate rom_path
                rom_path = f"steam_import/windows/{app_id}"

                c.execute("""
                    INSERT INTO games (
                        title, system_id, rom_path, scraped,
                        steam_app_id, created_at
                    ) VALUES (?, ?, ?, 0, ?, ?)
                """, (
                    title,
                    system_id,
                    rom_path,
                    app_id,
                    datetime.now(timezone.utc).isoformat(),
                ))

                imported += 1
                existing_steam_ids.add(app_id)
                existing_norm.add((normalize_title(title), system_id))

            except Exception as e:
                logger.error(f"Steam Import: Failed to import '{game.get('name')}': {e}")
                failed += 1

        conn.commit()

        logger.info(f"Steam Import complete: {imported} imported, {skipped} skipped, {failed} failed")

        return jsonify({
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
        })

    except Exception as e:
        logger.error(f"Steam Import error: {e}")
        return jsonify({'success': False, 'error': _('An internal error occurred')})
    finally:
        if conn:
            conn.close()


@bp.route('/api/steam/sync-achievements', methods=['POST'])
@editor_required
def api_steam_sync_achievements():
    """Start bulk Steam achievement sync (background job).

    Pass 31.4 — editor-gated; uses the caller's stored Steam credentials.
    """
    from services.jobs import steam_sync_job
    result = steam_sync_job.start(user_id=g.user['id'])
    return jsonify(result)


@bp.route('/api/steam/sync-status')
@login_required
def api_steam_sync_status():
    """Get Steam achievement sync job status."""
    from services.jobs import steam_sync_job
    return jsonify(steam_sync_job.get_status())


# Cancelling a sync is the same privilege as starting one (both are
# @editor_required's `scrape` surface); at @login_required a viewer could
# cancel an editor's running import. The museum sibling already gates its
# cancel this way.
@bp.route('/api/steam/cancel-sync', methods=['POST'])
@editor_required
def api_steam_cancel_sync():
    """Cancel the Steam achievement sync."""
    from services.jobs import steam_sync_job
    return jsonify(steam_sync_job.cancel())


# =============================================================================
# XBOX ENDPOINTS
# =============================================================================

@bp.route('/api/xbox/auth-url')
@login_required
def api_xbox_auth_url():
    """Generate the Xbox OAuth authorization URL."""
    from scraper.scrape_xbox import get_auth_url

    api_keys = get_saved_api_keys()
    client_id = api_keys.get('xbox_client_id', '')

    if not client_id:
        return jsonify({'success': False, 'error': _('Xbox Client ID not configured. Add it in Settings → API Keys.')})

    # Pass 24.6 — generate a CSRF-protection `state` token, stash it in
    # the caller's session, and include it in the Microsoft auth URL so
    # the callback can verify the flow originated here. Without this,
    # an attacker triggering /api/xbox/callback with their own `code`
    # would bind the victim's RetroDB session to the attacker's MS account.
    # Pass 31.9 — bind the state to the issuing user's id so a logout/login
    # transition can't let user B's callback consume user A's pending state.
    state = _secrets.token_urlsafe(32)
    flask_session['oauth_state_xbox'] = {'state': state, 'user_id': g.user['id']}

    # Build redirect URI based on current request
    redirect_uri = request.host_url.rstrip('/') + '/api/xbox/callback'
    auth_url = get_auth_url(client_id, redirect_uri, state=state)

    return jsonify({'success': True, 'auth_url': auth_url})


@bp.route('/api/xbox/callback')
@login_required
def api_xbox_callback():
    """Handle Xbox OAuth callback."""
    from scraper.scrape_xbox import (
        exchange_code_for_tokens, authenticate_xbox_live, get_xsts_token,
        save_tokens, get_gamertag, _get_auth_header, attach_expires_at,
    )

    code = request.args.get('code')
    error = request.args.get('error')
    returned_state = request.args.get('state', '')

    if error:
        logger.error(f"Xbox OAuth error: {error} - {request.args.get('error_description', '')}")
        return redirect(url_for('game_imports.game_imports_page', tab='xbox', xbox_error=error))

    if not code:
        return redirect(url_for('platform_import.platform_import') + '?xbox_error=no_code')

    # Pass 24.6 — verify the state parameter matches what we stashed in
    # api_xbox_auth_url. Pop-and-compare so a replay attack can't reuse a
    # consumed state. hmac.compare_digest for timing-safe equality.
    # Pass 31.9 — the stash is now `{'state': ..., 'user_id': ...}` so the
    # callback also refuses to consume a state issued by a different user
    # on the same browser session (logout → new login re-race). Legacy
    # bare-string stashes from an in-flight upgrade degrade to a forced
    # state_mismatch, which is the safe behavior.
    import hmac as _hmac
    expected = flask_session.pop('oauth_state_xbox', None)
    expected_state = expected.get('state') if isinstance(expected, dict) else None
    expected_user_id = expected.get('user_id') if isinstance(expected, dict) else None
    if (not expected_state
            or not returned_state
            or not _hmac.compare_digest(expected_state, returned_state)
            or expected_user_id != g.user['id']):
        logger.warning("Xbox OAuth callback rejected: state mismatch or user mismatch")
        return redirect(url_for('platform_import.platform_import') + '?xbox_error=state_mismatch')

    api_keys = get_saved_api_keys()
    client_id = api_keys.get('xbox_client_id', '')
    client_secret = api_keys.get('xbox_client_secret', '')

    redirect_uri = request.host_url.rstrip('/') + '/api/xbox/callback'

    # Exchange code for tokens
    tokens = exchange_code_for_tokens(client_id, client_secret, code, redirect_uri)
    if not tokens:
        return redirect(url_for('platform_import.platform_import') + '?xbox_error=token_exchange_failed')

    # Verify by authenticating with Xbox Live
    xbl_token, user_hash = authenticate_xbox_live(tokens.get('access_token', ''))
    if not xbl_token:
        return redirect(url_for('platform_import.platform_import') + '?xbox_error=xbl_auth_failed')

    xsts_token, xuid = get_xsts_token(xbl_token)
    if not xsts_token:
        return redirect(url_for('platform_import.platform_import') + '?xbox_error=xsts_auth_failed')

    # Get gamertag
    auth_header = _get_auth_header(user_hash, xsts_token)
    gamertag = get_gamertag(auth_header, xuid)

    # Store tokens and metadata
    tokens['xuid'] = xuid
    tokens['gamertag'] = gamertag
    tokens['connected_at'] = datetime.now(timezone.utc).isoformat()
    # Pass 45.12 — record the token's absolute expiry so subsequent calls
    # to get_authenticated_session can skip an unnecessary refresh.
    attach_expires_at(tokens)
    save_tokens(tokens, g.user['id'])

    logger.info(f"Xbox: Connected as {gamertag} (XUID: {xuid}, user={g.user['id']})")
    # Pass 41.7.B — pass `xbox_connected=1` as a kwarg to url_for so URL
    # construction is unambiguous. The previous `+ '&xbox_connected=1'`
    # string concat worked only because url_for happened to emit `?tab=xbox`
    # today; a future refactor that drops the query arg would have produced
    # `/game-imports&xbox_connected=1` (broken path).
    return redirect(url_for('game_imports.game_imports_page', tab='xbox', xbox_connected=1))


@bp.route('/api/xbox/status')
@login_required
def api_xbox_status():
    """Check if Xbox account is connected (Pass 27.2 — per current user)."""
    from scraper.scrape_xbox import load_tokens

    tokens = load_tokens(g.user['id'])
    if tokens and tokens.get('refresh_token'):
        return jsonify({
            'connected': True,
            'gamertag': tokens.get('gamertag', 'Unknown'),
            'xuid': tokens.get('xuid', ''),
            'connected_at': tokens.get('connected_at', ''),
        })
    return jsonify({'connected': False})


@bp.route('/api/xbox/disconnect', methods=['POST'])
@login_required
def api_xbox_disconnect():
    """Disconnect Xbox account (remove stored tokens for current user)."""
    from scraper.scrape_xbox import clear_tokens
    clear_tokens(g.user['id'])
    logger.info(f"Xbox: Account disconnected (user={g.user['id']})")
    return jsonify({'success': True})


@bp.route('/api/xbox/fetch-library', methods=['POST'])
@login_required
def api_xbox_fetch_library():
    """Fetch the user's Xbox game library with duplicate detection."""
    from scraper.scrape_xbox import get_authenticated_session, get_title_history, parse_title_platform

    api_keys = get_saved_api_keys()
    client_id = api_keys.get('xbox_client_id', '')
    client_secret = api_keys.get('xbox_client_secret', '')

    if not client_id or not client_secret:
        return jsonify({'success': False, 'error': _('Xbox credentials not configured. Add them in Settings → API Keys.')}), 400

    session = get_authenticated_session(client_id, client_secret, g.user['id'])
    if not session:
        return jsonify({'success': False, 'error': _('Xbox authentication failed. Please re-connect your Xbox account.')}), 401

    titles = get_title_history(session['auth_header'], session['xuid'])
    if not titles:
        return jsonify({'success': False, 'error': _('No games found in Xbox title history.')})

    # Build system lookup and ensure Xbox systems exist
    xbox_systems = {}
    for folder in ['xbox', 'xbox360', 'xboxone', 'xboxseriesx']:
        system = _ensure_system_exists(folder)
        if system:
            xbox_systems[folder] = system

    # Also ensure "windows" exists for PC Game Pass titles
    windows_system = _ensure_system_exists('windows', 'Microsoft Windows')
    if windows_system:
        xbox_systems['windows'] = windows_system

    result_games = []
    for title in titles:
        name = title.get('name', '')
        title_id = str(title.get('titleId', ''))
        if not name or not title_id:
            continue

        # Determine platform
        folder = parse_title_platform(title)
        if not folder or folder not in xbox_systems:
            folder = 'xboxone'  # Default fallback

        system = xbox_systems.get(folder)
        system_id = system['id'] if system else None

        # Check duplicates
        existing_id = _check_duplicate(name, system_id, 'xbox_title_id', title_id)

        # Extract achievement summary from title data
        achievement = title.get('achievement', {})
        total_achievements = achievement.get('totalGamerscore', 0)
        earned_achievements = achievement.get('currentGamerscore', 0)

        # Get image
        display_image = ''
        images = title.get('images', [])
        for img in images:
            if img.get('type') == 'BoxArt' or img.get('type') == 'Poster':
                display_image = img.get('url', '')
                break
        if not display_image and images:
            display_image = images[0].get('url', '')

        # Platform display name
        devices = title.get('devices', [])
        platform_display = ', '.join(devices) if devices else 'Xbox'

        result_games.append({
            'title_id': title_id,
            'name': name,
            'platform': folder,
            'platform_display': platform_display,
            'system_name': system['name'] if system else folder,
            'already_imported': existing_id is not None,
            'existing_game_id': existing_id,
            'total_gamerscore': total_achievements,
            'earned_gamerscore': earned_achievements,
            'image_url': display_image,
        })

    result_games.sort(key=lambda g: g['name'].lower())

    return jsonify({
        'success': True,
        'games': result_games,
        'total': len(result_games),
        'already_imported': sum(1 for g in result_games if g['already_imported']),
        'gamertag': session.get('gamertag', ''),
    })


@bp.route('/api/xbox/import', methods=['POST'])
@editor_required
def api_xbox_import():
    """Import selected Xbox games into the library."""
    data = request.get_json(silent=True) or {}
    selected_games = data.get('games', [])

    if not selected_games:
        return jsonify({'success': False, 'error': _('No games selected')})

    # Ensure all needed Xbox systems exist
    xbox_systems = {}
    for folder in ['xbox', 'xbox360', 'xboxone', 'xboxseriesx', 'windows']:
        system = _ensure_system_exists(folder)
        if system:
            xbox_systems[folder] = system

    imported = 0
    skipped = 0
    failed = 0

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        # Build lookup
        existing_xbox_ids = set()
        existing_norm = {}
        for row in c.execute("SELECT xbox_title_id, title, system_id FROM games").fetchall():
            if row['xbox_title_id']:
                existing_xbox_ids.add(row['xbox_title_id'])
            key = (normalize_title(row['title']), row['system_id'])
            existing_norm[key] = True

        for game in selected_games:
            try:
                title_id = str(game.get('title_id', ''))
                title = game.get('name', '').strip()
                platform = game.get('platform', 'xboxone')
                if not title:
                    failed += 1
                    continue

                system = xbox_systems.get(platform)
                if not system:
                    failed += 1
                    continue

                system_id = system['id']

                # Check duplicates
                if title_id in existing_xbox_ids:
                    skipped += 1
                    continue
                if (normalize_title(title), system_id) in existing_norm:
                    skipped += 1
                    continue

                rom_path = f"xbox_import/{platform}/{title_id}"

                c.execute("""
                    INSERT INTO games (
                        title, system_id, rom_path, scraped,
                        xbox_title_id, created_at
                    ) VALUES (?, ?, ?, 0, ?, ?)
                """, (
                    title,
                    system_id,
                    rom_path,
                    title_id,
                    datetime.now(timezone.utc).isoformat(),
                ))

                imported += 1
                existing_xbox_ids.add(title_id)
                existing_norm[(normalize_title(title), system_id)] = True

            except Exception as e:
                logger.error(f"Xbox Import: Failed to import '{game.get('name')}': {e}")
                failed += 1

        conn.commit()

        logger.info(f"Xbox Import complete: {imported} imported, {skipped} skipped, {failed} failed")

        return jsonify({
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
        })

    except Exception as e:
        logger.error(f"Xbox Import error: {e}")
        return jsonify({'success': False, 'error': _('An internal error occurred')})
    finally:
        if conn:
            conn.close()


@bp.route('/api/xbox/sync-achievements', methods=['POST'])
@editor_required
def api_xbox_sync_achievements():
    """Start bulk Xbox achievement sync (background job).

    Pass 27.3 — the starting user's id is passed to the job so
    `get_authenticated_session` reads that user's Xbox tokens, not
    whatever happened to be cached first on the install.
    """
    from services.jobs import xbox_sync_job
    result = xbox_sync_job.start(user_id=g.user['id'])
    return jsonify(result)


@bp.route('/api/xbox/sync-status')
@login_required
def api_xbox_sync_status():
    """Get Xbox achievement sync job status."""
    from services.jobs import xbox_sync_job
    return jsonify(xbox_sync_job.get_status())


@bp.route('/api/xbox/cancel-sync', methods=['POST'])
@editor_required
def api_xbox_cancel_sync():
    """Cancel the Xbox achievement sync."""
    from services.jobs import xbox_sync_job
    return jsonify(xbox_sync_job.cancel())


# =============================================================================
# PSN ENDPOINTS
# =============================================================================

PSN_PLATFORM_MAP = {
    'PS3': 'ps3',
    'PS4': 'ps4',
    'PS5': 'ps5',
    'PSVITA': 'psvita',
}


def _get_psn_settings():
    """Get PSN NPSSO and username from user settings."""
    npsso = ''
    username = ''
    if hasattr(g, 'user_settings') and g.user_settings:
        settings = dict(g.user_settings) if not isinstance(g.user_settings, dict) else g.user_settings
        npsso = settings.get('psn_npsso', '') or ''
        username = settings.get('psn_username', '') or ''
    return npsso, username


@bp.route('/api/psn/import/status')
@login_required
def api_psn_import_status():
    """Check if PSN is configured and has data for import."""
    npsso, username = _get_psn_settings()

    if not npsso:
        return jsonify({'configured': False, 'has_data': False})

    # Check if psn_games table has data (Pass 31.1 — per user).
    try:
        row = query(
            "SELECT COUNT(*) as cnt FROM psn_games WHERE user_id = ?",
            (g.user['id'],), one=True,
        )
        total_games = row['cnt'] if row else 0
    except Exception:
        total_games = 0

    # Get sync status info — Pass 27.2 scopes to current user.
    try:
        sync_info = query(
            "SELECT username, last_full_sync, avatar_url FROM psn_sync_status WHERE user_id = ?",
            (g.user['id'],), one=True
        )
    except Exception:
        sync_info = None

    return jsonify({
        'configured': True,
        'has_data': total_games > 0,
        'username': sync_info['username'] if sync_info else username,
        'avatar_url': sync_info['avatar_url'] if sync_info else '',
        'total_games': total_games,
        'last_sync': sync_info['last_full_sync'] if sync_info else None,
    })


@bp.route('/api/psn/fetch-library', methods=['POST'])
@login_required
def api_psn_fetch_library():
    """Fetch PSN game library from local DB or live API."""
    from routes.trophies import create_psn_client, extract_psn_platform

    npsso, _username = _get_psn_settings()

    if not npsso:
        return jsonify({
            'success': False,
            'error': _('PSN NPSSO not configured. Add it in Settings \u2192 API Keys.')
        }), 400

    # Check local psn_games table first (Pass 31.1 — per user).
    try:
        local_games = query(
            "SELECT npwr_id, title, platform, icon_url, progress, linked_game_id "
            "FROM psn_games WHERE user_id = ? ORDER BY title",
            (g.user['id'],),
        )
    except Exception:
        local_games = []

    if local_games:
        # Use local data (faster)
        return _build_psn_library_response(local_games)

    # No local data — fetch live from PSN API
    psnawp, error = create_psn_client(npsso)
    if error:
        return jsonify({'success': False, 'error': error}), 400

    try:
        me = psnawp.me()
        trophy_titles = list(me.trophy_titles())
    except Exception as e:
        logger.error(f"PSN Import: Failed to fetch trophy titles: {e}")
        return jsonify({
            'success': False,
            'error': _('Failed to fetch PSN game list. Try syncing trophies first.')
        })

    games_data = []
    for title in trophy_titles:
        npwr_id = getattr(title, 'np_communication_id', '') or ''
        name = getattr(title, 'title_name', '') or ''
        icon_url = getattr(title, 'title_icon_url', '') or ''
        progress = getattr(title, 'progress', 0) or 0

        if not npwr_id or not name:
            continue

        platform_str = extract_psn_platform(title)

        games_data.append({
            'npwr_id': npwr_id,
            'title': name,
            'platform': platform_str,
            'icon_url': icon_url,
            'progress': progress,
            'linked_game_id': None,
        })

    # Build response using same helper
    return _build_psn_library_response(games_data, from_api=True)


def _build_psn_library_response(games_data, from_api=False):
    """Build the fetch-library response from PSN game data.

    Args:
        games_data: List of dicts or Row objects with game info.
        from_api: True if data came from live API (dict), False if from DB (Row).
    """
    # Ensure all PSN systems exist
    psn_systems = {}
    for platform_str, folder in PSN_PLATFORM_MAP.items():
        system = _ensure_system_exists(folder)
        if system:
            psn_systems[platform_str] = system

    result_games = []
    for game in games_data:
        if from_api:
            npwr_id = game['npwr_id']
            name = game['title']
            platform_str = game['platform']
            icon_url = game['icon_url']
            progress = game['progress']
            linked_game_id = None
        else:
            npwr_id = game['npwr_id'] or ''
            name = game['title'] or ''
            platform_str = (game['platform'] or 'PS4').upper()
            icon_url = game['icon_url'] or ''
            progress = game['progress'] or 0
            linked_game_id = game['linked_game_id']

        if not npwr_id or not name:
            continue

        folder = PSN_PLATFORM_MAP.get(platform_str, 'ps4')
        system = psn_systems.get(platform_str)
        system_id = system['id'] if system else None

        # Check duplicates
        existing_id = linked_game_id or _check_duplicate(
            name, system_id, 'psn_npwr_id', npwr_id
        )

        result_games.append({
            'npwr_id': npwr_id,
            'name': name,
            'platform': folder,
            'platform_display': platform_str,
            'system_name': system['name'] if system else platform_str,
            'icon_url': icon_url,
            'trophy_progress': progress,
            'already_imported': existing_id is not None,
            'existing_game_id': existing_id,
        })

    result_games.sort(key=lambda g: g['name'].lower())

    # Get sync status for profile info — Pass 27.2 scopes to current user.
    sync_info = query(
        "SELECT username, avatar_url FROM psn_sync_status WHERE user_id = ?",
        (g.user['id'],), one=True
    )

    avatar_out = ''
    if sync_info:
        stored = sync_info['avatar_url'] or ''
        username = sync_info['username'] or ''
        # Legacy rows stored the PSN CDN URL directly; the browser can't
        # load those (PSN rejects the default UA). Mirror to /static on
        # first read so existing profiles fix themselves without forcing
        # the user to re-run a full trophy sync.
        if stored.startswith('/static/'):
            avatar_out = stored
        elif stored and username:
            from services.jobs.base import _download_psn_avatar
            local = _download_psn_avatar(username, stored)
            if local:
                execute(
                    "UPDATE psn_sync_status SET avatar_url = ? WHERE user_id = ?",
                    (local, g.user['id']),
                )
                avatar_out = local
            else:
                avatar_out = stored  # fallback — still broken, but no worse
        else:
            avatar_out = stored

    return jsonify({
        'success': True,
        'games': result_games,
        'total': len(result_games),
        'already_imported': sum(1 for g in result_games if g['already_imported']),
        'profile': {
            'username': sync_info['username'] if sync_info else '',
            'avatar_url': avatar_out,
        } if sync_info else None,
    })


@bp.route('/api/psn/import', methods=['POST'])
@editor_required
def api_psn_import():
    """Import selected PSN games into the library."""
    data = request.get_json(silent=True) or {}
    selected_games = data.get('games', [])

    if not selected_games:
        return jsonify({'success': False, 'error': _('No games selected')})

    # Ensure all needed PSN systems exist
    psn_systems = {}
    for platform_str, folder in PSN_PLATFORM_MAP.items():
        system = _ensure_system_exists(folder)
        if system:
            psn_systems[folder] = system

    imported = 0
    skipped = 0
    failed = 0

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        # Build lookup for duplicate detection
        existing_psn_ids = set()
        existing_norm = {}
        for row in c.execute("SELECT psn_npwr_id, title, system_id FROM games").fetchall():
            if row['psn_npwr_id']:
                existing_psn_ids.add(row['psn_npwr_id'])
            key = (normalize_title(row['title']), row['system_id'])
            existing_norm[key] = True

        for game in selected_games:
            try:
                npwr_id = str(game.get('npwr_id', ''))
                title = game.get('name', '').strip()
                platform = game.get('platform', 'ps4')
                if not title:
                    failed += 1
                    continue

                system = psn_systems.get(platform)
                if not system:
                    failed += 1
                    continue

                system_id = system['id']

                # Check duplicates
                if npwr_id in existing_psn_ids:
                    skipped += 1
                    continue
                if (normalize_title(title), system_id) in existing_norm:
                    skipped += 1
                    continue

                rom_path = f"psn_import/{platform}/{npwr_id}"

                c.execute("""
                    INSERT INTO games (
                        title, system_id, rom_path, scraped,
                        psn_npwr_id, created_at
                    ) VALUES (?, ?, ?, 0, ?, ?)
                """, (
                    title,
                    system_id,
                    rom_path,
                    npwr_id,
                    datetime.now(timezone.utc).isoformat(),
                ))

                # Link the PSN trophy record to the imported game.
                # Pass 31.1 — scope by user so user B's import can't
                # inadvertently repoint user A's trophy row to a new game.
                new_game_id = c.lastrowid
                c.execute(
                    "UPDATE psn_games SET linked_game_id = ? "
                    "WHERE npwr_id = ? AND user_id = ?",
                    (new_game_id, npwr_id, g.user['id'])
                )

                imported += 1
                existing_psn_ids.add(npwr_id)
                existing_norm[(normalize_title(title), system_id)] = True

            except Exception as e:
                logger.error(f"PSN Import: Failed to import '{game.get('name')}': {e}")
                failed += 1

        conn.commit()

        logger.info(f"PSN Import complete: {imported} imported, {skipped} skipped, {failed} failed")

        return jsonify({
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
        })

    except Exception as e:
        logger.error(f"PSN Import error: {e}")
        return jsonify({'success': False, 'error': _('An internal error occurred')})
    finally:
        if conn:
            conn.close()
