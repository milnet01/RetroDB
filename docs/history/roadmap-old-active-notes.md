# Roadmap: the old "Active" section notes

Moved here word for word from `roadmap.md` on 2026-11-10 (PASS-59-272), when the open work was regrouped into version blocks. Every item that sat under these headings is now in a version block in [`roadmap.md`](../../roadmap.md); only the section notes and sweep reports remain here.

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
  - *Resolved (2026-08-06)*: dropped from the spec — `controllers/` was
    removed from `retrodb.spec` in v3.6.29 (`38d0940`), so neither shape
    ships it. The `build_dist.py` cite has also drifted:
    `INCLUDE_IMAGE_DIRS` is now at `build_dist.py:91`. (Pass 57.10)
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

### Pass 56 — Language expansion: eleven new locales (2026-07-05)

> Source: user request 2026-07-05 — "since I am South African, please add these
> languages: Afrikaans, Zulu, Xhosa … also Dutch, Norwegian, Russian … Polish,
> Turkish, Ukrainian, Indonesian … and languages used in Israel (Hebrew)."

### Pass 55 — Scraper throughput (2026-07-05)

> Source: user request 2026-07-05 — "are there any performance improvements that
> can be made to scraping?" Per-game latency is dominated by external API
> round-trips; an Explore-agent map of `scraper/` found the code made that worse
> than necessary (sequential source queries, per-image TCP+TLS handshakes).

### Pass 54 — Media integrity & DB maintenance (2026-07-04)

> Source: user session 2026-07-04, during investigation of an external, recurring
> mass-deletion of scraped game media (boxart / boxart_3d / screenshots / fanart /
> manuals) that occurs while RetroDB is NOT running. Root cause is external to
> RetroDB (disk healthy — SMART pass, no ext4 / I/O errors, empty lost+found, fs
> clean; RetroDB has no automatic media-delete code path). A fatrace + inotify
> trap was installed to identify the deleter. These items harden RetroDB so it
> stops AMPLIFYING such external loss and give the user a controlled cleanup tool.
> CAUTION: do NOT run any ref-clearing bulk action until the external deleter is
> identified and stopped — clearing refs erases the record of what art each game
> had, which is what's needed to know what to re-scrape / re-link.

### Pass 53 — Interface UX review (2026-07-03)

> Source: user-requested interface/usability review 2026-07-03. Code-grounded,
> not a live walkthrough — the login-gated app was not running and the browser
> extension was unavailable, so findings were surveyed across `templates/base.html`
> (nav/chrome), `all_games.html` + `static/js/all-games-controller.js` (browsing),
> the game detail/edit modals, `settings.html` + `_settings_tabs/*`,
> `rom_tools_hub.html`, and the toast / modal / empty-state layer. The
> design-token system, icon+text nav, and a11y work (aria-live, focus traps,
> aria-current) were confirmed already solid; these items target findability,
> flow, and first-run. Prioritised T1 (biggest flow wins) → T4
> (consistency/polish). A live visual pass (desktop + ~375px mobile) is still
> owed once the app is running and the browser extension is connected.

### Pass 52 — Post-v3.14.0 UX & i18n polish (2026-07-01)

> Source: in-session review 2026-07-01, immediately after the v3.14.0 Chinese
> localization ship. Three improvements surfaced while surveying the app; each
> was verified against the code so none duplicates existing/rejected scope
> (reduced-motion, backup/restore, and core a11y were checked and already exist).

### Pass 51 — Chinese localization + China game-rating system (2026-06-30)

> Source: user request 2026-06-30 — add Chinese (Mandarin + Cantonese) UI
> languages and, if China has a ratings board, gather its icons + info. Roadmapped
> for later, not yet started.

### Pass 50 — PSN authentication simplification (2026-06-30)

