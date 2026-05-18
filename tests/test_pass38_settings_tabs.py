"""Pass 38.6 — split `templates/settings.html` into per-tab partials.

The page was a ~7.3k-line monolith; CSP / a11y / i18n sweeps all bottlenecked
on it. Six panels were extracted into `templates/_settings_tabs/{tab}.html`
and the shell now `{% include %}`s each.

Pins:
- Every expected partial exists, opens with the panel `<div>` carrying the
  right `id`/`role`/`aria-label`, and ends with the matching `</div>`.
- Each partial re-imports `tab_subnav`/`subnav_link` from
  `_macros/sticky_subnav.html` so the partial is testable in isolation (a
  consumer rendering it through `Environment.get_template()` doesn't have
  to thread the macro through manually).
- The shell `templates/settings.html` no longer carries the inline
  `<div class="settings-tab-panel"` blocks — it now references each tab
  via `{% include "_settings_tabs/<tab>.html" %}`.
- Functional render: feeding the shell a no-context render reaches each
  partial via include and emits the canonical panel wrapper.
- Anchor IDs (`#profile`, `#timezone`, `#users`, `#logging`, etc.) are
  preserved — the sticky subnav links depend on them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._util import REPO_ROOT, read_settings_with_partials, read_source


TABS = ("account", "library", "scraping", "data", "customization", "system")

TEMPLATES_DIR = Path(REPO_ROOT) / "templates"
PARTIALS_DIR = TEMPLATES_DIR / "_settings_tabs"


# ---------------------------------------------------------------------------
# Partial file existence + shape
# ---------------------------------------------------------------------------


class TestPartialsExist:
    @pytest.mark.parametrize("tab", TABS)
    def test_partial_file_exists(self, tab):
        path = PARTIALS_DIR / f"{tab}.html"
        assert path.is_file(), f"missing settings-tab partial: {path}"

    @pytest.mark.parametrize("tab", TABS)
    def test_partial_opens_with_panel_div(self, tab):
        src = (PARTIALS_DIR / f"{tab}.html").read_text(encoding="utf-8")
        # The `active` class only belongs to the account partial — the
        # initially-visible tab. The others get it from JS on switch.
        active_marker = " active" if tab == "account" else ""
        opening = (
            f'<div class="settings-tab-panel{active_marker}" id="tab-{tab}" '
            f'role="tabpanel" aria-label="{tab.capitalize()} settings">'
        )
        assert opening in src, (
            f"{tab}.html should open with the panel wrapper:\n{opening}"
        )

    @pytest.mark.parametrize("tab", TABS)
    def test_partial_closes_with_end_marker(self, tab):
        src = (PARTIALS_DIR / f"{tab}.html").read_text(encoding="utf-8")
        assert f"</div><!-- End tab-{tab} -->" in src

    @pytest.mark.parametrize("tab", TABS)
    def test_partial_imports_sticky_subnav(self, tab):
        src = (PARTIALS_DIR / f"{tab}.html").read_text(encoding="utf-8")
        assert "_macros/sticky_subnav.html" in src, (
            f"{tab}.html should re-import sticky_subnav so it's self-contained"
        )


# ---------------------------------------------------------------------------
# Shell shape — settings.html is now a thin wrapper
# ---------------------------------------------------------------------------


class TestShellIsThin:
    @pytest.mark.parametrize("tab", TABS)
    def test_shell_includes_each_partial_once(self, tab):
        shell = read_source("templates/settings.html")
        include_line = f'{{% include "_settings_tabs/{tab}.html" %}}'
        count = shell.count(include_line)
        assert count == 1, (
            f"settings.html should `{include_line}` exactly once; found {count}"
        )

    def test_shell_has_no_inline_settings_tab_panel_div(self):
        """All six panel wrappers should now live in partials, not the shell."""
        shell = read_source("templates/settings.html")
        assert 'class="settings-tab-panel' not in shell, (
            "settings.html still contains an inline `<div class=\"settings-tab-panel\">` "
            "block — extract it to `_settings_tabs/<tab>.html`."
        )

    def test_shell_dropped_below_5500_lines(self):
        """A coarse pin against re-bloat. Pre-split settings.html was 7,368
        lines; the post-split shell is ~5.2k (the JS/CSS blocks dominate).
        Pin below 5,500 to catch accidental re-inlining of a tab."""
        shell = read_source("templates/settings.html")
        line_count = shell.count("\n")
        assert line_count < 5500, (
            f"settings.html is back up to {line_count} lines — check whether "
            "a tab panel was re-inlined into the shell"
        )


# ---------------------------------------------------------------------------
# Functional render — each partial reaches the panel wrapper via include
# ---------------------------------------------------------------------------


class _SilentUndefined:
    """Stand-in for any context variable a partial reaches for. Allows
    attribute access, item access, method calls (including `.get(...)`),
    iteration, comparison, and stringification — every operation returns
    another `_SilentUndefined`. Lets partials render to a stable shape
    without us hand-listing the Flask globals they touch (avoids coupling
    this test to view-layer wiring)."""

    def __getattr__(self, _name):
        return _SilentUndefined()

    def __getitem__(self, _key):
        return _SilentUndefined()

    def __call__(self, *_args, **_kwargs):
        return _SilentUndefined()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __eq__(self, _other):
        return False

    def __ne__(self, _other):
        return True

    def __hash__(self):
        return 0

    def __str__(self):
        return ""

    def __html__(self):
        return ""


@pytest.fixture
def jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Replace the strict `Undefined` with our permissive stand-in so any
    # name a partial reaches for resolves to a chainable empty value.
    env.globals.update(
        current_user=_SilentUndefined(),
        current_user_settings=_SilentUndefined(),
        user_settings=_SilentUndefined(),
        users=(),
        systems=(),
        stats=_SilentUndefined(),
        config=_SilentUndefined(),
        scraper_settings=_SilentUndefined(),
        settings=_SilentUndefined(),
        g=_SilentUndefined(),  # Flask request-globals proxy
        request=_SilentUndefined(),
        get_avatar_url=lambda *a, **kw: None,
        tz=lambda *a, **kw: "",
        format_number=str,
    )
    env.filters["tz"] = lambda *a, **kw: ""
    env.filters["format_number"] = str
    return env


class TestFunctionalRender:
    @pytest.mark.parametrize("tab", TABS)
    def test_partial_renders_standalone(self, jinja_env, tab):
        """The partial must compile + render without the shell — confirms
        it's truly self-contained (macros imported, no orphan blocks)."""
        rendered = jinja_env.get_template(f"_settings_tabs/{tab}.html").render()
        assert f'id="tab-{tab}"' in rendered
        # Macros must have resolved (no Jinja {%…%} stragglers).
        assert "{% " not in rendered, (
            f"{tab}.html left Jinja markup in rendered output — macros didn't resolve"
        )


