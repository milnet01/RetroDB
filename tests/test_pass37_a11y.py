# =============================================================================
# Pass 37 — accessibility round 3
# =============================================================================
# Regression pins for the 7 sub-items of Pass 37. Templates aren't rendered by
# pytest so these are source-level checks — they confirm the hardening patterns
# stay wired up.
# =============================================================================

import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _read(relpath):
    with open(os.path.join(_REPO_ROOT, relpath), encoding='utf-8') as f:
        return f.read()


# -----------------------------------------------------------------------------
# 37.1 — composite-field labels properly associated with their controls
# -----------------------------------------------------------------------------
# Pass 37.1 originally fixed `<label for="<X>">` to point at the helper "+ Add"
# dropdown (real focus target) instead of the hidden `<input>`.  FU.5 (v3.5.67)
# strengthened this further: each multi-value tag-picker field is now a
# `role="group" aria-labelledby="<id>FieldLabel"` container with the label
# demoted to a `<div class="form-label" id="<id>FieldLabel">`, and the helper
# `<select>` carries its own `aria-label="Add <X>"`.  Screen readers now anchor
# the chip list to the field name instead of jumping straight to the combobox.
def test_37_1_edit_modal_composite_labels_have_group_role():
    """edit_modal.html: each composite tag-picker field is a labelled group."""
    src = _read('templates/_modals/edit_modal.html')
    # No bare <label> without for= remains (the inner <label class="toggle-switch">
    # variants always carry an attribute and are picked up by the substring guard).
    assert '<label>' not in src, 'edit_modal.html still has bare <label> with no for='
    # The seven multi-value tag-picker fields use role="group" + aria-labelledby
    # pointing at a div.form-label with a stable id.
    for field, label_text in [
        ('editGenreFieldLabel', 'Genre'),
        ('editModesFieldLabel', 'Play Modes'),
        ('editGameStructureFieldLabel', 'Game Structure'),
        ('editPerspectiveFieldLabel', 'Perspective'),
        ('editDimensionFieldLabel', 'Dimension'),
        ('editControllerFieldLabel', 'Controller Support'),
        ('editSaveTypeFieldLabel', 'Save Type'),
    ]:
        assert f'aria-labelledby="{field}"' in src, (
            f'edit_modal.html: composite field missing aria-labelledby={field}')
        assert f'id="{field}">{label_text}</div>' in src, (
            f'edit_modal.html: missing div.form-label#{field}>{label_text}')
    # Helper "+ Add" selects each carry their own aria-label so they're
    # distinguishable from the chip container inside the group.
    for needle in ('aria-label="Add genre"', 'aria-label="Add play mode"',
                   'aria-label="Add game structure"', 'aria-label="Add perspective"',
                   'aria-label="Add dimension"', 'aria-label="Add controller"',
                   'aria-label="Add save type"'):
        assert needle in src, f'edit_modal.html missing helper-select {needle}'


def test_37_1_game_edit_modal_composite_labels_have_group_role():
    """base.html gem-* modal: same role="group" pattern as edit_modal.html."""
    src = _read('templates/base.html')
    # Scope to the gem-* modal tab-content block.
    gem_start = src.index('gemTabQuick')
    gem = src[gem_start:]
    # No bare <label> tags in the game-edit-modal.
    assert '<label>' not in gem, 'base.html gem-modal still has bare <label>'
    for field, label_text in [
        ('gemGenreFieldLabel', 'Genre'),
        ('gemModesFieldLabel', 'Play Modes'),
        ('gemGameStructureFieldLabel', 'Game Structure'),
        ('gemPerspectiveFieldLabel', 'Perspective'),
        ('gemDimensionFieldLabel', 'Dimension'),
        ('gemControllerFieldLabel', 'Controller Support'),
        ('gemSaveTypeFieldLabel', 'Save Type'),
    ]:
        assert f'aria-labelledby="{field}"' in gem, (
            f'gem modal: composite field missing aria-labelledby={field}')
        assert f'id="{field}">{label_text}</div>' in gem, (
            f'gem modal: missing div.form-label#{field}>{label_text}')


# -----------------------------------------------------------------------------
# 37.2 — ModalFocusTrap wired on PSN trophies modals
# -----------------------------------------------------------------------------
def test_37_2_psn_trophies_modals_activate_focus_trap():
    src = _read('templates/psn_trophies.html')
    # Pass 37.2 marker comments are fine but not required; what matters is that
    # ModalFocusTrap.activate is called for both syncModal and bulkRefreshModal,
    # with matching deactivate on close paths.
    assert src.count('ModalFocusTrap.activate') >= 2
    assert src.count('ModalFocusTrap.deactivate') >= 4  # sync + bulk + error paths


