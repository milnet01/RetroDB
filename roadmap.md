# RetroDB Roadmap

Tracking file for refactoring, security, performance, and quality work
identified in successive reviews (2026-04-21 onwards). Items are ordered so
that earlier passes establish the patterns used by later ones (service-layer
carve-outs, response helpers, etc.).

Scope covers: refactoring (Passes 2-10), security (Pass 11, 16, 24),
database performance (Pass 12), frontend performance (Pass 13, 18, 21),
developer efficiency and tests (Pass 14, 22), accessibility (Pass 15, 28),
observability (Pass 17), operational resilience (Pass 19), schema migrations
(Pass 20), correctness bugfixes surfaced by the 2026-04-23 multi-agent
independent review (Pass 23), input hardening / SSRF / size caps (Pass 25),
scraper HTTP uniformity (Pass 26), multi-user data ownership (Pass 27), and
frontend defense in depth (Pass 29).  See "Scope notes" near the bottom for
items deliberately excluded, and "Periodic Independent Review" at the very
end for the cadence on re-running the multi-agent audit that populated
Passes 23-29.

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
- [x] **Pass 18 — Image pipeline modernization** — Three-item sweep
  landed as v2.88.0. 244 tests pass (was 226); 18 new tests in
  `tests/test_image_pipeline.py`.
    - **18.1** WebP on ingest. New `RETRODB_IMAGE_FORMAT` config (default
      `webp`) + `services.image_utils.preferred_image_extension()` helper
      routed through every scraper filename construction: `scrape_igdb.py`,
      `scrape_thegamesdb.py`, and 9 inline sites in `metadata_merger.py`
      (IGDB / RAWG / ScreenScraper). Download path ends with new
      `finalize_downloaded_image(path, image_type)` which re-encodes bytes
      when the on-disk format doesn't match the filename extension (so
      JPEG-payload-in-`.webp`-path re-saves as WebP) + standardizes size +
      generates responsive variants. GIFs preserved; videos and manuals
      untouched.
    - **18.2** `loading="lazy" decoding="async"` on every `<img>` inside a
      card / list render path: both JS card renderers
      (`all-games-controller.js`, `game-modals.js` screenshot carousel)
      plus 12 template grids (dashboard, achievements, trophies, lists,
      wishlist, game detail screenshot row). Above-the-fold hero boxart
      kept eager + annotated `decoding="async" fetchpriority="high"` for
      LCP. Native browser-level lazy loading replaces the never-written
      scroll-observer the roadmap noted was missing.
    - **18.3** Responsive `srcset` for boxart. New
      `_make_responsive_variants(path, image_type)` writes `-sm` (160w) +
      `-md` (320w) Lanczos-downscaled siblings on ingest and during the
      bulk `ImageResizeJob`. New `boxart_srcset(filename)` Jinja global
      skips missing variant siblings so the browser never gets a 404
      candidate. Wired into the `game_detail.html` hero `<img>` with
      `sizes="(max-width: 768px) 160px, 320px"`. Grid-card integration
      deferred — per-card srcset on a 500-item page would mean 500
      filesystem `stat` calls; flagged as a follow-up (batch cache
      required). Follow-up entry: "Pass 18.3 — srcset for card grids".
- [x] **Pass 16 — HTTP security headers expansion** — Four-item sweep
  landed as v2.87.0. 226 tests pass (was 211); 15 new tests in
  `tests/test_security_headers.py`.
    - **16.1** Removed deprecated `X-XSS-Protection`. Modern OWASP
      guidance after Chromium removed the XSS Auditor.
    - **16.3** Added `Permissions-Policy` opting out of 11 unused
      browser APIs (camera / microphone / geolocation / payment / usb /
      interest-cohort / browsing-topics / accelerometer / gyroscope /
      magnetometer / midi).
    - **16.4** Added `Strict-Transport-Security` env-gated by
      `SESSION_COOKIE_SECURE` (so it only fires when the operator has
      flagged TLS is in front). `max-age=31536000; includeSubDomains`.
    - **16.2** Added `Content-Security-Policy` in **Report-Only** mode.
      Per-request nonce via `secrets.token_urlsafe(16)` generated in
      the existing `assign_request_id` hook (reused instead of a
      second `before_request`), exposed to templates via
      `{{ csp_nonce }}` through the `inject_config` context processor.
      Policy: `default-src 'self'`; `script-src 'self' 'nonce-...'
      https://cdn.jsdelivr.net` (Chart.js); `style-src 'self'
      'unsafe-inline' https://fonts.googleapis.com`; `img-src 'self'
      data: blob:`; `font-src 'self' https://fonts.gstatic.com`;
      `object-src 'none'`; `frame-ancestors 'self'`; `base-uri 'self'`;
      `form-action 'self'`. Intentionally report-only while ~765 inline
      `on*` handlers and ~38 inline `<script>` blocks still exist —
      follow-up template migration pass flips to enforcing once
      handlers are refactored to delegated listeners. (v2.87.0)
- [x] **Pass 17 — Observability & health checks** — Three-item sweep
  landed as v2.86.0. 211 tests pass (was 199); 12 new tests in
  `tests/test_observability.py`.
    - **17.1** `/health` and `/ready` probes inline in `app.py`.
      `/health` is cheap (no DB, returns version + status). `/ready` runs
      `SELECT 1` and returns 503 with error text on DB failure. Both
      exempted from first-time-setup redirect and slow-request logging.
    - **17.2** Request correlation IDs. `log_manager.install_request_id_factory()`
      installs a `setLogRecordFactory` wrapper that stamps `record.request_id`
      from `flask.g.request_id` (or `'-'` outside a request context). New
      `assign_request_id` before_request hook sets `g.request_id = secrets.token_hex(4)`.
      `basicConfig` and `CategoryFileHandler` format strings updated to
      include `%(request_id)s`. Single-grep log correlation across
      services.
    - **17.3** Slow-request middleware. `log_slow_request` after_request
      hook warns when handler elapsed > `config.SLOW_REQUEST_MS`
      (default 500 ms, env-overridable via `RETRODB_SLOW_REQUEST_MS`, 0
      disables). Probe endpoints exempted. Pairs with the existing
      `SLOW_QUERY_MS` DB-layer check. (v2.86.0)
- [x] **Pass 19.1 + 19.3 — SQLite online backup + retention** — Replaced
  `shutil.copy2(config.DB_PATH, ...)` in `routes/settings.py::api_backup`
  and the pre-restore snapshot in `api_restore` with a new
  `services.database.backup_database(src, dst)` helper that uses
  `sqlite3.Connection.backup()` — the SQLite online backup API, which
  coordinates with WAL and produces a consistent snapshot under concurrent
  writes. Always followed by `PRAGMA integrity_check`; the destination is
  removed and the call raises if the check fails, so no broken backup is
  ever handed back. New `config.MAX_BACKUPS` (default 30, env-overridable
  via `RETRODB_MAX_BACKUPS`) + `_prune_old_backups()` sweep after each
  successful backup. `pre_restore_*.db` snapshots are exempt and never
  pruned (recovery safety net). 9 new regression tests
  (`tests/test_database_backup.py`, `tests/test_backup_rotation.py`); 259
  total pass (was 250). End-to-end smoke against the live 39 MB DB clean.
  (v2.89.0)
- [x] **Pass 23 — Correctness bugfixes (2026-04-23 multi-agent review)** —
  Eight runtime bugs fixed; 250 tests pass (was 244); 6 new regression
  tests in `tests/test_hybrid_scraper.py`. Landed as v2.88.1.
    - **23.1** `scraper/hybrid_scraper.py` AttributeError on
      `scraper_manager._calculate_title_match_score` (function moved to
      `scraper/match_scorer.py` during Pass 6 but call sites missed) —
      swapped both call sites to the module-level
      `calculate_title_match_score`. The error was being swallowed by an
      outer `except` and silently returning empty fallback data in
      production.
    - **23.9** New `tests/test_hybrid_scraper.py` exercises
      `_pick_best_fallback` / `_pick_best_secondary` against the real
      scorer (no mocking) so the 23.1 bug cannot re-land.
    - **23.2** RAWG `apply_rawg_to_metadata` aligned with
      TGDB/IGDB/ScreenScraper fill-only semantics — only `title`
      overwrites on primary. `tests/test_metadata_merger.py` updated to
      pin the corrected behaviour.
    - **23.3** Collapsed inline RP-as-empty cross-map loop in
      `hybrid_scraper.py` to a 9-line wrapper around
      `services.game_metadata_service.cross_map_ratings()` — single
      source of truth restored.
    - **23.4** `routes/games_search.py:149` — materialised
      `seen_ids_list = list(seen_ids)` once so `NOT IN` placeholder count
      and bind values use the same iteration order.
    - **23.5** `services/game_query.py:235` — added explicit inner
      parens around the `source=rom` AND chain so the OR-with-NULL is
      visually unambiguous.
    - **23.6** `services/media_cleanup.py:115` — pointed manuals orphan
      sweep at `IMAGE_PATH/manuals` (matches scraper output and
      `_MEDIA_LAYOUT`); was scanning `STATIC_PATH/manuals` which never
      existed.
    - **23.7** `services/image_utils.py::_save_image` — early-return on
      `.gif` so animated GIFs are never re-encoded to first frame.
    - **23.8** `config.example.py` resynced with `config.py` (15
      missing IGDB platform mappings + 95 missing `SYSTEM_SPECS`
      entries). (v2.88.1)
