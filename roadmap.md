# RetroDB Roadmap

Tracking file for refactoring, security, performance, and quality work
identified in successive reviews (2026-04-21 onwards). Items are ordered so
that earlier passes establish the patterns used by later ones (service-layer
carve-outs, response helpers, etc.).

Scope covers: refactoring (Passes 2-10), security (Pass 11, 16), database
performance (Pass 12), frontend performance (Pass 13, 18, 22), developer
efficiency and tests (Pass 14, 20), accessibility (Pass 15), observability
(Pass 17), schema migrations (Pass 19), and operational resilience (Pass 21).
See "Scope notes" near the bottom for items deliberately excluded.

Each item lists:
- **Target** — file(s) and approximate line range / LOC
- **Why** — the specific issue (oversized function, duplicated logic, mixed
  concerns, long conditional chain)
- **Plan** — concrete extraction target: new file, class/function name, what
  moves where
- **Est. reduction** — rough LOC delta in the source file
- **Status** — `todo` / `in-progress` / `done`

Unchecked items should be tackled in the suggested order unless a user-facing
change forces a different sequence.

---

## Done

- [x] **Shared `@handle_api_errors` decorator** — `services/api_helpers.py`
  added; applied to all 12 handlers in `routes/games_hltb.py`. Also started
  logging with `exc_info=True` so 500s now carry stack traces. (v2.83.2)
- [x] **Consolidated `get_user_ra_credentials()`** — moved to
  `services/auth.py`; the dead duplicate in `routes/trophies.py` was removed
  and `routes/achievements.py` now imports from the service module. (v2.83.2)
- [x] **Consolidated PSN trophy image downloader** — `routes/trophies.py` now
  re-exports `_download_psn_trophy_image` from `services.jobs.base` under the
  `download_psn_trophy_image` name, so call sites are unchanged but the body
  is no longer duplicated. (v2.83.2)
