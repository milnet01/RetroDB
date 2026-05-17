# Chunk c-004 audit
Files: 12  ·  Findings: 28 raw

---

## Findings by dimension

### Performance

- **[MED]** `tests/test_observability.py:133` — `test_factory_returns_dash_with_no_request_context` spawns a full Python subprocess to test a single log-record attribute.
  - **Consequence:** Adds ~300–600 ms on every run (Python startup + import chain). The stated reason ("module-scoped client holds a request context open") is now stale: the `client` fixture was converted to function-scoped (see line 19 comment). The test could be rewritten in-process using `app.test_request_context` deliberately left exited.
  - **Fix:** Remove the subprocess. Since the `client` fixture is function-scoped, call `log_manager.install_request_id_factory()` and create a log record outside any request context within the test directly — no subprocess needed.

- **[LOW]** `tests/test_observability.py:15` — The `client` fixture (function-scoped) fully boots the real Flask `app` module on every test that uses it. `TestHealthProbe` has 4 tests, `TestReadyProbe` has 2, `TestSlowRequestLogging` has 2: 8 full app-module re-inits per run.
  - **Consequence:** Minor but cumulative; the fixture could be `module`-scoped safely for `TestHealthProbe` and `TestReadyProbe` since those tests don't mutate app state (the TESTING flag and log factories are snapshotted). The original comment explaining the function-scope rationale specifically cites `caplog`/handler leakage — which only applies to the logging tests, not the health-probe tests.
  - **Fix:** Split into a `module`-scoped client for `TestHealthProbe`/`TestReadyProbe` and keep function-scoped for `TestRequestIdFactory`/`TestSlowRequestLogging`.

---

### Flakiness

- **[HIGH]** `tests/test_museum_job.py:87` and `tests/test_museum_job.py:130` — `worker_finished.wait(timeout=2.0)` is used in two tests to wait for a real background thread. The 2-second timeout is a wall-clock assertion: if the CI runner is under heavy load, the fake worker (which does no I/O) can still fail to signal within 2 s.
  - **Consequence:** These tests fail spuriously on loaded CI runners. The timeout is short enough to be a real risk — thread scheduling can stall far longer than 2 s in containerised CI under memory pressure.
  - **Fix:** Raise the timeout to 10 s (still safe for CI time budgets) or, better, use `threading.Event.wait(timeout=10)` and assert on the returned value; also add a comment marking this as "generous wall-clock guard, not a timing assertion."

- **[MED]** `tests/test_migrations.py:200–248` — `test_update_refreshes_updated_at` creates a backdated baseline via a direct `UPDATE games SET updated_at = '2000-01-01T00:00:00.000Z'` and then asserts `after > before`. The comment at line 201–204 correctly explains the no-sleep rationale. However, the final comparison uses `datetime.fromisoformat(first[0].rstrip('Z'))` — if the trigger ever changes its timestamp format to include a timezone suffix (e.g. `2000-01-01T00:00:00+00:00`), `rstrip('Z')` silently produces a malformed string that `fromisoformat` in Python < 3.11 will raise on.
  - **Consequence:** Not a flakiness risk under normal runs, but a latent bomb if the SQLite trigger format changes or Python version drops.
  - **Fix:** Use `datetime.fromisoformat(value.replace('Z', '+00:00'))` (Python 3.7+ compatible) or `datetime.fromisoformat(value.rstrip('Z')).replace(tzinfo=timezone.utc)`.

---

### Duplication

- **[MED]** `tests/test_migrations.py:22` and `tests/test_pass31_migrations.py:18` — Both files define a private `_open(path)` helper. The two implementations differ slightly (pass31 adds `conn.row_factory = sqlite3.Row`), so they cannot be trivially merged, but the pattern of a local `_open` wrapping `sqlite3.connect` is repeated.
  - **Consequence:** Any future row-factory change must be applied in two places; the divergence (row_factory set in one, not the other) has already caused at least one test in `test_migrations.py` to access rows by index (`row[0]`) rather than by name — a fragile pattern masked by the missing factory.
  - **Fix:** Add a `make_migration_conn(path, row_factory=None)` helper in `tests/_util.py`; both files call it with their preferred factory. This consolidates one decision point and surfaces the factory difference explicitly.