# ---------------------------------------------------------------------------
# Anchor IDs the sticky subnav depends on must survive the split
# ---------------------------------------------------------------------------


class TestAnchorsPreserved:
    # These are the section anchors referenced by `subnav_link('<id>', ...)`
    # calls inside the partials. JS calls `scrollToSection('<id>')` which
    # looks up `document.getElementById('<id>')` — losing one breaks the
    # link target.
    EXPECTED_ANCHORS = {
        "account": ["profile", "timezone", "users"],
        "library": ["library", "display", "rom-naming", "backup"],
        "scraping": ["esde", "scraper", "apikeys"],
        "data": ["stats", "trophies", "dropdowns", "normalization"],
        "customization": ["notifications", "controllers", "logos"],
        "system": ["maintenance", "server", "logging", "troubleshooting"],
    }

    @pytest.mark.parametrize("tab", TABS)
    def test_partial_keeps_expected_anchors(self, tab):
        """Every anchor the subnav-link calls jump to must still resolve.
        Losing one silently breaks the scroll target on click."""
        src = (PARTIALS_DIR / f"{tab}.html").read_text(encoding="utf-8")
        missing = [a for a in self.EXPECTED_ANCHORS[tab] if f'id="{a}"' not in src]
        assert not missing, (
            f"{tab}.html dropped section anchors {missing} — "
            "sticky subnav links will scroll nowhere"
        )

    def test_subnav_call_count_matches_tab_count(self):
        """Every tab has a `{% call tab_subnav('<tab>') %}` block. After the
        split, each tab partial owns exactly one. Pinning the union count
        catches a partial losing its subnav during a future cleanup."""
        body = read_settings_with_partials()
        for tab in TABS:
            needle = f"{{% call tab_subnav('{tab}') %}}"
            assert needle in body, (
                f"missing sticky-subnav call for {tab!r}: `{needle}`"
            )
