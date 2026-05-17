# =============================================================================
# Pass 37 — accessibility round 3
# =============================================================================
# Regression pins for the 7 sub-items of Pass 37. Templates aren't rendered by
# pytest so these are source-level checks — they confirm the hardening patterns
# stay wired up.
# =============================================================================

import os
import pathlib
import re

import pytest

# REPO_ROOT/sys.path setup is centralised in tests/_util.py (test-audit DUP-1).
from tests._util import REPO_ROOT, read_source


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

# The seven multi-value tag-picker fields (shared by both templates that
# render this UI). Parametrised so each (template, field) failure shows up
# as an independent pytest node (test-audit VERB-1).
_COMPOSITE_FIELDS = (
    ('Genre', 'Genre'),
    ('Modes', 'Play Modes'),
    ('GameStructure', 'Game Structure'),
    ('Perspective', 'Perspective'),
    ('Dimension', 'Dimension'),
    ('Controller', 'Controller Support'),
    ('SaveType', 'Save Type'),
)


def _composite_id_pairs(prefix):
    """Return list of (field_id, label_text) for the given DOM-id prefix."""
    return [(f'{prefix}{name}FieldLabel', label) for name, label in _COMPOSITE_FIELDS]


@pytest.mark.parametrize(
    'template_rel,prefix,scope_marker',
    [
        ('templates/_modals/edit_modal.html', 'edit', None),
        # base.html's gem-* modal is one of several blocks in a large file;
        # scope to the gem-* tab-content section.
        ('templates/base.html', 'gem', 'gemTabQuick'),
    ],
)
def test_37_1_composite_labels_have_group_role(template_rel, prefix, scope_marker):
    """Each composite tag-picker field is a labelled group across both
    templates that render this UI (test-audit VERB-1)."""
    src = read_source(template_rel)
    scoped = src[src.index(scope_marker):] if scope_marker else src

    # No bare <label> without an attribute in the scoped section.
    label_kind = 'gem-modal' if scope_marker else 'edit_modal'
    assert '<label>' not in scoped, (
        f'{label_kind}: still has bare <label> with no attribute'
    )

    for field_id, label_text in _composite_id_pairs(prefix):
        assert f'aria-labelledby="{field_id}"' in scoped, (
            f'{label_kind}: composite field missing aria-labelledby={field_id}'
        )
        assert f'id="{field_id}">{label_text}</div>' in scoped, (
            f'{label_kind}: missing div.form-label#{field_id}>{label_text}'
        )


def test_37_1_edit_modal_helper_selects_have_aria_labels():
    """Helper "+ Add" selects carry their own aria-label so they're
    distinguishable from the chip container inside the group. Only
    edit_modal.html — the gem-modal helper-select markup uses a
    different pattern (covered by its own aria-labelledby chain)."""
    src = read_source('templates/_modals/edit_modal.html')
    for needle in (
        'aria-label="Add genre"',
        'aria-label="Add play mode"',
        'aria-label="Add game structure"',
        'aria-label="Add perspective"',
        'aria-label="Add dimension"',
        'aria-label="Add controller"',
        'aria-label="Add save type"',
    ):
        assert needle in src, f'edit_modal.html missing helper-select {needle}'


# -----------------------------------------------------------------------------
# 37.2 — ModalFocusTrap wired on PSN trophies modals
# -----------------------------------------------------------------------------
def test_37_2_psn_trophies_modals_activate_focus_trap():
    src = read_source('templates/psn_trophies.html')
    # Pass 37.2 marker comments are fine but not required; what matters is that
    # ModalFocusTrap.activate is called for both syncModal and bulkRefreshModal,
    # with matching deactivate on close paths. Lower bound was `>= 4` for
    # deactivate; actual count grew to 7 (sync + bulk + error + open/close paths).
    # Tighten to a balanced equality check — any drop in deactivate calls is now
    # caught instead of silently degrading the focus-trap teardown coverage.
    assert src.count('ModalFocusTrap.activate') == 2, (
        f"Expected 2 ModalFocusTrap.activate calls (sync+bulk); "
        f"got {src.count('ModalFocusTrap.activate')}"
    )
    assert src.count('ModalFocusTrap.deactivate') == 7, (
        f"Expected 7 ModalFocusTrap.deactivate calls "
        f"(sync open/close+esc, bulk open/close+esc, error path); "
        f"got {src.count('ModalFocusTrap.deactivate')}"
    )


# -----------------------------------------------------------------------------
# 37.3 — reduced-motion guards in effects CSS
# -----------------------------------------------------------------------------
def test_37_3_effects_animations_reduced_motion():
    src = read_source('static/css/effects/animations.css')
    # File-local @media block exists so defense-in-depth remains even if the
    # universal rule in reset.css is ever scoped down.
    assert '@media (prefers-reduced-motion: reduce)' in src
    # The only animated utility class is disabled in that block.
    assert '.highlight-jump' in src.split('@media (prefers-reduced-motion')[1]