- **[LOW]** `tests/test_migrations.py:303` and `tests/test_pass31_migrations.py:183–186` — Both tests use the same `monkeypatch.setattr(migrations, 'MIGRATIONS', real_list[:N])` / restore pattern to stop the migration runner at a specific point and seed legacy rows. The pattern is repeated verbatim with only `N` differing.
  - **Consequence:** Third writer will repeat the pattern again; maintenance cost when MIGRATIONS list shuffles.
  - **Fix:** Extract a `partial_migration(conn, monkeypatch, stop_at)` context helper into `tests/_util.py` or the nearest conftest.

---

### Isolation

- **[MED]** `tests/test_museum_job.py:141` — `test_resume_refuses_when_already_running` sets `job.running = True` directly, bypassing the `_lock`. The production code's `resume_from_params` reads `self.running` under the lock. Setting it outside the lock in test code introduces a data-race risk if the test ever runs concurrently with another test that acquired the singleton FD, and also silently skips testing the lock-acquisition path on the guard check.
  - **Consequence:** If `resume_from_params` ever moves its `running` guard inside the lock (as good thread-safe practice), this test would require the lock to be held first — and setting `job.running = True` without the lock would be UB.
  - **Fix:** Set `running` within `with job._lock:` or use a `monkeypatch`/setter that goes through the lock.

- **[MED]** `tests/test_observability.py:26–43` — The `client` fixture mutates the shared `app_module.app.config['TESTING']` and `log_manager._request_id_installed` directly (not through `monkeypatch`). It uses manual `try/finally` to restore. This is correct but fragile: if a future refactor wraps the fixture body in `with app_module.app.app_context()` (common pattern), the `finally` block may not run on context exit, leaving the TESTING flag dirty.
  - **Consequence:** Low risk today, but the manual snapshot/restore pattern is exactly what `monkeypatch.setitem` exists to automate.
  - **Fix:** Replace the manual TESTING snapshot/restore with `monkeypatch.setitem(app_module.app.config, 'TESTING', True)` (as already done in `test_33_6_logout_clears_session`). Requires adding `monkeypatch` as a fixture parameter.

- **[LOW]** `tests/test_observability.py:29` — The `client` fixture sets `app_module.app.config['TESTING'] = True` using direct dict assignment. The `test_33_6_logout_clears_session` test in `test_pass33_34_hardening.py:84` notes the correct idiom is `monkeypatch.setitem`. This is an inconsistency within the same codebase where the preferred pattern is already documented but not applied here.
  - **Consequence:** Already handled by manual try/finally, but inconsistent — see isolation finding above.
  - **Fix:** Same as above.

---

### Determinism

- **[LOW]** `tests/test_migrations.py:198` — `assert row[0] is not None and row[0].endswith('Z')` relies on SQLite's `STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')` returning a string ending in `Z`. This is deterministic for the current trigger format but would silently pass for any non-null timestamp string (e.g. `'NULL_WAS_WRONG_FORMAT_Z'`). The assertion shape is "non-null and ends in Z" rather than "parses as a valid ISO datetime."
  - **Consequence:** If the trigger format changes (e.g. to a Unix epoch integer), the test would fail at `endswith('Z')` — which is fine. The real gap is that the test doesn't verify the timestamp is approximately correct (i.e., near `datetime.now(UTC)`).
  - **Fix:** Add `datetime.fromisoformat(row[0].replace('Z', '+00:00'))` as a parse-validation step; optionally assert the year is >= 2024.

---

### Accuracy

- **[HIGH]** `tests/test_observability.py:141` — `assert "'-'" in proc.stdout` passes if the string `'-'` appears anywhere in the subprocess output, including in error messages, tracebacks, or module paths. A subprocess crash that prints `import log_manager; AttributeError: module 'log_manager' has no attribute '-'` would match this assertion.
  - **Consequence:** The assertion form (`in proc.stdout`) could pass even when the subprocess actually errored, as long as the error message happened to contain `'-'`. `proc.returncode == 0` is asserted first (line 141), so a crash is caught, but a case where the code returns `repr('-')` in an error string without crashing would produce a false pass.
  - **Fix:** Assert `proc.stdout.strip() == "'-'"` (exact equality on the stripped output) rather than substring membership.

- **[MED]** `tests/test_pass33_34_hardening.py:31–34` — `test_33_2_avatar_not_in_allowed_fields` slices `src[start:end + 1]` where `end = src.index("]", start)`. This finds the first `]` after `allowed_fields = [`. If the list contains a nested structure or a comment with `]`, the slice terminates prematurely — masking a `'avatar'` entry in a later element.
  - **Consequence:** The assertion could be vacuously satisfied on a truncated slice, giving a false-pass if `avatar` appears after the first `]` in the source (e.g. in a comment like `# ['avatar'] was removed`).
  - **Fix:** Use `_util.slice_function` (AST-based) to extract the body of `api_user_settings`, then search for `'avatar'` in the full extracted text.

