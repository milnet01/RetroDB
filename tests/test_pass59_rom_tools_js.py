"""Pass 59.86: a script loaded outside the bundles must not call t() at load.

Page scripts are loaded with a plain <script>, which runs before the deferred
core.bundle.js that defines the i18n helpers t() / tField(). A call evaluated
at load time threw, and everything after it in the file was never defined:
rom-tools.js (four ROM Tools pages) and log-viewer.js (the Logs page).

Each file listed in build_js.EXCLUDED is run in Node with those helpers absent
and a catch-all stand-in for the DOM, and must not fail on them."""
import os
import shutil
import subprocess

import pytest

import build_js
from tests._util import REPO_ROOT

NODE = shutil.which('node')

_RUNNER = r"""
const vm = require('vm');
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const any = new Proxy(function () {}, {
  get: (_t, k) => (k === 'then' ? undefined : any), apply: () => any, construct: () => any,
});
try {
  vm.runInNewContext(src, {window: any, document: any, localStorage: any, navigator: any,
    console, setTimeout() {}, setInterval() {}, fetch: () => new Promise(() => {})});
} catch (e) {
  if (/\b(t|tField) is not defined/.test(e.message)) { console.error(e.stack); process.exit(1); }
}
"""


@pytest.mark.skipif(NODE is None, reason='node not available')
@pytest.mark.parametrize('name', build_js.EXCLUDED)
def test_page_script_does_not_call_t_at_load(name):
    path = os.path.join(REPO_ROOT, 'static', 'js', name)
    result = subprocess.run([NODE, '-e', _RUNNER, path], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-600:]
