# =============================================================================
# RETRODB - Collections Blueprint
# =============================================================================
# Handles Tags, Named Lists, and Wishlist features for game organization.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify
import logging
from datetime import datetime, timezone

from services.database import query, execute
from services.auth import login_required

logger = logging.getLogger(__name__)

bp = Blueprint('collections', __name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _utcnow_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# =============================================================================
# PAGE ROUTES
# =============================================================================

@bp.route('/tags')
@login_required
def tags_page():
    """Tags management page - show all tags with game counts."""
    tags = query("""
        SELECT t.id, t.name, t.color, t.created_at, COUNT(gt.game_id) AS game_count
        FROM tags t
        LEFT JOIN game_tags gt ON gt.tag_id = t.id
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
    """)
    return render_template('tags.html', tags=tags)


@bp.route('/lists')
@login_required
def lists_page():
    """Lists overview page - show all named lists."""
    lists = query("""
        SELECT l.id, l.name, l.description, l.icon, l.sort_order, l.created_at,
               COUNT(lg.game_id) AS game_count
        FROM lists l
        LEFT JOIN list_games lg ON lg.list_id = l.id
        GROUP BY l.id
        ORDER BY l.sort_order, l.name COLLATE NOCASE
    """)
    return render_template('lists.html', lists=lists)


@bp.route('/list/<int:list_id>')
@login_required
def list_detail_page(list_id):
    """View a specific list's games."""
    lst = query("SELECT * FROM lists WHERE id = ?", (list_id,), one=True)
    if not lst:
        return render_template('lists.html', lists=[], error='List not found'), 404

    games = query("""
        SELECT g.*, lg.position, lg.added_at AS list_added_at
        FROM list_games lg
        JOIN games g ON g.id = lg.game_id
        WHERE lg.list_id = ?
        ORDER BY lg.position, g.title COLLATE NOCASE
    """, (list_id,))
    return render_template('list_detail.html', list=lst, games=games)


@bp.route('/wishlist')
@login_required
def wishlist_page():
    """Wishlist page."""
    items = query("""
        SELECT w.*, g.title AS linked_game_title, s.name AS linked_system
        FROM wishlist w
        LEFT JOIN games g ON g.id = w.game_id
        LEFT JOIN systems s ON g.system_id = s.id
        ORDER BY w.priority ASC, w.added_at DESC
    """)
    return render_template('wishlist.html', items=items)


# =============================================================================
# TAG API ROUTES
# =============================================================================

@bp.route('/api/tags', methods=['GET'])
@login_required
def api_get_tags():
    """Get all tags with game count."""
    tags = query("""
        SELECT t.id, t.name, t.color, t.created_at, COUNT(gt.game_id) AS game_count
        FROM tags t
        LEFT JOIN game_tags gt ON gt.tag_id = t.id
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
    """)
    return jsonify({'success': True, 'tags': tags})


@bp.route('/api/tags', methods=['POST'])
@login_required
def api_create_tag():
    """Create a new tag."""
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return jsonify({'success': False, 'error': 'Tag name is required'}), 400

    name = data['name'].strip()
    color = data.get('color', '#4cc9f0').strip()

    existing = query("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,), one=True)
    if existing:
        return jsonify({'success': False, 'error': 'A tag with that name already exists'}), 409

    try:
        tag_id = execute(
            "INSERT INTO tags (name, color, created_at) VALUES (?, ?, ?)",
            (name, color, _utcnow_iso())
        )
        logger.info(f"Created tag '{name}' (id={tag_id})")
        return jsonify({'success': True, 'tag': {'id': tag_id, 'name': name, 'color': color}}), 201
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/tags/<int:tag_id>', methods=['PUT'])
@login_required
def api_update_tag(tag_id):
    """Update an existing tag."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    tag = query("SELECT * FROM tags WHERE id = ?", (tag_id,), one=True)
    if not tag:
        return jsonify({'success': False, 'error': 'Tag not found'}), 404

    name = data.get('name', tag['name']).strip()
    color = data.get('color', tag['color']).strip()

    # Check for name conflict with a different tag
    if name.lower() != tag['name'].lower():
        conflict = query("SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND id != ?", (name, tag_id), one=True)
        if conflict:
            return jsonify({'success': False, 'error': 'A tag with that name already exists'}), 409

    try:
        execute("UPDATE tags SET name = ?, color = ? WHERE id = ?", (name, color, tag_id))
        logger.info(f"Updated tag id={tag_id} -> name='{name}', color='{color}'")
        return jsonify({'success': True, 'tag': {'id': tag_id, 'name': name, 'color': color}})
    except Exception as e:
        logger.error(f"Failed to update tag: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/tags/<int:tag_id>', methods=['DELETE'])
@login_required
def api_delete_tag(tag_id):
    """Delete a tag and all its game associations."""
    tag = query("SELECT * FROM tags WHERE id = ?", (tag_id,), one=True)
    if not tag:
        return jsonify({'success': False, 'error': 'Tag not found'}), 404

    try:
        execute("DELETE FROM game_tags WHERE tag_id = ?", (tag_id,))
        execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        logger.info(f"Deleted tag '{tag['name']}' (id={tag_id})")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete tag: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


# =============================================================================
# GAME-TAG API ROUTES
# =============================================================================

@bp.route('/api/games/<int:game_id>/tags', methods=['GET'])
@login_required
def api_get_game_tags(game_id):
    """Get all tags for a specific game."""
    tags = query("""
        SELECT t.id, t.name, t.color
        FROM game_tags gt
        JOIN tags t ON t.id = gt.tag_id
        WHERE gt.game_id = ?
        ORDER BY t.name COLLATE NOCASE
    """, (game_id,))
    return jsonify({'success': True, 'tags': tags})


@bp.route('/api/games/<int:game_id>/tags', methods=['POST'])
@login_required
def api_add_tag_to_game(game_id):
    """Add a tag to a game. Accepts {tag_id} or {tag_name} for auto-create."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    # Verify game exists
    game = query("SELECT id FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    tag_id = data.get('tag_id')
    tag_name = data.get('tag_name', '').strip() if data.get('tag_name') else None

    if not tag_id and not tag_name:
        return jsonify({'success': False, 'error': 'Either tag_id or tag_name is required'}), 400

    # Resolve or create the tag
    if tag_id:
        tag = query("SELECT id, name, color FROM tags WHERE id = ?", (tag_id,), one=True)
        if not tag:
            return jsonify({'success': False, 'error': 'Tag not found'}), 404
    else:
        # Look up by name, auto-create if missing
        tag = query("SELECT id, name, color FROM tags WHERE name = ? COLLATE NOCASE", (tag_name,), one=True)
        if not tag:
            new_id = execute(
                "INSERT INTO tags (name, color, created_at) VALUES (?, ?, ?)",
                (tag_name, '#4cc9f0', _utcnow_iso())
            )
            tag = {'id': new_id, 'name': tag_name, 'color': '#4cc9f0'}
            logger.info(f"Auto-created tag '{tag_name}' (id={new_id})")

    # Check if association already exists
    existing = query(
        "SELECT 1 FROM game_tags WHERE game_id = ? AND tag_id = ?",
        (game_id, tag['id']), one=True
    )
    if existing:
        return jsonify({'success': True, 'tag': tag, 'message': 'Tag already assigned'})

    try:
        execute("INSERT INTO game_tags (game_id, tag_id) VALUES (?, ?)", (game_id, tag['id']))
        logger.info(f"Added tag '{tag['name']}' to game id={game_id}")
        return jsonify({'success': True, 'tag': tag}), 201
    except Exception as e:
        logger.error(f"Failed to add tag to game: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/games/<int:game_id>/tags/<int:tag_id>', methods=['DELETE'])
@login_required
def api_remove_tag_from_game(game_id, tag_id):
    """Remove a tag from a game."""
    existing = query(
        "SELECT 1 FROM game_tags WHERE game_id = ? AND tag_id = ?",
        (game_id, tag_id), one=True
    )
    if not existing:
        return jsonify({'success': False, 'error': 'Tag is not assigned to this game'}), 404

    try:
        execute("DELETE FROM game_tags WHERE game_id = ? AND tag_id = ?", (game_id, tag_id))
        logger.info(f"Removed tag id={tag_id} from game id={game_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to remove tag from game: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


# =============================================================================
# TAG-GAMES BROWSING API
# =============================================================================

@bp.route('/api/tags/<int:tag_id>/games', methods=['GET'])
@login_required
def api_get_tag_games(tag_id):
    """Get all games that have a specific tag."""
    tag = query("SELECT id, name, color FROM tags WHERE id = ?", (tag_id,), one=True)
    if not tag:
        return jsonify({'success': False, 'error': 'Tag not found'}), 404

    games = query("""
        SELECT g.id, g.title, g.boxart, s.name AS system_name
        FROM game_tags gt
        JOIN games g ON g.id = gt.game_id
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE gt.tag_id = ?
        ORDER BY g.title COLLATE NOCASE
    """, (tag_id,))

    # Prefix boxart paths for the frontend
    for g in games:
        if g.get('boxart'):
            g['boxart'] = f"/static/images/boxart/{g['boxart']}"

    return jsonify({'success': True, 'games': games, 'tag': tag})


# =============================================================================
# LIST API ROUTES
# =============================================================================

@bp.route('/api/lists', methods=['GET'])
@login_required
def api_get_lists():
    """Get all lists with game count."""
    lists = query("""
        SELECT l.id, l.name, l.description, l.icon, l.sort_order, l.created_at,
               COUNT(lg.game_id) AS game_count
        FROM lists l
        LEFT JOIN list_games lg ON lg.list_id = l.id
        GROUP BY l.id
        ORDER BY l.sort_order, l.name COLLATE NOCASE
    """)
    return jsonify({'success': True, 'lists': lists})


@bp.route('/api/lists', methods=['POST'])
@login_required
def api_create_list():
    """Create a new named list."""
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return jsonify({'success': False, 'error': 'List name is required'}), 400

    name = data['name'].strip()
    description = data.get('description', '').strip()
    icon = data.get('icon', '').strip()

    # Determine next sort_order
    max_order = query("SELECT MAX(sort_order) AS max_order FROM lists", one=True)
    next_order = (max_order['max_order'] or 0) + 1 if max_order else 1

    try:
        list_id = execute(
            "INSERT INTO lists (name, description, icon, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, description, icon, next_order, _utcnow_iso())
        )
        logger.info(f"Created list '{name}' (id={list_id})")
        return jsonify({
            'success': True,
            'list': {
                'id': list_id, 'name': name, 'description': description,
                'icon': icon, 'sort_order': next_order
            }
        }), 201
    except Exception as e:
        logger.error(f"Failed to create list: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/lists/<int:list_id>', methods=['PUT'])
@login_required
def api_update_list(list_id):
    """Update an existing list."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    lst = query("SELECT * FROM lists WHERE id = ?", (list_id,), one=True)
    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    name = (data.get('name', lst['name']) or '').strip()
    description = (data.get('description', lst['description']) or '').strip()
    icon = (data.get('icon', lst['icon']) or '').strip()
    sort_order = data.get('sort_order', lst['sort_order'])

    try:
        execute(
            "UPDATE lists SET name = ?, description = ?, icon = ?, sort_order = ? WHERE id = ?",
            (name, description, icon, sort_order, list_id)
        )
        logger.info(f"Updated list id={list_id} -> name='{name}'")
        return jsonify({
            'success': True,
            'list': {
                'id': list_id, 'name': name, 'description': description,
                'icon': icon, 'sort_order': sort_order
            }
        })
    except Exception as e:
        logger.error(f"Failed to update list: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/lists/<int:list_id>', methods=['DELETE'])
@login_required
def api_delete_list(list_id):
    """Delete a list and all its game associations."""
    lst = query("SELECT * FROM lists WHERE id = ?", (list_id,), one=True)
    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    try:
        execute("DELETE FROM list_games WHERE list_id = ?", (list_id,))
        execute("DELETE FROM lists WHERE id = ?", (list_id,))
        logger.info(f"Deleted list '{lst['name']}' (id={list_id})")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete list: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


# =============================================================================
# LIST-GAMES API ROUTES
# =============================================================================

@bp.route('/api/lists/<int:list_id>/games', methods=['GET'])
@login_required
def api_get_list_games(list_id):
    """Get all games in a list."""
    lst = query("SELECT id FROM lists WHERE id = ?", (list_id,), one=True)
    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    games = query("""
        SELECT g.*, lg.position, lg.added_at AS list_added_at
        FROM list_games lg
        JOIN games g ON g.id = lg.game_id
        WHERE lg.list_id = ?
        ORDER BY lg.position, g.title COLLATE NOCASE
    """, (list_id,))
    return jsonify({'success': True, 'games': games})


@bp.route('/api/lists/<int:list_id>/games', methods=['POST'])
@login_required
def api_add_game_to_list(list_id):
    """Add a game to a list."""
    data = request.get_json()
    if not data or not data.get('game_id'):
        return jsonify({'success': False, 'error': 'game_id is required'}), 400

    game_id = data['game_id']

    lst = query("SELECT id FROM lists WHERE id = ?", (list_id,), one=True)
    if not lst:
        return jsonify({'success': False, 'error': 'List not found'}), 404

    game = query("SELECT id, title FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    existing = query(
        "SELECT 1 FROM list_games WHERE list_id = ? AND game_id = ?",
        (list_id, game_id), one=True
    )
    if existing:
        return jsonify({'success': True, 'message': 'Game already in list'})

    # Determine next position
    max_pos = query(
        "SELECT MAX(position) AS max_pos FROM list_games WHERE list_id = ?",
        (list_id,), one=True
    )
    next_pos = (max_pos['max_pos'] or 0) + 1 if max_pos else 1

    try:
        execute(
            "INSERT INTO list_games (list_id, game_id, position, added_at) VALUES (?, ?, ?, ?)",
            (list_id, game_id, next_pos, _utcnow_iso())
        )
        logger.info(f"Added game '{game['title']}' (id={game_id}) to list id={list_id}")
        return jsonify({'success': True}), 201
    except Exception as e:
        logger.error(f"Failed to add game to list: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/lists/<int:list_id>/games/<int:game_id>', methods=['DELETE'])
@login_required
def api_remove_game_from_list(list_id, game_id):
    """Remove a game from a list."""
    existing = query(
        "SELECT 1 FROM list_games WHERE list_id = ? AND game_id = ?",
        (list_id, game_id), one=True
    )
    if not existing:
        return jsonify({'success': False, 'error': 'Game is not in this list'}), 404

    try:
        execute("DELETE FROM list_games WHERE list_id = ? AND game_id = ?", (list_id, game_id))
        logger.info(f"Removed game id={game_id} from list id={list_id}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to remove game from list: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


# =============================================================================
# WISHLIST API ROUTES
# =============================================================================

@bp.route('/api/wishlist', methods=['GET'])
@login_required
def api_get_wishlist():
    """Get all wishlist items."""
    items = query("""
        SELECT w.*, g.title AS linked_game_title, s.name AS linked_system
        FROM wishlist w
        LEFT JOIN games g ON g.id = w.game_id
        LEFT JOIN systems s ON g.system_id = s.id
        ORDER BY w.priority ASC, w.added_at DESC
    """)
    return jsonify({'success': True, 'items': items})


@bp.route('/api/wishlist', methods=['POST'])
@login_required
def api_add_to_wishlist():
    """Add an item to the wishlist."""
    data = request.get_json()
    if not data or not data.get('title', '').strip():
        return jsonify({'success': False, 'error': 'Title is required'}), 400

    title = data['title'].strip()
    system_name = data.get('system_name', '').strip()
    notes = data.get('notes', '').strip()
    priority = data.get('priority', 2)
    game_id = data.get('game_id')

    # Validate priority range
    if not isinstance(priority, int) or priority < 1 or priority > 5:
        return jsonify({'success': False, 'error': 'Priority must be an integer between 1 and 5'}), 400

    # Check for duplicates (same title, case-insensitive)
    existing = query(
        "SELECT id FROM wishlist WHERE title = ? COLLATE NOCASE",
        (title,), one=True
    )
    if existing:
        return jsonify({'success': False, 'error': 'This game is already on your wishlist'}), 409

    try:
        item_id = execute(
            "INSERT INTO wishlist (title, system_name, notes, priority, added_at, game_id) VALUES (?, ?, ?, ?, ?, ?)",
            (title, system_name, notes, priority, _utcnow_iso(), game_id)
        )
        logger.info(f"Added '{title}' to wishlist (id={item_id})")
        return jsonify({
            'success': True,
            'item': {
                'id': item_id, 'title': title, 'system_name': system_name,
                'notes': notes, 'priority': priority, 'game_id': game_id
            }
        }), 201
    except Exception as e:
        logger.error(f"Failed to add to wishlist: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/wishlist/<int:item_id>', methods=['PUT'])
@login_required
def api_update_wishlist_item(item_id):
    """Update a wishlist item."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    item = query("SELECT * FROM wishlist WHERE id = ?", (item_id,), one=True)
    if not item:
        return jsonify({'success': False, 'error': 'Wishlist item not found'}), 404

    title = (data.get('title', item['title']) or '').strip()
    system_name = (data.get('system_name', item['system_name']) or '').strip()
    notes = (data.get('notes', item['notes']) or '').strip()
    priority = data.get('priority', item['priority'])
    game_id = data.get('game_id', item['game_id'])

    if not isinstance(priority, int) or priority < 1 or priority > 5:
        return jsonify({'success': False, 'error': 'Priority must be an integer between 1 and 5'}), 400

    try:
        execute(
            "UPDATE wishlist SET title = ?, system_name = ?, notes = ?, priority = ?, game_id = ? WHERE id = ?",
            (title, system_name, notes, priority, game_id, item_id)
        )
        logger.info(f"Updated wishlist item id={item_id} -> title='{title}'")
        return jsonify({
            'success': True,
            'item': {
                'id': item_id, 'title': title, 'system_name': system_name,
                'notes': notes, 'priority': priority, 'game_id': game_id
            }
        })
    except Exception as e:
        logger.error(f"Failed to update wishlist item: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/wishlist/<int:item_id>', methods=['DELETE'])
@login_required
def api_delete_wishlist_item(item_id):
    """Delete a wishlist item."""
    item = query("SELECT * FROM wishlist WHERE id = ?", (item_id,), one=True)
    if not item:
        return jsonify({'success': False, 'error': 'Wishlist item not found'}), 404

    try:
        execute("DELETE FROM wishlist WHERE id = ?", (item_id,))
        logger.info(f"Deleted wishlist item '{item['title']}' (id={item_id})")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Failed to delete wishlist item: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