- [x] **Pass 15 — Accessibility (WCAG 2.2 AA)** — Five-item sweep landed
  as v2.85.0. 199 tests still pass; no regressions.
    - **15.1** Skip-to-main-content link. `base.html` now starts with
      `<a href="#main-content" class="skip-link">` as the first focusable
      element; visually hidden until focused (`.skip-link` rule in
      `components/buttons.css`). `<main>` gained `id="main-content"` and
      dropped redundant `role="main"`.
    - **15.2** Modal focus trap. New `ModalFocusTrap` helper in
      `utils.js` (activate/deactivate/deactivateAll, stacked for nested
      modals, onEscape callback, focus restore to trigger). Wired into
      GameDetail/GameEdit modals, showModal/confirmModal/closeModal,
      folder browser, queue manager, bulk-edit and bulk-scrape modals.
      Most modal roots already had `role="dialog" aria-modal="true"`.
    - **15.3** Theme contrast audit. New `scripts/audit_contrast.py`
      parses `variables.css` + `themes.css`, resolves `var()`, computes
      WCAG contrast ratios for 12 pairs × 7 themes → `docs/theme_contrast.md`.
      Initial run found 2 FAILs in bladerunner theme
      (`--text-muted: #505868` at 2.80:1); bumped to `#78809a` for
      5.10:1. All 7 themes now clear 4.5:1 body / 3.0:1 UI thresholds.
    - **15.4** Two redundant ARIA patterns fixed: `<main role="main">`
      → `<main>` and `<aside class="sidebar" role="navigation">` →
      `<nav class="sidebar">` (all selectors were `.sidebar`, no CSS
      ripple). `<div role="navigation">` on alphabet-nav kept — `<div>`
      has no implicit role so the attribute is meaningful.
    - **15.5** Keyboard shortcut overlay refactored to auto-generate
      from a single source of truth. Each entry in
      `KeyboardShortcuts.shortcuts`/`gameShortcuts` gained a `category`
      field; `showShortcutsModal()` builds rows by iterating the dicts.
      Added `role="dialog" aria-modal="true" aria-labelledby` + focus
      trap + friendly key-label map (Escape → Esc, ArrowLeft → ←, etc).
      New shortcuts auto-document. (v2.85.0)
