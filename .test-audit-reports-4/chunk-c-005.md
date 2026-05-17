# Chunk c-005 audit
Files: 12  ·  Findings: 23 raw

---

## Pre-pass triage

- **tests/test_pass40_security.py:914** — `sleep_call` ❌ FALSE POSITIVE  
  Line 914 is inside `TestPass40_10ShutdownAwareSleep.test_no_bare_time_sleep_in_jobs`, which *searches production source files for `time.sleep(` calls and fails if found*. The string `'time.sleep('` appears in the test as a grep needle, not as a call. No sleep in the test itself. This is the fix, not the problem.

- **tests/test_pass40_security.py:934** — `sleep_call` ❌ FALSE POSITIVE  
  Line 934 is the `if 'time.sleep(' in line:` check inside the same source-scan loop. Again a string literal, not a call to `time.sleep`. No flakiness risk.

- **tests/test_pass41_security.py:380** — `hardcoded_password` ❌ FALSE POSITIVE  
  Lines 380–381 are string literals `'password: admin'`, `'password=admin'`, `"password='admin'"` used as *needles in a security regression test* that asserts these strings are absent from `services/database_init.py`. The test is purposefully pinning that the default-admin creation log line no longer leaks credentials. These are obviously fake test markers, not real credentials; gitleaks should allowlist them.

---

## Findings by dimension

### Performance

- **[LOW] test_pass40_security.py:819 (test_worker_invokes_full_persist_lifecycle)**  
  `done.wait(timeout=2.0)` spins a real background `Thread` via `job.start()`. Even with a mocked empty `IMAGE_PATH`, starting a real threading.Thread for each run adds observable overhead per test invocation. Current approach is already well-motivated (using Event signal avoids a sleep loop) but the 2 s ceiling is a flakiness budget, not a necessity.  
  Fix: This is a borderline case — the Event pattern already avoids polling. No action required unless timing data shows this test taking > 200ms consistently.

- **[LOW] test_pass46_frozen_paths.py:62 (test_split_takes_effect_when_frozen)**  
  Evicts and re-imports `config`, `settings_manager`, `log_manager`, `routes.scraper`, `app` — five heavy module imports per test run. The module eviction is necessary for correctness (frozen-mode check runs at module level), but it makes this test unusually expensive. The `reloaded_app` fixture at line 131 duplicates a subset of this eviction pattern.  
  Fix: No structural fix available without changing the SUT. Document why with a timing note. Ensure this test isn't inadvertently picked up by parallel runners.

---

### Flakiness

- **[MED] test_pass40_security.py:862–884 (test_worker_invokes_full_persist_lifecycle)**  
  Although the `done.wait(timeout=2.0)` approach correctly replaces the prior sleep-poll pattern, the test relies on a real `Thread` that must complete within 2 s. If the OS scheduler is heavily loaded on CI (e.g. high-parallelism matrix build), the worker thread may not be scheduled for > 2 s, causing a spurious `done.wait(timeout=2.0) → False`. The test body notes "in practice this returns within a couple of ms" but the 2 s timeout is the only guard.  
  Fix: Increase ceiling to 5 s (matching poll budgets elsewhere in the suite, e.g. other worker tests), or run the worker synchronously via `Thread.start → Thread.run()` (the same monkeypatch used by `test_convert_e2e_rejects_traversal` at line 328). The synchronous pattern is strictly more reliable.

