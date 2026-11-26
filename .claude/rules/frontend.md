---
paths:
  - "templates/**"
  - "static/**"
  - "build_css.py"
  - "build_js.py"
  - "routes/**"
---

# Page wiring and CSS / JS build contracts

### Page wiring
- A box that takes a path gets `browse_button()` from `_macros/browse_button.html` beside it, in a `.path-input-row`, and a row in `tests/test_path_browser.py`. The button shows for admins only: `/api/settings/browse-paths` can list any folder on the computer.
- Both `/games` (Library) and `/system/<id>` use `AllGamesController` — keep them in sync.
- The game page's Previous / Next links follow the list it was opened from (`?from=library`, else its console). `AllGamesController` saves each list's filter and sort params per tab via `RetroDB.saveGameNavContext`; the game page sends them to `/api/games/neighbors`.

---

### CSS / JS build contracts

- CSS: edit `static/css/<category>/<file>.css`, then `python3 build_css.py` to rebuild `main.min.css`.
- JS: edit `static/js/<file>.js`, then `python3 build_js.py` if it's bundled. Never edit `core.bundle.js` / `games.bundle.js` directly — generated output.
- Bundles: `core.bundle.js` (every page) and `games.bundle.js` (game-centric pages only). Templates that need the games bundle MUST set `{% set needs_games_bundle = true %}` at the template's top level — before the first `{% block %}`, so `base.html` sees it at render time. An intervening `{% from %}` import is fine.
- Adaptive layout (PASS-59-104): a page opts in with `{% set adaptive_layout = true %}` (same placement as `needs_games_bundle`) and wraps its content in an element with class `page-box`; the rules are `docs/RETRODB_DESIGN_STANDARDS.md` §7 "Page Width — adaptive".
- Cache-busting: `build_css.py` / `build_js.py` write `static/asset_manifest.json` with SHA-256 prefixes. Reference assets via `{{ asset_url('js/core.bundle.js') }}` (Jinja global from `services/assets.py`). Fallback is `?v={APP_VERSION}`.
- CSS rules: never duplicate external classes inline; use variables from `core/variables.css` (no hardcoded colors; brand colours are named tokens, design standards §2); promote any style used on 2+ pages to external CSS.
- Sticky bars: a page-level `position: sticky` bar sets `top: var(--sticky-top)`, or `calc()` from it, never `top: 0`. On a phone the fixed header covers the top of the window (PASS-59-165). A header that sticks inside its own scrolling box keeps `top: 0`. Nothing checks this.
- Pinned bars on a phone (PASS-59-167): at 768px and narrower, filter bars and toolbars scroll away and tab strips become one row that swipes sideways. A new bar of either kind joins its list in `layout/responsive.css`.
