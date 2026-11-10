"""The handler names a page may call through `data-on-<event>` (PASS-59-276).

`main.js` runs `data-on-click="fn"` by looking `fn` up on `window`. Without a
list, HTML injected anywhere could name any reachable function (`API.post`,
`location.assign`) and fire it on a click or a hover, past the CSP. So
`base.html` hands the page the names the source actually writes, and
`main.js` refuses every other name.

The list is read from the templates and the hand-written JS on demand, and
read again when any of those files changes, so a new handler needs no build
step. `tests/test_fu1_csp.py` reads names with the same patterns.
"""

import os
import re

# `data-on-click="fn"`, and a modal's `data-focus-trap-onescape="fn"`, which
# main.js looks up the same way. `data-on-error` takes fixed actions, not names.
ACTION_RE = re.compile(r'(?:data-on-(?!error\b)[a-z]+|data-focus-trap-onescape)'
                       r'="([A-Za-z_$][\w$.]*)"')
# A script that sets the attribute: setAttribute('data-on-click', 'fn').
SET_ATTRIBUTE_RE = re.compile(
    r'''setAttribute\(\s*['"]data-on-[a-z]+['"]\s*,\s*['"]([A-Za-z_$][\w$.]*)['"]''')

_cache = {'key': None, 'names': ()}


def source_files(template_dir, js_dir):
    """Every template, and every hand-written JS file (bundles are built from them)."""
    paths = []
    for root, _dirs, files in os.walk(template_dir):
        paths.extend(os.path.join(root, f) for f in files if f.endswith('.html'))
    if os.path.isdir(js_dir):
        paths.extend(os.path.join(js_dir, f) for f in os.listdir(js_dir)
                     if f.endswith('.js') and not f.endswith(('.bundle.js', '.min.js')))
    return sorted(paths)


def names_in(text):
    """The handler names one file's text writes."""
    return set(ACTION_RE.findall(text)) | set(SET_ATTRIBUTE_RE.findall(text))


def action_names(template_dir, js_dir):
    """Sorted handler names across the source; re-read only when a file changes."""
    paths = source_files(template_dir, js_dir)
    key = tuple((p, os.stat(p).st_mtime_ns) for p in paths)
    if key != _cache['key']:
        names = set()
        for p in paths:
            with open(p, encoding='utf-8') as f:
                names |= names_in(f.read())
        _cache.update(key=key, names=tuple(sorted(names)))
    return list(_cache['names'])
