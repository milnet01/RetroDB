# RetroDB - Claude Code Project Guide

> Flask-based retro gaming ROM library manager with cyberpunk UI theme.

This file holds only non-obvious project contracts and the mandatory workflow.
For file index / routes / services / JS globals / design tokens, use `ls
routes/`, `grep`, and the source.

**Global rules apply.** `~/.claude/CLAUDE.md` covers development discipline
(root-cause fixes, shortest correct implementation, reuse-before-rewrite,
six-month test, current-idiom external libraries), git/CI cadence (private-repo
push batching, PR-opt-in feature flow — neither currently active here), and the
clarity rules (surface ambiguity, push back on over-complex framing,
reproduce-before-fix, stay in lane on edits, state a `step → verify` plan for
3+ step work). Don't restate them here — extend or override only when RetroDB
genuinely diverges.

---

## Mandatory Workflow

### After Every Code Change
1. Bump version in `config.py` AND `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`)
2. Add changelog entry at top of `data/changelog.yaml`. For a real release, also translate the **recent** entry (current line onward; deep history stays English) into each per-locale `data/changelog.<locale>.yaml` (the human-translation locales in `docs/specs/i18n.md` §9 — a different delivery path from the installed UI-catalog set `services/i18n.py::available_locales()` derives, §3). Repeat `version`, `date`, and every tag verbatim — the `/changelog` route swaps the whole entry in by version, so anything omitted is dropped, not inherited (Pass 43.6). Skip for internal/no-release bumps.
3. Rebuild CSS if any `static/css/**.css` changed: `python3 build_css.py`
4. Rebuild JS if any bundled `static/js/*.js` changed: `python3 build_js.py`
5. Run tests if any `services/*.py` or `scraper/*.py` changed: `python3 -m pytest`
6. Regenerate lockfile if `requirements.txt` was edited: `pip-compile requirements.txt -o requirements.lock --strip-extras --generate-hashes` (Pass 39.4 — `install.py` prefers `--require-hashes` when `requirements.lock` is present and falls back to `requirements.txt` otherwise; keep the lockfile current so the secure path stays the default). Dependencies track **latest-always** (features + security); a hold below latest is allowed only for a documented breakage recorded in `docs/DEPENDENCY_POLICY.md` — read it before pinning, capping, or bumping a major.
7. Update this file if change adds/removes/renames routes, templates, bundled JS, CSS files, or alters page/asset wiring contracts
8. Wrap any new user-facing string for i18n and regenerate catalogs — see `docs/specs/i18n.md` §2/§4/§6/§7/§9:
   - Templates `{{ _('...') }}` / `{% trans %}`; Python `flash(_('...'))` / `error(_('...'))`.
   - **JS** (toasts, modal copy): `t('...')` — string literals only (see §6); `python3 build_js.py` regenerates `services/js_i18n_strings.py` (runtime manifest + `_()` bridge anchors that carry JS msgids into the catalog via the Python extractor — there is no `[javascript:]` babel mapping).
   - **Canonical multi-value labels** (genre/perspective/dimension/modes/game_structure): never wrap the value; it's translated for display via `display_field_value()` (server) / `tField()` (JS) — see §7. Add new canonical values to `services/i18n_labels.py` or `tests/test_i18n_labels.py` fails.
   - Regenerate: `python3 build_js.py && pybabel extract -F babel.cfg --ignore-dirs='.* __pycache__ node_modules venv .venv env build dist staging tests' -o messages.pot . && pybabel update -i messages.pot -d translations && python3 scripts/gen_pseudolocale.py && pybabel compile -d translations`. CI gate: `python3 scripts/check_i18n_fresh.py`. (The `--ignore-dirs` flag is mandatory — Babel otherwise skips the `_`-prefixed template partials; keep it identical to `check_i18n_fresh.py`.)
   - **Long-form content** (the help manual + changelog) is NOT in the catalog — it's translated as whole per-locale files (`templates/help.<locale>.html`, `data/changelog.<locale>.yaml`) with English fallback (Pass 43.6, `docs/specs/i18n.md` §9). If you materially edit `templates/help.html` structure, mirror it into each `help.<locale>.html` (keep `id`/`href="#..."` anchors byte-identical, leave `<code>`/`<pre>` English).

