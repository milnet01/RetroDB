"""PASS-59-63, browser-JS group: seven small front-end defects.

Where it is practical the real script runs in Node against a minimal
stand-in DOM (`_DOM` below), so the test exercises the shipped function
rather than its source text. The rest are precise source checks.
"""
import json
import re
import shutil
import subprocess

import pytest

from tests._util import REPO_ROOT, read_source

NODE = shutil.which('node')

needs_node = pytest.mark.skipif(NODE is None, reason='node not available')

# A deliberately small DOM: elements with id/class/dataset/style, a
# selector matcher for `#id`, `.cls`, `tag`, `tag.cls`, `[data-x]`,
# comma lists and one descendant level, and per-node listeners with a
# capture flag. Enough for the functions under test; nothing more.
_DOM = r"""
const vm = require('vm');
const fs = require('fs');
class ClassList {
  constructor(el) { this.el = el; this.s = new Set(); }
  add(...c) { c.forEach(x => this.s.add(x)); }
  remove(...c) { c.forEach(x => this.s.delete(x)); }
  contains(c) { return this.s.has(c); }
  toggle(c, f) { const on = f === undefined ? !this.s.has(c) : f; on ? this.s.add(c) : this.s.delete(c); return on; }
}
class Node_ {
  constructor() { this.listeners = []; }
  addEventListener(type, fn, opt) { this.listeners.push({type, fn, capture: opt === true || !!(opt && opt.capture)}); }
  removeEventListener(type, fn, opt) {
    const cap = opt === true || !!(opt && opt.capture);
    const i = this.listeners.findIndex(l => l.type === type && l.fn === fn && l.capture === cap);
    if (i >= 0) this.listeners.splice(i, 1);
  }
  fire(type, ev, phaseCapture) {
    this.listeners.filter(l => l.type === type && (phaseCapture === undefined || l.capture === phaseCapture))
      .slice().forEach(l => l.fn(ev));
  }
}
class El extends Node_ {
  constructor(tag) {
    super(); this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
    this.classList = new ClassList(this); this.dataset = {}; this.style = {}; this.attrs = {};
    this._text = ''; this.id = ''; this.value = ''; this.isContentEditable = false;
    this.offsetParent = {};
  }
  set className(v) { this.classList.s = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classList.s].join(' '); }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { this._html = String(v); this._text = ''; this.children = []; }
  get innerHTML() { return this._html || ''; }
  appendChild(c) { c.parentNode = this; this.children.push(c); if (c.id) document._ids[c.id] = c; return c; }
  remove() { if (this.parentNode) { const p = this.parentNode.children; p.splice(p.indexOf(this), 1); this.parentNode = null; } }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') { this.id = v; document._ids[v] = this; } }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  focus() { document.activeElement = this; }
  click() { this.fire('click', {target: this, stopPropagation() {}, preventDefault() {}}); }
  contains(o) { while (o) { if (o === this) return true; o = o.parentNode; } return false; }
  closest(sel) { let e = this; while (e && e.matches) { if (e.matches(sel)) return e; e = e.parentNode; } return null; }
  matches(sel) { return sel.split(',').some(s => matchOne(this, s.trim())); }
  _all() { const out = []; const walk = n => n.children.forEach(c => { out.push(c); walk(c); }); walk(this); return out; }
  querySelectorAll(sel) { return query(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
function simple(el, s) {
  const m = s.match(/^([a-zA-Z0-9]*)((?:[#.][\w-]+)*)((?:\[[^\]]+\])*)$/);
  if (!m) return false;
  if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
  for (const p of (m[2].match(/[#.][\w-]+/g) || [])) {
    if (p[0] === '#' && el.id !== p.slice(1)) return false;
    if (p[0] === '.' && !el.classList.contains(p.slice(1))) return false;
  }
  for (const a of (m[3].match(/\[[^\]]+\]/g) || [])) {
    const name = a.slice(1, -1).split('=')[0];
    if (name.startsWith('data-')) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      if (!(key in el.dataset)) return false;
    } else if (!(name in el.attrs)) return false;
  }
  return true;
}
function matchOne(el, s) {
  const parts = s.split(/\s+/);
  if (!simple(el, parts[parts.length - 1])) return false;
  if (parts.length === 1) return true;
  let p = el.parentNode;
  while (p && p.matches) { if (simple(p, parts[0])) return true; p = p.parentNode; }
  return false;
}
function query(root, sel) { return root._all().filter(e => e.matches(sel)); }
class Doc extends Node_ {
  constructor() { super(); this._ids = {}; this.body = new El('body'); this.head = new El('head');
    this.documentElement = new El('html'); this.activeElement = this.body; }
  createElement(t) { return new El(t); }
  getElementById(id) { const e = this._ids[id]; return e && (e === this.body || this.body.contains(e) || this.head.contains(e)) ? e : null; }
  querySelectorAll(sel) { return query(this.body, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const document = new Doc();
const win = new Node_();
const ctx = vm.createContext(Object.assign(win, {
  document, console, Date, JSON, Math, Promise, Set, Map, Array, Object, String, Number, RegExp, Error,
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: f => f(),
  MutationObserver: class { observe() {} disconnect() {} },
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  location: {pathname: '/', href: '/', hash: ''},
  navigator: {}, fetch: () => new Promise(() => {}),
  scrollTo() {}, getComputedStyle: () => ({}), AbortController,
  IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
}));
ctx.window = ctx;
ctx.El = El;
const g = name => vm.runInContext(name, ctx);
function load(rel) { vm.runInContext(fs.readFileSync(rel, 'utf8'), ctx, {filename: rel}); }
function make(tag, attrs, parent) {
  const e = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'id') { e.id = v; document._ids[v] = e; }
    else if (k === 'class') e.className = v;
    else if (k === 'dataset') Object.assign(e.dataset, v);
    else if (k === 'src') { e.src = v; e.attrs.src = v; }
    else e[k] = v;
  }
  (parent || document.body).appendChild(e);
  return e;
}
function keydown(key, mods) {
  const ev = Object.assign({key, target: document.body, shiftKey: false, ctrlKey: false,
    metaKey: false, altKey: false, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}}, mods || {});
  document.fire('keydown', ev, true);
  document.fire('keydown', ev, false);
  return ev;
}
"""