> Source: user request 2026-06-30 — "simplify the PSN NSO token required for
> syncing trophies and the PSN library." Hard constraint: Sony exposes no
> official public trophy/library API, so the NPSSO cookie is unavoidable (it is
> what PSNAWP and every community PSN tool use). These items can't remove it but
> they make the user touch it **far less often** and more smoothly. Current flow
> mapped: NPSSO pasted via a 3-step wizard (`templates/_settings_tabs/account.html:
> 111-185`) → PSNAWP derives an access/refresh/id bundle (~2-month refresh
> token, stored per-user in `user_platform_tokens`) → on-demand refresh only when
> a sync runs (`routes/trophies.py:100-157`). Pain: every ~2 months (or sooner if
> the NPSSO goes stale) the user must redo the whole browser copy-paste wizard.

### Pass 49 — audit + indie-review 2026-06-30 (fix-pass + deferrals)

> Source: `/audit` (static analysis) + `/indie-review` (14-subsystem cold
> review) run at v3.12.0. Static analysis was clean (ruff / semgrep / gitleaks /
> pip-audit all green; 97 bandit + 132 mypy findings triaged to false-positives,
> logged to `.ants_review_falsepos.jsonl`). The semantic sweep surfaced one
> **CRITICAL** fresh-install schema gap plus a tier of HIGH/MEDIUM fixes — all
> verified and **landed in v3.12.1** — and the deferred tail below, calibrated to
> the single-household-LAN threat model.

**Landed in v3.12.1** (do not re-open; the cold re-read is the verification):
- **CRITICAL — fresh-install schema backfill** (migration 013). A truly fresh
  install (`init_database()` runs migrations 001..012 only) built a `games`
  table missing 12 columns (`critic_score`/`user_score`/`has_retroachievements`/
  `ra_game_id`/`ra_achievement_count`/`ra_points`/`campaign`/`game_structure`/
  `edition`/`other_platforms` + the two `*_count`s), a `systems` table missing
  `system_type`/`default_controller_id`, and the `controllers` /
  `system_controllers` / `psn_sync_status` tables entirely — they existed only
  on the maintainer's legacy DB. Card-data (main library view), scraping, and
  PSN sync 500'd on a clean install. Found only once the test suite was isolated
  onto a fresh throwaway DB (see below). Migration 013 ensures all of them
  idempotently; regression-pinned by `tests/test_fresh_install_schema.py`.
- **HIGH** SSRF DNS-rebinding pin connected to port 0 (`services/ssrf.py`) — the
  pin was a no-op that only "worked" via connection-pool reuse and hung on a
  cold pool; now echoes the real port.
- **HIGH** `ra_sync` / `platform_sync` batched-commit rollback discarded a prior
  game's already-counted writes → per-game commit.
- **HIGH** `game_cleanup.clear_scraped_data` deleted image files before nulling
  DB columns → reordered (null first), no dangling refs on failure.
- **HIGH** `pytest` (and the `ci_local.sh` pre-push gate) ran migrations +
  seeder against the real `database/roms.db` → `tests/conftest.py` now points
  `RETRODB_DB_PATH` at a throwaway DB.
- **MEDIUM** bare `request.get_json()` on 9 POST endpoints (auth ×4, platform
  imports ×3, games_media ×2) 500'd on empty/non-JSON bodies → `silent=True or {}`.
- **MEDIUM** `atomic_write_json` static `.tmp` suffix (torn-write race) → routed
  through `atomic_write_text`/`mkstemp`.
- **MEDIUM** IGDB `comp['company']['name']` unguarded discarded the whole IGDB
  apply on an unexpanded company → shape-guarded.
- **MEDIUM** raw `{{ name }}` into JS string literals on 8 template sites (a `"`
  or `</script>` in a system/ROM name hard-broke the page) → `|tojson`.
- **LOW** `/api/games` pagination `page` floored at 1.
- **MEDIUM (Loop-2)** PSN trophy-sync upsert used a bare `ON CONFLICT(user_id)`
  against the **partial** `idx_psn_sync_status_user_id` index
  (`WHERE user_id IS NOT NULL`), which SQLite refuses — the first PSN full-sync
  500'd on every install (fresh AND the legacy DB, both carry the partial
  index). Conflict target now names the partial predicate
  (`routes/trophies.py`); pinned by `tests/test_fresh_install_schema.py`.
