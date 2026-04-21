# RetroDB Refactor Roadmap

Tracking file for refactoring opportunities identified in the 2026-04-21 code
review. Items are ordered so that earlier passes establish the patterns used
by later ones (service-layer carve-outs, response helpers, etc.).

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

---

## In progress

_None._

---

## Pass 2 — finish the cross-route cleanup (small, mechanical)

### `@handle_api_errors` on the rest of the routes layer

- **Target**: every `routes/*.py` file with a `try: … except Exception as e:
  logger.error(…); return jsonify({'success': False, 'error': …}), 500`
  block.
- **Why**: `games_hltb.py` is the template. The same boilerplate appears in
  `routes/games.py`, `routes/maintenance.py`, `routes/bulk_scrape.py`,
  `routes/ra_sync.py`, `routes/bonus_discs.py`, `routes/trophies.py`,
  `routes/collections.py`, `routes/platform_import.py`, etc.
- **Plan**: grep for `'An internal error occurred'` across `routes/`; for
  each hit, drop the try/except and add `@handle_api_errors` below the auth
  decorator. Be careful to preserve any `except` clauses that catch *specific*
  exceptions (those are intentional handlers, not generic 500 fallbacks).
- **Est. reduction**: ~4 LOC × every occurrence. Likely 200+ LOC total
  across routes/.
- **Status**: todo

### Response builder helpers

- **Target**: new `services/api_helpers.py::success()` / `::error()` + sweep
  across `routes/*.py`.
- **Why**: every handler builds `jsonify({'success': True/False, 'data': …,
  'error': …})` inline. Standardising lets us tweak the envelope in one
  place (e.g. add a `request_id` field) and makes error vs. success calls
  visually distinct.
- **Plan**:
  ```python
  def success(data=None, **extra):
      payload = {'success': True}
      if data is not None:
          payload['data'] = data
      payload.update(extra)
      return jsonify(payload)

  def error(message, code=400, **extra):
      return jsonify({'success': False, 'error': message, **extra}), code
  ```
  Migrate gradually — don't force a mass rewrite. Use on new routes and
  when touching old ones.
- **Est. reduction**: cosmetic per site, but large cumulative gain in
  readability.
- **Status**: todo

---

## Pass 3 — HLTB service extraction

### Split `routes/games_hltb.py` into route + service

- **Target**: `routes/games_hltb.py` (407 LOC → ~150), new
  `services/hltb_service.py`.
- **Why**: three concerns mixed in one file: (1) single-game lookup and
  save, (2) pending-match review queue, (3) bulk job orchestration. The
  helpers `_extract_alt_titles()`, `_apply_pending_match()` and
  `_resolve_filter_clause()` are buried in route bodies.
- **Plan**: create `services/hltb_service.py` with:
  - `HLTBLookup` — `lookup(game_id, search_title=None, preview=False)`,
    `search(query, folder, year=None, alternate_titles=None)`,
    `save_result(game_id, payload)`, `clear(game_id)`.
  - `HLTBPendingQueue` — `list()`, `approve(id)`, `reject(id)`,
    `approve_all(filter)`, `reject_all(filter)`. Owns `_apply_pending_match`
    and `_resolve_filter_clause`.
  - `HLTBBulkOrchestrator` — `start()`, `status()`, `cancel()` (thin wrapper
    over `services.jobs.hltb_bulk_job` with queue-depth stitching).
- **Est. reduction**: route file drops from 407 → ~150 LOC; service file is
  ~300 LOC and reusable from any future caller (CLI, admin UI, etc.).
- **Status**: todo

---

## Pass 4 — maintenance.py split

### Break `routes/maintenance.py` into service modules

- **Target**: `routes/maintenance.py` (769 LOC → ~200); new
  `services/game_cleanup.py`, `services/media_cleanup.py`,
  `services/rom_scanner.py`.
- **Why**: file mixes seven concerns (ROM scanning, image deletion, game
  cleanup, scraped-data clearing, orphan detection, DB optimisation, job
  scheduling for image resize + alt-titles backfill). Helper functions like
  `delete_game_images()` and `clean_title()` are trapped inside route
  bodies.
- **Plan**:
  - `services/game_cleanup.py::GameCleanup` — `clean_missing_roms()`,
    `delete_game_images(game_id)`, `clear_scraped_data(game_id, fields)`.
  - `services/media_cleanup.py::MediaCleaner` — `find_orphaned_media()`,
    `clean_orphaned_files()`.
  - `services/rom_scanner.py::ROMScanner` — `clean_title(name)`,
    `parse_systeminfo(folder)`, `run_inline_scan(system_id)`.
  - Routes call into these; each handler becomes 3–10 LOC.
