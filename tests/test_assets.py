"""Tests for the asset manifest service (Pass 13.3)."""

import json
import os
from unittest.mock import patch

import pytest
from flask import Flask

from services import assets


@pytest.fixture
def app_with_manifest(tmp_path):
    """Spin up a minimal Flask app pointing at a temp static dir."""
    static_dir = tmp_path / 'static'
    static_dir.mkdir()
    manifest = static_dir / 'asset_manifest.json'

    app = Flask(__name__, static_folder=str(static_dir), static_url_path='/static')

    with patch.object(assets, 'config') as mock_cfg:
        mock_cfg.STATIC_PATH = str(static_dir)
        mock_cfg.APP_VERSION = '2.84.2'
        # Reset the module-level cache so each test starts fresh.
        assets._MANIFEST_CACHE['mtime'] = 0
        assets._MANIFEST_CACHE['data'] = {}
        yield app, manifest


class TestAssetUrl:
    def test_falls_back_to_app_version_when_manifest_missing(self, app_with_manifest):
        app, manifest = app_with_manifest
        with app.test_request_context('/'):
            url = assets.asset_url('js/core.bundle.js')
        assert url == '/static/js/core.bundle.js?v=2.84.2'

    def test_uses_manifest_hash_when_present(self, app_with_manifest):
        app, manifest = app_with_manifest
        manifest.write_text(json.dumps({
            'js/core.bundle.js': 'abcd1234',
            'css/main.min.css': 'deadbeef',
        }))
        with app.test_request_context('/'):
            assert assets.asset_url('js/core.bundle.js') == '/static/js/core.bundle.js?v=abcd1234'
            assert assets.asset_url('css/main.min.css') == '/static/css/main.min.css?v=deadbeef'

    def test_unknown_path_falls_back_to_app_version(self, app_with_manifest):
        app, manifest = app_with_manifest
        manifest.write_text(json.dumps({'js/core.bundle.js': 'abcd1234'}))
        with app.test_request_context('/'):
            url = assets.asset_url('js/theme.js')
        assert url == '/static/js/theme.js?v=2.84.2'

    def test_manifest_cache_refreshes_on_mtime_change(self, app_with_manifest):
        app, manifest = app_with_manifest
        manifest.write_text(json.dumps({'js/core.bundle.js': 'v1'}))
        with app.test_request_context('/'):
            assert assets.asset_url('js/core.bundle.js').endswith('?v=v1')

        # Rewrite with a new hash and bump mtime explicitly — on fast filesystems
        # the second write can land in the same whole second.
        mtime1 = os.path.getmtime(manifest)
        manifest.write_text(json.dumps({'js/core.bundle.js': 'v2'}))
        new_mtime = mtime1 + 2
        os.utime(manifest, (new_mtime, new_mtime))

        with app.test_request_context('/'):
            assert assets.asset_url('js/core.bundle.js').endswith('?v=v2')

    def test_corrupt_manifest_falls_back_gracefully(self, app_with_manifest):
        app, manifest = app_with_manifest
        manifest.write_text('{not valid json}')
        with app.test_request_context('/'):
            url = assets.asset_url('js/core.bundle.js')
        assert url.endswith('?v=2.84.2')
