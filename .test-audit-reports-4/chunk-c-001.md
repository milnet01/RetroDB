# Chunk c-001 audit
Files: 12  ·  Findings: 18 raw

## Pre-pass triage

- **tests/test_auth_hashing.py:26** — FALSE POSITIVE. The `"legacy_password"` default arg in `_make_legacy_hash()` is a legitimate test helper constructing a legacy hash format. No real credential; the value has zero security sensitivity. The comment at line 23 (`TEST_ITERATIONS = 1`) even documents the performance trade-off. Not a hardcoded secret.

- **tests/test_bulk_scrape_race.py:4** — FALSE POSITIVE. Line 4 is inside the module docstring: `"The race: the old code set \`cancelled=True\`, then \`time.sleep(0.5)\`, then"`. This is descriptive text explaining the *bug that was fixed*, not an import or call. No `import time` appears anywhere in the file.

- **tests/test_bulk_scrape_race.py:137** — FALSE POSITIVE. Line 137 is a comment: `"# event instead of busy-polling with time.sleep()."` The actual code on line 138 is `if worker_can_exit.wait(timeout=0.05):` — a non-blocking `Event.wait()` with a 50 ms ceiling, which is the correct pattern replacing the old sleep. Not a sleep call.

---

## Findings by dimension

### Isolation

**[HIGH] tests/test_auth_hardening.py:24** — `_REPO_ROOT` recomputed from `os.path.dirname(__file__)` instead of using `REPO_ROOT` from `tests._util`.

The project extracted this exact boilerplate into `_util.py` during the 2026-05-17 audit cycle (documented in `_util.py` lines 3–6). `test_auth_hardening.py` was not updated. The two values are equivalent today, but if the test tree is ever reorganised they'll silently diverge.

Fix: replace lines 21–24 with `from tests._util import REPO_ROOT as _REPO_ROOT` (or import `pathlib.Path(REPO_ROOT)` as the player-role test does at line 7).

---

**[MED] tests/test_auth_hardening.py:370–381** — Class-scoped `client` fixture uses manual try/finally to restore `TESTING=True` because `monkeypatch` is unavailable in `scope="class"` fixtures; other methods in the same file (lines 52–55, 133–135) use `monkeypatch.setitem` in function-scoped tests accessing the same singleton app object.

Consequence: if the class-scoped fixture teardown is skipped (e.g. a keyboard interrupt or a fixture error during setup), `app.config['TESTING']` is left `False` for the rest of the test session, silently changing behaviour of any subsequent test that imports `app_module.app`. The try/finally on line 377 guards normal exits but not exceptions inside the `with` block that prevent `yield` from being reached.

Fix: convert `client` to a function-scoped fixture and use `monkeypatch.setitem` consistently, matching the surrounding test patterns.

---

**[MED] tests/test_auth_hardening.py:261–281** — `_isolated_db()` is a class helper method, not a pytest fixture. It receives `monkeypatch` from the calling test, which means each of the five calling tests (lines 284, 291, 299, 307, 316) must remember to pass both `tmp_path` and `monkeypatch`. If a future test author calls `self._isolated_db(tmp_path)` and omits `monkeypatch`, the `monkeypatch.setattr` for `database._db_pool` is silently skipped — the real pool is used and `config.DB_PATH` is set permanently for the rest of the session.

Fix: convert `_isolated_db` to a `@pytest.fixture(scope="function")` in the module (not on the class) so pytest injects dependencies and the monkeypatch restoration is guaranteed.

---

### Flakiness

**[HIGH] tests/test_bulk_scrape_race.py:125–177** — `test_demoted_job_state_only_resets_after_worker_exits` never sets `worker_can_exit`. After `demote_running()` promotes the second queued job and starts a new worker thread for it, that thread enters `slow_worker`'s loop, calling `worker_can_exit.wait(timeout=0.05)` forever. The thread is `daemon=True` (bulk_scrape.py:266) so it won't block process exit, but it spins for the rest of the pytest session, burning CPU and potentially interfering with subsequent threading-sensitive tests. The swap test (line 62) correctly sets `worker_can_exit.set()` at line 121; the demote test omits the equivalent cleanup.

