# RetroDB - Claude Code Project Guide

> Flask-based retro gaming ROM library manager with cyberpunk UI theme.

**Screenshots:** User screenshots are always at `/home/ants/Pictures/`

The full file index, route table, service descriptions, JS-globals catalog, and
design tokens were intentionally removed in favor of `ls routes/`, `grep`, and
reading source. Keep this file to non-obvious contracts and mandatory workflow.

---

## Mandatory Workflow

### After Every Code Change
1. Bump version in `config.py` AND `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`)
2. Add changelog entry at top of `data/changelog.yaml`
3. Rebuild CSS if any `static/css/**.css` changed: `python3 build_css.py`
4. Rebuild JS if any bundled `static/js/*.js` changed: `python3 build_js.py`
5. Run tests if any `services/*.py` or `scraper/*.py` changed: `python3 -m pytest`
6. Regenerate lockfile if `requirements.txt` was edited: `pip-compile requirements.txt -o requirements.lock --strip-extras`
7. Update this file if change adds/removes/renames routes, templates, bundled JS, CSS files, or alters page/asset wiring contracts

### Verification Before Declaring Done
Tests authored alongside the implementation are regression pins, not correctness
proofs — they encode the implementer's understanding, which may be wrong.

- **UI changes** (templates / CSS / JS / page-rendering routes): start dev server,
  walk golden path in browser at desktop + mobile (~375px). DevTools Network to
  verify runtime assumptions (WebP served? srcset picked `-md`? API shape matches
  template?). DevTools Console for errors/warnings. Trigger one error path
  (empty input, missing record, cancelled action), not just happy path.
- **Backend-only**: unit tests + a single end-to-end smoke call (curl, invoke job).
- State what was verified in the session summary; if something couldn't be tested
  in-session, say so explicitly — never imply coverage that wasn't produced.
- For architecturally significant passes (touches multiple subsystems, reshapes an
  abstraction, changes security/auth/data flow): proactively recommend the user
  run `/ultrareview` before merging. Only the user can launch it.
- Never mark a task complete solely because the tests I wrote pass.

### Periodic Independent Review (Multi-Agent Audit)
Run a multi-agent independent sweep at one of these triggers (whichever first):
1. Every 5 landed roadmap passes
2. Before any minor version bump (`x.N+1.0`)
3. After an architectural change touching >3 subsystems

How: see `roadmap.md` §Periodic Independent Review (14-subsystem partition,
reviewer brief, triage rules). Dispatch all 14 agents in parallel from a single
message. Surface reports verbatim — don't filter or summarize before the user
has seen the raw output. Triage into new roadmap passes after.

### Version Bumping
- **Patch** (x.x.N+1): bug fixes, cleanup, refactoring, accessibility
- **Minor** (x.N+1.0): new features, enhancements, new options
- **Major** (N+1.0.0): major releases, breaking changes

---

## Non-Obvious Project Facts

### Schema / data shapes
- `perspective`, `dimension`, `genre`, `modes`, `game_structure` are comma-separated multi-value TEXT fields.
- `region` is single-value, dropdown-driven (`region_options` setting; default `default_region`).
- Genre canonical forms are hyphenated and must match `FIELD_SCHEMAS` in `scraper/scrape_ai.py` (e.g. `First-Person-Shooter`, `Shoot-em-up`, `Beat-em-up`, `Hack-n-Slash`, `Board-Card`).
- `players` is INTEGER. Scraper/AI ranges like `"1-4"` are normalized to the max (4) before saving.
- Sort title is auto-generated during scraping and AI Fill via `generate_sort_title()` in `services/game_utils.py`.
- When a system has curated default controllers in the DB, they always override scraped/AI controller values.

### Media handling
- Media fields (boxart, boxart_3d, screenshots, fanart, video, manual) are never replaced during normal scraping — only filled when empty. Screenshots are always appended, never replaced. To get new media: clear it from the edit modal first, then re-scrape. Full Re-scrape mode overrides this and replaces everything.
- During pre-population, media files are validated on disk — stale DB references (file deleted, filename still in DB) are auto-cleared so scrapers can re-download.

### Multi-rating system (8 systems)
ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd — DB columns `{system}_rating`.
Cross-mapping via maturity tiers in `services/game_utils.py` (`map_rating()`,
`get_preferred_rating()`). Empty ratings auto-fill from any available rating
during scrape / AI Fill / manual edit. User preference: `preferred_rating_system`.

Rating images live in `static/images/ratings/{SYSTEM}/`. `RATING_IMAGE_MAP` in
`game_utils.py` maps `(system, value)` → path. JS helpers expose
`window.RATING_IMAGE_MAP`, `window.RATING_TO_TIER`, `window.TIER_TO_RATING` via
`base.html`.

### Page wiring
- Both `/games` (Library) and `/system/<id>` use `AllGamesController` — keep them in sync.

---

## CSS / JS Build Contracts

- CSS: edit `static/css/<category>/<file>.css`, then `python3 build_css.py` to rebuild `main.min.css`.
- JS: edit `static/js/<file>.js`, then `python3 build_js.py` if it's bundled. Never edit `core.bundle.js` / `games.bundle.js` directly — generated output.
- Bundles: `core.bundle.js` (every page) and `games.bundle.js` (game-centric pages only). Templates that need the games bundle MUST set `{% set needs_games_bundle = true %}` right after `{% extends "base.html" %}`.
- Cache-busting: `build_css.py` / `build_js.py` write `static/asset_manifest.json` with SHA-256 prefixes. Reference assets via `{{ asset_url('js/core.bundle.js') }}` (Jinja global from `services/assets.py`). Fallback is `?v={APP_VERSION}`.
- CSS rules: never duplicate external classes inline; use variables from `core/variables.css` (no hardcoded colors); promote any style used on 2+ pages to external CSS.

