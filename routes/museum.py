# =============================================================================
# RETRODB - Museum Blueprint
# =============================================================================
# Gaming system encyclopedia — AI-generated history, specs, top games,
# and controller gallery for each system.
# =============================================================================

from flask import Blueprint, render_template, jsonify, request
import ipaddress
import json
import os
import re
import logging
import requests
import socket
import time
from urllib.parse import urlparse

import threading

import config
from services.database import get_request_db
from services.auth import login_required, editor_required

logger = logging.getLogger(__name__)


def _is_public_https_url(url, max_redirects=3):
    """Pass 25.3 / 32.6 / 45.2 — SSRF guard. Thin wrapper over
    services.ssrf.validate_and_pin_url so this module's existing call sites
    keep working.
    """
    from services.ssrf import validate_and_pin_url
    return validate_and_pin_url(requests, url, max_redirects=max_redirects, timeout=5)

# Serialize all rembg GPU work to prevent concurrent sessions from exhausting
# GPU memory (ROCm/HIP workspace allocation failures → GPU hang).
# The cached session is reused across requests so GPU memory is allocated once.
_rembg_lock = threading.Lock()
_rembg_session = None       # Cached GPU session (or CPU fallback)
_rembg_session_cpu = False   # True if cached session is CPU-only

bp = Blueprint('museum', __name__)

# =============================================================================
# GENERATION ORDER — Timeline grouping for landing page
# =============================================================================

GENERATION_ORDER = [
    '1st Generation',
    '1st/2nd Generation (Handheld)',
    '2nd Generation',
    '3rd Generation',
    '4th Generation',
    '4th Generation (Handheld)',
    '5th Generation',
    '5th Generation (Handheld)',
    '6th Generation',
    '6th Generation (Handheld)',
    '7th Generation',
    '7th Generation (Handheld)',
    '8th Generation',
    '8th Generation (Handheld)',
    '8th/9th Generation (Hybrid)',
    '9th Generation',
    'Computers',
    'Arcade',
    'Other',
]

# Friendly display names for generation groups
GENERATION_DISPLAY = {
    '1st Generation': '1st Generation',
    '1st/2nd Generation (Handheld)': '1st/2nd Generation Handhelds',
    '2nd Generation': '2nd Generation',
    '3rd Generation': '3rd Generation',
    '4th Generation': '4th Generation',
    '4th Generation (Handheld)': '4th Generation Handhelds',
    '5th Generation': '5th Generation',
    '5th Generation (Handheld)': '5th Generation Handhelds',
    '6th Generation': '6th Generation',
    '6th Generation (Handheld)': '6th Generation Handhelds',
    '7th Generation': '7th Generation',
    '7th Generation (Handheld)': '7th Generation Handhelds',
    '8th Generation': '8th Generation',
    '8th Generation (Handheld)': '8th Generation Handhelds',
    '8th/9th Generation (Hybrid)': '8th/9th Generation Hybrid',
    '9th Generation': '9th Generation',
    'Computers': 'Computers',
    'Arcade': 'Arcade',
    'Other': 'Other',
}

# Era descriptions for timeline context
GENERATION_ERAS = {
    '1st Generation': '1972–1980',
    '1st/2nd Generation (Handheld)': '1980–1991',
    '2nd Generation': '1976–1992',
    '3rd Generation': '1983–1992',
    '4th Generation': '1987–1996',
    '4th Generation (Handheld)': '1989–1998',
    '5th Generation': '1993–2002',
    '5th Generation (Handheld)': '1998–2003',
    '6th Generation': '1998–2006',
    '6th Generation (Handheld)': '2001–2005',
    '7th Generation': '2005–2012',
    '7th Generation (Handheld)': '2004–2013',
    '8th Generation': '2012–2020',
    '8th Generation (Handheld)': '2011–2019',
    '8th/9th Generation (Hybrid)': '2017–Present',
    '9th Generation': '2020–Present',
    'Computers': 'Various',
    'Arcade': 'Various',
    'Other': 'Various',
}


# =============================================================================
# HELPERS
# =============================================================================

def _find_hardware_image(folder):
    """Find a hardware image for the given system folder."""
    hardware_dir = os.path.join(config.STATIC_PATH, 'images', 'hardware')
    for ext in ['.webp', '.png', '.jpg']:
        path = os.path.join(hardware_dir, f"{folder}{ext}")
        if os.path.exists(path):
            return f"images/hardware/{folder}{ext}"
    return None


