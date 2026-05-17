# =============================================================================
# v3.6.5 — Scan Library reads rom_path at runtime, errors loudly when unset
# =============================================================================
# Regression pins for the bug shape diagnosed on 2026-05-17:
#
#   - `scraper/scan_roms.py` did `from config import ROM_PATH` at module top,
#     binding the variable to the hardcoded default `""` (config.py:41) before
#     `data/settings.json` was loaded. `config.ROM_PATH` is *never mutated* at
#     runtime — only `app.config['ROM_PATH']` gets the resolved value via
#     `settings_manager.get_effective_path('rom_path', ...)`. So clicking
#     Dashboard → Scan Library called `scan_roms()`, which read its own stale
#     `ROM_PATH = ""`, then returned 0 silently. The user saw a green "Library
#     scan complete! Found 0 new games." toast instead of a misconfig error.
#
#   - `services/rom_scanner.py:74` (the inline fallback used when the scraper
#     package can't be imported) had the same bug.
#
# These tests pin:
#   1. The scanner resolves rom_path at call time via
#      `settings_manager.get_effective_path`, not at import time.
#   2. An empty rom_path raises `RomPathNotConfigured` instead of returning 0.
#   3. /api/scan converts that exception into a 4xx JSON response with a
#      remediation message ("ROM path not configured. Go to Settings → Paths
#      to set it.") — distinguishable from a legit empty-scan result.
# =============================================================================

from __future__ import annotations

import pytest

# `_util` performs the sys.path insert + REPO_ROOT computation centrally so the
# repo-root modules this file imports (scraper.scan_roms, services.rom_scanner)
# resolve. `read_source` replaces the open()-and-read source-grep boilerplate.
from tests._util import read_source


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _seed_rom_root(tmp_path, *, system='xbox', filename='Halo (USA).iso'):
    """Build an ES-DE-style ROM root with one system folder + a stub ROM."""
    rom_root = tmp_path / 'roms'
    rom_root.mkdir()
    system_dir = rom_root / system
    system_dir.mkdir()
    (system_dir / 'systeminfo.txt').write_text(
        'System name:\n'
        f'{system}\n'
        '\n'
        'Full system name:\n'
        'Microsoft Xbox\n'
        '\n'
        'Supported file extensions:\n'
        '.iso .ISO\n'
    )
    (system_dir / filename).write_bytes(b'')
    return rom_root


# -----------------------------------------------------------------------------
# Shared fake DB layer (test-audit c-007 MED-2)
# -----------------------------------------------------------------------------
# Used by both `_stub_db` (`scraper.scan_roms` — get_scraper_conn) and
# `_stub_db_context` (`services.rom_scanner` — get_db_with_context). Keeping
# one definition prevents drift between the two scanners' fakes.

class _FakeCursor:
    """In-memory cursor that pattern-matches the three SQL shapes the
    scanner issues: lookup system → row=(1,), lookup existing game →
    row=None, insert new game → append params to the shared list."""

    def __init__(self, inserted):
        self._inserted = inserted
        self._row = None

    def execute(self, sql, params=()):
        sql_norm = ' '.join(sql.split())
        if sql_norm.startswith('SELECT id FROM systems'):
            self._row = (1,)
        elif sql_norm.startswith('SELECT id FROM games'):
            # No existing game with this rom_path → return None so the
            # scanner inserts.
            self._row = None
        elif sql_norm.startswith('INSERT INTO games'):
            self._inserted.append(params)
            self._row = None
        else:
            self._row = None
        return self

    def fetchone(self):
        return self._row


class _FakeConn:
    """Reuses a single _FakeCursor across calls so callers can observe its
    last-fetched row. Matches the production sqlite3.Connection contract
    (one cursor per logical scan loop)."""

    def __init__(self, inserted):
        self._cursor = _FakeCursor(inserted)

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