- **Est. reduction**: routes file shrinks by ~550 LOC; three new service
  modules total ~500 LOC, each focused.
- **Status**: todo

---

## Pass 5 — scraper/metadata_merger.py split

### Extract image dedup and field normalisation from metadata_merger

- **Target**: `scraper/metadata_merger.py` (1293 LOC → ~600); new
  `scraper/image_dedup.py`, `scraper/metadata_normalizer.py`.
- **Why**: five near-parallel `apply_{tgdb,igdb,rawg,screenscraper,ai}_to_metadata()`
  functions each re-implement: field normalisation → image dhash computation
  → screenshot dedup → DB update. Image hashing code (`_compute_dhash`,
  `_get_existing_screenshot_hashes`, etc.) is ~100 LOC interleaved with
  field-mapping code in the middle of each function.
- **Plan**:
  - `scraper/image_dedup.py::ImageDeduplicator` — `compute_dhash(path)`,
    `get_existing_hashes(game_id)`, `is_duplicate(path, existing)`,
    `find_duplicates_in_batch(paths)`.
  - `scraper/metadata_normalizer.py::MetadataNormalizer` — field-level
    helpers (`normalize_genre()`, `normalize_rating()`, `normalize_players()`,
    `merge_alt_titles()`, etc.) currently re-implemented inside each
    scraper.
  - Each `apply_*_to_metadata()` becomes a linear fetch → normalise →
    dedupe → write, dropping to ~100 LOC.
- **Est. reduction**: merger shrinks by ~700 LOC; new helper files total
  ~400 LOC.
- **Status**: todo

---

## Pass 6 — scraper_manager.py split

### Extract match scoring and cache from ScraperManager

- **Target**: `scraper/scraper_manager.py` (1022 LOC → ~700); new
  `scraper/match_scorer.py`, `scraper/scraper_cache.py`.
- **Why**: `ScraperManager` currently handles orchestration (fine), match
  scoring (`_calculate_title_match_score` is 200+ LOC of nested logic),
  noise-stripping regexes, and cache/TTL management. The scoring code is
  the single hardest-to-maintain block in the file.
- **Plan**:
  - `scraper/match_scorer.py::MatchScorer` — `score_title(a, b)`,
    `word_order_bonus(a, b)`, `ss_specific_score(...)`,
    `calculate_match_confidence(result, query)`.
  - `scraper/title_normalizer.py::TitleNormalizer` — config-driven
    dict-of-regex patterns for region tags, edition tags, disc markers;
    single loop applies them in priority order. Replaces the long
    conditional chain in `_strip_title_noise()`.
  - `scraper/scraper_cache.py::ScraperCache` — TTL-backed cache used by
    `search_games()` / `get_extended_data()`.
- **Est. reduction**: manager drops by ~300 LOC; three new files total
  ~350 LOC, each with one job.
- **Status**: todo

---

## Pass 7 — games.py decomposition

### Carve service layer out of the biggest route file

- **Target**: `routes/games.py` (1390 LOC) — split into thin route handlers
  + multiple service modules.
- **Why**: the file handles game CRUD, metadata application, trophy/
  achievement linking, image management, game search, and stats/reports in
  one body. Too big to tackle in one pass; start with the three heaviest
  endpoints.
- **Plan** (multi-stage):
  1. `services/game_metadata_service.py` — owns `apply_metadata_to_game`,
     field merging, scrape-history writes. Called from both
     `routes/games.py` and `routes/games_ai.py`.
  2. `services/achievement_linking_service.py` — the ad-hoc code that
     matches games to RA / PSN / Steam / Xbox titles via `_clean_title_for_matching`
     and related helpers. Pull the matching logic out of the route so it's
     reusable from sync jobs.
  3. `services/game_media_service.py` — image upload, boxart application,
     screenshot dedup (share with Pass 5 helpers).
- **Est. reduction**: per stage ~150 LOC out of routes/games.py.
  Multi-stage; target ~800 LOC when done.
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo (from ants-audit triage 2026-04-21)

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

### 12.4 Slow-query logging (MEDIUM, M)

- **Target**: `services/database.py::query()` / `::execute()`.
- **Why**: No visibility into production N+1 patterns or slow queries.
  Even a threshold-based debug log (query > 100 ms) would surface
  regressions immediately.
- **Plan**: wrap `conn.execute(sql, args)` in a `time.perf_counter()`
  delta; if > 100 ms, log at WARNING with the SQL (redacted) and
  arguments count.  Guard behind a `SLOW_QUERY_MS` config knob (default
  disabled in production, 100 ms in dev).
- **Status**: todo

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
- **Status**: todo

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
