"""PASS-53-1 — the sidebar's global search on every signed-in page.

Pins the wiring the browser walk relies on: the combobox markup in
base.html, its script in the core bundle (loaded on every page), and the
Library reading the ?q= that "See all results" sends.
"""
from tests._util import read_source


def test_signed_in_page_renders_the_search_combobox(admin_test_client):
    client, _csrf = admin_test_client()
    html = client.get('/help').get_data(as_text=True)
    assert 'id="globalSearch"' in html
    assert 'role="combobox"' in html
    assert 'aria-controls="globalSearchList"' in html
    assert 'id="globalSearchList"' in html and 'role="listbox"' in html


def test_search_script_is_in_the_core_bundle():
    build = read_source('build_js.py')
    core = build[build.index('CORE_ORDER = ['):]
    core = core[:core.index(']')]
    assert "'global-search.js'" in core
    assert 'globalSearch' in read_source('static/js/core.bundle.js')


def test_library_reads_q_from_the_address():
    src = read_source('static/js/all-games-controller.js')
    assert ".get('q')" in src


def test_slash_shortcut_falls_back_to_the_global_search():
    src = read_source('static/js/main.js')
    body = src[src.index('function focusSearch()'):]
    body = body[:body.index('\n}\n')]
    assert ":not(#globalSearch)" in body
    assert "getElementById('globalSearch')" in body