def _node(body):
    """Run `_DOM` + `body` in Node from the repo root; return the JSON the
    body prints with `out(...)`."""
    script = _DOM + 'const out = v => console.log(JSON.stringify(v));\n' + body
    res = subprocess.run([NODE, '-e', script], cwd=REPO_ROOT, capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-1500:]
    return json.loads(res.stdout.strip().splitlines()[-1])


def _src(rel):
    return read_source(rel)


# ---------------------------------------------------------------------------
# 1. Re-opening an open game modal must not stack a second focus trap.
# ---------------------------------------------------------------------------

@needs_node
@pytest.mark.parametrize('which', ['detail', 'edit'])
def test_reopening_an_open_modal_keeps_one_focus_trap(which):
    """AI Fill re-calls GameDetailModal.open() on the open modal. Each call
    pushed another trap, and close() pops only one, so a capture-phase
    keydown listener outlived the modal and kept swallowing Tab."""
    got = _node(r"""
load('static/js/utils.js');
load('static/js/game-modals.js');
const which = process.argv[1];
const M = which === 'detail' ? g('GameDetailModal') : g('GameEditModal');
// A parent dialog's trap underneath must survive the close.
g('ModalFocusTrap').activate(make('div'), null, {autoFocus: false});
const base = g('ModalFocusTrap')._stack.length;
const modal = make('div', {id: which === 'detail' ? 'gameDetailModal' : 'gameEditModal'});
make('button', {}, modal);
// Exercise only the trap bookkeeping, not the data loading.
if (which === 'detail') {
  ['gameDetailLoading', 'gameDetailContent'].forEach(id => make('div', {id}));
  M.cache.set(7, {});
  M.populate = () => {};
  M.open(7); M.open(7);
} else {
  const realOpen = M.open;
  const src = realOpen.toString();
  // open() fills the form first; stub the element look-ups it needs.
  ctx.document.getElementById = (id) => ctx.document._ids[id] || (ctx.document._ids[id] = new ctx.El('div'));
  ctx.document._ids.gameEditModal = modal;
  for (const k of Object.keys(M)) if (typeof M[k] === 'function' && k !== 'open' && k !== 'close') M[k] = () => {};
  g('GameDetailModal').currentId = 7;
  g('GameDetailModal').cache.set(7, {id: 7});
  try { M.open(); M.open(); } catch (e) { out({error: e.message, src: src.slice(0, 200)}); process.exit(0); }
}
const T = g('ModalFocusTrap');
const added = T._stack.length - base;
M.close();
out({added, leftover: T._stack.length - base,
     keydown: ctx.document.listeners.filter(l => l.type === 'keydown' && l.capture).length});
""".replace("process.argv[1]", json.dumps(which)))
    assert 'error' not in got, got
    assert got == {'added': 1, 'leftover': 0, 'keydown': 1}, got


