# RetroDB Roadmap

Tracking file for refactoring, security, performance, and quality work
identified in successive reviews (2026-04-21 onwards). Items are ordered so
that earlier passes establish the patterns used by later ones (service-layer
carve-outs, response helpers, etc.).

Each item lists:
- **Target** — file(s) and approximate line range / LOC
- **Why** — the specific issue (oversized function, duplicated logic, mixed
  concerns, long conditional chain)
- **Plan** — concrete extraction target: new file, class/function name, what
  moves where
- **Est. reduction** — rough LOC delta in the source file
- **Status** — `todo` / `in-progress` / `done`

Open items are grouped by theme below; ship Tier-1 items (Pass 40) first.
The compact "Done index" near the bottom lists landed passes by version —
detail lives in git history (`git log --grep "Pass NN"`).

See "Scope notes — considered and dropped" for items deliberately excluded,
and "Periodic Independent Review" at the very end for the cadence on
re-running the multi-agent audit that surfaces new passes.

---

## Active

Grouped by theme. Within each theme, items ordered by priority (CRITICAL →
HIGH → MEDIUM → LOW). The 2026-04-24 indie-review Tier-1 sweep (Pass 40)
is highest priority overall — sixteen findings carry concrete exploit
paths or silent-corruption vectors under routine use.

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
- **Status**: partial (v3.5.5) — H2 (redactor) + H3 (IGDB 401) closed:
  `key` and `sspassword` added to `services/log_redactor.py` URL-
  querystring allowlist; `igdb_request` invalidates `_igdb_token_cache`
  and retries once with a fresh token on 401. H1/H4 (route Steam +
  HLTB raw `requests.get/post` through `base_scraper.http_get/post`)
  carried over as a follow-up — 10 callsites need case-by-case audit
  because `http_get` returns `None` on total failure where the current
  code expects `requests.get` semantics. Tests:
  `tests/test_pass41_security.py::TestPass41_5A/B` (5 cases).

#### Pass 41.5b Steam + HLTB through base_scraper (carry-over from 41.5)

- **Target**: `scraper/scrape_steam.py` (7 endpoints) and
  `scraper/hltb_lookup.py` (3 endpoints) — raw `requests.get`/`requests.post`.
- **Why**: `base_scraper.http_get` / `http_post` provide retry/backoff/
  size-cap; raw `requests.*` skips that hardening.
- **Plan**: replace each raw call with the `http_get`/`http_post` shape
  (returns `Response` or `None`); add explicit `if resp is None:` guards
  in callers that currently rely on `requests` raising on `None`.
- **Status**: todo (carry-over from Pass 41.5)

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

#### Pass 39.2 Explicit `permissions:` block on CI (HIGH, S)

- **Target**: `.github/workflows/ci.yml`.
- **Why**: no workflow-level `permissions:` block; job inherits repo-
  default `GITHUB_TOKEN` scope, which for private/org repos can
  include `contents: write`.  OWASP CICD-SEC-2.
- **Plan**: add `permissions: { contents: read }` at workflow level;
  let individual steps narrow further if needed.
- **Source**: 2026-04-24 audit, Tests/tooling/CI H2.
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

#### Pass 39.5 Dependabot regenerates `requirements.lock` (MEDIUM, S)

- **Target**: `.github/dependabot.yml:10-27`.
- **Why**: currently updates `requirements.txt` only.  Lockfile-drift
  check at `ci.yml:88-113` hard-fails every Dependabot PR until
  manual `pip-compile`.
- **Plan**: add a GitHub Actions post-update step (or a
  `@dependabot pre-task` directive) that runs `pip-compile`; ensure
  the resulting diff is committed to the same PR.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M5.
- **Status**: todo

#### Pass 39.6 `build_dist.py` env-configurable `STAGING_DIR` (MEDIUM, S)

- **Target**: `build_dist.py:22`; `release.yml:55-64`.
- **Why**: hardcoded absolute path `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB`.
  Release workflow monkey-patches `build_dist.STAGING_DIR` inline —
  fragile; `main()` return is also `None`-masked.