def _stub_db(monkeypatch, scan_mod):
    """Replace `scraper.scan_roms.get_scraper_conn` with a fake. Returns the
    `inserted` list so callers can assert on captured INSERT params.

    Raises AttributeError loudly if `get_scraper_conn` has been removed from
    the module — surfaces a test-config mismatch instead of silently passing
    (test-audit c-007 LOW-2)."""
    inserted = []
    monkeypatch.setattr(scan_mod, 'get_scraper_conn', lambda: _FakeConn(inserted))
    return inserted


def _stub_db_context(monkeypatch, scan_mod):
    """Replace `services.rom_scanner.get_db_with_context` with a context-
    manager-wrapped fake. Returns the `inserted` list."""
    from contextlib import contextmanager

    inserted = []
    conn = _FakeConn(inserted)

    @contextmanager
    def _fake_ctx():
        yield conn

    monkeypatch.setattr(scan_mod, 'get_db_with_context', _fake_ctx)
    return inserted


# -----------------------------------------------------------------------------
# 1 — Source-level pin: no module-level `from config import ROM_PATH`
# -----------------------------------------------------------------------------

class TestScanRomsImportTimeBinding:
    """`scraper/scan_roms.py` MUST NOT import `ROM_PATH` at module level —
    that snapshots the empty default before settings are loaded.  Use a
    runtime resolver (`settings_manager.get_effective_path`) inside the
    function body instead."""

    def test_scan_roms_does_not_bind_rom_path_at_import(self):
        src = read_source('scraper/scan_roms.py')
        assert 'from config import ROM_PATH' not in src, (
            'scraper/scan_roms.py must NOT bind ROM_PATH at import time — '
            'config.ROM_PATH is the hardcoded `""` default and is never '
            'mutated at runtime. Resolve via settings_manager inside '
            'scan_roms() instead. (v3.6.5)'
        )

    def test_rom_scanner_does_not_read_config_rom_path_directly(self):
        """The inline fallback in services/rom_scanner.py had the same bug:
        `rom_path = config.ROM_PATH` reads the hardcoded `""` default."""
        src = read_source('services/rom_scanner.py')
        assert 'rom_path = config.ROM_PATH' not in src, (
            'services/rom_scanner.py must resolve rom_path via '
            'settings_manager.get_effective_path, not by reading the '
            'config.ROM_PATH hardcoded default. (v3.6.5)'
        )


# -----------------------------------------------------------------------------
# 2 — Behavioural pin: scanner reads from settings_manager at call time
# -----------------------------------------------------------------------------

class TestScanRomsRuntimeResolution:
    """`scan_roms()` must call `settings_manager.get_effective_path` each
    time it runs, so a rom_path saved through Settings → Paths takes effect
    on the next scan without re-importing the module.

    Patching note: monkeypatch through `scan_mod.settings_manager` rather
    than a fresh `import settings_manager`. `tests/test_pass46_frozen_paths`
    evicts `settings_manager` from `sys.modules` and re-imports it, so a
    later `import settings_manager` can yield a different module object
    than the one already cached inside `services.rom_scanner.settings_manager`
    (imported eagerly via `routes.maintenance` at app boot)."""

    def test_scan_roms_uses_settings_manager_path(self, tmp_path, monkeypatch):
        from scraper import scan_roms as scan_mod

        rom_root = _seed_rom_root(tmp_path)
        monkeypatch.setattr(
            scan_mod.settings_manager, 'get_effective_path',
            lambda key, fallback='': str(rom_root) if key == 'rom_path' else fallback,
        )

        inserted = _stub_db(monkeypatch, scan_mod)

        n = scan_mod.scan_roms()
        assert n == 1, (
            f'scan_roms() must find the seeded ROM via settings_manager — '
            f'got {n}, inserted={inserted}'
        )

    def test_run_inline_scan_uses_settings_manager_path(self, tmp_path, monkeypatch):
        """The inline fallback must resolve the same way."""
        from services import rom_scanner as scan_mod

        rom_root = _seed_rom_root(tmp_path, system='xbox360', filename='Halo 3 (USA).iso')
        monkeypatch.setattr(
            scan_mod.settings_manager, 'get_effective_path',
            lambda key, fallback='': str(rom_root) if key == 'rom_path' else fallback,
        )

        inserted = _stub_db_context(monkeypatch, scan_mod)
        monkeypatch.setattr(scan_mod, 'find_image_file', lambda *a, **kw: (None, None))

        n = scan_mod.run_inline_scan()
        assert n == 1, (
            f'run_inline_scan() must find the seeded ROM via settings_manager '
            f'— got {n}, inserted={inserted}'
        )


