"""Pass 44 — RetroArch path auto-detect endpoint.

Pins the wire shape of `/api/settings/retroarch/detect`: route registration,
auth gating (unauthenticated POSTs blocked), and the helper contract for the
binary + cores-dir probes that drive the response payload."""

import pytest


def test_detect_endpoint_registered():
    """The auto-detect route must be wired into the app — a missing
    blueprint registration would silently 404 the Settings page button."""
    import app as app_module
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert '/api/settings/retroarch/detect' in rules


def test_probe_binary_falls_through_to_which(monkeypatch):
    """When none of the chain paths exist, falls through to shutil.which."""
    from routes import launch_settings as ls
    monkeypatch.setattr(ls.Path, 'exists', lambda self: False, raising=False)
    # Make the flatpak info call fail
    monkeypatch.setattr(ls.subprocess, 'run',
                        lambda *a, **kw: type('X', (), {'returncode': 1})())
    monkeypatch.setattr(ls.shutil, 'which', lambda name: '/somewhere/retroarch')

    result = ls._probe_retroarch_binary()
    assert result == '/somewhere/retroarch'


def test_probe_binary_returns_none_when_which_fails(monkeypatch):
    """When no chain path exists AND shutil.which returns None (no RetroArch
    anywhere on PATH), the probe must return a falsy value — never invent a
    bogus path. c-006 C-2 coverage gap fix."""
    from routes import launch_settings as ls
    monkeypatch.setattr(ls.Path, 'exists', lambda self: False, raising=False)
    monkeypatch.setattr(ls.subprocess, 'run',
                        lambda *a, **kw: type('X', (), {'returncode': 1})())
    monkeypatch.setattr(ls.shutil, 'which', lambda name: None)

    result = ls._probe_retroarch_binary()
    assert not result, f"expected falsy probe result, got {result!r}"


def test_probe_cores_dir_returns_string(monkeypatch):
    """The probe always returns a string (empty if nothing found)."""
    from routes import launch_settings as ls
    monkeypatch.setattr(ls.Path, 'is_dir', lambda self: False, raising=False)
    out = ls._probe_cores_dir()
    assert isinstance(out, str)
    assert out == ''


def test_validate_binary_handles_empty():
    from routes.launch_settings import _validate_binary
    info = _validate_binary('')
    assert info.get('error') == 'empty'


def test_validate_binary_rejects_nonexistent():
    """A path that doesn't exist on disk must not validate — prevents the
    Settings UI from accepting typo'd binary paths that would fail at launch."""
    from routes.launch_settings import _validate_binary
    info = _validate_binary('/does/not/exist/retroarch-xyz')
    assert 'error' in info


def test_validate_cores_dir_handles_empty():
    from routes.launch_settings import _validate_cores_dir
    info = _validate_cores_dir('')
    assert info.get('error') == 'empty'


def test_validate_cores_dir_rejects_nondir(tmp_path):
    """An existing path that is not a directory is rejected."""
    from routes.launch_settings import _validate_cores_dir
    f = tmp_path / 'not-a-dir'
    f.write_text('x')
    info = _validate_cores_dir(str(f))
    assert 'error' in info


def test_validate_cores_dir_accepts_dir_with_cores(tmp_path):
    from routes.launch_settings import _validate_cores_dir
    (tmp_path / 'snes9x_libretro.so').write_bytes(b'\x7fELF')
    info = _validate_cores_dir(str(tmp_path))
    assert info.get('core_count') == 1


def test_validate_cores_dir_rejects_dir_without_cores(tmp_path):
    from routes.launch_settings import _validate_cores_dir
    info = _validate_cores_dir(str(tmp_path))
    assert 'error' in info


def test_unauth_detect_blocked():
    """Unauthenticated callers must be redirected/blocked — the auto-detect
    endpoint runs filesystem probes and must not leak shape info to anonymous
    visitors."""
    import app as app_module
    client = app_module.app.test_client()
    rv = client.post('/api/settings/retroarch/detect')
    assert rv.status_code in (302, 401, 403)
