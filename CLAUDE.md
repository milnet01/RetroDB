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
1. **Bundle changes into releases** (user, 2026-10-17): a release with one changelog item is too small. A release carries at least 5 changelog items, with no upper limit (user, 2026-10-27: the floor only stops a release going out with one item; an open entry may grow past 10). While the version at the top of `data/changelog.yaml` has no `v<version>` git tag, it is still open: add the change to that entry and keep the version. Otherwise bump `config.py` AND `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`) and open a new entry. Keep `APP_LAST_UPDATE` current either way.
2. Add or extend the changelog entry at top of `data/changelog.yaml`. For a real release, also translate the **recent** entry (current line onward; deep history stays English) into each per-locale `data/changelog.<locale>.yaml` (the human-translation locales in `docs/specs/i18n.md` §9 — a different delivery path from the installed UI-catalog set `services/i18n.py::available_locales()` derives, §3). Repeat `version`, `date`, and every tag verbatim — the `/changelog` route swaps the whole entry in by version, so anything omitted is dropped, not inherited (Pass 43.6). Skip for internal/no-release bumps.
3. Rebuild CSS if any `static/css/**.css` changed: `python3 build_css.py`
4. Rebuild JS if any bundled `static/js/*.js` changed: `python3 build_js.py`
5. Run tests if any `services/*.py` or `scraper/*.py` changed: `python3 -m pytest`
6. Regenerate lockfile if `requirements.txt` was edited: `uv pip compile requirements.txt --strip-extras --generate-hashes --universal -o requirements.lock` (`--universal` keeps Windows-only deps in a lock compiled on Linux, Pass 59.99; Pass 57.3 moved the compiler from pip-tools to uv — pip-tools breaks against pip 26; Pass 39.4 — `install.py` prefers `--require-hashes` when `requirements.lock` is present and falls back to `requirements.txt` otherwise; keep the lockfile current so the secure path stays the default). Dependencies track **latest-always** (features + security); a hold below latest is allowed only for a documented breakage recorded in `docs/DEPENDENCY_POLICY.md` — read it before pinning, capping, or bumping a major.
7. Update this file if change adds/removes/renames routes, templates, bundled JS, CSS files, or alters page/asset wiring contracts
8. Wrap any new user-facing string for i18n and regenerate catalogs — see `docs/specs/i18n.md` §2/§4/§6/§7/§9:
   - Templates `{{ _('...') }}` / `{% trans %}`; Python `flash(_('...'))` / `error(_('...'))`. Never a bare `%` in a template msgid: Jinja's newstyle gettext formats it and the page fails with "incomplete format" — write `(_('Completeness') ~ ' %')`.
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

### Contract Reviews (Global Rule 14)
Rule 14's contract gate is **cancelled for this project** (user,
2026-10-17); record each such edit as "no gate: cancelled by RetroDB
CLAUDE.md". The practice kept instead: run `review-contract` on a spec, plan
or standard only when its author is unsure of details in the planned work,
and say which details. Otherwise the code and the user's viewing of the result
are the review.

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
- `units_sold` (INTEGER, migration 023) is filled only by the AI — scrape gap-fill and AI Fill; `scrape_ai.parse_units_sold()` turns "2.4 million" etc. into an int.
- `release_dates` (TEXT, migration 024) is a JSON object of region code → date (`{"JP": "2002-11-17", "NA": "2002-11"}`), filled only by the AI — scrape gap-fill and AI Fill. `services/release_dates.py` parses, stores and displays it; `release_date` stays the row's own release.
- RPCS3 compatibility (PS3) is never stored: `services/rpcs3_compat.py` reads the local RPCS3's `GuiConfigs/compat_database.dat` (re-read when it changes) and looks games up by `games.disc_serial`. Local ROMs only, never imported games.
- Regional versions (PASS-59-106): only `services/version_groups.py` links rows through `games.version_group_id`. `_build_games_query` shows one row per group unless `group_versions=False`. Contract: `docs/specs/PASS-59-106-regional-versions.md`.