- [x] **Pass 2 — `@handle_api_errors` sweep across routes/** — Applied to 118
  handlers across 20 files (155 raw `'An internal error occurred'` hits → 37
  remaining, all intentional HTTP-200 responses or non-standard payload
  shapes). Files fully swept: `achievements`, `auth`, `bulk_scrape`,
  `clz_import`, `collections`, `collector_trophies`, `controllers`,
  `maintenance`, `games_ai`, `games_media`, `games_search`, `ra_sync`,
  `reports`, `tools`. Partial: `bonus_discs` (8/10), `games` (6/9),
  `scraper` (2/5), `scrape_logs` (1/5), `settings` (5/13), `systems` (6/8).
  Skipped entirely: `platform_import`, `steam_achievements`,
  `xbox_achievements`, `trophies` — all use HTTP-200 responses. Specific
  exception handlers (`ValueError`, `sqlite3.IntegrityError`, `ImportError`,
  `PermissionError`, `OSError`, `json.JSONDecodeError`) preserved; all
  `try/finally` cleanup blocks preserved. (v2.83.5)
- [x] **Pass 2 — response-builder helpers (`success()` / `error()`)** —
  `services/api_helpers.py` now exports `success(data=None, **extra)` and
  `error(message, code=400, **extra)`. First migration wave: 56 sites across
  7 fully-swept routes (`games_ai`, `collector_trophies`, `bulk_scrape`,
  `ra_sync`, `clz_import`, `games_media`, `games_search`). Wire format
  preserved exactly; HTTP-200-with-`success:False` handlers now pass
  `code=200` explicitly. (v2.83.6)
- [x] **Pass 2 — second migration wave across remaining fully-swept routes** —
  Migrated ~130 sites across `controllers`, `maintenance`, `achievements`,
  `reports`, `auth`, `tools`, and `collections`. Scanner-result / job-status
  / task-dict passthroughs preserved as raw `jsonify` (correct shape, no
  `success` key). Combined Pass 2 total: **186 sites across 14 routes**.
  (v2.83.7)
- [x] **Pass 3 — HLTB service extraction** — Split
  `routes/games_hltb.py` (366 LOC) into a 165-LOC route layer plus a new
  `services/hltb_service.py` with three classes (`HLTBLookup`,
  `HLTBPendingQueue`, `HLTBBulkOrchestrator`). Typed error surface:
  service raises `HLTBError` subclasses carrying HTTP status codes;
  routes catch and map to `error()`. `routes/games_hltb.py` also
  migrated its 10 `jsonify` sites to `success()` / `error()` in the
  same pass (Pass 2 carry-over). Wire format preserved; all 124
  tests pass. (v2.83.8)
- [x] **Pass 4 — `routes/maintenance.py` split** — Carved the 693-LOC
  blueprint into a 254-LOC route layer (−63%) plus three focused service
  modules: `services/rom_scanner.py` (128 LOC, inline-fallback scanner),
  `services/media_cleanup.py` (185 LOC, per-game media delete +
  orphan detection), `services/game_cleanup.py` (154 LOC, missing-ROM
  cleanup, CLZ-import purge, scraped-data reset). Used module-level
  functions rather than the roadmap's suggested classes — simpler and
  matches `game_query.py` / `analytics.py` idiom (the Pass 3 class
  approach was motivated by typed errors, which these simpler helpers
  don't need). The six near-duplicate per-field delete blocks inside
  `delete_game_images()` now run off a single `_MEDIA_LAYOUT` table.
  Wire format preserved exactly; all 124 tests pass. (v2.83.10)
- [x] **Pass 5 — `scraper/metadata_merger.py` split** — Extracted two
  helper modules, shrinking the merger from 1293 → 1090 LOC (−16%):
  `scraper/image_dedup.py` (99 LOC, dHash + post-download dedup helper
  `keep_screenshot_if_unique`) and `scraper/metadata_normalizer.py`
  (158 LOC, `normalize_title` / `normalize_esrb_rating` / `alt_title_entry`
  / `merge_alt_titles`). The four near-identical screenshot post-
  download dedup blocks (TGDB / IGDB / RAWG / ScreenScraper) now call
  `keep_screenshot_if_unique()`. ScreenScraper ESRB branch replaced its
  inline if/elif chain with `normalize_esrb_rating()`, which also picks
  up the legacy KA → E mapping for free. Fell short of the roadmap's
  ~700-LOC reduction target: collapsing the `apply_*` functions to
  ~100 LOC each would require normalising across different per-source
  response shapes (TGDB uses its own downloader, IGDB needs URL
  transforms, SS has two URL sources), which belongs in a dedicated
  later pass rather than this one. Callers updated
  (`hybrid_scraper.py`, `alt_titles_backfill.py`, tests); three dead
  imports in `hybrid_scraper.py` also dropped. All 124 tests pass.
  (v2.83.11)
- [x] **Pass 6 — `scraper/scraper_manager.py` split** — Carved the 1022-LOC
  manager into a 684-LOC orchestrator (−33%) plus three focused modules:
  `scraper/match_scorer.py` (207 LOC, pure scoring — `calculate_title_match_score`,
  `word_order_bonus`, and four per-source calculators `calculate_ss_score` /
  `calculate_tgdb_score` / `calculate_igdb_score` / `calculate_rawg_score`),
  `scraper/title_normalizer.py` (100 LOC, `strip_title_noise` and
  `normalize_for_matching` with module-level compiled regexes instead of
  re-compiled inline patterns), `scraper/scraper_cache.py` (48 LOC,
  thread-safe TTL-backed ScreenScraper result cache). Module-level
  functions rather than the roadmap's suggested `MatchScorer` /
  `TitleNormalizer` / `ScraperCache` classes — same reasoning as Pass 4:
  matches `game_query.py` / `analytics.py` idiom, and scoring is
  fundamentally stateless so `self` was never load-bearing. The 80-line
  inline ScreenScraper result-parsing block inside `search_games()` also
  flattened to `_parse_ss_result()` + `_pick_ss_region()` static helpers
  so the orchestrator reads as "for each source: search → score →
  extend". `scraper_manager.py` re-exports cache + scoring helpers so
  every existing caller (`routes/bulk_scrape.py`, `routes/games.py`,
  `scraper/hybrid_scraper.py`, `services/wishlist_scraper.py`,
  `services/jobs/*`) is unchanged. All 124 tests pass. (v2.83.12)
- [x] **Pass 12 (partial) — Database performance** — Four-item sweep
  across the SQLite layer, landed as v2.84.1.
    - **12.1** Long-lived `PRAGMA optimize=0x10002` on background-job
      connections. `services/jobs/base.py::_get_conn()` now sets the
      0x10002 mask on open so per-table stats accumulate; a later
      `PRAGMA optimize` (no args) uses those stats to ANALYZE stale
      tables. Per-request teardown already ran `PRAGMA optimize` in
      Pass 11; this closes the gap for job threads. Graceful fallthrough
      on older SQLite builds.
    - **12.2** Batched job progress persistence. `persist_job_progress`
      gained an optional `conn=` kwarg; `services/jobs/bulk_scrape.py`
      opens a long-lived `_progress_conn` at job start, reuses it for
      every in-loop progress tick (eliminates ~100 conn open/PRAGMA
      cycles per 1000-game scrape), closes it in both success and
      exception branches, runs `PRAGMA optimize` periodically so the
      0x10002-collected stats actually get applied.
    - **12.3** Already-landed in v2.84.0 — `database_init.py` runs
      `PRAGMA optimize` after `CREATE INDEX` loop. Noted here for
      completeness.
    - **12.4** Slow-query logging gated by new
      `RETRODB_SLOW_QUERY_MS` env var (default 0 = disabled).
      `services/database.py` wraps `query()` / `execute()` /
      `execute_many()` with `perf_counter` deltas; threshold-exceed
      cases log WARNING with whitespace-compacted + 500-char-truncated
      SQL and arg count (values themselves stay out of the log to avoid
      PII leaks). 6 tests added in `tests/test_slow_query_log.py`.
    - **12.5 (deferred)** FTS5 virtual table — L-sized; gated on a
      benchmark run to confirm `WHERE title LIKE '%q%'` actually is the
      hot path on realistic 10k-row libraries. Pushed to a later pass.
    Net: 140 tests pass (was 134); 6 new tests; smoke-import clean.
    (v2.84.1)
- [x] **Pass 11 — Security hardening** — Seven-item security sweep
  landed as one patch (v2.84.0).
    - **11.1** PBKDF2-SHA256 iteration count bumped 100,000 → 600,000
      (OWASP 2026 floor). Hash format migrated from `<salt>:<hash>` to
      `pbkdf2:<iters>:<salt>:<hash>` so future iteration bumps don't
      need another format change. Legacy hashes stay verifiable; they
      transparently upgrade on next successful login via new
      `needs_rehash()` helper + rehash branch in
      `routes/auth.py::api_login`. 8 tests added in
      `tests/test_auth_hashing.py`.
    - **11.2** `SESSION_COOKIE_SECURE` env-gated via
      `RETRODB_SECURE_COOKIES` (default off). Localhost HTTP deploys
      keep working; operators fronting with TLS flip the env var.
    - **11.3** Image upload magic-byte validation via
      `PIL.Image.verify()` in `services/game_media_service.py::
      save_upload` + `save_screenshots` + `routes/auth.py::
      api_upload_avatar`. Per-file 10 MB ceiling
      (`MAX_IMAGE_SIZE`) inside the global 16 MB cap.
    - **11.4** Rate limits extended to heavy admin endpoints
      (`api_restart` 2/min; `api_scan`, `api_database_optimize`,
      `api_image_resize_start`, `api_backup` 3/min). Latent bug
      fix: pre-existing AI Fill + bulk-scrape limiters pointed at
      stale endpoint names (`games.api_game_ai_fill` →
      `games_ai.api_game_ai_fill`; `api_bulk_scrape_start` →
      `api_bulk_scrape_job_start`) so those two limits never fired;
      names corrected.
    - **11.5** Anchor comment added to the `except Exception: pass`
      in `inject_config` per global rule #1.
    - **11.6** Custom CSRF implementation rationale documented in
      `docs/RETRODB_DESIGN_STANDARDS.md` §22 (why not Flask-WTF).
    - **11.7** `SecretRedactor` installed universally at root-logger
      level via new `log_manager.install_global_redactor()`, called
      in `app.py` immediately after `basicConfig`. Idempotent — two
      tests added in `test_log_redactor.py`.
    Net: 134 tests pass (was 124); 10 new tests; smoke-import clean.
    (v2.84.0)
- [x] **Pass 10 — template macros: modal extraction from
  `game_detail.html`** — Extracted all six modal dialogs from
  `templates/game_detail.html` (5904 → 5376 LOC, −528, −8.9%) into a
  new `templates/_modals/` directory, wired back in via Jinja
  `{% include %}` directives that inherit the full template context.
  New partials: `_modals/rename_modal.html` (23 LOC, rename-ROM
  dialog), `_modals/scrape_modal.html` (45 LOC, search-metadata with
  reset footer), `_modals/screenshot_modal.html` (9 LOC, carousel
  viewer), `_modals/filter_modal.html` (22 LOC, similar-games /
  platform filter), `_modals/edit_modal.html` (400 LOC, the big
  edit-metadata form with identity / release / gameplay / technical /
  ratings / description / images / video sections), and
  `_modals/boxart_zoom_modal.html` (5 LOC, lightbox). Used
  `{% include %}` rather than `{% macro %}` because the modals are
  single-use on this page and share the full `game` /
  `user_settings` / `csrf_token` context — an include inherits that
  context transparently, while a macro would require declaring and
  forwarding every field. Modal `id=` attributes stay identical, so
  every `document.getElementById(...)` in the page's own script block
  keeps working unchanged. Zero JS changes needed. The hidden
  `applyMetadataForm` POST-submission stub stays inline (7 LOC, not a
  modal). Each partial was rendered in isolation under a Flask
  test-request context to confirm Jinja parsing + include
  resolution + context inheritance work end-to-end. All 124 tests
  pass; smoke-import of `app` clean. (v2.83.23)
- [x] **Pass 8 — `window.API` migration across the JS layer** — Migrated
  83 of 84 raw `fetch()` call sites across 13 JS files (`theme.js`,
  `trophies.js`, `achievements.js`, `bulk-edit.js`, `bulk-scrape.js`,
  `game-list.js`, `rom-tools.js`, `log-viewer.js`,
  `all-games-controller.js`, `settings-page.js`, `main.js`,
  `game-modals.js`, `toast-controller.js`) to the existing
  `window.API` helper. Collapsed `fetch(url, { method: 'POST', headers:
  { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
  }).then(r => r.json()).then(...)` → `API.post(url, data).then(...)`;
  collapsed `const resp = await fetch(url); const data = await
  resp.json();` → `const data = await API.get(url);`. AbortController
  signals pass through the options parameter — `API.get(url, { signal
  })` works unchanged in the dropdown-options loaders and the toast
  poller. One `fetch()` remains raw: the `DELETE /api/logs/delete/
  <filename>` in `log-viewer.js`, because `window.API` has no
  `.delete()` helper yet. Per the original roadmap item, no new
  `APIClient` class was invented — the existing `window.API` (which
  already shipped `.get()`, `.post()`, `.postForm()`) does the job.
  Side-effect fix: the server-restart ping in `main.js::
  checkServerStatus` now uses `API.get` which throws on non-200,
  preserving the silent-retry path cleanly. Bundle regenerated
  (312,602 → 271,155 bytes after minification, ~13.3% reduction).
  All 124 tests pass; smoke-import of `app` clean. (v2.83.22)
- [x] **Pass 9 — scraper/ filename consistency** — Renamed
  `scraper/scrape_metadata_igdb.py` → `scraper/scrape_igdb.py` and
  `scraper/scrape_metadata_thegamesdb.py` → `scraper/scrape_thegamesdb.py`
  via `git mv` so blame is preserved. The `scrape_metadata_` prefix added
  nothing — every other scraper in the directory is already
  `scrape_<source>.py` (`scrape_rawg.py`, `scrape_screenscraper.py`,
  `scrape_steam.py`, `scrape_xbox.py`, `scrape_ai.py`, `scrape_esde.py`)
  and `docs/RETRODB_DESIGN_STANDARDS.md` §24.1 codifies the convention.
  Six import sites updated: `scraper/scraper_manager.py` (top-level),
  `scraper/hybrid_scraper.py` (2 top-level + 2 deferred inside
  fallback branches), `scraper/metadata_merger.py` (deferred inside
  `apply_tgdb_to_metadata`), `services/game_metadata_service.py`
  (2 deferred inside `apply_metadata_to_game`), `log_manager.py`
  (`scraping` category logger names), `static/js/log-viewer.js`
  (`shortenModule()` replaced the stale
  `scraper.scrape_metadata_` strip — the remaining `scraper.scrape_`
  strip now handles both old TGDB/IGDB files and all other scrapers).
  `CLAUDE.md` scraper-table rows updated. Cosmetic LOC-wise, but the
  scraper dir is now fully self-consistent with the standards doc.
  Smoke-import of `app` clean; all 124 tests pass. (v2.83.21)
- [x] **Pass 7 stage 3 — unified metadata-apply orchestrator** — Moved
  `ScraperManager.apply_metadata` + `ScraperManager.apply_hybrid_metadata`
  out of `scraper/scraper_manager.py` (684 → 584 LOC; −100) and into
  `services/game_metadata_service.py` (110 → 285 LOC; +175) as
  `apply_metadata_to_game(db_game_id, game_data, source, system_folder)` +
  `apply_hybrid_metadata_to_game(db_game_id, primary_source, primary_id,
  system_folder, all_results=None, explicit_secondary=None,
  secondary_sources=None, fill_gaps=True, force_overwrite=False,
  primary_data=None)`. All three apply-path callers — `routes/games.py`
  (manual edit), `routes/bulk_scrape.py` (single-game sync bulk),
  `services/jobs/bulk_scrape.py` (background bulk) — now go through the
  same entry point instead of two calling the manager and one calling
  `scraper.hybrid_scraper.apply_hybrid_metadata` directly. Side-effect
  fix: `routes/games.py` no longer does the
  `apply_metadata_to_game = scraper_manager.apply_metadata` reassignment
  dance, and the two bulk-scrape call sites that previously passed raw
  'thegamesdb' as `primary_source` (which hybrid_scraper's dispatch
  silently skipped, falling through to the fallback search) now get
  normalized to 'tgdb' at the service boundary — the primary-source
  branch actually fires instead of relying on the fallback path to
  re-search. Dead imports (`apply_tgdb`, `apply_igdb`, `apply_esde`)
  dropped from `scraper_manager.py`. All 124 tests pass. (v2.83.19)
- [x] **Pass 7 stage 2 — title-matching consolidation** — Pulled three
  remaining cross-module title-normalization helpers into
  `services/achievement_linking.py` (125 → 333 LOC; +208 LOC of shared
  code; ~75 LOC of inline boilerplate removed from consumers):
  `normalize_title_for_dedup` (lifted from `routes/platform_import.py`'s
  `normalize_title`, re-exported under the same local name so all nine
  Steam / Xbox / PSN import call sites are unchanged; `unicodedata` + `re`
  imports dropped from `platform_import.py`), `find_linked_game_for_psn`
  (lifted from `routes/trophies.py`; the blueprint keeps a thin wrapper
  that injects its module-level `query` so the service helper doesn't
  have to import back into `routes/`), and the three-pass RA matcher
  `normalize_for_ra_match` / `ra_significant_words` / `match_ra_game`
  (lifted from the ~60-line nested-inline block inside
  `RARefreshJob._run_refresh`; the job now calls `match_ra_game(...)`
  directly, `re` import dropped). Service module now documents why the
  three normalization regimes (`clean_title_for_matching`,
  `normalize_title_for_dedup`, `normalize_for_ra_match`) are deliberately
  distinct — conflating them would silently break downstream fuzzy
  matching. Parity spot-checked: `normalize_title_for_dedup` output
  matches the old `normalize_title` on diacritics, apostrophes,
  parenthesised years; `match_ra_game` still links "The Legend of Zelda:
  A Link to the Past" to "Legend of Zelda, The - A Link to the Past
  (USA)". All 124 tests pass. (v2.83.16)
- [x] **Pass 7 stage 1 — `routes/games.py` decomposition (first wave)** —
  Shrank the route from 1373 → 1128 LOC (−18%) by extracting three
  focused service modules (327 LOC of pure, reusable logic):
  `services/game_metadata_service.py` (110 LOC — `cross_map_ratings`,
  `build_game_card`, `import_source_for_rom_path`),
  `services/achievement_linking.py` (101 LOC — `clean_title_for_matching`
  moved out of `routes/trophies.py` which now re-exports it under the
  legacy `_clean_title_for_matching` name, plus `build_rpcs3_trophy_map`
  and `lookup_rpcs3_info`), `services/game_media_service.py` (116 LOC —
  `save_upload`, `save_screenshots`, `remove_media_file`,
  `resolve_media_path`, `try_standardize`, allowed-extension constants).
  The duplicated ~60-line card dict literal in `/api/games` and
  `/api/games/card-data` collapsed to a single `build_game_card()`
  call. Three copies of "fetch trophy data, build clean-title dict" for
  RPCS3 matching collapsed to `build_rpcs3_trophy_map()` +
  `lookup_rpcs3_info()`. The `edit_metadata` action's ~100-line inline
  filesystem block (upload / remove / path resolve per media type)
  became a ~20-line sequence of service calls. `routes/games_ai.py`
  also migrated to the shared `cross_map_ratings` helper so the
  manual-edit and AI-fill paths share a single source of truth.
  Leftover dead imports (`map_esrb_to_pegi`, `map_rating`,
  `infer_rating_from_content`, `is_ra_supported`, `normalize_platform_name`,
  `RATING_SYSTEM_KEYS`) cleaned out of `routes/games.py`. All 124 tests
  pass. Remaining stages (`achievement_linking_service` for external-
  provider matching beyond RPCS3, and the `apply_metadata_to_game` merge
  orchestrator) tracked as Pass 7 stage 2/3. (v2.83.13)

---

## In progress

### Pass 2 — continue gradual migration of `jsonify({'success': …})` → `success()` / `error()`

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

---

## Pass 5 — scraper/metadata_merger.py split — done (v2.83.11)

See "Done" section above. Future follow-up for the deeper collapse of
`apply_*_to_metadata()` into a linear fetch → normalise → dedupe → write
skeleton tracked under Pass 7 alongside `services/game_metadata_service.py`,
which will handle the merge orchestration from both the bulk-scrape and
AI-fill sides.

---

## Pass 6 — scraper_manager.py split — done (v2.83.12)

See "Done" section above. All three extractions landed:
`scraper/match_scorer.py` (scoring), `scraper/title_normalizer.py`
(noise strip + match normalization), `scraper/scraper_cache.py`
(SS TTL cache). Module-level functions rather than classes — matches
the `game_query.py` / `analytics.py` idiom followed from Pass 4
onwards. Manager shrank 1022 → 684 LOC (−33%).

---

## Pass 7 — games.py decomposition

### Carve service layer out of the biggest route file

- **Target**: `routes/games.py` (now 1128 LOC, was 1373) — split into thin
  route handlers + multiple service modules.
- **Why**: the file handles game CRUD, metadata application, trophy/
  achievement linking, image management, game search, and stats/reports in
  one body. Too big to tackle in one pass; start with the three heaviest
  endpoints.
- **Plan** (multi-stage):
  1. **stage 1 — done (v2.83.13).** Landed
     `services/game_metadata_service.py` (rating cross-map +
     `build_game_card` used by `/api/games` and `/api/games/card-data`),
     `services/achievement_linking.py` (`clean_title_for_matching` +
     `build_rpcs3_trophy_map` + `lookup_rpcs3_info`, with
     `routes/trophies.py` re-exporting for backward compat),
     `services/game_media_service.py` (upload/removal/path helpers). See
     the "Done" entry above.
  2. **stage 2 — done (v2.83.16).** Consolidated the remaining title-
     matching helpers into `services/achievement_linking.py` — see the
     "Done" entry above. Steam / Xbox sync jobs (`platform_sync.py`)
     actually link by `steam_app_id` / `xbox_title_id` rather than by
     title, so there was less title-matching duplication in sync jobs
     than the original roadmap prose implied. The real consolidation
     was three distinct normalization regimes (import-dedup,
     RA-list-match, PSN-trophy-link) previously scattered across a
     route, a blueprint, and a job — now all in one service module with
     documented semantics for why they stay separate.
  3. **stage 3 — done (v2.83.19).** Extracted `apply_metadata` and
     `apply_hybrid_metadata` off `ScraperManager` and into
     `services/game_metadata_service.py` as `apply_metadata_to_game` +
     `apply_hybrid_metadata_to_game`. All three call sites now share
     one code path. See the "Done" entry above.
- **Status**: all three stages done

---

## Pass 8 — frontend duplication

### Audit `window.API` coverage and migrate stragglers

- **Target**: `static/js/game-modals.js` (2331), `static/js/main.js` (1650),
  and any page-specific files that still use raw `fetch()`.
- **Why**: `utils.js` already ships `window.API` with `.get()`, `.post()`,
  `.postForm()` and `Notifications` for toasts. Pattern is already
  established — the refactor is migration, not invention. Inventing a new
  `APIClient` class on top would duplicate what's already there.
- **Plan**:
  - Grep for `fetch(` across `static/js/**/*.js` (excluding `app.bundle.js`).
    For each hit, check whether it has to remain raw (streaming, custom
    headers) or could be an `API.post()` call.
  - Replace inline `.then(r => r.json())` + error-toast patterns with
    `API.post(url, data).catch(Notifications.error)`.
  - Do NOT create a new class — use the existing `window.API`.
- **Est. reduction**: 10–20 LOC per migrated site; probably 200+ LOC
  across the codebase, but more importantly centralises error handling
  and CSRF/auth header logic if/when we add it.
- **Status**: done (v2.83.22) — see "Done" entry above.

---

## Pass 9 — scraper/ naming consistency

### Drop the legacy `scrape_metadata_` prefix on two scrapers

- **Target**: `scraper/scrape_metadata_igdb.py` → `scraper/scrape_igdb.py`,
  `scraper/scrape_metadata_thegamesdb.py` → `scraper/scrape_thegamesdb.py`.
- **Why**: every other scraper in the dir uses `scrape_<source>.py`
  (`scrape_rawg.py`, `scrape_screenscraper.py`, `scrape_steam.py`,
  `scrape_xbox.py`, `scrape_ai.py`, `scrape_esde.py`).  IGDB and TheGamesDB
  carry an extra `metadata_` segment that adds nothing — *all* scrapers
  scrape metadata. Codified by §24.1 of `docs/RETRODB_DESIGN_STANDARDS.md`.
- **Plan**:
  1. `git mv scraper/scrape_metadata_igdb.py scraper/scrape_igdb.py`
  2. `git mv scraper/scrape_metadata_thegamesdb.py scraper/scrape_thegamesdb.py`
  3. Update imports in the ~7 callers:
     - `scraper/scraper_manager.py`
     - `scraper/hybrid_scraper.py`
     - `scraper/metadata_merger.py`
     - `log_manager.py` (if it references the module name as a log
       category)
     - `static/js/log-viewer.js` (if the log category key is the filename)
     - `CLAUDE.md` (project file index)
     - `data/changelog.yaml` (any historical references)
  4. Run `python3 -m pytest`; run `python3 -c "import app"` smoke test.
- **Est. reduction**: cosmetic LOC-wise (~0) but brings scraper/ dir to
  full consistency with the standards doc.
- **Status**: done (v2.83.21) — see "Done" entry above.

---

## Pass 10 — template macros

### Extract repeated modal markup from `templates/game_detail.html`

- **Target**: `templates/game_detail.html` (5903 LOC). Create a
  `templates/_partials/` and `templates/_modals/` directory.
- **Why**: the page contains many modal dialogs (rename, scrape,
  screenshot, edit) each 30–60 LOC, plus game-card and metadata-field UIs
  that are duplicated on other pages (local_trophy_detail, PSN trophy
  detail, compare, etc.).
- **Plan**: convert each modal into a Jinja macro that takes just its
  local state as parameters. Candidate extractions:
  - `_modals/rename_modal.html` (≈30 LOC)
  - `_modals/scrape_modal.html` (≈55 LOC)
  - `_modals/screenshot_modal.html` (≈15 LOC)
  - `_modals/edit_modal.html` (≈200 LOC — biggest win)
  - `_partials/game_card.html` — reusable in `all_games.html`, list
    detail, wishlist, search results.
  - `_partials/metadata_fields.html` — the `<label>/<input>`/`<select>`
    triplets repeated per field.
- **Est. reduction**: game_detail.html shrinks ~40% (target ~3500 LOC).
  Other templates shrink too by consuming the shared macros.
- **Status**: done (v2.83.23) — modals extracted; see "Done" entry
  above. Actual reduction 8.9% (5904 → 5376 LOC) — below the 40%
  target because the `_partials/game_card.html` and
  `_partials/metadata_fields.html` ideas would shrink *other*
  templates, not `game_detail.html`, and converting the edit-modal's
  field triplets to a macro would add call-site complexity without
  a clear win. The cross-template `game_card` / `metadata_fields`
  extractions can be picked up separately if/when duplication grows.

---

## Pass 11 — Security hardening

Consolidated from: ad-hoc security pass (2026-04-21) + ants-audit v0.7.5
triage (2026-04-21) + online research (OWASP 2026 password-storage cheat
sheet, Flask/Werkzeug/Waitress CVE scan).

### 11.1 Upgrade password hashing (HIGH, M)

- **Target**: `services/auth.py:50-51` — `hash_password()` uses
  `hashlib.pbkdf2_hmac('sha256', password, salt, 100000)`.
- **Why**: OWASP 2026 Password Storage Cheat Sheet recommends PBKDF2-SHA256
  at **600,000+ iterations** (up from 310k in 2023) or migration to
  **Argon2id** (19 MiB memory, 2+ iterations).  100k is below floor.
- **Plan**: two options.
  1. Minimal — bump iterations to 600,000 and add a migration path: on next
     successful login, if the stored hash uses 100k iters, re-hash with
     600k.  Requires encoding the iteration count in the stored hash
     (e.g. `pbkdf2:600000:salt:hash`).
  2. Thorough — migrate to `argon2-cffi`.  Same migration-on-login
     pattern.  Adds a dependency; slightly more involved.
- **Source**: <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
- **Status**: done (v2.84.0) — option 1 (bump + migrate-on-login) shipped;
  Argon2id migration deferred pending real-world demand.

### 11.2 `SESSION_COOKIE_SECURE` env-gated (LOW / defense-in-depth, S)

- **Target**: `app.py:118-119` — sets `HTTPONLY` and `SAMESITE='Lax'`
  but never `SECURE`.
- **Why**: On localhost HTTP the flag would break login (browser drops
  the cookie).  But if an operator fronts RetroDB with a TLS reverse proxy,
  cookies leak over HTTP silently.  §22 of the design standards doc lists
  `SESSION_COOKIE_SECURE` as required, so the current state is a standards
  gap even if behaviourally correct.
- **Plan**: one-line env gate, documented in the security §.
  ```python
  app.config['SESSION_COOKIE_SECURE'] = (
      os.environ.get('RETRODB_SECURE_COOKIES', '').lower() in ('true', '1', 'yes')
  )
  ```
  Default off; operators fronting with HTTPS flip the env var.
- **Source**: <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>
- **Status**: done (v2.84.0)

### 11.3 File upload content-type / magic-byte validation (MEDIUM, M)

- **Target**: `routes/games.py:664-677` — `_save_upload()` only validates
  the filename extension.  `routes/auth.py:335+` — `api_upload_avatar`
  similarly extension-only.
- **Why**: Extension whitelisting is trivially bypassable (rename `.exe`
  to `.jpg`).  The 16 MB `MAX_CONTENT_LENGTH` cap is global; single-file
  size and per-directory quotas are absent.  For a localhost app the real
  risk is operator self-foot-gun, not RCE — but a picture upload with
  embedded script bytes could be rendered inline by a future feature that
  does so.
- **Plan**:
  1. `Pillow.Image.open(file.stream).verify()` on image uploads; reject
     if PIL can't decode.  Zero extra dependency (PIL already in
     requirements for decompression-bomb defence).
  2. Add per-file size limit (e.g. 5 MB avatars, 10 MB boxart) inside
     `_save_upload()`.
- **Status**: done (v2.84.0) — `PIL.Image.verify()` wired in
  `services/game_media_service.py` + `routes/auth.py::api_upload_avatar`;
  10 MB per-image cap applied (`MAX_IMAGE_SIZE`).

### 11.4 Rate-limit heavy admin routes (LOW, S)

- **Target**: `app.py:208-213` — flask-limiter is wired only to
  `games.api_game_ai_fill`, `bulk_scrape.api_bulk_scrape_start`, and
  `auth.api_login`.  `routes/maintenance.py:api_restart` (line 758),
  `api_maintenance_scan_roms`, `api_database_optimize`, `api_backup`,
  `api_image_resize_*` are unlimited.
- **Why**: On a single-user localhost deploy the realistic risk is the
  admin clicking "scan" twice by mistake and pinning the CPU, not a
  malicious DoS.  But adding limits is cheap and matches the existing
  pattern for login/bulk-scrape.
- **Plan**: add `limiter.limit("2 per minute")` to restart, `"3 per minute"`
  to scan/bulk/backup in the same register block.
- **Status**: done (v2.84.0) — limits applied; also fixed two pre-existing
  stale endpoint-name lookups (`games.api_game_ai_fill` →
  `games_ai.api_game_ai_fill`, `bulk_scrape.api_bulk_scrape_start` →
  `bulk_scrape.api_bulk_scrape_job_start`) so those two limiters actually
  fire now instead of silently wrapping a no-op lambda.

### 11.5 Anchor comment for exception swallow in `inject_config` (LOW, S)

- **Target**: `app.py:472` — `except Exception: pass` with no anchor
  comment.
- **Why**: Global rule #1 requires workarounds to carry a comment
  explaining the constraint.  The three other `except: pass` blocks in
  `app.py` (lines 226, 543, 1226) all have comments; this one was
  missed.
- **Plan**: one-line comment:
  ```python
  except Exception:
      pass  # non-fatal — missing/invalid scraper_settings.json just hides the AI Fill button
  ```
- **Status**: done (v2.84.0)

### 11.6 Document CSRF rationale in §22 (LOW, S)

- **Target**: `docs/RETRODB_DESIGN_STANDARDS.md` §22 — the security
  section doesn't explain why RetroDB uses a custom CSRF implementation
  (`app.py:277-305`) rather than Flask-WTF / CSRFProtect.
- **Why**: The custom implementation is correct (HMAC + session token +
  header/form check + explicit exempt list), but a future contributor
  reading §22 might "modernise" it to Flask-WTF without realising the
  design intent.
- **Plan**: two-sentence note in §22 explaining the choice (minimal
  dependency footprint; single-user localhost means CSRF is low-impact
  anyway, so the custom impl is simpler than wiring CSRFProtect).
- **Status**: done (v2.84.0)

### 11.7 Consolidate logger initialisation so `SecretRedactor` is universal (MEDIUM, M)

- **Target**: `services/log_redactor.py` + `log_manager.py:104-105`.
- **Why**: `SecretRedactor` is currently added only at `CategoryFileHandler`
  level.  A logger initialised before log setup, or one configured with a
  plain `StreamHandler`, bypasses redaction.  Spot-audit found no active
  leaks, but the architecture allows for future ones.
- **Plan**: install `SecretRedactor` as a root-logger filter during app
  startup, so every handler inherits it.  Requires verifying it doesn't
  over-redact structured log output (e.g. JSON tokens that are literals
  in stack traces).
- **Status**: done (v2.84.0) — `log_manager.install_global_redactor()`
  attaches the filter to the root logger + every basicConfig-era
  handler; idempotent; two tests added in `test_log_redactor.py`.

---

## Pass 12 — Database performance

### 12.1 Run `PRAGMA optimize` on connection close (HIGH, S)

- **Target**: `services/database.py` — `get_db()` and the request-scoped
  teardown handler (registered in `app.py`).  `services/jobs/base.py` —
  `_get_conn()` used by background jobs.
- **Why**: Since SQLite 3.18, `PRAGMA optimize` (when called just before
  closing a connection) runs ANALYZE on individual tables whose statistics
  are stale.  RetroDB never calls it.  For short-lived connections (the
  Flask per-request pattern) the cost is negligible; for long-lived ones
  (background jobs) the gain is larger.
- **Plan**:
  1. Short-lived (per-request): add `conn.execute("PRAGMA optimize")`
     immediately before `conn.close()` in the teardown handler.
  2. Long-lived (jobs): run `PRAGMA optimize=0x10002` on connection open,
     then `PRAGMA optimize` periodically (e.g. every 30 minutes or every
     500 iterations).
- **Source**: <https://sqlite.org/pragma.html#pragma_optimize>
- **Status**: done (v2.84.1) — per-request teardown landed in v2.84.0 at
  `app.py:234`; long-lived 0x10002 mask + fallback-safe try/except added to
  `services/jobs/base.py::_get_conn()` in v2.84.1; periodic `PRAGMA optimize`
  (no args) every 30 min on the bulk-scrape progress connection.

### 12.2 Batch job progress persistence (HIGH, M)

- **Target**: `services/jobs/base.py:158-183` — `persist_job_progress`
  opens a fresh SQLite connection (6 PRAGMAs) per call.  Called from
  `services/jobs/bulk_scrape.py:717` inside a `for game in games:` loop,
  every 10 items or 30 seconds.  For a 1000-game bulk scrape that's
  ~100 connection-open/close cycles just for progress updates.
- **Why**: Measured overhead of `_get_conn()` (including PRAGMA setup) is
  ~3-10 ms depending on disk.  At 100 calls over a 30-minute job that's
  only ~1 second total — not dramatic — but the pattern is wasteful and
  will worsen if the per-interval is tightened.
- **Plan**: have the job thread cache a persistent connection for its
  lifetime (PRAGMAs run once on job start).  Pass that connection down
  into `persist_job_progress(conn, job_id, progress_dict)`.  Close on
  job completion.  `_commit_with_retry` already exists for the long-
  lived pattern — re-use it.
- **Status**: done (v2.84.1) — `persist_job_progress(job_id, dict, conn=None)`
  new signature; `bulk_scrape.py::run()` now opens `_progress_conn` once at
  job start, reuses it via `_commit_with_retry`, closes it in both success
  and exception branches.

### 12.3 Run `ANALYZE` after schema / index changes (MEDIUM, S)

- **Target**: `services/database_init.py` — adds ~30 indexes via
  `CREATE INDEX IF NOT EXISTS` on every app startup, but never runs
  `ANALYZE` afterwards.  Query planner stats never update on a running
  server.
- **Why**: Without ANALYZE, the planner falls back to heuristics and can
  pick bad plans for compound WHERE clauses on large `games` tables.
  OWASP-unrelated; this is pure perf.
- **Plan**: after the `CREATE INDEX` loop, run `PRAGMA optimize` (which
  since SQLite 3.46.0 auto-runs ANALYZE where stale).  Alternatively an
  explicit `ANALYZE;`.  One-off per app start.
- **Source**: <https://sqlite.org/lang_analyze.html>
- **Status**: done (v2.84.0) — `database_init.py:515` runs `PRAGMA optimize`
  after the `CREATE INDEX` loop.  Confirmed in the 2.84.1 audit.

### 12.4 Slow-query logging (MEDIUM, M)

- **Target**: `services/database.py::query()` / `::execute()`.
- **Why**: No visibility into production N+1 patterns or slow queries.
  Even a threshold-based debug log (query > 100 ms) would surface
  regressions immediately.
- **Plan**: wrap `conn.execute(sql, args)` in a `time.perf_counter()`
  delta; if > 100 ms, log at WARNING with the SQL (redacted) and
  arguments count.  Guard behind a `SLOW_QUERY_MS` config knob (default
  disabled in production, 100 ms in dev).
- **Status**: done (v2.84.1) — `config.SLOW_QUERY_MS` (env
  `RETRODB_SLOW_QUERY_MS`, default 0 = disabled); `services/database.py`
  wraps `query()`, `execute()`, and `execute_many()` with perf-counter
  deltas; threshold-exceed logs WARNING with whitespace-compacted +
  500-char-truncated SQL and arg count.  Values themselves never logged.
  6 tests in `tests/test_slow_query_log.py`.

### 12.5 FTS5 virtual table for `games.title` + `alternate_titles` (MEDIUM, L)

- **Target**: search endpoints (`routes/games_search.py::api_games_find`
  and similar), plus filter pages doing `WHERE title LIKE '%q%'`.
- **Why**: `LIKE '%q%'` on a 10k-row games table with no index is an
  O(N) scan every time.  SQLite FTS5 with a porter tokeniser brings
  this to sub-20 ms on the same dataset (measured wins reported widely
  in community benchmarks).
- **Plan**:
  1. Define a virtual table `games_fts(title, alternate_titles, content='games', content_rowid='id')`.
  2. Populate it from `games` (and keep it in sync via triggers on
     INSERT/UPDATE/DELETE).
  3. Replace `WHERE title LIKE` with `WHERE id IN (SELECT rowid FROM games_fts WHERE games_fts MATCH ?)`.
- **Caveat**: FTS5 doesn't replace prefix LIKE for all cases (autocomplete,
  substring mid-word).  Keep LIKE where required.
- **Source**: <https://www.sqlite.org/fts5.html>
- **Status**: deferred (post-v2.84.1) — L-sized; gated on a benchmark run
  that confirms `WHERE title LIKE '%q%'` is actually the hot path on a
  realistic 10k-row library.  `RETRODB_SLOW_QUERY_MS=100` (added 12.4) is
  the instrument to collect that data.

---

## Pass 13 — Frontend performance

### 13.1 Stream large image downloads in the scraper (MEDIUM, S)

- **Target**: `scraper/base_scraper.py:181-234::download_image()` —
  `f.write(response.content)` buffers the whole response in memory.
- **Why**: Per-request memory use is proportional to image size (typically
  500 KB – 10 MB).  Sequential downloads mean only one image is resident
  at a time, so the agent's earlier "500 MB at once" claim was wrong —
  but streaming is still best practice and cheap.
- **Plan**: replace with `for chunk in response.iter_content(chunk_size=8192):`.
- **Status**: todo

### 13.2 Split `app.bundle.js` into core vs feature bundles (MEDIUM, M)

- **Target**: `build_js.py` — concatenates 9 files (~7300 LOC) into a
  single bundle loaded on every page.
- **Why**: Pages like `/logs`, `/settings`, `/museum` don't use
  `game-modals.js`, `bulk-edit.js`, or `bulk-scrape.js`.  Loading them
  anyway costs ~200 KB minified over the wire on first visit.
- **Plan**:
  1. `core.bundle.js` — utils, page-lifecycle, toast-controller, main.
     Loaded on every page.
  2. `games.bundle.js` — game-list, game-modals, bulk-scrape, bulk-edit,
     filters.  Loaded only by `base.html` when a template sets
     `{% set needs_games_bundle = true %}` or when on a games-related
     endpoint.
- **Status**: todo

### 13.3 Per-file cache-busting hash in bundle URLs (LOW, M)

- **Target**: `templates/base.html:23,359` — CSS and JS loaded with
  `?v={{ config.APP_VERSION }}`.  All static assets share the same cache
  key; a CSS-only change still busts JS cache and vice versa.
- **Why**: Currently, each patch version bump forces every user's browser
  to refetch both CSS and JS bundles.  Per-file content hashes let browsers
  keep the unchanged file in cache.
- **Plan**: `build_css.py` / `build_js.py` write a short content hash
  (e.g. first 8 chars of SHA-256) to a JSON manifest; `base.html` reads
  the manifest via a Jinja global.  Loaded assets become
  `main.min.css?v=abc12345`.
- **Status**: todo

---

## Pass 14 — Developer efficiency & test coverage

### 14.1 Pre-commit hooks for ruff + gitleaks (MEDIUM, S)

- **Target**: repository root — no `.pre-commit-config.yaml`.
- **Why**: `pyproject.toml` already configures ruff with the project's
  preferred rule set (`E, F, B, S`).  `.gitleaks.toml` already documents
  the secrets allowlist.  Wiring both into pre-commit means no
  lint/secret regression lands in a commit.
- **Plan**: create `.pre-commit-config.yaml` with two hooks:
  `astral-sh/ruff-pre-commit` (ruff-check + ruff-format in check mode)
  and `gitleaks/gitleaks` (pre-commit stage, using existing
  `.gitleaks.toml`).  Do NOT wire mypy or pytest into pre-commit —
  they're slower and belong in CI.
- **Source**: <https://github.com/astral-sh/ruff-pre-commit>,
  <https://gatlenculp.medium.com/effortless-code-quality-the-ultimate-pre-commit-hooks-guide-for-2025-57ca501d9835>
- **Status**: todo

### 14.2 Gradual type hints on high-risk modules (LOW, L)

- **Target**: `scraper/metadata_merger.py`, `services/game_query.py`,
  `routes/games.py`.
- **Why**: These are the largest / most-called modules in the codebase.
  Type hints on function signatures make IDE autocomplete and `mypy`
  checks meaningful.  Currently the codebase has ~0% type coverage.
- **Plan**: adopt one module at a time.  Start with signatures (`-> dict`,
  `-> list[dict]`, `int | None`) then internal variables only where
  they help.  Add `mypy` as a CI-only check (not pre-commit) with
  `--ignore-missing-imports`.
- **Status**: todo

### 14.3 Test coverage on `scraper/metadata_merger.py` and `services/jobs/bulk_scrape.py` (HIGH, L)

- **Target**: `tests/` — currently 124 tests across 40+ modules.
  Coverage is concentrated on formatters, game_utils, HLTB.  The two
  most complex / most-changing modules (metadata_merger at 1293 LOC,
  bulk_scrape job at ~700 LOC) have near-zero coverage.
- **Why**: Regressions in scraper merge logic or job state tracking go
  undetected until production.  Given Pass 5 (metadata_merger split)
  will rewrite this heavily, adding tests first is insurance.
- **Plan**:
  1. Characterisation tests for `apply_*_to_metadata()` — feed in a
     canned scraper response, assert on the `games` row state after.
     Done per-source (TGDB, IGDB, RAWG, ScreenScraper, AI).
  2. State-machine tests for `BulkScrapeJob` — start → pause → resume →
     cancel → restart transitions.  Use an in-memory SQLite fixture.
- **Status**: todo (but do this BEFORE Pass 5 to de-risk the rewrite)

---

## Pass 15 — Accessibility (a11y)

Derived from: template audit (2026-04-21) + WCAG 2.2 AA. ARIA is present in
17 of 45 templates (163 occurrences) but uneven. No skip-to-main-content
link; `<main role="main">` on `base.html:239` has a redundant role attribute
(the `<main>` element implies `role="main"`).

### 15.1 Skip-to-main-content link (LOW, S)

- **Target**: `templates/base.html` — add a `.skip-link` as the first
  focusable element inside `<body>`, styled to be visually hidden until
  focused.
- **Why**: WCAG 2.2 Success Criterion 2.4.1 (Bypass Blocks). Keyboard-only
  users currently have to tab through the entire sidebar on every page.
- **Plan**:
  ```html
  <a href="#main-content" class="skip-link">Skip to main content</a>
  ```
  plus a `.skip-link` rule in `components/buttons.css` (positioned off-screen
  with `position: absolute; left: -9999px;` and brought on-screen on
  `:focus`). Give `<main>` `id="main-content"` and drop the redundant
  `role="main"`.
- **Status**: todo

### 15.2 Modal focus management (MEDIUM, M)

- **Target**: `static/js/game-modals.js` — `GameDetailModal`, `GameEditModal`,
  and any ad-hoc modals in `static/js/main.js`. Also `bulk-edit.js`,
  `bulk-scrape.js` modal flows.
- **Why**: WCAG 2.4.3 (Focus Order) + 3.2.1 (On Focus). Current modals show
  `focus()` calls but no trap — tab can escape the modal to the background
  sidebar. Also no "focus restore to trigger" pattern on close, so keyboard
  users lose their place in the list.
- **Plan**: add a small `ModalFocusTrap` helper to `utils.js`:
  ```js
  const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
  const ModalFocusTrap = {
      activate(modalEl, triggerEl) { /* save trigger, trap Tab, Escape closes */ },
      deactivate() { /* restore focus to saved trigger */ },
  };
  ```
  Call on modal open/close. Add `aria-modal="true"`, `aria-labelledby="..."`
  and `role="dialog"` to each modal root element.
- **Status**: todo

### 15.3 Theme contrast audit (MEDIUM, M)

- **Target**: all 7 themes (`cyberpunk`, `matrix`, `amber`, `ocean`,
  `christian`, `bladerunner`, `elite`) — `static/css/core/themes.css` plus
  per-theme overrides.
- **Why**: WCAG 2.2 AA requires 4.5:1 contrast for normal text and 3:1 for
  large text / UI components. Cyberpunk-style dark themes routinely fail on
  secondary text (`--text-secondary: #9aa0a6` on `--bg-darkest: #0a0e17` =
  about 7.5:1 — fine, but gradients and overlays can drop below threshold).
