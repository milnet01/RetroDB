"""PASS-59-249: the RDNA2 kernel override is set only for RDNA2 cards.

HSA_OVERRIDE_GFX_VERSION=10.3.0 makes an RX 6600 (gfx1032) use gfx1030
kernels. It was forced for every AMD card, and over a value the user set."""
import pytest

from services import gpu_env


def _nodes(tmp_path, *versions):
    for i, v in enumerate(versions):
        node = tmp_path / str(i)
        node.mkdir()
        (node / 'properties').write_text(f'simd_count 4\ngfx_target_version {v}\n')
    return str(tmp_path)


@pytest.mark.parametrize('versions,wanted', [
    ((0, 100302), True),        # CPU node + RX 6600
    ((100300,), True),          # gfx1030 itself: harmless
    ((0, 110000), False),       # RDNA3
    ((90010,), False),          # Vega
    ((100302, 110000), False),  # mixed: the override would break the other card
    ((0,), False),              # no GPU
])
def test_override_only_for_rdna2(tmp_path, versions, wanted):
    assert gpu_env.rdna2_override_wanted(_nodes(tmp_path, *versions)) is wanted


def test_missing_topology_wants_nothing(tmp_path):
    assert gpu_env.rdna2_override_wanted(str(tmp_path / 'none')) is False


def test_a_users_own_value_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv('HSA_OVERRIDE_GFX_VERSION', '11.0.0')
    gpu_env.apply_rdna2_override(_nodes(tmp_path, 0, 100302))
    import os
    assert os.environ['HSA_OVERRIDE_GFX_VERSION'] == '11.0.0'


def test_set_for_an_rx_6600(tmp_path, monkeypatch):
    monkeypatch.delenv('HSA_OVERRIDE_GFX_VERSION', raising=False)
    assert gpu_env.apply_rdna2_override(_nodes(tmp_path, 0, 100302)) is True
    import os
    assert os.environ['HSA_OVERRIDE_GFX_VERSION'] == '10.3.0'


def test_app_py_does_not_force_the_override():
    from pathlib import Path
    src = Path(gpu_env.__file__).resolve().parent.parent.joinpath('app.py').read_text(encoding='utf-8')
    assert "os.environ['HSA_OVERRIDE_GFX_VERSION'] =" not in src
