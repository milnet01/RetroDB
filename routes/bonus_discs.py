# =============================================================================
# RETRODB - Bonus Discs Blueprint
# =============================================================================
# Handles bonus disc detection, linking, and management.
# =============================================================================

from flask import Blueprint, request, jsonify
import os
import re
import logging

from services.database import query, execute
from services.game_utils import is_bonus_disc_title, extract_base_game_title
from services.auth import login_required, editor_required

logger = logging.getLogger(__name__)

bp = Blueprint('bonus_discs', __name__)

# =============================================================================
# BONUS DISC HELPER FUNCTIONS
# =============================================================================

def find_potential_parent_games(bonus_game_id, system_id):
    """
    Find potential parent games for a bonus disc within the same system.

    Returns a list of games that could be the parent.
    """
    bonus_game = query("SELECT title, rom_path FROM games WHERE id = ?", (bonus_game_id,), one=True)
    if not bonus_game:
        return []

    # Try to extract base title from title first, then from ROM filename
    base_title = extract_base_game_title(bonus_game['title'])

    if not base_title and bonus_game.get('rom_path'):
        # Title didn't have bonus pattern, try the filename
        filename = os.path.basename(bonus_game['rom_path'])
        base_title = extract_base_game_title(filename)

    if not base_title:
        return []

    # Strip edition suffixes to get core title for broader matching
    # "Call of Duty 3 Special Edition" -> "Call of Duty 3"
    # "Mortal Kombat - Armageddon Kollectors Edition" -> "Mortal Kombat - Armageddon"
    core_title = re.sub(
        r"\s*(Special|Collector'?s?|Kollector'?s?|Limited|Game of the Year|GOTY|Premium|Deluxe|Ultimate|Gold|Platinum)\s*(Edition)?$",
        '', base_title, flags=re.IGNORECASE
    ).strip()

    # Create a normalized version for comparison (remove colons, dashes, extra spaces)
    # This handles cases like "Persona 2 Eternal Punishment" matching "Persona 2: Eternal Punishment"
    def normalize_for_search(title):
        # Remove colons, dashes, and normalize spaces
        return re.sub(r'[\s]+', ' ', re.sub(r'[:\-–]', ' ', title)).strip()

    base_normalized = normalize_for_search(base_title)
    core_normalized = normalize_for_search(core_title)

    # Escape special LIKE characters so %, _, \ in titles are matched literally
    def escape_like(value):
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    base_escaped = escape_like(base_title)
    core_escaped = escape_like(core_title)
    base_norm_escaped = escape_like(base_normalized)
    core_norm_escaped = escape_like(core_normalized)

    # Search for games with similar titles in the same system
    # Use REPLACE to normalize DB titles for comparison (remove : and -)
    # This allows "Persona 2 Eternal Punishment" to match "Persona 2: Eternal Punishment"
    potential_parents = query("""
        SELECT id, title, boxart
        FROM games
        WHERE system_id = ?
          AND id != ?
          AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
          AND (
              -- Direct matches
              title LIKE ? ESCAPE '\\'
              OR title LIKE ? ESCAPE '\\'
              -- Normalized matches (remove colons and dashes from both sides)
              OR REPLACE(REPLACE(REPLACE(title, ':', ' '), '-', ' '), '  ', ' ') LIKE ? ESCAPE '\\'
              OR REPLACE(REPLACE(REPLACE(title, ':', ' '), '-', ' '), '  ', ' ') LIKE ? ESCAPE '\\'
              -- Reverse: search term contains DB title
              OR ? LIKE title || '%'
              OR ? LIKE title || '%'
          )
        ORDER BY
            CASE
                WHEN title = ? THEN 0
                WHEN title = ? THEN 1
                WHEN REPLACE(REPLACE(title, ':', ' '), '-', ' ') = ? THEN 2
                WHEN REPLACE(REPLACE(title, ':', ' '), '-', ' ') = ? THEN 3
                ELSE 4
            END,
            length(title) DESC,
            title
        LIMIT 10
    """, (system_id, bonus_game_id,
          f"{base_escaped}%", f"{core_escaped}%",
          f"{base_norm_escaped}%", f"{core_norm_escaped}%",
          base_title, core_title,
          base_title, core_title, base_normalized, core_normalized))

    return [dict(row) for row in potential_parents]