Fix: add `worker_can_exit.set()` after the final assertions (before the `with patch.object` block exits) to let the promoted worker thread exit cleanly.

---

**[MED] tests/test_bulk_scrape_race.py:63–122** — Both race tests use `wait(timeout=5.0)` ceilings on thread synchronisation. On a heavily loaded CI runner, 5 seconds is defensible, but neither test is marked with a `slow` marker, so the suite has no way to skip or time-gate them. The project's `pyproject.toml` uses `--strict-markers` with no `slow` marker defined, so adding `@pytest.mark.slow` would fail without also registering the marker — but documenting the expected wall-clock cost in a comment would at least make it intentional.

Fix: register a `slow` marker in `pyproject.toml` and apply it to both race tests, or document the expected worst-case wall time in the fixture docstring so CI alert thresholds can be set accordingly.

---

### Duplication

**[MED] tests/test_bulk_scrape_job.py:61–68 vs tests/test_bulk_scrape_race.py:46–52** — The 7-line `patch.object` stanza for BulkScrapeJob persistence helpers is duplicated verbatim across both files (same 7 targets, same return values). `test_bulk_scrape_race.py` imports `_make_memory_db` from `test_bulk_scrape_job` (line 20) but not the patch stanza.

Consequence: a new persistence helper added to `bulk_scrape_mod` needs to be patched in both places; observed that `persist_job_queued` was already added and matched correctly, but future additions may not be.

Fix: extract the patch stanza (and the `_make_memory_db` helper it depends on) into a shared fixture in `conftest.py` or a new `tests/_bulk_scrape_fixtures.py` helper module, then import from there in both test files.

---

**[LOW] tests/test_auth_hardening.py:42, 64, 86, 166, 211, 241** — Six `open(mod.__file__).read()` calls without a context manager and without `encoding="utf-8"`. The `_util.py` module was created to provide `read_module_source(mod)` (line 32–39 of `_util.py`) which uses a context manager. `test_auth_player_role.py` already migrated to `path.read_text()`. These six sites pre-date the extraction and were not updated.

Consequence: file descriptor leak if the `read()` raises (unlikely on UTF-8 source files but possible in constrained environments); also silently breaks on systems where the default encoding is not UTF-8.

Fix: replace with `read_module_source(mod)` from `tests._util` (already imported via `conftest.py`) or `pathlib.Path(mod.__file__).read_text(encoding="utf-8")`.

---

### Determinism

**[LOW] tests/test_backup_rotation.py:20–22, 38–40, 54, 63** — `time.time()` is called live (unfrozen clock) to set relative mtime offsets. The offsets are large enough (1 second apart) that this won't flake, but the tests exercise sorting-by-mtime logic and any future test that compares absolute timestamps would need a frozen clock. The pattern is inconsistent with `test_assets.py` which artificially bumps mtime by `+2` (line 74–75) specifically to avoid filesystem timestamp granularity issues.

Fix: capture `now = time.time()` once per test and use it consistently (already done in `test_keeps_newest_n_files` and `test_pre_restore_backups_are_never_pruned`). The `test_keep_zero_is_noop` and `test_fewer_than_keep_is_noop` tests (lines 52–57, 61–66) call `time.time()` inside the loop, meaning each file gets a slightly different base. This is harmless but imprecise — capture `now` before the loop.

---

### Assertions

**[MED] tests/test_alternate_titles.py:84–93** — `test_preserves_region_and_source` asserts `merged[1]["region"] == "US"` but does not assert `merged[1]["source"] == "screenscraper"`. The test is named "preserves region and source" so the missing source assertion on the second entry is an incomplete check. A bug that drops `source` from the second entry only would pass.

