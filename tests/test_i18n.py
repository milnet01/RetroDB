"""Regression pins for the i18n foundation (Pass 43.1).

These are regression pins, not correctness proofs — they lock the observable
behaviour the foundation ships with: the locale-selection chain, the locale
validator, and the pilot (login.html) being fully wrapped under the
pseudolocale. The pseudolocale code is read from services.i18n.PSEUDO_LOCALE
(never hard-coded) so resolving INV-1 to a different code updates every test
automatically.
"""

import pytest
from bs4 import BeautifulSoup, Comment

import app as app_module
from services.i18n import available_locales, locale_display_name, PSEUDO_LOCALE

app = app_module.app

# The pseudolocale brackets every translated string (see scripts/gen_pseudolocale.py).
BRACKET = '⟦'


# ---------------------------------------------------------------------------
# available_locales() + display labels
# ---------------------------------------------------------------------------

def test_available_locales_enumerates_catalogs_plus_en():
    locales = available_locales()
    assert 'en' in locales                 # implicit source language
    assert PSEUDO_LOCALE in locales        # the one shipped catalog
    assert locales == sorted(locales)      # stable order


def test_pseudolocale_label_is_fixed_not_endonym():
    # eo's real endonym is "Esperanto"; the dropdown must hide that behind the
    # fixed "Pseudo" label so the QA locale never looks like a real language.
    assert locale_display_name(PSEUDO_LOCALE) == 'Pseudo'


def test_unparseable_locale_label_falls_back_to_code():
    assert locale_display_name('zz_NOPE') == 'zz_NOPE'


# ---------------------------------------------------------------------------
# Locale-selection chain: user pref > session > Accept-Language > 'en'
# ---------------------------------------------------------------------------

def _select(headers=None, user_settings=None, session_locale=None):
    """Invoke app.select_locale() inside a controlled request context."""
    from flask import g, session
    with app.test_request_context('/', headers=headers or {}):
        g.user_settings = user_settings
        if session_locale is not None:
            session['locale'] = session_locale
        return app_module.select_locale()


def test_selector_user_pref_beats_everything():
    assert _select(
        headers={'Accept-Language': 'en'},
        user_settings={'locale_preference': PSEUDO_LOCALE},
        session_locale='en',
    ) == PSEUDO_LOCALE


def test_selector_session_beats_accept_language():
    assert _select(
        headers={'Accept-Language': 'en'},
        user_settings=None,
        session_locale=PSEUDO_LOCALE,
    ) == PSEUDO_LOCALE


def test_selector_accept_language_when_no_pref_or_session():
    assert _select(
        headers={'Accept-Language': PSEUDO_LOCALE},
        user_settings=None,
    ) == PSEUDO_LOCALE


def test_selector_defaults_to_en():
    assert _select(headers={'Accept-Language': 'zz'}, user_settings=None) == 'en'


def test_selector_stale_locale_does_not_raise_falls_through():
    # A removed/unknown saved pref must be ignored (membership-guarded), not
    # raise; with no other signal it degrades to 'en'.
    assert _select(
        headers={'Accept-Language': 'zz'},
        user_settings={'locale_preference': 'qq_GONE'},
    ) == 'en'


# ---------------------------------------------------------------------------
# Locale validator on /api/users/settings (§4)
# ---------------------------------------------------------------------------

def _authed_client(monkeypatch, no_op_execute=True):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 1, 'username': 'admin', 'role': 'admin'})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})
    if no_op_execute:
        # Don't mutate the real user_settings row in a test.
        monkeypatch.setattr('routes.auth.execute', lambda *a, **k: None)
    client = app.test_client()
    csrf = 'test-csrf-token'
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['_csrf_token'] = csrf
    return client, {'X-CSRF-Token': csrf}


def test_validator_accepts_installed_locale(monkeypatch):
    client, headers = _authed_client(monkeypatch)
    resp = client.post('/api/users/settings',
                       json={'locale_preference': PSEUDO_LOCALE}, headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True


def test_validator_rejects_unknown_locale(monkeypatch):
    client, headers = _authed_client(monkeypatch)
    resp = client.post('/api/users/settings',
                       json={'locale_preference': 'qq_GONE'}, headers=headers)
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


# ---------------------------------------------------------------------------
# Pseudolocale render + coverage signal (§7)
# ---------------------------------------------------------------------------

def test_wrapped_string_pseudolocalized_unwrapped_control_stays_english():
    from flask_babel import gettext
    with app.test_request_context('/', headers={'Accept-Language': PSEUDO_LOCALE}):
        # A wrapped + extracted pilot string is bracketed.
        translated = gettext('Welcome to RetroDB')
        assert translated != 'Welcome to RetroDB'
        assert BRACKET in translated
        # A string that was never wrapped in source (so never extracted) stays
        # English — this is the coverage signal the pseudolocale provides.
        control = gettext('This sentence is deliberately never wrapped in source')
        assert control == 'This sentence is deliberately never wrapped in source'
        assert BRACKET not in control


# ---------------------------------------------------------------------------
# Pilot completeness scan (§6 acceptance criterion, §7)
# ---------------------------------------------------------------------------

def test_login_pilot_every_visible_string_pseudolocalized(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    # Render the empty-user-list branch so only static UI strings appear —
    # user-card data (role / username / display_name) is dynamic content, not
    # translatable UI, and would otherwise be an un-bracketed false positive.
    monkeypatch.setattr('routes.auth.query', lambda *a, **k: [])
    client = app.test_client()

    resp = client.get('/login', headers={'Accept-Language': PSEUDO_LOCALE})
    assert resp.status_code == 200

    soup = BeautifulSoup(resp.get_data(as_text=True), 'html.parser')
    # Scope to login.html's own content roots — the login card + the password
    # modal. base.html chrome that lives inside <main> (mobile-menu toggle,
    # skip-link, flash region, <title>) is out of the pilot's scope; only the
    # bulk migration (Pass 43.5) wraps it.
    roots = soup.select('.login-container, .password-modal')
    assert roots, 'login.html content roots not found'

    for root in roots:
        # The <script> block's JS strings are the Pass 43.3 boundary — English.
        for tag in root.find_all('script'):
            tag.decompose()

        # (a) Every visible text run containing letters must be bracketed.
        for node in root.find_all(string=True):
            if isinstance(node, Comment):
                continue
            text = node.strip()
            if text and any(ch.isalpha() for ch in text):
                assert BRACKET in text, f'unwrapped visible text: {text!r}'

        # (b) Every non-empty user-visible attribute value must be bracketed.
        for el in root.find_all(True):
            for attr in ('placeholder', 'title', 'aria-label'):
                val = el.get(attr)
                if val and val.strip():
                    assert BRACKET in val, f'unwrapped {attr}: {val!r}'
