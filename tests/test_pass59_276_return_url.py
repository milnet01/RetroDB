"""PASS-59-276: a toast's return URL must stay on this site.

`UnifiedToastController._isSafeReturnUrl` once accepted any value starting
with one slash, but a browser reads `/\\evil.example` and `/<tab>/evil.example`
as `//evil.example`, another site. The guard now parses every value and
compares origins. This runs the real method in node.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from tests._util import REPO_ROOT

NODE = shutil.which('node')

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const m = src.match(/_isSafeReturnUrl\(url\) \{[\s\S]*?\n    \},/);
global.window = {location: {origin: 'http://retrodb.lan:5000'}};
const obj = eval('({' + m[0] + '})');
const urls = JSON.parse(process.argv[3]);
console.log(JSON.stringify(urls.map(u => obj._isSafeReturnUrl(u))));
"""

CASES = {
    '/games': True,
    '/system/3?sort=title': True,
    'http://retrodb.lan:5000/games': True,
    '//evil.example/': False,
    '/\\evil.example': False,
    '/\t/evil.example': False,
    'https://evil.example/': False,
    'javascript:alert(1)': False,
    '': False,
}


@pytest.mark.skipif(NODE is None, reason='node not available')
def test_return_url_stays_on_this_site(tmp_path):
    harness = tmp_path / 'harness.js'
    harness.write_text(_HARNESS)
    js = os.path.join(REPO_ROOT, 'static', 'js', 'toast-controller.js')
    urls = list(CASES)
    done = subprocess.run([NODE, str(harness), js, json.dumps(urls)],
                          capture_output=True, text=True, timeout=30, check=True)
    got = dict(zip(urls, json.loads(done.stdout.strip().splitlines()[-1])))
    assert got == CASES


def test_harness_finds_the_method():
    src = open(os.path.join(REPO_ROOT, 'static', 'js', 'toast-controller.js'), encoding='utf-8').read()
    assert re.search(r'_isSafeReturnUrl\(url\) \{[\s\S]*?\n    \},', src)