# ---------------------------------------------------------------------------
# 2. Chip removal compares the canonical value, not the translated label.
# ---------------------------------------------------------------------------

_CHIPS = [
    ('Genre', 'genre', 'gemGenreContainer', 'gemGenreHidden', '.genre-tag'),
    ('Mode', 'modes', 'gemModesContainer', 'gemModesHidden', '.genre-tag'),
    ('SaveType', 'save_type', 'gemSaveTypeContainer', 'gemSaveTypeHidden', '.genre-tag'),
    ('Controller', 'controller', 'gemControllerContainer', 'gemControllerHidden', '.controller-tag'),
    ('GameStructure', 'game_structure', 'gemGameStructureContainer', 'gemGameStructureHidden', '.genre-tag'),
    ('Perspective', 'perspective', 'gemPerspectiveContainer', 'gemPerspectiveHidden', '.genre-tag'),
    ('Dimension', 'dimension', 'gemDimensionContainer', 'gemDimensionHidden', '.genre-tag'),
]


@needs_node
@pytest.mark.parametrize('kind, _field, container, hidden, sel', _CHIPS)
def test_chip_is_removed_under_a_translated_locale(kind, _field, container, hidden, sel):
    """With a non-English catalog, tField() renders 'Action' as 'Acción';
    removeX('Action') compared the chip's text to 'action' and never
    matched, so the chip stayed on screen while the hidden value lost it."""
    got = _node(f"""
load('static/js/utils.js');
load('static/js/game-modals.js');
ctx.tField = v => 'XX-' + v;          // any translation that changes the text
const M = g('GameEditModal');
const c = make('div', {{id: '{container}'}});
const h = make('input', {{id: '{hidden}'}});
for (const k of Object.keys(M)) if (/^update.*Dropdown$/.test(k)) M[k] = () => {{}};
h.value = 'Action, Puzzle';
M._createTag(c, '{sel[1:]}', 'Action', () => M.remove{kind}('Action'));
M._createTag(c, '{sel[1:]}', 'Puzzle', () => M.remove{kind}('Puzzle'));
M.remove{kind}('Action');
out({{hidden: h.value, chips: c.querySelectorAll('{sel}').map(e => e.dataset.value)}});
""")
    assert got == {'hidden': 'Puzzle', 'chips': ['Puzzle']}, got


# ---------------------------------------------------------------------------
# 3. Normalisation confirm renders its table as HTML, with values escaped.
# ---------------------------------------------------------------------------

def _norm_apply_src():
    src = _src('static/js/settings-page.js')
    start = src.index('    async apply() {')
    return src[start:src.index('    async _doApply(', start)]


def test_normalization_confirm_opts_into_html():
    body = _norm_apply_src()
    call = body[body.index('showConfirm('):]
    assert re.search(r'\{\s*allowHtml:\s*true\s*\}', call), call[:300]


def _holes(line):
    """Each ${...} expression in a template-literal line, braces balanced."""
    out, i = [], line.find('${')
    while i >= 0:
        depth, j = 1, i + 2
        while depth:
            depth += {'{': 1, '}': -1}.get(line[j], 0)
            j += 1
        out.append(line[i + 2:j - 1])
        i = line.find('${', j)
    return out


def test_normalization_confirm_escapes_every_interpolation():
    """allowHtml re-opens the innerHTML sink, so every ${...} that lands in
    the message must pass through escapeHtml()."""
    body = _norm_apply_src()
    msg_lines = [ln for ln in body.splitlines() if 'msg +=' in ln or 'msg =' in ln]
    holes = [h for ln in msg_lines for h in _holes(ln)]
    assert holes
    bad = [h for h in holes if not h.strip().startswith('escapeHtml(')]
    assert not bad, f'unescaped interpolations: {bad}'


# ---------------------------------------------------------------------------
# 4-6. main.js: shortcuts, early image errors, screenshot-modal close.
# ---------------------------------------------------------------------------

_MAIN = r"""
load('static/js/utils.js');
load('static/js/main.js');
"""


