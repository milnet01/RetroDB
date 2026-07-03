# =============================================================================
# Pass 52 — accessibility: aria-live announcements for long-running job progress
# =============================================================================
# Regression pins for Pass 52.2. Screen-reader users previously heard nothing
# between a job's "start" and "done" — the unified toast controller updated the
# progress DOM (counts, percent, current item) silently. Pass 52.2 speaks
# throttled milestones + a forced completion line through a dedicated,
# visually-hidden aria-live region.
#
# Templates/JS aren't executed by pytest, so these are source-level + catalog
# checks that keep the wiring (and its translations) in place. Slices are scoped
# to the relevant function bodies so a stray mention elsewhere can't satisfy a
# check (test-audit hardening pattern, cf. test_pass35_36_hardening.py:313).
# =============================================================================

import os

from babel.messages.pofile import read_po

from tests._util import REPO_ROOT, read_source

PROGRESS_MSGID = "{job}: {current} of {total} ({percent}%)"
PLACEHOLDERS = ("{job}", "{current}", "{total}", "{percent}")
# The human-translation locales (docs/specs/i18n.md §9); `eo` is the
# auto-generated pseudolocale and is excluded from the translated-content pin.
HUMAN_LOCALES = ("de", "es", "fr", "it", "ja", "ko", "pt_BR", "zh_Hans", "zh_Hant")


def _slice(src, start_marker, end_marker):
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def test_announce_region_defined_in_utils():
    """utils.js exposes Notifications.announce() backed by a hidden polite region."""
    src = read_source(os.path.join("static", "js", "utils.js"))
    # Scope to the announce() method body (last method in the Notifications
    # object) so an unrelated mention can't satisfy the check.
    body = _slice(src, "announce(message,", "\n};")
    assert "a11y-progress-announce" in body, "dedicated live-region id missing"
    assert "visually-hidden" in body, "region must reuse the sr-only utility class"
    assert "'aria-live'" in body and "'polite'" in body, "region must be aria-live=polite"
    assert "force" in body, "completion must be able to bypass the throttle"
    assert "ANNOUNCE_THROTTLE_MS" in src, "milestone throttle constant missing"


def test_toast_controller_announces_progress_and_completion():
    """The unified toast controller drives the announcer from its progress path."""
    src = read_source(os.path.join("static", "js", "toast-controller.js"))
    body = _slice(src, "updateActiveToastContent(toast", "hideActiveToast(type)")
    assert body.count("Notifications.announce(") >= 2, "expected running + completion announce"
    assert "{ force: true }" in body, "completion announce must be forced past the throttle"
    assert PROGRESS_MSGID in body, "running-progress line must be wrapped in t() with the msgid"


def test_progress_msgid_registered_in_js_manifest_and_pot():
    """build_js.py must have carried the new t() literal into the JS manifest + catalog."""
    manifest = read_source(os.path.join("services", "js_i18n_strings.py"))
    assert PROGRESS_MSGID in manifest, "run `python3 build_js.py` — msgid not in JS manifest"
    pot = read_source("messages.pot")
    assert PROGRESS_MSGID in pot, "re-run the pybabel extract — msgid not in messages.pot"


def test_progress_msgid_translated_in_every_human_locale():
    """Each shipped locale translates the announcement (not fuzzy, placeholders intact)."""
    for loc in HUMAN_LOCALES:
        po_path = os.path.join(REPO_ROOT, "translations", loc, "LC_MESSAGES", "messages.po")
        with open(po_path, "rb") as f:
            catalog = read_po(f)
        msg = catalog.get(PROGRESS_MSGID)
        assert msg is not None, f"{loc}: msgid absent from catalog"
        assert msg.string, f"{loc}: untranslated (would fall back to English)"
        assert "fuzzy" not in msg.flags, f"{loc}: still fuzzy — pybabel compile drops it"
        for placeholder in PLACEHOLDERS:
            assert placeholder in msg.string, f"{loc}: translation dropped {placeholder}"