- [x] **Pass 14 (partial) — Developer efficiency & test coverage** —
  Two-item sweep; 14.2 (gradual type hints) deferred as a separate
  LOW-priority future pass. Landed as v2.84.3.
    - **14.1** Pre-commit hooks. New `.pre-commit-config.yaml` wires
      `astral-sh/ruff-pre-commit` (ruff check with `--fix`, reading
      `pyproject.toml`'s E/F/B/S rule set) and `gitleaks/gitleaks`
      (using the existing `.gitleaks.toml` allowlist). `ruff-format`
      was dropped from the initial wiring because the repo is not
      format-clean today (101 files would reformat); adopting format
      is its own future pass. `pytest` / `mypy` intentionally stay in
      CI, not pre-commit. Install locally with
      `pip install pre-commit --break-system-packages` then
      `pre-commit install`.
    - **14.3a** Characterisation tests for
      `scraper/metadata_merger.py` (1090 LOC, 0 → 30 tests). New
      `tests/test_metadata_merger.py` pins all 5 apply functions
      (TGDB, IGDB, RAWG, ScreenScraper, AI): fill_only semantics,
      TGDB ESRB/PEGI regex parsing, IGDB age-rating category map,
      IGDB extended fields, RAWG release-date ISO truncation,
      ScreenScraper region-priority + 0-20 → 0-100 note conversion,
      AI VALIDATE_FIELDS override, AI score coercion.
    - **14.3b** State-machine tests for
      `services/jobs/bulk_scrape.py` (980 LOC, 0 → 24 tests). New
      `tests/test_bulk_scrape_job.py` pins the `BulkScrapeJob`
      transitions: start/queue/pause/resume/cancel + queue management
      (`cancel_queued`, `cancel_all_queued`, `promote_queued`,
      `demote_queued`) + duplicate-rejection (same system + same mode).
      Real `_run_scrape` thread target stubbed; `_get_conn()` patched
      to an in-memory SQLite with minimal fixtures.
    - **14.2 (deferred)** Gradual type hints on `metadata_merger.py`,
      `game_query.py`, `routes/games.py` — LOW priority / L sized; a
      full pass in its own right. Pushed to a later pass.
    Net: 199 tests pass (was 145); 54 new tests; full suite green;
    ruff + gitleaks pre-commit hooks both pass on the tree. (v2.84.3)
- [x] **Pass 13 — Frontend performance** — Three-item sweep landed as
  v2.84.2.
    - **13.1** Streaming image downloads. `scraper/base_scraper.py::
      download_image` switched to `requests.get(..., stream=True)` +
      `iter_content(chunk_size=8192)` so the full response body is no
      longer materialised in memory before write. Same pattern applied
      to the two PSN image downloaders in `services/jobs/base.py`.
      One lingering buffered spot at `scrape_thegamesdb.py:1006` — it
      goes through `http_get()` which returns the full Response, so a
      refactor is needed; noted in the changelog.
    - **13.2** Split single 271 KB `app.bundle.js` into
      `core.bundle.js` (144 KB — utils, page-lifecycle,
      toast-controller, main) + `games.bundle.js` (127 KB — filters,
      bulk-scrape, bulk-edit, game-list, game-modals).  Core loads on
      every page; games loads only on 13 templates that opt in via
      `{% set needs_games_bundle = true %}`.  Non-games pages
      (dashboard, settings, logs, museum, help, changelog, login,
      setup, analytics, &hellip;) now ship 127 KB less JS per load.
      `build_js.py` auto-removes the legacy bundle.
    - **13.3** Per-file content-hash cache-busting.  `build_css.py` +
      `build_js.py` now write `static/asset_manifest.json` mapping each
      built file to its SHA-256[:8].  New
      `services/assets.py::asset_url(path)` appends `?v=<hash>` to the
      static URL (mtime-cached manifest with lock; falls back to
      `?v={APP_VERSION}` on miss).  Registered as Jinja global +
      context processor entry; `base.html` uses it for the 3 bundle
      URLs.  CSS-only changes no longer bust JS cache, and vice versa.
      5 new tests in `tests/test_assets.py`.
    Net: 145 tests pass (was 140); smoke render-tests confirm
    dashboard omits the games bundle and all_games includes it.
    (v2.84.2)
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
- **Status**: done (v2.84.2) — `scraper/base_scraper.py::download_image`
  switched to `stream=True` + `iter_content(chunk_size=8192)`.  Same pattern
  applied to both PSN image downloaders in `services/jobs/base.py`.
  `scrape_thegamesdb.py:1006` still buffers because it goes through the
  non-streaming `http_get()` — noted as a follow-up.

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
- **Status**: done (v2.84.2) — `build_js.py` now emits `core.bundle.js`
  (144 KB minified) + `games.bundle.js` (127 KB minified), auto-removes the
  legacy single bundle.  13 templates opt in via the Jinja var.  Non-games
  pages (dashboard, settings, logs, museum, help, changelog, login, setup,
  analytics) now ship 127 KB less JS per page load.

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
- **Status**: done (v2.84.2) — `static/asset_manifest.json` written by both
  builders; `services/assets.py::asset_url(path)` reads it (mtime-cached
  with lock) and appends `?v=<hash>`.  Falls back to `?v={APP_VERSION}` on
  manifest miss or corrupt JSON.  Registered as Jinja global + context
  processor entry.  5 tests in `tests/test_assets.py`.

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
- **Status**: done (v2.84.3) — `.pre-commit-config.yaml` wires ruff-check +
  gitleaks. `ruff-format` was dropped from the initial wiring because the
  repo is not currently format-clean (101 files would reformat); adopting
  format is a separate future pass.

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
- **Status**: done (v2.84.3) — `tests/test_metadata_merger.py` (30 tests)
  pins all 5 `apply_*_to_metadata()` functions; `tests/test_bulk_scrape_job.py`
  (24 tests) pins the BulkScrapeJob state machine (start/queue/pause/resume/
  cancel + queue management + duplicate-rejection). 54 new tests, total 199.

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
- **Status**: done (v2.85.0) — `<a href="#main-content" class="skip-link">`
  is now the first focusable element in `base.html`; `.skip-link` rule in
  `components/buttons.css`; `<main>` gained `id="main-content"` and dropped
  its redundant `role="main"`.

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
- **Status**: done (v2.85.0) — `ModalFocusTrap` helper added to `utils.js`
  (activate/deactivate/deactivateAll, stacked for nested modals, onEscape
  callback, restores focus to trigger element on close). Wired into
  `GameDetailModal`, `GameEditModal`, `showModal`/`confirmModal`/`closeModal`,
  `openFolderBrowser`/`closeFolderBrowser`, `openQueueManager`/`closeQueueManager`,
  `BulkEditController.open/close`, `BulkScrapeController.resetUI/closeModal/onComplete`.
  Most modal roots already had `role="dialog" aria-modal="true" aria-labelledby"`;
  this pass wired the focus-trap behavior behind them.

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
- **Status**: done (v2.85.0) — new `scripts/audit_contrast.py` parses
  `variables.css` + `themes.css`, resolves `var()`, computes WCAG ratios
  for 12 pairs × 7 themes. Output: `docs/theme_contrast.md` with
  PASS/NOTE/FAIL per theme. Initial run found 2 FAILs in bladerunner
  (`--text-muted: #505868` at 2.80:1); bumped to `#78809a` for 5.10:1.
  All 7 themes now clear 4.5:1 body text and 3.0:1 UI thresholds.

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
- **Status**: done (v2.85.0) — two redundant patterns fixed: `<main
  role="main">` → `<main>` (implicit role) and `<aside class="sidebar"
  role="navigation">` → `<nav class="sidebar">` (semantic element, no CSS
  ripple — all selectors were `.sidebar`). Kept `<div
  class="alphabet-nav" role="navigation">` on list pages — `<div>` has no
  implicit role so the attribute is meaningful.

### 15.5 Keyboard shortcut help overlay (LOW, S)

- **Target**: `static/js/main.js::KeyboardShortcuts` — document existing
  shortcuts in a `?` overlay.
- **Why**: discoverability. Help page has a shortcuts section, but in-app
  `?` overlay is a standard pattern (Gmail, GitHub, Linear) and takes ~40 LOC.
- **Plan**: bind `?` (Shift+/) to open a modal listing all registered
  shortcuts. Generate the list from a single source of truth so new
  shortcuts auto-document.
- **Status**: done (v2.85.0) — overlay already existed and was already
  bound to `?`, but its rows were hardcoded in HTML. Refactored
  `showShortcutsModal()` to build the body from
  `KeyboardShortcuts.shortcuts` + `.gameShortcuts` with a new `category`
  field on each entry (`'Navigation'` / `'Actions'` / `'Game Page'`),
  added `role="dialog"` + `aria-modal` + `aria-labelledby` + focus trap
  via Pass 15.2 `ModalFocusTrap`, and a `_SHORTCUT_KEY_LABELS` map so
  `Escape` / `ArrowLeft` / `ArrowRight` render as friendly glyphs.

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
- **Status**: done (v2.87.0)

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
- **Status**: done (v2.87.0) — shipped in Report-Only. `g.csp_nonce`
  generated inside the existing `assign_request_id` hook (no second
  `before_request`), surfaced via `inject_config` as `{{ csp_nonce }}`.
  Enforcing flip is a follow-up once the ~765 inline `on*` handlers and
  ~38 inline `<script>` blocks have been migrated to delegated listeners
  / nonced blocks. Allowed hosts: `cdn.jsdelivr.net` (Chart.js),
  `fonts.googleapis.com`, `fonts.gstatic.com`.

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
- **Status**: done (v2.87.0) — extended the baseline list with four
  more sensor/instrument APIs (`accelerometer`, `gyroscope`,
  `magnetometer`, `midi`) for 11 total.

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
- **Status**: done (v2.87.0)

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
- **Status**: done (v2.86.0)

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
- **Status**: done (v2.86.0) — implemented via `logging.setLogRecordFactory`
  instead of a `logging.Filter` so every `LogRecord` created anywhere in
  the process (including records from child loggers that propagate to
  root) carries `record.request_id` without needing per-handler filter
  wiring.

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
- **Status**: done (v2.86.0) — `config.SLOW_REQUEST_MS` defaults to 500 ms
  and is overridable via `RETRODB_SLOW_REQUEST_MS`; 0 disables.
  `assign_request_id` (17.2) already captures `g.request_start_time` so
  17.3 reuses that timer without a second `before_request` hook.

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
- **Status**: done (v2.88.0) — `RETRODB_IMAGE_FORMAT` config + new
  `services.image_utils.preferred_image_extension()` /
  `finalize_downloaded_image()` helpers. Every scraper filename-construction
  site (IGDB / TGDB / RAWG / ScreenScraper) now goes through the helper;
  `base_scraper.download_image()` + every inline download site calls
  `finalize_downloaded_image()` which re-encodes bytes to match the filename
  extension (handles the case where the URL served JPEG but the path is
  `.webp`), standardizes size, and generates responsive variants. Plan step 4
  (the bulk JPEG→WebP migration endpoint) was deliberately descoped for this
  pass — fresh scrapes land as WebP, and the bulk `ImageResizeJob` already
  re-saves via `_save_image()` so re-running it on an existing library will
  migrate formats opportunistically (filename extension is preserved though;
  a dedicated DB-filename-rewriting endpoint is a follow-up).

### 18.2 `loading="lazy"` + `decoding="async"` on game-card images (MEDIUM, S)

- **Target**: `static/js/all-games-controller.js` (card render), `static/js/game-modals.js`
  (screenshot carousel), plus any template loops over `<img>`.
- **Why**: on pages with 500+ cards the browser fetches every image
  eagerly until JS scroll-observer kicks in. Native `loading="lazy"` is
  free to add and has been baseline-supported since 2022.
- **Plan**: add both attributes to every `<img>` inside a card / list
  render path. First image on the page (above-the-fold boxart) can remain
  eager via `loading="eager"` to avoid LCP regression.
- **Status**: done (v2.88.0) — applied to both JS card renderers
  (`all-games-controller.js` + `game-modals.js`) and 12 template grids
  (dashboard, achievements, trophies, lists, wishlist, game detail
  screenshot row + filter modal thumbs). Above-the-fold hero boxart on
  `game_detail.html` kept eager but annotated
  `decoding="async" fetchpriority="high"` for LCP.

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
- **Status**: done (v2.88.0), grid integration is a follow-up —
  `_make_responsive_variants(path, image_type)` writes `-sm` (160w) and
  `-md` (320w) siblings on both the scrape path (via
  `finalize_downloaded_image`) and the bulk `ImageResizeJob` so backfills
  happen automatically. `boxart_srcset(filename)` Jinja global does
  per-candidate filesystem existence checks so missing variants never 404
  the browser. Wired into `game_detail.html` hero `<img>` with
  `sizes="(max-width: 768px) 160px, 320px"`. **Grid-card srcset deferred**
  — emitting per-card srcset on a 500-item page would mean 500 filesystem
  `stat` calls per render; needs a batched existence cache (one
  `os.scandir` of `images/boxart/` per request, membership test per card)
  before it's safe to flip on in `all-games-controller.js`. Flagged as
  follow-up "Pass 18.3 — srcset for card grids" in the new Done entry
  above.

---

## Pass 19 — Operational resilience

### 19.1 SQLite online backup API (HIGH, M)

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
- **Status**: done (v2.89.0) — landed as `services/database.backup_database()`,
  used by both `api_backup` and the pre-restore snapshot in `api_restore`. 4
  regression tests in `tests/test_database_backup.py`.

### 19.2 Graceful shutdown — mark jobs paused on SIGTERM (MEDIUM, M)

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

### 19.3 Backup rotation / max-backups knob (LOW, S)

- **Target**: `routes/settings.py::api_backup` — currently unbounded.
- **Why**: on a deploy that auto-backups daily, the `backups/` dir grows
  without limit. Each backup is ~10-500 MB depending on library size.
- **Plan**: after creating a new backup, if the count exceeds
  `MAX_BACKUPS` config (default 30), delete the oldest N. Keep at least
  one always.
- **Status**: done (v2.89.0) — `config.MAX_BACKUPS` (env-overridable via
  `RETRODB_MAX_BACKUPS`) + `_prune_old_backups()` after each successful
  backup. `pre_restore_*` snapshots are exempt and never pruned. 5
  regression tests in `tests/test_backup_rotation.py`.

### 19.4 Fix `BulkScrapeJob.swap_with_running` / `demote_running` cancel+reset race (MEDIUM, S)

- **Target**: `services/jobs/bulk_scrape.py:375-414, 451-490`.
- **Why**: current code sets `cancelled=True` then sleeps 0.5 s and calls
  `reset()` — if the worker hasn't observed the cancel flag yet, it wakes,
  reads `cancelled=False`, and keeps processing the new job's first game as
  if it were the old job's (mixing `current_game_title` and counters).
- **Plan**: replace `time.sleep(0.5)` with `self._thread.join(timeout=...)`
  so the new state is only written once the worker has actually exited its
  current iteration.
- **Source**: 2026-04-23 audit, Jobs subsystem finding 3.
- **Status**: todo

### 19.5 Bring `MuseumGenerateJob` up to the persistence contract (MEDIUM, M)

- **Target**: `services/jobs/museum.py` (add persistence), plus dedup the
  duplicate `museum_generate_job` singleton declared at both
  `services/jobs/__init__.py:46` and `services/jobs/museum.py:404`.
- **Why**: every other job in scope calls
  `persist_job_start/progress/complete` + defines `resume_from_params` so
  the dashboard's `/api/jobs/resume/<id>` can rehydrate after a crash.
  Museum doesn't — a mid-run museum generation silently dies on restart.
  And the double-singleton means whichever import order loses ships
  divergent state.
- **Plan**: mirror the `bulk_scrape` / `ra_sync` persistence pattern; pick
  one of the two singletons (keep `__init__.py:46`, delete the other); also
  take `self._lock` in `get_status()` (museum.py:78-93).
- **Source**: 2026-04-23 audit, Jobs subsystem finding 1.
- **Status**: todo

### 19.6 `job_queue` retention sweep (LOW, S)

- **Target**: `services/jobs/base.py` — add a startup sweep.
- **Why**: `job_queue` grows unbounded — every completed/failed/dismissed
  job stays forever.  On a long-running install this table accumulates
  indefinitely.
- **Plan**: on app start (or via a periodic scheduler), run `DELETE FROM
  job_queue WHERE status IN ('completed','failed','dismissed') AND
  completed_at < date('now', '-30 days')`.  Config knob
  `JOB_HISTORY_RETENTION_DAYS` default 30.
- **Source**: 2026-04-23 audit, Jobs subsystem gap 3.
- **Status**: todo

### 19.7 Atomic settings file writes (MEDIUM, S)

- **Target**: `services/settings_manager.py:196`, `routes/scraper.py:168`,
  `routes/scraper.py:196`.
- **Why**: plain `open('w') + json.dump` — a crash or power loss mid-write
  truncates `settings.json` / `scraper_settings.json`, wiping the user's
  API keys and paths.
- **Plan**: write to `<path>.tmp` in the same directory, `os.fsync(fd)`
  before close, `os.replace(tmp, final)`.  Single helper function, reused
  by both settings modules.
- **Source**: 2026-04-23 audit, Maintenance subsystem finding 1.
- **Status**: todo

### 19.8 Guard `database_init.py` PSN ALTERs on table existence (MEDIUM, S)

- **Target**: `services/database_init.py:267-291` — `ALTER TABLE psn_games`
  / `psn_sync_status` runs unconditionally, but those tables are created
  elsewhere (first `/trophies` visit).
- **Why**: on a fresh DB the ALTERs raise `OperationalError: no such
  table` on every app start, swallowed by the bare `except` block.
  Silently masks real schema drift and adds noise to Sentry-style error
  surfaces if one is ever wired in.
- **Plan**: `SELECT name FROM sqlite_master WHERE type='table' AND
  name=?` gate before each ALTER, or move the CREATE TABLE for both PSN
  tables into `database_init.py` so ordering is explicit.
- **Source**: 2026-04-23 audit, Database subsystem finding 1.
  Properly fixed only by Pass 20 (schema_version table) — this is the
  stopgap.
- **Status**: todo

---

## Pass 20 — Versioned schema migrations

### 20.1 Replace ad-hoc `_migrate_*` with `PRAGMA user_version` (MEDIUM, M)

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

### 20.2 Document migration authoring in standards doc (LOW, S)

- **Target**: `docs/RETRODB_DESIGN_STANDARDS.md` — add §25 after the
  naming standards.
- **Why**: the above pattern needs a one-page rulebook: file naming, no
  editing past migrations, how to handle data migrations vs schema.
- **Plan**: short section covering filename format (`NNN_description.sql`),
  idempotency rules, and the "migrations are append-only once shipped"
  invariant.
- **Status**: todo (follows 20.1)

---

## Pass 21 — Request-level caching & ETags

> **Depends on Pass 20** — the ETag scheme in 21.1 hinges on every game write touching `updated_at`.  Landing Pass 20 first lets any missing trigger / column be added as an auditable migration rather than an ad-hoc `_migrate_*` graft.

### 21.1 ETag / `If-None-Match` on `/api/games/card-data` (MEDIUM, M)

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

### 21.2 Response compression (LOW, S)

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

### 21.3 Per-file cache-busting hash — consolidate with Pass 13.3 (N/A)

See Pass 13.3 — no duplicate entry.

---

## Pass 22 — CI/CD hardening

### 22.1 Dependabot config for pip + GitHub Actions (MEDIUM, S)

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

### 22.2 `pip-audit` in CI (MEDIUM, S)

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

### 22.3 Coverage reporting via `pytest-cov` (LOW, S)

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

### 22.4 Python version matrix (LOW, S)

- **Target**: `.github/workflows/ci.yml` — add matrix for 3.12 + 3.13.
- **Why**: CI pins 3.13 only. Users on long-term distros (Debian stable,
  openSUSE Leap) are often on 3.11-3.12 — a regression on those Pythons
  wouldn't be caught. Keep 3.13 on the list (JIT coming).
- **Plan**: `strategy.matrix.python-version: [ "3.12", "3.13" ]`. Do NOT
  include 3.14 free-threaded — research confirms it hurts single-threaded
  Flask perf 30-50%.
- **Source**: <https://codspeed.io/blog/state-of-python-3-13-performance-free-threading>
- **Status**: todo

### 22.5 Wire CI semgrep to the calibrated `.semgrep.yml` (MEDIUM, S)

- **Target**: `.github/workflows/ci.yml:44-56`.
- **Why**: `.semgrep.yml` documents 13 excluded rule IDs with rationale,
  but CI invokes semgrep with raw upstream packs — none of the exclusions
  apply.  The documented "calibrated audit" and the actual CI scan have
  drifted apart.
- **Plan**: pass `--config .semgrep.yml` (or loop the documented
  `--exclude-rule` list) so the CI run matches the documented threat
  model.  Alternative: delete the exclusion-list documentation if the
  intent really is "upstream packs only in CI."
- **Source**: 2026-04-23 audit, Tests/Tooling/CI finding 1.
- **Status**: todo

### 22.6 Signed release artifacts + provenance (MEDIUM, M)

- **Target**: `.github/workflows/release.yml:74-80`.
- **Why**: current workflow ships ZIPs with no checksum, no signing, no
  SLSA attestation, no SBOM.  Downstream (Patreon) recipients can't
  verify the ZIP came from this workflow.
- **Plan**: add `actions/attest-build-provenance` after the build step to
  emit signed provenance; add `cosign sign-blob --yes` (keyless OIDC) for
  each ZIP; add `cyclonedx-py` or `syft` to emit an SBOM alongside each
  ZIP.  Pin the third-party actions by SHA (currently
  `softprops/action-gh-release@v2` floats).
- **Source**: 2026-04-23 audit, Tests/Tooling/CI finding 2.
- **Status**: todo

### 22.7 Destructive-endpoint coverage for `routes/games_media.py` (MEDIUM, M)

- **Target**: `tests/test_games_media.py` (new).
- **Why**: `/api/delete-game`, `/api/rename-rom`, `/api/delete-screenshot`
  currently have only auth-redirect assertions in
  `tests/test_routes_smoke.py:57-59`.  Zero coverage for path-traversal
  on `rom_path`, role-separation (admin vs editor vs viewer), or
  cascade cleanup of screenshot rows.  These endpoints can irreversibly
  destroy user data.
- **Plan**: spin a fixture DB with test games, exercise each endpoint
  under each role, assert both the positive (admin succeeds) and
  negative (viewer gets 403) paths.  Include one `..` traversal probe
  on `rename-rom`.
- **Source**: 2026-04-23 audit, Tests/Tooling/CI finding 3.
- **Status**: todo (lands with Pass 24 authz tightening)

### 22.8 Lockfile-drift test (LOW, S)

- **Target**: `tests/test_lockfile.py` (new), or a CI-only `make` target.
- **Why**: CLAUDE.md workflow rule #5 says "Regenerate lockfile if
  requirements.txt was edited" but it's honor-system.  A PR that bumps
  `requirements.txt` without regenerating `requirements.lock` lands
  silently.
- **Plan**: CI step that runs `pip-compile requirements.txt -o
  /tmp/fresh.lock --strip-extras` and fails if `diff
  requirements.lock /tmp/fresh.lock` is non-empty.
- **Source**: 2026-04-23 audit, Tests/Tooling/CI gap 7.
- **Status**: todo

---

## Pass 23 — Correctness bugfixes (2026-04-23 multi-agent review)

> **Land first.**  These are real runtime bugs silently degrading every
> install; no architectural dependencies; most are one-to-few-line fixes.

### 23.1 Fix `scraper_manager._calculate_title_match_score` AttributeError (CRITICAL, S)

- **Target**: `scraper/hybrid_scraper.py:96, 147`.
- **Why**: after the Pass 6 scraper split, the method moved to module-level
  `calculate_title_match_score` in `scraper/match_scorer.py` but wasn't
  re-attached to `scraper_manager`.  Every `_pick_best_fallback` /
  `_pick_best_secondary` call path raises `AttributeError`, gets caught by
  the outer `except Exception as fallback_error`, and silently returns
  zero fallback data with only a generic "Fallback scraper X failed"
  warning in logs.  This is live, invisible, and running in production.
- **Plan**: `from scraper.match_scorer import calculate_title_match_score`
  at the top of `hybrid_scraper.py`, swap the two call sites.
- **Source**: 2026-04-23 audit, Scraper Orchestration finding 1.
- **Status**: done (v2.88.1)

### 23.2 Align RAWG `apply_rawg_to_metadata` with fill-only semantics (HIGH, S)

- **Target**: `scraper/metadata_merger.py:462-519`.
- **Why**: every field uses `(not metadata[X] or not fill_only)` — when
  RAWG is the primary source this overwrites publisher / developer /
  release_date / description / genre / players / modes / ESRB / critic /
  user score even if those already hold curated or cross-source data.
  TGDB / IGDB / ScreenScraper only overwrite `title` on primary; RAWG is
  the odd one out, contradicting CLAUDE.md's "media fields never
  replaced" contract and surprising users who re-scrape.
- **Plan**: collapse the `(not metadata[X] or not fill_only)` pattern to
  `not metadata[X]` for everything except `title`, matching the other
  three per-source applies.
- **Source**: 2026-04-23 audit, Scraper Orchestration finding 2.
- **Status**: done (v2.88.1)

### 23.3 Collapse duplicate rating cross-map in `hybrid_scraper.py` (MEDIUM, S)

- **Target**: `scraper/hybrid_scraper.py:1224-1246`.
- **Why**: reimplements the `RP`-as-empty tier-mapping loop that lives in
  `services/game_metadata_service.cross_map_ratings`.  Two sources of
  truth now; any change to `_RP_VALUES` or tier-map semantics has to be
  synced across both.  CLAUDE.md already names `cross_map_ratings` as
  the single API.
- **Plan**: delete the inline loop, call `cross_map_ratings(metadata)`
  after normalizing the key convention (the inline version uses
  `db_column` keys; the service uses bare system keys — pick one, stick
  with it).
- **Source**: 2026-04-23 audit, Scraper Orchestration finding 2 (spec).
- **Status**: done (v2.88.1)

### 23.4 Fix `api_similar_games` set-iteration ordering bug (MEDIUM, S)

- **Target**: `routes/games_search.py:149-155`.
- **Why**: builds `NOT IN ({placeholders})` from `seen_ids` (a `set`),
  then binds `list(seen_ids)`.  The two iterations of the set are not
  guaranteed to produce the same order across calls in CPython — the
  `NOT IN` filter can silently exclude the wrong game IDs (or none at
  all).  Appears to work today because the set happens to iterate
  consistently within one call, but this is a correctness landmine.
- **Plan**: assign `seen_ids_list = list(seen_ids)` once, use that same
  list both for placeholder-count and bind values.
- **Source**: 2026-04-23 audit, Game Routes finding 8.
- **Status**: done (v2.88.1)

### 23.5 Fix `source=rom` filter precedence (LOW, S)

- **Target**: `services/game_query.py:235`.
- **Why**: `A AND B AND C OR D` parses as `(A AND B AND C) OR D` so a
  `NULL` `rom_path` row appears under every `source=` filter, not just
  the intended one.
- **Plan**: add explicit parentheses: `AND (… OR g.rom_path IS NULL)`.
- **Source**: 2026-04-23 audit, Game Routes finding 9.
- **Status**: done (v2.88.1)

### 23.6 Fix `media_cleanup.py` manuals path divergence (MEDIUM, S)

- **Target**: `services/media_cleanup.py:28` vs `:115`.
- **Why**: `_MEDIA_LAYOUT` claims manuals live under `IMAGE_PATH/manuals`
  but `find_orphaned_media` scans `STATIC_PATH/manuals`.  Per-game
  deletion and orphan detection hit different directories — manuals are
  silently bypassed by the orphan sweep.
- **Plan**: pick one canonical location (whichever matches the actual
  scraper output — verify via `base_scraper.download_image`), update both
  references to match.
- **Source**: 2026-04-23 audit, Image Pipeline finding 1.
- **Status**: done (v2.88.1)

### 23.7 Preserve GIF animation in `_save_image` (MEDIUM, S)

- **Target**: `services/image_utils.py:751`.
- **Why**: `img.save(path, 'GIF')` without `save_all=True, append_images=...`
  flattens animated GIFs to first frame.  `preferred_image_extension`
  preserves `.gif` correctly, but any touch by the pipeline
  (re-encode, variant generation, standardization) destroys the
  animation.
- **Plan**: either pass `save_all=True, append_images=list(ImageSequence.Iterator(img))[1:]`
  for GIF, or branch GIF to a dedicated "copy without re-encode" path.
  The latter is simpler and also avoids quality loss.
- **Source**: 2026-04-23 audit, Image Pipeline finding 3.
- **Status**: done (v2.88.1)

### 23.8 Sync `config.example.py` with `config.py` system mappings (MEDIUM, S)

- **Target**: `config.example.py`.
- **Why**: `config.py` has IGDB platform entries (atarist:63, atari800:65,
  zxspectrum:26, amstradcpc:25, msx/msx2, bbcmicro:69, apple2:75,
  x68000:121, pc88:125, pc98:149, fmtowns:118, sg-1000:84, neogeocd:136,
  supergrafx:128) plus extra `SYSTEM_SPECS` entries (famicom, fds, …)
  that `config.example.py` lacks.  Fresh installs silently miss these
  mappings — scraped metadata for those platforms drops back to
  per-name fuzzy lookup.  This is the same class of bug that broke CI
  in the Pass 18 ship (missing `IMAGE_SKIP_TYPES`).
- **Plan**: diff the two files constant-by-constant, backfill
  `config.example.py`.  Add a CI test (22.8-adjacent) that fails if
  top-level constants diverge.
- **Source**: 2026-04-23 audit, Core App finding 7.
- **Status**: done (v2.88.1)

### 23.9 Fix `_calculate_title_match_score` call-site coverage test gap

- **Target**: `tests/test_hybrid_scraper.py` (new or extension).
- **Why**: 23.1 above is a regression that landed undetected through the
  Pass 6 split — tests mocked too aggressively.  Without a test that
  exercises `_pick_best_fallback` against a real
  `calculate_title_match_score`, the bug can re-land.
- **Plan**: add a test that constructs a minimal fallback scenario, runs
  `_pick_best_fallback`, and asserts the `AttributeError` is *not*
  raised and a scored result comes back.
- **Source**: 2026-04-23 audit, meta.
- **Status**: done (v2.88.1, landed alongside 23.1)

---

## Pass 24 — Multi-user authn/authz hardening

> **Severity caveat.**  Under the single-user-localhost threat model
> (see §Notes below) these are LOW.  Under the documented multi-user
> role model (admin / editor / viewer in `services/auth.py:26-28`) they
> are HIGH because a viewer can currently assume any editor identity.
> Land if you actually use multi-user mode.  If you don't, skip to
> Pass 25.

### 24.1 Require a password for editor and viewer roles (HIGH-in-multi-user, M)

- **Target**: `routes/auth.py:59-81`.
- **Why**: `api_login` skips password verification entirely for any
  `role in ('editor','viewer')` and sets `session['user_id']` on the
  POSTed ID.  Combined with `/login` enumerating users + roles
  (`routes/auth.py:35-41`), anyone reaching `/api/login` assumes any
  non-admin identity.  Editors hold `edit`, `delete_metadata`, and
  `scrape` permissions — full authentication bypass.
- **Plan**: remove the passwordless branch; require `verify_password`
  for every role.  Migration path: on first login after the change,
  prompt editor/viewer accounts to set a password (mirroring the
  admin `force_password_change` flow).
- **Source**: 2026-04-23 audit, Auth & Security finding 1.
- **Status**: todo

### 24.2 Session rotation on login (LOW-single-user, HIGH-multi-user, S)

- **Target**: `routes/auth.py:81`.
- **Why**: `session['user_id'] = user['id']` without calling
  `session.regenerate()` / equivalent.  Any pre-login session data
  (including an attacker-set cookie) survives the auth boundary —
  session fixation.
- **Plan**: Flask doesn't expose a built-in `regenerate()`, so clear
  then re-set: `session.clear(); session.permanent = True;
  session['user_id'] = user['id']`.  Add a CSRF-token rotation call
  here once Pass 29 lands.
- **Source**: 2026-04-23 audit, Auth & Security finding 3.
- **Status**: todo

### 24.3 Force password change for default-`changeme` admins (MEDIUM, S)

- **Target**: `routes/auth.py:146-151` (create flow),
  `services/database_init.py:570-586` (seed), `app.py` (before_request
  middleware).
- **Why**: `force_password_change` flag and `force_change_password.html`
  template exist, but nothing enforces the redirect.  A seeded admin
  can navigate the whole app with `changeme` / `admin` credentials
  indefinitely.
- **Plan**: add a `before_request` handler that redirects logged-in
  users with `force_password_change = 1` to the change-password page
  for every non-login, non-static route.
- **Source**: 2026-04-23 audit, Auth & Security finding 4.
- **Status**: todo

### 24.4 Tighten password policy + rate-limit password change (MEDIUM, S)

- **Target**: `routes/auth.py:278, 308` (policy), `:262` (change
  endpoint).
- **Why**: current policy is 8 chars with no complexity / breach
  check — `password` passes.  OWASP 2026 guidance is ≥12 or HIBP
  k-anonymity check.  Password-change endpoint isn't rate-limited at
  all, so an attacker with any session can brute-force `current_password`
  unlimited.
- **Plan**: raise minimum to 12 chars; add the same `login_attempts`
  dict-based rate limit to the change endpoint; document the choice
  (HIBP call vs length rule) in standards addendum.
- **Source**: 2026-04-23 audit, Auth & Security findings 5, 8.
- **Status**: todo

### 24.5 `@editor_required` / `@admin_required` on destructive endpoints (HIGH-in-multi-user, M)

- **Target**: `routes/games.py:849, 906, 1011`;
  `routes/games_media.py:25, 51, 100`;
  `routes/bulk_scrape.py:151-256`;
  `routes/achievements.py:269` (sync);
  `routes/collector_trophies.py` (refresh);
  `routes/collections.py` list/tag/wishlist CRUD.
- **Why**: all currently `@login_required` only — any authenticated
  viewer can delete games, rename ROMs, delete screenshots, wipe
  another user's bulk-scrape queue, trigger expensive API sync on the
  admin's account.
- **Plan**: per-endpoint review: destructive mutation → `@editor_required`
  (data write), or `@admin_required` (credential / global setting).
  Collections endpoints deferred to Pass 27 (needs `owner_id`).
- **Source**: 2026-04-23 audit, Game Routes finding 1, Collections
  finding 1, Maintenance finding 5.
- **Status**: todo

### 24.6 Xbox OAuth `state` parameter + verification (MEDIUM-in-multi-user, S)

- **Target**: `scraper/scrape_xbox.py:46-62` (generate), `routes/platform_import.py:383-452` (verify).
- **Why**: `get_auth_url()` omits `state` entirely.  An attacker can
  trigger the callback with arbitrary `code` and bind the victim's
  RetroDB session to the attacker's Microsoft account.
- **Plan**: generate a random token, stash in session as
  `oauth_state_xbox`, include as `state=` in the auth URL, compare on
  callback.  Reject mismatches with 400.
- **Source**: 2026-04-23 audit, Platform Imports finding 1.
- **Status**: todo

### 24.7 Sensitive-file permissions on token JSON (LOW, S)

- **Target**: `scraper/scrape_xbox.py:42-43, 182-189` (Xbox tokens),
  PSN token writer in `routes/trophies.py` (out-of-file reference).
- **Why**: `open(..., 'w')` then `json.dump` with no umask / chmod,
  so world-readable on group-shared filesystems.  Tokens are
  long-lived refresh credentials.
- **Plan**: after save, `os.chmod(path, 0o600)`.  Tiny helper,
  applied uniformly.
- **Source**: 2026-04-23 audit, Platform Imports finding 4.
- **Status**: todo

### 24.8 Broaden `SecretRedactor` token patterns (LOW, S)

- **Target**: `services/log_redactor.py:22-32`.
- **Why**: current patterns catch JWTs and `[a-f0-9]{40,}` hex
  digests.  PSN `NPSSO` is 64 chars of base64 (`[A-Za-z0-9]{64}`)
  and slips through when logged as a bare string.  Same for raw
  Gemini API keys.
- **Plan**: add a base64-ish `[A-Za-z0-9_\-]{32,}` pattern gated to
  field names in a known-sensitive list (`npsso`, `api_key`,
  `access_token`).  Don't redact unconditionally — too many false
  positives.
- **Source**: 2026-04-23 audit, Auth & Security finding 10.
- **Status**: todo

---

## Pass 25 — Input hardening, SSRF, size caps

> Defensive.  No architectural deps.  Independent of Pass 24.

### 25.1 ES-DE path-traversal guard (MEDIUM, S)

- **Target**: `scraper/scrape_esde.py:801-828` (`resolve_media_path`).
- **Why**: accepts absolute `/`-prefixed paths verbatim; `shutil.copy2`
  then copies anything the server process can read into `IMAGE_PATH`.
  A crafted `gamelist.xml` → arbitrary-file-read (within server
  privilege).
- **Plan**: `os.path.commonpath([resolved, allowed_es_de_root])`
  check against an allowlist of configured ES-DE roots before
  `shutil.copy2`.  Reject otherwise.
- **Source**: 2026-04-23 audit, Per-source Scrapers finding 4.
- **Status**: todo

### 25.2 `/api/reports` system-folder whitelist (MEDIUM, S)

- **Target**: `routes/reports.py:391, 568` (pre-join whitelist),
  `:576` (post-join guard already via `safe_path`).
- **Why**: `system_filter` is concatenated into `os.path.join(ROM_PATH,
  system_filter)` before `safe_path` validates.  Pre-join
  `os.listdir` / `glob` calls still run on the unvalidated path, so
  a `../../etc` value enumerates outside `ROM_PATH`.
- **Plan**: validate `system_filter` against `SELECT folder FROM
  systems` (DB-known folders only) before any FS call.
- **Source**: 2026-04-23 audit, Maintenance finding 3.
- **Status**: todo

### 25.3 Museum Bing-search SSRF hardening (MEDIUM, M)

- **Target**: `routes/museum.py:736-780`
  (`_bing_image_search`), `:984-1007` (`_fetch_and_process_image`).
- **Why**: returns `murl` from Bing HTML and fetches verbatim with
  only `startswith('http')` check.  No host allowlist, no
  RFC1918 / localhost / link-local rejection, no redirect cap.
- **Plan**: resolve hostname to IP, reject private ranges
  (`ipaddress.ip_address(h).is_private`, `.is_loopback`,
  `.is_link_local`, `.is_reserved`); cap redirects with
  `allow_redirects=False` + manual hop limit; restrict content-type
  to `image/*`.
- **Source**: 2026-04-23 audit, Collections finding 3.
- **Status**: todo

### 25.4 Museum controller-image upload size cap (MEDIUM, S)

- **Target**: `routes/museum.py:607` — `file.read()` before
  validation.
- **Why**: a 2 GB upload OOMs the process.  No per-route cap.
- **Plan**: check `request.content_length` before `file.read()`;
  hard cap 10 MB for controller images.  Same helper used for
  avatar / boxart uploads.
- **Source**: 2026-04-23 audit, Collections finding 4.
- **Status**: todo

### 25.5 CLZ PDF bounds (MEDIUM, M)

- **Target**: `routes/clz_import.py:281-374`.
- **Why**: opens arbitrary 50 MB PDFs and iterates every page; a
  pathological 10 000-page PDF blocks a worker for minutes.  Temp
  file isn't unlinked on exception path.  Duplicate SELECT loads
  the whole `games` table for each import.
- **Plan**: page-count ceiling (default 500); `try/finally` around
  the `tmp_path` cleanup; scope the dup-check SELECT to `WHERE
  system_id IN (...)` so it stays fast on large libraries.
- **Source**: 2026-04-23 audit, Collections findings 5, 6.
- **Status**: todo

### 25.6 Video upload `MAX_VIDEO_SIZE` (MEDIUM, S)

- **Target**: `services/game_media_service.py:125-128` (video branch
  of `save_upload`).
- **Why**: image branch enforces `MAX_IMAGE_SIZE`; video branch
  writes with `file_storage.save()` directly.  Flask
  `MAX_CONTENT_LENGTH` is the only backstop.
- **Plan**: add `MAX_VIDEO_SIZE` to `config.py` (default 50 MB);
  apply in `save_upload`.
- **Source**: 2026-04-23 audit, Game Routes finding 5.
- **Status**: todo

### 25.7 Response size caps in scraper image downloads (MEDIUM, S)

- **Target**: `scraper/base_scraper.py:216-223`
  (`download_image` streaming), `scraper/scrape_screenscraper.py:742-753`
  (`download_media`), `scraper/_ss_request_with_retry:933`.
- **Why**: streaming download writes every chunk with no total-size
  limit.  A malicious or misconfigured API response exhausts disk;
  a giant SS JSON response OOMs the worker.
- **Plan**: cap at `MAX_MEDIA_DOWNLOAD_BYTES` (default 50 MB) and
  `MAX_API_RESPONSE_BYTES` (default 10 MB); abort + delete partial
  file on overflow.
- **Source**: 2026-04-23 audit, Per-source Scrapers finding 1,
  Image Pipeline gap 7.
- **Status**: todo

### 25.8 Cap list-returning endpoints (LOW, S)

- **Target**: `routes/games.py:1099-1130` (`api_filter_games`,
  no LIMIT), `:1048` (`api_recently_viewed`, user-trusted `limit`),
  `:209-214` (`api_games_ids` uncapped).
- **Why**: `?limit=999999` can OOM or produce multi-MB JSON blobs.
- **Plan**: enforce a hard `MAX_LIST_ROWS` (default 500) via
  `min(user_limit, MAX_LIST_ROWS)`.
- **Source**: 2026-04-23 audit, Game Routes finding 4.
- **Status**: todo

### 25.9 Rate limits on expensive endpoints (MEDIUM, S)

- **Target**: `routes/games_ai.py:29` (AI fill),
  `routes/games_hltb.py` (HLTB lookup + search),
  `routes/museum.py:346` (museum generate),
  `routes/collector_trophies.py` (refresh).
- **Why**: currently unbounded — a single user can burn the
  Gemini / OpenAI quota in minutes, spam the HLTB scraper, or
  trigger repeated 20-query trophy-stat scans.
- **Plan**: reuse the existing rate-limiter from `routes/auth.py`
  (dict-based per-IP or per-user).  Defaults: AI-fill 30/hour,
  HLTB 60/hour, museum generate 20/hour, trophy refresh 10/hour.
- **Source**: 2026-04-23 audit, Game Routes gaps 3, 4; Collections
  gaps 2.
- **Status**: todo

---

## Pass 26 — Scraper HTTP uniformity & API-key hygiene

> Polish pass.  No deps.  Independent of security passes.

### 26.1 Route ScreenScraper + RetroAchievements through `base_scraper` (MEDIUM, M)

- **Target**: `scraper/scrape_screenscraper.py:238, 745, 933`
  (bypass sites); `scraper/retroachievements.py:211, 291, 359,
  441, 523` (5 bare `requests.get` sites).
- **Why**: these 8 sites skip shared retry, 429 `Retry-After`,
  log redaction, and session reuse.  Error handling is
  inconsistent across scrapers — RA has zero 429 / 5xx handling at
  all.
- **Plan**: swap each site to `base_scraper.http_get` /
  `http_post`; keep the per-scraper response-shape parsing but
  delegate HTTP policy to the shared helpers.
- **Source**: 2026-04-23 audit, Per-source Scrapers finding 1.
- **Status**: todo

### 26.2 Move Gemini API key out of URL querystring (MEDIUM, S)

- **Target**: `scraper/scrape_ai.py:647, 1036`.
- **Why**: `?key={api_key}` ends up in every log line via
  `http_post`'s DEBUG + ERROR logging (`base_scraper.py:133, 177`).
  `SecretRedactor` does catch the `api_key=` querystring pattern
  today, but header-based auth eliminates the exposure surface
  entirely.
- **Plan**: use `x-goog-api-key: {api_key}` header; delete the
  querystring param.
- **Source**: 2026-04-23 audit, Per-source Scrapers finding 3.
- **Status**: todo

### 26.3 Apply AI circuit-breaker at the call site (LOW, S)

- **Target**: `scraper/hybrid_scraper.py:1094` (`fetch_ai_metadata`).
- **Why**: `_ai_breaker` is defined at `scraper_manager.py:267`
  but never wrapped around `fetch_ai_metadata`.  Every AI
  gap-fill hits the provider regardless of recent failures.
- **Plan**: wrap the call in `with _ai_breaker:` (or manual
  `if _ai_breaker.is_open(): return None`).
- **Source**: 2026-04-23 audit, Scraper Orchestration gap 2.
- **Status**: todo

### 26.4 Unify 5xx retry policy across `http_get` and SS retry helper (LOW, S)

- **Target**: `scraper/base_scraper.py:90` (no-retry on 5xx),
  `scraper/scrape_screenscraper.py:947` (does retry 5xx).
- **Why**: inconsistent policy — an SS transient 503 retries,
  a TGDB transient 503 doesn't.
- **Plan**: retry `[500, 502, 503, 504]` in `http_get` with
  exponential backoff + jitter (no thundering herd); never retry
  401 / 403.
- **Source**: 2026-04-23 audit, Per-source Scrapers gaps 2, 3.
- **Status**: todo

### 26.5 Mask API keys on GET `/settings` + `/api/scraper-settings` (LOW, S)

- **Target**: `routes/settings.py:116-130`,
  `routes/scraper.py:46-82`.
- **Why**: `/settings` renders unmasked API keys directly to the
  DOM; `get_saved_api_keys` returns them in response envelopes.
  Not a vuln per se (single-user localhost) but fails shoulder-surf
  / screenshot hygiene.
- **Plan**: show `***` with last 4 chars only on GET; accept the
  `***` placeholder on PUT as "don't change" sentinel.
- **Source**: 2026-04-23 audit, Maintenance finding 2.
- **Status**: todo

---

## Pass 27 — Multi-user data ownership

> **Depends on Pass 20 (schema migrations) + Pass 24.1 (real
> auth on editor/viewer).**  Don't start until both have landed —
> adding `owner_id` columns through the ad-hoc migration path
> would be exactly the kind of schema drift Pass 20 exists to
> kill.

### 27.1 Add `owner_id` to `tags`, `lists`, `wishlist` (HIGH-in-multi-user, M)

- **Target**: new migration file under `services/migrations/`
  (shape defined by 20.1); `routes/collections.py` list / tag /
  wishlist CRUD.
- **Why**: currently zero per-user scoping — any logged-in user
  can mutate any other user's tags / lists / wishlist items.
- **Plan**: migration adds `owner_id INTEGER REFERENCES
  users(id)`, NULL for existing rows (treat as admin-owned);
  backfill step can assign existing rows to admin.  Every route
  handler gains `WHERE owner_id = g.user['id'] OR
  g.user['role']='admin'`.
- **Source**: 2026-04-23 audit, Collections finding 1.
- **Status**: todo

### 27.2 Scope PSN / Xbox tokens per user (HIGH-in-multi-user, M)

- **Target**: migration (rename `psn_tokens.json` →
  `user_psn_tokens` table with `user_id` FK); `scraper/scrape_xbox.py`
  token file → table with `user_id`; `routes/platform_import.py`
  status + library readers; singleton state in
  `services/jobs/psn_refresh.py`.
- **Why**: today `psn_sync_status` uses `LIMIT 1` with no
  `user_id` filter — every logged-in user sees the single
  account that happens to have synced, including its avatar and
  PSN username.  Same for `xbox_tokens.json` (one file per
  install, not per user).
- **Plan**: new `user_platform_tokens` table keyed by
  `(user_id, platform)`.  Job workers take `user_id` as a
  parameter; status reads filter by session user.
- **Source**: 2026-04-23 audit, Platform Imports finding 11.
- **Status**: todo

### 27.3 Remove global-state assumptions from platform sync jobs (MEDIUM, S)

- **Target**: `services/jobs/platform_sync.py:20-49`
  (`_get_steam_credentials`, `_get_xbox_credentials`).
- **Why**: reads credentials from a single source every job
  run; won't compose with 27.2's per-user scoping.
- **Plan**: accept `user_id` on job construction; credential
  lookup goes through the new `user_platform_tokens` table.
- **Source**: 2026-04-23 audit, Background Jobs finding
  (platform_sync.py:20-49).
- **Status**: todo (follows 27.2)

---

## Pass 28 — Accessibility pass 2 — forms, focus traps, motion

> Independent of every other pass.  Each sub-item is independently
> shippable.

### 28.1 Add `<label for=…>` association across form controls (HIGH, L)

- **Target**: `templates/settings.html` (~50 controls),
  `templates/wishlist.html:103`, `templates/museum_system.html:199`,
  and scattered sites (~209 non-hidden controls total out of
  365).
- **Why**: sibling `<label>` tags sit above the `<input>` but
  lack `for=`, so screen readers announce placeholder text only.
  Biggest a11y regression in the template tree.
- **Plan**: add `id=` to each input and `for=` to its label.  No
  schema change, just markup.
- **Source**: 2026-04-23 audit, Templates & CSS finding 2.
- **Status**: todo

### 28.2 `ModalFocusTrap` on template-local modals (MEDIUM, M)

- **Target**: inline modal open/close JS in `wishlist.html`,
  `tags.html`, `lists.html`, `list_detail.html`,
  `compare_games.html`, `settings.html` user-edit / tz-picker /
  folder-browser, `museum_system.html`.
- **Why**: these pages define their own `openXModal /
  closeXModal` without calling `ModalFocusTrap.activate /
  deactivate`.  Keyboard users tabbing inside the modal escape
  to the page behind.
- **Plan**: wrap each open/close pair with the existing
  `ModalFocusTrap` calls documented in CLAUDE.md §Global JS.
- **Source**: 2026-04-23 audit, Templates & CSS finding 4.
- **Status**: todo

### 28.3 Remove positive `tabindex` values from `_modals/edit_modal.html` (LOW, S)

- **Target**: `templates/_modals/edit_modal.html:29-… (28 occurrences)`.
- **Why**: positive `tabindex="1"` through `tabindex="28"` fights
  DOM order; WCAG 2.1 SC 2.4.3 discourages.  DOM order suffices
  if the modal form is laid out in the intended tab sequence.
- **Plan**: strip all positive `tabindex` attributes; verify tab
  order via keyboard walk-through.
- **Source**: 2026-04-23 audit, Templates & CSS finding 3.
- **Status**: todo

### 28.4 Skip-to-content link (LOW, S)

- **Target**: `templates/base.html:240` (after `<body>` open).
- **Why**: WCAG 2.1 SC 2.4.1 "Bypass Blocks" — keyboard users
  currently have to tab through the full sidebar on every page.
  `<main id="main-content">` already exists; just need the link.
- **Plan**: `<a href="#main-content" class="skip-link">Skip to
  main content</a>` styled to only appear on `:focus`.
- **Source**: 2026-04-23 audit, Templates & CSS gap 3.
- **Status**: todo

### 28.5 `prefers-reduced-motion` kill-switch for theme canvas effects (MEDIUM, S)

- **Target**: `static/js/theme.js` — Matrix rain, Cyberpunk
  volumetric smoke, Ocean reflection.
- **Why**: CSS `@media (prefers-reduced-motion: reduce)` covers
  the rest of the app (via `reset.css:62`), but JS-driven canvas
  animations ignore CSS media queries entirely.  Users with
  motion-sensitivity see full-bleed animated canvases regardless.
- **Plan**: `window.matchMedia('(prefers-reduced-motion:
  reduce)').matches` check at theme init; if true, skip the
  canvas animation start.
- **Source**: 2026-04-23 audit, Templates & CSS gap 1.
- **Status**: todo

### 28.6 `aria-live="polite"` on notification + loading containers (MEDIUM, S)

- **Target**: `static/js/utils.js:344-357`
  (`Notifications.show`), `:409-426` (`LoadingState.show`).
- **Why**: screen-reader users don't hear scrape progress,
  errors, or bulk-edit completion because the `.notification`
  divs lack `role="status"` / `aria-live`.  Direct contradiction
  of the WCAG 2.2 AA sweep shipped in Pass 15.
- **Plan**: one-line attribute add on the container element
  Notifications injects into.
- **Source**: 2026-04-23 audit, Frontend JS gap 4.
- **Status**: todo

---

## Pass 29 — Frontend defense in depth

> No deps.  Independent of every other pass.  Severity is
> LOW under the single-user-localhost threat model but these
> are cheap, high-signal hardening wins.

### 29.1 Escape user-derived strings in `innerHTML` sinks (MEDIUM, S)

- **Target**: `static/js/settings-page.js:826`
  (system.name / system.slug);
  `static/js/achievements.js:320`
  (badge_url / title);
  `static/js/trophies.js:294` (icon_url / name);
  `static/js/museum.js:191-195` (imageFilename in `src=`);
  `static/js/settings-page.js:552, 581`
  (`ConfirmModal.show` `.innerHTML = message`);
  `static/js/all-games-controller.js:491-502`
  (inline-onclick construction).
- **Why**: API-derived strings flow into `innerHTML` without
  escaping.  Today the data is trusted (scrapers, local
  settings) so XSS risk is low, but any future user-facing input
  sharing these sinks becomes an execution primitive.
- **Plan**: use `escapeHtml()` from `utils.js` at every sink; for
  the ConfirmModal case, switch `.innerHTML = message` to
  `.textContent = message` unless the caller explicitly passes
  HTML (document the contract).
- **Source**: 2026-04-23 audit, Frontend JS finding 1.
- **Status**: todo

### 29.2 CSRF token propagation in `API.post` / `API.postForm` (LOW-per-threat-model, S)

- **Target**: `static/js/utils.js:231-272`.
- **Why**: zero CSRF token header on any POST.  Under the
  single-user-localhost threat model this is LOW (see §Notes).
  Worth doing anyway because (a) it's one file, and (b) multi-user
  installs do exist once Pass 24.1 passes ship.
- **Plan**: backend emits CSRF token via `csrf_token()` Jinja
  global (needs Pass 24.x backend half — bundle with it).
  Frontend reads from `<meta name="csrf-token">` and sets
  `X-CSRFToken` on every non-GET.  Coordinate with 24.2 session
  rotation to regenerate token on login.
- **Source**: 2026-04-23 audit, Frontend JS gap 3.
- **Status**: todo (lands with Pass 24 backend CSRF middleware)

### 29.3 Consolidate duplicate keyboard handlers + enforce focus-trap stacking (MEDIUM, M)

- **Target**: `static/js/main.js:532` (Escape for screenshot nav),
  `static/js/game-modals.js:2048` (Escape for carousel),
  `static/js/all-games-controller.js:1365` (Escape for filter modal);
  all three register document-level `keydown` handlers.
- **Why**: opening the filter modal over the game-detail modal
  fires both handlers; the nested modal can close along with the
  outer.  Screenshot-lightbox focus trap overrides the
  underlying `GameDetailModal` trap.
- **Plan**: migrate all three to the existing `ModalFocusTrap`
  API, which already stacks correctly per spec.  Delete the
  direct document listeners.
- **Source**: 2026-04-23 audit, Frontend JS finding (event
  leaks + stacking).
- **Status**: todo

### 29.4 `try/catch` around `JSON.parse` of `localStorage` values (LOW, S)

- **Target**: 13 sites (`static/js/toast-controller.js:726, 740,
  798, 871, 911, 933, 1012, 1381, 1617`;
  `static/js/main.js:908`;
  `static/js/game-list.js:149`;
  `static/js/achievements.js:74`).
- **Why**: a corrupted or tampered `localStorage` value throws
  and breaks the page on load.  No recovery path.
- **Plan**: single helper `safeParseJSON(key, fallback)` in
  `utils.js`; swap each call site.
- **Source**: 2026-04-23 audit, Frontend JS finding (unguarded
  parse).
- **Status**: todo

### 29.5 `AbortController` on search-style API calls (LOW, S)

- **Target**: `static/js/main.js:247` (global search);
  `static/js/all-games-controller.js` filter / sort rapid-fire
  calls.
- **Why**: rapid typing spawns parallel requests; last-response-wins
  races flash stale results.
- **Plan**: store an `AbortController` per input on the
  controller; abort the previous request before issuing a new
  one.
- **Source**: 2026-04-23 audit, Frontend JS finding (race).
- **Status**: todo

---

## Follow-ups from landed passes

Small, well-scoped items that surfaced while finishing an earlier pass but
weren't worth blocking the ship on.  Ordered by rough priority.

### FU.1 Flip CSP from Report-Only to enforcing (MEDIUM, L — needs template migration)

- **Context**: Pass 16.2 shipped CSP as `Content-Security-Policy-Report-Only`
  because ~765 inline `on*` event handlers and ~38 inline `<script>` blocks
  still exist across templates.  Violations surface in the browser console
  today; flipping to enforcing would break pages.
- **Plan**: migrate inline handlers to delegated listeners registered in the
  page's bundled JS, convert inline `<script>` blocks to either external
  files or nonced blocks (`<script nonce="{{ csp_nonce }}">`), then change
  the header name from `Content-Security-Policy-Report-Only` to
  `Content-Security-Policy` in `app.py::set_security_headers`.
- **Status**: todo

### FU.2 Grid-card `srcset` for boxart (LOW, M)

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
- **Status**: todo

### FU.3 Bulk JPEG→WebP migration endpoint (LOW, M)

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
- **Status**: todo

### FU.4 Stream large image downloads in the TGDB scraper (LOW, S)

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
- **Status**: todo

---

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

1. **Auth & security** — `services/auth.py`, `security.py`, `log_redactor.py`, `routes/auth.py`
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
> Project root: `/mnt/Storage/Scripts/Linux/RetroDB`.  You do not know what
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