### Verification Before Declaring Done
Tests written alongside the implementation are regression pins, not correctness
proofs. Never mark a task complete just because those tests pass.

- **UI changes** (templates / CSS / JS / page-rendering routes): start dev
  server, walk the golden path in browser at desktop + mobile (~375px). DevTools
  Network to confirm runtime assumptions (WebP served? srcset picked `-md`? API
  shape matches template?). DevTools Console for errors/warnings. Trigger one
  error path (empty input, missing record, cancelled action), not just happy.
- **Backend-only**: unit tests + a single end-to-end smoke call (curl / invoke job).
- **Tests that import new symbols (or grep for new strings) must run against a
  staged-only tree, not against your working copy.** Whenever a test commit adds
  an `import X` for a new symbol from production code, asserts on a string
  literal the production code is also about to grow, or grep-checks for a class
  / route / decorator name that doesn't ship yet, do `git stash --keep-index &&
  pytest <that test file> && git stash pop` (or stash everything and re-run the
  full suite) before committing. The risk this catches: the production half of
  the change still sits unstaged in the working tree, the tests pass locally
  because the symbol is in scope, and a fresh checkout of `main` lights up red.
  Two CI-red situations during the 2026-05-17 audit cycle (`RomPathNotConfigured`
  in v3.6.8/v3.6.9, `/api/bleed` in v3.6.9) came from exactly this miss.
- State what was verified in the session summary. If something couldn't be
  tested in-session, say so — never imply coverage that wasn't produced.
- Architecturally significant passes (multi-subsystem, reshapes an abstraction,
  touches security/auth/data flow): recommend the user run `/code-review ultra`
  before merging. `/code-review ultra` is a Claude Code slash-command that
  dispatches a multi-agent cloud review of the current branch (or PR number) — it
  is user-triggered and billed; a Claude Code session cannot launch it itself.
  (`/ultrareview` is a deprecated alias for the same command.) Maintainer-only.
- For 3+ step work, post a `step → verify` plan up front (global §12) and tick
  off as you go.

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
- Media fields (boxart, boxart_3d, screenshots, fanart, video, manual) are never replaced during normal scraping — only filled when empty. Screenshots are always appended, never replaced. To get new media: clear it from the edit modal first, then re-scrape. Full Re-scrape mode overrides this and overwrites any field a source actually provides (and re-downloads media whose file is missing from disk); fields no source fills keep their existing value — hand-curated data is not blanked.
- During pre-population, media files are validated on disk — stale DB references (file deleted, filename still in DB) are auto-cleared so scrapers can re-download.

### Scraper fill-only invariant
- Every `apply_*_to_game()` UPDATE in `scraper/scrape_*.py` MUST wrap every `?` in `COALESCE(?, column_name)` so an empty response from IGDB/TGDB/RAWG/etc. preserves the existing scraped or curated value. Bare `publisher = ?, developer = ?` is a bug (Pass 30.4 fix). `scrape_esde.apply_esde_metadata` is the canonical pattern. `tests/test_scrape_fill_only.py` pins the contract for IGDB + TGDB.
- The only exception is Full Re-scrape mode in `hybrid_scraper` (user-requested overwrite of any field a source provides; fields no source fills are preserved, not blanked).

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
`game-modals.js`, `theme.js`, and `templates/base.html` (the two dialog
primitives `showConfirm` / `showModal` live in `base.html` rather than a JS
file so the CSP-nonce script-tag inlines them). Read source for full
signatures.

- **Toasts/dialogs**: `showNotification(msg, type, duration?)` (`utils.js`), `showConfirm(title, msg, onConfirm, opts?)` (`base.html`), `showModal(title, msg, onConfirm?, showCancel?, onCancel?)` (`base.html`).
- **HTTP/storage**: `API.get/post/postForm`, `Storage.get/set/remove/clearAll`.
- **Utilities**: `escapeHtml`, `formatNumber` (thin-space thousands), `formatBytes`, `copyToClipboard`, `debounce`, `throttle`, `DOM.$/$$/create/toggle/delegate`, `DateUtils`.
- **Game modals**: `GameDetailModal.open/close/clearCache`, `GameEditModal.open/save/close`, `HLTBManager.lookup/save/cancel/clear`, `triggerAiFill`.
- **Sticky nav**: `StickyScroll.to(target)`, `.stackPositions()`, `.updateMargins()`. Mark sticky elements containing anchor links with `data-sticky-nav`. Both `stackPositions()` + `updateMargins()` run on DOMContentLoaded in `main.js`; call them again after tab/panel switches that show/hide sticky navs.
- **Themed icons**: `getThemedIcon(key, fallback?)` (defined in `static/js/toast-controller.js`) returns icons matching the current theme (e.g. `'error'` → `❌` on cyberpunk, `✗` on matrix). Keys: job types (`bulk-scrape`, `ra-sync`, `ra-refresh`...), job states (`paused`, `resume`, `complete`, `queued`, `cancelled`, `background`), notifications (`success`, `error`, `warning`, `info`), stats (`stat-success`, `stat-failed`, `stat-skipped`), actions (`starting`, `running`, `cancel`, `save`, `loading`). `background` is a state, not an action — matches the bucketing in `toast-controller.js` and `docs/specs/themes.md` §7. In HTML use `data-themed-icon="key"` — `main.js` auto-populates on DOMContentLoaded.
- **A11y**: `ModalFocusTrap.activate(modalEl, triggerEl, {onEscape, autoFocus})` / `.deactivate()` — WCAG 2.4.3, stacks for nested modals, restores focus to trigger on close.
- **Number formatting**: Jinja `{{ value|format_number }}`; JS `formatNumber(value)`.

Themes (display name on left, `internal key` in backticks): Cyberpunk (`cyberpunk`, default), Matrix (`matrix`), Amber (`amber`), Ocean (`ocean`), Cathedral (`christian`), Blade Runner (`bladerunner`), Elite (`elite`).

---

## Distribution (Patreon Releases)

Two shapes:
- **Source** — small zip; user installs Python + runs `pip install -r requirements.txt`. Cross-platform from one host.
- **Standalone** — PyInstaller bundle (Python runtime + deps + assets baked in). User unzips and double-clicks the platform's launcher (`start.sh` / `start.command` / `start.bat`) — the PyInstaller `retrodb` binary sits next to it. PyInstaller has no cross-compile — must build on the target OS.

```bash
python3 build_dist.py                       # all 3 source ZIPs
python3 build_dist.py linux|macos|windows   # one source ZIP
python3 build_dist.py --standalone          # standalone for host platform
python3 build_dist.py --standalone --cpu-only  # CPU-only standalone (~600 MB, -CPU suffix)
```

- Output: `STAGING_DIR` constant in `build_dist.py` (currently defaults to a maintainer-local path under `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB`; override with `RETRODB_STAGING_DIR` env var — see Pass 39.6 in roadmap).
- Filename: `RetroDB-v{VERSION}-{Platform}.zip` (source) or `RetroDB-v{VERSION}-{Platform}-Standalone.zip`
- Excluded from source ZIPs: see the `EXCLUDE_FILES`, `EXCLUDE_DIRS`, `EXCLUDE_EXTENSIONS` and the `INCLUDE_IMAGE_DIRS` whitelist in `build_dist.py` (the canonical list). At time of writing this excludes user config (`config.py`, `data/{settings,scraper_settings,rom_tools_config,psn_tokens,xbox_tokens}.json`, `data/.secret_key`), the runtime DB (the whole `database/` dir — covers `database/roms.db`; `data/retrodb.db` is also listed as a legacy path, and all `.db*` / `.log` files are excluded by extension), and scraped media (`static/videos/`, plus every `static/images/<dir>/` that is not in `INCLUDE_IMAGE_DIRS = {'hardware','ratings','systems','avatars'}`). Per-platform: only that platform's start script (`start.sh` / `start.command` / `start.bat`).
- Standalone build is driven by `retrodb.spec` (PyInstaller onedir mode). Spec whitelists static subdirs explicitly to avoid sweeping in scraped media; new pip deps that PyInstaller's static analyser can't follow (string-imported via `importlib`) must be added to `HIDDEN_IMPORTS` in the spec.
- `--cpu-only` (Pass 46.3 Part 3) builds the standalone inside an isolated venv under `STAGING_DIR/.cpu-build-venv` (vanilla CPU `onnxruntime` from `requirements.txt` + PyInstaller), so it produces the ~600 MB CPU bundle even on the maintainer's AMD box where `onnxruntime-rocm` is installed system-wide (the two flavours share the `onnxruntime` import name and can't coexist). Artifacts get a `-CPU` filename suffix. Plain `--standalone` inherits whatever onnxruntime is in the current env (GPU/ROCm locally; CPU on a clean checkout, since `requirements.txt` pins vanilla).
- CI standalone build (Pass 46.3 Part 4): `.github/workflows/release.yml` has a `build-standalone` job — a `[ubuntu, macos, windows]-latest` matrix gated behind `workflow_dispatch` + `build_standalone: true` (never fires on an automatic tag push; triples CI minutes). Each runner builds `--standalone --cpu-only` and attaches the zip + SHA-256 to the draft release.
- `./release-standalone.sh` (repo root) automates that standalone CI release: detects the version from `config.example.py`, pushes the `vX.Y.Z` tag (cancelling the redundant push-triggered source run), dispatches `release.yml` with `build_standalone=true`, watches the matrix, and fixes the draft's release notes from `data/changelog.yaml` (the dispatch path leaves a placeholder body). Leaves the release as a **draft** — review and publish manually. Windows/macOS standalones can only come from this CI path (PyInstaller has no cross-compile).

Pre-release checklist: bump version + changelog → ensure `config.example.py` matches any new settings → `python3 build_dist.py` (source) and/or `python3 build_dist.py --standalone` (host platform) → upload from staging.

---

## Reference Documents

- `docs/RETRODB_DESIGN_STANDARDS.md` — Full UI/CSS/JS/API standards (25 sections; §23 controller naming, §25 schema migrations)
- `docs/STANDARDS_ADDENDUM.md` — Version checklist, logging system
- `docs/DEPENDENCY_POLICY.md` — Dependency policy: latest-always (features + security), held-back ledger, major-bump review gate, re-test workflow (read before pinning/capping/major-bumping any dep)
- `docs/ROM_NAMING_STANDARD.md` — ROM file naming
- `docs/specs/` — Per-feature design/contract docs (`api-contracts`, `auth`, `image-pipeline`, `jobs`, `migrations`, `scrapers`, `settings`, `themes`, `i18n`). Read the relevant one before touching that subsystem.
- `docs/theme_contrast.md` — Generated WCAG output (`scripts/audit_contrast.py`); regenerate when theme colors change
- `roadmap.md` — Backlog of refactoring/security/perf/a11y/observability/migrations/CI/ops passes. Includes "Scope notes — considered and dropped". Check before proposing net-new architectural work.
- `audit_hygiene.md` — Portable `/audit`-skill recommendations (not RetroDB-specific)
- `.semgrep.yml` — Documented threat model + excluded upstream rule IDs (read before triaging new audit findings)
- `.gitleaks.toml` — Allowlist for `logs/`, `data/*.json` tokens, admin-editable settings
- `.pre-commit-config.yaml` — per-commit `ruff check --fix` + `gitleaks`, **plus a pre-push gate** (`scripts/ci_local.sh`) that mirrors `.github/workflows/ci.yml` (ruff · import smoke · pytest · i18n freshness · semgrep · pip-audit · lockfile-drift) so a red build is caught locally before it reaches GitHub. Install: `pip install pre-commit` (venv / `--user` / `--break-system-packages` on PEP-668 distros) then `pre-commit install && pre-commit install --hook-type pre-push`. `ruff-format` / `mypy` intentionally excluded; `pytest` runs in the pre-push gate, not per-commit.
- `scripts/ci_local.sh` — the local-CI runner the pre-push gate invokes; run it by hand any time with `./scripts/ci_local.sh` (~40 s warm). Exit 0 = safe to push. A missing tool is reported as a skip (never silently passed); override a failing gate with `git push --no-verify`.

---

## Common DB Access

```python
from services.database import get_db
db = get_db()
games = db.execute("SELECT * FROM games WHERE system_id = ?", [system_id]).fetchall()
```

`safe_column()` in `services/database.py` is the allowlist validator for any
column name interpolated into an SQL f-string.