def _get_top_games(system_id, museum_data):
    """Get top 10 games combining DB critic scores and AI-cached data."""
    db = get_request_db()

    # Get top-scored games from DB with boxart
    db_games = db.execute("""
        SELECT g.id, g.title, g.critic_score, g.boxart
        FROM games g
        WHERE g.system_id = ? AND g.critic_score IS NOT NULL AND g.critic_score > 0
        ORDER BY g.critic_score DESC
        LIMIT 10
    """, (system_id,)).fetchall()

    top_games = []
    seen_titles = set()

    for i, g in enumerate(db_games):
        top_games.append({
            'rank': i + 1,
            'title': g['title'],
            'score': g['critic_score'],
            'boxart': g['boxart'],
            'game_id': g['id'],
            'source': 'db',
        })
        seen_titles.add(g['title'])

    # Supplement with AI suggestions if < 10
    if len(top_games) < 10 and museum_data and museum_data['top_games']:
        try:
            ai_games = json.loads(museum_data['top_games'])
            for ag in ai_games:
                if len(top_games) >= 10:
                    break
                title = ag.get('title', '') if isinstance(ag, dict) else str(ag)
                if title and title not in seen_titles:
                    top_games.append({
                        'rank': len(top_games) + 1,
                        'title': title,
                        'score': ag.get('score') if isinstance(ag, dict) else None,
                        'boxart': None,
                        'game_id': None,
                        'source': 'ai',
                    })
                    seen_titles.add(title)
        except (json.JSONDecodeError, TypeError) as exc:
            # Pass 41.11.A — log the decode failure at WARNING so an operator
            # can prompt the next museum generation (the LLM occasionally
            # returns truncated JSON). Previously a bare `pass` left the
            # admin with an empty top-games list and no breadcrumb.
            logger.warning(
                "Museum top_games JSON decode failed for system_id=%s: %s",
                getattr(museum_data, 'get', lambda _k: None)('system_id'),
                exc,
            )

    return top_games


def _get_system_type(folder):
    """Determine system type from generation string."""
    from services.game_utils import COMPUTER_SYSTEMS, HANDHELD_SYSTEMS
    specs = config.SYSTEM_SPECS.get(folder, {})
    gen = specs.get('generation', '')

    if folder in COMPUTER_SYSTEMS:
        return 'Computer'
    if folder in HANDHELD_SYSTEMS:
        return 'Handheld'
    if 'arcade' in folder.lower() or folder in ('mame', 'fbneo', 'daphne'):
        return 'Arcade'
    if 'Handheld' in gen or 'Hybrid' in gen:
        return 'Handheld'
    return 'Console'


# =============================================================================
# PAGE ROUTES
# =============================================================================

@bp.route('/museum')
@login_required
def museum():
    """Museum landing page — timeline grouped by generation."""
    db = get_request_db()

    # Get all systems with game counts
    systems = db.execute("""
        SELECT s.id, s.name, s.folder, COUNT(g.id) as game_count
        FROM systems s
        LEFT JOIN games g ON g.system_id = s.id
        GROUP BY s.id
        ORDER BY s.name
    """).fetchall()

    # Get museum content status for each system
    museum_data = {}
    rows = db.execute("SELECT system_id, summary, history FROM system_museum").fetchall()
    for row in rows:
        museum_data[row['system_id']] = {
            'summary': row['summary'],
            'has_content': bool(row['history']),
        }

    # Group systems by generation
    generations = {}
    for system in systems:
        folder = system['folder']
        specs = config.SYSTEM_SPECS.get(folder, {})
        gen = specs.get('generation', '')

        # Classify into generation bucket
        if not gen:
            # Systems without specs — classify by type
            from services.game_utils import COMPUTER_SYSTEMS
            if folder in COMPUTER_SYSTEMS:
                gen = 'Computers'
            elif folder in ('arcade', 'mame', 'fbneo', 'daphne', 'consolearcade', 'pcarcade',
                            'model2', 'model3', 'naomi', 'naomi2', 'stv'):
                gen = 'Arcade'
            else:
                gen = 'Other'

        if gen not in generations:
            generations[gen] = []

        hw_image = _find_hardware_image(folder)
        museum_info = museum_data.get(system['id'], {})

        generations[gen].append({
            'id': system['id'],
            'name': system['name'],
            'folder': folder,
            'game_count': system['game_count'],
            'hw_image': hw_image,
            'manufacturer': specs.get('manufacturer', ''),
            'released': specs.get('released', ''),
            'summary': museum_info.get('summary', ''),
            'has_content': museum_info.get('has_content', False),
            'system_type': _get_system_type(folder),
        })

    # Sort into ordered list of (gen_name, display_name, era, systems)
    sorted_generations = []
    seen = set()
    for gen_key in GENERATION_ORDER:
        if gen_key in generations:
            sorted_generations.append((
                gen_key,
                GENERATION_DISPLAY.get(gen_key, gen_key),
                GENERATION_ERAS.get(gen_key, ''),
                generations[gen_key],
            ))
            seen.add(gen_key)

    # Add any unlisted generations at the end
    for gen_key, sys_list in generations.items():
        if gen_key not in seen:
            sorted_generations.append((gen_key, gen_key, '', sys_list))

    total_systems = sum(len(g[3]) for g in sorted_generations)
    content_count = sum(1 for m in museum_data.values() if m.get('has_content'))

    return render_template('museum.html',
                           generations=sorted_generations,
                           total_systems=total_systems,
                           content_count=content_count)


