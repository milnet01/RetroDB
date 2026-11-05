"""The ROCm kernel override for RDNA2 cards (PASS-59-249).

An RX 6600-series card (gfx1031 to gfx1036) has no ROCm kernels of its own;
HSA_OVERRIDE_GFX_VERSION=10.3.0 makes it use gfx1030's. Any other card breaks
under that override, so it is set only when every GPU is RDNA2, and never over
a value the user set. Standard library only: app.py calls it before any GPU
library loads.
"""

import glob
import os

KFD_NODES = '/sys/class/kfd/kfd/topology/nodes'


def _gfx_versions(nodes_dir):
    """gfx_target_version of each GPU node; a CPU node reports 0."""
    versions = []
    for path in glob.glob(os.path.join(nodes_dir, '*', 'properties')):
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    key, _, value = line.partition(' ')
                    if key == 'gfx_target_version' and value.strip().isdigit():
                        if int(value) > 0:
                            versions.append(int(value))
                        break
        except OSError:
            continue
    return versions


def rdna2_override_wanted(nodes_dir=KFD_NODES):
    """True when there is a GPU and every GPU is gfx103x (RDNA2)."""
    versions = _gfx_versions(nodes_dir)
    return bool(versions) and all(100300 <= v < 100400 for v in versions)


def apply_rdna2_override(nodes_dir=KFD_NODES):
    """Set HSA_OVERRIDE_GFX_VERSION=10.3.0 when wanted and not already set.
    True when the override is in effect afterwards."""
    if 'HSA_OVERRIDE_GFX_VERSION' in os.environ:
        return os.environ['HSA_OVERRIDE_GFX_VERSION'] == '10.3.0'
    if not rdna2_override_wanted(nodes_dir):
        return False
    os.environ['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'
    return True