@needs_node
@pytest.mark.parametrize('mod', ['ctrlKey', 'metaKey', 'altKey'])
def test_shortcuts_ignore_modified_keys(mod):
    """Ctrl+D must bookmark, not run a shortcut; Ctrl+G must not be eaten."""
    got = _node(_MAIN + f"""
const K = g('KeyboardShortcuts');
let ran = 0;
K.shortcuts['d'] = {{action: () => ran++}};
const ev = (key, m) => Object.assign({{key, target: ctx.document.body, defaultPrevented: false,
  preventDefault() {{ this.defaultPrevented = true; }}}}, m);
const gEv = ev('g', {{{mod}: true}}); K.handleKeydown(gEv);
const dEv = ev('d', {{{mod}: true}}); K.handleKeydown(dEv);
const plain = ev('/', {{}});
let focused = 0; K.shortcuts['/'] = {{action: () => focused++}};
K.handleKeydown(plain);
out({{gPrevented: gEv.defaultPrevented, dPrevented: dEv.defaultPrevented, ran,
      pending: K.pendingKey, plainStillWorks: focused}});
""")
    assert got == {'gPrevented': False, 'dPrevented': False, 'ran': 0,
                   'pending': None, 'plainStillWorks': 1}, got


@needs_node
def test_image_that_failed_before_the_script_ran_still_gets_its_fallback():
    """core.bundle.js is deferred, so a missing server-rendered boxart can
    fire `error` before main.js runs. Those images must still be handled."""
    got = _node(r"""
// Server-rendered image that has already failed (complete, no pixels).
const img = make('img', {dataset: {onError: 'hide'}, complete: true, naturalWidth: 0, src: '/x.png'});
const ok = make('img', {dataset: {onError: 'hide'}, complete: true, naturalWidth: 120, src: '/y.png'});
const lazy = make('img', {dataset: {onError: 'hide'}, complete: false, naturalWidth: 0, src: '/z.png'});
load('static/js/utils.js');
load('static/js/main.js');
ctx.document.fire('DOMContentLoaded', {});
// A later failure is caught by the capture listener.
const late = make('img', {dataset: {onError: 'hide'}, src: '/w.png'});
ctx.document.fire('error', {target: late}, true);
out({early: img.style.display || null, ok: ok.style.display || null,
     lazy: lazy.style.display || null, late: late.style.display || null});
""")
    assert got == {'early': 'none', 'ok': None, 'lazy': None, 'late': 'none'}, got


@needs_node
def test_unrelated_modal_close_leaves_the_screenshot_modal_alone():
    """Every `.modal-close` on the page was wired to closeScreenshotModal,
    so closing a dialog on top of the screenshot viewer also closed the
    viewer state, restored page scroll and popped the wrong focus trap."""
    got = _node(r"""
const shot = make('div', {id: 'screenshotModal', class: 'modal'});
const shotClose = make('button', {class: 'modal-close'}, shot);
make('img', {id: 'modalImage'}, shot);
const other = make('div', {id: 'otherModal', class: 'modal'});
const otherClose = make('button', {class: 'modal-close'}, other);
load('static/js/utils.js');
load('static/js/main.js');
ctx.document.fire('DOMContentLoaded', {});
g('RetroDBState').screenshots = ['/a.png'];
ctx.openScreenshotModal(0);
otherClose.click();
other.fire('click', {target: other});
const afterOther = {open: shot.classList.contains('active'), traps: g('ModalFocusTrap')._stack.length};
shotClose.click();
out({afterOther, afterOwn: {open: shot.classList.contains('active'), traps: g('ModalFocusTrap')._stack.length}});
""")
    assert got == {'afterOther': {'open': True, 'traps': 1},
                   'afterOwn': {'open': False, 'traps': 0}}, got


# ---------------------------------------------------------------------------
# 7. Boxart fallback in an onerror attribute uses the JS-string escaper.
# ---------------------------------------------------------------------------

def test_boxart_fallback_onerror_uses_escattr():
    """The fallback filename sits inside a single-quoted JS string inside
    an HTML attribute; escapeHtml's &#039; is decoded before JS parses it,
    so a filename with a quote broke out. Pass 36.1's escAttr is the fix."""
    src = _src('static/js/all-games-controller.js')
    line = next(ln for ln in src.splitlines() if "this.src='/static/images/boxart/" in ln)
    assert '${escAttr(fallbackBoxart)}' in line, line.strip()
