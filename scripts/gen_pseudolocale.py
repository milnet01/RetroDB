#!/usr/bin/env python3
"""Generate the pseudolocale catalog from messages.pot (Pass 43.1).

The pseudolocale is a permanent QA tool, not throwaway scaffolding:

* **Bracketing** (``⟦ … ⟧``) surfaces any *unwrapped* UI string — it renders
  as plain English with no brackets, so a missed ``{{ _() }}`` is visible at a
  glance.
* **Accenting** (``a`` -> ``à`` …) plus a length pad surfaces layout and
  truncation bugs that ASCII English hides.

The catalog is housed under the ``eo`` (Esperanto) CLDR code — see
``services/i18n.py::PSEUDO_LOCALE`` / INV-1 — but always labelled "Pseudo" in
the UI.

Workflow (run from the repo root, after wrapping new strings):

    pybabel extract -F babel.cfg -o messages.pot .
    python3 scripts/gen_pseudolocale.py
    pybabel compile -d translations

Both the generated ``.po`` and the compiled ``.mo`` are committed so the
source-zip and PyInstaller distributions need no build step on the user's
machine.
"""

import os
import sys

from babel.messages.pofile import read_po, write_po

# Import the resolved pseudolocale code from the single source of truth.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.i18n import PSEUDO_LOCALE  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POT_PATH = os.path.join(REPO_ROOT, 'messages.pot')
PO_PATH = os.path.join(
    REPO_ROOT, 'translations', PSEUDO_LOCALE, 'LC_MESSAGES', 'messages.po'
)

# Latin-1-ish accent map — enough to make every ASCII letter visibly altered
# while staying readable, so a tester can still recognise the English source.
_ACCENT = str.maketrans({
    'a': 'à', 'b': 'ƀ', 'c': 'ç', 'd': 'ð', 'e': 'é', 'f': 'ƒ', 'g': 'ĝ',
    'h': 'ĥ', 'i': 'ì', 'j': 'ĵ', 'k': 'ķ', 'l': 'ļ', 'm': 'ɱ', 'n': 'ñ',
    'o': 'ö', 'p': 'þ', 'q': 'ɋ', 'r': 'ŕ', 's': 'š', 't': 'ţ', 'u': 'ü',
    'v': 'ⱴ', 'w': 'ŵ', 'x': ' x', 'y': 'ý', 'z': 'ž',
    'A': 'À', 'B': 'Ɓ', 'C': 'Ç', 'D': 'Ð', 'E': 'É', 'F': 'Ƒ', 'G': 'Ĝ',
    'H': 'Ĥ', 'I': 'Ì', 'J': 'Ĵ', 'K': 'Ķ', 'L': 'Ļ', 'M': 'Ɱ', 'N': 'Ñ',
    'O': 'Ö', 'P': 'Þ', 'Q': 'Ɋ', 'R': 'Ŕ', 'S': 'Š', 'T': 'Ţ', 'U': 'Ü',
    'V': ' V', 'W': 'Ŵ', 'X': 'X', 'Y': 'Ý', 'Z': 'Ž',
})


def pseudo(text):
    """Bracket + accent a source string; leave gettext placeholders intact.

    ``%(name)s`` / ``%s`` / ``{name}`` substitutions must survive verbatim or
    the runtime format breaks, so only the surrounding literal text is accented.
    For the pilot's simple strings there are no placeholders, but the guard
    keeps the generator correct as more strings get wrapped.
    """
    import re
    parts = re.split(r'(%\([^)]*\)[a-z]|%[sd]|\{[^}]*\})', text)
    accented = ''.join(
        p if (p.startswith('%') or p.startswith('{')) else p.translate(_ACCENT)
        for p in parts
    )
    return f'⟦{accented}⟧'


def main():
    if not os.path.exists(POT_PATH):
        sys.exit(f'messages.pot not found at {POT_PATH} — run pybabel extract first.')

    with open(POT_PATH, 'rb') as f:
        catalog = read_po(f, locale=PSEUDO_LOCALE)

    # read_po() of a .pot template flags the catalog fuzzy; left set, `pybabel
    # compile` skips it and never writes the .mo. Every msgstr here is
    # machine-generated and complete, so clear the flag.
    catalog.fuzzy = False
    for message in catalog:
        if message.id:  # skip the header (empty id)
            message.string = pseudo(message.id)

    os.makedirs(os.path.dirname(PO_PATH), exist_ok=True)
    with open(PO_PATH, 'wb') as f:
        write_po(f, catalog, width=0)

    print(f'Wrote {sum(1 for m in catalog if m.id)} pseudolocalized messages to {PO_PATH}')
    print('Now run: pybabel compile -d translations')


if __name__ == '__main__':
    main()
