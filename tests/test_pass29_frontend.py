# =============================================================================
# Pass 29 — frontend defense in depth
# =============================================================================
# JS code can't be executed from pytest, but regression pins ensure the
# hardening patterns stay wired up (import contracts, expected strings in
# the rendered base template, no reintroduction of bare innerHTML patterns).
# =============================================================================

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_JS_DIR = os.path.join(_REPO_ROOT, 'static', 'js')


def _read(path):
    with open(os.path.join(_JS_DIR, path), encoding='utf-8') as f:
        return f.read()


def test_29_2_csrf_shim_present_in_base_template():
    """Pass 29.2 — the fetch CSRF shim lives in templates/base.html.
    Confirm it's still there so API.post / API.postForm (which use global
    fetch) continue to auto-attach X-CSRF-Token on every non-GET.
    """
    base_html = os.path.join(_REPO_ROOT, 'templates', 'base.html')
    with open(base_html, encoding='utf-8') as f:
        src = f.read()
    assert 'window.fetch = function' in src
    assert 'X-CSRF-Token' in src
    assert "meta[name=\"csrf-token\"]" in src


def test_29_4_safeParseJSON_defined_and_exposed():
    """Pass 29.4 — helper exists and is on window for cross-bundle use."""
    utils = _read('utils.js')
    assert 'function safeParseJSON' in utils
    assert 'window.safeParseJSON = safeParseJSON' in utils


def test_29_4_no_unguarded_localstorage_json_parse_in_audited_files():
    """Pass 29.4 — audited call sites replaced with safeParseJSON.

    The audit named 13 sites across four files. Any remaining
    `JSON.parse(localStorage.getItem(...` invocation in those files
    without a surrounding try/catch is a regression.
    """
    for fname in ('toast-controller.js', 'main.js', 'game-list.js', 'achievements.js'):
        src = _read(fname)
        # No direct JSON.parse(localStorage.getItem(...)) left.
        assert 'JSON.parse(localStorage.getItem(' not in src, (
            f"{fname} still has an unguarded JSON.parse(localStorage.getItem(...))"
        )


def test_29_1_confirmmodal_defaults_to_textcontent():
    """Pass 29.1 — settings-page.js ConfirmModal now uses textContent
    unless callers opt into HTML via options.allowHtml.
    """
    src = _read('settings-page.js')
    # Both entry points (show, showInfo) gained the allowHtml branch.
    assert src.count('options.allowHtml') >= 2
    assert 'messageEl.textContent = message' in src


def test_29_1_trophies_render_escapes_icon_url():
    """Pass 29.1 — trophies.js renderCard now wraps trophy.icon_url in
    escapeHtml before interpolating into the <img src="..."> attribute.
    """
    src = _read('trophies.js')
    assert 'iconUrlSafe = trophy.icon_url ? escapeHtml(trophy.icon_url)' in src


def test_29_1_achievements_render_escapes_badge_url():
    src = _read('achievements.js')
    assert 'badgeUrlSafe = achievement.badge_url ? escapeHtml(achievement.badge_url)' in src


def test_29_3_filter_modal_uses_ModalFocusTrap():
    """Pass 29.3 — the filter modal's standalone document keydown listener
    was removed in favor of ModalFocusTrap's stacked onEscape callback.
    """
    src = _read('all-games-controller.js')
    assert 'ModalFocusTrap.activate(modal' in src
    assert '_filterModalTrapActive' in src
    # No standalone _onFilterKeydown registered directly on document any more.
    assert "document.addEventListener('keydown', _onFilterKeydown)" not in src


def test_29_3_lightbox_activates_focus_trap():
    """Pass 29.3 — GameDetailModal.openLightbox pushes a ModalFocusTrap
    on top of the detail-modal trap so Escape closes the lightbox first.
    """
    src = _read('game-modals.js')
    assert 'ModalFocusTrap.activate(lb' in src
    # Old monolithic Escape handler replaced with arrow-only handler.
    assert "if (e.key === 'Escape') {" not in src.split('document.addEventListener(\'keydown\', function(e) {\n    const lightbox')[1].split('\n});')[0]


def test_29_5_global_search_uses_abort_controller():
    """Pass 29.5 — performGlobalSearch aborts any in-flight request before
    issuing a new one, and silently ignores AbortError on the stale promise.
    """
    src = _read('main.js')
    assert '_globalSearchController = null' in src
    assert '_globalSearchController.abort()' in src
    assert "error.name === 'AbortError'" in src