- **[MED]** `tests/test_pass33_34_hardening.py:266–275` — `test_34_6_asset_url_not_in_inject_config` asserts `"Pass 34.6" in inject_body` as proof that "the removal landed." A comment with that text is not the same as the removal actually landing — if someone reverts the functional change but keeps the comment, this test still passes.
  - **Consequence:** False confidence: the real behavioural contract (no `'asset_url': asset_url` in the dict) is already asserted on line 275; the comment-presence check adds nothing and can pass vacuously.
  - **Fix:** Remove the `assert "Pass 34.6" in inject_body` line — it tests documentation, not behaviour. The negative assertion `assert "'asset_url': asset_url" not in inject_body` is the load-bearing one.

- **[MED]** `tests/test_pass35_36_hardening.py:65–69` — `test_35_2_atomic_write_json_fsync_dir` asserts that a Pass comment marker (`"Pass 35.2"`) and a specific API call string (`"os.open(directory, os.O_RDONLY)"`) appear in `atomic_io.py`. Asserting on a comment marker has the same problem as the 34.6 finding above.
  - **Consequence:** The `"Pass 35.2" in src` line adds no value — the real check is the code string. If someone removes the comment but keeps the code, the test fails spuriously. If someone keeps the comment but removes the `os.open` call, the `os.open` assertion catches it anyway.
  - **Fix:** Remove `assert "Pass 35.2" in src`; keep only the `os.open(directory, os.O_RDONLY)` assertion.

- **[MED]** `tests/test_pass37_a11y.py:108–116` — `test_37_2_psn_trophies_modals_activate_focus_trap` asserts `src.count('ModalFocusTrap.deactivate') == 7`. This exact count will fail the moment a new deactivate call is legitimately added (e.g., adding a third modal) even though the contract (focus trap is always released) is still met. The docstring comment already acknowledges the count "grew to 7" once.
  - **Consequence:** Any future modal addition to `psn_trophies.html` breaks this test even when the focus-trap contract is correct. Maintenance friction for no additional safety.
  - **Fix:** Change to `>= 2` for activate (the meaningful lower bound: both modals are covered) and `>= activate_count * 2` for deactivate (each activate should have at least 2 close paths: close button + Escape). Or document the exact count with a date and link to the template snapshot so the intent is clear.

---

### Assertions

- **[MED]** `tests/test_pass32_hardening.py:124–130` — `test_32_6_ssrf_validate_rejects_private` makes three independent `validate_outbound_url` calls in one test body. The first failure (127.0.0.1) masks the others (10.0.0.1, 169.254.169.254).
  - **Consequence:** If 127.0.0.1 is accidentally allowed but 10.0.0.1 is still blocked, the test reports "127.0.0.1 not rejected" and the 10.0.0.1 result is never checked. Three bug-reports collapses to one.
  - **Fix:** `@pytest.mark.parametrize('url', ['http://127.0.0.1/', 'http://10.0.0.1/', 'http://169.254.169.254/latest/meta-data/'])` so each gets its own node.

- **[LOW]** `tests/test_museum_job.py:23–24` — `test_class_exposes_resume_from_params` asserts `hasattr(MuseumGenerateJob, 'resume_from_params')` and `callable(...)`. Both checks pass if `resume_from_params` is defined as a property or a non-callable attribute named identically.
  - **Consequence:** Minimal — the downstream `test_resume_*` tests would catch a broken implementation. But `hasattr` + `callable` provides weaker signal than calling `inspect.signature` or actually invoking the method.
  - **Fix:** Can be left as-is since downstream tests provide coverage. If kept, add `inspect.signature(MuseumGenerateJob.resume_from_params)` to assert it takes `params` and `progress` args.

