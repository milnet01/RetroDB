# Pass 44 — ProcessRegistry: token registry + GC.
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def registry():
    from services.launcher.registry import ProcessRegistry
    return ProcessRegistry(post_exit_ttl_s=1.0)


@pytest.fixture
def fake_proc():
    p = MagicMock()
    p.pid = 12345
    p.poll.return_value = None  # running
    p.returncode = None
    return p


def test_register_and_get(registry, fake_proc):
    h = registry.register(token='t1', proc=fake_proc, game_id=1, emulator_id=2, started_at=100.0)
    assert registry.get('t1') is not None
    assert registry.get('t1').handle.pid == 12345
    assert h.token == 't1'


def test_get_unknown_returns_none(registry):
    assert registry.get('nope') is None


def test_active_returns_running_only(registry, fake_proc):
    registry.register(token='running', proc=fake_proc, game_id=1, emulator_id=1, started_at=100.0)

    exited_proc = MagicMock()
    exited_proc.pid = 22222
    exited_proc.poll.return_value = 0
    exited_proc.returncode = 0
    registry.register(token='exited', proc=exited_proc, game_id=2, emulator_id=2, started_at=99.0)

    active = registry.active()
    tokens = {h.token for h in active}
    assert 'running' in tokens
    assert 'exited' not in tokens


def test_find_by_game_returns_running(registry, fake_proc):
    registry.register(token='t1', proc=fake_proc, game_id=42, emulator_id=1, started_at=100.0)
    found = registry.find_running_by_game(42)
    assert found is not None
    assert found.token == 't1'

    assert registry.find_running_by_game(999) is None


def test_gc_removes_exited_after_ttl(registry):
    """Exited entries linger for post_exit_ttl_s, then are GC'd.

    Anchor TTL math to a frozen clock — `time.time()` jitter on a loaded CI
    runner could otherwise corrupt the cutoff arithmetic. Patches
    `services.launcher.registry.time.time` (the only call site that the
    test exercises in `gc()`).
    """
    exited_proc = MagicMock()
    exited_proc.poll.return_value = 1
    exited_proc.returncode = 1
    exited_proc.pid = 1
    t = 10_000.0
    registry.register(token='gone', proc=exited_proc, game_id=1, emulator_id=1,
                      started_at=t - 3.0)
    registry._mark_exited('gone', exit_time=t - 2.0)  # 2s ago, ttl=1.0

    with patch('services.launcher.registry.time.time', return_value=t):
        registry.gc()
    assert registry.get('gone') is None


def test_gc_keeps_recent_exited(registry):
    """Frozen clock — exit was at `t`, GC runs at `t`, so cutoff = t - ttl
    is strictly less than exit_time and the entry is preserved."""
    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0
    proc.pid = 1
    t = 10_000.0
    registry.register(token='recent', proc=proc, game_id=1, emulator_id=1,
                      started_at=t)
    registry._mark_exited('recent', exit_time=t)
    with patch('services.launcher.registry.time.time', return_value=t):
        registry.gc()
    assert registry.get('recent') is not None
