# RetroDB Roadmap

Tracking file for refactoring, security, performance, and quality work
identified in successive reviews (2026-04-21 onwards). Items are ordered so
that earlier passes establish the patterns used by later ones (service-layer
carve-outs, response helpers, etc.).

> **Find a specific pass:** `grep -nE "^#### Pass [0-9]+(\.[0-9]+)?(\.[A-Z])?" roadmap.md` lists every pass with its line number. For free-text search use `git log --grep "Pass 41.6"` or `grep "FU.2" roadmap.md`.

## Table of contents

- [§ Active](#active) — open work, grouped by theme
- [§ Doc-sweep history](#doc-sweep-history) — meta-log of cold-eyes / indie-review sessions
- [§ Done index](#done-index) — landed passes, organised by shipped version
- [§ Scope notes — considered and dropped](#scope-notes--considered-and-dropped) — work explicitly excluded
- [§ Periodic Independent Review](#periodic-independent-review) — cadence and procedure for the multi-agent audit

Each item lists:
- **Target** — file(s) and approximate line range / LOC
- **Why** — the specific issue (oversized function, duplicated logic, mixed
  concerns, long conditional chain)
- **Plan** — concrete extraction target: new file, class/function name, what
  moves where
- **Est. reduction** — rough LOC delta in the source file
- **Status** — `todo` / `in-progress` / `done`

Open items are grouped by theme below. The 2026-04-24 Tier-1 indie-review
sweep (Pass 40) is fully landed (v3.4.1 → v3.5.0) — current highest-priority
active work is the FU.x follow-up chain (CSP enforcing, srcset, WebP
migration), the Pass 38.1 hybrid-scraper fallback-loop carve-out, and the
Pass 47.x fundraising-platform chain.

The compact "Done index" near the bottom lists landed passes by version —
detail lives in git history (`git log --grep "Pass NN"`).

See "Scope notes — considered and dropped" for items deliberately excluded,
and "Periodic Independent Review" at the very end for the cadence on
re-running the multi-agent audit that surfaces new passes.

---

<a id="active"></a>

## Active

Grouped by theme. Within each theme, items ordered by priority (CRITICAL →
HIGH → MEDIUM → LOW). The 2026-04-24 indie-review Tier-1 sweep (Pass 40)
fully landed. FU.2 (grid-card srcset, v3.6.18) and FU.3 (WebP migration,
v3.6.19) have also landed; the remaining top-priority work is FU.1 phase B/C
(flip CSP from report-only to enforcing and remove `unsafe-inline`), the
Pass 38.1 hybrid-scraper fallback-loop carve-out, and the Pass 47.x
fundraising-platform chain.

<a id="doc-sweep-history"></a>

### Cold-eyes 2026-05-18 (doc-sweep history)

> Docs reviewed: 12. Reviewer lanes: 7 (contracts / design-standards /
> ops-install / roadmap-active / roadmap-history / dev-hygiene / spec-gaps).
> Loops to clean: 2. Findings fixed: 30 verified + 8 new spec docs authored.
> Audit trail; not actionable open work — see git log around 2026-05-18
> for per-file diffs.

Full `/cold-eyes` documentation sweep with parallel per-lane reviewers,
all severities folded in, two verify loops to convergence.

- **CLAUDE.md** — 8 fixes: showConfirm/showModal definition site (`templates/base.html` not utils/main/toast/game-modals); EXCLUDE_FILES list rewrite (full set + `data/.secret_key` + INCLUDE_IMAGE_DIRS semantics); STAGING_DIR default path; "22 sections" → "25 sections"; lockfile-hashes "MUST" softened to "prefers, falls back"; `/ultrareview` annotated as Claude Code skill; `data-sticky-scope` claim removed (not implemented); `getThemedIcon` location corrected to `static/js/toast-controller.js`; `--break-system-packages` made cross-platform-conditional.
- **README.md** — 5 fixes: Python floor 3.8 → 3.10; system count 277 → 150+ (verified against `config.py`); Cathedral display ↔ `christian` token mapping documented; backup-on-update list expanded; end-user-vs-dev install ambiguity resolved.
- **CONTRIBUTING.md** — 5 fixes: Python floor 3.8 → 3.10; `YOUR_USERNAME` placeholder annotated; relative link `docs/RETRODB_DESIGN_STANDARDS.md` corrected; stale 60-line architecture tree replaced with one-line `ls`-pointer; CI checklist expanded (pip-audit + lockfile-drift).
- **LEGAL.md** — 2 fixes: LICENSE pointer added at top; PSN URL added.
- **docs/STANDARDS_ADDENDUM.md** — 3 fixes: stale `1.20.1` example refreshed to `3.6.14`; "MAJOR.FEATURE.PATCH" → "MAJOR.MINOR.PATCH"; "5 log categories" → "4" (`system` dropped per Pass 41.3.C); "should be incorporated" TODO banner removed.
- **docs/RETRODB_DESIGN_STANDARDS.md** — 9 fixes: §13 `showToast` → `showNotification`; §20 `main-new.css` → `main.css` (3 sites) + `CSS_ORDER` clarified as canonical; §16 `system-type-badge` declared canonical (legacy `.system-type-tag` flagged); §21 changelog date format `YYYY/MM/DD` → `YYYY-MM-DD`; §6.3 `--bg-darker` → `--bg-dark`, `--border-color` → `--card-border` (real CSS vars); §20 `launch-indicator.css` added to inventory; §8 step 7 "rebuild bundle" corrected (`theme.js` not bundled).
- **docs/PROXY-DEPLOY.md** — 4 fixes: `main.py` → `app.py` (broken on copy-paste); port `8765` → `5000` (4 sites); `app.py:153` line-number anchor replaced with symbol name; `MAX_UPLOAD_BYTES` vs `client_max_body_size` warning added.
- **docs/ROM_NAMING_STANDARD.md** — 4 fixes: `article_placement` setting caveat added to Core Principle 1; edition-vs-publisher parser-caveat added; region table annotated as curated subset; M3U template `{}` notation reconciled with the rest of the doc.
- **docs/README.md** — replaced root-README duplicate with a proper docs-folder index pointing at the 8 new specs.
- **audit_hygiene.md** — 4 fixes: "13 upstream rules" → "14" (`.semgrep.yml:34` also fixed); line-range "40-80" → grep-anchor pattern; "lines 18-34" → grep-anchor; mypy marked CI-only; §3 and §4 marked "Proposed — not yet implemented".
- **roadmap.md** — 7 fixes: `/mnt/Emulators/` → `/mnt/Games/` in §How-to-run reviewer brief (was sending 14 agents to wrong path); `services/security.py` path fix in §How-to-run partition; Pass 39.6 status-path narrative rewritten with the 2026-05-08 hub-move context; Done-index intro adds "pass numbers reflect planning order" + "LOC numbers are at-landing" notes; Pass 41.13 status sub-letter labels fixed (B is HIGH not MEDIUM); Pass 41.5b → 41.5.B and Pass 41.13c → 41.13.C (consistent suffix convention); new `### v3.5.x — Tier-2 hardening` + `### v3.6.x — multi-emulator launch + audits` Done-index rollup blocks added covering ~60 passes that had landed but were missing from the index.
- **.semgrep.yml** — 1 fix: "13 excludes" → "14" in the Verified-2026-04-21 header note.
- **New specs authored** — 8 files in `docs/specs/` covering subsystems that had no contract doc: `jobs.md` (background-job lifecycle, singleton-lock contract, recovery, toast-UI contract), `scrapers.md` (hybrid orchestration, fill-only invariant, COALESCE pattern, source inventory), `auth.md` (roles, permission matrix, per-user partitioning, session model, CSRF), `settings.md` (5-store layering + precedence + atomic-write contract), `api-contracts.md` (envelope, ETag, gzip, rate-limit buckets, status-code policy), `image-pipeline.md` (ESRGAN + Lanczos + WebP variants + dedup + ROCm trap), `migrations.md` (runner + numbering + backup + rollback), `themes.md` (full theme contract: CSS layer + JS ThemeManager + canvas effects + themed icons + FOUC prevention).
- **CSRF exempt-set duplication** — `auth.md` declared canonical owner; `api-contracts.md §9.1` now points at it instead of listing the set independently.
- **MCP feedback** — captured in `/mnt/Games/Scripts/Linux/RetroDB_Ants_MCP_Feedback.md` (appended to the existing test-audit feedback). Two HIGH suggestions: case-insensitive contract-name matching in `cold_eyes_partition` + `project_layout`; `data/changelog.yaml` recognition alongside `CHANGELOG.md`. One correctness call-out: `cold_eyes_partition` summary field mentioned files not in `doc_paths`.
- **Source**: cold-eyes-2026-05-18 docs sweep.

#### Cold-eyes 2026-05-18 sweep #2

Second full `/cold-eyes` sweep on the same day after the 2026-05-18 #1
landed — driven by user request to re-cover all lanes after the FU.x
follow-up chain shipped (v3.6.18 / v3.6.19 / v3.6.20). Two loops to
convergence. 20 doc files edited; ~100 findings across all severities
verified and fixed in-place. Per-doc highlights:

- **CLAUDE.md** — 7 fixes: DB path corrected (`database/roms.db` not
  `data/retrodb.db`); `/ultrareview` glossed inline; staging-binary
  description corrected; theme list rewritten "display-name first"; the
  hard-coded `/home/ants/Pictures/` operator path removed; `background`
  themed-icon bucketed under job-states; theme list deduplicated.
- **README.md** — 3 fixes: backup-on-update list expanded into
  three-thing list (database/data/config); new "Deployment" section
  pointing at `docs/PROXY-DEPLOY.md`; theme naming order canonicalised
  to "Cathedral (`christian` internal key)".
- **CONTRIBUTING.md** — 5 fixes: clone URL rewritten with upstream +
  fork variants; Python-version row delegated to README; `database/roms.db`
  delete now carries a backup-first warning + `RETRODB_DB_PATH` alternative;
  `30 route files at time of writing` snapshot removed; CI checklist
  rewritten as full blocking-list (six checks, every one hard-fail).
- **SECURITY.md** — 1 fix: "thank-you in CONTRIBUTING.md" promise rewritten
  to "Credit in the changelog (unless you ask to remain anonymous)".
- **LEGAL.md** — 2 fixes: trademark list annotated as illustrative;
  duplicate closing License section removed.
- **roadmap.md** — 6 fixes: TOC + grep recipe added at top; `<a id="…">`
  anchors added; `Pass 41.6.A-extend` renamed to `Pass 41.6.D`; lowercase
  `41.13c` survivor → `41.13.C`; §Active opener rewritten; v3.6.18 / 19 / 20
  added to v3.6.x rollup; Cold-eyes 2026-05-18 #2 entry added (this block);
  doc-sweep meta heading restructured + emoji dropped.
- **docs/RETRODB_DESIGN_STANDARDS.md** — 6 fixes: §22 X-XSS-Protection
  line replaced with "intentionally not set" + rationale; §20 CSS tree
  added `themes.css` + `fonts.css` to `core/`; §22 CSP "Future
  recommendation" replaced with FU.1-in-progress note; §23 partials/macros
  rewritten in present tense (real dirs); status vs neon colour tokens
  split into distinct token families with explicit guidance on which
  controls which; standalone doc-version footer dropped.
- **docs/STANDARDS_ADDENDUM.md** — 2 fixes: stale `3.6.14` / `2026-05-17`
  example replaced with `X.Y.Z` / `YYYY-MM-DD` placeholders; §16 → §17
  changelog-tags anchor fix.
- **docs/specs/api-contracts.md** — 8 fixes: 202 row now reserved /
  not-currently-emitted; 422 row marked aspirational + new §3.2 describes
  the legacy auth-validator shape; bulk-scrape paths corrected to
  hyphen-not-slash form; `/ready` shape documented with `str(e)` carve-out;
  §1 cross-reference dropped the wrong §10 claim; CSP table row updated
  to FU.1 chain; `_rate_limit` "in addition to" wording; CSRF "HMAC-equivalent"
  rewritten as "per-session random token, constant-time compared".
- **docs/specs/auth.md** — 5 fixes: §11 cross-reference corrected to
  api-contracts.md + §22; §9 change-password bucket now names the shared
  `_login_attempts` OrderedDict + LRU eviction; §9 force-change rate-limit
  justification rewritten with explicit carve-out condition;
  `TestPass45_1*` glob replaced with exact class name; §3 viewer line
  rewritten; admin_required/editor_required asymmetric-on-`/api/*` warning
  callout added; §8 PBKDF2 legacy format shown side-by-side.
- **docs/specs/image-pipeline.md** — 5 fixes: FU.2 + FU.3 "deferred"
  paragraphs rewritten as "v3.6.18/19 landed" with contract detail;
  new §12.1 `WebPMigrateJob` section documenting worklist (`_SOURCES` +
  `_CONVERTIBLE_EXTS = {.jpg, .jpeg, .png}`), per-file order, disk-space
  precheck (runs inside `_run()`, not `start()`), resume by adopting
  existing `.webp` siblings; format-decision table cleaned (non-image
  rows replaced with prose note); §11 `rom_tools.py` line numbers
  replaced with grep recipe; §3 `MAX_IMAGE_PIXELS` clarified as
  process-global singleton (import-order-dependent); §12 `ImageResizeJob`
  failure-handling bullet added.
- **docs/specs/jobs.md** — 8 fixes: §2 inventory "Ten singletons" →
  "Eleven singletons" + new `WebPMigrateJob` row; TL;DR count updated;
  §4 `_retry_on_locked` "5×" → "3× by default; progress + commit override
  to 5×"; §5 lock table de-collapsed into per-singleton rows; §6 magic
  300 s → `FETCH_TIMEOUT = 300` named constant; §8 candidate list
  enumerated + `webp_migrate_job` carve-out called out; §8 resume-class
  count corrected (seven) and the four non-resuming jobs named; §13
  invariant 1 softened (counter reads under lock, derived fields can be
  inside the same `with`); §11 step 4 `getTypeFromKey` → `getTypeConfig`;
  §6/§13 Pass 41.6 sub-letter cites replaced with prose pointers.
- **docs/specs/migrations.md** — 7 fixes: §6 explicit callout for
  migration 012's inline `conn.commit()` + the crash-window semantics
  (rewritten to match runner code precisely); §3 quoted error string;
  §10 `_add_column_if_missing` strict helper required for new migrations;
  §11 smoke-test command rewritten with `config.DB_PATH` + four boot
  PRAGMAs; §13 heading rename; §13 migration 012 row caveat; §4 Pass 41.2
  narrative rewritten with worked-exception framing; `_foreign_key_count`
  helper home clarified (per-migration local in 011, not in `_helpers.py`).
- **docs/specs/scrapers.md** — 6 fixes: §2 AI key names corrected to
  `ai_*` prefix; §2 RAWG key clarified (`rawg` JSON, `RAWG_API_KEY` fallback);
  §5 fill-only invariant split into "scraper UPDATEs" (COALESCE) vs
  "AI Fill" (bare `field = ?` + `should_apply` filter) with audit-column
  exception called out; §3 fallback breaker list narrowed to actual five
  sources; §4 `user_score` FIELD_SOURCES row corrected (rawg → igdb →
  screenscraper → ai); §4 `save_type` carve-out described (`['manual']`
  sentinel); §6 priority-boost formula rewritten.
- **docs/specs/settings.md** — 9 fixes: explicit blockquote that
  `settings_manager.py` lives at project root (no `services.` prefix);
  §322 line citation; "Convention (not enforced by code)" framing for
  the validators-at-route-layer rule; six-tab partial paths replacing
  stale `templates/settings.html`; `static/js/settings-page.js` /
  `emulators-settings.js` replacing non-existent `static/js/settings.js`;
  canonical test home `tests/test_launch_settings_validators.py` (not
  `test_settings_validators.py`); `validate_rom_tools_value` testability
  entry added; `_deep_merge` list-replacement caveat; store-count
  reconciled to six (matches table).
- **docs/specs/themes.md** — 5 fixes: theme picker path corrected to
  `templates/_settings_tabs/library.html`; "Elite 1984" → "Elite"
  canonicalised across §2 / §8 / §10; `26 keys` → "see §7 category table";
  last "See also" path updated.
- **docs/PROXY-DEPLOY.md** — 5 fixes: opener softened ("required when
  behind a proxy"); ProxyFix multi-hop note now acknowledges patch-every-upgrade
  burden + env-var feature-request pointer; upload-limits cite corrected
  to `config.py` (was `app.py`); pass-ID anchor genericised; Related-section
  grep pointer instead of bare ID.
- **docs/ROM_NAMING_STANDARD.md** — 7 fixes: M3U folder/M3U structure
  example rewritten with `(USA)` tags everywhere consistent (top, middle,
  table); disc-file naming rule clarified (folder + M3U must agree, disc
  base names free); region table annotated against `region_re` actual
  allowlist; validation-rules list extended with issue codes; meta-apology
  parenthetical deleted; archive-scanner staging folder corrected to
  hard-coded `tempfile.gettempdir()/retrodb_m3u_staging` (not configurable);
  Systems Classification points at `services.game_utils::get_system_type`;
  standalone version + date footer dropped.
- **docs/README.md** — 1 fix: `docs/requirements.txt` description corrected
  (historical copy of project deps, not docs-build deps).
- **audit_hygiene.md** — 1 fix: "0 actionable findings" claim dated +
  "verify before quoting" disclaimer added.
- **Source**: cold-eyes-2026-05-18 sweep #2 (post-FU.x).

#### Cold-eyes 2026-05-18 #2 — deferred items folded into roadmap

The sweep surfaced several items the cold-eyes skill flags as code-side
(out of scope for a docs-review skill) or as known follow-up gaps. They
are tracked here so the next pass picks them up:

- **`services/jobs/base.py::request_shutdown` candidate list** — does
  not include `webp_migrate_job` today, so SIGTERM mid-WebP-migration
  doesn't actively cancel the job (relies on `mark_jobs_interrupted` +
  user-driven re-run on next boot). Decide: add `webp_migrate_job` to
  the candidate list (active cancel on SIGTERM), or document the carve-out
  in the spec as intentional. Spec currently documents the carve-out.
- **`services/jobs/base.py:270` code comment** — says `data/job_locks/`
  but the resolved path is `database/job_locks/`. Stale code comment.
- **`services/jobs/base.py:375` resume-helpers docstring** — says "Six
  job classes" but grep across `services/jobs/*.py` for
  `def resume_from_params` returns seven. Doc on the spec side now says
  seven; sync the code-side docstring.
- **`tests/test_migrations.py:351-353`** — comment encodes the inverted
  boot order (`ensure_user_tables` after `init_database`). The test
  passes because it manually skips `ensure_user_tables`, but the comment
  contradicts `app.py:1545-1546`. Update the comment.
- **`build_dist.py:38-40` `STAGING_DIR` default** — still points at the
  retired `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB` drive. The
  env-var override (`RETRODB_STAGING_DIR`) covers production use, but the
  default is dead. Bump the default to the current `/mnt/Games/…` path
  or to a portable home-dir fallback.
- **`services/jobs/webp_migrate.py` disk-space precheck position** —
  precheck runs inside `_run()` after the worker spins, so `start()`
  returns `success: True` even when the precheck will fail. Move the
  precheck into `start()` so the user sees the refusal synchronously.
- **`scraper/rom_tools.py:804`** — `extract_folder.rglob(...)` runs
  without the `_safe_under_root` guard the other rglob sites carry. The
  root is a tempdir (not user-controlled) so the risk is bounded, but
  the invariant should explicitly cover this case (either guard it or
  document the carve-out).
- **`retrodb.spec:96` vs `build_dist.py:77` `INCLUDE_IMAGE_DIRS`** — the
  PyInstaller spec bundles `static/images/controllers/` into standalone
  builds; the source ZIPs omit it. Decide whether controller images
  ship with both shapes (add to `INCLUDE_IMAGE_DIRS`) or neither (drop
  from `retrodb.spec`).
- **`templates/base.html` line cite for `<meta name="csrf-token">`** —
  `api-contracts.md` cites lines 340-352 (the fetch patch); the meta tag
  itself is at line 27. Minor — refine the cite.
- **`docs/specs/auth.md` — no TOC** on a 508-line spec; same for several
  other specs >300 lines. Token-tax for LLM implementers; add anchor lists.
- **`CLAUDE.md` — no TOC** on a 191-line file with 7 H2s.
- **`atomic_write_bytes` vs `atomic_write_text` clarification** — the
  settings spec describes `.secret_key` write semantics as going through
  `atomic_write_bytes(..., mode=0o600)`; the actual call is
  `atomic_write_text(..., mode=0o600)` at `app.py:118-119`, and
  `atomic_write_bytes` itself defaults to `0o644`. Spec wording needs
  a final pass.

- **Source**: cold-eyes-2026-05-18 sweep #2.

### Carry-overs from landed passes

#### Pass 2 — continue gradual migration of `jsonify({'success': …})` → `success()` / `error()`

- **Target**: partially-swept routes (`bonus_discs`, `games`, `scraper`,
  `scrape_logs`, `settings`, `systems`) and HTTP-200-only
  (`platform_import`, `steam_achievements`, `xbox_achievements`,
  `trophies`). `games_hltb` completed as part of Pass 3 (v2.83.8).
- **Why**: the helpers are landed and wire-format-compatible with every
  existing call site. Gradual migration per roadmap guidance — pick files
  up as they are touched for other work, or knock them off opportunistically
  in future patch bumps.
- **Plan**: convert `jsonify({'success': True, ...})` → `success(...)` and
  `jsonify({'success': False, 'error': '...'})[, code]` → `error('...', code)`.
  Non-standard payloads (e.g. `{'configured': True, 'error': '...'}` without
  `success`, or scanner-result passthroughs) stay as raw `jsonify` —
  document here if discovered.
- **Status**: in-progress

#### Pass 12.5 — FTS5 virtual table for `games.title` + `alternate_titles` (MEDIUM, L)

- **Target**: search endpoints (`routes/games_search.py::api_games_find`
  and similar), plus filter pages doing `WHERE title LIKE '%q%'`.
- **Why**: `LIKE '%q%'` on a 10k-row games table with no index is an
  O(N) scan every time.  SQLite FTS5 with a porter tokeniser brings
  this to sub-20 ms on the same dataset.
- **Plan**:
  1. Define a virtual table `games_fts(title, alternate_titles, content='games', content_rowid='id')`.
  2. Populate from `games` and keep in sync via INSERT/UPDATE/DELETE triggers.
  3. Replace `WHERE title LIKE` with `WHERE id IN (SELECT rowid FROM games_fts WHERE games_fts MATCH ?)`.
- **Caveat**: FTS5 doesn't replace prefix LIKE for all cases (autocomplete,
  substring mid-word).  Keep LIKE where required.
- **Source**: <https://www.sqlite.org/fts5.html>
- **Status**: deferred — L-sized; gated on a benchmark run that confirms
  `WHERE title LIKE '%q%'` is actually the hot path on a realistic
  10k-row library.  `RETRODB_SLOW_QUERY_MS=100` (Pass 12.4) is the
  instrument to collect that data.

#### Pass 14.2 — Gradual type hints on high-risk modules (LOW, L)

- **Target**: `scraper/metadata_merger.py`, `services/game_query.py`,
  `routes/games.py`.
- **Why**: largest / most-called modules in the codebase. Type hints on
  function signatures make IDE autocomplete and `mypy` checks meaningful.
  Currently the codebase has ~0% type coverage.
- **Plan**: adopt one module at a time.  Start with signatures (`-> dict`,
  `-> list[dict]`, `int | None`) then internal variables only where
  they help.  Add `mypy` as a CI-only check (not pre-commit) with
  `--ignore-missing-imports`.
- **Status**: deferred (LOW priority, L sized — its own pass)

---

### Pass 48 — audit + indie-review fix-pass deferrals (2026-06-05)

> Source: `/audit` (static analysis) + `/indie-review` (14-subsystem cold
> review) run at v3.6.28. The bulk of findings landed directly in v3.6.29
> (see changelog). These are the items deliberately deferred — design
> decisions, risk-of-regression LOWs, and INFO-grade notes — calibrated to the
> single-user-localhost threat model. False positives logged to
> `.ants_review_falsepos.jsonl` (incl. the `get_db()`-vs-`g.db` mis-read).

#### Pass 48.1 Force-rescrape "replaces everything" reconciliation (MEDIUM, M)
- **Status**: done (v3.6.32) — user chose "keep current behaviour, fix the
  docs". CLAUDE.md media-handling claim softened to "overwrites any field a
  source provides; fields no source fills are preserved". Force mode now also
  validates the DB's existing media against disk and NULLs references to deleted
  files (`hybrid_scraper` force branch) so they re-download instead of being
  restored by COALESCE.
- **Lane**: scraper orchestration (Lane 3)
- **Finding**: `hybrid_scraper` force_overwrite mode skips pre-population but the
  final save still wraps every field in `COALESCE(?, column)`, so a field no
  source fills keeps its old DB value. CLAUDE.md claims Full Re-scrape "replaces
  everything" — it only replaces fields a source actually provides, and the
  stale-media-on-disk clear is also skipped in force mode.
- **Decision**: either save raw (non-COALESCE) for non-media text fields in
  force mode AND re-run the disk-validation/stale-clear, OR soften the doc claim
  to "overwrites any field a source provides." Design call — not a silent fix.

#### Pass 48.2 media_cleanup orphan-match precision (LOW, S)
- **Status**: done (v3.6.30) — substring reference test replaced with a
  basename-equality match (still protects path-form refs); `referenced_files`
  audited (bare filenames / container paths). Regression: `tests/test_pass48_media_cleanup.py`.
- **Lane**: image pipeline (Lane 6)
- **Finding**: `media_cleanup.py` falls back to a substring test
  (`if filename in ref`) after the exact-membership checks, making the orphan
  count imprecise. It currently errs toward *under*-deletion (safe), so changing
  it risks flipping to over-deletion (data loss) if any DB reference stores a
  path prefix. Needs an audit of how `referenced_files` is built before tightening.

#### Pass 48.3 Assorted LOW/INFO review notes (LOW, S)
- **Status**: done (Lane-6 variant-pruning v3.6.30; three Lane-4 scraper items
  v3.6.32; jobs items v3.6.33; pre-commit pins + dependabot v3.6.34 — all items
  landed)
- **Items** (each independent, low blast radius):
  - ✅ **done v3.6.32** — `scrape_esde.apply_esde_metadata` set `scraped = 1`
    even when no field was filled, excluding the game from later
    `WHERE scraped = 0` bulk passes. Now gated on ≥1 field filled (`region`,
    derived from the ROM filename, excluded from the test) (Lane 4).
  - ✅ **done v3.6.32** — `scrape_screenscraper.download_media` wrote
    non-atomically (bare `open(...,'wb')`); now uses the tempfile + `fsync` +
    `os.replace` pattern from `base_scraper.download_image` (Lane 4).
  - ✅ **done v3.6.32** — IGDB `apply_metadata_to_game` keyed age ratings on the
    deprecated `age_ratings.category` enum. Confirmed via the IGDB v4 proto that
    `organization`/`rating_category` are now reference objects (not enums); the
    scraper requests both shapes, detects ESRB/PEGI from the legacy enum or the
    org name, and best-effort-parses the new rating string (degrades to empty,
    never mis-rates) (Lane 4).
  - ✅ **done v3.6.30** — `image_utils._make_responsive_variants` never prunes a
    now-oversized `-sm`/`-md` sibling when the primary shrinks — srcset can serve
    a stale variant (Lane 6). Now unlinks the stale sibling on the skip branch.
  - ✅ **done v3.6.33** — `services/jobs/__init__.py` `__all__`/comment claimed
    to "re-export all public names" but omitted `resolve_terminal_status`,
    `shutdown_requested`, the singleton-lock helpers, etc. (imported directly
    from `services.jobs.base`). Comment softened to describe the backward-compat
    subset accurately (Lane 7).
  - ✅ **done v3.6.33** — `bulk_scrape` pause loop now waits on
    `shutdown_requested.wait(0.2)` instead of `time.sleep(0.2)`, so a paused job
    collapses on SIGTERM (mirrors the `psn_refresh` fix) (Lane 7).
  - ✅ **done v3.6.33** — `clz_import` import-time dedup now scopes by target
    `system_id IN (...)` (collected from the import payload) instead of scanning
    the whole `games` table (Lane 10).
  - ✅ **done v3.6.34** — `.pre-commit-config.yaml` ruff `v0.8.4 → v0.15.16` +
    gitleaks `v8.21.2 → v8.30.1`, back in lockstep with CI's unpinned-latest
    ruff. Dependabot now covers the `pre-commit` ecosystem so they stay current
    (Lane 14).

#### Pass 48.4 Loop-2 cold-review deferrals (LOW, S)
- **Status**: done (Lane-6 `media_cleanup` v3.6.30; bulk_scrape resume flock +
  ra_sync points + psn_sync_state + db `__exit__` v3.6.33; game-launch.js +
  dependabot/ci.yml v3.6.34 — all items landed)
- **Source**: the second (cold) indie-review loop surfaced these after the
  loop-1 fixes landed. All LOW under the single-user-localhost model.
- **Items**:
  - ✅ **done v3.6.30** — `media_cleanup` `/clean` re-scans for orphans
    milliseconds before deleting instead of reusing the previewed list, so the
    Pass 45.7 mtime race-defense doesn't cover the preview→clean window it was
    built for (Lane 6). Resolved by keeping the server-side re-scan (so the file
    SET stays trustworthy) but having the client echo back the preview's
    scan-start time as a `scan_started_override`, so any candidate modified
    since the preview is skipped — simpler and safer than accepting a
    client-supplied delete list.
  - ✅ **done v3.6.30** — `media_cleanup.py` picked the relpath base via a
    `'static' in dir_path` substring test — fragile if `IMAGE_PATH` ever moves
    outside `static/` (it does, in standalone builds) (Lane 6). Each `media_dirs`
    entry now carries an explicit `rel_base`.
  - ✅ **done v3.6.33** — `bulk_scrape` resume-after-restart path
    (`resume_from_params`) now acquires the `bulk_scrape` cross-process
    singleton flock (`try_acquire_singleton_or_warn`) before starting
    `_run_scrape`, refusing if another worker holds it (Lane 7).
  - ✅ **done v3.6.33** — `ra_sync` now skips the `earned_points`/`total_points`
    columns on the UPSERT UPDATE path when the `Achievements` payload is empty
    but `total_achievements > 0`, so a transient empty payload can't wipe a good
    value (Lane 7).
  - ✅ **done v3.6.33** — `_psn_sync_state` (trophies.py) is now a per-user
    registry keyed by `user_id`, so concurrent PSN syncs don't block each other
    or leak the other user's current-game title (Lane 10).
  - ✅ **done v3.6.34** — `game-launch.js` kill-instance `fetch` now checks
    `.ok` before retrying the launch; a failed kill reports "could not stop the
    running instance" instead of a confusing second "already running" 409
    (Lane 12).
  - ✅ **done v3.6.33** — `services/database.py` `get_db_with_context.__exit__`
    now rolls back explicitly on the error path and closes in `finally` (also
    fixes the LOW-tail "leaks on a failing commit" item) (Lane 2).
  - ✅ **done v3.6.34** — `.github/dependabot.yml` now covers the `pre-commit`
    ecosystem (pairs with 48.3's stale-pins item); and `ci.yml` no longer awk-
    scrapes the semgrep `--exclude-rule` set out of `.semgrep.yml` comment prose
    — the 14 IDs moved to a structured `.semgrep-excludes.txt` that CI reads
    directly (hard-failing if it's empty) (Lane 14).

#### Pass 48.5 Loop-3 cold-review deferrals (MEDIUM, M)
- **Status**: done (Lane-6 variant-leak done v3.6.30; IGDB/TGDB
  media-replace done v3.6.32; DB-restore-integrity + LOW-tail items done
  v3.6.33; final `ensure_user_tables` connection-leak done v3.6.35 — all items
  landed)
- **Source**: the third (cold) indie-review loop — confirmed all loop-1/loop-2
  fixes held (no resurfacing), then surfaced this deeper batch. Calibrated to
  single-user-localhost.
- **MEDIUM items**:
  - ✅ **done v3.6.32** — **Single-source IGDB/TGDB apply replaces curated media**
    (`scrape_igdb.py` `apply_metadata_to_game`, `scrape_thegamesdb.py` ditto):
    unlike `apply_esde_metadata`, these downloaded boxart/screenshots/fanart
    unconditionally and `COALESCE`-wrote a non-null new value, so on the hybrid
    *fallback* path a fresh boxart overwrote a curated one and the screenshots
    column was replaced, not appended. Both now read existing media first:
    boxart/fanart fill only when empty, screenshots append (de-duped,
    order-preserving). Regression: `tests/test_scrape_fill_only.py`. Resolved
    alongside Pass 48.1.
  - ✅ **done v3.6.30** — **Responsive variants leaked on per-game deletion**
    (`media_cleanup.py` `delete_game_images`): only the bare DB filename was
    unlinked; the `-sm`/`-md` siblings written by `_make_responsive_variants`
    survived until a manual orphan sweep — 2-4 stranded files per deleted game
    with boxart. `delete_game_images` now unlinks the variant siblings.
  - ✅ **done v3.6.33** — **DB restore has no integrity gate** (`settings.py`
    `api_restore`): now runs `PRAGMA integrity_check` on the backup (opened
    read-only) before the destructive `os.replace`, and refuses the restore
    (HTTP 409) while any `job_queue.status = 'running'` row exists.
- **LOW tail** (each independent): ✅ **all done v3.6.33 except
  `ensure_user_tables`** —
  - ✅ `scraper_manager._settings_cache` now lock-guarded under bulk-scrape
    threads (`metadata_merger` has no such cache — the original note was
    imprecise);
  - ✅ `hybrid_scraper.detect_save_type/detect_controller_support` guard
    `system_folder=None` via `(x or '').lower()`;
  - ✅ bulk-edit now validates `completion_status` against the shared whitelist
    and cross-maps ratings per game (fill-empty only);
  - ✅ `for g in games` in `api_filter_games` renamed to `row` (no flask.g
    shadow);
  - ✅ `execute_script` docstring documents its non-atomicity;
  - ✅ `get_db_with_context.__exit__` leak-on-failing-commit fixed (close in
    `finally`) — folded into the 48.4 `__exit__` fix;
  - ✅ **done v3.6.35** — `ensure_user_tables` leaked its connection on
    exception: the body is now wrapped in `try/finally` (matching the sibling
    `init_database()` pattern in the same file) so a mid-bootstrap failure
    still closes the handle instead of waiting on GC to drop the WAL lock.
    Verified both paths: happy-path seeds the admin row, error-path closes the
    connection despite a forced mid-body exception;
  - ✅ `backup_database` chmod-fail now logs a warning instead of silent `pass`;
  - ✅ `systems.update_system_types` partial match dropped the buggy `folder in
    key` direction (`'nes'` no longer inherits the `'snes'` type);
  - ✅ `scrape_logs.api_view_log_compat` now enforces the `VALID_PREFIXES`
    allowlist its siblings use;
  - ✅ `clz_import` dedup scoped to target systems (done with the 48.3 item).

---

### Pass 47 — Open-source release & donation funnel (2026-05-07)

> User-requested track: flip the GitHub repo from private to public,
> repurpose Patreon to a pure donation model (the app itself becomes
> free), add GitHub Sponsors and Buy Me A Coffee, and surface donation
> links from both the repo and the in-app About panel. The
> marketing/distribution website (a separate property the user plans
> to host RetroDB *and* their other apps under, with the same donation
> model) is **out of scope** for this pass — see "Scope notes —
> considered and dropped".
>
> **Recommended donation stack** (rationale captured here so future
> sessions don't re-litigate the platform choice):
>
> 1. **GitHub Sponsors** — primary. Free for the recipient, integrated
>    "Sponsor this project" button on the repo page, supports monthly +
>    one-off, no platform fee beyond standard Stripe processing.
>    Strongest alignment with the public-repo move; the donation CTA
>    sits where prospective contributors are already looking.
> 2. **Buy Me A Coffee** — secondary. Lowest-friction one-off-tip
>    surface for users who don't want a monthly commitment or a GitHub
>    account. ~5% platform fee + Stripe processing.
> 3. **Patreon** — keep, but de-emphasise. Existing setup with zero
>    subscribers; Patreon's 8–12% take is the steepest of the three so
>    it should not be the primary CTA. Tier copy is rewritten so the
>    perks are cosmetic (the app itself is free).
>
> Skipped on purpose: Open Collective (fiscal-host overhead is overkill
> for a solo dev), Liberapay (audience too small for a third recurring
> platform), Ko-fi (overlaps BMAC — pick one), PayPal Donate (clunky UX,
> dilutes the funnel), crypto (high friction, signals "shady" to
> mainstream users).

#### Pass 47.1 Pre-publish hygiene sweep (HIGH, M)

- **Target**: full git history, repo metadata, README, root community
  files (`SECURITY.md`, issue / PR templates).
- **Why**: visibility flip is irreversible in practice — anything ever
  committed to any branch becomes public the instant the repo flips.
  Need a clean sweep first, especially of pre-`.gitleaks.toml` history.
- **Plan**:
  1. **Secret-history sweep**: `gitleaks detect --source . --redact
     --no-banner --log-opts="--all"` to scan every ref, not just
     `HEAD`. If anything turns up, decide between (a) `git filter-repo`
     to scrub history (rewrites SHAs — preferred *before* flipping),
     or (b) rotate the leaked credential and accept the historical
     exposure if scrubbing would be too disruptive.
  2. **Excluded-paths sanity check**: confirm `config.py`,
     `data/settings.json`, `data/scraper_settings.json`,
     `data/rom_tools_config.json`, `.secret_key`, all `*.db`,
     `static/images/{boxart,boxart_3d,screenshots,fanart,manuals,trophies}/`,
     `static/videos/` are correctly `.gitignore`d AND have never been
     tracked. `git log --all -- <path>` empty for each.
  3. **Hardcoded-paths / personal-identifiers grep**:
     `grep -rE "/home/(ants|[a-z]+)/|aant\.schemel|milnet01"
     --exclude-dir=.git` — anything that ties source code to the local
     dev box is parameterised or removed (test fixtures, log lines,
     comments). Email + GitHub handle expected to remain in `LICENSE`,
     `CONTRIBUTING.md`, and changelog entries — those are intended.
  4. **`SECURITY.md`**: add a top-level disclosure policy (contact
     email, expected response window, in/out-of-scope, "no bug
     bounty"). GitHub renders this in the Security tab; a public repo
     without one looks unmaintained.
  5. **`.github/ISSUE_TEMPLATE/`**: minimal `bug_report.md` and
     `feature_request.md` so first-time contributors don't dump
     unstructured prose. Match the project's existing reproduction-
     before-fix discipline (env / steps / expected vs actual / log
     excerpt).
  6. **`.github/PULL_REQUEST_TEMPLATE.md`**: short; mirrors the
     project's commit-message contract (one-line title, "what / why"
     body, mandatory-workflow checklist — version bumped, changelog
     entry, tests run if applicable).
  7. **README polish**: add a "Status" line ("Solo-developed; releases
     on a best-effort cadence"), 2–3 representative screenshots, and a
     "Support development" section anchored to 47.6's funding stack.
  8. **Repo metadata**: write a one-line description, add 6–8 topics
     (`rom-manager`, `retro-gaming`, `flask`, `python`, `emulation`,
     `rom-library`, `self-hosted`, `gaming`) so the repo is
     discoverable from GitHub search.
- **Status**: shipped in v3.6.15. Items 1 (gitleaks --all clean: 0
  leaks / 203 commits scanned), 2 (every excluded path verified
  `git log --all` empty), 3 (one real cleanup — stray Inkscape
  export-filename in `static/images/systems/cps.svg`; the rest are
  intentional dev-box-aware test fixtures + UX placeholders + the
  maintainer's own CLAUDE.md note), 4 (SECURITY.md authored), 5
  (3 issue-template files incl. `config.yml` routing security to PVR
  and questions to Discussions), 6 (PR template authored), 7
  (Status line + Support-development section pointing at GitHub
  Sponsors — screenshots deferred, maintainer needs to curate; the
  Patreon / BMAC URLs land in Pass 47.6 once the platforms are set
  up). Item 8 (repo description + topics) deferred to Pass 47.2 —
  the `gh repo edit` call is paired with the visibility flip.

#### Pass 47.2 Flip repo visibility private → public (MEDIUM, S)

- **Target**: GitHub Settings → General → Danger Zone → Change
  visibility (or `gh repo edit milnet01/RetroDB --visibility public
  --accept-visibility-change-consequences`).
- **Why**: gates 47.4–47.6. Public visibility is also what unlocks
  unlimited Linux-runner CI minutes (private repos consume the
  account's monthly Actions quota — see `~/.claude/CLAUDE.md` §6),
  which retires the push-batching rule for this repo.
- **Plan**:
  1. Confirm 47.1 clean.
  2. Flip visibility.
  3. Verify GitHub Actions secrets (`GITHUB_TOKEN`, any custom
     workflow secrets) still scope correctly. Repository secrets stay
     scoped to the repo regardless of visibility, but tokens with
     restricted-scope PATs may need rotation if their grant was
     "private repos only".
  4. **Update push-cadence expectations**: with the repo now public,
     the global rule's PRIVATE-batching path no longer applies — push
     freely after each release.
- **Status**: done (2026-05-18). Flipped via `gh repo edit milnet01/RetroDB
  --visibility public --accept-visibility-change-consequences`.
  `gh secret list` returned empty (no Actions secrets to verify scope on).
  `.github/FUNDING.yml` already wires GitHub Sponsors (`github: [milnet01]`);
  Sponsors profile is approved + live at <https://github.com/sponsors/milnet01>
  (resolved out-of-band ahead of the flip). Patreon + BMAC entries in
  FUNDING.yml remain pending on 47.3 + 47.5. Push-batching rule retired
  for this repo.

#### Pass 47.3 Repurpose Patreon (free app, donation-only tiers) (MEDIUM, S)

- **Target**: existing Patreon page (off-repo, web admin).
- **Why**: existing setup with zero subscribers — the paywall is the
  discovery bottleneck, not willingness-to-pay. Free + donate is the
  standard play for niche FOSS hobbyist software.
- **Plan**:
  1. Update Patreon page copy: "RetroDB is now free and open source.
     Patreon supports ongoing development." Strip any "buy access"
     framing.
  2. Re-tier the membership levels so they're cosmetic / appreciation
     rather than gated content. Suggested tiers (sized so the highest
     stays approachable — risk is patron expectations creeping into
     roadmap influence at >$15):
     - **Tip jar** ($1/mo) — name in CHANGELOG supporters list,
       Discord role if/when a Discord exists.
     - **Coffee** ($5/mo) — same, plus early access to release builds
       (~1 week before public release).
     - **Patron** ($15/mo) — same, plus a monthly behind-the-scenes
       update post (single paragraph; not a content treadmill).
  3. Add the Patreon URL to `.github/FUNDING.yml` (Pass 47.6).
- **Status**: blocked on 47.2

#### Pass 47.4 GitHub Sponsors (MEDIUM, M)

- **Target**: <https://github.com/sponsors> waitlist + sponsor
  profile.
- **Why**: integrated with the public repo (Sponsor button on the repo
  page), no platform fee beyond standard payment processing, supports
  both monthly and one-off. Strongest alignment with the open-source
  release.
- **Plan**:
  1. Apply at <https://github.com/sponsors>. Eligibility checks:
     verified GitHub account, 2FA on, public profile photo + bio,
     identity verification (passport / driver's licence) for
     Stripe-Connect-equivalent payout setup. Approval can take 2–6
     weeks, so start the application *early* — runs in parallel with
     47.1 / 47.2 since the application is account-level, not
     repo-level.
  2. Once approved, configure tiers (mirror the Patreon tiers from
     47.3 so prospective supporters can pick the platform they prefer
     — same cosmetic perks).
  3. Skip goal-based fundraising at first. Goals only feel real once
     the audience is large enough that "$50/mo unlocks weekly
     office-hours streams" isn't aspirational fanfic.
- **Status**: done (2026-05-18). Sponsors profile is live at
  <https://github.com/sponsors/milnet01> (resolved out-of-band ahead of
  the 47.2 flip). `.github/FUNDING.yml` carries `github: [milnet01]`,
  so the Sponsor button now renders on the public repo page. Tier
  configuration left to operator-side admin once 47.3 lands.

#### Pass 47.5 Buy Me A Coffee (LOW, S)

- **Target**: <https://buymeacoffee.com> profile.
- **Why**: lowest-friction one-off-tip surface for users without a
  GitHub account or who don't want monthly commitment. Stripe-backed;
  recipient pays standard processing fees (~2.9% + $0.30) plus 5% BMAC
  fee.
- **Plan**:
  1. Sign up at <https://buymeacoffee.com>; pick a username matching
     the GitHub handle (`milnet01`) for cross-platform consistency.
  2. Add the BMAC URL to `.github/FUNDING.yml` (Pass 47.6) under the
     `custom` field — BMAC isn't a natively-recognised FUNDING.yml
     platform.
  3. **Skip the BMAC "memberships" feature** — that overlaps
     Patreon/Sponsors and fragments the monthly-tier story across
     three platforms. Use BMAC strictly for one-off coffees.
- **Status**: blocked on 47.2

#### Pass 47.6 Donation surfaces in app + repo (MEDIUM, M)

- **Target**: `.github/FUNDING.yml`, `README.md`, in-app
  Settings/About surface.
- **Why**: discovery — users only donate if they see the link. The
  repo button (`FUNDING.yml`) covers GitHub visitors; the README
  badges cover anyone reading docs; the in-app panel covers existing
  users who never visit the repo.
- **Plan**:
  1. **`.github/FUNDING.yml`** with the platforms enabled in 47.3 / 47.4
     / 47.5 (GitHub renders these as a "Sponsor this project"
     dropdown):

     ```yaml
     github: [milnet01]
     patreon: <username-from-47.3>
     custom: ['https://buymeacoffee.com/<username-from-47.5>']
     ```
  2. **README.md** — the "Support development" section landed in Pass 47.1
     (currently above the License section; grep `## Support development`
     to find it). Pass 47.6 step 2 is to expand it with badges (Sponsor /
     BMAC / Patreon) once the BMAC/Patreon usernames from 47.3/47.5 are
     live. Don't add a second section — extend the existing one.
  3. **In-app surface** — fold a "Support development" panel into the
     existing settings page (`templates/settings.html`) or the About
     modal. Three external links + a one-line note. **No paywalled
     features, no nag dialogs** — those degrade trust faster than
     they raise donations. A first-run notification *might* be worth
     it (one-time, dismissable, never reappears) but skip on the
     first cut and revisit if conversion stays at zero.
  4. **Footer link** — single text link ("Support") in the page
     footer next to the version / GitHub link if a footer exists. If
     no footer exists today, *skip* — don't add chrome solely to
     hold a donation link.
  5. **CHANGELOG supporters list** — render contributors from the top
     Patreon / Sponsors tier into a "Supporters" section at the
     bottom of `data/changelog.yaml`'s release notes, fed manually
     per release. Defer until there *are* supporters.
- **Status**: blocked on 47.3 / 47.4 / 47.5 (need the platform URLs
  to populate). The Sponsors-only subset is unblocked — see 47.6.A.

#### Pass 47.6.A In-app sponsorship link (GitHub Sponsors only) (LOW, S)

- **Target**: in-app surface — settings page (likely the
  `templates/_settings_tabs/system.html` partial or About modal) +
  optional footer link.
- **Why**: Pass 47.6's full plan is blocked on 47.3 + 47.5 (need Patreon
  + BMAC usernames). GitHub Sponsors is already live
  (<https://github.com/sponsors/milnet01>) and already in
  `.github/FUNDING.yml`. There's no reason to delay the in-app discovery
  surface until *all three* platforms are wired — start with Sponsors,
  add the others when 47.6 lands.
- **Plan**:
  1. **Settings → System tab.** Add a "Support development" panel with
     a single-link card pointing at <https://github.com/sponsors/milnet01>,
     a one-line framing ("RetroDB is free and open source. If it saves
     you time, consider sponsoring — every bit helps keep solo development
     sustainable."), and the GitHub Sponsors mark. Use existing card +
     theme tokens; no new CSS components.
  2. **About modal.** Add the same link as a secondary surface for
     users who never visit Settings.
  3. **No nag dialog, no paywalled features**, no first-run modal —
     trust costs more than the marginal conversion would earn. A footer
     link is fine if a footer exists; otherwise skip per 47.6 step 4.
  4. **Open in a new tab** (`target="_blank" rel="noopener noreferrer"`)
     so the user doesn't lose their place.
- **Source**: user-request-2026-05-18 (post-public-flip follow-up).
- **Status**: done (2026-06-10, v3.6.36). Added a "💝 Support
  Development" card to Settings → System (visible to all users, with a
  `#support` subnav entry) and a "💝 Sponsor" button to the About modal,
  both linking <https://github.com/sponsors/milnet01> in a new tab
  (`rel="noopener noreferrer"`). No nag dialog / paywall / first-run
  modal. Reused existing `.card` / `.btn` / `.subnav-link` styling — no
  new CSS. Verified via an authenticated render of `/settings` (admin
  session) through the Flask test client — all surfaces present. Pass
  47.6 stays open to absorb Patreon + BMAC additions once those land.

---

### Pass 46 — vendor third-party assets / distribution self-containment (2026-04-27)

> User-requested track: drop runtime CDN dependencies (Chart.js, Google
> Fonts), refresh pinned pip versions within current ranges, and add a
> PyInstaller-based "no Python install needed" distribution alongside the
> existing source-zip distribution. Goal — let RetroDB run without
> reaching out to third-party CDNs and let end users pick between
> "needs Python" (small zip) and "self-contained" (bigger binary)
> distribution channels.

#### Pass 46.1 Vendor Chart.js + Google Fonts (privacy / offline)

- **Targets**: `templates/analytics.html` (CDN Chart.js ref),
  `templates/base.html` (Google Fonts ref).
- **Why**: every browser load made requests to `cdn.jsdelivr.net`
  (Chart.js) and `fonts.gstatic.com` + `fonts.googleapis.com` (3 font
  families, 17 WOFF2 files) — third-party fetches that log IP +
  User-Agent and add CDN failure modes. User asked for a no-CDN runtime.
- **Plan**: vendor Chart.js v4.5.1 UMD bundle (~208 KB) into
  `static/js/vendor/`, register it in the `asset_manifest.json` cache-
  bust pipeline. Vendor 17 WOFF2 files (Orbitron variable + Rajdhani
  5×3 subsets + Share Tech Mono) into `static/fonts/`, write a local
  `static/css/core/fonts.css` with the @font-face block, drop the
  preconnect + Google CSS link in `base.html`. One-shot bash script
  `scripts/vendor_fonts.sh` for the font download (idempotent + WOFF2
  magic-byte verification).
- **Source**: user request 2026-04-27 ("can we get this project to a
  point where there are no external dependencies?").
- **Status**: done (v3.5.35) — 17 WOFF2 + Chart.js UMD bundle vendored
  (~784 KB repo growth). Build scripts updated to hash vendor JS +
  standalone fonts.css for per-file cache-busting. Smoke-tested:
  `/login` response has zero `gstatic.com`/`googleapis.com` references
  outside HTML comments; all three asset paths return 200 with valid
  bytes. 683 tests green.

#### Pass 46.2 Refresh pinned pip versions within current ranges

- **Target**: `requirements.txt`, `requirements.lock`.
- **Why**: lockfile pins are 2-week-old snapshots; latest patch/minor
  releases within the existing version ceilings (Flask `<4.0`, Pillow
  `<13.0`, etc.) include security fixes and bugfixes worth picking up
  before the PyInstaller distribution work bakes them into a binary.
- **Plan**: `pip-compile --upgrade requirements.txt -o requirements.lock
  --strip-extras`, run full pytest, fix any breakage. Bump the
  ceilings if any package's latest exceeds the current cap (Flask 4
  if released, numpy 3, etc.); document any version-locking decisions.
- **Status**: done (v3.5.36) — 6 packages bumped (certifi, click,
  cryptography 46→47, idna, onnxruntime 1.24→1.25, packaging). 2
  transitives removed (mpmath, sympy — onnxruntime 1.25 no longer
  pulls them). All ceilings in `requirements.txt` already
  accommodated the new versions; no top-level constraint changes
  needed. 683 tests green, app boots clean. Repo install footprint
  drops ~25 MB from sympy removal.

#### Pass 46.3 PyInstaller spec + dual-distribution `build_dist.py`

- **Target**: new `retrodb.spec`, extended `build_dist.py`, distribution
  README updates.
- **Why**: end users currently must install Python + pip-install
  requirements before running RetroDB. A PyInstaller binary lets them
  run a single executable on Linux/macOS/Windows. Both distribution
  channels remain (small source zip for users who already have Python;
  ~3.7 GB binary for users who don't — onnxruntime + ROCm libs dominate).
- **Status**: part 1 done (v3.5.38). Bundle builds, smoke-tests cleanly:
  `Real-ESRGAN ONNX loaded`, Waitress serving, `/login` 200. PyInstaller
  cannot cross-compile — `--standalone` only produces the host platform's
  binary. Open follow-ups in part 2 / part 3.

##### Part 2 — frozen-mode user-data path

- **Why**: today, when run from `dist/retrodb/retrodb`, `BASE_DIR =
  dirname(__file__)` resolves to `_internal/` (PyInstaller MEIPASS in
  onedir mode). User data — `database/`, `data/`, `logs/`, scraped media
  — gets written into `_internal/` alongside bundled assets. Functional
  (the dir is writable) but ugly: clobbers the "support files" boundary
  and makes upgrades messy (user has to manually copy data out of an
  old `_internal/` into a new one).
- **Plan**: detect `getattr(sys, 'frozen', False)` in `config.py`. When
  frozen, set `BASE_DIR = os.path.dirname(sys.executable)` (next to the
  launcher, NOT inside `_internal/`). `STATIC_PATH` for the bundled
  CSS/JS/font assets stays at `sys._MEIPASS/static`. Custom Flask static
  route falls back to `BASE_DIR/static/images/` for scraped media so
  `/static/images/boxart/<id>.webp` resolves correctly.
- **Status**: done (v3.5.39) — `config.py` now exposes `BASE_DIR`
  (writable user data root) and `BUNDLE_DIR` (read-only bundled assets
  root); `IMAGE_PATH` + `DB_PATH` follow `BASE_DIR`, `STATIC_PATH`
  follows `BUNDLE_DIR`. Eight call sites retargeted (settings_manager,
  log_manager, routes.scraper, plus five sites in app.py) from local
  `dirname(__file__)` to `config.BASE_DIR` / `config.BUNDLE_DIR`. New
  `/static/images/<path>` route tries `BASE_DIR/static/images/` first,
  falls back to `BUNDLE_DIR/static/images/`; in dev mode both roots are
  identical and the fallback is a no-op. 11 regression tests in
  `tests/test_pass46_frozen_paths.py` pin the dev-mode invariant,
  frozen-mode split (monkeypatched `sys.frozen` + `sys._MEIPASS`),
  dependent-modules anchor, and route behaviour. 694 / 694 tests green.

##### Part 3 (optional) — CPU-only build variant

- **Why**: `onnxruntime-rocm` pulls in ~2 GB of ROCm libs
  (`librocsolver.so.0`, `libMIOpen.so.1`, `libamd_comgr.so.3`) for AMD
  GPU acceleration. Users on Intel/NVIDIA CPUs gain nothing from these
  but pay the download size.
- **Plan**: add a `--standalone --cpu-only` flag that builds against a
  CPU-only Python venv (vanilla `onnxruntime`, not `-rocm`). Estimated
  bundle ~600 MB. Both variants ship; the page lists size +
  GPU-acceleration trade-off so users self-select.
- **Status**: todo

##### Part 4 (optional) — CI matrix build for cross-platform binaries

- **Why**: `--standalone` produces only the host's binary. To ship
  Linux + macOS + Windows standalones from a single tag push, GitHub
  Actions needs a 3-runner matrix (`ubuntu-latest`, `macos-latest`,
  `windows-latest`).
- **Plan**: extend `.github/workflows/release.yml` to spawn one
  `pyinstaller retrodb.spec` job per OS on `tags: 'v*'` push, then
  upload all 3 zips as release assets. Note this multiplies CI minutes
  by 3× per release; might be worth gating behind a manual
  workflow_dispatch for the standalone build.
- **Status**: todo

---

### Pass 45 — indie-review 2026-04-25 (post Pass 41 sweep)

> Third 14-agent independent review (v3.5.14). 2 CRIT + 33 HIGH raw →
> 1 CRITICAL + ~28 HIGH after threat-model calibration. The CRITICAL is
> a net-new bug introduced by Pass 41.9; everything else is hardening or
> contract drift surfaced by cold-read agents that don't share the
> author's mental model. Cross-cutting themes (≥2 reviewers) flagged
> independently: atomic-write drift, SSRF pin_host_ip unwired, source-
> grep test antipattern, inline-onclick + CSP zombie nonce, aria-current
> + ModalFocusTrap rollouts incomplete, Steam/Xbox/PSN sync rate-limit
> gap, migration runner BEGIN DEFERRED.

#### Pass 45.1 CRITICAL — `track_progress` permission unsatisfiable (CRITICAL, S)

- **Targets**: `services/auth.py:31-42` (`ROLE_PERMISSIONS`) +
  `routes/games.py:1101, 1130` (`@permission_required('track_progress')`).
- **Why**: Pass 41.9.A added the decorator on `api_track_view` and
  `api_update_completion` but never added the permission to any role.
  `has_permission('track_progress')` returns False for every user
  including admin → both endpoints redirect to `/dashboard`. Completion-
  toggle and recently-viewed are dead in production. Caught by Auth +
  Game routes lanes independently.
- **Plan**: add `'track_progress'` to admin + editor + viewer (and
  whatever future Player role lands). Make `permission_required` JSON-
  aware on `/api/*` routes (return 403 envelope, not 302).
- **Source**: indie-review 2026-04-25 cross-cutting theme T1.
- **Status**: done (v3.5.15) — `track_progress` granted to admin / editor /
  viewer; `permission_required` now returns 403 JSON envelope on `/api/*`
  routes (page routes still flash+302). 5 regression tests in
  `tests/test_pass45_security.py::TestPass45_1*`.

#### Pass 45.2 SSRF DNS-rebinding TOCTOU on scraper download path (HIGH, M)

- **Targets**: `services/ssrf.py:127` (`pin_host_ip`), threaded through
  `scraper/base_scraper.download_image`,
  `scraper/metadata_merger._download_and_finalize`,
  `services/image_utils._download_model`.
- **Why**: Pass 32.7 documented the rebinding protection but the helper
  is consumed only by `routes/museum.py:1085`. Every other scraper path
  calls `validate_outbound_url()` then GETs separately — adversarial DNS
  flips A-records between validate and connect. Caught by Core app +
  Scraper orchestration + Per-source scrapers lanes.
- **Plan**: thread `pin_host_ip` through every `validate_outbound_url`
  call site or document the residual.
- **Source**: indie-review 2026-04-25 theme T3.
- **Status**: done (v3.5.17) — added `services.ssrf.validate_and_pin_url`
  (walks redirect chain through SSRF gate + captures IP for pinning) and
  threaded `pin_host_ip` through `scraper/base_scraper.download_image`,
  `scraper/metadata_merger._download_and_finalize`, `scraper/metadata_
  merger._download_ss_media`, `scraper/scrape_screenscraper.download_
  media`, and `services/image_utils._download_model`. The last path was
  switched from `urllib.urlopen` (auto-follows redirects through real
  DNS) to `requests` with `allow_redirects=False` so each hop can be
  pinned. `routes/museum.py:_is_public_https_url` is now a thin wrapper
  around the new helper. 6 regression tests in
  `tests/test_pass45_security.py::TestPass45_2*` capture what
  `socket.getaddrinfo` returns at the moment of the GET — with the pin
  active it returns the verified IP, without it real DNS is queried
  (and fails with `gaierror` in the sandbox).

#### Pass 45.3 AI Fill breaks fill-only invariant on integer columns (HIGH, S)

- **Targets**: `routes/games_ai.py:109` — `all_updates.append(f"{field} = ?")`.
- **Why**: writes bare `field = ?` instead of `COALESCE(?, field)`.
  `_int_fields` coerce path at `:106` writes `0` after `int(float("0"))`,
  overwriting curated non-zero values (e.g. `players=4` clobbered by
  AI returning `"0"`). CLAUDE.md scraper-fill-only invariant should
  apply to AI Fill too.
- **Plan**: wrap integer column writes in `COALESCE(NULLIF(?, 0), col)`,
  or skip when `value == 0`.
- **Source**: indie-review 2026-04-25 (Game routes lane H1).
- **Status**: done (v3.5.16) — int fields coerced to 0 after `int(float(value))`
  now skip the UPDATE clause (chose the simpler "skip" branch over COALESCE
  NULLIF since the existing `should_apply` filter already guarantees we only
  reach the int-coerce on values worth writing). Covers all 5 int columns
  (`players`, `critic_score`, `critic_score_count`, `user_score`,
  `user_score_count`). 4 regression tests in
  `tests/test_pass45_security.py::TestPass45_3*` exercise the route
  end-to-end with a stubbed AI provider — reverting the production fix
  fails the curated-`players` and spurious-`critic_score` cases.

#### Pass 45.4 XSS sinks in toast / HLTB / settings dialogs (HIGH, S)

- **Targets**:
  - `static/js/toast-controller.js:1171` — raw-interpolated `data.return_url`
    in inline `onclick` JS-string. Pass 41.12.B's runtime guard fires too
    late (URL already rendered as HTML).
  - `static/js/game-modals.js:670-689` — `data.main_story/main_extra/
    completionist` from HLTB API in `innerHTML` without `escapeHtml`.
  - `templates/settings.html:4373, 4399` — `confirmMessage.innerHTML = message`
    with comment `"Use innerHTML to support HTML content"`. Same family
    as `showModal` Pass 40.13 closed.
- **Plan**: migrate `toast-controller.js:1171` to delegated listener +
  `data-` attr; wrap HLTB fields with `escapeHtml`; default
  `showConfirmModal/showInfoModal` to `textContent` with `{allowHtml:true}`
  opt-in mirroring Pass 40.13.
- **Source**: indie-review 2026-04-25 theme T12.
- **Status**: done (v3.5.18) — toast-controller's three inline onclicks
  (active-toast navigate / pause / cancel + RA-queued cancel) replaced
  with `data-toast-action` + a single delegated container click handler
  that routes by action; all interpolated values run through
  `escapeHtml`. HLTB `main_story/main_extra/completionist` wrapped in
  `escapeHtml(String(...))`; HLTB clear button migrated from inline
  onclick to `data-hltb-clear` + addEventListener. `showConfirmModal`/
  `showInfoModal` in `settings.html` now accept `options` and default
  to `textContent`; `clearScrapedData` and `deleteController` opt in
  via `{allowHtml: true}` AND escape `systemName`/`controllerName`.
  6 regression tests in `tests/test_pass45_security.py::TestPass45_4*`
  pin each contract via source grep (mirrors Pass 40.13's pattern).
  Pass 45.3 CI fix folded in: monkeypatch `settings_manager.load_
  settings` so the empty-data CI environment doesn't 302 to /setup.

#### Pass 45.5 Atomic-write contract drift (HIGH, M)

- **Targets**:
  - `app.py:115-120` `_get_secret_key` truncates without `os.replace`;
    chmod-after-write leaves brief 644 window.
  - `services/image_utils.py:759-779` `_atomic_save` claims fsync in
    docstring but doesn't call `os.fsync`. Same in
    `services/game_media_service.py:201-216` `_atomic_write_bytes`.
  - `services/image_utils.py:88-118` `_download_model` uses static
    `.tmp` suffix (race-prone with concurrent processes).
  - `services/database.py:295` `backup_database` chmods after the
    integrity-check open (mode-0644 window).
- **Plan**: route everything through `services.atomic_io` (one helper);
  add `f.flush() + os.fsync(fd)` before `os.replace`; chmod before
  any reopen-for-verify.
- **Source**: indie-review 2026-04-25 theme T2.
- **Status**: done (v3.5.20) — added `services.atomic_io.atomic_write_
  bytes` / `atomic_write_text` / `fsync_path`; threaded through all
  five sites: `_get_secret_key` (mode=0o600 chmod-before-replace),
  `_atomic_save` (added missing fsync the docstring claimed),
  `_atomic_write_bytes` in game_media_service (delegates to helper),
  `backup_database` (chmod reordered to fire before integrity-check
  verify open), `_download_model` (mkstemp instead of static `.tmp`).
  8 regression tests in `tests/test_pass45_security.py::TestPass45_5*`
  pin the contracts; reverting `backup_database` reorder fails the
  position check.

#### Pass 45.6 Decompression-bomb / `MAX_IMAGE_PIXELS` global (HIGH, S)

- **Targets**: `services/image_utils.py` + `services/game_media_service.py`
  module imports; `_validate_image_bytes`, `_ensure_format_matches_extension`,
  `standardize_image` exception handling.
- **Why**: scraper-downloaded crafted PNG can decode to GBs of pixels.
  Pass 41.14.A fixed `compute_dhash` for image_dedup; the rest of the
  image stack still has no `Image.MAX_IMAGE_PIXELS` set and `verify()`
  doesn't decode.
- **Plan**: `Image.MAX_IMAGE_PIXELS = config.IMAGE_MAX_PIXELS or 64_000_000`
  at module import in both files; explicit `DecompressionBombError` catch
  at every `Image.open(...)` call site.
- **Source**: indie-review 2026-04-25 theme T5.
- **Status**: done (v3.5.21) — added `config.IMAGE_MAX_PIXELS` (default
  64 megapixels), set `Image.MAX_IMAGE_PIXELS` at module-import time in
  both `services/image_utils.py` and `services/game_media_service.py`,
  and added explicit `DecompressionBombError` catches at every
  `Image.open` site (5 total) with distinct log lines for forensics.
  5 regression tests in `tests/test_pass45_security.py::TestPass45_6*`.

#### Pass 45.7 Stale-ref orphan-cleanup race (HIGH, M)

- **Targets**: `services/media_cleanup.py:127-187`.
- **Why**: `clean_orphaned_files` deletes based on a snapshot taken by
  `find_orphaned_media` at scan time. A scraper writing a new
  `42_boxart.webp` between scan and delete loses the file. Same
  architectural shape as Pass 40.15's `hybrid_scraper` stale-clear race.
  Also: orphan deletion follows symlinks (no `os.path.islink` guard).
- **Plan**: re-validate each candidate against fresh DB read at delete
  time, OR filter on `mtime > scan_start_time`. Add `os.path.islink`
  skip in the iteration.
- **Source**: indie-review 2026-04-25 (Image pipeline lane).
- **Status**: done (v3.5.22) — each orphan dict carries `mtime` and
  `scan_started_at`; `clean_orphaned_files` re-checks both at delete
  time and skips files modified during the cleanup window. Symlinks
  refused at both scan and clean (`os.path.islink` guard added in
  `find_orphaned_media` and again in `clean_orphaned_files` as defence
  in depth). 5 regression tests in
  `tests/test_pass45_security.py::TestPass45_7*`; reverting the
  `services/media_cleanup.py` change fails 4 of 5.

#### Pass 45.8 Steam/Xbox/PSN/wishlist endpoint rate-limits (HIGH, S)

- **Targets**: `app.py:266-300` registrations. Add for:
  `platform_import.api_steam_fetch_library`, `..._import`,
  `..._sync_achievements`, Xbox + PSN siblings,
  `trophies.api_psn_sync`, `..._sync_one`, `..._bulk_refresh_start`,
  `collections.scrape_all_wishlist`,
  `scraper.api_check_scraper`, `..._scraper_allowance`.
- **Why**: each fans out hundreds of remote API calls; misclick or
  stuck XHR can hammer Steam/Xbox/PSN APIs and trigger account bans
  or burn paid AI quota.
- **Plan**: 5/min or 5/hour caps mirroring `tools.api_*_scan` block.
- **Source**: indie-review 2026-04-25 theme T13.
- **Status**: done (v3.5.23) — 15 endpoints registered with caps in
  `app.py` via the existing `_rate_limit` helper. Library-fetch
  endpoints at 5/min, "sync everything" at 2/hour, credit probes at
  30/min. 3 regression tests in
  `tests/test_pass45_security.py::TestPass45_8*` pin the endpoints
  exist + the source-level registration + the 2/hour cap on bulk
  actions.

#### Pass 45.9 collector_trophies regressions (HIGH, S)

- **Targets**:
  - `routes/collector_trophies.py:372` — `for g in (r['genre'] or '').split(',')`
    is the exact Pass 41.8.A `flask.g` shadow pattern.
  - `routes/collector_trophies.py:570-605` — `collector_trophies_page`
    + `get_all_trophies` GET handlers call `_refresh_trophies` (writes
    ~70 rows) on cold-cache. RFC 7231 GET-idempotency violation; same
    family Pass 41.11.B closed for museum.
- **Plan**: rename loop var to `genre_part`; remove lazy-init from GET
  paths (explicit POST at `:616` already exists).
- **Source**: indie-review 2026-04-25 (Collections lane).
- **Status**: done (v3.5.24) — genre loop renamed `genre_part`; both
  GET handlers now call `_trophies_sorted(user_id) or
  _empty_trophies_from_definitions()` so cold-cache renders an
  in-memory roster from `TROPHY_DEFINITIONS` instead of writing rows;
  explicit POST at line 616 is the only refresh path. 4 regression
  tests in `tests/test_pass45_security.py::TestPass45_9*`; reverting
  the fix fails all 4 (functional smoke pins zero writes from GET).

#### Pass 45.10 Migration runner `BEGIN IMMEDIATE` + busy_timeout (HIGH, S)

- **Targets**:
  - `services/migrations/__init__.py:84` — `conn.execute("BEGIN")` is
    DEFERRED; table-rebuild migrations 007/008/009 deadlock under
    concurrency.
  - `services/database_init.py:48` — migration connection skips
    `PRAGMA busy_timeout = 5000` (also `ensure_user_tables` at `:80`,
    `backup_database` verify at `database.py:295`).
  - migrations 007/008/009 — add `PRAGMA foreign_key_check` immediately
    before COMMIT to fail loudly if rebuild ordering breaks.
- **Plan**: switch to `BEGIN IMMEDIATE`; add `busy_timeout = 5000` on
  all migration/init connections; pin foreign_key_check.
- **Source**: indie-review 2026-04-25 theme T14 (Database lane H1+H2+H3).
- **Status**: done (v3.5.25) — runner now uses `BEGIN IMMEDIATE`;
  busy_timeout=5000 set on the migration, `ensure_user_tables`, and
  `backup_database` verify connections; 007/008/009 each end with a
  scoped `PRAGMA foreign_key_check(<table>)` (scoped, not unscoped, so
  pre-existing FK debt elsewhere doesn't block the upgrade path on
  legacy installs). 5 regression tests in
  `tests/test_pass45_security.py::TestPass45_10*`. Two pre-existing
  test fixtures updated to handle the new pragma + the seeded games row.

#### Pass 45.11 `/api/settings/logging` POST bypasses validator (HIGH, S)

- **Targets**: `routes/settings.py:579`.
- **Why**: writes `data` directly to `settings['logging']` without
  calling `validate_settings_value('logging', data)`. The validator
  exists at `services/settings_validators.py:182-199` but is unwired.
  An admin (or admin under XSRF, even though CSRF protected) can
  persist a malformed logging block that crashes
  `log_manager.setup_all_logging()` on next start.
- **Plan**: route through `validate_settings_value`. Same for
  `/api/scraper-settings` POST and `/api/scraper-api-keys` POST
  (`routes/scraper.py:228, 263`) — author per-key validators in
  `services/scraper_settings_validators.py`.
- **Source**: indie-review 2026-04-25 (Maintenance/settings lane P1+P2).
- **Status**: done (v3.5.26) — `/api/settings/logging` POST now routes through
  `validate_settings_value('logging', data)` and returns 400 on malformed
  bodies (Pass 32.2 validator was unwired). New
  `services/scraper_settings_validators.py` mirrors the
  `services/settings_validators.py` pattern with allowlists for `priority`,
  `enabled`, `minimum_match_score`, `match_mode`, `match_criteria` (top-level
  keys for `/api/scraper-settings`) and a 24-field allowlist for
  `/api/scraper-api-keys` with type+length+control-char checks. `ai_provider`
  enum-locked to `''/gemini/openai/claude`. 17 regression tests in
  `TestPass45_11*` (pure-function + end-to-end + source-position pin); test
  suite 633 → 650.

#### Pass 45.12 Xbox refresh-token rotation hardening (HIGH, M)

- **Targets**: `scraper/scrape_xbox.py:236-286`.
- **Why**: refresh on every sync (no `expires_at` tracking); revocation
  leaves stale tokens forever (no `clear_tokens` on 401-loop); `xuid`/
  `gamertag` not re-validated on refresh.
- **Plan**: track `expires_at = now + expires_in - 60s`; clear stored
  `xuid`/`gamertag` on refresh; `clear_tokens(user_id)` when refresh
  returns None.
- **Source**: indie-review 2026-04-25 (Platform imports lane H1).
- **Status**: done (v3.5.27) — `scraper/scrape_xbox.py` now exports
  `attach_expires_at(tokens)` which records `expires_at = now + max(60,
  expires_in - 60)`. `get_authenticated_session` short-circuits the
  refresh when the access_token is still fresh, drops stored `xuid`/
  `gamertag` on refresh (XSTS/profile re-validates), and calls
  `clear_tokens(user_id)` when refresh returns None. OAuth callback in
  `routes/platform_import.py` also calls `attach_expires_at` before
  `save_tokens` so the first connect carries an expiry. 8 regression
  tests in `TestPass45_12*`; suite 650 → 658.

#### Pass 45.13 IGDB token cache thread-safety + `y/z` redactor (HIGH, S)

- **Targets**:
  - `scraper/scrape_igdb.py:31` — `_igdb_token_cache` mutated by
    background threads without lock; concurrent expiry → duplicate
    Twitch OAuth calls.
  - `services/log_redactor.py:35` — RetroAchievements API key
    (`?y=KEY`) and username (`?z=USER`) flow through unredacted if
    any caller logs the full URL. Latent leak.
- **Plan**: wrap cache in `threading.Lock` mirroring
  `retroachievements._ra_console_cache_lock`. Add `y` and `z` to the
  URL-querystring redactor allowlist (narrow boundary `[?&]y=`).
- **Source**: indie-review 2026-04-25 (Per-source scrapers lane).
- **Status**: done (v3.5.28) — `scraper/scrape_igdb.py` adds
  `_igdb_token_cache_lock = threading.Lock()` mirroring
  `_ra_console_cache_lock`. Both `igdb_auth()` and the 401-retry cache
  reset in `igdb_request()` now wrap their cache mutations in
  `with _igdb_token_cache_lock:`. `services/log_redactor.py` extended
  the URL-querystring allowlist to include `y` and `z` (RA's `?y=KEY&z=USER`
  pattern) with the existing `[?&]` boundary so `?fancy=` / `?lazy=`
  remain untouched. 7 regression tests in `TestPass45_13*`; suite 658 →
  665.

#### Pass 45.14 TGDB / RAWG / IGDB add `max_bytes` (MEDIUM, S)

- **Targets**: `scraper/scrape_thegamesdb.py:85,150,170,190`,
  `scrape_rawg.py:124`, `scrape_igdb.py:84-90,102-108`.
- **Why**: each calls `http_get` without `max_bytes`; OOM risk on
  malicious or buggy upstream.
- **Plan**: pass `max_bytes=getattr(config, 'MAX_API_RESPONSE_BYTES',
  10*1024*1024)` (matches RA + AI + ScreenScraper precedent).
- **Source**: indie-review 2026-04-25 theme T4.
- **Status**: done (v3.5.29) — 5 call sites across `scrape_thegamesdb.py`,
  `scrape_rawg.py`, `scrape_igdb.py` now pass `max_bytes` (resolved once at
  module import via `_<module>_MAX_BYTES = getattr(config,
  'MAX_API_RESPONSE_BYTES', 10*1024*1024)`). Both IGDB primary + 401-retry
  http_post sites carry the cap. 6 regression tests in `TestPass45_14*`;
  suite 665 → 671.

#### Pass 45.15 Migration 010 missing CASCADE FKs (MEDIUM, S)

- **Target**: `services/migrations/scripts/010_user_game_views.py:43-49`.
- **Why**: composite PK exists but no `FOREIGN KEY (game_id) REFERENCES
  games(id) ON DELETE CASCADE` and no `FOREIGN KEY (user_id) REFERENCES
  users(id) ON DELETE CASCADE`. When games or users are deleted, rows
  orphan; recently-viewed query joins return inconsistent results.
- **Plan**: write migration 011 (or higher — collision-aware after
  feat/multi-emulator-launch merges) adding CASCADE FKs via table-rebuild.
- **Source**: indie-review 2026-04-25 (Database lane M1).
- **Status**: done (v3.5.30) — migration `011_user_game_views_cascade_fk`
  rebuilds `user_game_views` with `FOREIGN KEY (game_id) REFERENCES
  games(id) ON DELETE CASCADE` and `FOREIGN KEY (user_id) REFERENCES
  users(id) ON DELETE CASCADE`. Pre-existing orphans dropped during the
  INSERT (INNER JOIN both parents). Idempotent: skips rebuild if both FK
  clauses already present. `PRAGMA foreign_key_check(user_game_views)`
  before commit (Pass 45.10 pattern). 7 regression tests in
  `TestPass45_15*`; suite 671 → 678.

#### Pass 45.16 `aria-current` rollout to remaining 50+ nav links (HIGH, M)

- **Targets**: `templates/dashboard.html:8` (8 tabs),
  `templates/analytics.html:8` (6 tabs),
  `templates/museum_system.html:58` (4 tabs),
  `templates/settings.html` 7 subnavs (~30 links),
  `rom_tools_settings.html:249`, `duplicate_finder.html:174`,
  `screenshot_dedup.html:239`, `chd_verify.html:91`,
  `multi_disc_organizer.html:174`, `archive_scanner.html:564`,
  `chd_converter.html:71`.
- **Plan**: extract `nav_active(cond)` macro to a shared partial;
  apply to every `class="* active"` nav link. Same WCAG 2.4.3 criterion
  Pass 41.13.A handled for the sidebar.
- **Source**: indie-review 2026-04-25 theme T10 (Templates & CSS lane).
- **Status**: done (v3.5.31) — chose one-time wiring over 70-call-site
  refactor: new `_setupTabbarAriaCurrent` + `_syncAriaCurrent` in
  `static/js/main.js` mounts a MutationObserver per `[data-tabbar]`
  container that mirrors `.active` ↔ `aria-current="page"` on descendant
  links. Templates updated: dashboard / analytics / museum nav (3 JS-
  toggled tab bars), all 6 settings subnav containers, 7 rom-tools page-
  link tabs (server-rendered with static `aria-current="page"`). Top-
  level settings tabs use `role="tablist"` + `aria-selected` (correct
  ARIA pattern for tabs proper) and were left unchanged. 7 regression
  tests in `TestPass45_16*`; suite 678 → 685.

#### Pass 45.17 `ModalFocusTrap` rollout to 20+ remaining dialogs (HIGH, M)

- **Targets**: `templates/base.html:290` `customModal`,
  `:307` `folderBrowserModal`, `:640` queue-manager,
  `:858` `gameDetailModal`, `:939` `gameEditModal`,
  `_modals/scrape_modal.html`, `_modals/edit_modal.html`,
  `_modals/filter_modal.html`, `wishlist.html:50`, `tags.html:37`.
- **Why**: only 6/26 dialogs activate the focus trap; Tab key escapes
  the modal (WCAG 2.1.2 No Keyboard Trap inverted — a focus-leak).
- **Plan**: pair `ModalFocusTrap.activate()` with every `.classList.add('active')`
  open path; `.deactivate()` on close.
- **Source**: indie-review 2026-04-25 theme T11.
- **Status**: done (v3.5.32) — same one-time-wiring strategy as Pass 45.16:
  new `ModalFocusTrap.autoAttach(modalEl, opts)` in `static/js/utils.js`
  mounts a MutationObserver per `[data-focus-trap]` element that
  mirrors `.active` ↔ `activate/deactivate`. Per-modal config via
  `data-focus-trap-onescape="closeFn"` and `data-focus-trap-content=
  ".selector"`. 12 dialogs marked: userModal, confirmModal,
  editControllerModal, tagModal, wishlistModal, listModal, addGameModal,
  searchModal, batchRenameModal, scrapeModal, editModal, renameModal,
  boxartZoomModal. Modals already wiring the manual API (game detail/
  edit, custom, queue, folder browser, filter, bulk-edit/scrape,
  museum lightboxes) are left alone — opt-in attribute prevents double-
  attach. 7 regression tests in `TestPass45_17*`; suite 685 → 692.

#### Pass 45.18 Source-grep test antipattern (HIGH systemic, L)

- **Targets**: `tests/test_pass40_security.py`, `test_pass41_security.py`
  (78 cases / 1645 LOC), `test_pass33_34_hardening.py`,
  `test_pass35_36_hardening.py`, `test_auth_hardening.py`. ~140
  `open(path).read()` + `getsource()` substring assertions across
  these.
- **Why**: tests fail on rename/refactor and pass on real regressions
  when the implementer keeps the string. The "regression coverage"
  is regression-of-our-own-fix, not contract verification.
- **Plan**: rewrite as functional `client.get/post` assertions where
  possible (Pass 40.x routes are testable via the test client).
  Where source-grep is unavoidable (e.g. decorator presence), assert
  via `app.view_functions[...].__wrapped__.__qualname__` or runtime
  introspection rather than regex over `.py` files. L-sized — gate
  on test-quality budget pass.
- **Source**: indie-review 2026-04-25 theme T7 (Tests/tooling lane).
- **Status**: done (v3.5.34) — three-bucket audit instead of mass
  rewrite. Bucket A (8 tests converted): `test_33_6_logout_clears_
  session` (functional session-clear via test client), `test_34_5_log_
  filename_uses_utc` (clock-pin via monkeypatched datetime), `test_35_
  4_init_database_issues_wal` (PRAGMA queried from fresh DB), `test_
  decode_error_no_silent_pass` (Pass 41.11.A — caplog of museum decode
  failure), `test_admin_cleanup_endpoint_*` (Pass 41.11.B — `app.url_
  map.iter_rules()` instead of source-grep), `test_recently_viewed_
  endpoint_deleted` (Pass 41.9.B — URL-map absence check), `test_
  helper_defined` (Pass 41.14.C — direct import), `test_bulk_scrape_
  uses_singleton_lock` (Pass 41.6.A — `hasattr` introspection),
  `test_rename_rom_rejects_path_traversal_in_filename` (exercise
  `safe_filename()` with attack inputs), `test_uuid4_still_used` (Pass
  41.10.C — uuid4 generated and import wired), and `test_worker_
  invokes_full_persist_lifecycle` (Pass 40.9 — consolidates 4 prior
  source-grep tests into one behavioral pin). Bucket B (~25 tests
  kept, file-header annotated): cross-file invariants (no
  `time.sleep` in jobs, no bare `get_db()` in routes, no `for g in`
  shadows, no `foreign_keys = OFF` in migrations), JS/template
  patterns (XSS sinks, AbortController, navigation guard, aria-current
  macro), atomic-write `.part` + `os.replace` source pins, SQL JOIN-
  on-user_id shapes, decorator-stack pins, PRAGMA `foreign_keys = ON`
  (per-connection — functional check would only verify the test's own
  connection). Bucket C (7 tests deleted): `test_post_handler_
  validates_input` (Pass 40.1, redundant with e2e), `test_staging_
  folder_not_user_supplied` (Pass 40.3, fragile shape-pin), `test_
  two_users_get_different_etags` (Pass 40.5, admits not-actually-
  e2e), `test_screenshot_sync_runs_unconditionally` (Pass 41.4.A,
  pure marker tautology), `test_offset_bounds_check` (Pass 41.7.A,
  marker tautology), `test_decompressionbombexception_caught` (Pass
  41.14.A, duplicated by functional bomb test), `test_rate_limit_
  applied_to_change_password` (24.4, duplicated by Pass 41.1.B
  functional bucket-isolation), `test_igdb/tgdb_initializes_players_
  none` (Pass 40.6, duplicated by `tests/test_scrape_fill_only.py`).
  Suite 695 → 683 (−12 net). Fidelity-checked: temporarily reverting
  `session.clear()` → `session.pop('user_id')` in `routes/auth.py`
  fails `test_33_6_logout_clears_session`; reverting `journal_mode =
  WAL` → `DELETE` in `services/database_init.py` fails `test_35_4_
  init_database_issues_wal`. Both restored after verification.

#### Pass 45.19 release.yml heredoc indentation (HIGH, S)

- **Target**: `.github/workflows/release.yml:55-64`.
- **Why**: `python - <<'PY'` heredoc has 10 spaces of leading whitespace
  on every line; `python -` reads stdin and parses module-level
  indented code as `IndentationError`. The release workflow as written
  cannot succeed; tag-driven release path likely unexercised since the
  SHA-pin/SLSA refactor.
- **Plan**: dedent heredoc, OR factor to `scripts/ci_build_dist.py`
  invoked as `python scripts/ci_build_dist.py`.
- **Source**: indie-review 2026-04-25 (Tests/tooling lane P1).
- **Status**: done (v3.5.15) — both `python - <<'PY'` blocks (build ZIPs +
  extract changelog) migrated to env-var + `python -c "$VAR"`; YAML `|`
  block-literal strips the indent baseline before bash interpolates.
  2 regression tests in `tests/test_pass45_security.py::TestPass45_19*`.

#### Pass 45.20 chmod-after-verify race + `<button type="button">` sweep (MEDIUM, S)

- **Targets**:
  - `services/database.py:295-323` — chmod 0o600 happens after the
    integrity-check open; brief 0644 window.
  - 419 `<button onclick="..."` across templates without explicit
    `type="button"`. Inside `<form>` defaults to submit → silent form
    submission.
- **Plan**: chmod before reopen for verify; sweep templates adding
  `type="button"` to every onclick-bearing button (or document `submit`
  intent where applicable).
- **Source**: indie-review 2026-04-25 (Database M3, Templates 11).
- **Status**: done (v3.5.33) — chmod-before-verify race already closed in
  Pass 45.5; this sub-pass re-pins the contract via a second source-position
  assertion in `TestPass45_20*` so reverting fails two passes worth of
  tests. Button sweep: one-shot regex inserted `type="button"` next to
  every onclick-bearing `<button>` across 30 templates (419 buttons →
  zero remaining). Buttons outside forms get a no-op; buttons meant to
  submit didn't have onclick to begin with so the sweep doesn't break
  them. 3 regression tests in `TestPass45_20*`; suite 692 → 695.

---

### Security & input hardening — Tier-1 (indie-review 2026-04-24)

> Sixteen findings from the 14-agent independent review post-Pass 37 that
> represent concrete exploit paths or silent-corruption vectors under routine
> use.  Each has an external anchor (OWASP, CWE, RFC, or prior-pass invariant)
> and a fix-sketch.  Land one-per-commit with red/green test pairs per the
> remediation workflow.

#### Pass 40.1 RCE via unvalidated `chdman_path` in `rom_tools_config.json` POST (CRITICAL, S)

- **Target**: `routes/tools.py:196-208` (`api_rom_tools_settings` POST).
- **Why**: `@login_required` only; JSON body written verbatim via
  `atomic_write_json(config_path, settings)`.  Downstream
  `subprocess.run([chdman_path, 'createcd', ...])` at `:618`/`:691` uses
  the attacker-supplied argv[0].  `shutil.which()` happily resolves
  `/usr/bin/python3` or `/tmp/evil`.  CWE-78 command injection via argv[0]
  substitution; logged-in-user → arbitrary code execution with Flask UID.
- **Plan**: (1) raise to `@admin_required`.  (2) author a
  `rom_tools_validators.py` mirroring `services/settings_validators.py`
  — whitelist `chdman_path` to `'chdman'` or resolved path under
  `/usr/bin|/usr/local/bin|bundled tools dir`; reject absolute paths to
  writable dirs; per-key allowlist validator for every other field.
- **Source**: 2026-04-24 indie-review, settings/maintenance/tools C1.
- **Status**: done (v3.4.1) — `services/rom_tools_validators.py` mirrors
  `settings_validators.py`; POST gated to admin via in-handler 403 check
  (GET stays login-required for the archive-scanner page); `chdman_path`
  validator allowlists bare name or absolute path under
  `/usr/bin|/usr/local/bin|/opt/homebrew/bin|/opt/local/bin|/bin` with
  basename anchored to `chdman`/`chdman.exe`; every other key has a
  per-shape validator. Tests: `test_pass40_security.py` (22 cases).

#### Pass 40.2 Arbitrary-path CHD convert + source file delete (CRITICAL, S)

- **Target**: `routes/tools.py:571-654` (`api_chd_converter_convert`) +
  `:682-752` (`api_chd_verify_verify`).
- **Why**: `files[]` list from request body goes straight into
  `subprocess.run([chdman_path, 'createcd', '-i', file_path, ...])` and
  `os.remove(file_path)` (when `chd_delete_originals=True`).  No
  `safe_path` check; `api_chd_converter_scan` correctly validates but the
  convert/verify endpoints don't.  Logged-in user → arbitrary file delete
  primitive.  CWE-22 path traversal.
- **Plan**: add `if safe_path(fp, _get_rom_path()) is None: continue`
  inside the `for file_path in files` loop of both endpoints.  Mirror
  the `api_duplicate_finder_delete` pattern which already gets this
  right.
- **Source**: 2026-04-24 indie-review, settings/maintenance/tools C2.
- **Status**: done (v3.4.2) — both worker loops now validate
  `safe_path(file_path, rom_root)` per iteration; rejected paths recorded
  as failed/invalid and skipped (mirrors `api_duplicate_finder_delete`).
  Tests: `test_pass40_security.py::TestPass40_2ChdConvertVerifyPathValidation`
  (4 cases including an `os.remove`-monitor smoke).

#### Pass 40.3 Archive-scanner batch extract + move to arbitrary paths (CRITICAL, S)

- **Target**: `routes/tools.py:479-525` (`api_archive_scanner_create_m3u`
  + `api_archive_scanner_batch_create_m3u`).
- **Why**: `@login_required` only; `paths` and `staging_folder` not
  validated.  `create_m3u_playlist` then runs unzip/7z/unrar on the
  archive and `shutil.move()` into `staging_folder`.  Logged-in user
  can extract archives anywhere the Flask process has write access.
- **Plan**: raise both endpoints to `@admin_required`; add per-entry
  `safe_path(p, _get_rom_path())` validation; restrict `staging_folder`
  to a pre-approved list.
- **Source**: 2026-04-24 indie-review, image/media #2.
- **Status**: done (v3.4.3) — both endpoints raised to `@admin_required`;
  `batch_create_m3u` loops paths up-front and rejects on first failed
  `safe_path`; `staging_folder` no longer accepted from request body
  (vestigial — zero UI callers; scanner uses its server-side default).
  Tests: `test_pass40_security.py::TestPass40_3ArchiveScannerM3u`
  (5 cases).

#### Pass 40.4 Steam achievement IDOR — three queries missing `user_id` filter (CRITICAL, S)

- **Target**: `routes/steam_achievements.py:31-40, 73-78, 80-84`.
- **Why**: Landing-page query joins `game_achievement_progress gap` without
  `AND gap.user_id = ?`; per-game progress query and per-game achievements
  query both omit the user filter.  Migration 009 added `user_id` to both
  tables, and `routes/xbox_achievements.py` is the correct template (lines
  33-43, 87-91, 94-98).  On a multi-user install, user A sees user B's
  earned-achievement counts.  CWE-639 IDOR; Pass 31.4's claim is present
  in a comment but the filter is not.
- **Plan**: copy the Xbox blueprint's `AND gap.user_id = ?` /
  `AND user_id = ?` into each of the three queries, bound to
  `g.user['id']`.
- **Source**: 2026-04-24 indie-review, achievements/trophies C1.
- **Status**: done (v3.4.4) — three Steam queries gained
  `AND gap.user_id = ?` / `AND user_id = ?` bound to `g.user['id']`
  (mirrors the Xbox blueprint). Tests:
  `test_pass40_security.py::TestPass40_4SteamAchievementsUserScoping`.

#### Pass 40.5 ETag cross-user cache bleed on `/api/games/card-data` (CRITICAL, S)

- **Target**: `routes/games.py:235`.
- **Why**: `etag_payload = f"cd:{...}:{max_updated}"` — `max_updated` is
  global, not per-user.  Per-user PSN and achievement progress join in
  lines 270/279.  User A's browser caches with the ETag; user B on the
  same browser sends A's `If-None-Match`, server 304s, B sees A's PSN
  numbers.  `Cache-Control: private` doesn't prevent cross-session reuse
  on the same client.  CWE-524 cache-bleed.
- **Plan**: append `str(g.user['id'])` to the ETag payload.
- **Source**: 2026-04-24 indie-review, game routes C1.
- **Status**: done (v3.4.5) — `etag_payload` now prepends
  `g.user['id']`; different users on the same client produce different
  ETags, no cross-user 304 reuse possible. Tests:
  `test_pass40_security.py::TestPass40_5CardDataEtagPerUser`.

#### Pass 40.6 `players` fill-only invariant broken at 3 sites (CRITICAL, S)

- **Target**:
  - `scraper/scrape_igdb.py:477-481, 591` — `players = 1` default + no
    `COALESCE(?, players)`.
  - `scraper/scrape_thegamesdb.py:876-882, 959` — same shape.
  - `routes/games.py:917-952` — `api_game_edit` stores raw string
    (SQLite weak typing lets `"1-4"` into an INTEGER column).
  - `routes/games.py:458, 551` — `edit_metadata` form-POST has the same
    bug.
- **Why**: CLAUDE.md "scraper fill-only invariant" requires every `?` to
  be wrapped in `COALESCE(?, column_name)` so empty API responses preserve
  curated values.  With `players` initialised to `1` instead of `None`,
  `COALESCE(1, players)` is always `1` — a curated "4-players" row
  silently becomes 1 after re-scrape.  The JSON-edit path compounds the
  issue by corrupting the column type.  Same bug class as Pass 30.4
  fixed for `publisher`/`developer`.
- **Plan**: in IGDB + TGDB adapters, initialise `players = None`, set
  only when the source provided a value, bind `players if players else
  None` through COALESCE.  In `api_game_edit` + `edit_metadata`,
  normalise via `generate_sort_title`-siblings helper that rejects
  ranges like `"1-4"` → 4, also triggers `cross_map_ratings` and
  `generate_sort_title` to match the form-POST path's contract.
  Extract a shared `_normalize_game_edit(dict) -> dict` helper used by
  both routes (addresses game-routes C3's cache-invalidation drift as
  a free side-effect).
- **Source**: 2026-04-24 indie-review, scraper adapters C2 + game routes
  C2/H4.
- **Status**: done (v3.4.6) — IGDB + TGDB initialise `players = None`,
  set only when source provides a value; bind `players if players else
  None` through COALESCE. New `normalize_players_value` helper in
  `services/game_utils.py` coerces ranges/junk/empty to `int|None`;
  wired into `api_game_edit` (per-field branch) and `edit_metadata`
  (form-POST). Tests: `test_pass40_security.py::TestPass40_6*` (12
  cases).

#### Pass 40.7 TGDB image downloads bypass SSRF (CRITICAL, S)

- **Target**: `scraper/scrape_thegamesdb.py:985-1043`
  (`_download_tgdb_image`).
- **Why**: calls `http_get(image_url, ...)` + `open(local_path,
  'wb').write(response.content)` with no `validate_outbound_url`, no
  redirect-chain check, no `max_bytes`, no streaming.  `metadata_merger`
  re-exports it and uses it on the default scrape path.  Because
  `requests` follows redirects by default, a crafted TGDB response
  with an image URL redirecting to `http://169.254.169.254/...` fetches
  cloud metadata and writes it to `static/images/boxart/`.  `base_scraper
  .download_image` is already hardened (Pass 32.6, 32.7, 25.7).  CWE-918.
- **Plan**: delete `_download_tgdb_image`; route through
  `metadata_merger._download_and_finalize` or `base_scraper.download_image`.
  Both are functionally equivalent and hardened.
- **Source**: 2026-04-24 indie-review, scraper adapters C1.
- **Status**: done (v3.4.7) — `_download_tgdb_image` now delegates to
  `base_scraper.download_image`; only TGDB-specific URL absolutization
  and filename construction remain in the wrapper. SSRF gate +
  redirect-walk + 50 MB streaming cap + partial-file cleanup all apply.
  Tests: `test_pass40_security.py::TestPass40_7TgdbImageSsrf`.

#### Pass 40.8 Museum job `finally` clobbers `failed` status back to `completed` (CRITICAL, S)

- **Target**: `services/jobs/museum.py:136-336`.
- **Why**: two early-exit failure paths at lines 189 (no-AI-provider) and
  213 (unknown-provider) call `persist_job_complete(persist_id,
  status='failed', ...)` and `return` without setting `persist_id = None`.
  The `finally:` block at 334 then calls
  `persist_job_complete(persist_id, status=final_status)` a second time,
  overwriting 'failed' with 'completed'.  Silent data corruption — a
  mis-configured admin sees "Completed" in `job_queue` with no error
  trace.
- **Plan**: set `persist_id = None` after every early-return
  `persist_job_complete('failed')` call (the `except` branch at 321-323
  already does this correctly).  Alternative: collapse the early-exit
  paths into guard-blocks so exactly one terminal persist runs in the
  `finally`.
- **Source**: 2026-04-24 indie-review, jobs C1.
- **Status**: done (v3.4.8) — both early-exit failure paths
  (no-AI-provider, unknown-provider) now `persist_id = None` after the
  `persist_job_complete('failed')` call, so the `finally` block's
  `if persist_id:` guard short-circuits and the recorded failure
  survives. Tests:
  `test_pass40_security.py::TestPass40_8MuseumJobFailedStatusPreserved`.

#### Pass 40.9 ImageResizeJob has no persistence, no lock, no shutdown recovery (CRITICAL, M)

- **Target**: `services/jobs/image_resize.py`.
- **Why**: `_worker` never calls `persist_job_start`/`persist_job_progress`/
  `persist_job_complete`; reads/writes `self.running`, `self.cancelled`,
  `self.current_index`, `self.total_images` without `self._lock`;
  `get_status()` reads without the lock either.  A bulk resize of 10,000
  boxart files interrupted at 8,000 has zero DB record of ever running.
  `request_shutdown` at `base.py:56` includes the job in its cancel
  candidates, which only sets the in-memory flag — no persisted audit
  trail.  Worst-of-both-worlds: acts cancellable without any cancellation
  record.
- **Plan**: either (a) bring up to `base.py` convention — wrap `_worker`
  in `persist_job_start`/`persist_job_progress` ticks (every 10 items),
  take `self._lock` around all counter reads/writes, add
  `resolve_terminal_status` on exit; or (b) explicitly carve out — remove
  from `request_shutdown` candidates and document in a docstring as
  non-recoverable.  Option (a) is the lower-risk path.
- **Source**: 2026-04-24 indie-review, jobs C3.
- **Status**: done (v3.4.9) — `_worker` now calls `persist_job_start` /
  `persist_job_progress` (every 10 items or 30s) / `persist_job_complete`
  with `resolve_terminal_status`; every shared-counter read/write is
  inside `with self._lock`; `get_status()` snapshots state under the
  lock and computes derived fields outside. Failure path mirrors the
  museum/bulk-scrape pattern (`persist_id = None` after failure).
  Tests: `test_pass40_security.py::TestPass40_9ImageResizeJobBaseConvention`.

#### Pass 40.10 Rate-limit `time.sleep` blocks shutdown drain, loses progress (CRITICAL, M)

- **Target**: `services/jobs/psn_refresh.py:433, 459`,
  `platform_sync.py:452, 767`, `ra_sync.py:359`, `ra_refresh.py:306`,
  `museum.py:272, 283, 315`.
- **Why**: per-iteration `time.sleep()` with durations 0.5-2.5s ignores
  both `self.cancelled` and `shutdown_requested`.  Combined with blocking
  HTTP timeouts up to 300s and `request_shutdown(timeout=5.0)`, a SIGTERM
  during any sleep or in-flight call expires the drain budget.  The
  daemon thread is killed mid-operation with un-persisted progress lost
  and DB writes possibly half-committed — `job_queue` row stays
  `status='running'` until the startup sweep marks it interrupted, and
  up to 30s of committed work is re-done on resume.
- **Plan**: replace every `time.sleep(d)` in `services/jobs/*.py` with
  `shutdown_requested.wait(d)` — when the event is set, the sleep
  short-circuits.  Separately, either cap outbound HTTP timeouts below
  the shutdown budget (e.g. 4s) or lengthen the budget to fit realistic
  API call durations (30-60s is more honest for PSN/RA sync).  Pick one
  explicitly — document the decision.
- **Source**: 2026-04-24 indie-review, jobs C2.
- **Status**: done (v3.4.10) — every `time.sleep(d)` in
  `services/jobs/{psn_refresh, platform_sync, ra_sync, ra_refresh,
  museum}.py` replaced with `shutdown_requested.wait(d)`. SIGTERM now
  collapses rate-limit waits in &lt; a few ms; the pause loop in
  `psn_refresh._run_full_refresh` uses the same primitive so paused
  jobs unblock too. Tests:
  `test_pass40_security.py::TestPass40_10ShutdownAwareSleep`. (HTTP
  timeout vs shutdown-budget tension was a separate point in the
  finding — leaving outbound timeouts as-is for now; we trade SIGKILL
  on rare in-flight HTTP calls for honest API durations.)

#### Pass 40.11 CHD conversion non-atomic + dead `chd_verify_after_convert` (CRITICAL, M)

- **Target**: `scraper/rom_tools.py:1129-1188` (`CHDConverter._convert_file`),
  `routes/tools.py:602-648` (inline worker).
- **Why**: both paths run `chdman createcd -i src -o dst` where
  `dst = src.with_suffix('.chd')`.  chdman writes to the final path; any
  mid-run kill (subprocess.TimeoutExpired at :1177, SIGKILL from OOM)
  leaves a truncated `.chd`.  If `chd_delete_originals=True` and chdman
  exits 0 with a warning-ridden partial output, `src.unlink()` fires.
  Next run sees `dst.exists() → True`, `chd_skip_existing=True` → skipped.
  Permanent corruption.  `chd_verify_after_convert: bool = True` is
  declared in the `ROMToolsConfig` dataclass but grep returns zero
  readers — the setting is surfaced in the UI but does nothing.
- **Plan**: (1) write chdman output to `dst.with_suffix('.chd.part')`.
  (2) if `config.chd_verify_after_convert`, run `chdman verify -i tmp`
  after successful conversion; fail the task if verify fails.  (3)
  `os.replace(tmp, dst)` only after verify (or on settings-off). (4) on
  any exception path, `tmp.unlink(missing_ok=True)`.  (5) deduplicate
  the `CHDConverter` class and the `routes/tools.py` inline worker —
  one implementation.
- **Source**: 2026-04-24 indie-review, image/media #3.
- **Status**: done (v3.4.11) — both paths now write to `.chd.part`,
  optionally `chdman verify -i tmp` (default on) before
  `os.replace(tmp, dst)`; `finally` unlinks the tempfile on any
  exception/timeout so the directory entry never points at a partial
  file. Source `.unlink()` only after the verified `.chd` is in place.
  CHDConverter and the inline worker still duplicated &mdash; left for a
  later refactor pass; both implementations now have identical
  semantics. Tests:
  `test_pass40_security.py::TestPass40_11ChdAtomicConversion`.

#### Pass 40.12 Toast-controller XSS on `job.system_name` (CRITICAL, S)

- **Target**: `static/js/toast-controller.js:1462-1467`.
- **Why**: `${job.system_name || 'Multi-System'}` interpolated into
  `toast.innerHTML` without escape; `${type}`/`${job.job_id}`
  interpolated into an inline `onclick=` JS-string-in-HTML-attribute
  double-decode context.  Every other toast path uses
  `this.escapeHtml()` — this site is the anomaly.  A system name of
  `<img src=x onerror=alert(1)>` fires in admin context.  CWE-79
  reflected XSS; Pass 29/36 regression.
- **Plan**: wrap `${job.system_name}` with `this.escapeHtml()`; replace
  the inline `onclick` with `addEventListener` in a separate JS
  statement using `data-job-id` + `data-job-type` attributes via
  `escAttr` (pattern already in `all-games-controller.js:1362`).
- **Source**: 2026-04-24 indie-review, frontend JS C1.
- **Status**: done (v3.4.12) — `job.system_name` and `config.name` now
  `escapeHtml`'d; inline `onclick="...cancelQueued('${type}', ...)"`
  replaced with `data-cancel-queued` + post-innerHTML
  `addEventListener` closing over `type`/`job.job_id` as JS values
  (no string concat into HTML). Tests:
  `test_pass40_security.py::TestPass40_12ToastControllerXss`.

#### Pass 40.13 `showModal` HTML auto-detect heuristic is blocklist XSS sink (CRITICAL, M)

- **Target**: `templates/base.html:385-401`.
- **Why**: `if (message.includes('<') && message.includes('>'))` triggers
  an `innerHTML` render with a `<script>`-only strip — misses `<img
  onerror=>`, `<svg onload=>`, `<iframe src=javascript:>`, and any event
  handler on any element.  Dozens of call sites pass `'Error: ' +
  data.error` — the day a server echoes user-controlled text containing
  both brackets, every page becomes a reflected-XSS sink.  The settings-
  page `ConfirmModal.show` (`settings-page.js:553-560`) gets this right
  with opt-in `allowHtml` — the two implementations disagree.  CWE-79.
- **Plan**: mirror settings-page `ConfirmModal.show` — default to
  `textContent`; require explicit `allowHtml: true` opt-in.  Remove the
  `<script>`-strip heuristic entirely.  Audit callers and migrate the
  handful that legitimately need HTML.
- **Source**: 2026-04-24 indie-review, frontend JS C3.
- **Status**: done (v3.4.13) — `showModal` defaults to `textContent`
  with line-break preservation; opt-in `{allowHtml: true}` via new 6th
  `options` argument. Auto-detect heuristic removed. 131 existing
  callers all pass plain text, so no migration needed. Tests:
  `test_pass40_security.py::TestPass40_13ShowModalOptInHtml`.

#### Pass 40.14 PSN trophy-detail game-link search XSS (CRITICAL, S)

- **Target**: `templates/psn_trophy_detail.html:815-831`.
- **Why**: user-authored `game.title` / `game.boxart` / `game.system`
  interpolated into a template literal (both HTML-text and attribute
  contexts) then `resultsDiv.innerHTML = html;`.  Only mitigation is
  `.replace(/'/g, "\\'")` on `title` for the `onclick` JS-string context
  — nothing for HTML-text or attribute contexts.  Payload of title
  `"><img src=x onerror=alert(1)>` escapes the div; boxart `x"
  onerror=alert(1) x="` escapes the `src` attribute.  `setup.html:360-
  393` demonstrates the correct pattern with `escapeHtml`/`escapeAttr`.
  Pass 35 (XSS round 2) regression.  CWE-79.
- **Plan**: wrap every `${game.title}` / `${game.boxart}` /
  `${game.system}` with `escapeHtml()` (text context) or `escapeAttr()`
  (attribute context); refactor the inline `onclick="linkGame(...)"`
  to `data-game-id` + `addEventListener` so the single-quote sanitiser
  stops being load-bearing.
- **Source**: 2026-04-24 indie-review, templates C1.
- **Status**: done (v3.4.14) — local `esc` + `escAttr` helpers wrap
  every text and attribute interpolation; inline `onclick="linkGame(...)"`
  replaced with `data-link-game` + `data-game-{id,title,system}` and
  a post-innerHTML `addEventListener` closing over the dataset values.
  Tests: `test_pass40_security.py::TestPass40_14PsnTrophyDetailXss`.

#### Pass 40.15 `base_scraper.download_image` non-atomic + stale-clear race (CRITICAL, S)

- **Target**: `scraper/base_scraper.py:257-358` (`download_image`) +
  `scraper/hybrid_scraper.py:593-632` (stale-clear) +
  `services/media_cleanup.py:100-166` (orphan sweep).
- **Why**: `download_image` streams `open(dest_path, 'wb')` directly to
  final path; any mid-stream exception (connection reset, OOM) leaves a
  partial file, and the `if os.path.exists(dest_path): return True` at
  :274 means a later scrape treats it as "already downloaded" forever.
  Only IGDB uses this path; `metadata_merger._download_and_finalize`
  already uses `tempfile.mkstemp` + `os.replace` and has SSRF gates.
  Separately, the stale-ref auto-clear issues `UPDATE games SET {field}
  = NULL WHERE id = ?` without a check that the DB value is still the
  stale filename observed — so a concurrent upload between stat and
  UPDATE gets its new reference wiped and the file orphaned.  Orphan
  sweep compounds by deleting the now-dangling file.
- **Plan**: (1) copy `metadata_merger._download_and_finalize` scaffold
  into `base_scraper.download_image` — tempfile + fsync + `os.replace`.
  Unlink tempfile on any exception.  (2) tighten stale-clear to
  `UPDATE games SET {field} = NULL WHERE id = ? AND {field} = ?` binding
  both the row id and the stale filename captured at stat time.  (3)
  have `find_orphaned_media` re-check the DB per file when the
  prefix-ID fallback fails, or take an advisory lock.
- **Source**: 2026-04-24 indie-review, scraper adapters H1 + image/media
  H1 + H2.  Upgraded to CRITICAL under threat-model calibration because
  combining all three yields silent cross-user data loss.
- **Status**: done (v3.4.15) — `download_image` now uses
  `tempfile.mkstemp` + fsync + `os.replace`; `finally` drops orphaned
  `.dl-*.part` on any error path. `hybrid_scraper` stale-clear now
  conditions the UPDATE on `AND {field} = ?` binding the observed
  filename so concurrent uploads aren't wiped. Tests:
  `test_pass40_security.py::TestPass40_15DownloadImageAtomic`
  (source pin, functional smoke, conditional-UPDATE pin).

#### Pass 40.16 Missing `docs/PROXY-DEPLOY.md` referenced in `app.py:147` (HIGH, S)

- **Target**: `docs/PROXY-DEPLOY.md` (non-existent), referenced by
  `app.py:147` comment "See docs/PROXY-DEPLOY.md (added in this pass)
  for the trust contract."
- **Why**: operators enabling `RETRODB_TRUST_PROXY=1` have no guidance
  on required nginx/Caddy headers.  Misconfigure and `X-Forwarded-For`
  becomes attacker-controlled, defeating IP-based rate limiting.  The
  `ProxyFix` parameters (`x_for=1, x_proto=1, x_host=1, x_prefix=0`)
  assume a single trusted hop — undocumented assumption.
- **Plan**: either (a) author `docs/PROXY-DEPLOY.md` describing the
  required nginx/Caddy configuration (must-terminate-TLS-at-proxy,
  must-strip-and-re-emit-XFF-from-client, one hop only), or (b) drop
  the false reference and inline a 3-line comment naming the hop
  assumption.  (a) is the right call — other operators will hit this.
- **Source**: 2026-04-24 indie-review, app bootstrap H1.
- **Status**: done (v3.5.0) — `docs/PROXY-DEPLOY.md` authored: trust
  contract (one hop; proxy strips and re-emits XFF), copy-paste configs
  for nginx / Caddy / HAProxy, verification walk-through (forge XFF
  from client, confirm logs show the real IP), localhost-dev trap
  notes. Tests:
  `test_pass40_security.py::TestPass40_16ProxyDeployDocs`.

---

### Security & input hardening — Tier-2 (indie-review 2026-04-24)

> Forty-four HIGH findings after threat-model calibration.  Real
> correctness smells with concrete failure scenarios, but none carries
> a current-use exploit chain.  Group fixes by subsystem to minimise
> cross-cutting churn.

#### Pass 41.1 Auth — three decorator / bucket hygiene findings

- **Targets**:
  - `services/auth.py:204` — `login_required` inline allow-list bypass
    for 5 endpoint names is a footgun (any future endpoint that
    collides with the list becomes silently public).
  - `routes/auth.py:348-368` — `api_change_password` rate-limit bucket
    keyed on IP-only, shared with `/api/login` — allows cross-user LAN
    lockout.
  - `services/auth.py:96` — `needs_rehash` only upgrades on successful
    login; idle accounts keep weaker 100k-iter hashes indefinitely.
- **Why**: decorator allow-lists are the worst place for silent bypass;
  shared rate-limit buckets across orthogonal surfaces fail-close the
  wrong thing; OWASP ASVS V2.4.5 requires a path for inactive-account
  rehash.
- **Plan**: (1) remove the 5-name allow-list from `login_required`;
  attach the decorator only where needed.  (2) re-key change-password
  rate bucket to `(ip, user_id)`.  (3) add a background sweep or
  startup check flagging users with stale hash params for admin
  attention.
- **Source**: 2026-04-24 indie-review, auth H1/H2/H3.
- **Status**: done (v3.5.1) — A: allow-list dropped from `login_required`
  (none of the listed endpoints had `@login_required` applied today, so
  the allow-list was dead-code-as-footgun). B: `api_change_password`
  rate bucket now `f"{ip}:cpw:{user_id}"` — isolated from `/api/login`
  AND per-user. C: `services/auth.count_stale_password_hashes()` helper
  + `app.py` startup sweep that emits `logger.warning` when active
  users hold below-floor or malformed PBKDF2 hashes. Tests:
  `tests/test_pass41_security.py::TestPass41_1A/B/C` (10 cases).

#### Pass 41.2 Database — FK-OFF PRAGMA is no-op inside transaction; connection leaks in 10+ route sites

- **Targets**:
  - `services/migrations/__init__.py:83` — `conn.execute("BEGIN")`
    runs before per-migration PRAGMAs, so `PRAGMA foreign_keys = OFF`
    in migrations 007/008/009 is silently ignored (SQLite docs: FK
    state cannot change mid-transaction).
  - `routes/museum.py` (10+ sites), `routes/tools.py:1202`,
    `routes/trophies.py:1804` — raw `get_db()` without matching
    `.close()`.  Each leak holds a file handle + 64 MB cache.
- **Why**: the rebuilt `psn_games` / `collector_trophies` /
  achievement tables happen to work today only because no FK was
  declared `DEFERRABLE`; a future migration that does introduce a
  deferred-FK will silently corrupt on rebuild.  Connection leaks
  compound under load.
- **Plan**: (1) move `conn.execute("BEGIN")` to *after* the PRAGMA
  preamble, or convert 007/008/009 to `PRAGMA defer_foreign_keys = ON`
  which works inside a txn.  (2) route every leaking `get_db()` through
  `get_request_db()` (teardown-managed).
- **Source**: 2026-04-24 indie-review, database H1/H2.
- **Status**: done (v3.5.2) — A: migrations 007/008/009 now use
  `PRAGMA defer_foreign_keys = ON` (works inside a txn; auto-resets at
  COMMIT) instead of the no-op `PRAGMA foreign_keys = OFF`. B: 10 leaking
  sites in `routes/museum.py` (8), `routes/tools.py:1316`,
  `routes/trophies.py:1804` routed through `get_request_db()` so the
  teardown-appcontext handler closes them. Tests:
  `tests/test_pass41_security.py::TestPass41_2A/B` (6 cases).

#### Pass 41.3 App bootstrap — CSP nonce zombie + `'system'` log category dead + redactor ordering

- **Targets**:
  - `app.py:342-356` — CSP Report-Only header references
    `nonce-{{csp_nonce}}`; `grep -rn csp_nonce templates/` → zero hits.
    CSP is effectively unshipped.  (Feeds FU.1.)
  - `log_manager.py:55, 58` — `'system'` category listed but has no
    logger names; creates empty log files that mislead operators.
  - `app.py:631-639` — `install_global_redactor()` runs *after*
    `logging.basicConfig()`; intermediate log records emitted between
    the two lines bypass redaction.  `services/database_init.py:150`
    logs default admin/admin creds verbatim.
- **Plan**: wire CSP migration per FU.1.  Drop or populate the
  `'system'` category.  Move `install_global_redactor` before
  `basicConfig`; scrub the default-creds log line.
- **Source**: 2026-04-24 indie-review, app bootstrap H2/M3/M4.
- **Status**: done (v3.5.3) — A: `install_global_redactor()` now runs
  BEFORE `logging.basicConfig()` (and again after, idempotent) so the
  root-level filter is in place from first emit. B: default-admin
  log line scrubbed at `services/database_init.py` — username only,
  no plaintext password. C: `'system'` dropped from
  `log_manager.LOGGER_CATEGORIES` (was orphan: listed in categories,
  missing from `CATEGORY_LOGGERS`, created empty daily files). CSP
  nonce zombie deferred to Pass 41.12 (gated on inline-onclick removal).
  Tests: `tests/test_pass41_security.py::TestPass41_3A/B/C` (3 cases).

#### Pass 41.4 Scraper orchestration — ES-DE screenshot append lost + primary-source exceptions abort scrape

- **Targets**:
  - `scraper/hybrid_scraper.py:714-727` — sync-back from DB reload after
    `apply_esde_metadata` uses `if game.get(field) and not
    metadata.get(field):` guard; for `screenshots` the guard is False
    because metadata was pre-populated, so newly-appended screenshots
    are lost on the final UPDATE.
  - `scraper/hybrid_scraper.py:737-795` — primary-source dispatch has
    no per-source try/except; fallback dispatches do.  One malformed
    IGDB response aborts the whole hybrid apply; user sees "scrape
    failed" even when fallbacks could have filled gaps.  Orphan media
    files downloaded before the exception are never cleaned.
- **Plan**: (1) for `screenshots`, replace the guard with an
  unconditional copy from the reloaded DB value (after file-existence
  filter).  (2) wrap each primary dispatch in its own try/except; log
  and fall through to gap-fill.  Track downloaded file paths in a
  local list and `os.remove` them on exception.
- **Source**: 2026-04-24 indie-review, scraper orchestration H1/H2.
- **Status**: done (v3.5.4) — A: post-`apply_esde_metadata` sync now copies
  `screenshots` from the reloaded DB row unconditionally (file-existence
  filtered) before the guarded loop; `screenshots` removed from the loop's
  iteration list so the `not metadata.get(field)` guard never drops the
  appended scrape. B: each primary-source branch (esde/tgdb/igdb/rawg/
  screenscraper) wrapped in its own try/except — failure logged at
  WARNING, fall through to gap-fill. ES-DE branch additionally guards
  the gamelist.xml fetch with `esde_details = None` on exception, drops
  into the existing "no details" else-branch. Tests:
  `tests/test_pass41_security.py::TestPass41_4A/B` (3 cases).

#### Pass 41.5 Scraper adapters — credential leak in logs + adapters bypassing `base_scraper`

- **Targets**:
  - `scraper/scrape_steam.py` (7 endpoints) and `scraper/hltb_lookup.py`
    (3 endpoints) call raw `requests.get/post` — no retry+size-cap via
    `base_scraper`, no redactor coverage for URL params on exception.
  - `services/log_redactor.py:31` — querystring allowlist covers
    `apikey|api_key|token|auth|pwd|password|devpassword|ssid` but NOT
    `key=` (Steam) or `sspassword=` (ScreenScraper).  Exception
    `HTTPError` stringification exposes full URL → credentials leak
    to log files.
  - `scraper/scrape_igdb.py:86-87` — 401 from expired Twitch token
    doesn't invalidate the cached token; subsequent calls in the same
    scrape replay the dead token and silently return empty results.
- **Plan**: (1) route Steam + HLTB calls through `http_get`/`http_post`
  for retry/backoff/size-cap.  (2) add `key` and `sspassword` to the
  redactor querystring patterns (narrow to avoid false positives).
  (3) in `igdb_request`, on status 401, clear `_igdb_token_cache` and
  retry once with a fresh token.
- **Source**: 2026-04-24 indie-review, scraper adapters H1/H2/H3/H4.
- **Status**: done (H2/H3 v3.5.5; H1/H4 v3.5.47) — H2 (redactor) + H3 (IGDB 401) closed:
  `key` and `sspassword` added to `services/log_redactor.py` URL-
  querystring allowlist; `igdb_request` invalidates `_igdb_token_cache`
  and retries once with a fresh token on 401. H1/H4 (route Steam +
  HLTB raw `requests.get/post` through `base_scraper.http_get/post`)
  carried over as a follow-up — 10 callsites need case-by-case audit
  because `http_get` returns `None` on total failure where the current
  code expects `requests.get` semantics. Tests:
  `tests/test_pass41_security.py::TestPass41_5A/B` (5 cases).
  Closed (2026-06-10): H1/H4 carry-over landed in Pass 41.5.B
  (done v3.5.47) — all 7 Steam + 3 HLTB endpoints route through
  `base_scraper.http_get`/`http_post`, each call site guarded with
  `if resp is None:`; verified by
  `TestPass41_5bSteamHltbThroughBaseScraper`. Parent now fully resolved.

#### Pass 41.5.B Steam + HLTB through base_scraper (carry-over from 41.5)

- **Target**: `scraper/scrape_steam.py` (7 endpoints) and
  `scraper/hltb_lookup.py` (3 endpoints) — raw `requests.get`/`requests.post`.
- **Why**: `base_scraper.http_get` / `http_post` provide retry/backoff/
  size-cap; raw `requests.*` skips that hardening.
- **Plan**: replace each raw call with the `http_get`/`http_post` shape
  (returns `Response` or `None`); add explicit `if resp is None:` guards
  in callers that currently rely on `requests` raising on `None`.
- **Status**: done (v3.5.47) — all 7 Steam GETs + 1 HLTB GET + 2 HLTB POSTs
  routed through `base_scraper.http_get` / `http_post`. Each call site got
  an explicit `if resp is None:` early return preserving its original
  failure shape (`None` / `[]` / `{'valid': False, 'error': 'Connection
  error'}`); no behaviour change on success or on explicitly-handled status
  codes (Steam 400, HLTB 403). HLTB's existing 403 token-refresh retry path
  preserved with its own `None` guard. `requests` import retained in
  `scrape_steam.py` only because `requests.exceptions.HTTPError` is
  referenced as an explicit exception filter. Tests:
  `tests/test_pass41_security.py::TestPass41_5bSteamHltbThroughBaseScraper`
  (5 cases — source-grep + import-identity + functional `None`-handling
  for all 7 Steam wrappers and both HLTB internals).

#### Pass 41.6 Jobs — cross-process singleton + persist-under-lock + PSN inner-thread unsync

- **Targets**:
  - every job class (`bulk_scrape`, `psn_refresh`, etc.) — in-memory
    `self.running` flag only prevents concurrent starts in the same
    Python process.  Multi-worker WSGI (gunicorn `--workers 2`) has no
    cross-process guard; two workers can each run their own `bulk_scrape
    _job` singleton simultaneously against the same system.
  - `services/jobs/alt_titles_backfill.py:154-162`,
    `hltb_bulk.py:207-214` — `persist_job_progress` called inside
    `with self._lock`, blocking every status-poll request for 10-50ms
    per tick (up to 30s under WAL busy-timeout contention).
  - `services/jobs/psn_refresh.py:306-320` — `_fetch_titles` inner
    thread reads `self.cancelled` without the lock; if the outer 300s
    join times out, the inner thread continues updating shared state.
- **Plan**: (1) add a DB-advisory-lock (`fcntl.flock` on a sentinel
  file) around `start()` for each job type to guard multi-worker
  deployments.  (2) move `persist_job_progress` outside the lock
  block; follow `bulk_scrape.py:738-745` pattern.  (3) give
  `_fetch_titles` an explicit cancel event; treat the 300s timeout
  as "abandoned, may still run" and drop its state updates.
- **Source**: 2026-04-24 indie-review, jobs H1/H2/H3.
- **Status**: done (v3.5.14) — A: new
  `services/jobs/base.acquire_job_singleton_lock(name)` /
  `release_job_singleton_lock(fd)` helpers wrap
  `fcntl.flock(LOCK_EX | LOCK_NB)` on a sentinel file under
  `data/job_locks/`. Applied to `BulkScrapeJob` as the reference
  implementation; Windows / NFS gracefully degrade. B: persist payload
  snapshot under lock + persist call outside in
  `alt_titles_backfill.py` and `hltb_bulk.py` (matches
  `bulk_scrape.py:738-745` pattern). C: PSN `_fetch_titles` thread
  gets an explicit `threading.Event` set on cancel AND on the 300s
  timeout, so an abandoned inner thread stops writing shared state.
  Tests: `tests/test_pass41_security.py::TestPass41_6A/B/C` (7 cases);
  test fixtures updated to release the FD in teardown.

#### Pass 41.6.D Apply singleton lock to remaining 9 job classes (carry-over from 41.6.A)

- **Target**: `ra_sync`, `ra_refresh`, `psn_refresh`,
  `museum_generate`, `image_resize`, `steam_sync`, `xbox_sync`,
  `alt_titles_backfill`, `hltb_bulk`.
- **Why**: Pass 41.6.A landed the helper + the
  `BulkScrapeJob` reference implementation; the other 9 job classes
  still have no cross-process guard.
- **Plan**: same pattern — `start()` calls `acquire_job_singleton_lock`
  with the job name; the FD lives on `self._singleton_fd`; the worker's
  terminal cleanup releases it. Each job's existing test fixture needs
  the same teardown release pattern as `tests/test_bulk_scrape_job.py`.
- **Status**: done (v3.5.48) — all 9 job classes wired up. New helper
  `services.jobs.base.release_singleton_fd(self)` collapses the 3-line
  cleanup boilerplate to one line; idempotent across multiple terminal-
  cleanup branches in a worker. Each job: (1) `__init__` sets
  `_singleton_fd = None`; (2) `start()` acquires lock named
  `image_resize` / `alt_titles_backfill` / `hltb_bulk` /
  `museum_generate` / `ra_sync` / `ra_refresh` / `psn_refresh` /
  `steam_sync` / `xbox_sync` and refuses with a worker-process-busy
  message on `None`; (3) every cleanup path (early-return validations,
  normal completion, exception path) calls `release_singleton_fd(self)`.
  Six jobs with `resume_from_params` (museum, ra_sync, ra_refresh,
  psn_refresh, steam_sync, xbox_sync) acquire their own locks too —
  resume otherwise would silently shadow a fresh start on a different
  worker. Existing test fixtures (`test_hltb_bulk.py`,
  `test_museum_job.py`) don't call `start()` so no fixture changes
  needed; new regression class `TestPass41_6AExtendSingletonLockOtherJobs`
  (4 cases) functionally pins acquire-with-correct-name across all 9
  classes plus helper idempotency.

#### Pass 41.7 OAuth / trophy-parser — TROPUSR bounds hardening + Xbox redirect URL concat + RA 401 observability

- **Targets**:
  - `scraper/trophy_parser.py:189-216` — attacker-controlled
    `tables_count`/`entries_count`/`offset` in TROPUSR.DAT; inner
    `break` saves exploitability, but control flow relies on the
    reviewer proving early-exit rather than explicit bounds.
  - `routes/platform_import.py:484` — Xbox callback redirect uses
    `url_for(...) + '&xbox_connected=1'` — works only because
    `url_for` currently emits a query arg; brittle on future refactor.
  - `scraper/retroachievements.py:253-254` + 4 other callers — 401
    from stale RA API key falls through to generic `None` return;
    user sees "no RA entry found" instead of "check your API key."
- **Plan**: (1) prepend explicit `tables_count = min(tables_count,
  (len(data) - 0x30) // 32 + 1)` + `if offset >= len(data): return`
  guards.  (2) switch redirect to `url_for(..., xbox_connected=1)`
  kwarg form.  (3) in the 5 RA HTTP callers, add an `if
  response.status_code == 401: logger.error(...); return None` branch
  before the generic non-200 fallthrough.
- **Source**: 2026-04-24 indie-review, OAuth H1/H2/M5.
- **Status**: done (v3.5.6) — A: TROPUSR parser caps `tables_count` to
  `(len(data) - 0x30) // 32` up-front and early-returns from
  `_parse_table6` if `header['offset'] >= len(data)`. B: Xbox callback
  redirect now `url_for('game_imports.game_imports_page', tab='xbox',
  xbox_connected=1)` (kwarg form, no fragile string concat). C: 5
  RetroAchievements HTTP callers (`GetGameList`, `GetGame`, two
  `GetGameInfoAndUserProgress` variants, `GetUserSummary`) emit
  `logger.error` on 401 with the user-actionable hint to re-enter
  the API key in Settings → Scrapers. Tests:
  `tests/test_pass41_security.py::TestPass41_7A/B/C` (4 cases).

#### Pass 41.8 Achievements/trophies — `flask.g` shadow + achievement aggregation silent-drop

- **Targets**:
  - `routes/trophies.py:1075, 1119, 1125, 1131` — four `for g in ...`
    loops in `_run_psn_full_sync` shadow module-level `from flask
    import g`.  Latent bug (thread has no request context).
  - `routes/achievements.py:88-96` — `LEFT JOIN` with `AND
    gap.user_id = ?` silently filters out pre-migration null-user_id
    rows, hiding data without erroring.
- **Plan**: rename the four loop vars to `ps_game` (mirrors the
  `existing_groups` comprehension at :1384).  Either back-fill
  `user_id` in migration 009 for the admin user (similar to the PSN
  tokens case) or document the silent-drop behavior and surface a
  warning in the aggregated view.
- **Source**: 2026-04-24 indie-review, achievements/trophies H1/H2.
- **Status**: done (v3.5.7) — A: every `for g in ...` shadow in
  `routes/trophies.py` renamed (`ps_game` for PSN background sync
  loops mirroring the existing comprehension; `tg` for trophy_groups
  comprehensions; `game` for the per-request game-search loop).
  B: comment block in `routes/achievements.py` documents the
  `gap.user_id NOT NULL` invariant + the diagnostic query
  (`SELECT COUNT(*) FROM game_achievement_progress WHERE user_id IS NULL`)
  for operators hitting "too empty" aggregations after a pre-009
  backup restore. Tests:
  `tests/test_pass41_security.py::TestPass41_8A/B` (2 cases).

#### Pass 41.9 Game routes — track-view / completion / recently-viewed / sort_title

- **Targets**:
  - `routes/games.py:1086, 1106` — `@editor_required` on
    `api_track_view` + `api_update_completion`; viewers can't mark
    their own games complete.  Separately, `last_viewed` is a global
    column on `games` — cross-user leak of viewing history.
  - `routes/games.py:1117-1142` — `/api/recently-viewed` has zero
    callers (dashboard uses inline `query()` in `app.py:994`).
  - `services/game_utils.py:1275-1288` — `generate_sort_title`
    converts single-letter Roman numerals at word-start: "I am
    Setsuna" → "01 am Setsuna".
- **Plan**: (1) downgrade the two decorators to `@login_required`,
  and introduce a per-user `user_game_views` table so `last_viewed`
  isn't shared.  (2) delete `/api/recently-viewed`.  (3) tighten the
  Roman-numeral heuristic: only convert when followed by digit, end-
  of-string, or adjacent to another numeral token.
- **Source**: 2026-04-24 indie-review, game routes H1/H2/H3.
- **Status**: done (v3.5.13) — A: `api_track_view` and
  `api_update_completion` dropped from `@editor_required` to
  `@login_required` + `@permission_required('track_progress')` so
  Player and Editor roles can self-track. B: new `user_game_views`
  table (migration 010) keyed on `(user_id, game_id)`; track-view now
  upserts via `INSERT … ON CONFLICT DO UPDATE`; dashboard recently-
  viewed + continue-playing panels JOIN per-user. `/api/recently-viewed`
  endpoint deleted (zero callers). C: `generate_sort_title` single-
  letter Roman pattern narrowed to `(?<![-\w])R(?=\s*$|\s*[:(\[]|\s+\d)`;
  pronoun "I" no longer converts but EOS / subtitle / numeric-adjacent
  cases still do. Tests:
  `tests/test_pass41_security.py::TestPass41_9A/B/C` (11 cases). NOTE
  for merger of PR #3 (feat/multi-emulator-launch): that branch
  carries migration 010_emulators.py; rebase will need to renumber
  it to 011_emulators.py.

#### Pass 41.10 Settings/maintenance/tools — every destructive endpoint at `@login_required` + task-cancel authz + scan unboundedness

- **Targets**:
  - `routes/tools.py` — 10+ endpoints at `@login_required` that
    mutate filesystem / launch subprocesses; `api_archive_scanner_scan`,
    `api_duplicate_finder_scan`, `api_screenshot_dedup_scan`,
    `api_chd_converter_scan`, `api_chd_verify_scan` all walk the ROM
    tree with no rate limit.
  - `routes/tools.py:298-351` — `api_rom_tools_task_cancel/pause/
    resume` are `@login_required`-only; any logged-in user can cancel
    any admin task.
- **Plan**: raise every destructive `api_*_convert`/`_verify_verify`
  to `@admin_required`; raise every heavy-filesystem `*_scan` to
  `@editor_required` + `_rate_limit('...', '5 per minute')` in
  `app.py`.  Task cancel/pause/resume endpoints also need
  `@admin_required`.  Full UUIDs for task IDs (currently 8-char
  slice → 32 bits, guessable across logged-in users).
- **Source**: 2026-04-24 indie-review, settings/maintenance/tools
  H1/H2/H3.
- **Status**: done (v3.5.10) — A: task cancel/pause/resume in
  `routes/tools.py:328/344/364` raised to `@admin_required`. B: CHD
  `convert` (line 626) and `verify` (line 797) raised to
  `@admin_required`. C: 4 `task_id = str(uuid.uuid4())[:8]` sites now
  use full UUID-4 strings (no slice). D: 5 scan endpoints
  (`archive_scanner_scan`, `chd_converter_scan`, `chd_verify_scan`,
  `duplicate_finder_scan`, `screenshot_dedup_scan`) raised to
  `@editor_required` and registered with `5 per minute` Flask-Limiter
  caps in `app.py`. Tests:
  `tests/test_pass41_security.py::TestPass41_10A/B/C/D` (13 cases).

#### Pass 41.11 Museum — silent JSON decode failure + GET-handler DB mutation

- **Targets**:
  - `routes/museum.py:192` — `_get_top_games` catches
    `(json.JSONDecodeError, TypeError): pass`; admin sees a page
    with no top-games and no indicator that cached LLM output is
    corrupt.
  - `routes/museum.py:347-351` — stale-controller-image cleanup runs
    inside a GET handler (`UPDATE controllers SET image = NULL`);
    violates RFC 7231 GET-idempotency and allows one user's page load
    to mutate globally-shared state.
- **Plan**: (1) log the JSON decode failure at `warning` so the next
  museum generation can be prompted.  (2) move the stale-image
  cleanup to a background sweep or an `@editor_required` POST.
- **Source**: 2026-04-24 indie-review, museum H1/H2.
- **Status**: done (v3.5.8) — A: `_get_top_games` JSON decode failure
  now logged at `logger.warning` (was silent `pass`). B: `museum_system`
  GET handler clears stale controller-image refs in-memory only;
  persistent cleanup moved to new admin POST
  `/api/museum/cleanup-controller-images` (`@editor_required`).
  Tests: `tests/test_pass41_security.py::TestPass41_11A/B` (4 cases).

#### Pass 41.12 Frontend JS — fetch timeout + navigateTo open-redirect + inline-onclick JSON

- **Targets**:
  - `static/js/utils.js:264-329` — `API.get/post/postForm` use `fetch()`
    without `AbortController`, no default timeout, no `signal` param.
  - `static/js/toast-controller.js:1171, 1586-1592` — `navigateTo`
    writes raw `returnUrl` from localStorage to `window.location.href`
    with no scheme check; `data.return_url` also interpolated into an
    inline `onclick=` JS-string.
  - 51 raw `setInterval`/`setTimeout`/`addEventListener` sites across
    the JS tree; 0 callers of `PageLifecycle.*` — the abstraction is
    a documented zombie.
- **Plan**: (1) thread `options.signal` through `API.*`; default
  timeout 30s via `AbortController`.  (2) in `navigateTo`, reject
  URLs not matching `startsWith('/')` or `new URL(..., location).
  protocol ∈ {http:, https:}`.  Replace inline `onclick` with
  delegated `addEventListener` + `data-*` attrs.  (3) either adopt
  `PageLifecycle` in the canonical hot paths (museum, rom-tools,
  log-viewer) or delete the abstraction — pick one.
- **Source**: 2026-04-24 indie-review, frontend JS H1/H2/H3/M3.
- **Status**: done (A/B v3.5.11; M3 v3.5.18) — A (HIGH) + B (HIGH) closed:
  `_withTimeout(opts)` wraps every `API.get/post/postForm` call in a
  30 s default `AbortController`; caller-supplied `signal` opts out.
  `_isSafeReturnUrl(url)` validates `navigateTo` redirect targets to
  same-origin paths or origins. M3 (inline-onclick → delegated listener
  rewrite) un-gated as of Pass 42.7 (v3.5.46) — PageLifecycle was
  removed, so the listener-cleanup question is moot; M3 can be done
  now with plain `addEventListener` and no centralized tracking.
  Closed (2026-06-10): M3 landed in Pass 45.4 (done v3.5.18, which
  strictly subsumed it) — the inline `onclick` toast actions
  (navigate / pause / cancel) were replaced with a single delegated
  container click handler keyed off `data-toast-action` /
  `data-toast-return-url`; no inline `onclick` remains in
  `toast-controller.js` (comments only) and `core.bundle.js` carries
  the delegated handler. Tests:
  `tests/test_pass41_security.py::TestPass41_12A/B` (5 cases) +
  `tests/test_pass45_security.py::TestPass45_4*`.

#### Pass 41.13 Templates / a11y — aria-current + div-as-button + mis-targeted label-for + label-as-group-heading

- **Targets**:
  - `templates/base.html:83-189` — no `aria-current="page"` on sidebar
    nav links.
  - `templates/base.html:194`, `rom_tools_hub.html:201/214/227`,
    `game_detail.html:659`, `duplicate_finder.html:460`,
    `screenshot_dedup.html:481`, `game_imports.html:191` — `<div
    onclick=>` / `<h2 onclick=>` primary actions fail WCAG 2.1.1
    (keyboard).
  - `templates/base.html:1154-1162` — gem-modal platform toggle:
    `<label class="toggle-switch" for="gemOtherPlatforms">` wraps
    checkbox `gemExclusiveToggle` but `for=` points at the sibling
    text input.  Functional bug, not just a11y — clicking the toggle
    focuses the text input instead of toggling the checkbox.
  - wishlist.html / lists.html / tags.html / logs.html / chd_converter
    .html / rom_tools_settings.html / duplicate_finder.html /
    _modals/rename_modal.html — `<label>` used as group heading above
    button groups (no form control to associate with).
- **Plan**: (1) Jinja one-liner `{% if request.endpoint == '...' %}
  aria-current="page"{% endif %}` on every sidebar nav link.  (2)
  convert the 6 `<div onclick=>` primary actions to `<button>`.  (3)
  drop the `for=` on the wrapping toggle label (implicit association
  via wrapped input is correct).  (4) replace bare `<label>` over
  button groups with `<fieldset><legend>` or `<div role="group"
  aria-labelledby="...">` + heading.
- **Source**: 2026-04-24 indie-review, templates H1/H2/H3/H4.
- **Status**: done (A/B v3.5.12; C/D v3.5.51) — A (HIGH aria-current) + B (HIGH
  wrapping-label toggle) closed: new Jinja
  macro `nav_active(cond)` emits `class="nav-item active"` +
  `aria-current="page"` together; all 17 sidebar nav links converted.
  gem-modal exclusive toggle's wrapping label dropped the misleading
  `for="gemOtherPlatforms"` (was focusing the sibling text input —
  functional keyboard-focus bug, HIGH, not MEDIUM);
  implicit association via wrapping is correct. C (HIGH div-as-button)
  and D (MEDIUM label-as-heading) deferred to Pass 41.13.C carry-over —
  needs browser verification across 8+ template files. Tests:
  `tests/test_pass41_security.py::TestPass41_13A/B` (3 cases).
  Closed (2026-06-10): C/D carry-over landed in Pass 41.13.C
  (done v3.5.51) — 6 scoped div/h2-`onclick` primary actions converted
  to native `<button>`/disclosure patterns, 8 label-as-group-heading
  shapes promoted to `role="group"` + `aria-labelledby`; verified by
  `TestPass41_13cDivAsButton` + `TestPass41_13cLabelAsGroupHeading`.
  Parent now fully resolved.

#### Pass 41.13.C Templates a11y carry-over (div-as-button + label-as-heading)

- **Target**: 6 `<div onclick=>` / `<h2 onclick=>` primary actions in
  `base.html`, `rom_tools_hub.html`, `game_detail.html`,
  `duplicate_finder.html`, `screenshot_dedup.html`, `game_imports.html`.
  Plus `<label>`-as-group-heading shapes in `wishlist.html`,
  `lists.html`, `tags.html`, `logs.html`, `chd_converter.html`,
  `rom_tools_settings.html`, `duplicate_finder.html`,
  `_modals/rename_modal.html`.
- **Why**: WCAG 2.1.1 (keyboard) — `<div onclick=>` is not focusable
  and not Enter/Space-activatable. WCAG 1.3.1 / 4.1.2 — `<label>` over
  a button group has no form control to associate with; should be
  `<fieldset><legend>` or `<div role="group" aria-labelledby="...">`.
- **Plan**: convert each `<div onclick=>` to `<button>` (preserves
  click handlers, gains keyboard activation). Replace bare `<label>`
  group headings with `<fieldset><legend>`. Browser-verify each page
  on desktop + mobile (~375px) to confirm visual layout intact.
- **Status**: done (v3.5.51) — six div-as-button primary actions
  converted to native `<button>` (rom_tools_hub × 3 tool cards,
  base.html version-info + folder-item rows × 2, game_imports CLZ
  upload area as `<label for=>`). Three disclosure patterns
  restructured per WAI-ARIA APG accordion (game_detail scrape-
  history, duplicate_finder group, screenshot_dedup game) — each
  uses `<hN>` wrapping `<button aria-expanded aria-controls>` with
  the toggle JS flipping aria-expanded. Eight bare-label group
  headings promoted to `<div class="form-label" id="...">` (or
  styled span) with `role="group" aria-labelledby="..."` on the
  wrapping button-group container; chose the div+aria-labelledby
  pattern over `<fieldset><legend>` because legend's default styling
  is harder to override consistently and the wrapper containers
  already exist. Five CSS rules gained the button-as-styled-element
  reset (background:transparent; border:none; font:inherit;
  text-align:left; width:100%; appearance:none). 15 regression
  tests in `TestPass41_13cDivAsButton` (7) + `TestPass41_13c
  LabelAsGroupHeading` (8); suite 710 → 725.

#### Pass 41.14 Image/media — Pillow bomb-error not caught + ESRGAN SSRF gap + `rglob` follows symlinks

- **Targets**:
  - `scraper/image_dedup.py:24-45` — `except (OSError, ValueError)`
    misses `PIL.Image.DecompressionBombError`; one bomb-image aborts
    the scrape for that game.
  - `services/image_utils.py:67-107` — `_download_model` calls
    `urllib.request.urlopen` directly, bypassing `services.ssrf`.
    `_MODEL_URLS` is hardcoded today; if the URL becomes settings-
    editable (as happened in Pass 32.1 for `ROM_PATH`), this becomes
    a real SSRF primitive.
  - `scraper/rom_tools.py:260-272, 1044-1064, 1212-1225, 1408-1423` —
    `Path.rglob()` follows symlinks on Python 3.12 (default changed
    in 3.13); a symlink to `/` inside ROM_PATH enumerates the entire
    filesystem.
- **Plan**: widen the `compute_dhash` exception catch to `Exception`
  or add `DecompressionBombError` explicitly.  Route ESRGAN model
  download through `services.ssrf.validate_outbound_url`.  In every
  rglob loop, check `archive_path.is_symlink() and resolved-path-
  under-root` before traversal.
- **Source**: 2026-04-24 indie-review, image/media #8/#9/#10.
- **Status**: done (v3.5.9) — A: `compute_dhash` except clause widened
  to include `Image.DecompressionBombError` (sibling of OSError/ValueError;
  was leaking through and aborting whole-game dedup loops). B: ESRGAN
  `_download_model` runs every URL through
  `services.ssrf.validate_outbound_url(require_https=True)` before
  `urlopen`; defensive against future code paths that surface the URL via
  settings. C: new `_safe_under_root(path, root_resolved)` helper guards
  four `Path.rglob()` walks (archive scanner ×2, CHD converter, duplicate
  finder) against symlinks pointing outside ROM root. Tests:
  `tests/test_pass41_security.py::TestPass41_14A/B/C` (6 cases).

---

### CI/CD hardening round 2

> **Follows Pass 22.**  Action pinning, workflow permissions,
> `continue-on-error` discipline, lockfile hash verification,
> Dependabot lockfile regeneration.

#### Pass 39.1 Pin CI workflow actions to SHA (HIGH, S)

- **Target**: `.github/workflows/ci.yml:39, 41, 132` (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`).
- **Why**: release workflow pins every action by SHA + version
  comment (e.g. `release.yml:35, 39, 83, 106, 133`); CI uses floating
  tags.  Tags are mutable — a compromised maintainer account can
  rewrite a tag and CI runs on every PR, including forks via
  `pull_request`.  OWASP CICD-SEC-4 Poisoned Pipeline Execution.
- **Plan**: copy release-workflow pattern; add comment with version
  next to each SHA for Dependabot legibility.
- **Source**: 2026-04-24 audit, Tests/tooling/CI H1.
- **Status**: done (v3.5.40) — three SHA pins added: checkout v4.3.1
  (`34e114876b…`), setup-python v5.6.0 (`a26af69be9…`), upload-artifact
  v4.6.2 (`ea165f8d65…`). Trailing `# vX.Y.Z` comment kept for
  Dependabot legibility, mirrors release.yml convention.

#### Pass 39.2 Explicit `permissions:` block on CI (HIGH, S)

- **Target**: `.github/workflows/ci.yml`.
- **Why**: no workflow-level `permissions:` block; job inherits repo-
  default `GITHUB_TOKEN` scope, which for private/org repos can
  include `contents: write`.  OWASP CICD-SEC-2.
- **Plan**: add `permissions: { contents: read }` at workflow level;
  let individual steps narrow further if needed.
- **Source**: 2026-04-24 audit, Tests/tooling/CI H2.
- **Status**: done (v3.5.40) — workflow-level `permissions:
  contents: read` added in ci.yml, mirroring release.yml. CI never
  writes to the repo, so this is the tightest viable scope.

#### Pass 39.3 Hard-fail `pip-audit` + `semgrep` in CI (HIGH, S)

- **Target**: `.github/workflows/ci.yml:81, 86`.
- **Why**: both marked `continue-on-error: true` with TODO comments
  promising an eventual flip.  Security steps perpetually warn =
  observability, not enforcement.  Five consecutive 0-actionable
  audit runs means the suite is calibrated.
- **Plan**: remove `continue-on-error: true` on both; document the
  bar ("audit-triage must actionable=0 for main merge") in
  CONTRIBUTING.md.
- **Source**: 2026-04-24 audit, Tests/tooling/CI H3.
- **Status**: done (v3.5.40) — pip-audit `continue-on-error: true`
  flipped to hard-fail. Verified `pip-audit --strict` on the current
  lockfile reports zero known vulnerabilities; new CVE surfacing now
  blocks merge. Roadmap entry was stale on semgrep — already
  hard-fail since Pass 30 debt sweep. CONTRIBUTING.md note skipped
  (project has no CONTRIBUTING.md and the "audit-triage actionable=0"
  bar is documented in CLAUDE.md / audit_hygiene.md).

#### Pass 39.4 `requirements.lock` with `--generate-hashes` + `--require-hashes` install (MEDIUM, S)

- **Target**: `requirements.lock`; `install.py:192`, `install_gui.py:433`; regen command in CLAUDE.md.
- **Why**: lockfile has no hashes — installs don't fail-closed on
  MITM or PyPI compromise.  OWASP CICD-SEC-3 Dependency Chain Abuse.
  Pass 22 shipped signed *outputs* (cosign) without verifying
  *inputs*.
- **Plan**: `pip-compile requirements.txt -o requirements.lock
  --strip-extras --generate-hashes`; `pip install --require-hashes -r
  requirements.lock`.  Update CLAUDE.md regen instruction.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M4.
- **Status**: done (v3.5.49) — `requirements.lock` regenerated with
  `pip-compile --generate-hashes` (98 → 880 lines; one or more SHA256s
  per pinned package). `install.py` and `install_gui.py` now run
  `pip install --require-hashes -r requirements.lock` by default; both
  fall back to `requirements.txt` with a visible warning if the
  lockfile is absent (developer checkout pre-regeneration). CI's
  lockfile-drift recompile step adds `--generate-hashes` so the
  comparison stays apples-to-apples. CLAUDE.md regen instruction
  updated. Tests: `tests/test_pass39_supply_chain.py::TestPass39_4LockfileHashes`
  (4 cases — per-package hash count, lockfile-header recipe pin, both
  installers reference `--require-hashes` + lockfile path, CI workflow
  drift step uses `--generate-hashes`). Full pytest 707/707 green.

#### Pass 39.5 Dependabot regenerates `requirements.lock` (MEDIUM, S)

- **Target**: `.github/dependabot.yml:10-27`.
- **Why**: currently updates `requirements.txt` only.  Lockfile-drift
  check at `ci.yml:88-113` hard-fails every Dependabot PR until
  manual `pip-compile`.
- **Plan**: add a GitHub Actions post-update step (or a
  `@dependabot pre-task` directive) that runs `pip-compile`; ensure
  the resulting diff is committed to the same PR.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M5.
- **Status**: done (v3.5.50) — new workflow
  `.github/workflows/dependabot-lockfile.yml`. Triggers on
  `pull_request` events with `paths: requirements.txt`; guarded to
  `github.actor == 'dependabot[bot]'`. Checks out the PR branch, runs
  `pip-compile --strip-extras --generate-hashes` (matches the recipe
  pinned by Pass 39.4), and pushes the regenerated lockfile back to
  the Dependabot branch. Concurrency-keyed on PR number with
  `cancel-in-progress` so a Dependabot force-push cancels the in-flight
  regen. Permissions scoped to `contents: write` + `pull-requests:
  write`; default `GITHUB_TOKEN` (no PAT). The original CI run on the
  Dependabot PR picks up the new commit and goes green without human
  intervention. `dependabot.yml` itself unchanged — `@dependabot
  pre-task` doesn't exist; the auxiliary-workflow pattern is the
  established GitHub solution. Tests:
  `tests/test_pass39_supply_chain.py::TestPass39_5DependabotLockfileWorkflow`
  (3 cases — file exists, YAML shape pin (path filter, actor guard,
  contents:write permission), pip-compile invocation uses
  --generate-hashes). Full pytest 710/710 green.

#### Pass 39.6 `build_dist.py` env-configurable `STAGING_DIR` (MEDIUM, S)

- **Target**: `build_dist.py:22`; `release.yml:55-64`.
- **Why**: hardcoded absolute path under the maintainer-local staging tree
  (`/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB` at landing; was originally
  `/mnt/Emulators/...` pre-2026-05-08 hub move). Release workflow
  monkey-patches `build_dist.STAGING_DIR` inline — fragile; `main()` return is
  also `None`-masked.
- **Plan**: `STAGING_DIR = os.environ.get('RETRODB_STAGING_DIR',
  '/mnt/Storage/...')`; set `env: RETRODB_STAGING_DIR:` in the
  workflow.  Raise on `hasattr(build_dist, 'main') is False` rather
  than silently no-op.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M3.
- **Status**: done (v3.5.40) — `STAGING_DIR =
  os.environ.get('RETRODB_STAGING_DIR', …)` in build_dist.py;
  release.yml replaces the inline Python wrapper script with `env:
  RETRODB_STAGING_DIR: /tmp/staging` and a direct `python
  build_dist.py` call. The `hasattr(build_dist, 'main')` no-op-mask
  was an artifact of the wrapper script — gone with the wrapper.

#### Pass 39.7 Rate-limit `api_reports_multidisc_scan` (MEDIUM, S)

- **Target**: `routes/reports.py:376-378`; `app.py:232-236` limiter config.
- **Why**: `@login_required`-only POST that walks the filesystem;
  non-editor users can loop-hammer it.  Pass 25.9 scope.
- **Plan**: add a Flask-Limiter rule (or gate behind `@editor_required`
  since it's effectively a write-adjacent discovery).
- **Source**: 2026-04-24 audit, Maintenance/settings M3.
- **Status**: done (v3.5.40) — `_rate_limit('reports.api_reports_multidisc_scan',
  "5 per minute")` registered in app.py alongside the existing
  `tools.api_*_scan` block. Same family as Pass 41.10.D.

#### Pass 39.8 Audit-hygiene: gitleaks allowlist for `tests/test_log_redactor.py` (LOW, S)

- **Target**: `.gitleaks.toml`.
- **Why**: `/audit` run 2026-04-24 surfaced the synthetic-JWT test
  fixture at `tests/test_log_redactor.py:9` — intended to verify the
  redactor replaces JWTs.  Recurs on every audit.
- **Plan**: add `'''tests/test_log_redactor\.py$'''` to the existing
  `paths` array in `.gitleaks.toml` (narrow form — keep gitleaks
  active on other test files).
- **Source**: 2026-04-24 audit, /audit triage config-tightening.
- **Status**: done (v3.5.40) — path entry added to
  `.gitleaks.toml`'s admin-runtime-state allowlist.

#### Pass 39.9 Audit-hygiene: `usedforsecurity=False` kwarg on non-security MD5/SHA1 (LOW, S)

- **Target**: `routes/games.py:236` (ETag fingerprint),
  `routes/tools.py:1071` (user-requested file hash),
  `scraper/retroachievements.py:95` (RA API contract),
  `scraper/scrape_screenscraper.py:205-206` (MD5 + SHA1 for ScreenScraper).
- **Why**: bandit B324 recurs on five sites every audit; none is a
  security primitive (remote-API contract hashes + ETag fingerprint +
  user-selected hash method).  `hashlib.md5(usedforsecurity=False)`
  is supported on Python 3.9+, documents intent inline (six-month
  test), and silences the rule permanently — cheaper than adding a
  per-site `# nosec` comment.
- **Plan**: add the `usedforsecurity=False` kwarg to each of the five
  constructors.  Run `bandit -ll scraper/ routes/` after — B324 count
  should drop to 0.
- **Source**: 2026-04-24 audit (5th), /audit triage config-tightening.
- **Status**: done (v3.5.40) — kwarg added to all five constructors:
  `routes/games.py:241` (ETag MD5), `routes/tools.py:1208`
  (user-selected file MD5; line drift from roadmap entry's stale
  `:1071`), `scraper/retroachievements.py:95` (RA hash MD5),
  `scraper/scrape_screenscraper.py:205-206` (MD5 + SHA1).
  `bandit -ll` on the four files now reports zero B324.

#### Pass 39.10 Audit-hygiene: gitleaks regex allowlist for Claude model literal (LOW, S)

- **Target**: `.gitleaks.toml`; re-firing at `templates/settings.html:1265`.
- **Why**: the existing `claude-(opus|sonnet|haiku)-\d[-\w]*` regex
  allowlist isn't suppressing the `generic-api-key` hit on the
  `<option value="claude-haiku-4-5-20251001">` literal.  Likely
  cause: gitleaks `generic-api-key` extracts the surrounding
  high-entropy context (HTML attribute) as the secret, so the
  allowlist regex (which only covers the model name substring)
  doesn't match the full captured string.
- **Plan**: add `'''templates/settings\.html$'''` to the `paths`
  allowlist array — narrow (only this file, which is project-
  controlled Jinja markup, not user content).  Cheaper than hunting
  the gitleaks regex semantics.
- **Source**: 2026-04-24 audit (5th), /audit triage config-tightening.
- **Status**: done (v3.5.40) — path entry added to `.gitleaks.toml`
  alongside the test_log_redactor entry from 39.8.

#### Pass 39.11 Re-pin CI actions when upstream releases Node 24 builds (LOW, S)

- **Target**: `.github/workflows/ci.yml:39, 41, 132` —
  `actions/checkout@34e114876b… (v4.3.1)`,
  `actions/setup-python@a26af69be9… (v5.6.0)`,
  `actions/upload-artifact@ea165f8d65… (v4.6.2)`. Same SHA pins live in
  `.github/workflows/release.yml`.
- **Why**: the v3.5.52 push (CI run 25247530694) surfaced two
  `Node.js 20 is deprecated` annotations against these three actions.
  GitHub force-upgrades the runner to Node 24 today (so CI still
  passes), but the long-term fix is a re-pin to a release that
  natively targets Node 24 in its `action.yml`. The current pins are
  the right ones for *now* per Pass 39.1's SHA-pinning contract — the
  re-pin only happens when `actions/checkout`, `actions/setup-python`,
  and `actions/upload-artifact` ship a new SemVer with a
  `using: 'node24'` runtime.
- **Plan**: when each upstream action releases a Node-24-native build,
  bump the SHA + trailing `# vX.Y.Z` comment and let Dependabot's
  github-actions ecosystem regenerate the lockstep. No code change
  needed in RetroDB itself; the action versions are the only edits.
- **Source**: GitHub deprecation notice
  <https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/>;
  surfaced post-push 2026-05-02.
- **Status**: done (2026-05-02) — closed by merging Dependabot PR #1
  (squash commit `ddd894c`), which the Dependabot github-actions
  ecosystem had already opened against these three pins on
  2026-04-23 (and refreshed against current main on the v3.5.52
  push). Bumps re-pinned to: `actions/checkout` v4.3.1 → v6.0.2 (SHA
  `de0fac2e…`), `actions/setup-python` v5.6.0 → v6.2.0 (SHA
  `a309ff8b…`), `actions/upload-artifact` v4.6.2 → v7.0.1 (SHA
  `043fb46d…`). All three majors target Node 24 natively in their
  `action.yml`. Pre-merge CI on the PR branch was green on both
  Python 3.12 and 3.13. The same SHAs apply across `ci.yml`,
  `dependabot-lockfile.yml`, and `release.yml`.

#### Pass 39.12 Create the labels referenced by `.github/dependabot.yml` (LOW, S)

- **Target**: GitHub repo labels (`gh label list`) vs.
  `.github/dependabot.yml:25-27, 42-44`.
- **Why**: `dependabot.yml` declares `labels: ["dependencies",
  "python"]` (pip group) and `["dependencies", "github-actions"]`
  (github-actions group). None of those labels existed on the repo,
  so Dependabot logged `The following labels could not be found:
  dependencies, python` on every PR open and applied no labels.
  Cosmetic but breaks PR triage filters (`is:open label:dependencies`
  returns nothing).
- **Plan**: `gh label create` for the three missing names with sane
  colors (#0366d6 / #3572A5 / #2088FF mirroring GitHub's pip / Python
  / Actions iconography); retro-apply to any open Dependabot PR.
- **Source**: surfaced post-PR-#1 merge 2026-05-02 by Dependabot's
  comment thread on PR #2.
- **Status**: done (2026-05-02) — three labels created via `gh label
  create`: `dependencies` (#0366d6, "Pull requests that update a
  dependency file"), `python` (#3572A5, "Python (pip) dependency
  updates"), `github-actions` (#2088FF, "GitHub Actions workflow
  updates"). Retro-applied to PR #2 via `gh pr edit --add-label
  dependencies --add-label python` before merge. Future Dependabot
  PRs auto-label correctly.

---

### Refactoring & consolidation

> **Pass 38** — Rule-of-Three triggered on five areas surfaced by the
> 2026-04-24 sweep.  **Pass 42** — MEDIUM/LOW cross-cutting items
> from the indie-review that aren't urgent but should be scheduled
> before the next indie-review — opportunistically mergeable into
> feature PRs that touch adjacent code.

#### Pass 38.1 Split `apply_hybrid_metadata` (HIGH, L)

- **Target**: `scraper/hybrid_scraper.py:495-1516` (1,022-line function).
- **Why**: untestable in isolation, hard to audit.  The fallback loop
  (807-1112), normalize block (1222-1266), save block (1268-1464), RA
  check (1469-1498) are each independent operations with clean inputs.
- **Plan**: carve `_run_fallbacks`, `_normalize_metadata`,
  `_save_game_row`, `_check_ra_matches` into separate helpers.
  Sibling mergers already extracted to `scraper/metadata_merger.py`.
- **Source**: 2026-04-24 audit, Scraper orchestration M2.
- **Status**: done (v3.6.37) — all four sub-blocks named in the Plan now extracted across v3.5.60–v3.6.37:
    - **RA-check (v3.5.60)**: `scraper.hybrid_scraper._apply_retroachievements_check(db_game_id, title, system_folder) -> bool`. Smallest + most self-contained of the four sub-blocks (31 lines, opens its own DB connection, mutates only RA columns, silently swallows exceptions). Callsite collapsed to 3 lines.
    - **Region-normalize (v3.5.62)**: `scraper.hybrid_scraper._normalize_region(metadata, result)`. Folded the two inline `settings_manager.load_settings()` branches (multi-value reduction + empty-region fallback) into a single helper that loads settings once. Callsite collapsed from 25 lines to 1 line.
    - **Scrape-history (v3.5.64)**: `scraper.hybrid_scraper._build_scrape_history_json(c, db_game_id, primary_source, metadata, result, force_overwrite) -> str`. Reads `games.scrape_history` JSON, appends a new entry summarising the current scrape, returns serialised JSON ready for the save UPDATE. Takes the caller's cursor so the read stays inside the outer transaction's lifetime. Callsite collapsed from 28 lines to 4 lines; the function-local `import json` + `from datetime import datetime` moved into the helper.
    - **Ratings-normalize (v3.5.65)**: `scraper.hybrid_scraper._normalize_ratings(metadata, result)`. Combined ESRB-letter-normalize + cross-map-empties + content-based-inference into one helper. Callsite collapsed from 26 lines to 1 line.
    - **Run-fallbacks (v3.6.37)**: `scraper.hybrid_scraper._run_fallbacks(metadata, result, sources_data, game, db_game_id, primary_source, system_folder, secondary_sources, restrict_to_selected, force_overwrite, c)`. The ~300-line FILL GAPS FROM SECONDARY SOURCES loop (priority build + per-scraper search/apply across ES-DE/TGDB/IGDB/RAWG/ScreenScraper/AI, each isolated in try/except). `force_overwrite` had to be threaded into the signature — the ES-DE fallback branch used it; a latent NameError caught by ruff before commit. Callsite collapsed to one guarded call under `if fill_gaps:`.
    - **Save-game-row (v3.6.37)**: `scraper.hybrid_scraper._save_game_row(c, metadata, scrape_history_json, db_game_id)`. The COALESCE fill-only save UPDATE (~50 columns) plus the `_boxart_source` pop + alternate_titles JSON-encode. Caller still owns the commit. Callsite collapsed from ~110 lines to 1.
    - **Players/sort-title-normalize (v3.6.37)**: `scraper.hybrid_scraper._normalize_players_and_sort_title(metadata)`. Pre-save players range→max reduction + sort_title regen. Callsite collapsed from 11 lines to 1.
  Tests: `tests/test_pass38_ra_check_helper.py` (4) +
  `tests/test_pass38_region_helper.py` (6) +
  `tests/test_pass38_scrape_history_helper.py` (5) +
  `tests/test_pass38_normalize_ratings_helper.py` (6) +
  `tests/test_pass38_players_sort_helper.py` (9) +
  `tests/test_pass38_save_game_row_helper.py` (4) +
  `tests/test_pass38_run_fallbacks_helper.py` (2). `apply_hybrid_metadata`
  is down from ~924 to ~510 lines; suite green aside from the 6
  pre-existing `test_pass48_media_cleanup` order-pollution failures.
  Residual (out of original Plan scope): the PRIMARY SOURCE fetch
  if/elif (~200 lines) and the pre-populate + media-validation block
  (~120 lines) remain inline — a future pass could carve these to push
  the function below ~300 lines.

#### Pass 38.2 Consolidate `load_scraper_settings` (MEDIUM, S)

- **Target**: `scraper/scraper_manager.py:63-106` vs `scraper/metadata_merger.py:72-86`.
- **Why**: duplicated with divergent miss-behavior; the manager's
  returns a fully-defaulted dict, the merger's returns
  `{'api_keys': {}, 'enabled': {}, 'priority': []}`.  Upstream `enabled`
  lookups silently disagree.
- **Plan**: keep one loader; re-export from the other.  Pick the
  manager's behavior (defaults from `config.py`) as canonical.
- **Source**: 2026-04-24 audit, Scraper orchestration M1.
- **Status**: done (v3.5.42) — `scraper/metadata_merger.py`'s duplicate
  loader deleted; the module now re-exports `load_scraper_settings`
  from `scraper/scraper_manager.py` (the canonical, defaults-from-
  config + 30 s cache version). Both
  `from scraper.metadata_merger import load_scraper_settings` and
  `from scraper.scraper_manager import load_scraper_settings` now
  resolve to the same callable — `enabled` lookups via the merger no
  longer disagree with the manager's view. All 3 caller sites
  unchanged. 694/694 tests pass.

#### Pass 38.3 Extract `installer_core.py` (MEDIUM, M)

- **Target**: `install.py`, `install_gui.py` share ~90% of logic
  (distro detection, `_run_pip`, `_check_module`, `_build_script`,
  config-copy list, directory list).
- **Why**: CLAUDE.md rule-of-three; bundle-name drift (`app.bundle.js`
  zombie, Pass 38.5) already demonstrated silent drift.
- **Plan**: `installer_core.py` with `detect_distro`, `pip_install`,
  `check_module`, `run_build_script`, `CONFIG_COPIES`, `DIRECTORIES`,
  `do_install_step_*`; both frontends call into it.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M2.
- **Status**: done (v3.5.56) — new `installer_core.py` (188 lines)
  exposes `CONFIG_COPIES` (3-tuple), `DIRECTORIES` (14-tuple),
  `CORE_MODULES` (4-tuple), `MIN_PYTHON` (3.8), `detect_distro()` /
  `distro_label()` / `pip_install_hint()`, `pip_install(quiet=)`,
  `check_module()`, `run_build_script() -> (ok_or_None, output)`,
  `select_pip_args() -> (args, source)` (canonicalised Pass 39.4
  lockfile selection), `python_version_ok()`. `install.py`
  shrunk 360→247 lines (−31%); `install_gui.py` 668→593 (−11%).
  GUI pip wrapper kept as a one-line `quiet=True` shim. Linux
  distros outside fedora/debian/arch now surface as "Linux" in
  both installers (was "unknown" in CLI, "Linux" in GUI — GUI
  wins). `tests/test_pass39_supply_chain.py::
  test_installers_use_require_hashes` rewritten as a Pass-45.18-
  style functional pin: calls `installer_core.select_pip_args`
  against the real lockfile + asserts both installers import the
  shared module. 746/746 green.

#### Pass 38.4 Extract Jinja macros (MEDIUM, M)

- **Target**: zero `{% macro %}` across 45 templates; duplicated
  rating `<select>` (8 sub-systems × ~90 lines × 2+ files), filter
  modal (3 copies), breadcrumb (2+), sticky-subnav (6× in
  `settings.html`).
- **Why**: Pass 10 target; rule-of-three crossed on all four.
- **Plan**: `_macros/ratings.html`, `_macros/breadcrumb.html`,
  `_macros/sticky_subnav.html`, `_macros/filter_modal.html`.  Closes
  Pass 10 substantively.
- **Source**: 2026-04-24 audit, Templates & CSS M2.
- **Status**: done (v3.6.16) — three of the four target shapes carved
  out; ratings-select left as a future follow-up because re-scan found
  the rule-of-three not yet crossed (full 8-system block exists only in
  `_modals/edit_modal.html`; `_bulk_edit_modal.html` has a different
  shape with `data-field=` hooks). Three extractions landed:
    - **`_macros/breadcrumb.html`** with macro `breadcrumb(items)`.
      `items` is a list of `(label, url)` tuples; `url=None` renders
      as `.breadcrumb-current`. Standardised on `›` separators and
      `aria-label="Breadcrumb"`. **11 templates converted**:
      `achievement_game`, `achievements_system`, `game_detail`
      (conditional `?from=...` branches lifted into a single `_trail`
      set), `list_detail`, `local_trophy_detail`, `psn_trophy_detail`,
      `steam_achievement_game`, `steam_achievements`, `system_games`,
      `xbox_achievement_game`, `xbox_achievements`. Page-scoped
      `.breadcrumb-link` / `.breadcrumb-current` CSS in
      `list_detail.html` removed as orphaned by the conversion (the
      global `.breadcrumb a` selector in `core/typography.css` already
      covers the styling — original page-local rules were a redundant
      copy with cosmetic divergences).
    - **`_macros/sticky_subnav.html`** with `tab_subnav(tab_id)` (a
      `{% call %}`-shaped wrapper macro) and `subnav_link(href, label,
      active=False)`. All **6 subnav blocks in `settings.html`**
      (account / library / scraping / data / customization / system)
      converted; admin-conditional links and the system-tab's
      "active depends on role" branch preserved via a boolean arg.
    - **`_modals/select_filter_modal.html`** — the `<div
      id="filterModal" class="filter-modal">` Select-Filter dialog used
      by `all_games.html` and `system_games.html` extracted as a single
      `{% include %}` partial. Distinct from the existing
      `_modals/filter_modal.html` (game-detail similar-games filter);
      header comment documents the boundary so a future patch doesn't
      collapse them.
  Tests: `tests/test_pass38_template_macros.py` (24 cases — functional
  pins on the macro output plus source-grep regressions that the
  inline HTML shapes can't drift back in). Pass 45.16's
  `test_settings_subnavs_all_marked` rewritten as a Pass-45.18-style
  functional pin (renders the macro, asserts the StickyScroll
  attributes; the settings.html check now counts `{% call tab_subnav(`
  call sites instead of raw HTML). Suite 1015 → 1039 (+24). Pass 10
  closed substantively — `templates/_macros/` now exists with three
  members.

#### Pass 38.5 Delete `app.bundle.js` references in installers (MEDIUM, S)

- **Target**: `install.py:299`, `install_gui.py:569, 572`.
- **Why**: `build_js.py:277-279` deletes `app.bundle.js` as a legacy
  artifact since the split into `core.bundle.js` + `games.bundle.js`.
  Installers still check for the old filename — "use existing bundle"
  branch never fires correctly on a failed build.  Zombie code.
- **Plan**: replace with checks for `core.bundle.js` + `games.bundle.js`.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M1.
- **Status**: done (v3.5.41) — both `install.py` and `install_gui.py`
  now check `core.bundle.js` AND `games.bundle.js` for the
  build-failed fallback ("use existing bundles" branch). Success-path
  log message updated to name both bundles. v3.5.55 follow-up
  swept the last three stale `app.bundle.js` references in
  `build_js.py` (header docstring + `JS_ORDER` comment) and
  `docs/README.md` (ASCII tree).

#### Pass 38.6 Split `settings.html` by tab (LOW, M)

- **Target**: `templates/settings.html` (7,333 lines).
- **Why**: CSP / a11y / i18n sweeps all bottleneck on this file.
- **Plan**: split into `_partials/settings_{account,library,
  scraping,data,customization,system}.html`; `{% include %}` from a
  thin shell; preserve anchor IDs for sticky nav.
- **Source**: 2026-04-24 audit, Templates & CSS M3.
- **Status**: done (v3.6.17) — six panels extracted into
  `templates/_settings_tabs/{account,library,scraping,data,
  customization,system}.html` (named per the project's existing
  `_macros/` / `_modals/` convention rather than the plan's
  `_partials/settings_*` placeholder). Shell `templates/settings.html`
  dropped 7,368 → 5,201 lines; each tab swapped to a single
  `{% include "_settings_tabs/<tab>.html" %}` line, comment markers
  preserved. Per-partial line counts: account 362, library 277,
  scraping 599, data 210, customization 313, system 412. Each partial
  re-imports `tab_subnav` / `subnav_link` from
  `_macros/sticky_subnav.html` for standalone-render safety.
  Anchors verified: all 19 `subnav_link('X')` targets (profile /
  timezone / users / library / display / rom-naming / backup / esde /
  scraper / apikeys / stats / trophies / dropdowns / normalization /
  notifications / controllers / logos / maintenance / server /
  logging / troubleshooting) still resolve to their `id="X"` sections.
  End-to-end Flask test-client GET `/settings` returns 200 with all 6
  panels and every anchor present (431 KB rendered output, parity
  with pre-split). Regression file
  `tests/test_pass38_settings_tabs.py` (45 cases) pins partial
  existence, opening-div shape, end-marker, macro re-import,
  shell-is-thin (line-count ceiling and absence of inline
  `settings-tab-panel` blocks), functional Jinja render via a
  permissive `_SilentUndefined` stand-in (no Flask context needed),
  per-partial anchor preservation, and a union-count check that all 6
  `tab_subnav(...)` calls are still present. New helper
  `tests._util.read_settings_with_partials()` returns
  `settings.html` ∪ every `_settings_tabs/*.html` so source-grep tests
  that used to grep `settings.html` keep tracking the rendered page
  after the split. Three pre-existing tests widened to use it:
  `test_pass37_a11y.py::test_37_6_settings_result_containers_have_
  live_regions` (aria-live result containers now in
  `scraping.html` partial), `test_pass45_security.py::test_settings_
  subnavs_all_marked` (six `{% call tab_subnav %}` invocations now
  one per partial), `test_pass45_security.py::test_settings_modals_
  marked` (userModal now in `account.html` partial,
  editControllerModal now in `customization.html` partial,
  confirmModal still in the shell). Suite 1,039 → 1,084 (+45) green.

#### Pass 38.7 Consolidate duplicate platform-sync endpoints (MEDIUM, S)

- **Target**: `routes/platform_import.py:298-361` vs `routes/steam_achievements.py:95-158` (`api_steam_sync_single` × 2); similarly Xbox single-sync in `xbox_achievements.py:110-175`.
- **Why**: two copies of near-identical UPSERT SQL; one uses
  `sqlite3.connect(config.DB_PATH)` directly, bypassing `get_db()`.
- **Plan**: extract `_upsert_steam_progress(game_id, result)` +
  `_upsert_xbox_progress(…)` helpers in
  `services/jobs/platform_sync.py`; collapse the routes.
- **Source**: 2026-04-24 audit, Platform imports M1/M2.
- **Status**: done (v3.5.44) — `_upsert_steam_progress` and
  `_upsert_xbox_progress` helpers added to
  `services/jobs/platform_sync.py`; bulk-sync job + active routes
  (`steam_achievements.py`, `xbox_achievements.py`) all call them.
  Both routes switched from `sqlite3.connect(config.DB_PATH)` to
  `get_db()` (fixes missing PRAGMAs: busy_timeout, foreign_keys,
  synchronous, cache_size, temp_store, mmap_size). Dead duplicate
  `/api/steam/sync-achievements/<id>` route removed from
  `routes/platform_import.py` (zero callers across .py/.js/.html);
  active route at `/api/steam-achievements/sync/<id>` retained
  (called from `templates/steam_achievement_game.html:288`). Xbox
  had no equivalent dead duplicate — only one single-sync route.
  Orphan imports (datetime/timezone/sqlite3/config) cleaned. Full
  pytest 694/694 green.

#### Pass 38.8 Consolidate resume-path boilerplate across job classes (LOW, M)

- **Target**: `services/jobs/ra_sync.py:112-157`, `ra_refresh.py:94-136`, `platform_sync.py:222-260, 514-564`, `psn_refresh.py:149-214`, `bulk_scrape.py:512-603`.
- **Why**: six copies of "if resume_index > 0 and game_ids, reset +
  prepend Nones + restore counts + start thread, else fall through."
- **Plan**: extract `_apply_resume(self, game_ids, progress, **extra)`
  onto a thin mixin used by every job with resume support.
- **Source**: 2026-04-24 audit, Background jobs M5.
- **Status**: done (v3.5.57) — three free-function helpers in
  `services/jobs/base.py` (chosen over a mixin: avoids forcing every
  job class into an inheritance chain when only ~10 lines are
  shared, and bulk_scrape's three callsites are inside class methods
  that already inherit from object). `pad_resume_game_ids(resume_
  index, remaining_ids)` returns `[None]*N + list(remaining)`;
  `restore_progress_counts(job, resume_index, progress)` writes
  `current_index` + the three counters under the caller's lock,
  treating `progress=None` and missing keys as zero;
  `try_acquire_singleton_or_warn(lock_name, kind='resume')` wraps
  `acquire_job_singleton_lock` with the standard "lock held by
  another worker process" warning. Eight callsites refactored:
  `ra_sync.resume_from_params`, `ra_refresh.resume_from_params`,
  `platform_sync.SteamSyncJob.resume_from_params` +
  `XboxSyncJob.resume_from_params`, `psn_refresh.resume_from_
  params`, `bulk_scrape.resume_from_params` + the two queued-job
  promote branches in `_swap_running_job` and
  `_start_next_queued`. Bulk scrape skips the singleton helper —
  it uses a queue-based promote/demote that acquires the lock
  elsewhere. `tests/test_pass38_resume_helpers.py` (18 tests)
  pins the helper contracts plus a source-grep regression that
  every refactored job module imports the helpers. Suite 764/764
  green (was 746).

#### Pass 42.1 Extract `_normalize_game_edit` helper (MEDIUM, M)

- **Target**: `routes/games.py:458` (form-POST) + `routes/games.py:917`
  (JSON).  Helper in `services/game_metadata_service.py`.
- **Why**: both edit paths independently normalize `players`, compute
  `sort_title`, cross-map ratings.  Three separate divergences today;
  Pass 40.6 closes the `players` case, but the structural lesson
  is "one helper, two callers."  Fold-in touches game routes H4 + C3
  plus scraper adapters C2.
- **Plan**: extract `_normalize_game_edit(dict) -> dict` that takes
  arbitrary edit payload and returns a sanitised dict ready for UPDATE.
  Include `cross_map_ratings`, `generate_sort_title`, `players`
  coercion, `invalidate_filter_cache + invalidate_analytics_cache`.
- **Status**: done (v3.5.52) — `services/game_metadata_service.
  normalize_game_edit(payload)` is the single source of truth: strip +
  empty-as-None on every string field, `release_date` validation
  (slashes → dashes, junk → None, impossible calendar dates → None),
  `players` routed through `normalize_players_value` (Pass 40.6
  invariant), 8-system rating cross-map that fires only on keys
  present in the payload (so JSON callers updating one rating don't
  get the other seven written underneath), `sort_title` auto-
  generation when title given but sort_title blank, `similar_games`
  re-join. Helper is pure (does not mutate caller dict; cache
  invalidation kept at call sites). `routes/games.py` form-POST and
  JSON paths both delegate; three orphaned imports
  (`cross_map_ratings`, `generate_sort_title`, `normalize_players_
  value`) cleaned. Form-POST cache-invalidation gap closed inline —
  it didn't call `invalidate_filter_cache`/`invalidate_analytics_
  cache` previously, only the JSON path did. 22 new functional tests
  in `tests/test_pass42_normalize_game_edit.py` (Strip / ReleaseDate
  / Players / RatingsCrossMap / SortTitle / SimilarGames buckets);
  Pass 40.6 source-grep tests rewritten to assert both edit paths
  route through `normalize_game_edit`. Suite 725 → 749.

#### Pass 42.2 Deduplicate migration helpers (MEDIUM, S)

- **Target**: `services/migrations/_helpers.py` (new); remove 4-6
  copies from individual migration scripts.
- **Why**: `_table_exists`, `_has_column`, `_admin_user_id`,
  `_columns_ddl`, `_add_column_if_missing` are duplicated across
  001/005/006/007/008/009.  Baseline's variant swallows
  `OperationalError`; post-baseline strict variants do not.  Drift
  is actively masking regressions.
- **Plan**: one `_helpers.py` with the strict variants; update all
  migration imports; add a schema-test that re-runs every migration
  on an empty DB to prove idempotency.
- **Status**: done (v3.5.43) — `services/migrations/_helpers.py`
  created with all 5 functions (strict `_add_column_if_missing`
  variant: PRAGMA-check-then-ALTER, no swallowed
  `OperationalError`). Migrations 005/006/007/008/009 import from
  `_helpers`; local copies removed. Migration 001 kept out of scope
  (its lenient try/except handles legacy pre-versioned schema and
  runs only against `user_version=0` installs); module docstring
  documents the deliberate split. Idempotency already covered by
  `test_idempotent_baseline_can_run_twice` (apply_pending re-runs
  after PRAGMA user_version=0 reset). `pytest tests/test_migrations
  .py tests/test_pass31_migrations.py`: 21/21 green; full suite
  694/694 green.

#### Pass 42.3 Global `window.onerror` + `unhandledrejection` handler (MEDIUM, S)

- **Target**: `static/js/main.js` or `static/js/utils.js` — handler
  pipes into `showNotification(msg, 'error')` with sampling.
- **Why**: 57 `console.error` sites and zero global handlers; silent
  UI failures reach the console and stop there.  User sees stale UI
  with no toast.
- **Plan**: add `window.addEventListener('error', ...)` and
  `'unhandledrejection'` handlers that dispatch to the toast system,
  rate-limited to one surface every 5s to avoid feedback loops.
- **Status**: done (v3.5.45) — handlers added in
  `static/js/main.js` immediately after the global-state block.
  Rate limit: one toast per 5 s via `_lastErrorToastAt` + `Date.now()`
  guard. Filters cross-origin "Script error." noise (browsers
  sanitize cross-origin script errors to that literal string with no
  useful detail). Unhandled-rejection branch handles `Error`,
  string, and arbitrary-object reasons (JSON.stringify + String()
  fallback). Toast call wrapped in try/catch as defence-in-depth.
  Bundle rebuilt; 694/694 tests green.

#### Pass 42.4 Pin / vendor Chart.js (MEDIUM, S)

- **Target**: `templates/analytics.html:1515`.
- **Why**: unpinned `cdn.jsdelivr.net/npm/chart.js` with no SRI on an
  admin-only page with session cookie.  Supply-chain attack surface.
- **Plan**: either pin `@4.x.y` + `integrity="sha384-..."`
  `crossorigin="anonymous"`, or vendor to `/static/vendor/chart.js`.
- **Status**: done — already addressed by Pass 46.1 (v3.5.35).
  Chart.js v4.5.1 UMD bundle vendored to
  `static/js/vendor/chart.umd.min.js`, served via the cache-busting
  `asset_url()` pipeline. No CDN reference left in the templates.

#### Pass 42.5 CHD converter dedup + `_persist_controller_image` (MEDIUM, M)

- **Target**: `scraper/rom_tools.py:CHDConverter` vs
  `routes/tools.py:602-648` inline worker; `routes/museum.py:670-698,
  723-755, 1105-1127` controller-image save.
- **Why**: two implementations of CHD conversion (one class-based,
  one inline) diverge on error handling; three identical 30-line
  blocks in museum do controller-image save/propagate.  Rule of
  Three crossed in both cases.
- **Plan**: keep the class; have `routes/tools.py` delegate.
  Extract `_persist_controller_image(controller_id,
  img_bytes_or_pil)` in `routes/museum.py`.
- **Status**: done (v3.5.54) — both halves landed.
  - **CHD dedup**: extracted module-level pure helper
    `scraper.rom_tools.convert_one_to_chd(src_path, chdman_path, *,
    do_verify, delete_original, skip_existing, convert_timeout,
    verify_timeout)` carrying the Pass 40.11 atomic-write contract end-
    to-end. Both `CHDConverter._convert_file` and
    `routes/tools.py:api_chd_converter_convert.run_conversion` now
    delegate to it; ~100 lines of duplicated subprocess/atomic-write
    logic collapsed. Pass 40.2 per-file `safe_path` guard stays at the
    route layer (the dict-task registry is route-local). The Pass
    40.11 regression suite was redirected to grep the helper directly
    + assert both call sites delegate via `convert_one_to_chd(`.
  - **Controller image dedup**: new
    `routes/museum.py:_persist_controller_image(controller_id,
    image_data)` carries the RGBA→crop→WebP→standardize pipeline;
    returns the saved filename or `None`. Three call sites collapsed
    (`upload_controller_image`, `remove_controller_bg`,
    `_fetch_and_process_image`); DB UPDATE + `_propagate_controller_image`
    stay at each call site (the third site doesn't do them, and the
    second has a divergent "skip UPDATE if filename matches" branch —
    pulling DB into the helper would re-introduce the divergence).
  - **Suite**: 746/746 green.

#### Pass 42.6 RA 401 observability + Steam / SS log-redaction tightening (MEDIUM, S)

- **Target**: `scraper/retroachievements.py` (5 callers),
  `services/log_redactor.py:31`.
- **Why**: stale API key masquerades as "no match"; credential
  patterns `key=` and `sspassword=` not in redactor.  Observability
  gap + credential leak surface.
- **Plan**: already scoped under Pass 41.5 for redactor; track the
  RA observability half here (5 call-site edits to surface 401 as a
  distinct error).
- **Status**: done — both halves landed in earlier passes. Redactor
  half: Pass 41.5 added `key` / `sspassword` patterns to
  `services/log_redactor.py:39`; Pass 45.13 added `y` / `z` (RA
  single-char param names). RA 401 observability half: Pass 41.7.C
  added explicit 401 `logger.error(...)` calls in all 5 RA callers
  (`search_game_by_name`, `get_game_info`, `get_user_game_progress`,
  `get_user_game_progress_custom`, `get_user_summary`) with the
  user-actionable hint "Re-enter the api_key in Settings →
  Scrapers". Stale roadmap entry; verified 2026-05-02.

#### Pass 42.7 Adopt or remove `PageLifecycle` (MEDIUM, M)

- **Target**: `static/js/page-lifecycle.js` (467 LoC) + all JS call
  sites currently rolling their own cleanup.
- **Why**: 0 current consumers of `PageLifecycle.*`; CLAUDE.md
  advertises the abstraction as canonical.  Either migrate the 10
  hot-path files or delete the module.
- **Plan**: pick an option; don't leave the doc-vs-code drift.
- **Status**: done (v3.5.46) — REMOVE option chosen (shorter, lower
  risk; with zero consumers the "canonical" advertisement in
  CLAUDE.md was misleading). `static/js/page-lifecycle.js` deleted;
  `build_js.py` CORE_ORDER entry dropped; CLAUDE.md "Globals
  defined in" list and "Lifecycle: PageLifecycle / DOMCache" bullet
  removed. Test pin
  `test_36_5_session_storage_sites_migrated` updated to drop the
  page-lifecycle.js file reference (its `safeParseJSON` site no
  longer exists). 694/694 tests green.

#### Pass 42.8 Remove `/api/recently-viewed` + `ScraperManager.get_enabled_scrapers` + CSP nonce dead infrastructure (LOW, S — bundle)

- **Targets**:
  - `routes/games.py:1117-1142` — zero callers.
  - `scraper/scraper_manager.py:286-302` — zero callers.
  - CSP nonce infrastructure is covered by FU.1; noted here for
    cross-reference.
- **Plan**: delete the two zombie functions; FU.1 handles CSP.
- **Status**: done (v3.5.41) — `routes/games.py` `/api/recently-viewed`
  was already removed by Pass 41.9 (zero-callers JS-side); now
  `ScraperManager.get_enabled_scrapers` deleted in
  `scraper/scraper_manager.py` (zero callers across .py, .js, .html;
  the `enabled` lookup it wrapped is read directly inside
  `search_games`). CSP nonce infrastructure stays gated on FU.1.

#### Pass 42.9 Test-suite hygiene sweep (LOW, S)

- **Target**: `tests/` — drop redundant / misplaced / subsumed tests
  surfaced by an end-to-end audit (749-test suite, 12k LoC).
- **Why**: The audit asked the six standard questions — accurate /
  valid / redundant / duplicated / optimised / efficient. Suite is
  fast (3.4s), green, and ~95% clean, but three tests had drifted into
  redundancy as later passes pinned strictly-stronger invariants
  elsewhere.
- **Plan**: delete the three; record subsumption in the surviving
  class's docstring so future-readers don't re-add the pin.
- **Status**: done (v3.5.53) — three deletions, suite 749 → 746:
  - `test_input_hardening.py::test_recently_viewed_endpoint_removed`
    — literal duplicate of `test_pass41_security.py
    ::test_recently_viewed_endpoint_deleted` (Pass 41 copy is
    stronger; also greps the function symbol is gone).
  - `test_pass45_security.py::TestPass45_20ButtonTypeSweep
    ::test_chmod_before_verify_in_backup` — re-pin of Pass 45.5
    misplaced in the button-sweep class. The Pass 45.5 home
    (`TestPass45_5AtomicWrite::test_backup_database_chmods_before_
    verify`) carries the same assertion plus an end-to-end backup
    smoke.
  - `test_pass40_security.py::TestPass40_12ToastControllerXss
    ::test_no_inline_onclick_with_template_interpolation` — historical
    pin for one specific `onclick=...cancelQueued...` string. Now
    strictly subsumed by Pass 45.4's
    `test_toast_controller_has_no_inline_onclicks` ("NO inline onclick
    anywhere in toast-controller.js"). Sibling test
    `test_system_name_escaped` retained — it pins a different
    invariant (raw-interpolation of `job.system_name`) that no other
    test covers; class docstring updated to record the subsumption.
- **Out of scope** (considered, kept):
  - `_REPO_ROOT = os.path.dirname(...)` constant duplicated across
    12 test files. Lifting to `conftest.py` looked attractive but
    each occurrence is paired with a `sys.path.insert` mutation;
    refactoring would require either making `tests/` a Python package
    (changes pytest collection semantics) or shimming through a
    helper module. 12 lines of trivial duplication is cheaper.
  - 10 tests use `'Pass NN.X' in body` comment-pin assertions.
    Fragile if comments rot, but each is paired with a structural
    assertion in a window — they degrade to broken-test, not silent
    pass. Acceptable.

---

### Internationalization (i18n) — language packs

> **Pass 43** (proposed, deferred until Tier-1 + Tier-2 sweeps are done).
> Ship-shape RetroDB in any language; UI strings translated, retro-game
> data (titles, descriptions, scraper output) deliberately untranslated
> because that's content, not chrome.

#### Pass 43.1 Wire Flask-Babel + extract first language pack (HIGH, L)

> **Re-scoped (design pending) — see `docs/superpowers/specs/2026-06-10-i18n-foundation-design.md`.**
> The full-scope plan below (all ~45 files, `de/fr/es/it/ja/pt_BR` roster,
> `settings.html` section) is superseded: 43.1 now lands i18n *machinery + a
> single-page pilot* only. The bulk template/string migration + real catalogs move
> to a new Pass 43.5 (created when the foundation lands). Trust the spec, not the
> body below, for 43.1 scope.

- **Target**: every user-facing UI string in `templates/*.html` (45
  files, ~3-4k strings), `routes/*.py` flash + error messages, and
  `services/api_helpers.py::error()` callers.  JS strings (toasts,
  modals, dialog labels) live separately — see 43.3.
- **Why**: RetroDB is a single-binary Flask app, single-household
  deployments often have non-English-speaking family members.  No
  language-switch primitive exists today; everything is hard-coded
  English.  Flask-Babel is the standard plugin and folds cleanly into
  Jinja's auto-escape pipeline.
- **Plan**:
  1. Add `flask-babel` to `requirements.txt` + `requirements.lock`.
  2. Initialize `Babel(app)` in `app.py`; locale selector reads
     `g.user_settings.locale_preference` first, then session, then
     `Accept-Language` header, then `BABEL_DEFAULT_LOCALE='en'`.
  3. Migrate templates progressively: wrap visible strings in
     `{{ _('...') }}` / `{% trans %}...{% endtrans %}`.  Keep
     attribute strings (`title=`, `aria-label=`, `placeholder=`) in
     scope.  Don't translate template comments or class names.
  4. Migrate Python flash + error sites: `flash(_('Please log in'))`,
     `error(_('Invalid CSRF token'), 403)`.
  5. `pybabel extract -F babel.cfg -o messages.pot .`; commit
     `messages.pot` as the canonical extraction snapshot.
  6. `pybabel init -i messages.pot -d translations -l en` (and any
     additional shipped languages: probably `de`, `fr`, `es`, `it`,
     `ja`, `pt_BR` to start).  Compile with `pybabel compile -d
     translations`.
  7. Add a Settings → Language section to `templates/settings.html`
     (per-user locale_preference) with a dropdown of available
     translations enumerated from `translations/` at request time.
- **Caveats**:
  - DB content (game titles, alternate_titles, description, genre
    canonical forms) is NOT translated — it's raw scraper data and
    canonical genre values feed FIELD_SCHEMAS-driven validation.
    Translating "First-Person-Shooter" would corrupt the schema; the
    scraper writes the canonical English form, the UI displays a
    translated label via a separate i18n map keyed on the canonical.
  - Theme display names ("Cyberpunk", "Matrix") are left as-is —
    they're brand-style identifiers, not chrome.
  - Multi-rating system labels (ESRB, PEGI, etc.) stay as-is — these
    are official trademarks.
- **Source**: net-new feature ask 2026-04-25.
- **Status**: todo

#### Pass 43.2 Translate canonical genre / dimension / perspective labels (MEDIUM, M)

- **Target**: `services/game_utils.py` field-display helpers + every
  `<select>` populating canonical multi-value fields.
- **Why**: 43.1 leaves DB-stored canonical values untranslated for
  data-integrity reasons.  But a French viewer reading "First-Person-
  Shooter, 3D" in the UI is mid-translation noise.  A small
  `services/i18n_labels.py` map keyed on canonical English → translated
  display label closes the loop without touching the DB.
- **Plan**: build the map at `services/i18n_labels.py`; expose a
  `display_field_value(field, canonical_value, locale)` helper.  Wire
  through `game_utils.py` for `genre`, `perspective`, `dimension`,
  `modes`, `game_structure`.  Filter pages render translated labels
  but submit canonical English values to the API; the controller
  layer never sees translated tokens.
- **Status**: todo

#### Pass 43.3 JS-side i18n bundle (MEDIUM, M)

- **Target**: `static/js/toast-controller.js`, `game-modals.js`,
  `main.js`, every JS file that constructs user-visible strings via
  template literals.
- **Why**: 43.1 covers server-rendered strings; toasts and modal
  copy are constructed client-side and would stay English under that
  scheme.
- **Plan**: server emits `window.I18N` (a translated string map) in
  `base.html` based on the active locale.  JS reads via a thin
  `t('toast.scrape_started')` helper.  Build step: a Python script
  that walks JS for `t('...')` keys and ensures every key exists in
  the locale map; CI fails the build on missing keys.
- **Status**: todo

#### Pass 43.4 RTL layout support (LOW, L)

- **Target**: `static/css/core/*.css`, every grid/flex layout, every
  text-align/margin-left utility.
- **Why**: Arabic and Hebrew are RTL; the current CSS bakes
  left-to-right assumptions deep into the grid/sticky-nav system.
- **Plan**: switch directional utilities (`margin-left/right`,
  `text-align: left`) to logical properties (`margin-inline-start/end`,
  `text-align: start`).  Add `[dir="rtl"]` overrides where logical
  properties don't reach (icons, chevrons, sortable column arrows).
  `<html dir="rtl">` driven by locale class.  Defer until at least one
  RTL translation lands — a feature without a user is dead weight.
- **Status**: deferred — gated on Pass 43.1 plus a translator who
  ships an RTL `.po`.

---

### Follow-ups from landed passes

Small, well-scoped items that surfaced while finishing an earlier pass but
weren't worth blocking the ship on.  Ordered by rough priority.

#### FU.1 Flip CSP from Report-Only to enforcing (MEDIUM, L — needs template migration)

- **Context**: Pass 16.2 shipped CSP as `Content-Security-Policy-Report-Only`
  because ~765 inline `on*` event handlers and ~38 inline `<script>` blocks
  still exist across templates.  Violations surface in the browser console
  today; flipping to enforcing would break pages.
- **Plan**: migrate inline handlers to delegated listeners registered in the
  page's bundled JS, convert inline `<script>` blocks to either external
  files or nonced blocks (`<script nonce="{{ csp_nonce }}">`), then change
  the header name from `Content-Security-Policy-Report-Only` to
  `Content-Security-Policy` in `app.py::set_security_headers`.
- **Status**: partial (v3.6.20). Phase A landed — every inline
  `<script>` block carries `nonce="{{ csp_nonce }}"` (46 blocks across
  38 templates) and every live `onerror=` attribute has moved to either
  a `data-on-error="<action>"` marker (handled by the document-level
  capture-phase listener in `static/js/main.js::initializeImageError
  Handling`) or a per-page `addEventListener('error', …)` block in the
  template's nonced `<script>`. Supported actions: `hide`,
  `hide-show-next`, `hide-show-id`, `src`, `outer-html`. Regression
  pins in `tests/test_fu1_csp.py` (10 cases).
- **Still queued for FU.1**: ~594 inline `onclick` handlers (the bulk
  of the work; needs a delegated `data-action` pattern + per-page
  controller wiring), ~80 `onchange`, plus a handful of `onsubmit`,
  `oninput`, `onkeydown`, `onkeypress`, `onmouseover`. Once those are
  migrated, flip the header name from
  `Content-Security-Policy-Report-Only` to `Content-Security-Policy`
  in `app.py::set_security_headers` and drop this entry.

#### FU.2 Grid-card `srcset` for boxart (LOW, M)

- **Context**: Pass 18.3 wired `boxart_srcset()` into the detail-page hero
  `<img>` but deliberately left the card grid off because emitting per-card
  srcset on a 500-item page would mean 500 filesystem `stat` calls per
  render.
- **Plan**: add a request-scoped batch-existence cache — one `os.scandir`
  of `static/images/boxart/` per request, membership test per card — then
  call `boxart_srcset()` from `build_game_card()` in
  `services/game_metadata_service.py` so every card payload includes a
  pre-computed `boxart_srcset` field.  Update
  `static/js/all-games-controller.js` to emit the field when present.
- **Status**: done (v3.6.18). `boxart_dir_listing()` memoizes one
  `os.scandir` per `image_type` on `flask.g`; `boxart_srcset()` gained
  optional `image_type` + `existing=<set>` arguments that skip
  `PIL.Image.open` in batch mode (760 w fallback descriptor for the
  original). `build_game_card()` emits `boxart_srcset` and
  `boxart_3d_srcset` fields; `renderGameCard()` in `all-games-controller.js`
  emits `srcset` + `sizes="(max-width: 768px) 100px, 135px"` when present,
  and the 3D→2D `onerror` fallback now clears both attributes. Trip-wire
  test (`test_batch_mode_uses_existing_set_no_pil`) pins the no-PIL
  contract.

#### FU.3 Bulk JPEG→WebP migration endpoint (LOW, M)

- **Context**: Pass 18.1 ships WebP on ingest, but legacy `.jpg` / `.png`
  files in existing libraries stay in their original format.  The bulk
  `ImageResizeJob` already re-encodes via `_save_image()` when it runs, but
  filename extensions (and therefore DB references) are preserved.
- **Plan**: new `/api/maintenance/convert-to-webp` endpoint that walks
  `games.boxart`, `games.boxart_3d`, `games.fanart`, `games.screenshots`
  (comma-split), and `games.manual`; converts each referenced JPEG/PNG to a
  sibling `.webp`; updates the DB filename in-place; then deletes the
  original after verifying the `.webp` opens cleanly.  Disk-space guard
  (refuse to start if free space < 2× current media size).  Background job
  following the `ImageResizeJob` pattern with status/cancel endpoints.
- **Status**: done (v3.6.19). `services/jobs/webp_migrate.py::WebPMigrateJob`
  follows the ImageResizeJob shape (singleton lock, persist_job_*
  checkpointing, lock-guarded counter reads). Per-file flow: PIL save →
  PIL verify → DB UPDATE → unlink original (in that order, so a crash
  leaves at worst an orphan `.webp` + intact original). Screenshots CSV
  handled with exact-entry read-modify-write under a `WHERE
  screenshots = ?` guard against concurrent edit-modal writes. Boxart
  variant `-sm` / `-md` siblings cleaned + regenerated against the new
  `.webp`. Resume-aware: an already-present `<stem>.webp` is adopted
  without re-encoding. Manuals (PDF) skipped. Three admin-gated routes
  in `routes/maintenance.py` (`/api/maintenance/convert-to-webp/start|status|cancel`).
  9 regression tests in `tests/test_webp_migrate.py` pinning filter
  behaviour, atomicity, CSV-collision safety, verification rollback,
  variant sync, resume path, disk-space guard, and lock-guarded status.

#### FU.4 Stream large image downloads in the TGDB scraper (LOW, S)

- **Context**: Pass 13.1 moved `base_scraper.download_image()` to streamed
  chunked writes, but the TGDB wrapper in
  `scraper/scrape_thegamesdb.py::download_image` still buffers
  `response.content` entirely in memory before writing.  For a 10 MB fanart
  JPEG that's a ~10 MB spike per concurrent scrape.
- **Plan**: switch the TGDB wrapper to the same `http_get(..., stream=True)`
  + `iter_content(8192)` pattern as the base helper.  Keep the
  `http_get` retry/backoff semantics — the helper doesn't currently expose
  `stream=True`, so either add a flag or call `_http_session.get` directly
  for images.
- **Status**: done — already addressed by Pass 40.7 (SSRF hardening).
  `_download_tgdb_image` now delegates to `base_scraper.download_image`
  which already does streamed `iter_content(8192)` writes with a 50 MB
  cap. The original `response.content` buffering pattern this entry
  describes is gone.

#### FU.5 Group-label a11y pattern (LOW–MEDIUM, S–M)

- **Context**: Pass 28.1 fixed the 87 sibling-label cases by adding
  `for=…`, but 33 cases remain where one `<label>` heads a *group* of
  controls — button groups (`templates/lists.html:54` icon picker,
  `templates/tags.html:50` color swatches, `templates/wishlist.html:78`
  priority radios, `templates/logs.html:748,768` level/view toggles),
  toggle grids (`chd_converter.html:124`, `duplicate_finder.html:231`,
  `rom_tools_settings.html:393,425`), custom tag widgets in the edit
  modals (`_modals/edit_modal.html:106,145,158,169,186` and the
  parallel `base.html:1067-1147` gem modal), and prose-style labels
  (`settings.html:171,433,461,580,912`).
- **Why**: visual labels already convey context, but the relationship
  isn't programmatically exposed to assistive tech. Screen readers
  hear the controls but can't anchor them to the group label.
- **Plan**: per-case judgement: convert to `<fieldset><legend>` for
  semantically-related controls (toggle grids, button groups), or use
  `role="group"` + `aria-labelledby` for custom widgets where
  fieldset semantics don't fit. For prose-style labels heading a
  read-only display (e.g. `Database Location`), demote `<label>` to
  `<div class="form-label">` since there's no control to associate.
- **Status**: partial (v3.5.67) — turned out most of the 33-case master
  list was already addressed in earlier passes:
  - **Toggle grids** (`chd_converter.html:124`, `duplicate_finder.html:231`,
    `rom_tools_settings.html:393,425`) already use
    `<div class="form-label" id="...Label">` + `role="group"
    aria-labelledby="...Label"` on the surrounding container.
  - **Button groups** (`lists.html:54` icon picker, `tags.html:50` color
    swatches, `wishlist.html:78` priority radios) — same pattern, already
    landed.
  - **Toolbar level/view toggles** (`logs.html:748,768`) — already
    `role="group" aria-labelledby`.
  - **Prose-style labels** in `settings.html:171, 433, 461, 580` — already
    demoted to `<div class="form-label">`. Line 912 is `<label
    for="matchPlatformRequired">` which correctly associates with its
    checkbox (a redundant `aria-label="Require platform match"` sits on
    the input — minor hygiene, left for a future sweep).
  - **Custom widgets in edit modals** (`_modals/edit_modal.html:106, 117,
    145, 158, 169, 186, 201` + parallel gem modal in `base.html:1093,
    1101, 1113, 1121, 1129, 1154, 1165`) — **closed in this pass**.
    Each multi-value tag-picker field had a `<label for="<X>Dropdown">`
    pointing at the helper "+ Add" `<select>` instead of the chip
    container. AT announced the field name, then a combobox, missing the
    chip list. Each field now wrapped in `role="group" aria-labelledby`
    with the `<label>` demoted to `<div class="form-label">` with a
    stable id; the helper select gets its own `aria-label="Add <X>"`.
    14 fields total. Custom-controller text input also picked up
    `aria-label="Custom controller name"`.

#### FU.6 Test-audit 2026-05-18 deferred items (LOW–MEDIUM, M)

- **Context**: `/test-audit` 2026-05-18 (v3.6.21) folded ~85 actionable
  findings across 70 pytest files. The HIGH-severity items and the
  surgical MEDIUM/LOW fixes landed in v3.6.21 (see changelog 3.6.21 for
  the per-item list). The items below are deferred because they need
  bigger structural changes than a quality-only fix-pass should make.
- **Why**: each one is real test-quality debt — flake risk, vacuous
  assertion, copy-paste fixture surface — but not load-bearing today.
  Bundle them into a single follow-up so the next test-pass touches each
  file once.
- **Plan** (per finding):
  - **Extract admin-stub fixture** (c-005 LOW duplication) — 8+ sites
    across `tests/test_pass40_security.py` + `tests/test_pass45_security.py`
    inline the same `fake_admin = {…}` + `monkeypatch.setattr(app_module,
    'get_current_user', …)` + `…get_user_settings` + `…load_settings` +
    `…config['TESTING']` stanza. Lift into a `@pytest.fixture
    admin_test_client(monkeypatch)` in `conftest.py` returning
    `(client, csrf_token)`. Any future user-dict schema change then
    propagates to one site.
  - **Split `test_pass40_security.py`** (1190 lines, 16 sub-passes —
    c-005 LOW splitting) at the 40.1–40.8 / 40.9–40.16 boundary so a
    shared-infrastructure import failure doesn't surface as 16 separate
    failures with no clear root cause.
  - **Split `test_input_hardening.py`** (255 lines, 8 unrelated
    security subsystems — c-003 LOW splitting): ES-DE path traversal,
    report whitelist, museum SSRF, museum upload cap, CLZ PDF bounds,
    video upload cap, scraper download caps, rate-limit registration.
    Splitting lets the heaviest test in each file (Flask app import)
    only fire when that subsystem actually needs it.
  - **`test_launcher_local` subprocess flake** (c-003 MED flakiness) —
    the 5 s poll-and-sleep deadline against `/bin/true` / `/bin/false`
    real subprocesses is documented flake-bait (the bump from 2 s → 5 s
    is in source comments). Expose a `LocalLauncher.wait(timeout)` that
    wraps `proc.wait(timeout)` so tests can join synchronously; add a
    `local_launcher` fixture that kills any leaked children on teardown
    (c-003 MED isolation, same file).
  - **Replace source-grep `test_status_snapshot_holds_lock`**
    (c-006 INFO accuracy) — `inspect.getsource(...).contains('with
    self._lock')` is satisfied by any comment containing the string,
    and breaks under a `_lock → _mutex` rename. Replace with a
    behavioural test: drive `get_status()` from a second thread while
    the worker holds the lock, assert the returned snapshot is
    consistent. Source-grep can stay as a secondary pin but isn't the
    primary contract.
  - **Tighten `test_webp_migrate` `saved >= 0`** (c-006 MED) — at
    integration scope, use a real JPEG/PNG sample image known to
    compress, assert `saved > 0`. Keep the type check at unit scope.
  - **`test_graceful_shutdown` wall-clock joins** (c-002 HIGH
    flakiness) — three tests pass `timeout=0.3/0.5 s` to
    `request_shutdown()` with fakes that complete instantly. For
    instant-fake tests tighten to `timeout=0.01`; for the
    stuck-worker `test_timeout_caps_drain_wait`, mock `Thread.join`
    to record calls rather than blocking on a real thread.
  - **`seeded_db` fixture rollback** (c-002 HIGH isolation) — the
    function-scoped `seeded_db` in `tests/test_emulator_seeder.py`
    writes to a module-scoped `db` without teardown rollback;
    `test_seeder_is_idempotent` then takes raw `db` and relies on
    sibling-test seed-data for its `emu_before > 0` floor. Add
    teardown rollback to `seeded_db`, OR give the idempotency test
    a fresh connection it seeds twice.
  - **Consolidate `_open()` migration helpers** (c-004 MED
    duplication) — `tests/test_migrations.py:22` and
    `tests/test_pass31_migrations.py:24` carry near-twin `_open()`
    helpers; the don't-merge contract lives in a comment. Promote to
    `tests/conftest.py` as `open_db_positional(path)` and
    `open_db_named(path)` with the row-access distinction
    documented in one place.
  - **Split multi-assertion `test_failed_migration_rolls_back_and_keeps_version`**
    (c-004 MED splitting) at `tests/test_migrations.py:114` — currently
    asserts both DDL rollback AND `user_version` non-advancement in
    one body; split so a failure in one doesn't mask the other.
  - **`test_pass40_security.py:861 done.wait(timeout=5.0)`** (c-005
    MED flakiness) — bump to `@pytest.mark.timeout(15)` so xdist
    kills rather than hangs, OR call `Thread.run()` synchronously in
    the same pattern as the sibling test at line 323.
  - **Coalesce `test_pass40_security` monkeypatches** (c-005 MED
    isolation) — 8 sites independently patch the same module-level
    `app_module.get_current_user` / `get_user_settings` /
    `load_settings`. Under xdist these can race; the same admin-stub
    fixture extraction above closes this finding.
  - **`_isolated_db` class method → pytest fixture**
    (c-001 LOW fixtures) — `tests/test_auth_hardening.py:261` exposes
    `_isolated_db` as a plain class method requiring callers to
    pass `tmp_path` and `monkeypatch` through manually. Convert to
    a function-scoped `@pytest.fixture` so the calling convention
    matches the rest of the suite.
  - **`_PersistentConn.__del__` → fixture teardown** (c-006 MED
    setup_teardown) — `tests/test_scrape_fill_only.py:52` relies on
    GC-driven `__del__` for connection close, which is best-effort
    on PyPy / under pytest-xdist process reuse. Wrap in a fixture
    or `try/finally` that calls `conn.real_close()` explicitly.
  - **`test_slow_query_log` fast-query 100 ms threshold**
    (c-006 HIGH flakiness) — `_log_if_slow(start=time.perf_counter(),
    threshold=100ms)` is only safe if the gap between the
    `perf_counter()` call and the threshold check stays under
    100 ms; GIL contention can stretch that. Patch
    `time.perf_counter` inside `_log_if_slow` OR back-date the start
    with a small negative buffer so a >100 ms hiccup can't cross
    the threshold.
  - **`test_pass46_frozen_paths` teardown error-masking**
    (c-006 LOW flakiness) — the `reloaded_app` fixture's teardown
    calls `importlib.import_module('config')` / `import_module('app')`
    unconditionally; if reload fails, the pytest ERROR masks the
    originating test failure. Wrap teardown reimports in
    `try/except Exception` with `warnings.warn`.
  - **Docstrings on 8/10 functions in `test_retroarch_detect.py`**
    (c-006 LOW doc_strings) — explain what UI behaviour each
    function pins (Settings UI silently-accepts-bad-path concern,
    etc.) — one-liners.
  - **`REPO_ROOT` shadow in `test_fu1_csp.py:22`** (c-002 LOW
    naming) — imported as `str` from `tests._util`, immediately
    re-bound as `pathlib.Path`; `read_source` also imported but
    unused. Drop the str-form import + remove the unused
    `read_source` import.
  - **`test_fu1_csp.py:64` magic-count floor `>= 40`** (c-002 LOW
    hardcoded_data) — drifts over time as templates are added or
    consolidated. Either drop (the `test_no_unnonced_inline_script_block`
    structural test is the authoritative gate) or generate the floor
    dynamically from the current count with a documented regeneration
    step.
  - **`test_graceful_shutdown::test_sets_shutdown_event timeout=0.1`**
    (c-002 LOW performance) — all singletons are `None`, so the test
    waits 100 ms for nothing. Pass `timeout=0`.
  - **`test_auth_hashing::test_needs_rehash_flags_low_iteration_pbkdf2`**
    (c-001 LOW performance) — `hash_password("x", iterations=100_000)`
    pays ~30-80 ms of real PBKDF2 work to inspect the output prefix.
    Synthesise the hash string directly:
    `f"pbkdf2:100000:{'a'*32}:{'b'*64}"` (already the pattern used at
    `:93`).
- **Status**: planned. Folded from `/test-audit` 2026-05-18 sweep
  (see changelog 3.6.21). Lanes: tests.

---

<a id="done-index"></a>

## Done index

Compact one-liner per landed pass.  Detail lives in git history
(`git log --grep "v2.83"` or similar), in `data/changelog.yaml`, and
in the commit messages themselves.  Listed in version order so the
landing sequence stays legible — Pass numbers reflect planning order
and may jump (e.g. Pass 17 → 16 → 23 → 19) because rows are sorted
by landed version.

LOC numbers in the historical rows below reflect the file size **at
the time the pass landed**, not the current file size.  Subsequent
edits drift the numbers; do not "correct" them — the historical figure
is the audit trail.

### v2.83.x — Refactoring waves (Passes 2–10)

- [x] **Pass 2 (waves 1–2)** — `@handle_api_errors` decorator + `success()` /
  `error()` response-builder helpers across 14 fully-swept routes (118
  handlers, 186 jsonify migrations).  Carry-over for partial files in
  Active.  (v2.83.5–7)
- [x] **Pass 3** — HLTB service extraction; `routes/games_hltb.py` 366 → 165
  LOC + new `services/hltb_service.py` (3 classes, typed error surface).
  (v2.83.8)
- [x] **Pass 4** — `routes/maintenance.py` split: 693 → 254 LOC + three
  service modules (`rom_scanner.py`, `media_cleanup.py`,
  `game_cleanup.py`); per-field delete blocks collapsed via `_MEDIA_LAYOUT`.
  (v2.83.10)
- [x] **Pass 5** — `scraper/metadata_merger.py` split: 1293 → 1090 LOC +
  `image_dedup.py` (dHash + post-download dedup) + `metadata_normalizer.py`
  (title/ESRB/alt-titles helpers).  (v2.83.11)
- [x] **Pass 6** — `scraper_manager.py` split: 1022 → 684 LOC + `match_scorer.py` /
  `title_normalizer.py` / `scraper_cache.py`; SS result-parsing flattened
  to `_parse_ss_result` + `_pick_ss_region`.  (v2.83.12)
- [x] **Pass 7 stages 1–3** — `routes/games.py` decomposition: 1373 → 1128
  LOC; carved `game_metadata_service.py`, `achievement_linking.py`,
  `game_media_service.py`; consolidated three normalization regimes;
  unified `apply_metadata_to_game` / `apply_hybrid_metadata_to_game`
  service entry point used by all three call sites.  (v2.83.13/16/19)
- [x] **Pass 8** — `window.API` migration across 13 JS files (83 of 84
  raw `fetch` sites collapsed); bundle 312 KB → 271 KB minified.
  (v2.83.22)
- [x] **Pass 9** — scraper/ filename consistency: `scrape_metadata_igdb.py`
  → `scrape_igdb.py`, `scrape_metadata_thegamesdb.py` →
  `scrape_thegamesdb.py`; 6 import sites updated; standards §24.1
  enforced.  (v2.83.21)
- [x] **Pass 10** — template macros: 6 modal partials extracted from
  `game_detail.html` into `templates/_modals/`; 5904 → 5376 LOC (−8.9%).
  (v2.83.23)

### v2.84.x — Security + DB perf + frontend perf + tests

- [x] **Pass 11 (7 items)** — Security hardening: PBKDF2-SHA256 100k → 600k
  with migrate-on-login, `SESSION_COOKIE_SECURE` env-gate, image-upload
  magic-byte validation, rate-limits on heavy admin routes (+ 2 stale
  endpoint-name fixes), CSRF rationale doc, root-logger `SecretRedactor`
  install.  (v2.84.0)
- [x] **Pass 12 (4 of 5)** — DB perf: per-request + long-lived `PRAGMA
  optimize`, batched job progress connection, `ANALYZE` after
  `CREATE INDEX`, `RETRODB_SLOW_QUERY_MS` query log.  12.5 (FTS5)
  deferred — see Active.  (v2.84.1)
- [x] **Pass 13** — Frontend perf: streaming image downloads
  (`iter_content`), single `app.bundle.js` split into `core.bundle.js` +
  `games.bundle.js` (127 KB savings on non-games pages), per-file
  content-hash cache-busting via `static/asset_manifest.json`.  (v2.84.2)
- [x] **Pass 14 (2 of 3)** — `.pre-commit-config.yaml` (ruff + gitleaks);
  characterisation tests for `metadata_merger.py` (30 tests) and
  `bulk_scrape.py` state machine (24 tests); 145 → 199 tests total.
  14.2 (type hints) deferred — see Active.  (v2.84.3)

### v2.85.x–v2.95.x — A11y, observability, headers, image, ops, migrations, ETag/gzip, CI, input hardening, multi-user

- [x] **Pass 15 (5 items)** — A11y round 1: skip-link, `ModalFocusTrap` (15
  call sites), theme contrast audit (`scripts/audit_contrast.py` +
  `docs/theme_contrast.md`; bladerunner contrast bumped 2.80 → 5.10:1),
  redundant ARIA sweep, keyboard-shortcut overlay refactor.  (v2.85.0)
- [x] **Pass 17 (3 items)** — Observability: `/health` + `/ready` probes,
  request-ID correlation via `setLogRecordFactory`, slow-request logging
  (`SLOW_REQUEST_MS`).  (v2.86.0)
- [x] **Pass 16 (4 items)** — HTTP security headers: drop `X-XSS-Protection`,
  add CSP **Report-Only** (per-request nonce via `secrets.token_urlsafe`),
  add `Permissions-Policy` (11 sensors/APIs), env-gated `Strict-Transport-Security`.
  Enforcing flip tracked as FU.1.  (v2.87.0)
- [x] **Pass 18 (3 items)** — Image pipeline: WebP on ingest
  (`RETRODB_IMAGE_FORMAT` + `finalize_downloaded_image`),
  `loading="lazy" decoding="async"` on every card/grid `<img>`, responsive
  `srcset` + `_make_responsive_variants`.  Grid-card srcset → FU.2.
  (v2.88.0)
- [x] **Pass 23 (9 items)** — Correctness bugfixes from 2026-04-23 review:
  scraper-manager AttributeError fix, RAWG fill-only alignment, rating
  cross-map dedup, set-iter ordering, source=rom paren fix, manuals path
  divergence, GIF animation preservation, `config.example.py` resync,
  hybrid-scraper test pin.  (v2.88.1)
- [x] **Pass 19 (8 items)** — Operational resilience: SQLite online backup
  API + integrity check, SIGTERM/SIGINT graceful shutdown, backup rotation
  (`MAX_BACKUPS`), bulk-scrape swap/demote race fix, MuseumGenerateJob
  brought up to persistence contract + dedup, `JOB_HISTORY_RETENTION_DAYS`
  sweep, `atomic_write_json` for settings, PSN ALTER table-existence
  guard.  (v2.89.0/2.90.0)
- [x] **Pass 20 (2 items)** — Versioned schema migrations: `services/migrations/`
  framework with `PRAGMA user_version`; `database_init.py` 647 → ~115 LOC;
  3 migrations seeded (baseline, normalize_genres, normalize_pegi);
  standards doc §25 added.  (v2.91.0)
- [x] **Pass 21 (2 items)** — Request-level caching: weak ETag on
  `/api/games/card-data` keyed on `MAX(updated_at)` (migration 004 +
  triggers); `compress_response` gzip after_request hook.  (v2.92.0)
- [x] **Pass 22 (8 items)** — CI/CD hardening: dependabot config, `pip-audit`
  in CI, `pytest-cov` reporting, py 3.12+3.13 matrix, semgrep wired to
  `.semgrep.yml`, signed release artifacts (cosign + SLSA + SBOM),
  destructive-endpoint coverage (landed alongside Pass 24), lockfile-drift
  test.  (v2.93.0/2.95.0)
- [x] **Pass 25 (9 items)** — Input hardening / SSRF / size caps: ES-DE
  path-traversal guard, `/api/reports` system-folder whitelist, museum
  Bing-search SSRF (`_is_public_https_url`), museum upload size cap, CLZ
  PDF page cap + scoped dup check, `MAX_VIDEO_SIZE`, response size caps
  on scraper image downloads, `MAX_LIST_ROWS` on list endpoints,
  Flask-Limiter rules on 5 expensive endpoints.  (v2.94.0)
- [x] **Pass 24 (8 items)** — Multi-user authn/authz: passwordless-editor
  bypass closed, `session.clear()` on auth boundary, force-password-change
  middleware pinned, password min 8 → 12 + change-endpoint rate-limit,
  11 destructive endpoints raised to `@editor_required`, Xbox OAuth state
  param, token JSON `0o600`, `SecretRedactor` label-gated token pattern.
  (v2.95.0)

### v2.96.x–v2.99.x — Scraper HTTP, multi-user data ownership, a11y round 2, bugfixes

- [x] **Pass 26 (5 items)** — Scraper HTTP uniformity & API-key hygiene:
  ScreenScraper + RetroAchievements through `base_scraper`, Gemini key
  out of querystring, AI circuit-breaker at call site, unified 5xx retry
  policy, mask API keys on settings GETs.  (v2.96.0)
- [x] **Pass 28 (6 items)** — A11y round 2: `<label for=>` association
  (87 sites), `ModalFocusTrap` on template-local modals, drop positive
  `tabindex` from `_modals/edit_modal.html`, skip-link verification,
  `prefers-reduced-motion` kill-switch on theme canvas, `aria-live="polite"`
  on notifications + loading containers.  (v2.97.0)
- [x] **Pass 27 (3 items)** — Multi-user data ownership round 1: `owner_id`
  on tags / lists / wishlist (migration 005), per-user PSN/Xbox tokens
  (migration 006), platform sync jobs scoped to user.  (v2.98.0)
- [x] **Pass 30 (10 items)** — Correctness bugfixes from 2026-04-24 review:
  fresh-install owner_id ordering, `scrape_history` fallback UPDATE
  removed, IGDB `themes` orphaned key removed, IGDB+TGDB
  `apply_metadata_to_game` COALESCE wrap, dashboard Resume 400s for 3
  job types, SIGTERM `cancelled` → `interrupted` for recovery banner,
  UTC datetime in bulk_scrape, `exc_info=True` in
  `handle_internal_error`, analytics cache invalidation gaps wired,
  TGDB `download_image` rename to disambiguate.  (v2.98.1)
- [x] **Pass 31 (9 items)** — Multi-user data ownership round 2: `user_id`
  on `psn_games` / `psn_trophies` (migration 007), `user_id` on
  `game_achievement_progress` + `steam_achievements` + `xbox_achievements`
  (migration 009), `user_id` on `collector_trophies` (migration 008),
  per-user Steam/PSN sync credentials, owner-scoped + role-gated PSN
  mutation endpoints, role-gated CLZ PDF import, `@editor_required` on
  `POST /game/<id>` write actions, `oauth_state_xbox` cleared across
  login boundary.  (v2.99.0)

### v3.x — Multi-user round 3, frontend defense, auth round 2, data integrity, a11y round 3

- [x] **Pass 32 (15 items)** — Input hardening round 2: filesystem-path
  validation in `api_update_paths`, per-key validators on
  `api_update_all_settings`, `api_restore` close-pool + delete-WAL/SHM,
  `clean_missing_roms` single-txn batched writes, `api_rename_rom` ROM-
  root jail, SSRF gate on `base_scraper.download_image` + media downloads,
  museum SSRF DNS-rebinding pin, CLZ PDF per-cell size cap, atomic
  image-pipeline writes + Pillow FD-leak fixes, format-vs-extension
  validation on image upload, consistent `safe_path` across media helpers,
  `api_games_bulk_edit` field names through `safe_column()`, escape
  user-controlled values in AI prompts, response-size caps on AI + RA
  HTTP, HTTP response hardening in metadata_merger image/video downloads.
  (v3.0.0)
- [x] **Pass 29 (5 items)** — Frontend defense in depth round 1: escape
  user-derived strings in `innerHTML` sinks, CSRF token propagation in
  `API.post` / `API.postForm` (lands with Pass 24 backend CSRF
  middleware), consolidate duplicate keyboard handlers + enforce
  focus-trap stacking, `try/catch` around `JSON.parse` of `localStorage`,
  `AbortController` on search-style API calls.  (v3.1.0)
- [x] **Pass 33 (11 items)** — Auth & session hardening round 2: `ProxyFix`
  env-gated, `safe_filename` on avatar upload, length-check `new_password`
  in `api_update_user`, force password change after admin reset, session
  rotation on password change, full `session.clear()` on logout, require
  Pillow for avatar upload, surface new CSRF token in login response,
  rate-limiter cleanup efficiency, `SecretRedactor` dict/bytes args,
  redact credentials in scraper INFO logs.  (v3.2.0)
- [x] **Pass 34 (7 items)** — Response envelope + observability round 2:
  `app.py` routes via `@handle_api_errors` + `success()` / `error()`,
  `inject_config` cache scraper_settings.json by mtime, delete zombie
  log helpers, rate-limiter view-function lookup hard-fail, log-rollover
  on UTC boundary, `asset_url` double-registration fix, observability on
  mutations in game routes.  (v3.2.0)
- [x] **Pass 35 (5 items)** — Data integrity & backup hardening: backup
  destination `chmod 0o600` + fsync file + parent dir, `atomic_write_json`
  fsync parent directory, `PRAGMA foreign_keys = ON` in migration
  connection, `journal_mode=WAL` / `journal_size_limit` moved to init,
  guard legacy `ensure_user_tables` ALTER blocks via
  `_add_column_if_missing`.  (v3.3.0)
- [x] **Pass 36 (10 items)** — Frontend defense in depth round 2: `escAttr`
  rewritten for JS-string context, escape system name + slug in
  `settings-page.js`, escape controller image filename in `museum.js`,
  escape log-viewer dynamic fields, migrate remaining
  `JSON.parse(localStorage.getItem(...))` sites, AbortController on
  `performGlobalSearch`, `DOM.create()` defaults to `textContent`,
  consolidate six document-level `keydown` handlers, `Storage.clearAll`
  prefix-list sync, notification container aria-live severity split.
  (v3.3.0)
- [x] **Pass 37 (7 items)** — Accessibility round 3: `<label for=>` on
  composite fields, focus trap on PSN trophies modals, reduced-motion
  kill-switch for canvas effects, `rel="noopener noreferrer"` on
  `target="_blank"`, heading hierarchy fixes, `aria-live` status regions
  on flash messages, promote hardcoded colors into variables.  (v3.4.0)
- [x] **Pass 40 (16 items)** — Tier-1 indie-review sweep (2026-04-24
  14-agent review): chdman_path RCE validator + admin gate (40.1),
  CHD convert/verify path traversal (40.2), archive-scanner m3u admin
  gate + per-entry safe_path (40.3), Steam achievements user-scoping
  IDOR (40.4), ETag cache-bleed user-id discriminator (40.5), players
  fill-only invariant + `normalize_players_value` (40.6), TGDB image
  download SSRF gate (40.7), museum job preserves failed status (40.8),
  ImageResizeJob persistence + lock discipline (40.9), shutdown-aware
  rate-limit sleeps across 5 jobs (40.10), CHD conversion atomic + verify
  wired (40.11), toast-controller XSS on system_name (40.12), showModal
  opt-in HTML via options.allowHtml (40.13), PSN trophy-detail
  game-link search XSS (40.14), `download_image` atomic + stale-clear
  race fix (40.15), `docs/PROXY-DEPLOY.md` authored for
  RETRODB_TRUST_PROXY trust contract (40.16).  (v3.4.1 — v3.5.0)
- [x] **Pass 41.1 (3 items)** — Tier-2 auth hygiene: `login_required`
  5-name allow-list bypass dropped, `api_change_password` rate bucket
  re-keyed to `(ip, user_id)` (isolated from `/api/login` and per-user),
  `count_stale_password_hashes()` startup sweep with `logger.warning`
  for active users below the OWASP PBKDF2 floor.  (v3.5.1)
- [x] **Pass 44 (multi-emulator launch — MAJOR FEATURE, 20 sub-tasks)** —
  ▶ Play button on game detail launches games via the right emulator
  (RetroArch with the right core for libretro platforms, DuckStation /
  PCSX2 / RPCS3 / Dolphin / mGBA / melonDS / Citra / PPSSPP / Cemu /
  ScummVM / MAME for standalones).  Schema: migration 010 +
  `emulators` / `system_emulators` tables + 12 emulator + 25 system-mapping
  seed.  New `Player` role + `launch` / `track_progress` permissions.
  Service layer: `services/launcher/` Protocol + LocalLauncher (Popen,
  TERM/KILL escalation, stderr tail) + ProcessRegistry (in-memory, GC TTL).
  `services/launch_resolver.py` turns game_id into argv via
  per-game-override → system-default → fallback chain, RA-special-cased
  for binary + cores dir, token-wise template substitution (no shell
  injection), ROM-path scan-root validation.  Routes: `routes/launch.py`
  (4 endpoints), `routes/emulators.py` (registry CRUD + admin page at
  `/settings/emulators`), `routes/launch_settings.py`
  (`/api/settings/retroarch/detect` probe).  UI: Play button (Jinja
  `has_perm`-gated), Launch section in edit-game modal, Settings →
  Emulators admin page (cyberpunk-themed), floating "now playing"
  indicator with kill popover.  94 new tests across 12 files (607 total,
  was 513).  (v3.6.0)

### v3.5.x — Tier-2 hardening + indie-review-2026-04-25 + refactor wave + CI hardening

The v3.5 line landed the bulk of Pass 41 (tier-2 hardening), Pass 45
(indie-review 2026-04-25 — 20 sub-items), Pass 38/42 (refactor +
consolidation waves), Pass 39 (CI/CD hardening round 2), Pass 46.1/46.2
(vendor third-party assets + pip pin refresh), and partials of Pass
43 (i18n) and Pass 47 (open-source flip prep). Per-version detail is
in `data/changelog.yaml`; per-pass detail is in the Active section of
this file. Each landed-in-v3.5.x pass is annotated with the version
in its **Status** line; `grep "done (v3.5" roadmap.md` enumerates all.

- [x] **Pass 41.2–41.14** — Tier-2 hardening across all 14 subsystems
  (auth, database, app bootstrap, scraper orchestration, scraper
  adapters, jobs, OAuth/trophy parser, achievements/trophies, game
  routes, settings/maintenance/tools, museum, frontend JS, templates
  /a11y, image/media).  See Pass 41.1–41.14 entries above and
  `tests/test_pass41_security.py`.  (v3.5.1 – v3.5.14)
- [x] **Pass 45.1–45.20** — Indie-review 2026-04-25 sweep (post-Pass-41
  cross-cutting themes T1–T14).  See Pass 45.x entries above; tests
  at `tests/test_pass45_security.py`.  (v3.5.15 – v3.5.33)
- [x] **Pass 46.1 + 46.2 + 46.3 part 1** — Vendor Chart.js + 17 WOFF2
  + pip pin refresh (6 packages) + PyInstaller spec scaffolding.  See
  Pass 46.x entries; tests at `tests/test_pass46_*`.  (v3.5.35 –
  v3.5.39)
- [x] **Pass 38 + Pass 42 refactor waves** — `apply_hybrid_metadata`
  partial extraction, scraper-settings consolidation, `installer_core.py`
  extraction, Jinja-macro extraction, removed `app.bundle.js` from
  installers, dead-code sweep, migration-helper dedup, global window
  error/unhandledrejection handler, RA 401 observability, settings.html
  split deferred.  See Pass 38.x / 42.x entries.  (v3.5.41 – v3.5.65)
- [x] **Pass 39.1–39.12** — CI/CD hardening round 2: SHA-pin actions,
  explicit `permissions:`, hard-fail pip-audit + semgrep, hash-locked
  `requirements.lock`, Dependabot lockfile regen workflow,
  env-configurable `STAGING_DIR`, multidisc-scan rate limit, gitleaks
  allowlist for test fixtures, `usedforsecurity=False` MD5/SHA1,
  gitleaks regex allowlist for Claude model literals, re-pin notes,
  Dependabot label scaffolding.  (v3.5.40 / 2026-05-02 dated entries)
- [x] **Pass 47 partials** — Pre-publish hygiene sweep + repo
  visibility flip prep (Pass 47.1–47.2 in flight as of v3.6.x).

### v3.6.x — Multi-emulator launch + test-suite audits + dependency bumps + small fixes

- [x] **Pass 44** — Multi-emulator launch (see entry above).  (v3.6.0)
- [x] **Test-suite audits + hot-fixes + UX fixes + bonus stats opt-in
  + project-path migration follow-through + AMD ROCm helper script**
  — three test-suite audit fix-passes resolving 119 + 100 + 133 raw
  findings (v3.6.8 / v3.6.9 / v3.6.14); two hot-fixes (HLTB endpoint
  `/api/find`→`/api/bleed`, scan 4xx when `rom_path` unset) (v3.6.10–
  v3.6.11); UX fix-pass (v3.6.12); CLAUDE.md staged-tree workflow
  note (between v3.6.13 and v3.6.14); dependency bumps (requests /
  onnxruntime / numpy) (v3.6.13).  See `data/changelog.yaml` for
  per-version detail.  (v3.6.1 – v3.6.14)
- [x] **Pass 47.1** — pre-publish hygiene sweep: gitleaks-all clean
  (0 leaks / 203 commits); every excluded path `git log --all` empty;
  one stray Inkscape host-path stripped from `static/images/systems/cps.svg`;
  `SECURITY.md` authored; `.github/ISSUE_TEMPLATE/` + `PULL_REQUEST_TEMPLATE.md`
  authored; README adds a Status line and a Support-development section
  pointing at GitHub Sponsors. Items 7-screenshots and 8-repo-metadata
  deferred to a maintainer-curation step and Pass 47.2 respectively.
  (v3.6.15)
- [x] **Pass 38.4** — Jinja macros + select-filter modal partial:
  `_macros/breadcrumb.html` (`breadcrumb(items)`; 11 templates
  converted), `_macros/sticky_subnav.html` (`tab_subnav` /
  `subnav_link`; all 6 settings subnav blocks converted),
  `_modals/select_filter_modal.html` ({% include %} partial for
  `all_games.html` + `system_games.html`). Pass 10 closed
  substantively. Suite 1015 → 1039 (+24). (v3.6.16)
- [x] **Pass 38.6** — Split `settings.html` by tab: six panels
  extracted into `_settings_tabs/{account,library,scraping,data,
  customization,system}.html`; shell shrank 7,368 → 5,201 lines.
  Three pre-existing source-grep tests widened via new helper
  `tests._util.read_settings_with_partials()`. Suite 1039 → 1084
  (+45). (v3.6.17)
- [x] **FU.2** — Grid-card boxart srcset: `boxart_dir_listing()`
  request-scoped scandir cache + `boxart_srcset(filename, existing=…)`
  batch mode (no per-card PIL width read); `build_game_card()` emits
  `boxart_srcset` / `boxart_3d_srcset`; `renderGameCard()` clears
  `srcset`/`sizes` in the 3D→2D `onerror` fallback. (v3.6.18)
- [x] **FU.3** — Bulk JPEG/PNG → WebP migration endpoint:
  `services/jobs/webp_migrate.py::WebPMigrateJob` (singleton
  `webp_migrate_job`); `POST /api/maintenance/convert-to-webp/
  {start,status,cancel}` in `routes/maintenance.py`. Worklist covers
  boxart / boxart_3d / fanart / screenshots; manuals + gifs skipped;
  pre-flight disk-space precheck (refuse if `free < 2 × in_scope_bytes`);
  resumes by adopting existing `.webp` siblings; wipes legacy
  `-sm.jpg` / `-md.png` and re-runs `_make_responsive_variants`
  after each conversion. (v3.6.19)
- [x] **FU.1 phase A** — CSP enforcing prep: every inline `onclick=`
  on dialog controls migrated to event-bound listeners + `csp_nonce`
  wired through `base.html`. Phase B (flip CSP to enforcing mode) and
  Phase C (remove `unsafe-inline`/`unsafe-eval`) still active. (v3.6.20)

---

<a id="scope-notes--considered-and-dropped"></a>

## Scope notes — considered and dropped

The following were considered during this planning round and intentionally
not added to the roadmap. Document here so they don't keep re-appearing.

- **Flask-Talisman**: replaces 4-8 lines of manual header setting with a
  dependency. Not worth it.
- **Flask-Migrate / Alembic**: requires SQLAlchemy adoption, which RetroDB
  explicitly doesn't use (raw SQL is part of the design). Pass 20 uses the
  suckless PRAGMA-user_version pattern instead.
- **Progressive Web App / service worker**: no offline story for a
  localhost ROM manager. Adds maintenance burden for zero user benefit.
- **Docker image / container**: `setup.sh` + `install_gui.py` already
  target bare-metal installs. A container would add a distribution surface
  without simplifying anything for current users.
- **API versioning / OpenAPI spec**: API is internal to the app. No
  external consumers to break.
- **Feature flags**: single-user app — no gradual rollouts needed.
- **Python 3.13 free-threaded build**: research confirmed single-threaded
  Flask perf regresses 30-50% in free-threaded mode. Actively avoid — pin
  to the GIL build.
- **Sentry / error tracking SaaS**: exfiltrates stack traces and request
  context to a third party. Local log files are the right place for a
  self-hosted app. Covered by Pass 17.3 instead.
- **Prometheus `/metrics`**: no scraper. Local `/health` + `/ready`
  (Pass 17.1) covers the actual need.
- **Distribution / portfolio website** (per-user landing page hosting
  RetroDB and the user's other apps with download links + donation
  CTAs): a separate, multi-app effort outside RetroDB itself. Tracked
  at the user's portfolio level, not in this roadmap. Pass 47 covers
  donation surfacing inside the RetroDB repo + app — the landing site
  comes later, host TBD (Cloudflare Pages / Netlify / GitHub Pages /
  Vercel are all viable for a static multi-app site). Mentioned here
  so the Pass 47 scope stays sharp and the website doesn't get
  retrofitted into a RetroDB-shaped pass.

---

## Audit hygiene

The 2026-04-21 ants-audit run produced 228 raw findings with only ~3
actionable (~1.3% signal rate).  The remediation belongs on the
**audit-tool side**, not in this project — it's about teaching the
audit tool to respect calibration files that already exist here
(`.semgrep.yml`, `pyproject.toml`'s ruff S-code ignores, `.gitleaks.toml`).

Those recommendations are captured in a standalone document intended
for the Claude Code session maintaining the `/audit` skill:
**`audit_hygiene.md`** (repo root).  That file is portable — it can be
handed to the audit-tool maintainer without any RetroDB-specific
context.

---

<a id="periodic-independent-review"></a>

## Periodic Independent Review

The 2026-04-23 multi-agent sweep that surfaced Passes 23-29 is the
counterweight to the "author marks own homework" problem: an agent that
wrote the code can't write tests that meaningfully vet it, because the
tests encode the same (possibly wrong) understanding.  Dispatching
multiple independent agents — each seeing only a subsystem's code + the
project docs, *not* seeing the orchestrator's prior reasoning — produces
fresh-eyes findings at full-codebase scale.

### Cadence

Re-run the multi-agent sweep:

1. **Every 5 landed passes**, or
2. **Before any minor version bump** (`x.N+1.0`), or
3. **After an architectural change** that touches >3 subsystems
   (migration, auth model change, DB schema reshape).

Whichever comes first.

### How to run

The 14-subsystem partition that produced this audit is:

1. **Auth & security** — `services/auth.py`, `services/security.py`, `services/log_redactor.py`, `routes/auth.py`
2. **Database & schema** — `services/database.py`, `database_init.py`
3. **Scraper orchestration & metadata** — `scraper/scraper_manager.py`, `hybrid_scraper.py`, `metadata_merger.py`, `metadata_normalizer.py`, `match_scorer.py`, `title_normalizer.py`, `scraper_cache.py`, `image_dedup.py`, `services/game_metadata_service.py`
4. **Per-source scrapers** — `scraper/base_scraper.py`, `scrape_igdb.py`, `scrape_thegamesdb.py`, `scrape_rawg.py`, `scrape_screenscraper.py`, `scrape_esde.py`, `scrape_ai.py`, `retroachievements.py`
5. **Platform imports** — `routes/platform_import.py`, `steam_achievements.py`, `xbox_achievements.py`, `game_imports.py`, `scraper/scrape_steam.py`, `scrape_xbox.py`
6. **Image pipeline** — `services/image_utils.py`, `jobs/image_resize.py`, `game_media_service.py`, `media_cleanup.py`
7. **Background jobs** — `services/jobs/*`
8. **Game routes & detail/edit** — `routes/games*.py`, `services/game_query.py`, `hltb_service.py`
9. **Maintenance, settings, systems, reports** — `routes/{systems,maintenance,settings,scraper,bulk_scrape,controllers,reports}.py`, `services/{rom_scanner,game_cleanup,normalization}.py`
10. **Collections, achievements, trophies, museum** — `routes/{collections,achievements,trophies,collector_trophies,museum,ra_sync,bonus_discs,clz_import,scrape_logs,tools}.py`, `services/{wishlist_scraper,achievement_linking}.py`
11. **Core app & shared utilities** — `app.py`, `config.py`, `config.example.py`, `services/{api_helpers,template_filters,formatters,game_utils,analytics,assets}.py`
12. **Frontend JavaScript** — `static/js/*.js` (source files only, skip bundles)
13. **Templates & CSS** — `templates/**/*.html`, `static/css/**/*.css`
14. **Tests, tooling, CI/CD** — `tests/`, `build_*.py`, `install*.py`, `scripts/`, `pyproject.toml`, `.semgrep.yml`, `.gitleaks.toml`, `.pre-commit-config.yaml`, `.github/workflows/*`

Each agent gets the same brief, scoped to its subsystem:

> You are performing an INDEPENDENT code review of ONE subsystem of RetroDB.
> Project root: `/mnt/Games/Scripts/Linux/RetroDB`.  You do not know what
> the orchestrator thinks about this code.  Fresh eyes.
>
> **Scope:** `<paths>` — review ONLY these files.
>
> **References (treat CLAUDE.md module descriptions as AUTHOR'S CLAIMS, verify against code):**
> `CLAUDE.md`, `docs/RETRODB_DESIGN_STANDARDS.md`, `docs/STANDARDS_ADDENDUM.md`,
> `docs/ROM_NAMING_STANDARD.md` (if your subsystem touches ROM paths).
>
> Answer three questions, with `file:line` refs mandatory on every finding:
> 1. **Spec alignment** — where does code diverge from docs/CLAUDE.md claims?
> 2. **Weaknesses** — fragile code, hidden assumptions, race conditions,
>    resource leaks, injection / SSRF / a11y risks, perf traps, surprising
>    behavior.
> 3. **Gaps** — features/edge cases the spec implies but code doesn't handle.
>
> Rules: stay in scope; don't read tests or git log to infer intent; no
> aesthetic refactors; if clean, say so — don't invent findings.
>
> Output: `## Subsystem: <name>` header, three numbered sections, summary
> with top-3 priorities. Target 300-600 words.

Dispatch all 14 in parallel (single message, 14 Agent tool calls).

### Triage rules

- Any **CRITICAL runtime bug** across two or more reports → land as the
  next pass.
- **Security findings** → weight against the "single-user localhost"
  threat model documented below; HIGH on SaaS ≠ HIGH here.
- **Consistent drift between CLAUDE.md and code** → either fix the code
  or fix the doc; don't let the claim stand unverified.
- **Findings already on the roadmap** → skip (acknowledge + link to the
  existing pass, don't duplicate).

The resulting triage lives as new numbered passes inserted before the
follow-ups section (see Passes 23-29 for a worked example).

---

## Notes

- Refactor passes that touch `services/*.py` or `scraper/*.py` must run
  `python3 -m pytest` (per CLAUDE.md workflow rule #4).
- Each pass should be its own patch version bump + changelog entry — they
  are behaviour-preserving by design, so `x.y.Z+1` is appropriate.
- Update this file (tick items, add notes) as work lands.
- **Severity calibration** for security items uses the single-user
  localhost threat model documented in `.semgrep.yml`.  Items that would
  be HIGH on a public-facing SaaS (e.g. CSRF, cookie flags) are LOW here;
  see §22 of the design standards doc.
- **Online sources** cited in specific passes are captured at time of
  writing (2026-04-21).  If >6 months old when you pick up the work,
  re-check OWASP / CVE databases for newer guidance.
