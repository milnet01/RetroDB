#!/usr/bin/env python3
"""Fill a locale's .po catalog from a JSON {msgid: translation} mapping.

Locale-bootstrapping helper for adding a new language (Pass 56). ``pybabel
init`` creates an empty catalog with every msgid present and every msgstr
blank; this script pours the translations in *safely* — via Babel's own PO
reader/writer, so the file format, header, and Plural-Forms are never
hand-mangled — and refuses to pass silently on an incomplete or
placeholder-breaking translation.

Usage:
    python3 scripts/apply_po_translations.py <locale> <translations.json> [more.json ...]

Multiple JSON files are merged in order (later keys win), so a translation may
be produced in several safe-sized chunk files and applied in one call.

Each JSON maps each **singular** msgid to its translation:
  - regular entry  -> "translated string"
  - plural entry   -> ["form 0", "form 1", ...]  (a list, one per plural form)

Exit status is 0 only when every non-header msgid is covered and every
placeholder (``%(name)s``, ``%d``, ``%s``, ``{name}``) in the source survives
in the translation. Anything missing or broken is reported and the exit code
is non-zero, so a translation agent cannot half-finish without noticing. The
catalog is still written (partial progress is kept); the non-zero exit is the
signal to fix and re-run.
"""

import json
import os
import re
import sys

from babel.messages.pofile import read_po, write_po

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# gettext-named %(x)s / %(x)d, bare printf %s %d %i %f, and brace {name}.
_PLACEHOLDER_RE = re.compile(r'%\([^)]+\)[sdifgx]|%[sdifgx]|\{[a-zA-Z0-9_]+\}')


def _placeholders(text):
    return sorted(_PLACEHOLDER_RE.findall(text or ''))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    locale, json_paths = sys.argv[1], sys.argv[2:]
    po_path = os.path.join(_REPO_ROOT, 'translations', locale, 'LC_MESSAGES', 'messages.po')

    with open(po_path, 'rb') as f:
        catalog = read_po(f)
    translations = {}
    for jp in json_paths:
        with open(jp, encoding='utf-8') as f:
            translations.update(json.load(f))

    nplurals = catalog.num_plurals
    total = missing = filled = 0
    missing_ids, ph_bad, empty_forms = [], [], []

    for msg in catalog:
        if not msg.id:  # the header (id == '')
            continue
        total += 1
        key = msg.id[0] if isinstance(msg.id, (list, tuple)) else msg.id
        if key not in translations or translations[key] in (None, '', []):
            missing += 1
            missing_ids.append(key)
            continue
        value = translations[key]

        if isinstance(msg.id, (list, tuple)):  # plural entry
            forms = value if isinstance(value, list) else [value]
            # Pad to nplurals by repeating the last supplied form.
            forms = [forms[min(i, len(forms) - 1)] for i in range(nplurals)]
            if any(not f for f in forms):
                empty_forms.append(key)
            msg.string = tuple(forms)
            src_ph = _placeholders(msg.id[0]) or _placeholders(msg.id[1])
            for f in forms:
                if set(src_ph) - set(_placeholders(f)):
                    ph_bad.append((key, f))
                    break
        else:
            msg.string = value
            if set(_placeholders(msg.id)) - set(_placeholders(value)):
                ph_bad.append((key, value))
        filled += 1

    with open(po_path, 'wb') as f:
        write_po(f, catalog, width=76)

    print(f'[{locale}] {filled}/{total} filled, {missing} missing, '
          f'{len(ph_bad)} placeholder-mismatch, {len(empty_forms)} empty-plural-form')
    if missing_ids:
        print('  MISSING (first 20):')
        for m in missing_ids[:20]:
            print(f'    - {m!r}')
    if ph_bad:
        print('  PLACEHOLDER MISMATCH (first 20):')
        for k, v in ph_bad[:20]:
            print(f'    - {k!r}\n        -> {v!r}')

    sys.exit(1 if (missing or ph_bad or empty_forms) else 0)


if __name__ == '__main__':
    main()
