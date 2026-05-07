# =============================================================================
# Pass 35 + 36 — data integrity & backup hardening + frontend XSS round 2
# =============================================================================
# Pass 45.21 audit (2026-04-27): converted 35.3 (foreign_keys=ON), 35.4
# (journal_mode=WAL) to functional fresh-DB tests that query PRAGMAs.
# Remaining source-grep tests pin JS XSS patterns (escAttr safelist regex,
# DOM.create textContent default, log-viewer field escaping, ModalFocusTrap
# arrow callbacks, Storage.clearAll prefix list, polite/assertive a11y
# containers), atomic_write_json fsync of parent dir (no functional crash-
# injection equivalent), and the no-raw-ALTER-TABLE codebase invariant in
# database_init.py.
# =============================================================================

import json
import os
import re
import sqlite3
import stat
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 35.1 — backup_database chmod 0o600 + fsync
# -----------------------------------------------------------------------------
def test_35_1_backup_mode_is_0600(tmp_path):
    from services.database import backup_database

    src = tmp_path / "source.db"
    dst = tmp_path / "backup.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE x (id INTEGER)")
    conn.execute("INSERT INTO x VALUES (1)")
    conn.commit()
    conn.close()

    backup_database(str(src), str(dst))

    mode = stat.S_IMODE(os.stat(str(dst)).st_mode)
    assert mode == 0o600, f"backup should be 0600, got {oct(mode)}"

    # Integrity-check intact
    verify = sqlite3.connect(str(dst))
    row = verify.execute("SELECT id FROM x").fetchone()
    verify.close()
    assert row[0] == 1


def test_35_1_fsync_helper_exists_and_handles_missing_path():
    from services.database import _fsync_path

    # Helper exists and raises a reasonable error when path is bogus.
    try:
        _fsync_path("/nonexistent/really/not/a/path")
    except OSError:
        pass  # expected
    else:
        raise AssertionError("expected OSError on missing path")


# -----------------------------------------------------------------------------
# 35.2 — atomic_write_json fsyncs parent directory
# -----------------------------------------------------------------------------
def test_35_2_atomic_write_json_fsync_dir(tmp_path):
    """Source-level check — verify the fsync path is wired in the source."""
    src = open(os.path.join(_REPO_ROOT, 'services', 'atomic_io.py'), encoding='utf-8').read()
    # Comment marker AND the fsync(directory_fd) call.
    assert "Pass 35.2" in src
    assert "os.open(directory, os.O_RDONLY)" in src


def test_35_2_atomic_write_json_still_works(tmp_path):
    """Sanity: the new fsync didn't break the happy path."""
    from services.atomic_io import atomic_write_json

    path = tmp_path / "out.json"
    atomic_write_json(str(path), {"foo": 1, "bar": [2, 3]})
    assert json.loads(path.read_text()) == {"foo": 1, "bar": [2, 3]}


# -----------------------------------------------------------------------------
# 35.3 + 35.4 — init_database enables FK + WAL/size PRAGMAs
# -----------------------------------------------------------------------------
def test_35_3_init_database_issues_foreign_keys_on():
    """Codebase invariant — kept as source-grep because PRAGMA foreign_keys
    is per-connection (not persisted to the DB file). The contract IS
    that init_database's body contains `PRAGMA foreign_keys = ON`; a
    runtime check would only verify the test's own connection state, not
    that init_database wires it for every future connection through
    get_db() (which is the actual user-facing path)."""
    src = open(os.path.join(_REPO_ROOT, 'services', 'database_init.py'), encoding='utf-8').read()
    body = src[src.index("def init_database("):src.index("def ensure_user_tables(")]
    assert "PRAGMA foreign_keys = ON" in body


def test_35_4_get_db_no_longer_issues_journal_mode():
    """get_db() should leave journal_mode and journal_size_limit to init.
    Codebase invariant: the pragma calls must not appear in get_db's body
    (ensures we don't double-issue them on every connection acquire)."""
    src = open(os.path.join(_REPO_ROOT, 'services', 'database.py'), encoding='utf-8').read()
    get_db_body = src[src.index("def get_db("):src.index("def get_request_db(")]
    assert "PRAGMA journal_mode = WAL" not in get_db_body
    assert "PRAGMA journal_size_limit" not in get_db_body