- **[LOW] test_pass45_security.py:967–1079 (TestPass45_7OrphanCleanupRace)**  
  `test_clean_skips_files_modified_during_cleanup_window` calls `os.utime(str(target), (future, future))` where `future = time.time() + 60`. If `find_orphaned_media` sets `scan_started_at` *after* the utime call (because wall time is not frozen), the mtime-ahead-of-scan-start guard may or may not fire depending on clock resolution and scheduling. This is not a problem in the current implementation (the test sets mtime to now+60, so it's always ahead), but there is no clock-freeze — this could theoretically false-negative on a system where `time.time()` has coarser than 1-second resolution. LOW because the +60 margin is very generous.  
  Fix: Freeze time or use a clearly large sentinel (e.g. `+3600`) for the future mtime. The current `+60` is fine in practice but fragile under scrutiny.

---

### Duplication

- **[MED] test_pass40_security.py:33–35, test_pass41_security.py:25–28, test_pass42_normalize_game_edit.py:17–19, test_pass45_security.py:13–16, test_pass46_frozen_paths.py:25–28**  
  Five files each define their own `_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` + `sys.path.insert(0, _REPO_ROOT)` block at module level. `tests/_util.py` was created specifically to centralise this pattern (its docstring even says "~15 test files were copy-pasting" this), and the pass38 files correctly import `REPO_ROOT` from `_util`. The pass40/41/42/45/46 files still duplicate it instead.  
  Fix: Replace the local `_REPO_ROOT` definition blocks with `from tests._util import REPO_ROOT as _REPO_ROOT` (as pass38 files do). The `sys.path` manipulation then also drops away because `_util.py` handles it.  
  Note: possibly_also_in_other_chunks: true — other test files outside this chunk may have the same pattern.

- **[MED] test_pass40_security.py:286–356, 358–431, 432–489 (three separate admin-auth preambles)**  
  The three `test_convert_*` tests inside `TestPass40_2ChdConvertVerifyPathValidation` each independently repeat the same ~25-line admin fixture: monkeypatching `get_current_user`, `get_user_settings`, `load_settings`, `TESTING`, creating a test client, seeding session with `user_id=1` and `_csrf_token`. Identical blocks at lines ~330-342, ~405-415, ~463-475. The `logged_in_client` fixture pattern in `test_routes_launch.py` (line 50-63) shows this project already knows how to factor this.  
  Fix: Extract a `@pytest.fixture def admin_client(monkeypatch, tmp_path)` or a `_make_admin_client(monkeypatch, tmp_path, rom_root)` helper for use across these three tests. Saves ~75 lines and makes failure messages point to the fixture, not each duplicate.

- **[LOW] test_pass41_security.py:221, 296, 346 (repeated `_read` helpers)**  
  `TestPass41_2AMigrationDeferForeignKeys._read`, `TestPass41_2BConnectionLeaksClosed._read`, and `TestPass41_3ARedactorOrder._read_app_py` each implement the same `open(path, encoding='utf-8').read()` one-liner. `tests/_util.py`'s `read_source(rel_path)` already does exactly this.  
  Fix: Replace with `from tests._util import read_source`.

---

### Isolation

- **[HIGH] test_pass41_security.py:71–88 (_cleared_login_attempts fixture)**  
  The `_cleared_login_attempts` fixture correctly snapshots and restores `services.security._login_attempts`. However, it takes the lock (`with sec._lock`) during both setup and teardown. If `services.security._lock` is a module-level `threading.Lock` and this fixture is invoked under `pytest-xdist` with workers sharing the same interpreter, the snapshot/restore interleaving can leave the dict in an inconsistent state between test isolation boundaries. More concretely: two tests that both use `_cleared_login_attempts` cannot safely run concurrently because the snapshot/clear/restore cycle is not atomic with respect to the outer lock.  
  Fix: This is a known limitation of module-level singleton state in parallel test runners. Document explicitly with `@pytest.mark.not_parallel` if xdist is ever enabled, or replace the fixture with a monkeypatch swap (`monkeypatch.setattr(sec, '_login_attempts', {})`) which has automatic single-test scope.

- **[MED] test_pass46_frozen_paths.py:82–101 (test_split_takes_effect_when_frozen)**  
  The test evicts `config`, `settings_manager`, `log_manager`, `routes.scraper`, `app` from `sys.modules` inside the test body (not via `monkeypatch`), restoring them in a `finally` block. If an exception occurs between the eviction and the `finally` teardown, and if pytest catches the exception and re-runs collection (e.g. with `--lf`), the partially-loaded frozen-mode `config` leaks into the next test's namespace. The `finally` block does re-evict, but it does *not* re-import — the comment says "the next `import config` (post-teardown) does the right thing", which relies on pytest not importing `config` again before the test session's module cache is flushed.  
  Fix: Use `monkeypatch` for the `sys.modules` pops (auto-restored on teardown) or at minimum add `importlib.import_module("config")` at the end of the `finally` block to leave a known-good dev-mode `config` in the cache.

- **[LOW] test_pass41_security.py:527–560 (_stub_igdb_with_401_then_200 static method)**  
  This method mutates `igdb._igdb_token_cache` via direct dict assignment on the monkeypatched reference (`igdb._igdb_token_cache['token'] = 'FRESH'` inside `fake_auth`). Because `_stub_igdb_with_401_then_200` is called from two separate test methods (`test_401_retry_returns_correct_result`, `test_401_retry_updates_cache`), both tests create independent monkeypatched `_igdb_token_cache` instances. This is correct thanks to `monkeypatch.setattr` on the dict reference. Flagging at LOW because the shared setup method makes it non-obvious that each test call gets its own monkeypatched dict; a reader might assume state leaks between the two test methods.  
  Fix: Add a docstring to `_stub_igdb_with_401_then_200` noting that callers receive fresh monkeypatch scope.

---

### Determinism

- **[LOW] test_pass38_scrape_history_helper.py:69–72**  
  The timestamp assertion uses `re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', ...)`, which validates format but not that the timestamp is close to `datetime.now()`. If the helper ever erroneously emits a hardcoded epoch string like `"2000-01-01T00:00:00"`, this test passes. This is an intentional trade-off (the test specifically calls out avoiding the "key present" tautology), but an upper-bound check (timestamp within last N seconds) would be stronger.  
  Fix: Add `assert datetime.fromisoformat(entry['timestamp']) > datetime.now() - timedelta(seconds=5)` to reject obviously wrong timestamps. Keep the format regex as a guard against non-ISO values.

---

### Accuracy

- **[MED] test_pass40_security.py:566–573 (test_create_m3u_e2e_rejects_outside_rom_path)**  
  The assertion is `assert resp.status_code in (400, 302, 403, 500)`. Including `500` in the acceptable status set means an unhandled server error (traceback) would pass the test. The intent is "the path was not accepted", but a 500 gives no confidence the *validator* ran — it could be an unrelated crash.  
  Fix: Remove `500` from the accepted set. If 500 appears in practice, diagnose and fix the underlying error rather than accepting it as a valid security outcome.

- **[MED] test_pass40_security.py:476–488 (test_convert_with_only_out_of_bound_files_invokes_no_chdman)**  
  The status assertion is `assert resp.status_code in (200, 400, 422)`. Accepting both 200 (worker processed and rejected all files silently) and 400/422 (rejected at the route level) is intentional per the comment. However, the only meaningful assertion is `assert not seen_argv`. The status-code assertion adds no additional signal and could mask a future path where the route returns 200 but chdman *was* called (if the `seen_argv` append silently failed). These two assertions together are fine, but they should be in separate logical checks to make failure attribution clear.  
  Fix: No code change required, but add a failure message to `assert not seen_argv` that includes `resp.status_code` for context.

- **[LOW] test_pass38_resume_helpers.py:153–178 (TestCallsitesUseHelpers)**  
  The source-grep assertions check that `'pad_resume_game_ids' in src` and `'restore_progress_counts' in src`, which confirms the *import* but not the *call*. A developer could import the helpers at the top and then call the old inline pattern (`[None] * resume_index + remaining_ids`) for the actual logic. The assertions are named "imports pad_and_restore" but the comment in the class docstring says "source-grep regression: every refactored job module imports the helpers".  
  Fix: Strengthen the grep from `'pad_resume_game_ids' in src` to checking the call site exists: `'pad_resume_game_ids(' in src`. One character change; eliminates the import-without-call blind spot.

- **[LOW] test_pass41_security.py:961 (test_no_for_g_in_loops)**  
  Uses `re.findall(r'\bfor\s+g\s+in\b', code_only)`. This correctly catches `for g in list(...)` but would miss `(g for g in ...)` generator expressions (where `\b` may not match as expected adjacent to `(`). In practice the file is unlikely to have generator expressions named `g`, but the regex is slightly under-anchored.  
  Fix: Use `re.findall(r'\bfor\s+g\s+in\s', code_only)` (trailing `\s` tightens the right boundary) or additionally scan for `g for g in`.

---

### Security

- **[MED] test_pass40_security.py:1025, 1048, 1061, 1082, 1092, 1209**  
  Six `open(path).read()` calls without context managers. The fd is implicitly closed when the returned string is GC'd (CPython refcount), but PyPy / Jython / test-runners with aggressive memory profiling can hold the fd open past test boundaries. More importantly, this was the exact pattern that `tests/_util.py`'s `read_source` was created to replace (per its docstring: "replaces ~15 bare `open(...).read()` sites flagged by the audit"). These six sites were missed.  
  Fix: Replace `open(path).read()` with `read_source(rel_path)` (import from `tests._util`) or at minimum wrap in `with open(path, encoding='utf-8') as f: src = f.read()`.

- **[MED] test_pass41_security.py:187, 221, 296, 346, 374, 422, 866, etc. (many bare `open(...)` calls)**  
  Same pattern as the test_pass40 issue above. `test_pass41_security.py` has ~30+ instances of `open(os.path.join(_REPO_ROOT, ...), encoding='utf-8').read()` without context managers. Some use `body = open(...).read()` (no `with`). Unlike test_pass40 where `read_source` is not imported, test_pass41 does `from tests._util import read_source, slice_function` at line 23 but still uses bare `open()` directly in most of the class methods.  
  Fix: Replace bare `open(...).read()` calls with `read_source(rel_path)` via the already-imported helper from `tests._util`.

---

### Verbosity

- **[MED] test_pass40_security.py:640–677 (TestPass40_6PlayersNormalization — 9 single-assertion tests)**  
  Nine separate test methods (`test_none_returns_none`, `test_empty_string_returns_none`, `test_int_passthrough`, etc.) each call `normalize_players_value` with one input and assert one output. The same contract is expressed more compactly in the neighbouring file `test_pass42_normalize_game_edit.py:72–80` via `@pytest.mark.parametrize`. The two test classes (`TestPass40_6PlayersNormalization` and `TestNormalizePlayers`) cover overlapping ground.  
  Fix: Collapse `TestPass40_6PlayersNormalization` into the `TestNormalizePlayers` parametrize table in `test_pass42_normalize_game_edit.py`, or replace the 9-method class with a single `@pytest.mark.parametrize` table.

- **[LOW] test_pass40_security.py:165–181 (test_returns_false_on_network_exceptions)**  
  Uses `lambda: __import__('requests').exceptions.Timeout(...)` — a nested import inside a lambda. The `__import__` idiom is unusual and hard to read. `requests` is available at test-module level (imported via `scraper.retroachievements`).  
  Fix: Import `requests` at module top or inside the test method; replace with `lambda: requests.exceptions.Timeout(...)`.

---

### Naming / AAA

- **[LOW] test_pass38_scrape_history_helper.py:21 (fixture named `connection` returns a `sqlite3.Connection`)**  
  The fixture comment itself explains "the fixture name was previously `cursor` but it returned the Connection" (a prior audit finding). The current name `connection` is correct. However, test bodies call `connection.cursor()` to get a cursor — the fixture returns the connection and tests create cursors ad hoc. A fixture named `conn` with a matching `cursor = conn.cursor()` in tests would be slightly cleaner, but the current naming is clear.  
  Info only — no action required.

- **[LOW] test_pass41_security.py:73 (_cleared_login_attempts fixture)**  
  The fixture is named with a leading underscore (`_cleared_login_attempts`), implying it's "private". In pytest, fixture names with leading underscores are still public fixtures; the naming convention is misleading. The `c-006 I-2` comment explains the intent but the leading underscore gives a false impression that it can't be reused by other tests.  
  Fix: Rename to `cleared_login_attempts` (no leading underscore).

---

### Coverage gaps

- **[MED] test_pass38_ra_check_helper.py — no test for ra_game_id=0 / ra_achievement_count=0 boundary**  
  `test_returns_false_when_has_achievements_is_false` tests `{'has_achievements': False, 'id': 99, 'achievement_count': 0, 'points': 0}`. There is no test for the case where `has_achievements=True` but `achievement_count=0` (a game exists on RA with 0 achievements yet). The helper's return value and DB write behaviour for this edge case are untested.  
  Fix: Add a test `test_writes_ra_columns_when_achievement_count_is_zero` with `has_achievements=True, achievement_count=0`.

- **[LOW] test_pass39_supply_chain.py — no test for `select_pip_args` when lockfile exists but is empty/corrupt**  
  `test_select_pip_args_falls_back_when_lockfile_missing` and `test_select_pip_args_returns_missing_when_neither_present` cover the no-file cases. A lockfile that exists but is 0 bytes (or truncated) would trigger the `lock` branch but break `pip install --require-hashes`. This edge case is untested.  
  Fix: Add a test that creates a 0-byte `requirements.lock` and asserts `select_pip_args` either falls back to `fallback` or raises a meaningful error.

- **[LOW] test_pass46_frozen_paths.py:104–127 (TestPass46_3_DependentModulesFollowConfig)**  
  The three tests pin that `settings_manager.SETTINGS_FILE`, `log_manager.LOGS_DIR`, and `routes.scraper.SCRAPER_SETTINGS_FILE` are anchored to `config.BASE_DIR`. There is no equivalent test for `routes.scraper`'s other path (`SCRAPER_SETTINGS_FILE`) in a frozen-mode context. More critically, no test checks that `config.DB_PATH` is still correctly anchored in the non-env-override dev path when `RETRODB_DB_PATH` is explicitly unset (the test at line 52 conditionally skips when the env var is set, but doesn't assert when it isn't).  
  Fix: Explicitly `monkeypatch.delenv("RETRODB_DB_PATH", raising=False)` before checking `config.DB_PATH` in `test_db_path_under_base_dir` so the test is unconditional.

---

### Setup / Teardown

- **[LOW] test_pass41_security.py:247–278 (test_migrations_still_apply_cleanly)**  
  Calls `init_database()` which creates a real SQLite file in `tmp_path`. The `conn.close()` in the `finally` block is correct. However, `init_database()` may also open its own connection(s) internally that aren't closed until the module is torn down. On Windows this would prevent `tmp_path` cleanup. Low priority (Linux/macOS CI), but worth noting.  
  Fix: Confirm `init_database()` closes all internal connections, or add a `gc.collect()` after `conn.close()` to flush CPython's refcount-based fd closures before `tmp_path` teardown.

---

### Splitting

- **[MED] test_pass41_security.py:562–620 (TestPass41_5BIgdbTokenRefreshOn401 — 3 tests sharing a static helper)**  
  `_stub_igdb_with_401_then_200` performs both the setup AND the actual call under test (`igdb.igdb_request(...)`) and returns the result. This means the helper does more than arrange — it also acts. The two tests that use it (`test_401_retry_returns_correct_result` and `test_401_retry_updates_cache`) each verify a different aspect of the same call, but that call is shared between them: a failure in `_stub_igdb_with_401_then_200` makes both tests fail with an identical error and neither message distinguishes which contract failed.  
  Fix: Make `_stub_igdb_with_401_then_200` a `@pytest.fixture` or factor the action (the `igdb_request` call) into the test bodies, so each test's failure message names only its own assertion.

---

### Doc strings

- **[LOW] test_retroarch_detect.py:1–6 (module-level docstring)**  
  The module has a module docstring (lines 1–5) but individual test functions `test_detect_endpoint_registered`, `test_probe_binary_falls_through_to_which`, etc. have no docstrings. Given the tests are checking non-obvious wire contracts (RetroArch flatpak probe, binary validation), a one-line "why this matters" on each would help a future reader.  
  Fix: Add one-line docstrings to the simpler tests that lack context beyond their name.

- **[LOW] test_routes_launch.py (no module docstring)**  
  The file has no module-level docstring. It's straightforward for an experienced reader but a one-liner ("Pins the launch-route wire shape and auth gating; see routes/launch.py") would match the style of `test_retroarch_detect.py` and the pass38 files.  
  Fix: Add a module docstring.

---

## Cross-file patterns (within this chunk)

1. **`_REPO_ROOT` inline definition** — 5 of 12 files (`test_pass40`, `test_pass41`, `test_pass42`, `test_pass45`, `test_pass46`) define their own `_REPO_ROOT` + `sys.path.insert` block instead of using `from tests._util import REPO_ROOT`. The pass38 files (all 4) correctly use `_util`. This is the strongest cross-file pattern in the chunk.

2. **Bare `open(path).read()` without context manager** — identified in `test_pass40_security.py` (6 sites) and `test_pass41_security.py` (~30 sites). `_util.py`'s `read_source()` was created to fix this but ~36 call sites were missed. `test_pass45_security.py` uses `with open(...) as f` correctly throughout.

3. **Admin-client fixture duplication** — `test_pass40_security.py`, `test_pass41_security.py`, `test_pass45_security.py`, and `test_routes_launch.py` all independently monkeypatch `get_current_user → fake_admin + get_user_settings + load_settings + TESTING + session['_csrf_token']`. The `logged_in_client` fixture in `test_routes_launch.py:50` is the cleanest version; the others inline it at each test method.

4. **Source-grep tests still present at significant scale** — The pass40/41/45 security files contain many `assert 'X' in body` source-grep checks. The file header of `test_pass40_security.py` (lines 6–25) explicitly defends keeping these where "the contract IS a source-pattern rule". This is a deliberate project-level decision, not a finding.

---

## Summary
- CRITICAL: 0
- HIGH: 1 (isolation — `_cleared_login_attempts` fixture safety under parallel runners)
- MED: 9
- LOW: 13
- INFO: 0