@bp.route('/museum/<int:system_id>')
@login_required
def museum_system(system_id):
    """Per-system museum page."""
    db = get_request_db()

    system = db.execute(
        "SELECT id, name, folder FROM systems WHERE id = ?", (system_id,)
    ).fetchone()
    if not system:
        return render_template('museum_system.html', system=None, error='System not found'), 404

    folder = system['folder']
    specs = config.SYSTEM_SPECS.get(folder, {})
    hw_image = _find_hardware_image(folder)

    # Museum content
    museum_data = db.execute(
        "SELECT * FROM system_museum WHERE system_id = ?", (system_id,)
    ).fetchone()

    # Top games
    top_games = _get_top_games(system_id, museum_data)

    # Controllers for this system (validate images exist on disk)
    controllers_raw = db.execute(
        """SELECT c.* FROM controllers c
           JOIN system_controllers sc ON c.id = sc.controller_id
           WHERE sc.system_id = ?
           ORDER BY c.sort_order, c.name""",
        (system_id,)
    ).fetchall()

    controllers_dir = os.path.join(config.STATIC_PATH, 'images', 'controllers')
    controllers = []
    # Pass 41.11.B — a GET handler must not mutate shared DB state (RFC 7231
    # GET-idempotency). The previous shape ran `UPDATE controllers SET
    # image = NULL` from inside this view, meaning one user's page load
    # rewrote globally-visible state. Clear stale refs in the in-memory
    # render dict only; persistent cleanup runs from POST
    # /api/museum/cleanup-controller-images (admin-only) below.
    for ctrl in controllers_raw:
        ctrl = dict(ctrl)
        if ctrl.get('image'):
            img_path = os.path.join(controllers_dir, ctrl['image'])
            if not os.path.isfile(img_path):
                ctrl['image'] = None
        controllers.append(ctrl)

    # Game count
    game_count = db.execute(
        "SELECT COUNT(*) as cnt FROM games WHERE system_id = ?", (system_id,)
    ).fetchone()['cnt']

    return render_template('museum_system.html',
                           system=system,
                           specs=specs,
                           hw_image=hw_image,
                           museum_data=museum_data,
                           top_games=top_games,
                           controllers=controllers,
                           game_count=game_count)


# =============================================================================
# API ROUTES — AI Generation
# =============================================================================

@bp.route('/api/museum/generate/<int:system_id>', methods=['POST'])
@editor_required
def generate_system(system_id):
    """Generate AI content for a single system."""
    from scraper.scrape_ai import (
        _get_active_provider, _call_gemini, _call_openai, _call_claude,
    )
    from services.jobs.museum import _build_museum_prompt, _build_top_games_prompt, _parse_museum_response

    db = get_request_db()
    system = db.execute(
        "SELECT id, name, folder FROM systems WHERE id = ?", (system_id,)
    ).fetchone()
    if not system:
        return jsonify({'success': False, 'error': 'System not found'}), 404

    provider_config = _get_active_provider()
    if not provider_config:
        return jsonify({'success': False, 'error': 'No AI provider configured'}), 400

    provider = provider_config['provider']
    api_key = provider_config['api_key']
    model = provider_config['model']

    call_fn = {
        'gemini': _call_gemini,
        'openai': _call_openai,
        'claude': _call_claude,
    }.get(provider)

    if not call_fn:
        return jsonify({'success': False, 'error': f'Unknown provider: {provider}'}), 400

    specs = config.SYSTEM_SPECS.get(system['folder'], {})
    prompt = _build_museum_prompt(system['name'], specs)

    kwargs = {}
    if provider == 'gemini' and provider_config.get('project_id'):
        kwargs['project_id'] = provider_config['project_id']

    raw_text = call_fn(prompt, api_key, model, **kwargs)
    if not raw_text:
        return jsonify({'success': False, 'error': 'Empty AI response'}), 500

    data = _parse_museum_response(raw_text)
    history = data.get('history', '')
    summary = data.get('summary', '')

    if not history and not summary:
        return jsonify({'success': False, 'error': 'No usable content in AI response'}), 500

    # Generate top games
    db_games = db.execute("""
        SELECT title FROM games
        WHERE system_id = ? AND critic_score IS NOT NULL AND critic_score > 0
        ORDER BY critic_score DESC LIMIT 10
    """, (system_id,)).fetchall()
    existing_titles = [g['title'] for g in db_games]

    top_games_json = '[]'
    if len(existing_titles) < 10:
        tg_prompt = _build_top_games_prompt(system['name'], existing_titles)
        tg_raw = call_fn(tg_prompt, api_key, model)
        if tg_raw:
            tg_data = _parse_museum_response(tg_raw)
            ai_games = tg_data.get('top_games', [])
            top_games = [
                {'title': g['title'], 'rank': i + 1, 'source': 'db'}
                for i, g in enumerate(db_games)
            ]
            rank = len(top_games) + 1
            for ag in ai_games:
                if rank > 10:
                    break
                title = ag.get('title', '') if isinstance(ag, dict) else str(ag)
                if title and title not in existing_titles:
                    top_games.append({'title': title, 'rank': rank, 'source': 'ai'})
                    existing_titles.append(title)
                    rank += 1
            top_games_json = json.dumps(top_games)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    db.execute("""
        INSERT INTO system_museum (system_id, history, summary, top_games, generated_at, generated_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_id) DO UPDATE SET
            history = excluded.history,
            summary = excluded.summary,
            top_games = excluded.top_games,
            generated_at = excluded.generated_at,
            generated_by = excluded.generated_by
    """, (system_id, history, summary, top_games_json, now, provider))
    db.commit()

    return jsonify({
        'success': True,
        'history': history,
        'summary': summary,
        'generated_by': provider,
        'generated_at': now,
    })


