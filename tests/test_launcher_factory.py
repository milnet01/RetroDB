# Pass 44 — get_launcher() factory keyed on launcher_backend setting.
import pytest


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """Each test starts with a fresh launcher singleton — otherwise the first
    test's call freezes the backend choice for the whole session.
    monkeypatch.setattr restores on teardown even if a collection-time error
    bypasses the yield."""
    from services import launcher
    monkeypatch.setattr(launcher, '_singleton', None)
    yield


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
    # match= pins the user-facing error wording — a refactor to a bare
    # `raise NotImplementedError()` would otherwise pass this test.
    with pytest.raises(NotImplementedError, match=r"remote"):
        get_launcher()


def test_factory_raises_for_unknown(monkeypatch):
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'spaceship' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    with pytest.raises(ValueError, match=r"spaceship"):
        get_launcher()


def test_factory_returns_singleton(monkeypatch):
    """Subsequent calls return the same launcher (so its registry persists)."""
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: 'local' if key == 'launcher_backend' else default)
    from services.launcher import get_launcher
    a = get_launcher()
    b = get_launcher()
    assert a is b


def test_factory_defaults_to_local_when_setting_absent(monkeypatch):
    """Coverage gap (audit LOW): when `launcher_backend` is not set, the
    factory must fall through to the safe default ('local') rather than
    raising. Pins the `get_setting(..., 'local')` default in the factory."""
    # get_setting forwards `default` straight through when the key has
    # never been written — simulate that by returning the supplied default.
    monkeypatch.setattr('services.launcher.get_setting',
                        lambda key, default=None: default)
    from services.launcher import get_launcher
    from services.launcher.local import LocalLauncher
    launcher = get_launcher()
    assert isinstance(launcher, LocalLauncher)