- **Loop-2 cleanup** removed the now-dead `_pending_commits` flush machinery the
  per-game-commit fix orphaned (`ra_sync`/`platform_sync`); migration 013 now
  imports the strict `_add_column_if_missing` from `_helpers` (spec §10/§11)
  instead of an error-swallowing inline copy.

> **Loop-2 cold re-review** (DB/migrations, jobs, SSRF — briefed cold, no mention
> of the fixes): the port-0 SSRF fix, the per-game-commit fix, migration 013
> (idempotency + completeness), and the atomic_write_json refactor were all
> independently confirmed to hold. The deferred 49.x items below were re-raised
> or newly surfaced and remain open.

### Pass 48 — audit + indie-review fix-pass deferrals (2026-06-05)

> Source: `/audit` (static analysis) + `/indie-review` (14-subsystem cold
> review) run at v3.6.28. The bulk of findings landed directly in v3.6.29
> (see changelog). These are the items deliberately deferred — design
> decisions, risk-of-regression LOWs, and INFO-grade notes — calibrated to the
> single-user-localhost threat model. False positives logged to
> `.ants_review_falsepos.jsonl` (incl. the `get_db()`-vs-`g.db` mis-read).

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

### Pass 46 — vendor third-party assets / distribution self-containment (2026-04-27)

> User-requested track: drop runtime CDN dependencies (Chart.js, Google
> Fonts), refresh pinned pip versions within current ranges, and add a
> PyInstaller-based "no Python install needed" distribution alongside the
> existing source-zip distribution. Goal — let RetroDB run without
> reaching out to third-party CDNs and let end users pick between
> "needs Python" (small zip) and "self-contained" (bigger binary)
> distribution channels.

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

### Security & input hardening — Tier-1 (indie-review 2026-04-24)

> Sixteen findings from the 14-agent independent review post-Pass 37 that
> represent concrete exploit paths or silent-corruption vectors under routine
> use.  Each has an external anchor (OWASP, CWE, RFC, or prior-pass invariant)
> and a fix-sketch.  Land one-per-commit with red/green test pairs per the
> remediation workflow.

### Security & input hardening — Tier-2 (indie-review 2026-04-24)

> Forty-four HIGH findings after threat-model calibration.  Real
> correctness smells with concrete failure scenarios, but none carries
> a current-use exploit chain.  Group fixes by subsystem to minimise
> cross-cutting churn.

### CI/CD hardening round 2

> **Follows Pass 22.**  Action pinning, workflow permissions,
> `continue-on-error` discipline, lockfile hash verification,
> Dependabot lockfile regeneration.

### Refactoring & consolidation

> **Pass 38** — Rule-of-Three triggered on five areas surfaced by the
> 2026-04-24 sweep.  **Pass 42** — MEDIUM/LOW cross-cutting items
> from the indie-review that aren't urgent but should be scheduled
> before the next indie-review — opportunistically mergeable into
> feature PRs that touch adjacent code.

### Internationalization (i18n) — language packs

> **Pass 43** (proposed, deferred until Tier-1 + Tier-2 sweeps are done).
> Ship-shape RetroDB in any language; UI strings translated, retro-game
> data (titles, descriptions, scraper output) deliberately untranslated
> because that's content, not chrome.

### Follow-ups from landed passes

Small, well-scoped items that surfaced while finishing an earlier pass but
weren't worth blocking the ship on.  Ordered by rough priority.

### Pass 59 — audit + indie-review 2026-09-01 (deferrals)

Deferrals from the 2026-09-01 sweep: `check-code` whole-tree, then
`review-code` over 18 hand-built lanes (the partition verb omitted `app.py`,
all JS, all templates and all shell — see Pass 58.1). 11 CRITICAL, 37 HIGH,
54 MEDIUM. Fixed in that pass and NOT listed here: the `retrodb.spec`
credential leak (`a5e0939`), the 14 workflow-security findings (`f29409b`)
and the ten authorization-boundary findings incl. Pass 49.5 (`2836bc3`).

Every bullet below was verified against source by the lane that raised it;
the ones marked **re-verified** were additionally reproduced by the
orchestrator, several by execution rather than reading.