# -----------------------------------------------------------------------------
# 3 — Behavioural pin: empty rom_path raises typed error (not silent 0)
# -----------------------------------------------------------------------------

class TestScanRomsLoudFailureWhenUnset:
    """When rom_path is empty/missing, the scanner must raise
    `RomPathNotConfigured` so the caller can distinguish misconfiguration
    from an empty-but-configured library."""

    def test_scan_roms_raises_when_path_empty(self, monkeypatch):
        from scraper import scan_roms as scan_mod
        from services.rom_scanner import RomPathNotConfigured

        monkeypatch.setattr(
            scan_mod.settings_manager, 'get_effective_path',
            lambda key, fallback='': '',
        )
        # The DB stub isn't even reached when rom_path is empty — the check
        # must fire first.
        with pytest.raises(RomPathNotConfigured, match=r'[Ss]ettings'):
            scan_mod.scan_roms()

    def test_run_inline_scan_raises_when_path_empty(self, monkeypatch):
        from services import rom_scanner as scan_mod
        from services.rom_scanner import RomPathNotConfigured

        monkeypatch.setattr(
            scan_mod.settings_manager, 'get_effective_path',
            lambda key, fallback='': '',
        )
        with pytest.raises(RomPathNotConfigured, match=r'[Ss]ettings'):
            scan_mod.run_inline_scan()


# -----------------------------------------------------------------------------
# 4 — End-to-end pin: /api/scan returns success=False with remediation
# -----------------------------------------------------------------------------

class TestApiScanRomPathNotConfigured:
    """The HTTP layer must catch `RomPathNotConfigured` and return a 4xx
    JSON response with a user-facing remediation message instead of
    success=True with new_games=0 (which the JS toasts as a green
    "scan complete")."""

    def _client(self, monkeypatch):
        import app as app_module
        import settings_manager as _settings_manager

        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(
            _settings_manager, 'load_settings',
            lambda: {'setup_completed': True},
        )
        # Force the path-resolver to report unset regardless of disk state.
        monkeypatch.setattr(
            _settings_manager, 'get_effective_path',
            lambda key, fallback='': '',
        )
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        return app_module.app.test_client()

    def test_api_scan_returns_error_when_rom_path_unset(self, monkeypatch):
        c = self._client(monkeypatch)
        with c.session_transaction() as sess:
            sess['_csrf_token'] = 'scan-csrf-token'
        resp = c.post(
            '/api/scan',
            headers={'X-CSRF-Token': 'scan-csrf-token'},
            follow_redirects=False,
        )
        assert resp.status_code in (400, 422), (
            f'Expected 4xx when rom_path unset, got {resp.status_code} '
            f'with body {resp.get_data(as_text=True)[:200]}'
        )
        body = resp.get_json()
        assert body is not None, 'Response must be JSON, not HTML redirect'
        assert body.get('success') is False
        err = (body.get('error') or '').lower()
        assert 'rom path' in err or 'rom_path' in err, (
            f'Error message must mention rom path so the user knows where to '
            f'fix it. Got: {body!r}'
        )
        assert 'settings' in err, (
            f'Error message must point at Settings as the remediation. '
            f'Got: {body!r}'
        )