---

### Naming / AAA

- **[LOW]** `tests/test_pass33_34_hardening.py:281` — `test_33_1_proxyfix_wired_under_flag` appears at the bottom of the file (line 281) even though it covers Pass 33 item 1. The file's section comments run 33.2, 33.3, 33.4, 33.5, 33.6, 33.8, 33.9, 33.10, 34.x, then 33.1 at the very end. Out-of-order placement makes the file confusing to navigate.
  - **Fix:** Move to the top of the Pass 33 block. (Low effort, cosmetic but aids maintenance.)

- **[LOW]** `tests/test_migration_012.py:9–14` — `_load_migration_012()` silently passes if `012_emulators.py` is missing on disk (`spec_from_file_location` would return `None`, and `module_from_spec(None)` raises `AttributeError` with an unhelpful message). The file exists today, but future migration renames would produce confusing failures.
  - **Consequence:** AttributeError: `'NoneType' object has no attribute 'create_module'` instead of a clear `FileNotFoundError: migration 012 not found at <path>`.
  - **Fix:** Add `if spec is None: raise FileNotFoundError(f"Migration file not found: {p}")` after `spec_from_file_location`.

---

### Coverage Gaps

- **[MED]** `tests/test_museum_job.py` — No test covers the path where `MuseumGenerateJob.resume_from_params` is called but the singleton FD is already held (i.e., another process owns it). The test at line 138 (`test_resume_refuses_when_already_running`) covers the `self.running` guard, but not the FD-lock contention path.
  - **Consequence:** FD-lock contention failure mode is untested; if `base.acquire_singleton_fd` raises rather than returns False, `resume_from_params` may propagate an uncaught exception.
  - **Fix:** Mock `services.jobs.base.acquire_singleton_fd` to return `None` / raise, assert `resume_from_params` handles gracefully.

- **[MED]** `tests/test_pass32_hardening.py` — Pass 32 items 32.3 (rate-limited endpoints listed correctly), 32.4 (SSRF accept-path: valid external URL accepted), 32.5, 32.9, 32.10, 32.12 have no test coverage in this file. The roadmap comment in the file header says "15 Pass 32 sub-items" but only 7 items (32.1, 32.2, 32.6, 32.7, 32.8, 32.11, 32.13, 32.14) have tests.
  - **Consequence:** Several hardening sub-items (particularly the accept-side of SSRF validation — no test confirms a valid external URL is let through) could regress silently.
  - **Fix:** At minimum, add `test_32_6_ssrf_validate_accepts_valid_external_url` asserting `validate_outbound_url('https://api.igdb.com/v4/games')` returns `(True, ...)`.

- **[LOW]** `tests/test_observability.py` — `TestSlowRequestLogging` has no test for the path where `g.request_start_time` is not set (e.g. a request that bypassed `assign_request_id`). The `log_slow_request` handler presumably guards against `AttributeError` via `getattr`; if it doesn't, it would crash on every request that didn't go through the before-request hook.
  - **Consequence:** The missing-attribute path is not regression-pinned. If `log_slow_request` is refactored to use `g.request_start_time` directly (instead of `getattr`), production would raise `AttributeError` on admin/probe routes.
  - **Fix:** Add a test that calls `log_slow_request` without prior `assign_request_id`, asserting no exception and no slow-request log entry.

---

### Splitting

- **[MED]** `tests/test_pass32_hardening.py:124` — `test_32_6_ssrf_validate_rejects_private` tests three distinct IPs (loopback, RFC-1918, APIPA/link-local) in one test node. First failure hides the rest (same issue as noted under Assertions).
  - **Fix:** `@pytest.mark.parametrize` (see Assertions finding above).

- **[MED]** `tests/test_pass35_36_hardening.py:156–169` — `test_36_1_escattr_js_string_escape` has two conceptually separate assertions: (1) that `escAttr` uses a safelist regex, and (2) that it emits `\x` or `\u` escapes. A regex failure hides the escape-type check.
  - **Consequence:** Low — both are implementation details of the same function. But the `assert "\\\\x" in body or "\\\\u" in body` branch (OR condition) means either escape style passes, which is intentionally permissive. Not a real split candidate; flagged for awareness.
  - **Fix:** Add a docstring note explaining why the OR is intentional (either escape dialect is acceptable). Not worth splitting.

