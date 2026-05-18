"""Pass 38.4 — Jinja macro extraction (breadcrumb + sticky-subnav).

Pins:
- `_macros/breadcrumb.html::breadcrumb` renders the canonical
  `<nav class="breadcrumb" aria-label="Breadcrumb">` shape with `›`
  separators and treats `url=None` as the current page.
- `_macros/sticky_subnav.html::tab_subnav` emits the StickyScroll-discoverable
  wrapper (`data-sticky-nav data-tabbar id="subnav-<tab_id>"`).
- `_macros/sticky_subnav.html::subnav_link` emits the canonical anchor with
  `scrollToSection('<href>')` hook and a derived id-less href.
- Source-grep regression: no template re-introduces raw
  `<nav class="breadcrumb"` or `class="tab-subnav sticky-subnav"` —
  every call site must import the macros.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def jinja_env():
    """Standalone Jinja environment over the project's templates/ tree.

    Avoids spinning up the full Flask app — the macros are pure-Jinja and
    have no Flask globals (url_for is bound by the caller before reaching
    the macro, so the macro itself sees ordinary strings).
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


# ---------------------------------------------------------------------------
# breadcrumb
# ---------------------------------------------------------------------------


class TestBreadcrumbMacro:
    def test_renders_canonical_wrapper(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/breadcrumb.html' import breadcrumb %}"
            "{{ breadcrumb([('Systems', '/systems'), ('SNES', None)]) }}"
        )
        html = tmpl.render()
        assert '<nav class="breadcrumb"' in html
        assert 'aria-label="Breadcrumb"' in html

    def test_url_none_renders_as_current(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/breadcrumb.html' import breadcrumb %}"
            "{{ breadcrumb([('SNES', None)]) }}"
        )
        html = tmpl.render()
        assert '<span class="breadcrumb-current">SNES</span>' in html
        assert "<a " not in html

    def test_url_present_renders_as_link(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/breadcrumb.html' import breadcrumb %}"
            "{{ breadcrumb([('Systems', '/systems'), ('SNES', None)]) }}"
        )
        html = tmpl.render()
        assert '<a href="/systems">Systems</a>' in html

    def test_separator_emitted_between_items_only(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/breadcrumb.html' import breadcrumb %}"
            "{{ breadcrumb([('A', '/a'), ('B', '/b'), ('C', None)]) }}"
        )
        html = tmpl.render()
        # Two separators (between A/B and B/C); none after C.
        assert html.count("breadcrumb-separator") == 2
        assert "›" in html

    def test_single_current_item(self, jinja_env):
        # `xbox_achievements.html` and `steam_achievements.html` pass exactly
        # one item with url=None — no separator should render.
        tmpl = jinja_env.from_string(
            "{% from '_macros/breadcrumb.html' import breadcrumb %}"
            "{{ breadcrumb([('Xbox Achievements', None)]) }}"
        )
        html = tmpl.render()
        assert "breadcrumb-separator" not in html
        assert '<span class="breadcrumb-current">Xbox Achievements</span>' in html


# ---------------------------------------------------------------------------
# sticky_subnav
# ---------------------------------------------------------------------------


class TestStickySubnavMacros:
    def test_tab_subnav_wrapper(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/sticky_subnav.html' import tab_subnav %}"
            "{% call tab_subnav('library') %}inner{% endcall %}"
        )
        html = tmpl.render()
        # StickyScroll discovers via `data-sticky-nav`; the tabbar marker keeps
        # this distinct from the top-level settings-tabs sticky strip.
        assert 'class="tab-subnav sticky-subnav"' in html
        assert "data-sticky-nav" in html
        assert "data-tabbar" in html
        assert 'id="subnav-library"' in html
        assert "inner" in html

    def test_subnav_link_default_inactive(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/sticky_subnav.html' import subnav_link %}"
            "{{ subnav_link('display', '🖼️ Display') }}"
        )
        html = tmpl.render()
        assert 'href="#display"' in html
        assert 'class="subnav-link"' in html
        assert "scrollToSection('display')" in html
        assert "🖼️ Display" in html
        assert "active" not in html

    def test_subnav_link_active_flag(self, jinja_env):
        tmpl = jinja_env.from_string(
            "{% from '_macros/sticky_subnav.html' import subnav_link %}"
            "{{ subnav_link('library', '📁 Paths', active=True) }}"
        )
        html = tmpl.render()
        assert 'class="subnav-link active"' in html

    def test_call_block_full_shape(self, jinja_env):
        # Smoke test for the actual settings.html invocation pattern.
        tmpl = jinja_env.from_string(
            "{% from '_macros/sticky_subnav.html' import tab_subnav, subnav_link %}"
            "{% call tab_subnav('account') %}"
            "{{ subnav_link('profile', '👤 My Profile', active=True) }}"
            "{{ subnav_link('timezone', '🕐 Timezone') }}"
            "{% endcall %}"
        )
        html = tmpl.render()
        assert 'id="subnav-account"' in html
        assert "👤 My Profile" in html
        assert 'class="subnav-link active"' in html
        assert "scrollToSection('timezone')" in html


# ---------------------------------------------------------------------------
# Source-grep regressions
# ---------------------------------------------------------------------------


def _read(template: str) -> str:
    return (TEMPLATES_DIR / template).read_text(encoding="utf-8")


def _every_template_html() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


class TestSourceGrepRegressions:
    """Stop future patches from reintroducing the duplicated shapes."""

    BREADCRUMB_CONSUMERS = [
        "achievement_game.html",
        "achievements_system.html",
        "game_detail.html",
        "list_detail.html",
        "local_trophy_detail.html",
        "psn_trophy_detail.html",
        "steam_achievement_game.html",
        "steam_achievements.html",
        "system_games.html",
        "xbox_achievement_game.html",
        "xbox_achievements.html",
    ]

    def test_no_raw_breadcrumb_nav_outside_macro(self):
        # Allowed: the macro file itself.
        offenders = []
        for path in _every_template_html():
            if path.name == "breadcrumb.html":
                continue
            src = path.read_text(encoding="utf-8")
            if re.search(r'<nav\s+class="breadcrumb"', src):
                offenders.append(str(path.relative_to(TEMPLATES_DIR)))
        assert not offenders, (
            f"Templates still emit raw `<nav class=\"breadcrumb\">` — use the "
            f"breadcrumb macro instead: {offenders}"
        )

    @pytest.mark.parametrize("template", BREADCRUMB_CONSUMERS)
    def test_breadcrumb_consumer_imports_macro(self, template):
        src = _read(template)
        assert "_macros/breadcrumb.html" in src, (
            f"{template} renders a breadcrumb but doesn't import the macro"
        )

    def test_settings_imports_sticky_subnav_macros(self):
        src = _read("settings.html")
        assert "_macros/sticky_subnav.html" in src

    def test_no_raw_tab_subnav_in_settings(self):
        src = _read("settings.html")
        # The old shape was `<div class="tab-subnav sticky-subnav" ...>`.
        assert 'class="tab-subnav sticky-subnav"' not in src, (
            "settings.html still contains a raw tab-subnav block — convert it "
            "to the `{% call tab_subnav(...) %}` macro"
        )

    def test_select_filter_modal_partial_used_in_both_libraries(self):
        for template in ("all_games.html", "system_games.html"):
            src = _read(template)
            assert "_modals/select_filter_modal.html" in src, (
                f"{template} should `{{% include %}}` the select-filter modal "
                "partial, not inline the markup"
            )
            # Inline copy of the modal markup must be gone.
            assert '<div id="filterModal" class="filter-modal">' not in src
