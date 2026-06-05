# =============================================================================
# RETRODB - Database Service
# =============================================================================
# Provides database connection management and query helpers.
# All database operations should use these functions for consistency.
# =============================================================================

import logging
import os
import re
import sqlite3
import time

import config
from flask import g, has_app_context

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r'\s+')


def _log_if_slow(sql, args, start):
    """Log a WARNING if (now - start) exceeds config.SLOW_QUERY_MS.

    Args:
        sql: The SQL string that was executed.
        args: The parameter sequence (used only for arg-count logging —
            values themselves stay out of the log to avoid PII leaks).
        start: perf_counter() timestamp captured before execute.
    """
    threshold = getattr(config, 'SLOW_QUERY_MS', 0) or 0
    if threshold <= 0:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if elapsed_ms < threshold:
        return
    compact_sql = _WHITESPACE_RE.sub(' ', sql).strip()
    if len(compact_sql) > 500:
        compact_sql = compact_sql[:497] + '...'
    try:
        arg_count = len(args) if args is not None else 0
    except TypeError:
        arg_count = -1
    logger.warning(
        "slow_query elapsed_ms=%.1f args=%d sql=%s",
        elapsed_ms, arg_count, compact_sql,
    )


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
    # Pass 35.4 — journal_mode=WAL and journal_size_limit are DB-file-level
    # settings (stored in the SQLite header). They're applied once at init
    # by init_database(); re-issuing them per connection wastes a parse
    # round-trip. Keep the six connection-scoped PRAGMAs below.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
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
    _t0 = time.perf_counter()
    cur = conn.execute(sql, args)
    rows = cur.fetchall()
    _log_if_slow(sql, args, _t0)

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
    _t0 = time.perf_counter()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
    except Exception:
        # The connection is request-scoped (shared on flask.g) and reused for
        # every query in the request. Roll back the failed statement's implicit
        # transaction so a later same-request execute() can't commit half-open
        # state left behind by this failure. Guard the rollback so its own
        # failure can't mask the original exception (callers catch e.g.
        # sqlite3.IntegrityError on the bare `raise`).
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _log_if_slow(sql, args, _t0)
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
    _t0 = time.perf_counter()
    try:
        cur = conn.executemany(sql, args_list)
        conn.commit()
    except Exception:
        # See execute(): roll back so a failed batch can't leave the shared
        # request connection in a half-open transaction (rollback guarded so it
        # can't mask the original exception).
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _log_if_slow(sql, args_list, _t0)
    return cur.rowcount


def execute_script(sql_script):
    """
    Execute multiple SQL statements from a script.

    Useful for running migrations or initialization scripts.

    NOT ATOMIC: SQLite's ``executescript`` COMMITs any pending transaction
    before it runs and auto-commits as it goes, so a failure midway leaves the
    already-executed statements committed — the except-branch rollback below
    cannot undo them. Make each script idempotent (``IF NOT EXISTS`` etc.) and
    don't rely on all-or-nothing semantics (Pass 48.5).

    Args:
        sql_script: String containing multiple SQL statements separated by semicolons
    
    Example:
        execute_script('''
            CREATE TABLE IF NOT EXISTS new_table (id INTEGER PRIMARY KEY);
            CREATE INDEX IF NOT EXISTS idx_new ON new_table(id);
        ''')
    """
    conn = get_request_db()
    try:
        conn.executescript(sql_script)
        conn.commit()
    except Exception:
        # executescript implicitly commits pending work first, then runs the
        # statements; on a mid-script failure roll back so the shared request
        # connection isn't left in a half-open transaction (matches execute()).
        # Note: this can't undo statements executescript already auto-committed
        # before the failure — see roadmap Pass 48.5. Rollback guarded so it
        # can't mask the original exception.
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def _fsync_path(path):
    """Open `path` read-only and fsync its file descriptor.

    Works for both regular files and directories — on POSIX, fsyncing a
    directory flushes the directory's own metadata (i.e. the rename/create
    entries under it) so a crash after `os.replace` can't lose the new name.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup_database(src_path, dst_path):
    """
    Create a consistent snapshot of a SQLite database using the online
    backup API. Coordinates with WAL mode and concurrent writers, unlike
    `shutil.copy2` which can produce a torn file. Verifies the result with
    `PRAGMA integrity_check` and removes the destination file if the check
    fails, so callers never receive a corrupt backup.

    Args:
        src_path: Path to the live SQLite database file.
        dst_path: Path where the backup will be written.

    Raises:
        RuntimeError: if the backup fails its post-write integrity check.
        sqlite3.Error: on any underlying SQLite failure.
    """
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    # Pass 45.5 — chmod *before* the integrity-check open so the backup
    # never exists at the umask default while it holds session cookies,
    # password hashes, and OAuth tokens. The previous order was
    # backup → verify-open → chmod, which left a 0o644 window for the
    # entire duration of PRAGMA integrity_check.
    try:
        os.chmod(dst_path, 0o600)
    except OSError as e:
        # Pass 48.5 — don't swallow silently: a failed chmod leaves the backup
        # at the umask default (potentially 0o644) while it holds session
        # cookies, password hashes and OAuth tokens. Surface it so the operator
        # can tighten permissions (e.g. on a filesystem that ignores chmod).
        logger.warning(f"Could not chmod backup {dst_path} to 0o600: {e}")

    verify = sqlite3.connect(dst_path)
    try:
        # Pass 45.10 — match the migration runner's busy_timeout. A
        # backup-verify connection competing with a peer reader on the
        # same file would otherwise fail-fast under SQLite's default
        # zero timeout.
        verify.execute("PRAGMA busy_timeout = 5000")
        result = verify.execute("PRAGMA integrity_check").fetchone()
    finally:
        verify.close()

    if not result or result[0] != 'ok':
        try:
            os.remove(dst_path)
        except OSError:
            pass
        raise RuntimeError(f"backup failed integrity check: {result[0] if result else 'no result'}")

    # Pass 35.1 — fsync both the file and its parent directory so a power
    # loss can't leave a directory entry pointing at empty contents.
    try:
        _fsync_path(dst_path)
        _fsync_path(os.path.dirname(dst_path) or '.')
    except OSError:
        # fsync can fail on some network filesystems — not worth aborting
        # an otherwise-verified backup over.
        pass


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
            # Pass 48.4 — explicit rollback on the error path (legibility, rather
            # than relying on close()'s implicit rollback) and close() in finally
            # so a commit that itself raises can't leak the connection.
            if self.conn:
                try:
                    if exc_type is None:
                        self.conn.commit()
                    else:
                        self.conn.rollback()
                finally:
                    self.conn.close()
            return False  # Don't suppress exceptions
    
    return DBContextManager()