@bp.route('/api/museum/generate-all', methods=['POST'])
@editor_required
def generate_all():
    """Start bulk AI generation for all systems."""
    from services.jobs import museum_generate_job

    data = request.get_json(silent=True) or {}
    overwrite = data.get('overwrite', False)
    result = museum_generate_job.start(overwrite=overwrite)
    return jsonify(result)


@bp.route('/api/museum/generate-status')
@login_required
def generate_status():
    """Poll bulk generation progress."""
    from services.jobs import museum_generate_job
    return jsonify(museum_generate_job.get_status())


@bp.route('/api/museum/cancel-generate', methods=['POST'])
@editor_required
def cancel_generate():
    """Cancel running bulk generation."""
    from services.jobs import museum_generate_job
    result = museum_generate_job.cancel()
    return jsonify(result)


@bp.route('/api/museum/cleanup-controller-images', methods=['POST'])
@editor_required
def cleanup_controller_images():
    """Pass 41.11.B — admin-triggered persistent cleanup of stale controller
    image references. The per-system museum page no longer mutates DB state
    inside its GET handler (it just nulls the in-memory render dict for
    missing files). Operators can invoke this endpoint to do the persistent
    sweep when they notice broken thumbnails.
    """
    db = get_request_db()
    controllers_dir = os.path.join(config.STATIC_PATH, 'images', 'controllers')
    rows = db.execute(
        "SELECT id, image FROM controllers WHERE image IS NOT NULL AND image != ''"
    ).fetchall()
    cleared = 0
    for row in rows:
        img_path = os.path.join(controllers_dir, row['image'])
        if not os.path.isfile(img_path):
            db.execute(
                "UPDATE controllers SET image = NULL WHERE id = ? AND image = ?",
                (row['id'], row['image']),
            )
            cleared += 1
    db.commit()
    logger.info("Museum: cleanup-controller-images cleared %d stale refs", cleared)
    return jsonify({'success': True, 'cleared': cleared, 'scanned': len(rows)})


# =============================================================================
# API ROUTES — Controller Images
# =============================================================================

def _persist_controller_image(controller_id, image_data):
    """Save image_data as ``controllers/<controller_id>.webp`` (RGBA, cropped, standardized).

    Pass 42.5 — extracted from three near-identical 30-line blocks
    (upload / removebg / fetch_and_process). Caller is responsible for
    the DB UPDATE and ``_propagate_controller_image`` call (the upload
    and removebg routes do them; ``_fetch_and_process_image`` returns
    the filename to its caller, which decides).

    Returns the saved filename on success, None on failure.
    """
    from PIL import Image
    import io
    try:
        img = Image.open(io.BytesIO(bytes(image_data)))
        img = img.convert('RGBA')
        img = _crop_to_content(img)

        controllers_dir = os.path.join(config.STATIC_PATH, 'images', 'controllers')
        os.makedirs(controllers_dir, exist_ok=True)

        filename = f"{controller_id}.webp"
        filepath = os.path.join(controllers_dir, filename)
        img.save(filepath, 'WEBP', quality=85)

        try:
            from services.image_utils import standardize_downloaded_image
            standardize_downloaded_image(filepath, 'controllers')
        except Exception:
            pass

        return filename
    except Exception as e:
        logger.error(f"Museum: Failed to persist controller image for {controller_id}: {e}")
        return None