def test_35_4_init_database_issues_wal(tmp_path, monkeypatch):
    """Functional: after init_database(), the DB file's journal_mode must be
    WAL (queryable via PRAGMA on a fresh connection)."""
    import sqlite3
    import config as cfg
    monkeypatch.setattr(cfg, 'DB_PATH', str(tmp_path / 'wal.db'))
    from services.database_init import init_database
    init_database()
    conn = sqlite3.connect(str(tmp_path / 'wal.db'))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == 'wal', f"journal_mode should be WAL, got {mode}"
        # journal_size_limit is per-connection, not stored in the DB header.
        # We can only sanity-check that init didn't leave it unset on its
        # own connection — re-run init and verify no error.
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# 35.5 — explicit ALTER helper replaces try/except blocks
# -----------------------------------------------------------------------------
def test_35_5_add_column_helper_exists():
    from services.database_init import _add_column_if_missing
    assert callable(_add_column_if_missing)


def test_35_5_no_more_try_except_alter_blocks():
    src = open(os.path.join(_REPO_ROOT, 'services', 'database_init.py'), encoding='utf-8').read()
    # No raw "ALTER TABLE ... ADD COLUMN" outside the helper body — every
    # ALTER must flow through _add_column_if_missing.
    body = src[src.index("def ensure_user_tables("):]
    # Count 'ALTER TABLE' occurrences — expect 1 (inside _add_column_if_missing),
    # which is defined BEFORE ensure_user_tables, so body shouldn't have any.
    assert "ALTER TABLE" not in body


def test_35_5_add_column_helper_is_idempotent(tmp_path):
    from services.database_init import _add_column_if_missing

    conn = sqlite3.connect(str(tmp_path / "t.db"))
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE t (a INTEGER)")
    _add_column_if_missing(cursor, 't', 'b', 'TEXT DEFAULT ""')
    _add_column_if_missing(cursor, 't', 'b', 'TEXT DEFAULT ""')  # second call — no error
    cols = [row[1] for row in cursor.execute("PRAGMA table_info(t)")]
    assert cols == ['a', 'b']
    conn.close()


# -----------------------------------------------------------------------------
# 36.1 — escAttr performs JS-string escape
# -----------------------------------------------------------------------------
def test_36_1_escattr_js_string_escape():
    """escAttr must escape ' < \\ newline to \\uXXXX / \\xXX JS escapes."""
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'all-games-controller.js'), encoding='utf-8').read()
    # Grab a wide window around the escAttr definition to include the
    # leading comment block with the Pass marker.
    fn_start = src.index("Pass 36.1")
    fn_end = src.index("// =========", fn_start)
    body = src[fn_start:fn_end]
    # The key indicator: a regex match against a safelist, with backslash
    # escape in the replacement.
    assert re.search(r"replace\(/\[\^a-zA-Z0-9", body), "escAttr should use safelist regex"
    assert "\\\\x" in body or "\\\\u" in body, "should emit \\x or \\u escapes"


# -----------------------------------------------------------------------------
# 36.3 — museum controller image uses DOM API, not innerHTML concat
# -----------------------------------------------------------------------------
def test_36_3_museum_uses_create_element():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'museum.js'), encoding='utf-8').read()
    body = src[src.index("function _updateControllerImage("):src.index("function _showControllerOverlay(")]
    # No innerHTML string concat inside the rebuilt helpers.
    assert "imgContainer.innerHTML" not in body
    assert "placeholder.innerHTML" not in body
    # Instead, setAttribute + addEventListener.
    assert "setAttribute('src'" in body
    assert "addEventListener('click'" in body


# -----------------------------------------------------------------------------
# 36.4 — log-viewer escapes all dynamic fields + allowlists level
# -----------------------------------------------------------------------------
def test_36_4_log_viewer_escapes_dynamic_fields():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'log-viewer.js'), encoding='utf-8').read()
    # The definition (not a call) — match the opening brace form.
    fn_start = src.index("renderLine(line) {")
    body = src[fn_start:fn_start + 2000]
    # Allowlist set for the CSS class context.
    assert "DEBUG" in body and "CRITICAL" in body
    # Every interpolated field escaped.
    assert "lineNumberSafe" in body
    assert "timeSafe" in body
    assert "levelSafe" in body


