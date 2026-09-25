# =============================================================================
# Pass 29 — frontend defense in depth
# =============================================================================
# JS code can't be executed from pytest, but regression pins ensure the
# hardening patterns stay wired up (import contracts, expected strings in
# the rendered base template, no reintroduction of bare innerHTML patterns).
# =============================================================================

import os

from tests._util import read_source


def _read_js(name):
    """Read a JS file under static/js/. Thin wrapper over the shared helper."""
    return read_source(os.path.join('static', 'js', name))


def test_29_2_csrf_shim_present_in_base_template():
    """Pass 29.2 — the fetch CSRF shim lives in templates/base.html.
    Confirm it's still there so API.post / API.postForm (which use global
    fetch) continue to auto-attach X-CSRF-Token on every non-GET.
    """
    src = read_source(os.path.join('templates', 'base.html'))
    assert 'window.fetch = function' in src
    assert 'X-CSRF-Token' in src
    assert "meta[name=\"csrf-token\"]" in src


def test_29_4_safeParseJSON_defined_and_exposed():
    """Pass 29.4 — helper exists and is on window for cross-bundle use."""
    utils = _read_js('utils.js')
    assert 'function safeParseJSON' in utils
    assert 'window.safeParseJSON = safeParseJSON' in utils


def test_29_4_no_unguarded_localstorage_json_parse_in_audited_files():
    """Pass 29.4 — audited call sites replaced with safeParseJSON.

    The audit named 13 sites across four files. Any remaining
    `JSON.parse(localStorage.getItem(...` invocation in those files
    without a surrounding try/catch is a regression.
    """
    for fname in ('toast-controller.js', 'main.js', 'game-list.js', 'achievements.js'):
        src = _read_js(fname)
        # No direct JSON.parse(localStorage.getItem(...)) left.
        assert 'JSON.parse(localStorage.getItem(' not in src, (
            f"{fname} still has an unguarded JSON.parse(localStorage.getItem(...))"
        )


# test_29_1_confirmmodal_defaults_to_textcontent retired (Pass 59.35): the
# ConfirmModal in settings-page.js was shadowed by settings.html's inline
# showConfirmModal and never ran, so it was deleted. The live dialog's
# textContent default is pinned in tests/test_pass45_security.py.


def test_29_1_trophies_render_escapes_icon_url():
    """Pass 29.1 — trophies.js renderCard now wraps trophy.icon_url in
    escapeHtml before interpolating into the <img src="..."> attribute.
    """
    src = _read_js('trophies.js')
    assert 'iconUrlSafe = trophy.icon_url ? escapeHtml(trophy.icon_url)' in src


def test_29_1_achievements_render_escapes_badge_url():
    """Pass 29.1 — achievements.js renderCard escapes badge_url before
    img src interpolation."""
    src = _read_js('achievements.js')
    assert 'badgeUrlSafe = achievement.badge_url ? escapeHtml(achievement.badge_url)' in src


def test_29_3_filter_modal_uses_ModalFocusTrap():
    """Pass 29.3 — the filter modal's standalone document keydown listener
    was removed in favor of ModalFocusTrap's stacked onEscape callback.
    """
    src = _read_js('all-games-controller.js')
    assert 'ModalFocusTrap.activate(modal' in src
    assert '_filterModalTrapActive' in src
    # No standalone _onFilterKeydown registered directly on document any more.
    assert "document.addEventListener('keydown', _onFilterKeydown)" not in src
    # ...and no dangling removeEventListener referencing the deleted symbol —
    # destroy() runs on beforeunload, so an orphan reference throws
    # "ReferenceError: _onFilterKeydown is not defined" on every navigation.
    assert '_onFilterKeydown' not in src


def test_29_3_lightbox_activates_focus_trap():
    """Pass 29.3 — GameDetailModal.openLightbox pushes a ModalFocusTrap
    on top of the detail-modal trap so Escape closes the lightbox first.
    Pass 36.8 further removed the standalone arrow-only keydown handler;
    arrows now route via ModalFocusTrap's onArrowLeft / onArrowRight.
    """
    src = _read_js('game-modals.js')
    assert 'ModalFocusTrap.activate(lb' in src
    # Pass 36.8 removal: no document-level keydown handler should remain
    # on the lightbox path; arrow callbacks are wired via the trap.
    assert "document.addEventListener('keydown'" not in src
    assert 'onArrowLeft' in src
    assert 'onArrowRight' in src


# test_29_5_global_search_uses_abort_controller retired (Pass 59.39):
# performGlobalSearch called a route that does not exist, keyed on an element
# no template renders, and had no caller, so it was deleted.