def _propagate_controller_image(db, controller_id, image_filename):
    """Share a controller image with all sibling controllers (same name, different systems)."""
    controller = db.execute(
        "SELECT name FROM controllers WHERE id = ?", (controller_id,)
    ).fetchone()
    if not controller:
        return
    siblings = db.execute(
        "SELECT id FROM controllers WHERE name = ? AND id != ?",
        (controller['name'], controller_id)
    ).fetchall()
    for sib in siblings:
        db.execute("UPDATE controllers SET image = ? WHERE id = ?",
                   (image_filename, sib['id']))
    if siblings:
        db.commit()
        logger.info(f"Museum: Propagated image to {len(siblings)} sibling controller(s) for '{controller['name']}'")


@bp.route('/api/museum/controller-image/<int:controller_id>', methods=['POST'])
@editor_required
def fetch_controller_image(controller_id):
    """Fetch and process a single controller image."""
    db = get_request_db()
    controller = db.execute(
        "SELECT id, name, manufacturer FROM controllers WHERE id = ?",
        (controller_id,)
    ).fetchone()
    if not controller:
        return jsonify({'success': False, 'error': 'Controller not found'}), 404

    # Get system name for search context
    system = db.execute(
        """SELECT s.name FROM systems s
           JOIN system_controllers sc ON s.id = sc.system_id
           WHERE sc.controller_id = ? LIMIT 1""",
        (controller_id,)
    ).fetchone()
    system_name = system['name'] if system else ''

    removebg_key = _get_removebg_key()
    result = _fetch_and_process_image(
        controller['id'], controller['name'], controller['manufacturer'] or '',
        system_name, removebg_key
    )

    if result:
        db.execute("UPDATE controllers SET image = ? WHERE id = ?", (result, controller_id))
        db.commit()
        _propagate_controller_image(db, controller_id, result)
        return jsonify({'success': True, 'image': result})

    return jsonify({'success': False, 'error': 'Could not find a suitable image for this controller'})


@bp.route('/api/museum/controller-images-bulk/<int:system_id>', methods=['POST'])
@editor_required
def fetch_controller_images_bulk(system_id):
    """Bulk fetch controller images for a system."""
    db = get_request_db()
    controllers = db.execute(
        """SELECT c.id, c.name, c.manufacturer, c.image FROM controllers c
           JOIN system_controllers sc ON c.id = sc.controller_id
           WHERE sc.system_id = ?""",
        (system_id,)
    ).fetchall()

    if not controllers:
        return jsonify({'success': False, 'error': 'No controllers found'}), 404

    # Get system name for search context
    system = db.execute("SELECT name FROM systems WHERE id = ?", (system_id,)).fetchone()
    system_name = system['name'] if system else ''

    removebg_key = _get_removebg_key()
    results = {'success': 0, 'failed': 0, 'skipped': 0}

    for ctrl in controllers:
        if ctrl['image']:
            # Already has an image
            results['skipped'] += 1
            continue

        result = _fetch_and_process_image(
            ctrl['id'], ctrl['name'], ctrl['manufacturer'] or '',
            system_name, removebg_key
        )

        if result:
            db.execute("UPDATE controllers SET image = ? WHERE id = ?", (result, ctrl['id']))
            db.commit()
            _propagate_controller_image(db, ctrl['id'], result)
            results['success'] += 1
        else:
            results['failed'] += 1

        time.sleep(1)  # Rate limit

    return jsonify({'success': True, 'results': results})