def auto_detect_bonus_discs(system_id=None):
    """
    Scan games and auto-detect bonus discs based on title patterns.

    Args:
        system_id: Optional - limit scan to specific system

    Returns:
        dict with 'detected' count and list of 'games'
    """
    if system_id:
        games = query("""
            SELECT g.id, g.title, g.system_id, g.rom_path, s.name as system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.system_id = ? AND (g.is_bonus_disc = 0 OR g.is_bonus_disc IS NULL)
        """, (system_id,))
    else:
        games = query("""
            SELECT g.id, g.title, g.system_id, g.rom_path, s.name as system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.is_bonus_disc = 0 OR g.is_bonus_disc IS NULL
        """)

    detected = []
    for game in games:
        # Check both title and ROM filename for bonus disc patterns
        title_match = is_bonus_disc_title(game['title'])
        rom_match = False
        filename = None
        if game.get('rom_path'):
            # Extract filename from path and check it too
            filename = os.path.basename(game['rom_path'])
            rom_match = is_bonus_disc_title(filename)

        if title_match or rom_match:
            # Extract base title from whichever source matched
            base_title = extract_base_game_title(game['title'])
            match_source = 'title'

            if not base_title and filename:
                base_title = extract_base_game_title(filename)
                match_source = 'filename'

            # If we matched on filename but title extraction worked, still note it
            if rom_match and not title_match:
                match_source = 'filename'

            detected.append({
                'id': game['id'],
                'title': game['title'],
                'system_id': game['system_id'],
                'system_name': game.get('system_name', 'Unknown'),
                'base_title': base_title,
                'match_source': match_source,
                'filename': filename if rom_match else None
            })

    return {
        'detected': len(detected),
        'games': detected
    }


def link_bonus_disc_to_parent(bonus_game_id, parent_game_id):
    """
    Link a bonus disc to its parent game.

    Returns success status and message.
    """
    try:
        # Verify both games exist and are in the same system
        bonus = query("SELECT id, title, system_id FROM games WHERE id = ?", (bonus_game_id,), one=True)
        parent = query("SELECT id, title, system_id FROM games WHERE id = ?", (parent_game_id,), one=True)

        if not bonus:
            return {'success': False, 'error': 'Bonus disc not found'}
        if not parent:
            return {'success': False, 'error': 'Parent game not found'}
        if bonus['system_id'] != parent['system_id']:
            return {'success': False, 'error': 'Bonus disc and parent game must be in the same system'}

        # Update the bonus disc
        execute("""
            UPDATE games
            SET is_bonus_disc = 1, parent_game_id = ?
            WHERE id = ?
        """, (parent_game_id, bonus_game_id))

        logger.info(f"Linked bonus disc '{bonus['title']}' to parent '{parent['title']}'")
        return {'success': True, 'message': f"Linked '{bonus['title']}' to '{parent['title']}'"}

    except Exception as e:
        logger.error(f"Error linking bonus disc: {e}")
        return {'success': False, 'error': 'An internal error occurred'}


def unlink_bonus_disc(bonus_game_id):
    """
    Remove the bonus disc link from a game.
    """
    try:
        execute("""
            UPDATE games
            SET is_bonus_disc = 0, parent_game_id = NULL
            WHERE id = ?
        """, (bonus_game_id,))

        return {'success': True, 'message': 'Bonus disc unlinked'}

    except Exception as e:
        logger.error(f"Error unlinking bonus disc: {e}")
        return {'success': False, 'error': 'An internal error occurred'}


def get_bonus_discs_for_game(parent_game_id):
    """
    Get all bonus discs linked to a parent game.
    """
    return query("""
        SELECT id, title, boxart, rom_path
        FROM games
        WHERE parent_game_id = ? AND is_bonus_disc = 1
        ORDER BY title
    """, (parent_game_id,))


# =============================================================================
# BONUS DISC ROUTES
# =============================================================================

