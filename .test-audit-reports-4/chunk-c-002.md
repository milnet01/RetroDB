# Chunk c-002 audit
Files: 12  ·  Findings: 22 raw

Chunk covers: test_database_backup, test_emulator_autodetect, test_emulator_registry_routes,
test_emulator_seeder, test_etag_and_gzip, test_formatters, test_game_query, test_game_utils,
test_graceful_shutdown, test_hltb_alt_titles, test_hltb_bulk, test_hltb_endpoint.

---

## Findings by dimension

### Flakiness

- **[HIGH]** `test_graceful_shutdown.py:111` — Wall-clock upper-bound assertion `assert elapsed < 1.0` on
  a test that blocks for `timeout=0.3s`. On a CI runner pinned to a single vCPU or under heavy load
  the join + overhead can easily reach or exceed 1.0 s, producing a spurious failure with no signal
  about the actual bug.
  Fix: replace the `elapsed < 1.0` bound with a multiplier of the timeout value
  (`assert elapsed < timeout * 4`), or assert only `stuck._thread.is_alive()` (already present at
  line 113), which is a stronger and load-independent check. The comment on lines 106–110 already
  explains the reasoning — the assert on line 111 contradicts it.

- **[MED]** `test_graceful_shutdown.py:59–67` — `test_sets_shutdown_event` calls
  `base_mod.request_shutdown(timeout=0.1)` against the real singleton module without the
  `isolated_singletons` fixture. Any real job singleton that happens to be `running=True` in the
  package at the time this test runs will have `.cancel()` called on it, producing a real
  side-effect that bleeds into later tests. The `finally: clear()` on line 66 only resets the
  event — it does not un-cancel any real jobs.
  Fix: add `isolated_singletons` fixture to `test_sets_shutdown_event` or call
  `base_mod.shutdown_requested.clear()` defensively in `isolated_singletons` teardown as well.

### Isolation

- **[HIGH]** `test_emulator_registry_routes.py:109–137` — `test_viewer_cannot_create` and
  `test_viewer_cannot_delete` (lines 109 and 125) each inline a full three-monkeypatch + session
  client setup instead of using the `admin_client` fixture pattern already established at line 34.
  This is not just duplication — both tests are *inside* `TestEmulatorCRUD` but bypass the class
  fixture, meaning any future state that `admin_client` guards will not be applied to these two
  tests, creating silent isolation divergence.
  Fix: extract a `viewer_client` fixture parallel to `admin_client` and use it in both viewer tests.