- **Plan**: `STAGING_DIR = os.environ.get('RETRODB_STAGING_DIR',
  '/mnt/Storage/...')`; set `env: RETRODB_STAGING_DIR:` in the
  workflow.  Raise on `hasattr(build_dist, 'main') is False` rather
  than silently no-op.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M3.
- **Status**: todo

#### Pass 39.7 Rate-limit `api_reports_multidisc_scan` (MEDIUM, S)

- **Target**: `routes/reports.py:376-378`; `app.py:232-236` limiter config.
- **Why**: `@login_required`-only POST that walks the filesystem;
  non-editor users can loop-hammer it.  Pass 25.9 scope.
- **Plan**: add a Flask-Limiter rule (or gate behind `@editor_required`
  since it's effectively a write-adjacent discovery).
- **Source**: 2026-04-24 audit, Maintenance/settings M3.
- **Status**: todo

#### Pass 39.8 Audit-hygiene: gitleaks allowlist for `tests/test_log_redactor.py` (LOW, S)

- **Target**: `.gitleaks.toml`.
- **Why**: `/audit` run 2026-04-24 surfaced the synthetic-JWT test
  fixture at `tests/test_log_redactor.py:9` — intended to verify the
  redactor replaces JWTs.  Recurs on every audit.
- **Plan**: add `'''tests/test_log_redactor\.py$'''` to the existing
  `paths` array in `.gitleaks.toml` (narrow form — keep gitleaks
  active on other test files).
- **Source**: 2026-04-24 audit, /audit triage config-tightening.
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

#### Pass 38.2 Consolidate `load_scraper_settings` (MEDIUM, S)

- **Target**: `scraper/scraper_manager.py:63-106` vs `scraper/metadata_merger.py:72-86`.
- **Why**: duplicated with divergent miss-behavior; the manager's
  returns a fully-defaulted dict, the merger's returns
  `{'api_keys': {}, 'enabled': {}, 'priority': []}`.  Upstream `enabled`
  lookups silently disagree.
- **Plan**: keep one loader; re-export from the other.  Pick the
  manager's behavior (defaults from `config.py`) as canonical.
- **Source**: 2026-04-24 audit, Scraper orchestration M1.
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

#### Pass 38.5 Delete `app.bundle.js` references in installers (MEDIUM, S)

- **Target**: `install.py:299`, `install_gui.py:569, 572`.
- **Why**: `build_js.py:277-279` deletes `app.bundle.js` as a legacy
  artifact since the split into `core.bundle.js` + `games.bundle.js`.
  Installers still check for the old filename — "use existing bundle"
  branch never fires correctly on a failed build.  Zombie code.
- **Plan**: replace with checks for `core.bundle.js` + `games.bundle.js`.
- **Source**: 2026-04-24 audit, Tests/tooling/CI M1.
- **Status**: todo

#### Pass 38.6 Split `settings.html` by tab (LOW, M)

- **Target**: `templates/settings.html` (7,333 lines).
- **Why**: CSP / a11y / i18n sweeps all bottleneck on this file.
- **Plan**: split into `_partials/settings_{account,library,
  scraping,data,customization,system}.html`; `{% include %}` from a
  thin shell; preserve anchor IDs for sticky nav.
- **Source**: 2026-04-24 audit, Templates & CSS M3.
- **Status**: todo

#### Pass 38.7 Consolidate duplicate platform-sync endpoints (MEDIUM, S)

- **Target**: `routes/platform_import.py:298-361` vs `routes/steam_achievements.py:95-158` (`api_steam_sync_single` × 2); similarly Xbox single-sync in `xbox_achievements.py:110-175`.
- **Why**: two copies of near-identical UPSERT SQL; one uses
  `sqlite3.connect(config.DB_PATH)` directly, bypassing `get_db()`.
- **Plan**: extract `_upsert_steam_progress(game_id, result)` +
  `_upsert_xbox_progress(…)` helpers in
  `services/jobs/platform_sync.py`; collapse the routes.
- **Source**: 2026-04-24 audit, Platform imports M1/M2.
- **Status**: todo

#### Pass 38.8 Consolidate resume-path boilerplate across job classes (LOW, M)

- **Target**: `services/jobs/ra_sync.py:112-157`, `ra_refresh.py:94-136`, `platform_sync.py:222-260, 514-564`, `psn_refresh.py:149-214`, `bulk_scrape.py:512-603`.
- **Why**: six copies of "if resume_index > 0 and game_ids, reset +
  prepend Nones + restore counts + start thread, else fall through."
- **Plan**: extract `_apply_resume(self, game_ids, progress, **extra)`
  onto a thin mixin used by every job with resume support.
- **Source**: 2026-04-24 audit, Background jobs M5.
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

#### Pass 42.3 Global `window.onerror` + `unhandledrejection` handler (MEDIUM, S)

- **Target**: `static/js/main.js` or `static/js/utils.js` — handler
  pipes into `showNotification(msg, 'error')` with sampling.
- **Why**: 57 `console.error` sites and zero global handlers; silent
  UI failures reach the console and stop there.  User sees stale UI
  with no toast.
- **Plan**: add `window.addEventListener('error', ...)` and
  `'unhandledrejection'` handlers that dispatch to the toast system,
  rate-limited to one surface every 5s to avoid feedback loops.
- **Status**: todo

#### Pass 42.4 Pin / vendor Chart.js (MEDIUM, S)

- **Target**: `templates/analytics.html:1515`.
- **Why**: unpinned `cdn.jsdelivr.net/npm/chart.js` with no SRI on an
  admin-only page with session cookie.  Supply-chain attack surface.
- **Plan**: either pin `@4.x.y` + `integrity="sha384-..."`
  `crossorigin="anonymous"`, or vendor to `/static/vendor/chart.js`.
- **Status**: todo

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
- **Status**: todo

#### Pass 42.6 RA 401 observability + Steam / SS log-redaction tightening (MEDIUM, S)

- **Target**: `scraper/retroachievements.py` (5 callers),
  `services/log_redactor.py:31`.
- **Why**: stale API key masquerades as "no match"; credential
  patterns `key=` and `sspassword=` not in redactor.  Observability
  gap + credential leak surface.
- **Plan**: already scoped under Pass 41.5 for redactor; track the
  RA observability half here (5 call-site edits to surface 401 as a
  distinct error).
- **Status**: todo

#### Pass 42.7 Adopt or remove `PageLifecycle` (MEDIUM, M)

- **Target**: `static/js/page-lifecycle.js` (467 LoC) + all JS call
  sites currently rolling their own cleanup.
- **Why**: 0 current consumers of `PageLifecycle.*`; CLAUDE.md
  advertises the abstraction as canonical.  Either migrate the 10
  hot-path files or delete the module.
- **Plan**: pick an option; don't leave the doc-vs-code drift.
- **Status**: todo

#### Pass 42.8 Remove `/api/recently-viewed` + `ScraperManager.get_enabled_scrapers` + CSP nonce dead infrastructure (LOW, S — bundle)

- **Targets**:
  - `routes/games.py:1117-1142` — zero callers.
  - `scraper/scraper_manager.py:286-302` — zero callers.
  - CSP nonce infrastructure is covered by FU.1; noted here for
    cross-reference.
- **Plan**: delete the two zombie functions; FU.1 handles CSP.
- **Status**: todo

---

### Internationalization (i18n) — language packs

> **Pass 43** (proposed, deferred until Tier-1 + Tier-2 sweeps are done).
> Ship-shape RetroDB in any language; UI strings translated, retro-game
> data (titles, descriptions, scraper output) deliberately untranslated
> because that's content, not chrome.

#### Pass 43.1 Wire Flask-Babel + extract first language pack (HIGH, L)

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

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
- **Status**: todo

---

## Done index

Compact one-liner per landed pass.  Detail lives in git history
(`git log --grep "v2.83"` or similar), in `data/changelog.yaml`, and
in the commit messages themselves.  Listed in version order so the
landing sequence stays legible.

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