@bp.route('/api/museum/controller-image-upload/<int:controller_id>', methods=['POST'])
@editor_required
def upload_controller_image(controller_id):
    """Upload a custom controller image, optionally remove background, save as webp."""
    from PIL import Image
    import io

    db = get_request_db()
    controller = db.execute(
        "SELECT id, name FROM controllers WHERE id = ?",
        (controller_id,)
    ).fetchone()
    if not controller:
        return jsonify({'success': False, 'error': 'Controller not found'}), 404

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No image file provided'})

    file = request.files['image']
    if not file.filename:
        return jsonify({'success': False, 'error': 'No file selected'})

    # Pass 25.4 — reject oversize uploads before reading the whole payload.
    # Werkzeug's MAX_CONTENT_LENGTH covers the full request body, but a single
    # /controller-image-upload with a 2 GB file still OOMs this process on
    # file.read(). Use the declared per-part Content-Length when present,
    # fall back to a byte budget on the stream read.
    max_upload = getattr(config, 'MUSEUM_UPLOAD_MAX_BYTES', 10 * 1024 * 1024)
    declared = getattr(file, 'content_length', 0) or 0
    if declared and declared > max_upload:
        return jsonify({
            'success': False,
            'error': f'File too large ({declared // (1024*1024)} MB). Maximum is {max_upload // (1024*1024)} MB.',
        }), 413

    image_data = file.stream.read(max_upload + 1)
    if len(image_data) > max_upload:
        return jsonify({
            'success': False,
            'error': f'File too large (> {max_upload // (1024*1024)} MB).',
        }), 413
    if len(image_data) < 100:
        return jsonify({'success': False, 'error': 'File is too small'})

    # Validate it's actually an image
    try:
        img_check = Image.open(io.BytesIO(image_data))
        img_check.verify()
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid image file'})

    # Optionally remove background
    remove_bg = request.form.get('remove_bg', 'false') == 'true'
    if remove_bg:
        removebg_key = _get_removebg_key()
        image_data = _remove_background(image_data, removebg_key)

    # Save as webp
    filename = _persist_controller_image(controller_id, image_data)
    if not filename:
        return jsonify({'success': False, 'error': 'Failed to process image'})

    db.execute("UPDATE controllers SET image = ? WHERE id = ?", (filename, controller_id))
    db.commit()
    _propagate_controller_image(db, controller_id, filename)

    logger.info(f"Museum: Uploaded image for {controller['name']}")
    return jsonify({'success': True, 'image': filename})


@bp.route('/api/museum/controller-image-removebg/<int:controller_id>', methods=['POST'])
@editor_required
def remove_controller_bg(controller_id):
    """Re-process an existing controller image to remove its background."""
    db = get_request_db()
    controller = db.execute(
        "SELECT id, name, image FROM controllers WHERE id = ?",
        (controller_id,)
    ).fetchone()
    if not controller:
        return jsonify({'success': False, 'error': 'Controller not found'}), 404

    if not controller['image']:
        return jsonify({'success': False, 'error': 'No image to process'})

    filepath = os.path.join(config.STATIC_PATH, 'images', 'controllers', controller['image'])
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'Image file not found'})

    try:
        with open(filepath, 'rb') as f:
            image_data = f.read()

        removebg_key = _get_removebg_key()
        processed = _remove_background(image_data, removebg_key)
    except Exception as e:
        logger.error(f"Museum: Failed to remove background for {controller['name']}: {e}")
        return jsonify({'success': False, 'error': 'Background removal failed'})

    filename = _persist_controller_image(controller_id, processed)
    if not filename:
        return jsonify({'success': False, 'error': 'Background removal failed'})

    if controller['image'] != filename:
        db.execute("UPDATE controllers SET image = ? WHERE id = ?", (filename, controller_id))
        db.commit()
    _propagate_controller_image(db, controller_id, filename)

    logger.info(f"Museum: Removed background for {controller['name']}")
    return jsonify({'success': True, 'image': filename})


def _get_removebg_key():
    """Get remove.bg API key from scraper settings."""
    settings_file = os.path.join(config.BASE_DIR, 'data', 'scraper_settings.json')
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            return settings.get('api_keys', {}).get('removebg_api_key', '')
    except Exception:
        pass
    return ''


def _crop_to_content(img):
    """Crop an RGBA image to its non-transparent content, removing blank space."""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    return img


