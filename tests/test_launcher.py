"""Unit tests for scripts/retrodb_launcher — port discovery + probe logic.

No real network / subprocess: server_url() is pure and is_running() is
exercised against a monkeypatched urlopen.
"""
import importlib.util
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    'retrodb_launcher', ROOT / 'scripts' / 'retrodb_launcher.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


class _FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_server_url_uses_config_port(monkeypatch):
    monkeypatch.setattr(launcher.config, 'SERVER_PORT', 5000)
    assert launcher.server_url() == 'http://localhost:5000'
    monkeypatch.setattr(launcher.config, 'SERVER_PORT', 8080)
    assert launcher.server_url() == 'http://localhost:8080'


def test_is_running_true_on_any_http_response(monkeypatch):
    monkeypatch.setattr(launcher, 'urlopen', lambda *a, **k: _FakeResp())
    assert launcher.is_running() is True


def test_is_running_false_on_connection_refused(monkeypatch):
    def _boom(*a, **k):
        raise URLError('Connection refused')
    monkeypatch.setattr(launcher, 'urlopen', _boom)
    assert launcher.is_running() is False
