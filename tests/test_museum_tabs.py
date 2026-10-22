"""The Museum system page's tabs switch when clicked.

main.js delegates every `data-on-click` from `document`, so a handler handed
"$event" sees `event.currentTarget === document`, which has no classList.
The tab switcher threw there (v3.30.0 to 3.31.0) and no other tab ever
showed. The real museum.js runs in Node against a stand-in page.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from tests._util import REPO_ROOT, read_source

NODE = shutil.which('node')

_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
class ClassList {
  constructor() { this.s = new Set(); }
  add(c) { this.s.add(c); } remove(c) { this.s.delete(c); } contains(c) { return this.s.has(c); }
}
function el(attrs, cls) {
  const e = {attrs: Object.assign({}, attrs), classList: new ClassList(), style: {}, id: attrs.id || ''};
  e.getAttribute = k => (k in e.attrs ? e.attrs[k] : null);
  e.setAttribute = (k, v) => { e.attrs[k] = String(v); };
  e.removeAttribute = k => { delete e.attrs[k]; };
  (cls || []).forEach(c => e.classList.add(c));
  return e;
}
const tabs = ['history', 'specifications', 'top-games', 'controllers'];
const nav = tabs.map((t, i) => el(i === 0 ? {href: '#' + t, 'aria-current': 'page'} : {href: '#' + t},
                                  i === 0 ? ['museum-nav-item', 'active'] : ['museum-nav-item']));
const sections = tabs.map((t, i) => { const s = el({id: t}, ['museum-section']); s.style.display = i ? 'none' : ''; return s; });
const document = {
  addEventListener() {},
  querySelectorAll(sel) { return sel === '.museum-nav-item' ? nav : sel === '.museum-section' ? sections : []; },
  getElementById(id) { return sections.find(s => s.id === id) || null; },
};
const ctx = {document, window: {location: {hash: ''}}, history: {replaceState() {}}, console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const args = JSON.parse(process.argv[3]);
// What main.js passes for "$this" / "$event" from its document listener.
const event = {currentTarget: document, target: nav[2], preventDefault() {}};
const resolved = args.map(a => a === '$this' ? nav[2] : a === '$event' ? event : a);
let error = null;
try { ctx.switchMuseumTab(...resolved); } catch (e) { error = String(e); }
console.log(JSON.stringify({
  error,
  active: nav.map(n => n.classList.contains('active')),
  current: nav.map(n => n.getAttribute('aria-current')),
  shown: sections.map(s => s.style.display !== 'none'),
}));
"""


def _tab_links():
    html = read_source('templates/museum_system.html')
    return re.findall(r'<a [^>]*class="museum-nav-item[^"]*"[^>]*>', html)


def test_every_tab_link_passes_its_own_element():
    links = _tab_links()
    assert len(links) == 4
    for link in links:
        args = json.loads(re.search(r"data-args='([^']*)'", link).group(1))
        assert args[0] == '$this', link
        assert 'data-prevent' in link, link   # a #hash link must not jump


@pytest.mark.skipif(NODE is None, reason='node not available')
def test_clicking_a_tab_shows_its_section(tmp_path):
    harness = tmp_path / 'harness.js'
    harness.write_text(_HARNESS)
    link = _tab_links()[2]
    args = re.search(r"data-args='([^']*)'", link).group(1)
    done = subprocess.run([NODE, str(harness), os.path.join(REPO_ROOT, 'static', 'js', 'museum.js'), args],
                          capture_output=True, text=True, timeout=30, check=True)
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out['error'] is None
    assert out['active'] == [False, False, True, False]
    assert out['current'] == [None, None, 'page', None]
    assert out['shown'] == [False, False, True, False]