- **Plan**: run each theme through a contrast audit (axe-core or Lighthouse
  in Firefox/Chrome dev tools). Document measured ratios per theme per token
  pair in a `docs/theme_contrast.md`. Fix any pair that falls below 4.5:1.
  Low-priority pairs (disabled text, decorative) can accept 3:1 documented.
- **Status**: todo

### 15.4 Sweep redundant ARIA + upgrade semantic HTML (LOW, M)

- **Target**: every template with `role=` attributes.
- **Why**: the first rule of ARIA is "don't use ARIA where HTML has native
  semantics". `<nav role="navigation">`, `<main role="main">`, `<header
  role="banner">` are redundant. Template audit found at least `base.html:239`
  as redundant.
- **Plan**: grep for `role="(navigation|main|banner|contentinfo|form|button)"`
  and remove redundant ones where the wrapping tag is the matching element.
  Add ARIA only where there's no native equivalent (live regions, modals,
  disclosure widgets).
- **Status**: todo

### 15.5 Keyboard shortcut help overlay (LOW, S)

- **Target**: `static/js/main.js::KeyboardShortcuts` — document existing
  shortcuts in a `?` overlay.
- **Why**: discoverability. Help page has a shortcuts section, but in-app
  `?` overlay is a standard pattern (Gmail, GitHub, Linear) and takes ~40 LOC.
- **Plan**: bind `?` (Shift+/) to open a modal listing all registered
  shortcuts. Generate the list from a single source of truth so new
  shortcuts auto-document.
- **Status**: todo

---

## Pass 16 — HTTP security headers expansion

Current state (`app.py:235-242`): `X-Content-Type-Options`, `X-Frame-Options`,
`X-XSS-Protection`, `Referrer-Policy`. Missing: `Content-Security-Policy`,
`Strict-Transport-Security`, `Permissions-Policy`. The `X-XSS-Protection`
header is deprecated and modern guidance is to omit it (Chromium removed
the auditor entirely; some edge cases where it enabled XSS).

### 16.1 Remove deprecated `X-XSS-Protection` (LOW, S)

- **Target**: `app.py:240`.
- **Why**: MDN / OWASP 2024-2026 guidance: the XSS Auditor was removed
  from Chrome/Edge. The header can itself introduce XSS in some browsers.
  Modern stance: omit, or set to `0` to explicitly disable in legacy
  browsers.
- **Plan**: delete the line. Leave a brief `# (deleted X-XSS-Protection
  — deprecated header)` commit message for posterity.
- **Source**: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-XSS-Protection>
- **Status**: todo

### 16.2 Add `Content-Security-Policy` (MEDIUM, L — needs template audit)

- **Target**: `app.py::set_security_headers`.
- **Why**: CSP is the strongest defence-in-depth against XSS. RetroDB is
  single-user localhost, but inline styles/scripts exist in several
  templates (the `<style>` blocks in game_detail / settings, inline event
  handlers in older JS). Adding CSP requires auditing all of them first.
- **Plan**:
  1. Inventory every inline `<script>` and `on*="..."` handler across
     `templates/`.
  2. Add CSP nonces via `secrets.token_urlsafe(16)` generated per-request,
     attached to `g` and surfaced via a Jinja context processor as
     `{{ csp_nonce }}`.
  3. Start in **report-only** mode:
     ```python
     response.headers['Content-Security-Policy-Report-Only'] = (
         "default-src 'self'; "
         "script-src 'self' 'nonce-" + g.csp_nonce + "'; "
         "style-src 'self' 'unsafe-inline'; "  # relax until inline <style> audit done
         "img-src 'self' data: https:; "  # https: needed for scraped boxart cached by URL in rare cases
         "font-src 'self'; "
         "connect-src 'self'; "
         "frame-ancestors 'self'"
     )
     ```
  4. After a week of zero `report-only` violations (collected via browser
     console in dev), flip to `Content-Security-Policy` enforcing.
  5. Do NOT adopt `flask-talisman` — the extension is overkill for a single
     `after_request` hook and adds a dependency.
- **Source**: <https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html>
- **Status**: todo

### 16.3 Add `Permissions-Policy` (LOW, S)

- **Target**: `app.py::set_security_headers`.
- **Why**: opt out of browser APIs that RetroDB never uses (camera, mic,
  geolocation, Topics). Defence-in-depth against compromised dependencies
  that attempt to access sensors.
- **Plan**: one-line addition:
  ```python
  response.headers['Permissions-Policy'] = (
      'browsing-topics=(), camera=(), microphone=(), geolocation=(), '
      'payment=(), usb=(), interest-cohort=()'
  )
  ```
- **Source**: <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy>
- **Status**: todo

### 16.4 Add `Strict-Transport-Security` — env-gated (LOW, S)

- **Target**: `app.py::set_security_headers` — pair with 11.2
  (`SESSION_COOKIE_SECURE`).
- **Why**: only meaningful behind a TLS reverse proxy. On localhost HTTP it
  does nothing (browsers ignore HSTS without a TLS handshake). But if an
  operator fronts with HTTPS and doesn't set HSTS, they're one MITM away
  from cookie theft.
- **Plan**: env-gated by the same `RETRODB_SECURE_COOKIES` flag as 11.2:
  ```python
  if app.config.get('SESSION_COOKIE_SECURE'):
      response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
  ```
- **Status**: todo

---

## Pass 17 — Observability & health checks

### 17.1 `/health` and `/ready` endpoints (HIGH, S)

- **Target**: new blueprint `routes/health.py` or inline in `app.py`.
- **Why**: no liveness or readiness endpoint currently exists. Operators
  running RetroDB behind systemd / Docker / a reverse-proxy have no way to
  tell "is the process alive" vs "is it ready to serve" without probing a
  real page.
- **Plan**: two cheap endpoints, no auth required, not logged as requests:
  ```python
  @app.route('/health')
  def health():
      return jsonify({'status': 'alive'}), 200

  @app.route('/ready')
  def ready():
      try:
          db = get_db()
          db.execute("SELECT 1").fetchone()
          return jsonify({'status': 'ready'}), 200
      except Exception as e:
          return jsonify({'status': 'not_ready', 'error': str(e)}), 503
  ```
  Liveness stays cheap (no DB). Readiness hits DB so it catches DB-lock
  failures. Exclude both from the `load_user` decorator to skip session
  overhead.
- **Source**: <https://github.com/fedora-infra/flask-healthz> (pattern, not
  adoption — do it inline, no dep)
- **Status**: todo

### 17.2 Request IDs / correlation IDs in logs (MEDIUM, S)

- **Target**: `app.py::before_request`, `services/log_redactor.py`, log
  format strings in `log_manager.py`.
- **Why**: when a user reports "my AI fill crashed at 3pm", correlating
  the route hit → scraper call → DB error across three log files currently
  requires timestamp matching. A per-request UUID in every log line makes
  it one grep.
- **Plan**:
  1. In `before_request`: `g.request_id = secrets.token_hex(4)` (8-char hex).
  2. Add a `logging.Filter` that reads `g.request_id` and stamps it onto
     every record (or `"-"` if no request context).
  3. Update format strings: `%(request_id)s [%(levelname)s] ...`.
- **Status**: todo

### 17.3 Slow-request logging middleware (LOW, S)

- **Target**: `app.py::before_request`/`after_request`.
- **Why**: spot-detects endpoints that regress. Pairs with 12.4
  (slow-query logging) — slow-query catches DB; slow-request catches the
  whole handler.
- **Plan**:
  ```python
  @app.before_request
  def _start_timer():
      g.start_time = time.perf_counter()

  @app.after_request
  def _log_slow_request(response):
      elapsed = (time.perf_counter() - g.start_time) * 1000
      if elapsed > 500:  # ms
          logger.warning(f"slow_request {request.method} {request.path} {elapsed:.0f}ms status={response.status_code}")
      return response
  ```
  Guard by a `SLOW_REQUEST_MS` config knob so ops can disable / tune.
- **Status**: todo

---

## Pass 18 — Image pipeline modernization

Cover art, screenshots, fanart and manuals are the largest single class of
disk usage and over-the-wire bytes for typical installs. Modernizing the
pipeline yields real wins.

### 18.1 WebP conversion on ingest (HIGH, M)

- **Target**: `scraper/base_scraper.py::download_image()` + the `apply_*_to_metadata()`
  helpers in `scraper/metadata_merger.py`.
- **Why**: WebP is 25-35% smaller than JPEG at equivalent quality and
  supported by ~97% of browsers in 2026. `Pillow` is already a dependency.
  AVIF is smaller still (~50% vs JPEG) but encoding is 10-100× slower —
  not worth the scrape-job cost on a single-user machine.
- **Plan**:
  1. Add `RETRODB_IMAGE_FORMAT` config (`jpeg` / `webp`, default `webp`).
  2. In `download_image()`, after fetching: `Image.open(io.BytesIO(response.content)).save(path, format='WEBP', quality=85, method=4)`.
  3. Keep filename extension logic — the DB stores filenames, so migrate
     over time, not in a big-bang conversion.
  4. Add a one-off maintenance task `/api/maintenance/convert-images-to-webp`
     that iterates `media_directory` and converts JPEGs in place, updating
     DB filename references. Gated behind a disk-space check.
- **Source**: <https://caniuse.com/webp>
- **Status**: todo

### 18.2 `loading="lazy"` + `decoding="async"` on game-card images (MEDIUM, S)

- **Target**: `static/js/all-games-controller.js` (card render), `static/js/game-modals.js`
  (screenshot carousel), plus any template loops over `<img>`.
- **Why**: on pages with 500+ cards the browser fetches every image
  eagerly until JS scroll-observer kicks in. Native `loading="lazy"` is
  free to add and has been baseline-supported since 2022.
- **Plan**: add both attributes to every `<img>` inside a card / list
  render path. First image on the page (above-the-fold boxart) can remain
  eager via `loading="eager"` to avoid LCP regression.
- **Status**: todo

### 18.3 Responsive `srcset` for boxart (LOW, L)

- **Target**: `services/image_utils.py` + card / detail templates.
- **Why**: game cards render boxart at ~150×200 px; detail modal at
  ~300×400 px. Both currently load the same file (often 1000×1400 original).
  Generating a `-sm` and `-md` variant on ingest and using
  `<img srcset="...-sm.webp 150w, ...-md.webp 300w">` would cut typical page
  payload 60-80%.
- **Plan**:
  1. `services/image_utils.py::make_responsive_variants(src_path)` — writes
     `-sm` (160w) and `-md` (320w) next to the original.
  2. Call from the `standardize_image()` path during scrape.
  3. Jinja helper `{{ boxart_srcset(game) }}` that produces the `srcset`
     string, skipping missing variants.
- **Source**: <https://developer.mozilla.org/en-US/docs/Web/HTML/Element/img#srcset>
- **Status**: todo

---

## Pass 19 — Versioned schema migrations

### 19.1 Replace ad-hoc `_migrate_*` with `PRAGMA user_version` (MEDIUM, M)

- **Target**: `services/database_init.py` — 21 `_migrate_*` / `ALTER TABLE`
  references, all run unconditionally on every app start. New migrations
  get grafted on as another `_migrate_X()` function.
- **Why**: current pattern works (migrations are idempotent with
  `CREATE TABLE IF NOT EXISTS` / try-except on column-exists) but:
  - No way to know "which migrations have actually run on this install?"
  - Startup cost grows linearly as migrations accumulate.
  - No rollback story.
  - Deleted migrations leave no audit trail.
- **Plan**: the "suckless" SQLite pattern — no Alembic, no SQLAlchemy dep.
  ```python
  # services/migrations/__init__.py
  MIGRATIONS = [
      '001_initial_schema.sql',
      '002_add_alt_titles.sql',
      # ...
  ]
  def apply_pending(conn):
      current = conn.execute("PRAGMA user_version").fetchone()[0]
      for idx, filename in enumerate(MIGRATIONS[current:], start=current):
          sql = (MIGRATIONS_DIR / filename).read_text()
          conn.executescript(sql)
          conn.execute(f"PRAGMA user_version = {idx + 1}")
          conn.commit()
  ```
  Folder `services/migrations/*.sql` holds the raw DDL (or `*.py` for
  data migrations that need Python). New migration = new file + array
  entry.
- **Source**: <https://eskerda.com/sqlite-schema-migrations-python/>
- **Status**: todo

### 19.2 Document migration authoring in standards doc (LOW, S)

- **Target**: `docs/RETRODB_DESIGN_STANDARDS.md` — add §25 after the
  naming standards.
- **Why**: the above pattern needs a one-page rulebook: file naming, no
  editing past migrations, how to handle data migrations vs schema.
- **Plan**: short section covering filename format (`NNN_description.sql`),
  idempotency rules, and the "migrations are append-only once shipped"
  invariant.
- **Status**: todo (follows 19.1)

---

## Pass 20 — CI/CD hardening

### 20.1 Dependabot config for pip + GitHub Actions (MEDIUM, S)

- **Target**: `.github/dependabot.yml` (new).
- **Why**: no automated dependency update PRs. `requirements.lock` drifts,
  CVEs sit unpatched. GitHub provides this free.
- **Plan**:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: "pip"
      directory: "/"
      schedule: { interval: "weekly" }
      cooldown: { default-days: 4 }
      groups:
        pip-dependencies:
          patterns: ["*"]
    - package-ecosystem: "github-actions"
      directory: "/"
      schedule: { interval: "weekly" }
  ```
  Cooldown avoids landing day-of-release breakages. Grouping keeps PR
  volume manageable.
- **Source**: <https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file>
- **Status**: todo

### 20.2 `pip-audit` in CI (MEDIUM, S)

- **Target**: `.github/workflows/ci.yml` — add a step after the install.
- **Why**: catches CVEs against the specific pinned versions in
  `requirements.lock`. Dependabot catches "new release exists";
  `pip-audit` catches "current pin has a known CVE".
- **Plan**:
  ```yaml
  - name: pip-audit
    run: |
      pip install pip-audit
      pip-audit --requirement requirements.lock --strict
    continue-on-error: true  # surface as warning until backlog is clean
  ```
- **Source**: <https://pypi.org/project/pip-audit/>
- **Status**: todo

### 20.3 Coverage reporting via `pytest-cov` (LOW, S)

- **Target**: `.github/workflows/ci.yml`, `pyproject.toml`.
- **Why**: currently no visibility into which modules are covered. Pairs
  with 14.3 (test coverage targets for metadata_merger / bulk_scrape).
- **Plan**:
  ```yaml
  - name: Pytest with coverage
    run: |
      pip install pytest-cov
      pytest --cov=services --cov=scraper --cov=routes --cov-report=term-missing
  ```
  Add `[tool.coverage.run]` omit rules for `tests/`, `migrations/`.
  Do NOT gate PRs on coverage threshold yet — set a baseline first.
- **Status**: todo

### 20.4 Python version matrix (LOW, S)

- **Target**: `.github/workflows/ci.yml` — add matrix for 3.12 + 3.13.
- **Why**: CI pins 3.13 only. Users on long-term distros (Debian stable,
  openSUSE Leap) are often on 3.11-3.12 — a regression on those Pythons
  wouldn't be caught. Keep 3.13 on the list (JIT coming).
- **Plan**: `strategy.matrix.python-version: [ "3.12", "3.13" ]`. Do NOT
  include 3.14 free-threaded — research confirms it hurts single-threaded
  Flask perf 30-50%.
- **Source**: <https://codspeed.io/blog/state-of-python-3-13-performance-free-threading>
- **Status**: todo

---

## Pass 21 — Operational resilience

### 21.1 SQLite online backup API (HIGH, M)

- **Target**: `routes/settings.py:247-276::api_backup` — currently uses
  `shutil.copy2(config.DB_PATH, backup_path)`.
- **Why**: `shutil.copy2` on a WAL-mode database with active writers can
  produce a torn / corrupted file. SQLite's online backup API
  (`sqlite3.Connection.backup()`) coordinates with WAL and guarantees a
  consistent snapshot even under concurrent writes.
- **Plan**:
  ```python
  src = sqlite3.connect(config.DB_PATH)
  dst = sqlite3.connect(backup_path)
  with dst:
      src.backup(dst)  # single call; SQLite handles WAL coordination
  dst.close(); src.close()

  verify = sqlite3.connect(backup_path)
  ok = verify.execute("PRAGMA integrity_check").fetchone()[0]
  verify.close()
  if ok != 'ok':
      os.remove(backup_path)
      raise RuntimeError(f"backup failed integrity check: {ok}")
  ```
  Integrity check at the end means we never hand the user a broken backup.
- **Source**: <https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup>
- **Status**: todo

### 21.2 Graceful shutdown — mark jobs paused on SIGTERM (MEDIUM, M)

- **Target**: `app.py` (signal handler install), `services/jobs/base.py`
  (shutdown hook).
- **Why**: background jobs (bulk scrape, RA sync, museum generation) run
  in threads with state in SQLite. A `systemctl stop` / Ctrl-C kills them
  mid-iteration — the queued-games DB row still shows "in-progress", the
  user sees a stuck job on next start. App.py has `/api/jobs/resume/<id>`
  already; the missing piece is marking jobs "pausable" cleanly at
  shutdown instead of leaving them wedged.
- **Plan**:
  ```python
  import signal
  _shutdown = threading.Event()
  def _handle_sigterm(signum, frame):
      _shutdown.set()
      for job in get_running_jobs():
          job.request_pause()  # set a flag the job's inner loop reads each iter
      logger.info("SIGTERM received; running jobs flagged for pause")
  signal.signal(signal.SIGTERM, _handle_sigterm)
  signal.signal(signal.SIGINT, _handle_sigterm)
  ```
  Each job's inner loop already has a "paused" check (for the pause
  button) — just need to wire the signal to the same path.
- **Status**: todo

### 21.3 Backup rotation / max-backups knob (LOW, S)

- **Target**: `routes/settings.py::api_backup` — currently unbounded.
- **Why**: on a deploy that auto-backups daily, the `backups/` dir grows
  without limit. Each backup is ~10-500 MB depending on library size.
- **Plan**: after creating a new backup, if the count exceeds
  `MAX_BACKUPS` config (default 30), delete the oldest N. Keep at least
  one always.
- **Status**: todo

---

## Pass 22 — Request-level caching & ETags

### 22.1 ETag / `If-None-Match` on `/api/games/card-data` (MEDIUM, M)

- **Target**: `routes/games.py::api_games_card_data` and similar large
  read-only endpoints.
- **Why**: card-data responses are huge (JSON of 1000+ games, ~500 KB).
  Currently the browser re-fetches on every page navigation. An ETag
  based on the max `updated_at` timestamp in the query's row set lets the
  browser short-circuit with `304 Not Modified`.
- **Plan**:
  ```python
  @bp.route('/api/games/card-data')
  def api_games_card_data():
      max_updated = db.execute("SELECT MAX(updated_at) FROM games WHERE ...").fetchone()[0]
      etag = hashlib.md5(f"{filter_key}:{max_updated}".encode()).hexdigest()
      if request.headers.get('If-None-Match') == etag:
          return '', 304
      response = jsonify(data)
      response.headers['ETag'] = etag
      response.headers['Cache-Control'] = 'private, must-revalidate'
      return response
  ```
  Requires every game write to touch `updated_at` — verify this on
  INSERT/UPDATE paths.
- **Status**: todo

### 22.2 Response compression (LOW, S)

- **Target**: `app.py` — add `Flask-Compress` or roll a `gzip`
  `after_request` hook.
- **Why**: large JSON payloads (card-data, filter options) ship
  uncompressed. Waitress doesn't compress by default.
- **Plan**: inline hook (avoids dep):
  ```python
  @app.after_request
  def _compress(response):
      if (response.content_length and response.content_length > 1024
          and 'gzip' in request.headers.get('Accept-Encoding', '')
          and response.content_type and 'json' in response.content_type):
          response.data = gzip.compress(response.data, compresslevel=6)
          response.headers['Content-Encoding'] = 'gzip'
          response.headers['Content-Length'] = len(response.data)
      return response
  ```
  Benchmark first — may be better done at the reverse-proxy layer on
  deploys that have one.
- **Status**: todo

### 22.3 Per-file cache-busting hash — consolidate with Pass 13.3 (N/A)

See Pass 13.3 — no duplicate entry.

---

## Scope notes — considered and dropped

The following were considered during this planning round and intentionally
not added to the roadmap. Document here so they don't keep re-appearing.

- **Flask-Talisman**: replaces 4-8 lines of manual header setting with a
  dependency. Not worth it.
- **Flask-Migrate / Alembic**: requires SQLAlchemy adoption, which RetroDB
  explicitly doesn't use (raw SQL is part of the design). Pass 19 uses the
  suckless PRAGMA-user_version pattern instead.
- **Progressive Web App / service worker**: no offline story for a
  localhost ROM manager. Adds maintenance burden for zero user benefit.
- **i18n / localization**: explicitly English-only single-operator context.
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
