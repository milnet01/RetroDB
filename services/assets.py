# =============================================================================
# RETRODB - Asset Manifest Service
# =============================================================================
# Reads static/asset_manifest.json (written by build_css.py + build_js.py) and
# exposes an `asset_url(relative_path)` helper that appends `?v=<sha-hash>` to
# the Flask static URL.  Per-file hashes let browsers keep the unchanged file
# in cache across patch bumps — a CSS-only change no longer busts the JS
# bundle and vice versa.
# =============================================================================

import json
import logging
import os
import threading

import config
from flask import url_for

logger = logging.getLogger(__name__)

_MANIFEST_CACHE = {'mtime': 0, 'data': {}}
_MANIFEST_LOCK = threading.Lock()


def _manifest_path():
    return os.path.join(config.STATIC_PATH, 'asset_manifest.json')


def _load_manifest():
    """Load + cache the manifest, refreshing on mtime change.

    Returns the cached dict directly — callers must treat it as read-only.
    """
    path = _manifest_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}

    with _MANIFEST_LOCK:
        if mtime != _MANIFEST_CACHE['mtime']:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    _MANIFEST_CACHE['data'] = json.load(f) or {}
                _MANIFEST_CACHE['mtime'] = mtime
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Could not load asset manifest: %s", e)
                _MANIFEST_CACHE['data'] = {}
                _MANIFEST_CACHE['mtime'] = mtime
        return _MANIFEST_CACHE['data']


def asset_url(relative_path):
    """Return a cache-busted static URL for `relative_path`.

    `relative_path` is the path under `static/` (e.g. `'css/main.min.css'`,
    `'js/core.bundle.js'`).  If the manifest has a hash for that file, the
    returned URL is `/static/<relative_path>?v=<hash>`; otherwise it falls
    back to `?v=<APP_VERSION>` so cache-busting still happens on version
    bumps even before the first manifest is written.
    """
    manifest = _load_manifest()
    version = manifest.get(relative_path)
    base = url_for('static', filename=relative_path)
    if version:
        return f"{base}?v={version}"
    return f"{base}?v={config.APP_VERSION}"