def _bing_image_search(query, max_results=10):
    """Search Bing Images and return a list of source image URLs.

    Parses image metadata from Bing's HTML search results — no API key needed.
    """
    import html as html_mod

    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
    }

    try:
        resp = requests.get(
            'https://www.bing.com/images/search',
            params={
                'q': query,
                'form': 'HDRSC2',
                'first': '1',
                'qft': '+filterui:imagesize-large+filterui:photo-photo',
            },
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Museum: Bing image search returned {resp.status_code}")
            return []

        # Bing embeds image metadata as JSON in 'iusc' class elements
        m_matches = re.findall(r'class="iusc"[^>]*m="([^"]*)"', resp.text)
        urls = []
        for m in m_matches[:max_results]:
            decoded = html_mod.unescape(m)
            try:
                data = json.loads(decoded)
                murl = data.get('murl', '')
                if murl and murl.startswith('http'):
                    urls.append(murl)
            except (json.JSONDecodeError, AttributeError):
                continue
        return urls

    except Exception as e:
        logger.warning(f"Museum: Bing image search failed: {e}")
        return []


def _remove_background(image_data, removebg_key=None):
    """Remove image background. Uses rembg (local AI) or remove.bg API.

    Returns:
        Processed image bytes (PNG with transparency), or original if removal fails.
    """
    # Prefer remove.bg API if key is configured
    if removebg_key:
        try:
            rbg_resp = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': ('image.png', image_data)},
                data={'size': 'auto', 'format': 'png'},
                headers={'X-Api-Key': removebg_key},
                timeout=30,
            )
            if rbg_resp.status_code == 200:
                logger.info("Museum: Background removed via remove.bg API")
                return rbg_resp.content
            logger.warning(f"Museum: remove.bg returned {rbg_resp.status_code}, falling back to rembg")
        except Exception as e:
            logger.warning(f"Museum: remove.bg error ({e}), falling back to rembg")

    # Fall back to rembg (local AI background removal).
    # Acquire lock so only one rembg session uses the GPU at a time.
    try:
        from rembg import remove as rembg_remove, new_session
        from PIL import Image
        import io

        # Downscale large images before rembg to avoid GPU memory exhaustion.
        # birefnet-general internally resizes to 1024x1024 anyway, so feeding
        # a 2048px image just wastes VRAM and can cause GPU hangs on AMD/ROCm.
        MAX_REMBG_DIM = 1024
        try:
            img = Image.open(io.BytesIO(image_data))
            w, h = img.size
            if max(w, h) > MAX_REMBG_DIM:
                scale = MAX_REMBG_DIM / max(w, h)
                new_w, new_h = int(w * scale), int(h * scale)
                img = img.resize((new_w, new_h), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                image_data = buf.getvalue()
                logger.info(f"Museum: Downscaled {w}x{h} -> {new_w}x{new_h} for rembg")
        except Exception as e:
            logger.warning(f"Museum: Pre-rembg downscale failed ({e}), using original size")

        with _rembg_lock:
            global _rembg_session, _rembg_session_cpu

            # Create or reuse a cached session so GPU memory is allocated once
            if _rembg_session is None:
                providers = None
                try:
                    # AMD GPUs like gfx1032 (RX 6600) need version override so
                    # rocBLAS/Tensile can find gfx1030 kernels (same RDNA2 arch).
                    # Must be set before ONNX Runtime touches the GPU.
                    if 'HSA_OVERRIDE_GFX_VERSION' not in os.environ:
                        os.environ['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'
                        logger.info("Museum: Set HSA_OVERRIDE_GFX_VERSION=10.3.0 for ROCm compatibility")
                    # Use MIOpen FAST find mode to skip exhaustive kernel benchmarking.
                    # Default mode benchmarks every candidate kernel on cache miss,
                    # hammering the GPU for ~60s after inference is already complete.
                    if 'MIOPEN_FIND_MODE' not in os.environ:
                        os.environ['MIOPEN_FIND_MODE'] = '2'
                        logger.info("Museum: Set MIOPEN_FIND_MODE=2 (fast) to skip kernel auto-tuning")

                    import onnxruntime as ort
                    available = ort.get_available_providers()
                    preferred = [
                        'CUDAExecutionProvider',
                        'ROCMExecutionProvider',
                        'CoreMLExecutionProvider',
                        'CPUExecutionProvider',
                    ]
                    providers = [p for p in preferred if p in available]
                    gpu_provider = next((p for p in providers if p != 'CPUExecutionProvider'), None)
                    if gpu_provider:
                        logger.info(f"Museum: rembg using {gpu_provider}")
                    else:
                        logger.info("Museum: rembg using CPU (no GPU provider available)")
                        _rembg_session_cpu = True
                except ImportError:
                    pass  # onnxruntime not importable — let rembg handle it

                _rembg_session = new_session('birefnet-general', providers=providers)
            else:
                logger.info(f"Museum: rembg reusing cached {'CPU' if _rembg_session_cpu else 'GPU'} session")

            try:
                result = rembg_remove(image_data, session=_rembg_session, post_process_mask=True)
            except Exception as e:
                # GPU session failed at runtime — permanently fall back to CPU
                if not _rembg_session_cpu:
                    logger.warning(f"Museum: rembg GPU failed ({e}), switching to CPU session")
                    _rembg_session = new_session('birefnet-general', providers=['CPUExecutionProvider'])
                    _rembg_session_cpu = True
                    result = rembg_remove(image_data, session=_rembg_session, post_process_mask=True)
                else:
                    raise
        logger.info("Museum: Background removed via rembg birefnet-general (local)")
        return result
    except ImportError:
        logger.info("Museum: rembg not installed, skipping background removal")
    except Exception as e:
        logger.warning(f"Museum: rembg error: {e}")

    return image_data


def _build_controller_search_queries(controller_name, manufacturer, system_name):
    """Build a ranked list of Bing search queries for a controller image.

    Returns multiple query strings to try in order — the first one that
    yields usable image results wins.
    """
    # Strip parenthesized model numbers from the name
    clean_name = re.sub(r'\s*\([^)]*\)', '', controller_name).strip()

    # Build a short system label for context (e.g. "PS3", "SNES", "Nintendo 64")
    # Use the system name as-is — it already contains the console identity
    sys_ctx = f" {system_name}" if system_name else ""

    # Peripheral type detection — these need "video game" context to avoid
    # returning real instruments, webcams, etc.
    peripheral_keywords = {
        'guitar': 'video game guitar controller',
        'drum': 'video game drum controller',
        'keyboard': 'video game keyboard controller',
        'microphone': 'video game USB microphone',
        'mic ': 'video game USB microphone',
        'wheel': 'racing wheel',
        'eye': 'camera peripheral',
        'camera': 'camera peripheral',
        'gun': 'light gun',
        'shooter': 'gun peripheral',
        'keypad': 'keypad attachment',
        'dance': 'dance pad',
        'mat': 'dance mat',
        'turntable': 'DJ turntable controller',
        'fishing': 'fishing controller',
        'maracas': 'maraca controller',
    }

    # Determine the best descriptor for this peripheral type
    name_lower = clean_name.lower()
    descriptor = 'controller'
    for kw, desc in peripheral_keywords.items():
        if kw in name_lower:
            descriptor = desc
            break

    mfr = f" {manufacturer}" if manufacturer else ""

    queries = []

    # Primary: clean name + system + descriptor + product photo
    queries.append(f"{clean_name}{sys_ctx}{mfr} {descriptor} product photo")

    # Fallback 1: without manufacturer (sometimes manufacturer name conflicts)
    queries.append(f"{clean_name}{sys_ctx} {descriptor} product photo")

    # Fallback 2: simplified — just name + system + "official"
    queries.append(f"{clean_name}{sys_ctx} official product image")

    return queries


def _fetch_and_process_image(controller_id, controller_name, manufacturer,
                             system_name, removebg_key):
    """Search for a controller image, remove background, save as webp.

    Uses Bing Image Search to find real image URLs, downloads the best one,
    removes the background via rembg or remove.bg, and saves as webp.

    Returns:
        Filename on success, None on failure.
    """
    from PIL import Image
    import io

    queries = _build_controller_search_queries(controller_name, manufacturer, system_name)

    # Try each query variant until we get results
    image_urls = []
    for query in queries:
        image_urls = _bing_image_search(query)
        if image_urls:
            logger.info(f"Museum: Search hit with query: {query}")
            break

    if not image_urls:
        logger.warning(f"Museum: No image search results for {controller_name}")
        return None

    # Try each result until we get a usable image (minimum 200x200).
    # Pass 25.3 — every candidate URL goes through the SSRF guard: private
    # IP rejection, redirect cap, HEAD/GET both with allow_redirects=False.
    image_data = None
    max_bytes = getattr(config, 'MAX_MEDIA_DOWNLOAD_BYTES', 50 * 1024 * 1024)
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    from services.ssrf import pin_host_ip
    for image_url in image_urls:
        safe_url, pinned_ip, err = _is_public_https_url(image_url)
        if err:
            logger.warning(f"Museum: rejected SSRF candidate {image_url}: {err}")
            continue
        # Pass 32.7: pin the resolved IP for the duration of the GET so a
        # hostile DNS server can't flip the record between validation and
        # fetch (classic DNS-rebinding SSRF).
        parsed_host = urlparse(safe_url).hostname
        try:
            # Stream so we can enforce a byte budget and bail on giant bodies
            # before they fill memory. allow_redirects is False because every
            # redirect hop was already vetted by _is_public_https_url.
            with pin_host_ip(parsed_host, pinned_ip), requests.get(
                safe_url, timeout=15, headers=headers,
                stream=True, allow_redirects=False,
            ) as resp:
                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    continue

                declared = int(resp.headers.get('Content-Length', 0) or 0)
                if declared and declared > max_bytes:
                    logger.warning(
                        f"Museum: response too large ({declared} > {max_bytes}): {safe_url}"
                    )
                    continue

                body = bytearray()
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        logger.warning(
                            f"Museum: streaming size exceeded {max_bytes}: {safe_url}"
                        )
                        body = None
                        break
                if body is None:
                    continue
                data_bytes = bytes(body)

            if len(data_bytes) < 5000:
                continue

            # Check actual image dimensions
            try:
                img_check = Image.open(io.BytesIO(data_bytes))
                w, h = img_check.size
                if w < 200 or h < 200:
                    continue
            except Exception:
                continue

            image_data = data_bytes
            logger.info(f"Museum: Downloaded {w}x{h} image for {controller_name}")
            break
        except Exception:
            continue

    if not image_data:
        logger.warning(f"Museum: All image downloads failed for {controller_name}")
        return None

    # Remove background (rembg local AI, or remove.bg API if key configured)
    processed = _remove_background(image_data, removebg_key)

    return _persist_controller_image(controller_id, processed)