---

### Fixtures

- **[MED]** `tests/test_pass31_migrations.py:41–55` — The `migrated_db` fixture opens a real on-disk SQLite file via `tmp_path`. Tests `test_two_users_can_have_same_npwr_id` (line 77) and `test_two_users_steam_achievements_coexist` (line 148) use `migrated_db` but then create a `users` table inline (line 81) even though `migrations.apply_pending` already created one. The inline `CREATE TABLE IF NOT EXISTS users` is redundant and could silently mask a migration regression where the `users` table wasn't created.
  - **Consequence:** The `IF NOT EXISTS` means the test won't fail even if migration omitted the users table — the test creates it itself, hiding the regression.
  - **Fix:** Remove the inline `CREATE TABLE IF NOT EXISTS users` in `test_two_users_can_have_same_npwr_id`; instead use `migrated_db.executemany("INSERT INTO users (role) VALUES (?)", ...)` directly (the table should already exist after full migration).

- **[LOW]** `tests/test_pass31_migrations.py:167–217` — `test_legacy_gap_rows_backfill_to_admin` uses `try/finally: conn.close()` instead of the `migrated_db` fixture or a context manager, while the rest of the class uses the fixture. The comment explains why (`migrated_db` is fully migrated, this test needs partial), which is valid. But the inconsistency means the test is the only one in the class that might leave a lingering connection on exception.
  - **Consequence:** Very low — `tmp_path` cleanup handles the file. But the manual `try/finally` around a SQLite connection is boilerplate that `contextlib.closing` would make idiomatic.
  - **Fix:** Wrap `conn` with `with contextlib.closing(_open(path)) as conn:` to make teardown automatic.

---

### Parametrisation

- **[MED]** `tests/test_pass32_hardening.py:20–34` — `test_32_1_validate_settings_path_rejects_forbidden` is correctly parametrised. However, the `expected_substring` parameter is `None` for three of the four cases (`'/'`, `'not-absolute'`, `'/nonexistent/path/xyz'`), so those nodes only verify `not ok` without checking the rejection reason. A wrong error message (e.g. returning `reason=""`) would pass.
  - **Consequence:** Minimal — `ok` is False is the contract. But the reason string is part of the UX (shown to the user); silent wrong messages would slip through.
  - **Fix:** Fill in expected substrings for all four cases (e.g. `'absolute'` for `'not-absolute'`, `'not found'` or `'exist'` for `/nonexistent`).

- **[LOW]** `tests/test_pass38_normalize_ratings_helper.py:11` — `from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401` is imported but never used in the file. The `# noqa: F401` suppresses the linter warning, making this effectively dead import.
  - **Consequence:** Dead import — no runtime or correctness impact. But the `# noqa` suppressor masks it, so it won't be caught by ruff either.
  - **Fix:** Remove the import entirely.

---

### Error Handling

- **[MED]** `tests/test_pass33_34_hardening.py:44–45` and `tests/test_pass33_34_hardening.py:54–55` — Both `test_33_3_update_user_enforces_length` and `test_33_4_force_change_on_admin_reset` use the same magic `start + 3000` slice to read `api_update_user`'s body. The actual function is 1869 chars, so 3000 is fine today. But there's no guard: if `api_update_user` is split or renamed, `src.index("def api_update_user")` raises `ValueError` with no helpful message.
  - **Consequence:** Test failure message is `ValueError: substring not found` — no context about which function was missing or why. This is a systemic issue across many source-grep tests in this chunk.
  - **Fix:** Use `tests._util.slice_function` (which returns `""` on miss and the caller can `assert body, f"api_update_user not found in routes/auth.py"`) for all such slices.

- **[LOW]** `tests/test_migration_012.py:9–14` — Same as the Naming finding: `_load_migration_012()` propagates `AttributeError` from `spec.loader.exec_module` with no helpful message if the migration file doesn't exist. (Duplicate root cause, different symptom than the naming aspect.)
  - **Fix:** Same `if spec is None: raise FileNotFoundError(...)` guard.

---

