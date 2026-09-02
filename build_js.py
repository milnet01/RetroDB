#!/usr/bin/env python3
"""
RetroDB JS Build Script
Concatenates and conservatively minifies deferred JS files into a single bundle.

Usage:
    python build_js.py              # Build core.bundle.js + games.bundle.js (minified)
    python build_js.py --dev        # Just verify all files exist
    python build_js.py --no-minify  # Concatenate without minifying

Notes:
    - theme.js is NOT included (loaded separately for FOUC prevention)
    - Page-specific JS files are NOT included (loaded per-page)
    - Each source file is wrapped in an IIFE to prevent variable leaking
    - Minification is conservative: no variable renaming, no structural changes
"""

import hashlib
import json
import re
import sys
from pathlib import Path

# Two-bundle split (Pass 13.2): core loads on every page; games loads only
# on templates that opt in via {% set needs_games_bundle = true %}.
#
# Core bundle — everything every page relies on (ambient APIs, toast polling,
# sidebar + keyboard shortcuts).
CORE_ORDER = [
    'utils.js',
    'toast-controller.js',
    'main.js',
]

# Games bundle — game card interactions, bulk ops, detail/edit modals, and
# alphabet nav (used by achievements / trophies listing pages alongside games).
GAMES_ORDER = [
    'filters.js',
    'bulk-scrape.js',
    'bulk-edit.js',
    'game-list.js',
    'game-modals.js',
]

# Combined source list — used by verify_files() to check every bundled source
# exists before any concatenation runs.
JS_ORDER = CORE_ORDER + GAMES_ORDER

# Files NOT included in any bundle (loaded separately)
EXCLUDED = [
    'theme.js',              # FOUC prevention - loaded non-deferred
    'all-games-controller.js',  # Page-specific
    'achievements.js',          # Page-specific
    'trophies.js',              # Page-specific
    'settings-page.js',         # Page-specific
    'log-viewer.js',            # Page-specific
    'rom-tools.js',             # Page-specific
    'museum.js',                # Page-specific
]

BUNDLES = [
    ('core.bundle.js', CORE_ORDER),
    ('games.bundle.js', GAMES_ORDER),
]
OUTPUT_FILENAME = 'core.bundle.js'  # primary output for freshness checks


def get_js_dir():
    """Get the JS directory path."""
    script_dir = Path(__file__).parent
    return script_dir / 'static' / 'js'


def get_manifest_path():
    """Shared cache-bust manifest at static/asset_manifest.json.

    Maps each built output relative to static/ (e.g. 'js/core.bundle.js',
    'css/main.min.css') to the first 8 hex chars of its SHA-256 content
    hash.  Read at request time by the `asset_url` template global so browsers
    can cache individual files independently of the APP_VERSION string.
    """
    return Path(__file__).parent / 'static' / 'asset_manifest.json'


def _load_manifest():
    path = get_manifest_path()
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_manifest(manifest):
    path = get_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