@bp.route('/api/bonus-discs/detect')
@login_required
def api_detect_bonus_discs():
    """Detect potential bonus discs based on title patterns"""
    try:
        system_id = request.args.get('system_id', type=int)
        result = auto_detect_bonus_discs(system_id)
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"Error detecting bonus discs: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/potential-parents/<int:game_id>')
@login_required
def api_get_potential_parents(game_id):
    """Get potential parent games for a bonus disc"""
    try:
        game = query("SELECT system_id FROM games WHERE id = ?", (game_id,), one=True)
        if not game:
            return jsonify({'success': False, 'error': 'Game not found'})

        parents = find_potential_parent_games(game_id, game['system_id'])
        return jsonify({'success': True, 'parents': parents})
    except Exception as e:
        logger.error(f"Error finding potential parents: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/link', methods=['POST'])
@editor_required
def api_link_bonus_disc():
    """Link a bonus disc to its parent game"""
    try:
        data = request.get_json()
        bonus_id = data.get('bonus_id')
        parent_id = data.get('parent_id')

        if not bonus_id or not parent_id:
            return jsonify({'success': False, 'error': 'Missing bonus_id or parent_id'})

        result = link_bonus_disc_to_parent(bonus_id, parent_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error linking bonus disc: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/unlink/<int:game_id>', methods=['POST'])
@editor_required
def api_unlink_bonus_disc(game_id):
    """Unlink a bonus disc from its parent"""
    try:
        result = unlink_bonus_disc(game_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error unlinking bonus disc: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/mark', methods=['POST'])
@editor_required
def api_mark_bonus_disc():
    """Manually mark a game as a bonus disc (without linking to parent)"""
    try:
        data = request.get_json()
        game_id = data.get('game_id')
        is_bonus = data.get('is_bonus', True)

        if not game_id:
            return jsonify({'success': False, 'error': 'Missing game_id'})

        execute("UPDATE games SET is_bonus_disc = ? WHERE id = ?",
               (1 if is_bonus else 0, game_id))

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error marking bonus disc: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/for-game/<int:game_id>')
@login_required
def api_get_bonus_discs_for_game(game_id):
    """Get all bonus discs linked to a parent game"""
    try:
        bonus_discs = get_bonus_discs_for_game(game_id)
        return jsonify({
            'success': True,
            'bonus_discs': [dict(b) for b in bonus_discs]
        })
    except Exception as e:
        logger.error(f"Error getting bonus discs: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/stats')
@login_required
def api_bonus_disc_stats():
    """Get statistics about bonus discs"""
    try:
        total_bonus = query("SELECT COUNT(*) as count FROM games WHERE is_bonus_disc = 1", one=True)['count']
        linked = query("SELECT COUNT(*) as count FROM games WHERE is_bonus_disc = 1 AND parent_game_id IS NOT NULL", one=True)['count']
        unlinked = total_bonus - linked

        # Count unique parent games that have bonus content
        parents_with_bonus = query("SELECT COUNT(DISTINCT parent_game_id) as count FROM games WHERE is_bonus_disc = 1 AND parent_game_id IS NOT NULL", one=True)['count']

        # Get list of current bonus discs
        bonus_list = query("""
            SELECT g.id, g.title, g.boxart, g.system_id, g.parent_game_id,
                   s.name as system_name,
                   p.title as parent_title
            FROM games g
            JOIN systems s ON g.system_id = s.id
            LEFT JOIN games p ON g.parent_game_id = p.id
            WHERE g.is_bonus_disc = 1
            ORDER BY s.name, g.title
        """)

        return jsonify({
            'success': True,
            'total_bonus': total_bonus,
            'linked': linked,
            'unlinked': unlinked,
            'parents_with_bonus': parents_with_bonus,
            'bonus_discs': [dict(b) for b in bonus_list]
        })
    except Exception as e:
        logger.error(f"Error getting bonus disc stats: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/bonus-discs/auto-link', methods=['POST'])
@editor_required
def api_auto_link_bonus_discs():
    """Auto-detect and link bonus discs to their parent games"""
    try:
        system_id = request.args.get('system_id', type=int)

        # Detect bonus discs
        result = auto_detect_bonus_discs(system_id)

        linked_count = 0
        for game in result['games']:
            # Mark as bonus disc
            execute("UPDATE games SET is_bonus_disc = 1 WHERE id = ?", (game['id'],))

            # Try to find and link parent
            if game['base_title']:
                # Look for exact or close title match
                parent = query("""
                    SELECT id FROM games
                    WHERE system_id = ?
                      AND id != ?
                      AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
                      AND (title = ? OR title LIKE ?)
                    ORDER BY
                        CASE WHEN title = ? THEN 0 ELSE 1 END
                    LIMIT 1
                """, (game['system_id'], game['id'], game['base_title'],
                      f"{game['base_title']}%", game['base_title']), one=True)

                if parent:
                    execute("UPDATE games SET parent_game_id = ? WHERE id = ?",
                           (parent['id'], game['id']))
                    linked_count += 1

        return jsonify({
            'success': True,
            'detected': result['detected'],
            'linked': linked_count,
            'message': f"Detected {result['detected']} bonus discs, linked {linked_count} to parent games"
        })
    except Exception as e:
        logger.error(f"Error auto-linking bonus discs: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})
