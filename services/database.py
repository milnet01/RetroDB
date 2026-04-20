# =============================================================================
# RETRODB - Database Service
# =============================================================================
# Provides database connection management and query helpers.
# All database operations should use these functions for consistency.
# =============================================================================

import sqlite3
import config
from flask import g, has_app_context


def safe_column(name, allowed):
    """
    Validate a column/order-by/field name against an allowlist before
    interpolating into an SQL string.

    Use this any time a request-derived value needs to end up inside a raw
    SQL fragment — column lists, ORDER BY, dynamic WHERE field references.
    Prevents both injection and typo-induced silent mismatches.

    Args:
        name: The untrusted string (e.g. request.args.get('sort')).
        allowed: An iterable of permitted values.

    Returns:
        The validated string, guaranteed to be equal to one of `allowed`.

    Raises:
        ValueError: If `name` is not in `allowed`.

    Example:
        column = safe_column(request.args.get('sort'), {'title', 'year', 'rating'})
        sql = f"SELECT * FROM games ORDER BY {column}"
    """
    if name not in allowed:
        raise ValueError(f"Invalid column name: {name!r}")
    return name


def get_db():
    """
    Get a database connection.
    
    Returns a sqlite3 connection with Row factory enabled for dict-like access.
    The caller is responsible for closing the connection.
    
    Returns:
        sqlite3.Connection: Database connection object
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    conn.execute("PRAGMA journal_size_limit = 67108864")
    return conn


def get_request_db():
    """
    Get a request-scoped database connection.

    Within a Flask request context, reuses the same connection (stored on flask.g)
    so that multiple queries in one request share a single connection + PRAGMAs.
    Outside a request context (e.g. background jobs), falls back to get_db().

    The connection is automatically closed by the teardown_appcontext handler
    registered in app.py.

    Returns:
        sqlite3.Connection: Database connection object
    """
    if not has_app_context():
        return get_db()
    if 'db' not in g:
        g.db = get_db()
    return g.db


def query(sql, args=(), one=False):
    """
    Execute a SELECT query and return results as dictionaries.
    
    This is the primary way to read data from the database. Results are
    automatically converted to dicts so .get() method works properly.
    
    Args:
        sql: SQL query string with ? placeholders
        args: Tuple of arguments to substitute into query
        one: If True, return only the first result (or None)
    
    Returns:
        If one=False: List of dicts representing rows
        If one=True: Single dict or None if no results
    
    Examples:
        # Get all games
        games = query("SELECT * FROM games")
        
        # Get single game by ID
        game = query("SELECT * FROM games WHERE id = ?", (game_id,), one=True)
        
        # Get games with parameters
        games = query("SELECT * FROM games WHERE system_id = ? AND title LIKE ?", 
                     (system_id, f"%{search}%"))
    """
    conn = get_request_db()
    cur = conn.execute(sql, args)
    rows = cur.fetchall()

    # Convert sqlite3.Row objects to dicts so .get() works
    if one:
        return dict(rows[0]) if rows else None
    return [dict(row) for row in rows]


def execute(sql, args=()):
    """
    Execute a SQL statement (INSERT, UPDATE, DELETE).
    
    This handles connection management and commits automatically.
    
    Args:
        sql: SQL statement string with ? placeholders
        args: Tuple of arguments to substitute into statement
    
    Returns:
        int: The lastrowid from the cursor (useful for INSERT statements)
    
    Examples:
        # Insert a new game
        game_id = execute(
            "INSERT INTO games (title, system_id) VALUES (?, ?)",
            (title, system_id)
        )
        
        # Update a game
        execute(
            "UPDATE games SET title = ? WHERE id = ?",
            (new_title, game_id)
        )
        
        # Delete a game
        execute("DELETE FROM games WHERE id = ?", (game_id,))
    """
    conn = get_request_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def execute_many(sql, args_list):
    """
    Execute a SQL statement multiple times with different arguments.
    
    More efficient than calling execute() in a loop when inserting
    or updating many rows.
    
    Args:
        sql: SQL statement string with ? placeholders
        args_list: List of tuples, each containing arguments for one execution
    
    Returns:
        int: Number of rows affected
    
    Example:
        # Insert multiple games
        games_data = [
            ('Game 1', 1),
            ('Game 2', 1),
            ('Game 3', 2),
        ]
        count = execute_many(
            "INSERT INTO games (title, system_id) VALUES (?, ?)",
            games_data
        )
    """
    conn = get_request_db()
    cur = conn.executemany(sql, args_list)
    conn.commit()
    return cur.rowcount


def execute_script(sql_script):
    """
    Execute multiple SQL statements from a script.
    
    Useful for running migrations or initialization scripts.
    
    Args:
        sql_script: String containing multiple SQL statements separated by semicolons
    
    Example:
        execute_script('''
            CREATE TABLE IF NOT EXISTS new_table (id INTEGER PRIMARY KEY);
            CREATE INDEX IF NOT EXISTS idx_new ON new_table(id);
        ''')
    """
    conn = get_request_db()
    conn.executescript(sql_script)
    conn.commit()


def get_db_with_context():
    """
    Get a database connection as a context manager.
    
    Use this when you need to perform multiple operations in a single
    transaction or need more control over the connection lifecycle.
    
    Usage:
        with get_db_with_context() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO games (title) VALUES (?)", (title,))
            game_id = cursor.lastrowid
            cursor.execute("INSERT INTO game_metadata (game_id) VALUES (?)", (game_id,))
            conn.commit()
    
    Returns:
        sqlite3.Connection: Database connection (auto-closes on exit)
    """
    class DBContextManager:
        def __init__(self):
            self.conn = None
        
        def __enter__(self):
            self.conn = get_db()
            return self.conn
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.conn:
                if exc_type is None:
                    self.conn.commit()
                self.conn.close()
            return False  # Don't suppress exceptions
    
    return DBContextManager()