Fix: add `assert merged[1]["source"] == "screenscraper"` after line 92.

---

**[LOW] tests/test_auth_hardening.py:392–394** — `test_destructive_endpoint_rejects_unauthenticated` asserts `resp.status_code in (301, 302, 303, 401, 403)` and then separately asserts `'/login' in location or '/setup' in location or resp.status_code in (401, 403)`. The second condition is a superset-of-first superset: any status code in the first set combined with any location satisfies the second. A 301 redirect to `/dashboard` (wrong redirect target) would pass the first assertion (301 is in the set) and the second (status 301 is not in 401/403, so location check runs — but `/dashboard` contains neither `/login` nor `/setup` so it would *fail*). Actually the assertion is fine for the rejection case, but the code comment says "exact status varies with rate-limit state and CSRF middleware" — the test window is wide enough that a misconfigured middleware returning 200 with a JSON error would fail. This is acceptable but the double-condition logic is harder to read than a single `assert` with a descriptive message.

Fix: split into two explicit assertions with failure messages, or collapse to one clear predicate: `assert resp.status_code in (301, 302, 303, 401, 403) and ('/login' in location or '/setup' in location or resp.status_code in (401, 403))`.

---

### Fixtures

**[MED] tests/test_assets.py:13–37** — `app_with_manifest` fixture uses a manual try/finally (lines 33–37) to restore `assets._MANIFEST_CACHE` because, as the comment on line 27 notes, `monkeypatch` can't wrap direct dict assignment. This is a legitimate pattern but the fixture resets both the `mtime` and `data` keys by name. If `_MANIFEST_CACHE` gains a third key in the future (e.g. `etag`), the snapshot/restore logic silently omits it.

Fix: snapshot the entire dict: `_orig_cache = dict(assets._MANIFEST_CACHE)` and restore with `assets._MANIFEST_CACHE.clear(); assets._MANIFEST_CACHE.update(_orig_cache)`.

---

**[LOW] tests/test_backup_rotation.py** (all 5 tests) — Tests use `tempfile.TemporaryDirectory` as context manager inside each test method rather than accepting the `tmp_path` pytest fixture. The `tmp_path` fixture is already used in `test_atomic_io.py` and `test_assets.py` in this same chunk. `tempfile.TemporaryDirectory` is not wrong but it's inconsistent with the rest of the suite and adds 2 lines per test that pytest provides for free.

Fix: convert the class to plain functions accepting `tmp_path`, or keep class shape and accept `tmp_path` as a method parameter.

---

### Hardcoded data

**[LOW] tests/test_assets.py:24, 45, 62, 85** — `APP_VERSION = '2.84.2'` is used as a test sentinel in four assertion sites. This is set via `mock_cfg.APP_VERSION = '2.84.2'` (line 24) so it is deliberately test-local, not stale from production. However the string `'2.84.2'` appears in 4 assertion statements that check for it literally. If the test is refactored and the mock version changes in one place, the 3 assertion sites need updating.

Fix: extract to a module-level constant: `_TEST_VERSION = '2.84.2'` and reference `_TEST_VERSION` in assertions.

---

### Coverage gaps

**[MED] tests/test_atomic_io.py** — No test for concurrent writes to the same path. `atomic_write_json` exists specifically to prevent corruption from concurrent access, but the test suite only verifies single-writer semantics. The `test_temp_file_cleaned_up_on_failure` and `test_original_file_intact_on_failure` tests cover single-writer failure atomicity. A two-thread concurrent write test would verify the rename-over semantics that make the function actually atomic.

Fix: add a test that spawns two threads each writing different data to the same path and asserts the final file is valid JSON (either value, not a torn write).

---