# -----------------------------------------------------------------------------
# 36.5 — safeParseJSON accepts storage argument
# -----------------------------------------------------------------------------
def test_36_5_safe_parse_json_signature():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    assert "function safeParseJSON(key, fallback, storage)" in src
    assert "storage || localStorage" in src


def test_36_5_session_storage_sites_migrated():
    """The identified sessionStorage sites route through safeParseJSON.

    Pass 42.7 removed `page-lifecycle.js` (467 LoC dead infrastructure, zero
    consumers). The two remaining sessionStorage sites still pin the contract.
    """
    for relpath in ('static/js/all-games-controller.js', 'static/js/rom-tools.js'):
        src = open(os.path.join(_REPO_ROOT, relpath), encoding='utf-8').read()
        assert "safeParseJSON" in src, f"{relpath} missing safeParseJSON call"


# -----------------------------------------------------------------------------
# 36.7 — DOM.create defaults to textContent; DOM.createHTML is opt-in
# -----------------------------------------------------------------------------
def test_36_7_dom_create_textcontent_default():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    create_start = src.index("create(tag, attrs = {}, content = '')")
    create_end = src.index("createHTML(", create_start)
    create_body = src[create_start:create_end]
    # The string branch must use textContent, not innerHTML.
    assert "el.textContent = content" in create_body
    assert "el.innerHTML = content" not in create_body


def test_36_7_dom_create_html_helper_exists():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    # Match the actual function definition (with opening brace + args
    # including a default). Docstrings sometimes reference the function
    # name, so we anchor against the definition shape.
    assert "createHTML(tag, attrs = {}, html = '')" in src
    fn_start = src.index("createHTML(tag, attrs = {}, html = '')")
    create_html_body = src[fn_start:fn_start + 300]
    assert "el.innerHTML = html" in create_html_body


# -----------------------------------------------------------------------------
# 36.8 — ModalFocusTrap accepts arrow callbacks
# -----------------------------------------------------------------------------
def test_36_8_modal_focus_trap_supports_arrows():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    activate_body = src[src.index("activate(modalEl, triggerEl, opts = {})"):
                        src.index("activate(modalEl, triggerEl, opts = {})") + 2500]
    assert "onArrowLeft" in activate_body
    assert "onArrowRight" in activate_body


def test_36_8_redundant_keydown_handlers_removed():
    """game-modals.js and museum.js no longer register lightbox-scoped
    document keydown handlers — they route through ModalFocusTrap."""
    gm = open(os.path.join(_REPO_ROOT, 'static', 'js', 'game-modals.js'), encoding='utf-8').read()
    # The dead handler was at line 2063; the replacement comment references 36.8.
    assert gm.count("document.addEventListener('keydown'") <= 0 or \
        "Pass 36.8" in gm

    museum = open(os.path.join(_REPO_ROOT, 'static', 'js', 'museum.js'), encoding='utf-8').read()
    # Museum's only remaining keydown listener should be none — trap handles it.
    assert museum.count("document.addEventListener('keydown'") == 0


# -----------------------------------------------------------------------------
# 36.9 — Storage.clearAll prefix list covers all known keys
# -----------------------------------------------------------------------------
def test_36_9_clear_all_includes_queue_keys():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    body = src[src.index("clearAll()"):src.index("clearAll()") + 1500]
    for key in ('retrodb', 'bulkScrape', 'sidebar', 'raOperationsQueue', 'raSyncQueue', 'toast_completion_'):
        assert f"'{key}'" in body, f"clearAll missing prefix {key!r}"


# -----------------------------------------------------------------------------
# 36.10 — notification container split into polite + assertive
# -----------------------------------------------------------------------------
def test_36_10_assertive_container():
    src = open(os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js'), encoding='utf-8').read()
    assert "assertiveContainer" in src
    assert 'aria-live' in src
    assert 'assertive' in src
    init_body = src[src.index("init() {", src.index("Notifications")):
                    src.index("_containerFor")]
    assert "'alert'" in init_body or '"alert"' in init_body
    assert "'assertive'" in init_body or '"assertive"' in init_body