def test_37_3_effects_backgrounds_reduced_motion():
    src = read_source('static/css/effects/backgrounds.css')
    assert '@media (prefers-reduced-motion: reduce)' in src


# -----------------------------------------------------------------------------
# 37.4 — rel="noopener noreferrer" on every target="_blank"
# -----------------------------------------------------------------------------
def test_37_4_target_blank_has_rel_noopener():
    """Every <a target="_blank"> across templates/ ships rel=noopener noreferrer.

    Earlier version only checked that *some* `rel=` was present, which would
    have happily accepted `rel="nofollow"` and still leak window.opener. The
    docstring claims "noopener noreferrer" — assert it."""
    offenders = []
    for p in pathlib.Path(os.path.join(REPO_ROOT, 'templates')).rglob('*.html'):
        src = p.read_text(encoding='utf-8')
        for m in re.finditer(r'<a\b[^>]*?target="_blank"[^>]*?>', src, re.IGNORECASE):
            tag = m.group(0)
            rel_match = re.search(r'\brel\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if rel_match is None:
                offenders.append(f"{p.relative_to(REPO_ROOT)}: missing rel=: {tag[:120]}")
                continue
            rel_value = rel_match.group(1).lower()
            # Both tokens required — noopener stops the new tab from
            # window.opener-ing back; noreferrer also strips the Referer header.
            if 'noopener' not in rel_value or 'noreferrer' not in rel_value:
                offenders.append(
                    f"{p.relative_to(REPO_ROOT)}: rel={rel_value!r} "
                    f"missing 'noopener' or 'noreferrer': {tag[:120]}"
                )
    assert not offenders, 'target=_blank without rel=noopener noreferrer:\n' + '\n'.join(offenders)


# -----------------------------------------------------------------------------
# 37.5 — heading hierarchy (no H1 → H3 jumps on the fixed pages)
# -----------------------------------------------------------------------------
def test_37_5_game_detail_no_h1_h3_jump():
    """The top-level page sections must be <h2>, not <h3>.

    Assert that for each section anchor word (e.g. "Screenshots"), there
    exists a `<h2 class="…">…anchor…</h2>` element somewhere in the
    template. We match the full h2 element (open tag + body + close)
    in one regex, so a future emoji or whitespace edit inside the body
    won't break the test as long as the heading level stays at h2
    (test-audit ASSERT-5).

    The previous implementation hardcoded the exact emoji-bearing string
    `'<h2 class="media-title">📸 Screenshots'`, which silently fails on
    emoji changes — masking what's actually a heading-level regression
    test.
    """
    src = read_source('templates/game_detail.html')

    # (heading_text_substring, expected_h2_css_class).
    sections = (
        ('Screenshots', 'media-title'),
        ('Video', 'media-title'),
        ('Similar Games', 'section-title-sm'),
        ('More Details', 'section-title-sm'),
    )
    for anchor, css_class in sections:
        # Match: <h2 …class="<css_class>…">…<anchor>…</h2>. DOTALL so the
        # body can wrap across whitespace; non-greedy so we don't span
        # multiple h2s.
        pattern = re.compile(
            rf'<h2\b[^>]*class="[^"]*{re.escape(css_class)}[^"]*"[^>]*>'
            rf'[^<]*{re.escape(anchor)}[^<]*</h2>',
            re.IGNORECASE,
        )
        assert pattern.search(src), (
            f'section {anchor!r}: no <h2 class="…{css_class}…">…{anchor}…</h2> '
            f'element found — heading-level jump (h1 → h3) regressed, OR '
            f'the section is no longer rendered with the expected class'
        )


def test_37_5_settings_h4_promoted_to_h3():
    src = read_source('templates/settings.html')
    # No <h4> opener remains outside generated/dropdown markup.
    assert not re.search(r'<h4\b', src), 'settings.html still has <h4 tags'


# -----------------------------------------------------------------------------
# 37.6 — aria-live on flash + result containers
# -----------------------------------------------------------------------------
def test_37_6_base_flash_has_aria_live():
    src = read_source('templates/base.html')
    # Both polite (role=status) and assertive (role=alert) branches present.
    flash_zone = src[src.index('Flash Messages'):src.index('Page Content')]
    assert 'role="status"' in flash_zone and 'aria-live="polite"' in flash_zone
    assert 'role="alert"' in flash_zone and 'aria-live="assertive"' in flash_zone


def test_37_6_settings_result_containers_have_live_regions():
    src = read_source('templates/settings.html')
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
    src = read_source('static/css/core/variables.css')
    assert '--neon-blue:' in src
    assert '--text-on-color:' in src


def test_37_7_game_list_no_residual_3b82f6_or_fff_on_ratings():
    src = read_source('static/css/pages/game-list.css')
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