### Media handling
- Media fields (boxart, boxart_3d, screenshots, fanart, video, manual) are never replaced during normal scraping — only filled when empty. Screenshots are always appended, never replaced. To get new media: clear it from the edit modal first, then re-scrape. Full Re-scrape mode overrides this and overwrites any field a source actually provides, media included, unless its "Keep existing media" option is ticked (then media whose file is on disk is kept); fields no source fills keep their existing value — hand-curated data is not blanked.
- Slipcase box faces (PASS-59-142) are not a media field: `games.box_faces` holds a JSON record and `<IMAGE_PATH>/box_faces/` the WebP faces. Only `services/box_faces.py` writes them (an editor's import, fill-only unless replaced); scraping, Clear and the image jobs never touch them, and `boxart_3d` is separate. Spec: `docs/specs/PASS-59-142-box-file-import.md`.
- During pre-population, media files are validated on disk — stale DB references (file deleted, filename still in DB) are auto-cleared so scrapers can re-download.

### Scraper fill-only invariant
- Every `apply_*_to_game()` UPDATE in `scraper/scrape_*.py` MUST wrap every `?` in `COALESCE(?, column_name)` so an empty response from IGDB/TGDB/RAWG/etc. preserves the existing scraped or curated value. Bare `publisher = ?, developer = ?` is a bug (Pass 30.4 fix). `scrape_esde.apply_esde_metadata` is the canonical pattern. `tests/test_scrape_fill_only.py` pins the contract for IGDB + TGDB.
- Three exceptions. Full Re-scrape mode in `hybrid_scraper` overwrites any field a source provides (fields no source fills are preserved, not blanked). AI Fill renames a game to the official title the AI gives (`docs/specs/scrapers.md` §12), keeping the old name as an alternate title. And the title runs the other way: with `games.title_locked = 1` no scrape writes `title` or `sort_title`, Full Re-scrape included — the four title writes are `CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END` (PASS-59-159 §4.3).

### Multi-rating system (9 systems)
Moved to `.claude/rules/ratings.md`, which loads when a matching file is read. Read it before touching ratings, the edit modals or the scrapers.

### Self-updater (PASS-59-169)
- The block at the top of `app.py` hands `--apply-update` to `updater_apply.py` before any other import; keep it first (the rest of `app.py` opens and migrates the database). `updater_apply.py` stays standard-library only: the standalone binary runs it inside its own bundle.
- Install runs the NEW version's helper, so a change to the plan file (`plan_version`) or to which paths an update may write (`updater_apply.PROTECTED`) must stay readable from the previous release's `services/updater.py`.
- The updater picks release assets by name (`RetroDB-v{V}-{Platform}.zip` + `SHA256SUMS.txt`, `RetroDB-v{V}-{Platform}[-CPU]-Standalone.zip` + `.sha256`); renaming them in `build_dist.py` / `release.yml` stops updates. Spec: `docs/specs/PASS-59-169-self-updater.md`.

### Cheats (PASS-59-155)
- `services/cheats.py` owns the store (`data/cheats/`, gitignored): `packs/` is replaced whole by a download, `own/` holds imports and wins on a name clash. Routes in `routes/cheats.py`; pack downloads ride the player downloads job as `_cheats_<pack>`.
- The emulator's files are the record of which cheats are on; RetroDB keeps no table. Never overwrite a cheat file already in DuckStation's or PCSX2's cheats folder (INV-4).
- The game page's Cheats panel (`static/js/game-cheats.js`) sits full width under the card row; Settings > Emulators has the Cheats section. Spec: `docs/specs/PASS-59-155-cheats.md`.

### RetroAchievements sign-in
- `services/ra_sign_in.py` owns it: the password is sent once and dropped, and the token lives in `user_platform_tokens` under `retroachievements`, per user. The web API key cannot sign RetroArch in.
- A token reaches RetroArch only in a launch's run layer (`session_keys`), never the base cfg or a game's cfg; `_PROTECTED_KEYS` holds the `cheevos_*` keys so a menu save cannot copy one.
- DuckStation and PCSX2 take no sign-in for one launch, so `services/ra_standalone.py` writes it to their main settings files at Play and takes it back when that user signs out or a signed-out user plays. A sign-in from an emulator's own menu is never overwritten. `emulator_written_settings` holds a hash of the token, never the token. DuckStation's token is encrypted as its `EncryptLoginToken` does; if DuckStation changes that, it asks the user to sign in again.

### Page wiring
- A box that takes a path gets `browse_button()` from `_macros/browse_button.html` beside it, in a `.path-input-row`, and a row in `tests/test_path_browser.py`. The button shows for admins only: `/api/settings/browse-paths` can list any folder on the computer.
- Both `/games` (Library) and `/system/<id>` use `AllGamesController` — keep them in sync.
- The game page's Previous / Next links follow the list it was opened from (`?from=library`, else its console). `AllGamesController` saves each list's filter and sort params per tab via `RetroDB.saveGameNavContext`; the game page sends them to `/api/games/neighbors`.

---

## CSS / JS Build Contracts

- CSS: edit `static/css/<category>/<file>.css`, then `python3 build_css.py` to rebuild `main.min.css`.
- JS: edit `static/js/<file>.js`, then `python3 build_js.py` if it's bundled. Never edit `core.bundle.js` / `games.bundle.js` directly — generated output.
- Bundles: `core.bundle.js` (every page) and `games.bundle.js` (game-centric pages only). Templates that need the games bundle MUST set `{% set needs_games_bundle = true %}` at the template's top level — before the first `{% block %}`, so `base.html` sees it at render time. An intervening `{% from %}` import is fine.
- Adaptive layout (PASS-59-104): a page opts in with `{% set adaptive_layout = true %}` (same placement as `needs_games_bundle`) and wraps its content in an element with class `page-box`; the rules are `docs/RETRODB_DESIGN_STANDARDS.md` §7 "Page Width — adaptive".
- Cache-busting: `build_css.py` / `build_js.py` write `static/asset_manifest.json` with SHA-256 prefixes. Reference assets via `{{ asset_url('js/core.bundle.js') }}` (Jinja global from `services/assets.py`). Fallback is `?v={APP_VERSION}`.
- CSS rules: never duplicate external classes inline; use variables from `core/variables.css` (no hardcoded colors); promote any style used on 2+ pages to external CSS.
- Sticky bars: a page-level `position: sticky` bar sets `top: var(--sticky-top)`, or `calc()` from it, never `top: 0`. On a phone the fixed header covers the top of the window (PASS-59-165). A header that sticks inside its own scrolling box keeps `top: 0`. Nothing checks this.

---

## Non-Obvious JS / Template Contracts

Moved to `.claude/rules/js-template-contracts.md`, which loads when a matching file is read. Read it before touching a template `<script>` block or `static/js/`.

---

## Distribution (Patreon Releases)

Moved to `.claude/rules/distribution.md`, which loads when a matching file is read. Read it before touching a release build, the launchers or the app icons.

---

## Reference Documents

- `docs/design.md` — What RetroDB is for, its threat model, its subsystems and the spec that owns each
- `docs/decisions/` — Decision records (threat model, fill-only scraping, HTTP-200 error replies); index in its `README.md`
- `docs/RETRODB_DESIGN_STANDARDS.md` — Full UI/CSS/JS/API standards (25 sections; §23 controller naming, §25 schema migrations)
- `docs/STANDARDS_ADDENDUM.md` — Version checklist, logging system
- `docs/DEPENDENCY_POLICY.md` — Dependency policy: latest-always (features + security), held-back ledger, major-bump review gate, re-test workflow (read before pinning/capping/major-bumping any dep)
- `docs/ROM_NAMING_STANDARD.md` — ROM file naming
- `docs/specs/` — Per-feature design/contract docs (`api-contracts`, `auth`, `image-pipeline`, `jobs`, `migrations`, `scrapers`, `settings`, `themes`, `i18n`). Read the relevant one before touching that subsystem.
- `docs/theme_contrast.md` — Generated WCAG output (`scripts/audit_contrast.py`); regenerate when theme colors change
- `roadmap.md` — Backlog of refactoring/security/perf/a11y/observability/migrations/CI/ops passes. Includes "Scope notes — considered and dropped". Check before proposing net-new architectural work.
- `audit_hygiene.md` — Portable `/audit`-skill recommendations (not RetroDB-specific)
- `.semgrep.yml` — Documented threat model + excluded upstream rule IDs (read before triaging new audit findings)
- `.gitleaks.toml` — scan scope (`logs/`, `data/*.json` tokens, admin-editable settings, media) plus one anchored model-name rule. A false positive in tracked source is excused per finding: inline `gitleaks:allow`, or its fingerprint in `.gitleaksignore` — never a path allow (Pass 59.87)
- **Git hooks** and `scripts/ci_local.sh` (the pre-push gate; run `./scripts/ci_local.sh` by hand, or `--docs` for the documentation checks alone) — setup, settings and skip rules are in `.claude/rules/git-hooks.md`. Read it before touching the hooks or pushing past a failed gate.

---

## Common DB Access

```python
from services.database import get_db
db = get_db()
games = db.execute("SELECT * FROM games WHERE system_id = ?", [system_id]).fetchall()
```

`safe_column()` in `services/database.py` is the allowlist validator for any
column name interpolated into an SQL f-string.
