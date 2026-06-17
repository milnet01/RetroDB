# =============================================================================
# RETRODB - Collections Blueprint
# =============================================================================
# Handles Tags, Named Lists, and Wishlist features for game organization.
#
# Per-user data ownership (Pass 27.1): every row carries an `owner_id`. Reads
# and mutations are restricted to the current user's rows; admins see and
# mutate everyone's. Routes use `_owner_clause()` (a fragment + params tuple)
# to splice the filter into queries without each callsite repeating the
# admin-bypass logic.
# =============================================================================

from flask import Blueprint, render_template, request, g
from flask_babel import gettext as _
import logging
from datetime import datetime, timezone

from services.database import query, execute
from services.auth import login_required
from services.api_helpers import handle_api_errors, success, error

logger = logging.getLogger(__name__)

bp = Blueprint('collections', __name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _utcnow_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _owner_clause(table_alias=''):
    """Per-user ownership filter for collections rows.

    Admins see every row; everyone else sees only their own. Returns
    (sql_fragment, params_tuple) ready to splice into a WHERE / AND.
    `table_alias` should be the alias used in the surrounding query
    (e.g. 't' for `tags t`); pass '' for unaliased SELECT * style queries.
    """
    col = f"{table_alias}.owner_id" if table_alias else "owner_id"
    if not g.user:
        # Fail closed: with no authenticated user, match no rows rather than
        # dereferencing g.user['id'] and raising. All callers are
        # @login_required today, but this keeps the helper safe if one isn't.
        return ("1=0", ())
    if g.user['role'] == 'admin':
        return ("1=1", ())
    return (f"{col} = ?", (g.user['id'],))


# =============================================================================
# PAGE ROUTES
# =============================================================================

@bp.route('/tags')
@login_required
def tags_page():
    """Tags management page - show all tags with game counts."""
    owner_sql, owner_params = _owner_clause('t')
    tags = query(f"""
        SELECT t.id, t.name, t.color, t.created_at, COUNT(gt.game_id) AS game_count
        FROM tags t
        LEFT JOIN game_tags gt ON gt.tag_id = t.id
        WHERE {owner_sql}
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
    """, owner_params)
    return render_template('tags.html', tags=tags)


@bp.route('/lists')
@login_required
def lists_page():
    """Lists overview page - show all named lists."""
    owner_sql, owner_params = _owner_clause('l')
    lists = query(f"""
        SELECT l.id, l.name, l.description, l.icon, l.sort_order, l.created_at,
               COUNT(lg.game_id) AS game_count
        FROM lists l
        LEFT JOIN list_games lg ON lg.list_id = l.id
        WHERE {owner_sql}
        GROUP BY l.id
        ORDER BY l.sort_order, l.name COLLATE NOCASE
    """, owner_params)
    return render_template('lists.html', lists=lists)


@bp.route('/list/<int:list_id>')
@login_required
def list_detail_page(list_id):
    """View a specific list's games."""
    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT * FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return render_template('lists.html', lists=[], error=_('List not found')), 404

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
    owner_sql, owner_params = _owner_clause('w')
    items = query(f"""
        SELECT w.*,
               g.title AS linked_game_title,
               gs.name AS linked_system,
               ws.name AS wishlist_system_name
        FROM wishlist w
        LEFT JOIN games g ON g.id = w.game_id
        LEFT JOIN systems gs ON g.system_id = gs.id
        LEFT JOIN systems ws ON ws.id = w.system_id
        WHERE {owner_sql}
        ORDER BY w.priority ASC, w.added_at DESC
    """, owner_params)
    return render_template('wishlist.html', items=items)


# =============================================================================
# TAG API ROUTES
# =============================================================================

@bp.route('/api/tags', methods=['GET'])
@login_required
def api_get_tags():
    """Get all tags with game count."""
    owner_sql, owner_params = _owner_clause('t')
    tags = query(f"""
        SELECT t.id, t.name, t.color, t.created_at, COUNT(gt.game_id) AS game_count
        FROM tags t
        LEFT JOIN game_tags gt ON gt.tag_id = t.id
        WHERE {owner_sql}
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
    """, owner_params)
    return success(tags=tags)


@bp.route('/api/tags', methods=['POST'])
@login_required
@handle_api_errors
def api_create_tag():
    """Create a new tag."""
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return error(_('Tag name is required'), 400)

    name = data['name'].strip()
    color = data.get('color', '#4cc9f0').strip()

    # Tag-name uniqueness is per-owner — two users can each have a "Favourites"
    # tag. Pre-Pass 27 the UNIQUE constraint on tags.name was global; the
    # constraint stays in the schema but we no longer validate against it
    # cross-user. (Admins still see everyone's tags via _owner_clause but
    # collisions there are intentional admin behavior.)
    existing = query(
        "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND owner_id = ?",
        (name, g.user['id']), one=True,
    )
    if existing:
        return error(_('A tag with that name already exists'), 409)

    tag_id = execute(
        "INSERT INTO tags (name, color, owner_id, created_at) VALUES (?, ?, ?, ?)",
        (name, color, g.user['id'], _utcnow_iso())
    )
    logger.info(f"Created tag '{name}' (id={tag_id}, owner={g.user['id']})")
    return success(tag={'id': tag_id, 'name': name, 'color': color}), 201


@bp.route('/api/tags/<int:tag_id>', methods=['PUT'])
@login_required
@handle_api_errors
def api_update_tag(tag_id):
    """Update an existing tag."""
    data = request.get_json()
    if not data:
        return error(_('No data provided'), 400)

    owner_sql, owner_params = _owner_clause()
    tag = query(
        f"SELECT * FROM tags WHERE id = ? AND {owner_sql}",
        (tag_id, *owner_params), one=True,
    )
    if not tag:
        return error(_('Tag not found'), 404)

    name = data.get('name', tag['name']).strip()
    color = data.get('color', tag['color']).strip()

    # Conflict check is scoped to the same owner so two users with the same
    # tag name don't collide on an admin's edit.
    if name.lower() != tag['name'].lower():
        conflict = query(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND id != ? AND owner_id = ?",
            (name, tag_id, tag['owner_id']), one=True,
        )
        if conflict:
            return error(_('A tag with that name already exists'), 409)

    execute("UPDATE tags SET name = ?, color = ? WHERE id = ?", (name, color, tag_id))
    logger.info(f"Updated tag id={tag_id} -> name='{name}', color='{color}'")
    return success(tag={'id': tag_id, 'name': name, 'color': color})


@bp.route('/api/tags/<int:tag_id>', methods=['DELETE'])
@login_required
@handle_api_errors
def api_delete_tag(tag_id):
    """Delete a tag and all its game associations."""
    owner_sql, owner_params = _owner_clause()
    tag = query(
        f"SELECT * FROM tags WHERE id = ? AND {owner_sql}",
        (tag_id, *owner_params), one=True,
    )
    if not tag:
        return error(_('Tag not found'), 404)

    execute("DELETE FROM game_tags WHERE tag_id = ?", (tag_id,))
    execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    logger.info(f"Deleted tag '{tag['name']}' (id={tag_id})")
    return success()


# =============================================================================
# GAME-TAG API ROUTES
# =============================================================================

@bp.route('/api/games/<int:game_id>/tags', methods=['GET'])
@login_required
def api_get_game_tags(game_id):
    """Get all tags for a specific game (current user's tags only).

    game_tags is the join table; tags themselves are owner-scoped, so a user
    only sees tag rows they own attached to a given game.
    """
    owner_sql, owner_params = _owner_clause('t')
    tags = query(f"""
        SELECT t.id, t.name, t.color
        FROM game_tags gt
        JOIN tags t ON t.id = gt.tag_id
        WHERE gt.game_id = ? AND {owner_sql}
        ORDER BY t.name COLLATE NOCASE
    """, (game_id, *owner_params))
    return success(tags=tags)


@bp.route('/api/games/<int:game_id>/tags', methods=['POST'])
@login_required
@handle_api_errors
def api_add_tag_to_game(game_id):
    """Add a tag to a game. Accepts {tag_id} or {tag_name} for auto-create."""
    data = request.get_json()
    if not data:
        return error(_('No data provided'), 400)

    # Verify game exists
    game = query("SELECT id FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    tag_id = data.get('tag_id')
    tag_name = data.get('tag_name', '').strip() if data.get('tag_name') else None

    if not tag_id and not tag_name:
        return error(_('Either tag_id or tag_name is required'), 400)

    owner_sql, owner_params = _owner_clause()

    # Resolve or create the tag — owner-scoped lookup so non-admins can't
    # attach another user's tag.
    if tag_id:
        tag = query(
            f"SELECT id, name, color FROM tags WHERE id = ? AND {owner_sql}",
            (tag_id, *owner_params), one=True,
        )
        if not tag:
            return error(_('Tag not found'), 404)
    else:
        tag = query(
            "SELECT id, name, color FROM tags WHERE name = ? COLLATE NOCASE AND owner_id = ?",
            (tag_name, g.user['id']), one=True,
        )
        if not tag:
            new_id = execute(
                "INSERT INTO tags (name, color, owner_id, created_at) VALUES (?, ?, ?, ?)",
                (tag_name, '#4cc9f0', g.user['id'], _utcnow_iso())
            )
            tag = {'id': new_id, 'name': tag_name, 'color': '#4cc9f0'}
            logger.info(f"Auto-created tag '{tag_name}' (id={new_id}, owner={g.user['id']})")

    # Check if association already exists
    existing = query(
        "SELECT 1 FROM game_tags WHERE game_id = ? AND tag_id = ?",
        (game_id, tag['id']), one=True
    )
    if existing:
        return success(tag=tag, message='Tag already assigned')

    execute("INSERT INTO game_tags (game_id, tag_id) VALUES (?, ?)", (game_id, tag['id']))
    logger.info(f"Added tag '{tag['name']}' to game id={game_id}")
    return success(tag=tag), 201


@bp.route('/api/games/<int:game_id>/tags/<int:tag_id>', methods=['DELETE'])
@login_required
@handle_api_errors
def api_remove_tag_from_game(game_id, tag_id):
    """Remove a tag from a game.

    Caller must own the tag (or be admin); enforces ownership via a join
    to tags so non-admins can't unlink another user's tag.
    """
    owner_sql, owner_params = _owner_clause('t')
    existing = query(
        f"""SELECT 1 FROM game_tags gt
            JOIN tags t ON t.id = gt.tag_id
            WHERE gt.game_id = ? AND gt.tag_id = ? AND {owner_sql}""",
        (game_id, tag_id, *owner_params), one=True,
    )
    if not existing:
        return error(_('Tag is not assigned to this game'), 404)

    execute("DELETE FROM game_tags WHERE game_id = ? AND tag_id = ?", (game_id, tag_id))
    logger.info(f"Removed tag id={tag_id} from game id={game_id}")
    return success()


# =============================================================================
# TAG-GAMES BROWSING API
# =============================================================================

@bp.route('/api/tags/<int:tag_id>/games', methods=['GET'])
@login_required
def api_get_tag_games(tag_id):
    """Get all games that have a specific tag."""
    owner_sql, owner_params = _owner_clause()
    tag = query(
        f"SELECT id, name, color FROM tags WHERE id = ? AND {owner_sql}",
        (tag_id, *owner_params), one=True,
    )
    if not tag:
        return error(_('Tag not found'), 404)

    games = query("""
        SELECT g.id, g.title, g.boxart, s.name AS system_name
        FROM game_tags gt
        JOIN games g ON g.id = gt.game_id
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE gt.tag_id = ?
        ORDER BY g.title COLLATE NOCASE
    """, (tag_id,))

    # Prefix boxart paths for the frontend
    for g_row in games:
        if g_row.get('boxart'):
            g_row['boxart'] = f"/static/images/boxart/{g_row['boxart']}"

    return success(games=games, tag=tag)


# =============================================================================
# LIST API ROUTES
# =============================================================================

@bp.route('/api/lists', methods=['GET'])
@login_required
def api_get_lists():
    """Get all lists with game count."""
    owner_sql, owner_params = _owner_clause('l')
    lists = query(f"""
        SELECT l.id, l.name, l.description, l.icon, l.sort_order, l.created_at,
               COUNT(lg.game_id) AS game_count
        FROM lists l
        LEFT JOIN list_games lg ON lg.list_id = l.id
        WHERE {owner_sql}
        GROUP BY l.id
        ORDER BY l.sort_order, l.name COLLATE NOCASE
    """, owner_params)
    return success(lists=lists)


@bp.route('/api/lists', methods=['POST'])
@login_required
@handle_api_errors
def api_create_list():
    """Create a new named list."""
    data = request.get_json()
    if not data or not data.get('name', '').strip():
        return error(_('List name is required'), 400)

    name = data['name'].strip()
    description = data.get('description', '').strip()
    icon = data.get('icon', '').strip()

    # sort_order is per-owner so two users' lists don't fight for slot 1.
    max_order = query(
        "SELECT MAX(sort_order) AS max_order FROM lists WHERE owner_id = ?",
        (g.user['id'],), one=True,
    )
    next_order = (max_order['max_order'] or 0) + 1 if max_order else 1

    list_id = execute(
        "INSERT INTO lists (name, description, icon, sort_order, owner_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, description, icon, next_order, g.user['id'], _utcnow_iso())
    )
    logger.info(f"Created list '{name}' (id={list_id}, owner={g.user['id']})")
    return success(list={
        'id': list_id, 'name': name, 'description': description,
        'icon': icon, 'sort_order': next_order,
    }), 201


@bp.route('/api/lists/<int:list_id>', methods=['PUT'])
@login_required
@handle_api_errors
def api_update_list(list_id):
    """Update an existing list."""
    data = request.get_json()
    if not data:
        return error(_('No data provided'), 400)

    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT * FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return error(_('List not found'), 404)

    name = (data.get('name', lst['name']) or '').strip()
    description = (data.get('description', lst['description']) or '').strip()
    icon = (data.get('icon', lst['icon']) or '').strip()
    sort_order = data.get('sort_order', lst['sort_order'])

    execute(
        "UPDATE lists SET name = ?, description = ?, icon = ?, sort_order = ? WHERE id = ?",
        (name, description, icon, sort_order, list_id)
    )
    logger.info(f"Updated list id={list_id} -> name='{name}'")
    return success(list={
        'id': list_id, 'name': name, 'description': description,
        'icon': icon, 'sort_order': sort_order,
    })


@bp.route('/api/lists/<int:list_id>', methods=['DELETE'])
@login_required
@handle_api_errors
def api_delete_list(list_id):
    """Delete a list and all its game associations."""
    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT * FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return error(_('List not found'), 404)

    execute("DELETE FROM list_games WHERE list_id = ?", (list_id,))
    execute("DELETE FROM lists WHERE id = ?", (list_id,))
    logger.info(f"Deleted list '{lst['name']}' (id={list_id})")
    return success()


# =============================================================================
# LIST-GAMES API ROUTES
# =============================================================================

@bp.route('/api/lists/<int:list_id>/games', methods=['GET'])
@login_required
def api_get_list_games(list_id):
    """Get all games in a list."""
    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT id FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return error(_('List not found'), 404)

    games = query("""
        SELECT g.*, lg.position, lg.added_at AS list_added_at
        FROM list_games lg
        JOIN games g ON g.id = lg.game_id
        WHERE lg.list_id = ?
        ORDER BY lg.position, g.title COLLATE NOCASE
    """, (list_id,))
    return success(games=games)


@bp.route('/api/lists/<int:list_id>/games', methods=['POST'])
@login_required
@handle_api_errors
def api_add_game_to_list(list_id):
    """Add a game to a list."""
    data = request.get_json()
    if not data or not data.get('game_id'):
        return error(_('game_id is required'), 400)

    game_id = data['game_id']

    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT id FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return error(_('List not found'), 404)

    game = query("SELECT id, title FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    existing = query(
        "SELECT 1 FROM list_games WHERE list_id = ? AND game_id = ?",
        (list_id, game_id), one=True
    )
    if existing:
        return success(message='Game already in list')

    # Determine next position
    max_pos = query(
        "SELECT MAX(position) AS max_pos FROM list_games WHERE list_id = ?",
        (list_id,), one=True
    )
    next_pos = (max_pos['max_pos'] or 0) + 1 if max_pos else 1

    execute(
        "INSERT INTO list_games (list_id, game_id, position, added_at) VALUES (?, ?, ?, ?)",
        (list_id, game_id, next_pos, _utcnow_iso())
    )
    logger.info(f"Added game '{game['title']}' (id={game_id}) to list id={list_id}")
    return success(), 201


@bp.route('/api/lists/<int:list_id>/games/<int:game_id>', methods=['DELETE'])
@login_required
@handle_api_errors
def api_remove_game_from_list(list_id, game_id):
    """Remove a game from a list."""
    owner_sql, owner_params = _owner_clause()
    lst = query(
        f"SELECT id FROM lists WHERE id = ? AND {owner_sql}",
        (list_id, *owner_params), one=True,
    )
    if not lst:
        return error(_('List not found'), 404)

    existing = query(
        "SELECT 1 FROM list_games WHERE list_id = ? AND game_id = ?",
        (list_id, game_id), one=True
    )
    if not existing:
        return error(_('Game is not in this list'), 404)

    execute("DELETE FROM list_games WHERE list_id = ? AND game_id = ?", (list_id, game_id))
    logger.info(f"Removed game id={game_id} from list id={list_id}")
    return success()


# =============================================================================
# WISHLIST API ROUTES
# =============================================================================

@bp.route('/api/wishlist', methods=['GET'])
@login_required
def api_get_wishlist():
    """Get all wishlist items."""
    owner_sql, owner_params = _owner_clause('w')
    items = query(f"""
        SELECT w.*,
               g.title AS linked_game_title,
               gs.name AS linked_system,
               ws.name AS wishlist_system_name
        FROM wishlist w
        LEFT JOIN games g ON g.id = w.game_id
        LEFT JOIN systems gs ON g.system_id = gs.id
        LEFT JOIN systems ws ON ws.id = w.system_id
        WHERE {owner_sql}
        ORDER BY w.priority ASC, w.added_at DESC
    """, owner_params)
    return success(items=items)


@bp.route('/api/wishlist', methods=['POST'])
@login_required
@handle_api_errors
def api_add_to_wishlist():
    """Add an item to the wishlist.

    Optional `system_id` links to a known systems row for stronger scraper
    matching; `system_name` is kept as free text so users can wishlist games
    for systems RetroDB doesn't yet know about (e.g. an upcoming Sony
    PlayStation 6 title). Optional `scrape=true` fires off a background
    scrape immediately after inserting.
    """
    data = request.get_json()
    if not data or not data.get('title', '').strip():
        return error(_('Title is required'), 400)

    title = data['title'].strip()
    system_name = data.get('system_name', '').strip()
    system_id = data.get('system_id')
    notes = data.get('notes', '').strip()
    priority = data.get('priority', 2)
    game_id = data.get('game_id')
    scrape_now = bool(data.get('scrape'))

    # Validate priority range
    if not isinstance(priority, int) or priority < 1 or priority > 5:
        return error(_('Priority must be an integer between 1 and 5'), 400)

    # Validate system_id (if provided) resolves to a real system
    if system_id is not None:
        if not isinstance(system_id, int):
            return error(_('system_id must be an integer'), 400)
        sys_row = query("SELECT id, name FROM systems WHERE id = ?", (system_id,), one=True)
        if not sys_row:
            return error(_('Unknown system_id'), 400)
        # If caller didn't send a system_name, use the canonical one
        if not system_name:
            system_name = sys_row['name']

    # Duplicate check is per-owner: two users may both wishlist the same game.
    existing = query(
        "SELECT id FROM wishlist WHERE title = ? COLLATE NOCASE AND owner_id = ?",
        (title, g.user['id']), one=True,
    )
    if existing:
        return error(_('This game is already on your wishlist'), 409)

    item_id = execute(
        """INSERT INTO wishlist
           (title, system_name, system_id, notes, priority, added_at, game_id,
            scrape_status, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, system_name, system_id, notes, priority, _utcnow_iso(), game_id,
         'unscraped', g.user['id'])
    )
    logger.info(f"Added '{title}' to wishlist (id={item_id}, system_id={system_id}, scrape={scrape_now}, owner={g.user['id']})")

    if scrape_now:
        from services.wishlist_scraper import scrape_wishlist_item_async
        scrape_wishlist_item_async(item_id)

    return success(item={
        'id': item_id, 'title': title, 'system_name': system_name,
        'system_id': system_id, 'notes': notes, 'priority': priority,
        'game_id': game_id, 'scrape_status': 'scraping' if scrape_now else 'unscraped',
    }), 201


@bp.route('/api/wishlist/<int:item_id>', methods=['PUT'])
@login_required
@handle_api_errors
def api_update_wishlist_item(item_id):
    """Update a wishlist item."""
    data = request.get_json()
    if not data:
        return error(_('No data provided'), 400)

    owner_sql, owner_params = _owner_clause()
    item = query(
        f"SELECT * FROM wishlist WHERE id = ? AND {owner_sql}",
        (item_id, *owner_params), one=True,
    )
    if not item:
        return error(_('Wishlist item not found'), 404)

    title = (data.get('title', item['title']) or '').strip()
    system_name = (data.get('system_name', item['system_name']) or '').strip()
    system_id = data.get('system_id', item['system_id']) if 'system_id' in data else item['system_id']
    notes = (data.get('notes', item['notes']) or '').strip()
    priority = data.get('priority', item['priority'])
    game_id = data.get('game_id', item['game_id'])

    if not isinstance(priority, int) or priority < 1 or priority > 5:
        return error(_('Priority must be an integer between 1 and 5'), 400)

    # Validate system_id if it was supplied (either in this request or previously stored)
    if system_id is not None:
        if not isinstance(system_id, int):
            return error(_('system_id must be an integer'), 400)
        sys_row = query("SELECT id FROM systems WHERE id = ?", (system_id,), one=True)
        if not sys_row:
            return error(_('Unknown system_id'), 400)

    execute(
        """UPDATE wishlist SET title = ?, system_name = ?, system_id = ?,
                               notes = ?, priority = ?, game_id = ?
           WHERE id = ?""",
        (title, system_name, system_id, notes, priority, game_id, item_id)
    )
    logger.info(f"Updated wishlist item id={item_id} -> title='{title}'")
    return success(item={
        'id': item_id, 'title': title, 'system_name': system_name,
        'system_id': system_id, 'notes': notes, 'priority': priority,
        'game_id': game_id,
    })


@bp.route('/api/wishlist/<int:item_id>', methods=['DELETE'])
@login_required
@handle_api_errors
def api_delete_wishlist_item(item_id):
    """Delete a wishlist item."""
    owner_sql, owner_params = _owner_clause()
    item = query(
        f"SELECT * FROM wishlist WHERE id = ? AND {owner_sql}",
        (item_id, *owner_params), one=True,
    )
    if not item:
        return error(_('Wishlist item not found'), 404)

    execute("DELETE FROM wishlist WHERE id = ?", (item_id,))
    logger.info(f"Deleted wishlist item '{item['title']}' (id={item_id})")
    return success()


@bp.route('/api/wishlist/<int:item_id>/scrape', methods=['POST'])
@login_required
@handle_api_errors
def api_scrape_wishlist_item(item_id):
    """Kick off a background scrape for a single wishlist item.

    Returns immediately; the UI polls /api/wishlist to see scrape_status
    flip from 'scraping' → 'scraped' | 'failed' | 'no_match'.
    """
    owner_sql, owner_params = _owner_clause()
    item = query(
        f"SELECT id FROM wishlist WHERE id = ? AND {owner_sql}",
        (item_id, *owner_params), one=True,
    )
    if not item:
        return error(_('Wishlist item not found'), 404)

    from services.wishlist_scraper import scrape_wishlist_item_async
    scrape_wishlist_item_async(item_id)
    return success(status='scraping')


@bp.route('/api/wishlist/scrape-all', methods=['POST'])
@login_required
@handle_api_errors
def api_scrape_all_wishlist():
    """Background-scrape every wishlist item with scrape_status NULL /
    'unscraped' / 'failed' / 'no_match'. Already-scraped items are left
    alone; the per-item re-scrape endpoint is what rescrapes those.

    Scope: current user's wishlist (admins scrape every user's items).
    """
    owner_sql, owner_params = _owner_clause()
    unscraped_count = query(f"""
        SELECT COUNT(*) AS c FROM wishlist
        WHERE (scrape_status IS NULL
               OR scrape_status IN ('unscraped', 'failed', 'no_match'))
          AND {owner_sql}
    """, owner_params, one=True)['c']

    if unscraped_count == 0:
        return success(scheduled=0, message='Nothing to scrape')

    from services.wishlist_scraper import scrape_unscraped_items_async
    # Admins re-scrape everyone's wishlist; everyone else re-scrapes their own.
    scrape_unscraped_items_async(
        owner_id=None if g.user['role'] == 'admin' else g.user['id']
    )
    return success(scheduled=unscraped_count)