**[LOW] tests/test_alternate_titles.py** — No test for `merge_alt_titles` when `existing` is a valid JSON string containing malformed entries (e.g. `'[{"region": "JP"}]'` — string form of the list-with-no-title case). The `test_drops_existing_entries_without_title` test (line 75) covers the list form; `test_accepts_json_string` (line 36) only covers well-formed JSON. The combination (JSON string that decodes to a list with malformed entries) is an untested path.

Fix: add one parametrized case: `merge_alt_titles(json.dumps([{"region": "JP"}, {"title": "Rockman"}]), [])` should return `[{"title": "Rockman"}]`.

---

### Splitting

**[LOW] tests/test_auth_hardening.py** — The file covers 7 distinct pass numbers (24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 22.7, 27.2, 24.8) across 8 top-level test classes. At 411 lines it is the longest file in this chunk. The `TestPerUserPlatformTokens` class (lines 255–321) tests a completely different service (`services/platform_tokens.py`) from the auth hardening tests above it. It was added here because Pass 27.2 superseded the file-permissions tests from 24.7.

Consequence: hard to navigate; `TestPerUserPlatformTokens` has no natural relationship to session rotation or password policy.

Fix: move `TestPerUserPlatformTokens` to a dedicated `tests/test_platform_tokens.py`. The `_isolated_db` helper should become a fixture in that file.

---

### Naming

**[LOW] tests/test_bulk_scrape_race.py:94–95, 147–148** — The inner functions `do_swap` and `do_demote` are defined inside the test body and capture the `job` variable via closure. They're only a few lines each. The naming is fine, but they are defined without type annotations while the surrounding code is otherwise well-typed. Not a bug, but annotating `job` in the closure would catch if `JobCls()` is accidentally redefined.

This is marginal — not surfacing as a real finding; noted for completeness. No action recommended.

---

## Cross-file patterns (within this chunk)

1. **Bare `open(...).read()` without context manager and without `encoding=`**: appears in `test_auth_hardening.py` (6 sites). The `_util.py` helper `read_module_source()` and `read_source()` were created specifically to fix this pattern (documented in `_util.py` lines 3–6). `test_auth_hardening.py` was not migrated. Probably the one file in the chunk that predates the extraction without being updated.

2. **`_REPO_ROOT` duplication**: `test_auth_hardening.py` computes `_REPO_ROOT` inline (line 24); `test_auth_player_role.py` correctly imports `REPO_ROOT` from `tests._util` and wraps it in `pathlib.Path` (lines 4–7). The two approaches give identical values today but diverge in style. This is the only remaining `os.path.dirname(os.path.dirname...)` inline computation in this chunk.

3. **`tempfile.TemporaryDirectory` vs `tmp_path`**: `test_backup_rotation.py` uses `tempfile.TemporaryDirectory` in every test; `test_atomic_io.py` and `test_assets.py` use `tmp_path`. No correctness impact, but the split means two different cleanup paths for temporary files across the suite.

4. **Thread-based tests without `slow` marker**: both tests in `test_bulk_scrape_race.py` have 5-second `wait()` ceilings. No `slow` marker is defined in `pyproject.toml` and `--strict-markers` is set. If future CI triage wants to skip or time-gate heavy tests, there is currently no hook for it.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH     | 2 |
| MED      | 7 |
| LOW      | 8 |
| INFO     | 1 |
| **Total**| **18** |

**Most actionable fixes in priority order:**

1. `test_bulk_scrape_race.py` — add `worker_can_exit.set()` to the demote test teardown (daemon thread spinning for session duration). HIGH.
2. `test_auth_hardening.py` — migrate 6 bare `open(...).read()` calls to `read_module_source()` (fd leak + encoding). LOW-MED cumulative.
3. `test_auth_hardening.py` line 24 — replace inline `_REPO_ROOT` computation with import from `tests._util`. LOW.
4. `test_assets.py` fixture — snapshot full `_MANIFEST_CACHE` dict, not just two keys. MED.
5. `test_atomic_io.py` — add concurrent-write test (the main invariant of atomic_write_json). MED coverage gap.
