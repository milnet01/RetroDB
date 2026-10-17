"""The anti-piracy disclaimer shows in the About dialog and on the ROM path card.

The wording is the one the antsprojectshub.co.za site and the trailer carry
(requested 2026-10-16). It is one msgid, so every locale translates it whole;
the pseudolocale check proves it is wrapped for i18n in both places.
"""

from bs4 import BeautifulSoup
from flask import render_template

import app as app_module
from services.i18n import PSEUDO_LOCALE

app = app_module.app

DISCLAIMER = (
    "We do not condone piracy. RetroDB does not distribute or host ROM files. "
    "Only use games you own, copied from your own discs and cartridges; the law "
    "on making such copies differs from country to country, so check yours. "
    "Game names, cover art, screenshots and videos belong to their owners. "
    "RetroDB is not affiliated with or endorsed by any console maker, game "
    "publisher, or the game databases and services it works with."
)


def _about_disclaimer(client, headers=None):
    resp = client.get('/login', headers=headers or {})
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.get_data(as_text=True), 'html.parser')
    modal = soup.select_one('#aboutModalOverlay')
    assert modal is not None, 'About dialog not rendered'
    node = modal.select_one('.legal-disclaimer')
    assert node is not None, 'About dialog has no disclaimer'
    return node.get_text(' ', strip=True)


def _library_disclaimer(locale):
    with app.test_request_context('/', headers={'Accept-Language': locale}):
        html = render_template('_settings_tabs/library.html')
    card = BeautifulSoup(html, 'html.parser').select_one('section#library')
    node = card.select_one('.legal-disclaimer')
    assert node is not None, 'ROM path card has no disclaimer'
    return node.get_text(' ', strip=True)


def test_about_dialog_shows_disclaimer(app_client, setup_complete, monkeypatch):
    monkeypatch.setattr('routes.auth.query', lambda *a, **k: [])
    assert DISCLAIMER in _about_disclaimer(app_client)


def test_about_dialog_disclaimer_is_translated(app_client, setup_complete, monkeypatch):
    monkeypatch.setattr('routes.auth.query', lambda *a, **k: [])
    text = _about_disclaimer(app_client, {'Accept-Language': PSEUDO_LOCALE})
    assert '⟦' in text and DISCLAIMER not in text


def test_about_dialog_is_not_inside_the_sidebar(app_client, setup_complete, monkeypatch):
    # The sidebar <nav> has a backdrop-filter, which makes it the containing
    # block for a position:fixed child: inside it, the overlay was clipped to
    # the sidebar's width instead of covering the window.
    monkeypatch.setattr('routes.auth.query', lambda *a, **k: [])
    soup = BeautifulSoup(app_client.get('/login').get_data(as_text=True), 'html.parser')
    assert soup.select_one('#aboutModalOverlay').find_parent('nav') is None


def test_rom_path_card_shows_disclaimer():
    assert DISCLAIMER in _library_disclaimer('en')


def test_rom_path_card_disclaimer_is_translated():
    text = _library_disclaimer(PSEUDO_LOCALE)
    assert '⟦' in text and DISCLAIMER not in text
