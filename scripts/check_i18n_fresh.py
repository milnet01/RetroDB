#!/usr/bin/env python3
"""CI freshness gate for i18n (Pass 43.3). See docs/specs/i18n.md §6.

Fails when the committed manifest / catalog do not reflect current source:

 (a) regenerating ``services/js_i18n_strings.py`` would change ``JS_I18N_KEYS``
     (a t('...') literal was added/removed without rebuilding);
 (b) a fresh ``pybabel extract`` msgid set differs from the committed
     ``messages.pot`` (a wrapped string was not re-extracted);
 (c) any ``JS_I18N_KEYS`` entry is missing from ``messages.pot`` — the manifest
     and catalog have diverged, so window.I18N would silently fall back to
     English for that key.

All comparisons are over parsed *sets* — ``POT-Creation-Date`` and ``#:``
location comments churn on every run and are ignored.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# MUST stay byte-identical to the --ignore-dirs in the docs/specs/i18n.md §4
# extract command (and babel.cfg's comment), or this gate diffs against a
# differently-scoped messages.pot and red-lights spuriously. Babel's default
# directory filter skips '.'/'_'-prefixed dirs — without this override the
# templates/_modals, _settings_tabs, _macros partials are silently never
# extracted (the 43.5 bug this list fixes). The list REPLACES that default, so
# it must re-list the junk dirs to skip.
I18N_IGNORE_DIRS = '.* __pycache__ node_modules venv .venv env build dist staging tests'

from babel.messages.pofile import read_po  # noqa: E402
import build_js  # noqa: E402
from services.js_i18n_strings import JS_I18N_KEYS  # noqa: E402


def _pot_msgids(path):
    with open(path, 'rb') as f:
        catalog = read_po(f)
    return {message.id for message in catalog if message.id}


def main():
    failures = []

    # (a) JS manifest freshness — regenerated key set vs committed.
    fresh_keys = set(build_js.collect_js_i18n_keys(build_js.get_js_dir()))
    committed_keys = set(JS_I18N_KEYS)
    if fresh_keys != committed_keys:
        failures.append(
            'JS msgid manifest stale — run `python3 build_js.py`. '
            f'added={sorted(fresh_keys - committed_keys)} '
            f'removed={sorted(committed_keys - fresh_keys)}'
        )

    # (b) + (c) catalog freshness — fresh extract vs committed messages.pot.
    committed_pot = ROOT / 'messages.pot'
    if not committed_pot.exists():
        failures.append('messages.pot missing — run the docs/specs/i18n.md §4 extract.')
    else:
        with tempfile.TemporaryDirectory() as td:
            fresh_pot = Path(td) / 'fresh.pot'
            subprocess.run(
                ['pybabel', 'extract', '-F', 'babel.cfg',
                 '--ignore-dirs', I18N_IGNORE_DIRS,
                 '-o', str(fresh_pot), '.'],
                cwd=ROOT, check=True, capture_output=True,
            )
            fresh_ids = _pot_msgids(fresh_pot)
        committed_ids = _pot_msgids(committed_pot)

        if fresh_ids != committed_ids:
            failures.append(
                'messages.pot stale — run the §4 extract. '
                f'added={sorted(fresh_ids - committed_ids)[:10]} '
                f'removed={sorted(committed_ids - fresh_ids)[:10]}'
            )
        missing = committed_keys - committed_ids
        if missing:
            failures.append(f'JS msgids missing from messages.pot: {sorted(missing)}')

    if failures:
        print('i18n freshness gate FAILED:')
        for failure in failures:
            print('  -', failure)
        sys.exit(1)
    print('i18n freshness gate OK.')


if __name__ == '__main__':
    main()