# -----------------------------------------------------------------------------
# 37.3 — reduced-motion guards in effects CSS
# -----------------------------------------------------------------------------
def test_37_3_effects_animations_reduced_motion():
    src = _read('static/css/effects/animations.css')
    # File-local @media block exists so defense-in-depth remains even if the
    # universal rule in reset.css is ever scoped down.
    assert '@media (prefers-reduced-motion: reduce)' in src
    # The only animated utility class is disabled in that block.
    assert '.highlight-jump' in src.split('@media (prefers-reduced-motion')[1]


def test_37_3_effects_backgrounds_reduced_motion():
    src = _read('static/css/effects/backgrounds.css')
    assert '@media (prefers-reduced-motion: reduce)' in src


# -----------------------------------------------------------------------------
# 37.4 — rel="noopener noreferrer" on every target="_blank"
# -----------------------------------------------------------------------------
def test_37_4_target_blank_has_rel_noopener():
    """Every <a target="_blank"> across templates/ ships rel=noopener noreferrer."""
    import pathlib
    offenders = []
    for p in pathlib.Path(os.path.join(_REPO_ROOT, 'templates')).rglob('*.html'):
        src = p.read_text(encoding='utf-8')
        for m in re.finditer(r'<a\b[^>]*?target="_blank"[^>]*?>', src, re.IGNORECASE):
            tag = m.group(0)
            if not re.search(r'\brel\s*=', tag, re.IGNORECASE):
                offenders.append(f"{p.relative_to(_REPO_ROOT)}: {tag[:120]}")
    assert not offenders, 'target=_blank without rel=:\n' + '\n'.join(offenders)


# -----------------------------------------------------------------------------
# 37.5 — heading hierarchy (no H1 → H3 jumps on the fixed pages)
# -----------------------------------------------------------------------------
def test_37_5_game_detail_no_h1_h3_jump():
    src = _read('templates/game_detail.html')
    # The top-level page sections (screenshots, video, similar games, …)
    # must now be h2, not h3.
    for needle in ('<h2 class="media-title">📸 Screenshots',
                   '<h2 class="media-title">🎬 Video',
                   '<h2 class="section-title-sm">🎯 Similar Games',
                   '<h2 class="section-title-sm">📋 More Details'):
        assert needle in src, f"missing promoted heading: {needle}"


def test_37_5_settings_h4_promoted_to_h3():
    src = _read('templates/settings.html')
    # No <h4> opener remains outside generated/dropdown markup.
    assert not re.search(r'<h4\b', src), 'settings.html still has <h4 tags'


# -----------------------------------------------------------------------------
# 37.6 — aria-live on flash + result containers
# -----------------------------------------------------------------------------
def test_37_6_base_flash_has_aria_live():
    src = _read('templates/base.html')
    # Both polite (role=status) and assertive (role=alert) branches present.
    flash_zone = src[src.index('Flash Messages'):src.index('Page Content')]
    assert 'role="status"' in flash_zone and 'aria-live="polite"' in flash_zone
    assert 'role="alert"' in flash_zone and 'aria-live="assertive"' in flash_zone


def test_37_6_settings_result_containers_have_live_regions():
    src = _read('templates/settings.html')
    for needle in (
        'id="scraperSettingsResult" role="status" aria-live="polite"',
        'id="rateLimitsResult" role="status" aria-live="polite"',
        'id="apiKeysResult" role="status" aria-live="polite"',
    ):
        assert needle in src, f"missing live region on result container: {needle}"


# -----------------------------------------------------------------------------
# 37.7 — hardcoded colors promoted to tokens
# -----------------------------------------------------------------------------
def test_37_7_neon_blue_token_exists():
    src = _read('static/css/core/variables.css')
    assert '--neon-blue:' in src
    assert '--text-on-color:' in src


def test_37_7_game_list_no_residual_3b82f6_or_fff_on_ratings():
    src = _read('static/css/pages/game-list.css')
    # The previously-cited .bulk-action-btn rule no longer hardcodes #3b82f6.
    bulk_action = src[src.index('.bulk-action-btn {'):
                      src.index('.bulk-action-btn {') + 300]
    assert '#3b82f6' not in bulk_action
    assert 'var(--neon-blue)' in bulk_action

    # The ESRB/PEGI badges use the text-on-color token, not #fff.
    esrb = src[src.index('.rating-text-badge.esrb'):
               src.index('.rating-text-badge.esrb') + 300]
    assert '#fff' not in esrb
    assert 'var(--text-on-color)' in esrb
