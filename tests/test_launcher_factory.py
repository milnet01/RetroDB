# Pass 42 — get_launcher() factory keyed on launcher_backend setting.
import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test starts with a fresh launcher singleton — otherwise the first
    test's call freezes the backend choice for the whole session."""
    from services import launcher
    launcher._singleton = None
    yield
    launcher._singleton = None


def test_factory_returns_local_when_setting_local(monkeypatch):
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'local' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    from services.launcher.local import LocalLauncher
    launcher = get_launcher()
    assert isinstance(launcher, LocalLauncher)


def test_factory_raises_for_remote_in_v1(monkeypatch):
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'remote' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    with pytest.raises(NotImplementedError):
        get_launcher()


def test_factory_raises_for_unknown(monkeypatch):
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'spaceship' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    with pytest.raises(ValueError):
        get_launcher()


def test_factory_returns_singleton(monkeypatch):
    """Subsequent calls return the same launcher (so its registry persists)."""
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'local' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    a = get_launcher()
    b = get_launcher()
    assert a is b
