"""Internationalization helpers (Pass 43.1 — i18n foundation).

Single source of truth for the set of installed locales and the pseudolocale
code. Deliberately import-light (only stdlib + ``config``) so it can be unit
tested without constructing the Flask app.

The pseudolocale (``PSEUDO_LOCALE``) is a permanent QA tool, not throwaway
scaffolding: its bracketed + accented strings surface any *unwrapped* UI string
(renders plain English) and any layout/truncation bug (padded length). See
``scripts/gen_pseudolocale.py`` and ``docs/specs/i18n.md``.
"""

import glob
import os

import config

# INV-1 (resolved at implementation 2026-06-12): the CLDR pseudo-locale
# ``en_XA`` is NOT parseable by Babel 2.18.0 (``Locale.parse('en_XA')`` raises
# UnknownLocaleError), which would break date/number formatting and
# display-name lookup. Per the design spec's decision tree we house the
# pseudolocale catalog under ``eo`` (Esperanto) — a real CLDR code Babel
# parses, which the project does not otherwise ship — while the Settings
# dropdown always labels it the fixed string "Pseudo" (see
# templates/_settings_tabs/library.html).
PSEUDO_LOCALE = 'eo'

# Absolute path to the committed catalog tree. Rooted at BUNDLE_DIR (read-only
# bundled assets), mirroring config.STATIC_PATH, so the path resolves
# identically in a source checkout and a frozen PyInstaller bundle — more
# robust than a root_path-relative 'translations' string under PyInstaller.
TRANSLATIONS_DIR = os.path.join(config.BUNDLE_DIR, 'translations')


def available_locales():
    """Return sorted locale codes for every compiled catalog plus implicit 'en'.

    Enumerates ``translations/<code>/LC_MESSAGES/messages.mo``. 'en' is the
    source language and needs no catalog. Used by the locale selector, the
    ``/api/users/settings`` validation, and the Settings dropdown so the three
    can never drift.
    """
    locales = {'en'}
    pattern = os.path.join(TRANSLATIONS_DIR, '*', 'LC_MESSAGES', 'messages.mo')
    for mo_path in glob.glob(pattern):
        # .../translations/<code>/LC_MESSAGES/messages.mo -> <code>
        code = os.path.basename(os.path.dirname(os.path.dirname(mo_path)))
        locales.add(code)
    return sorted(locales)


def locale_display_name(code):
    """Human-facing label for a locale code, for the Settings dropdown.

    The pseudolocale always shows the fixed label "Pseudo" (special-cased
    before the parse so its real ``eo`` endonym "Esperanto" never surfaces).
    Otherwise the endonym (the language's own name) via Babel; an unparseable
    code falls back to the raw string.
    """
    if code == PSEUDO_LOCALE:
        return 'Pseudo'
    try:
        from babel import Locale
        return Locale.parse(code).get_display_name(code) or code
    except Exception:
        return code