---

## Non-Obvious JS / Template Contracts

Use these names exactly in template `<script>` blocks — never invent aliases.
Globals are defined in `static/js/utils.js`, `main.js`, `toast-controller.js`,
`page-lifecycle.js`, `game-modals.js`. Read source for full signatures.

- **Toasts/dialogs**: `showNotification(msg, type, duration?)`, `showConfirm(title, msg, onConfirm, opts?)`, `showModal(title, msg, onConfirm?, showCancel?, onCancel?)`.
- **HTTP/storage**: `API.get/post/postForm`, `Storage.get/set/remove/clearAll`.
- **Utilities**: `escapeHtml`, `formatNumber` (thin-space thousands), `formatBytes`, `copyToClipboard`, `debounce`, `throttle`, `DOM.$/$$/create/toggle/delegate`, `DateUtils`.
- **Lifecycle**: `PageLifecycle` (timer/observer auto-cleanup), `DOMCache`.
- **Game modals**: `GameDetailModal.open/close/clearCache`, `GameEditModal.open/save/close`, `HLTBManager.lookup/save/cancel/clear`, `triggerAiFill`.
- **Sticky nav**: `StickyScroll.to(target)`, `.stackPositions()`, `.updateMargins()`. Mark sticky elements containing anchor links with `data-sticky-nav`. Scope to a container with `data-sticky-scope="containerId"` (height excluded from offsets for targets outside that container). Both `stackPositions()` + `updateMargins()` run on DOMContentLoaded in `main.js`; call them again after tab/panel switches that show/hide sticky navs.
- **Themed icons**: `getThemedIcon(key, fallback?)` returns icons matching the current theme (e.g. `'error'` → `❌` on cyberpunk, `✗` on matrix). Keys: job types (`bulk-scrape`, `ra-sync`, `ra-refresh`...), states (`paused`, `resume`, `complete`, `queued`, `cancelled`), notifications (`success`, `error`, `warning`, `info`), stats (`stat-success`, `stat-failed`, `stat-skipped`), actions (`starting`, `running`, `cancel`, `save`, `loading`, `background`). In HTML use `data-themed-icon="key"` — `main.js` auto-populates on DOMContentLoaded.
- **A11y**: `ModalFocusTrap.activate(modalEl, triggerEl, {onEscape, autoFocus})` / `.deactivate()` — WCAG 2.4.3, stacks for nested modals, restores focus to trigger on close.
- **Number formatting**: Jinja `{{ value|format_number }}`; JS `formatNumber(value)`.

Themes: cyberpunk (default), matrix, amber, ocean, christian (Cathedral), bladerunner, elite (Elite 1984).

---

## Distribution (Patreon Releases)

```bash
python3 build_dist.py            # all 3 platforms
python3 build_dist.py linux|macos|windows
```

- Output: `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB/`
- Filename: `RetroDB-v{VERSION}-{Platform}.zip`
- Excluded from ZIPs: `config.py`, `data/settings.json`, `data/scraper_settings.json`, `data/rom_tools_config.json`, `data/hltb_dataset.csv`, `.secret_key`, all scraped media (`static/images/{boxart,boxart_3d,screenshots,fanart,manuals,trophies}/`, `static/videos/`), all `.db` files. Per-platform: only that platform's start script (`start.sh` / `start.command` / `start.bat`).

Pre-release checklist: bump version + changelog → ensure `config.example.py` matches any new settings → `python3 build_dist.py` → upload from staging.

---

## Reference Documents

- `docs/RETRODB_DESIGN_STANDARDS.md` — Full UI/CSS/JS/API standards (22 sections; §23 controller naming)
- `docs/STANDARDS_ADDENDUM.md` — Version checklist, logging system
- `docs/ROM_NAMING_STANDARD.md` — ROM file naming
- `docs/theme_contrast.md` — Generated WCAG output (`scripts/audit_contrast.py`); regenerate when theme colors change
- `roadmap.md` — Backlog of refactoring/security/perf/a11y/observability/migrations/CI/ops passes. Includes "Scope notes — considered and dropped". Check before proposing net-new architectural work.
- `audit_hygiene.md` — Portable `/audit`-skill recommendations (not RetroDB-specific)
- `.semgrep.yml` — Documented threat model + excluded upstream rule IDs (read before triaging new audit findings)
- `.gitleaks.toml` — Allowlist for `logs/`, `data/*.json` tokens, admin-editable settings
- `.pre-commit-config.yaml` — `ruff check --fix` + `gitleaks`. Install: `pip install pre-commit --break-system-packages && pre-commit install`. `ruff-format`, `pytest`, `mypy` intentionally excluded (CI-only).

---

## Common DB Access

```python
from services.database import get_db
db = get_db()
games = db.execute("SELECT * FROM games WHERE system_id = ?", [system_id]).fetchall()
```

`safe_column()` in `services/database.py` is the allowlist validator for any
column name interpolated into an SQL f-string.