### Hardcoded Data

- **[LOW]** `tests/test_pass33_34_hardening.py:233–234` — `fixed_utc = datetime(2026, 4, 27, 23, 30, 0, tzinfo=timezone.utc)` is hardcoded to a date that is now in the past (today is 2026-05-17). This is intentional and correct — using a fixed historical date is exactly right for a deterministic clock-pin test. No action needed; flagged and dismissed.
  - **Note:** Not a real finding — the hardcoded past date is load-bearing. Dismissed.

- **[LOW]** `tests/test_migrations.py:44–48` — `_seed_legacy` inserts `genre='FPS,Action'` and `pegi_rating='12'` as hardcoded legacy format strings. These are load-bearing test inputs tied to the exact pre-migration format. If migrations 002 or 003 change their normalization rules, these values would need updating. No cross-file mechanism ensures they stay in sync with the migration logic.
  - **Consequence:** Low — the test immediately checks that migration output matches known results. But the input format is invisible unless you read both `_seed_legacy` and the migration scripts.
  - **Fix:** Add a comment `# Pre-migration format — must match what migration 002 rewrites from` inline with the INSERT.

---

### Doc Strings

- **[LOW]** `tests/test_museum_job.py` — The three test classes (`TestSingletonDedup`, `TestPersistenceContract`, `TestResumeFromParams`) have no module-level docstring. The module comment on line 1 describes only the job's persistence and dedup singleton aspects but does not explain the test structure or the singleton FD interaction — which is the most unusual aspect (two tests explicitly call `release_singleton_fd`).
  - **Fix:** Add a module docstring explaining why `release_singleton_fd` is called in fake workers (the real `_worker` always releases the FD on exit; fake workers must mirror this to avoid poisoning subsequent tests).

- **[LOW]** `tests/test_migration_012.py` — No module-level docstring explaining the difference between this file (migration-012-specific regression coverage) and `test_migrations.py` (general migration runner tests). A reader landing on either file needs to infer the distinction.
  - **Fix:** Add `"""Regression coverage for migration 012 (multi-emulator launch schema). See test_migrations.py for the general migration runner contract."""` at the top.

---

## Cross-file patterns (within this chunk)

1. **`src.index(...)` as the sole function-locator in source-grep tests (test_pass33_34_hardening.py, test_pass35_36_hardening.py, test_pass29_frontend.py):** At least 18 uses of `src.index("def <fn_name>")` or `src.index("function <name>")` across these three files. All raise `ValueError: substring not found` with no test-context message if the production function is renamed. The `tests/_util.slice_function` helper already exists for Python files; for JS, a `_js_method_body` helper exists in `test_pass29_frontend.py` but is not shared. Both should be standardised. The pattern is low-severity individually but systematic across the chunk.

2. **Comment-presence assertions as proof of code removal (test_pass33_34_hardening.py:273, test_pass35_36_hardening.py:68):** Two tests assert that a `"Pass XX.Y"` comment string exists in source as evidence that a change landed. This anti-pattern provides false confidence — the comment is not the change. Both cases already have a complementary functional or negative assertion that is the load-bearing check; the comment assertions are redundant and should be removed.

3. **`_open(path)` helper duplicated in test_migrations.py and test_pass31_migrations.py:** Both files define a private `_open` function wrapping `sqlite3.connect`. The two differ only in `row_factory`. This could be unified in `_util.py` (see Duplication finding).

4. **Magic fixed-size source slices (`start + 3000`, `+ 2500`, `+ 1500`) in test_pass33_34_hardening.py (lines 45, 55, 68, 211, 271) and test_pass35_36_hardening.py (lines 251, 280):** These are not bugs today (verified against actual function sizes), but they will silently clip the window if the functions grow beyond the fixed limit. The `slice_function` helper in `_util.py` handles this correctly for Python; these tests should migrate to it.

5. **The subprocess-in-test pattern (test_observability.py:133):** Spawning a child Python process is the only way to test "no Flask request context" without the module-scoped fixture leak concern — but the comment justifying it (line 129) refers to the old module-scoped fixture that was already removed. The justification is stale.

---

## Summary

- CRITICAL: 0
- HIGH: 2
- MED: 15
- LOW: 11
- INFO: 0

**Total: 28**