def _content_hash(path):
    """First 8 hex chars of SHA-256 of file content — long enough for
    cache-bust collision safety, short enough for readable URLs."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()[:8]


def update_manifest_entries(entries):
    """Merge {relative_path: hash} pairs into static/asset_manifest.json."""
    manifest = _load_manifest()
    manifest.update(entries)
    _write_manifest(manifest)


def verify_files():
    """Verify all JS files exist."""
    js_dir = get_js_dir()
    missing = []

    for js_file in JS_ORDER:
        path = js_dir / js_file
        if not path.exists():
            missing.append(js_file)

    return missing


def is_output_fresh():
    """Return True when every bundle is newer than every source file it owns.

    Skips the rebuild when no source has changed since the last build — makes
    the mandatory "rebuild JS after edits" step a no-op when nothing touched
    the bundled JS, instead of re-reading and re-concatenating 9 files.
    """
    js_dir = get_js_dir()

    # Also consider the build script itself — if we changed the minifier
    # or the bundle membership, rebuild regardless of source mtimes.
    script_mtime = Path(__file__).resolve().stat().st_mtime

    # Pass 59.16 — every i18n-scanned source, not just the bundled ones.
    # build() regenerates services/js_i18n_strings.py, so a t() added to a
    # page-specific file (settings-page.js, museum.js, theme.js...) must
    # invalidate the build; iterating BUNDLES alone reported "up-to-date" and
    # main() returned before the manifest was ever rewritten.
    watched = set(js_i18n_sources(js_dir))
    for _bundle_name, order in BUNDLES:
        watched.update(order)

    outputs = [js_dir / bundle_name for bundle_name, _order in BUNDLES]
    outputs.append(js_i18n_manifest_path())

    for output_path in outputs:
        if not output_path.exists():
            return False
        output_mtime = output_path.stat().st_mtime
        if script_mtime > output_mtime:
            return False
        for js_file in watched:
            path = js_dir / js_file
            if not path.exists():
                continue
            if path.stat().st_mtime > output_mtime:
                return False

    return True


def minify_js(js_text):
    """Conservative JS minification.

    Only performs safe transformations:
    - Remove lines that are purely whitespace
    - Remove lines that only contain a single-line // comment
    - Collapse 3+ consecutive newlines into 2
    - Trim trailing whitespace from lines

    Does NOT:
    - Remove multi-line comments (may contain important data)
    - Rename variables
    - Remove whitespace between tokens
    - Insert or remove semicolons
    """
    lines = js_text.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()

        # Remove lines that are only whitespace
        if stripped == '':
            result.append('')
            continue

        # Remove lines that only contain a single-line // comment
        # (line starts with optional whitespace then //)
        if stripped.startswith('//'):
            continue

        # Trim trailing whitespace from lines
        result.append(line.rstrip())

    text = '\n'.join(result)

    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text


def _build_one(js_dir, bundle_name, order, do_minify):
    """Concatenate `order` into `bundle_name`; return (orig, final) byte size."""
    output = []
    total_lines = 0
    file_count = 0

    print(f"  Bundle: {bundle_name}")
    for js_file in order:
        path = js_dir / js_file
        if not path.exists():
            print(f"    MISSING: {js_file}")
            continue

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.count('\n') + 1
            total_lines += lines

        # Wrap each file in an IIFE to prevent variable leaking
        wrapped = f'// === {js_file} ===\n(function(){{\n{content}\n}})();\n'
        output.append(wrapped)
        file_count += 1

        size_kb = len(content.encode('utf-8')) / 1024
        print(f"    + {js_file} ({lines} lines, {size_kb:.1f} KB)")

    combined = '\n'.join(output)
    original_size = len(combined.encode('utf-8'))

    if do_minify:
        combined = minify_js(combined)

    final_size = len(combined.encode('utf-8'))

    output_path = js_dir / bundle_name
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(combined)

    if do_minify:
        reduction = (1 - final_size / original_size) * 100 if original_size else 0
        print(f"    Size: {original_size:,} -> {final_size:,} bytes ({reduction:.1f}% reduction, {total_lines:,} src lines)")
    else:
        print(f"    Size: {final_size:,} bytes ({total_lines:,} src lines)")
    return original_size, final_size


def _hash_vendor_files(js_dir):
    """Hash every file under static/js/vendor/ for cache-busting via asset_url.

    Vendor files (Chart.js, future bundled libraries) ship pre-minified from
    upstream — we don't concatenate or transform them, just register their
    SHA-256 prefix so a version bump invalidates the browser cache cleanly.
    """
    vendor_dir = js_dir / 'vendor'
    if not vendor_dir.is_dir():
        return {}
    out = {}
    for path in sorted(vendor_dir.iterdir()):
        if path.is_file() and path.suffix in ('.js', '.mjs'):
            out[f'js/vendor/{path.name}'] = _content_hash(path)
    return out


# =============================================================================
# i18n JS msgid manifest (Pass 43.3)
# =============================================================================
# Every source JS file (NOT the generated bundles). The manifest is the runtime
# key set for window.I18N; catalog coverage comes separately from babel.cfg's
# [javascript:] mapping. The CI gate (scripts/check_i18n_fresh.py) cross-checks
# the two. See docs/specs/i18n.md §6.
# Pass 59.15 — globbed, not enumerated. The old `CORE_ORDER + GAMES_ORDER +
# EXCLUDED` list silently omitted every JS file added since it was written, so
# a t() call in one was never scanned, never reached the catalog, and never
# failed the CI gate (which calls this same collector, so it compared a blind
# scan against a blind manifest). A glob scans a new file by default.
def js_i18n_sources(js_dir):
    """Sorted names of every hand-written JS source (generated bundles out)."""
    return sorted(
        p.name for p in js_dir.glob('*.js') if not p.name.endswith('.bundle.js')
    )

# t('...') / t("...") literal calls — single-line, quote immediately after `t(`
# (optional whitespace tolerated). \b before t so format()/print() never match;
# the inner group handles backslash escapes (captured RAW, decoded below).
_T_CALL_RE = re.compile(r"""\bt\(\s*(['"])((?:\\.|(?!\1).)*?)\1""")

# Block (incl. JSDoc) + line comments, stripped before scanning so a t('...')
# example inside a comment isn't counted. `(?<!:)` keeps `http://` inside string
# literals from being mistaken for a line comment.
_JS_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_JS_LINE_COMMENT_RE = re.compile(r'(?<!:)//[^\n]*')

# JS string escapes we decode so the manifest key matches the *runtime* msgid
# (the JS engine decodes `…`/`\n`/`\'` before passing the string to t()) and
# the catalog msgid (the generated _() anchors below carry the decoded char).
_JS_ESCAPE_RE = re.compile(r'\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\\\'"/bfnrt])')
_JS_SIMPLE_ESCAPES = {'\\': '\\', "'": "'", '"': '"', '/': '/',
                      'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}

JS_I18N_MANIFEST = 'js_i18n_strings.py'  # written under services/


def js_i18n_manifest_path():
    """Where generate_js_i18n_manifest writes, and is_output_fresh reads."""
    return Path(__file__).resolve().parent / 'services' / JS_I18N_MANIFEST


def _decode_js_string(raw):
    """Decode the common JS string escapes in a captured t() literal."""
    def repl(m):
        e = m.group(1)
        if e[0] in 'ux':
            return chr(int(e[1:], 16))
        return _JS_SIMPLE_ESCAPES[e]
    return _JS_ESCAPE_RE.sub(repl, raw)


def scan_t_keys(js_text):
    """Return the set of *decoded* msgids from literal t('...') calls in one JS
    source. Comments are stripped first so a documented t('...') example isn't
    counted."""
    stripped = _JS_LINE_COMMENT_RE.sub('', _JS_BLOCK_COMMENT_RE.sub('', js_text))
    return {_decode_js_string(m.group(2)) for m in _T_CALL_RE.finditer(stripped)}


def collect_js_i18n_keys(js_dir):
    """Sorted unique JS msgids across every source file (skips missing files)."""
    keys = set()
    for name in js_i18n_sources(js_dir):
        path = js_dir / name
        if path.exists():
            keys |= scan_t_keys(path.read_text(encoding='utf-8'))
    return sorted(keys)


def render_js_i18n_module(keys):
    """Render the services/js_i18n_strings.py text for a key list (deterministic
    output — byte-stable across runs so the CI gate compares parsed sets cleanly).

    Emits TWO things from the same sorted key list:
      * JS_I18N_KEYS — the runtime set app.py loops through to build window.I18N.
      * _EXTRACTION_ANCHORS — literal lazy_gettext _() calls so pybabel's *Python*
        extractor pulls every JS msgid into the catalog. This is the bridge: we
        do NOT use babel.cfg's [javascript:] extractor, because pybabel's JS
        lexer mis-parses this codebase's template literals / ES6 and silently
        drops calls. build_js's regex is the single reliable reader. See
        docs/specs/i18n.md §6.
    """
    lines = [
        '"""AUTO-GENERATED by build_js.py — do not edit.',
        '',
        'Source-text msgids of every literal t(\'...\') call in the JS sources.',
        'JS_I18N_KEYS is the runtime set for window.I18N (app.py js_i18n_map);',
        '_EXTRACTION_ANCHORS bridges the same msgids into the gettext catalog via',
        "pybabel's Python extractor. Regenerate with `python3 build_js.py`; the CI",
        'gate (scripts/check_i18n_fresh.py) fails if this drifts. See docs/specs/i18n.md §6.',
        '"""',
        '',
        'from flask_babel import lazy_gettext as _',
        '',
        'JS_I18N_KEYS = [',
    ]
    lines += [f'    {k!r},' for k in keys]
    lines += [
        ']',
        '',
        '# Extraction anchors (pybabel reads these literal _() calls). Mirror',
        '# JS_I18N_KEYS exactly — kept as a tuple so the calls are not bare',
        '# expression statements.',
        '_EXTRACTION_ANCHORS = (',
    ]
    lines += [f'    _({k!r}),' for k in keys]
    lines += [')', '']
    return '\n'.join(lines)


def generate_js_i18n_manifest(js_dir):
    """Write services/js_i18n_strings.py from the current JS sources. Returns the
    key count. Only rewrites when content changes (keeps mtime stable for caches)."""
    keys = collect_js_i18n_keys(js_dir)
    out_path = js_i18n_manifest_path()
    new_text = render_js_i18n_module(keys)
    if not out_path.exists() or out_path.read_text(encoding='utf-8') != new_text:
        out_path.write_text(new_text, encoding='utf-8')
        print(f"  i18n: wrote {len(keys)} JS msgid(s) -> services/{JS_I18N_MANIFEST}")
    else:
        print(f"  i18n: {len(keys)} JS msgid(s) — manifest unchanged")
    return len(keys)


def build(do_minify=True):
    """Concatenate all JS files into core+games bundles, optionally minifying."""
    js_dir = get_js_dir()

    print(f"Building JS bundles{' (minified)' if do_minify else ''}...")
    print("-" * 50)

    # Refresh the i18n JS msgid manifest before bundling (Pass 43.3).
    generate_js_i18n_manifest(js_dir)

    totals = [0, 0]
    manifest_updates = {}
    for bundle_name, order in BUNDLES:
        orig, final = _build_one(js_dir, bundle_name, order, do_minify)
        totals[0] += orig
        totals[1] += final
        manifest_updates[f'js/{bundle_name}'] = _content_hash(js_dir / bundle_name)

    # Register vendor files so asset_url() emits a content-hash query string.
    manifest_updates.update(_hash_vendor_files(js_dir))

    update_manifest_entries(manifest_updates)

    print("-" * 50)
    if do_minify:
        reduction = (1 - totals[1] / totals[0]) * 100 if totals[0] else 0
        print(f"All bundles: {totals[0]:,} -> {totals[1]:,} bytes ({reduction:.1f}% reduction)")
    else:
        print(f"All bundles: {totals[1]:,} bytes")

    # Remove legacy single bundle if it's still on disk — prevents accidental
    # double-load if a template was missed during the split.
    legacy = js_dir / 'app.bundle.js'
    if legacy.exists():
        legacy.unlink()
        print(f"Removed legacy: {legacy.name}")

    print()
    print("Excluded (loaded separately):")
    for f in EXCLUDED:
        print(f"  - {f}")
    print()
    print("Build complete!")


def main():
    """Main entry point."""
    dev_mode = '--dev' in sys.argv
    no_minify = '--no-minify' in sys.argv
    force = '--force' in sys.argv

    # Verify all files exist
    missing = verify_files()

    if missing:
        print("Missing JS files:")
        for f in missing:
            print(f"  - {f}")
        if not dev_mode:
            print("\nBuild aborted. Create missing files first.")
            sys.exit(1)
        return

    if dev_mode:
        print(f"All {len(JS_ORDER)} JS files verified!")
        return

    if not force and is_output_fresh():
        print(f"{OUTPUT_FILENAME} is up-to-date — no source changes detected. (use --force to rebuild)")
        return

    # Build concatenated (and optionally minified) file
    build(do_minify=not no_minify)


if __name__ == '__main__':
    main()