- **[MED]** `test_etag_and_gzip.py:17–28` — The module-scoped `client` fixture mutates
  `app.config['TESTING']` using a manual save/restore pattern instead of `monkeypatch`. If any test
  in the module raises *before* the `finally` block in the fixture (e.g., during yield), the config
  key is correctly restored — that part is safe. The risk is subtler: `scope="module"` means the
  fixture runs once across all tests in the class, and the `TESTING=True` side-effect persists for
  the entire module. If another module in the same process session happens to run between setup and
  teardown (unlikely with pytest's default ordering but possible with `--randomly`), it inherits
  `TESTING=True`. Not critical, but worth noting.
  Fix: use `monkeypatch` with `scope="module"` (requires `@pytest.fixture(scope="module")` +
  `monkeypatch` also module-scoped, which pytest supports via `request.getfixturevalue`), or accept
  the current pattern as intentional given the comment at lines 20–22.

- **[MED]** `test_graceful_shutdown.py:59–67` — `shutdown_requested` is a real package-level
  threading.Event. The test clears it at entry and in a `finally` block, but if the test is
  interrupted mid-run (e.g., KeyboardInterrupt in CI) the `finally` may not fire before the process
  dies. This is acceptable for a module-level event but note that no other test in the suite
  (within the chunk) independently resets it — if `test_sets_shutdown_event` runs after a
  previously-failed run with the event set, the test will pass vacuously.
  Fix: ensure `isolated_singletons` (or a dedicated fixture) always calls
  `base_mod.shutdown_requested.clear()` in its teardown, so event state is predictable regardless
  of test order.

### Determinism

- **[MED]** `test_hltb_alt_titles.py:90–94` — `test_alternate_title_equal_to_primary_skipped`
  asserts `unique_titles == {'Doki Doki Panic'}` (a set). The fake_search always returns a good
  match, so the multi-step search logic may call the function more than once for valid reasons
  (e.g., platform-scoped search then titleonly search). The test's assertion on `unique_titles`
  (distinct titles) is correct for the de-duplication contract, but the comment "Only the primary
  title should have been searched (once per step)" implies there's also a call-count contract that
  isn't asserted. If the SUT adds a third search step using the same title, the test still passes
  even though the contract changed.
  Fix: add `assert len(calls) == <expected_step_count>` alongside the `unique_titles` assertion if
  call-count is part of the spec, or remove the comment if it is not.

### Accuracy

- **[HIGH]** `test_emulator_registry_routes.py:16–21` — `test_mutating_routes_require_admin` is a
  source-grep check: it reads `routes/emulators.py` and asserts that either `@admin_required` or
  `permission_required('manage_settings')` appears anywhere in the file. This passes if the
  decorator appears on *any* function — including a helper or a read-only route — even if the
  mutating handlers (POST, PUT, DELETE) are completely unprotected. The test cannot distinguish
  file-level presence from per-handler application.
  Fix: narrow the check by slicing each mutating function body with `slice_function()` from
  `tests/_util.py` and asserting the decorator appears within that slice, or — better — use the
  HTTP-level tests (`test_viewer_cannot_create`, `test_viewer_cannot_delete`) as the canonical
  auth-enforcement check and delete this source-grep entirely.

- **[HIGH]** `test_hltb_endpoint.py:87` — `test_search_url_points_to_bleed` asserts
  `src.count('"/api/bleed"') + src.count("'/api/bleed'") + src.count('/api/bleed') >= 3`. Because
  `/api/bleed` is a substring of `/api/bleed/init`, every occurrence of `/api/bleed/init` also
  counts toward the `src.count('/api/bleed')` total. The test would pass even if there were zero
  bare `/api/bleed` search calls and three `/api/bleed/init` lines, defeating its purpose of
  verifying the search endpoint.
  Fix: count only whole-path occurrences: `src.count('"/api/bleed"') + src.count("'/api/bleed'")
  >= 2` (exclude the init-URL substring) or use a regex `re.findall(r'["\']\/api\/bleed["\']', src)`.

- **[MED]** `test_emulator_seeder.py:49–57` — `test_seeder_inserts_system_emulators` asserts that
  the `psx` system's default emulator is `'DuckStation'` as a hardcoded string. If the seed file
  is ever updated to change the PSX default to a different emulator, this test fails with no
  diagnostic hint about *why* that change is wrong vs. deliberate.
  This is a reasonable contract pin, but note it couples the test tightly to seed-file content
  rather than the seeder's structural behaviour. Acceptable as-is; document that the seed file and
  this assertion must be updated together.

- **[MED]** `test_game_query.py:55` — `assert '42' in vals` for the system filter test. `in` on a
  list checks all elements, so this passes even if `'42'` appears as part of a different filter
  value (e.g., a LIKE pattern like `%42%`). For a single-value equality bind, `assert vals == ['42']`
  or `assert vals[0] == '42'` would be tighter and produce a clearer failure diff.
  Fix: `assert vals == ['42']` (single param, single value).

- **[LOW]** `test_game_query.py:73` — `assert 'Z' in vals` for the letter-alpha filter. Same issue
  as above — passes if `'Z'` appears anywhere in the vals list, including as a component of another
  parameter. Given the test description ("must be the literal string 'Z'"), use `assert 'Z' in vals
  and vals.count('Z') == 1` or `assert vals[-1] == 'Z'` (assuming letter is always appended last).

### Coverage gaps

- **[MED]** `test_database_backup.py` — No test covers the case where `backup_database` is called
  with a *non-existent source* file. The current tests cover missing *destination directory*
  (line 144) but not a missing source. The `sqlite3.connect()` call on a non-existent path creates
  an empty DB rather than raising, meaning the backup could silently succeed with a 0-row copy.
  Whether `backup_database` guards against this is untested.
  Fix: add `test_backup_missing_source_raises_or_empty` to pin the contract.

- **[MED]** `test_graceful_shutdown.py` — `_SINGLETON_NAMES` at line 19 lists 10 job singleton
  names, but `test_calls_cancel_on_running_jobs` (line 69) only sets two of them (`bulk_scrape_job`
  and `ra_sync_job`). The other 8 remain `None` (set by `isolated_singletons`). There is no test
  that verifies `cancel()` is called across *all* running singletons simultaneously — only that the
  first one in the list is cancelled. A future refactor that breaks `ra_refresh_job`'s cancel path
  would go undetected.
  Fix: populate all 10 singletons with `_FakeJob(running=True)` in a test and assert all 10
  `cancel_called` are True.

- **[LOW]** `test_hltb_bulk.py:56–65` — `test_main_missing_extras_and_completionist_present`
  documents itself as "uncovered branch flagged by audit (LOW)" and only asserts `s is not None`
  and `'8' in s and '12' in s`. The exact format string for this partial case is not pinned.
  Fix: assert the exact expected string once the behaviour is confirmed, to make this a regression
  pin rather than a presence check.

### Duplication

- **[MED]** `test_emulator_registry_routes.py:109–137` — `test_viewer_cannot_create` (line 109)
  and `test_viewer_cannot_delete` (line 125) repeat an identical 8-line block: three monkeypatch
  setattr calls + test_client() construction + session_transaction CSRF setup. This is also the
  same pattern as `admin_client` (line 34) modulo the role string.
  Fix: extract a `viewer_client` fixture (or a parametric `_make_client(role)` helper) to eliminate
  the duplication. Also see the Isolation finding above.

- **[LOW]** `test_hltb_endpoint.py:29–31` — inline `_REPO_ROOT` / `sys.path.insert` at module
  level despite `tests/_util.py` having been introduced specifically to centralise this boilerplate
  (the `_util.py` docstring explicitly names this pattern as the one it replaced). The same
  leftover pattern exists in `test_emulator_seeder.py:8–11`.
  Fix: replace with `from tests._util import REPO_ROOT` and remove the inline boilerplate.

### Fixtures

- **[MED]** `test_emulator_seeder.py:14–27` — The `db` fixture is function-scoped (default) and
  re-runs the full migration script (`012_emulators.py`) via `importlib.util` on every test.
  There are 5 tests in the file; `seeded_db` depends on `db`, so the migration runs 5 times.
  Since the in-memory DB and migration are read-only relative to test logic (tests never mutate
  schema), this could be `scope="module"` without isolation risk.
  Fix: `@pytest.fixture(scope="module") def db():` — the `seeded_db` fixture stays function-scoped
  (it writes seed data) but the schema setup runs once.

- **[LOW]** `test_emulator_seeder.py:31–37` — `seeded_db` fixture calls `seed_emulators_from_file`
  inside the fixture body but returns `db` (not `yield`), so there is no teardown. Because it uses
  an in-memory SQLite DB this is fine — the connection is closed by `db`'s own teardown. No action
  needed, but worth noting for future reviewers if `db` ever becomes file-backed.

### Hardcoded data

- **[MED]** `test_emulator_registry_routes.py:40,115,131` — The settings stub hardcodes
  `'rom_path': '/tmp'`. On a system where `/tmp` is mounted `noexec` or restricted (some hardened
  Linux configs), any downstream code that tries to use this path as a real directory could behave
  differently from a real run. More importantly, if the route under test validates that `rom_path`
  is a *real* directory, `/tmp` might pass that check when a clearly-fake value like
  `'/nonexistent/fake/path'` would expose the validation gap.
  Fix: use `str(tmp_path)` via a pytest fixture parameter, or use an obviously sentinel value
  that will never accidentally pass filesystem existence checks.

- **[LOW]** `test_emulator_registry_routes.py:43,118,133` — CSRF token hardcoded as `'tok'` in
  both the session setup and the `X-CSRF-Token` header. This is not a secret leak — it is clearly
  a test sentinel — but the value appears in 3 places. If the CSRF mechanism ever validates token
  entropy or length, all three places must be updated.
  Fix: define `_CSRF_TOKEN = 'tok'` as a module-level constant and reference it from all three
  sites (the class method `_csrf` at line 46 already does this for the header, but the session
  setup at lines 43, 118, 133 repeat the literal).

### Naming / AAA structure

- **[LOW]** `test_graceful_shutdown.py:81–90` — `test_waits_for_running_thread_then_exits` has no
  wall-clock assertion (deliberately — the comment explains the rationale), but the test name says
  "then exits" which implies the return-from-function contract is verified. The only assertion is
  `not slow._thread.is_alive()` — which proves the thread ended but not that `request_shutdown`
  *returned* (it could theoretically block indefinitely if the join has no timeout). The name is
  slightly misleading.
  Fix: rename to `test_cancel_causes_thread_to_exit` to match what is actually asserted.

### Verbosity

- **[LOW]** `test_formatters.py:68–84` — `test_no_duplicate_keys` walks the AST of
  `services/formatters.py` to check for duplicate dict keys. This is a valid technique (used
  elsewhere in the suite), but it reimplements the same pattern as `TestPlatformNameMap.test_no_duplicate_keys_in_map`
  in `test_game_utils.py:74–90` (which uses `inspect.getsource` + regex). Two different approaches
  to the same class of check in the same test suite is a maintenance burden.
  Fix: standardise on one pattern (AST is more robust; the game_utils regex will false-trigger on
  multi-line strings). Consider extracting a shared `assert_no_duplicate_dict_keys(source, dict_name)`
  helper to `tests/_util.py`.

### Doc strings

- **[INFO]** `test_emulator_autodetect.py` — The file has no module-level docstring and no test
  function docstrings except `test_detect_skips_unknown_emulator_names` (line 68–69). The test
  names are generally self-descriptive, so this is not a blocking issue, but
  `test_scan_paths_default_includes_mnt_emulators` (line 99) tests a spec invariant with a
  meaningful rationale (`/mnt/Emulators in default scan paths`) and would benefit from a one-line
  comment explaining what contract it protects (similar to the docstring pattern used in
  `test_hltb_endpoint.py`).
  Fix: add a one-line comment or docstring to invariant-pinning tests in this file.

---

## Cross-file patterns (within this chunk)

1. **Inline `_REPO_ROOT` / `sys.path.insert` boilerplate** — Present in `test_hltb_endpoint.py`
   (lines 29–31) and `test_emulator_seeder.py` (line 8, no sys.path but uses a private `_REPO_ROOT`
   instead of the shared `_util.REPO_ROOT`). The `tests/_util.py` module was created specifically to
   eliminate this pattern across the suite; these two files were not updated.

2. **Inline viewer/non-admin client construction** — `test_emulator_registry_routes.py` and
   `test_emulator_autodetect.py` (lines 92–96) both inline `import app as app_module` +
   `app.test_client()` + optional session setup inside individual test functions. The
   `admin_client` fixture in `test_emulator_registry_routes.py:34` shows the right pattern;
   it is not generalised.

3. **Source-grep assertion fragility** — Both `test_emulator_registry_routes.py:21` and
   `test_hltb_endpoint.py:87` use `in src` / `src.count(...)` checks that are not anchored to
   specific code paths. The `tests/_util.py:slice_function()` helper exists to address exactly
   this, and is used in other parts of the suite, but not yet here.

4. **AST-based duplicate-key checks** — `test_formatters.py:68–84` and `test_game_utils.py:74–90`
   both implement independent versions of a "check for duplicate dict keys by parsing source" test.
   These could share a utility in `tests/_util.py`.

---

## Summary

- CRITICAL: 0
- HIGH: 4
- MED: 10
- LOW: 7
- INFO: 1
