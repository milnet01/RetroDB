# Chunk c-003 audit
Files: 12  ·  Findings: 24 raw

## Pre-pass triage
- tests/test_launcher_local.py:27 — ❌ FALSE-POSITIVE. The `time.sleep(0.05)` lives inside `_poll_exited()`, a bounded poll helper with a hard 2-second deadline. If the deadline is breached, `pytest.fail()` fires with the last-observed status (line 28). This is intentionally a short-interval poll, not a bare sleep — the original anti-pattern (observed in prior audits) was a naked `sleep(N)` with no timeout guard. This implementation is correct.

---

## Findings by dimension

### Performance

- [INFO] tests/test_launcher_local.py:32–115 — Tests that spawn real subprocesses (`sleep 60`, `/bin/true`, `/bin/false`) each boot a new `LocalLauncher()` with no cross-test reuse. Each launch test is effectively independent (different `token` strings), which is correct for isolation, so this is not a fixture-scope problem. However, the 2s `deadline_s` in `_poll_exited` means a slow CI runner could add up to ~10s aggregate if every poll loop goes to the wire. No action needed unless timing data shows outliers.  Fix: n/a (informational).

### Flakiness

- [HIGH] tests/test_launcher_registry.py:58–89 — `test_gc_removes_exited_after_ttl` and `test_gc_keeps_recent_exited` both anchor timing deltas to `time.time()` at test-run time without freezing the clock. The comment acknowledges prior jitter (line 83) and uses a single baseline `t`, which mitigates the twin-call race. However, the TTL math (`t - 2.0` for a 1.0 TTL) still relies on the real wall clock being within a 1s tolerance. On a CI runner under heavy load, `time.time()` resolution coarseness can corrupt this delta. The tests do not freeze time (no `freezegun`). If the CI clock jitters backward by even a few milliseconds between `t = time.time()` and internal `_mark_exited` storage, the 2s-ago anchor becomes unreliable.  Fix: Use `freezegun.freeze_time` or inject a monotonic fake clock; or refactor `ProcessRegistry` to accept a `clock_fn` parameter and substitute a constant in tests.

- [MED] tests/test_launcher_local.py:14–28 — `_poll_exited` uses `time.sleep(0.05)` in a real-time loop that depends on the child process actually exiting within 2 seconds. For `/bin/true` and `/bin/false` this is fine on any real system, but on a severely loaded CI runner the OS scheduler might not reap the child within 2s. Consequence: test_launch_quick_exit_reaps_cleanly and test_launch_failed_exit_code_propagates would fail with `pytest.fail("timed out waiting for state...")` rather than flaking silently. This is an acceptable tradeoff (hard fail > silent flake), but the 2s limit is tight.  Fix: Increase `deadline_s` default to 5.0; or use `subprocess.wait(timeout=5)` to block rather than polling.

### Isolation

- [MED] tests/test_input_hardening.py:66–79 — `TestReportsSystemWhitelist.test_unknown_system_returns_400` imports `app` at the module level (via `import app as app_module`), mutates `app.config['TESTING']` via `monkeypatch.setitem`, and creates a `test_client()`. This boots the full Flask app including its DB connection, rate-limiter setup, and all blueprint registrations. If another test in the same session has already configured `app` differently (e.g. a different DB path), this test gets that state. `monkeypatch.setitem` correctly restores `TESTING` but any side-effects of the full-app boot (DB singleton, limiter state) persist.  Fix: Use `make_app_with_temp_paths()` from `tests/_util.py` (or the equivalent factory) to get a fresh isolated app instance instead of the shared module-global `app`.

- [LOW] tests/test_input_hardening.py:38 — `import os as _os` inside a test method body is unusual (the alias is used to avoid shadowing the outer `os` name, but `os` is not imported at the top of the file). This means the test re-imports on every call instead of once at module load. No functional harm, but it's an odd idiom that creates unnecessary confusion.  Fix: Import `os` at the top of the file; use it directly. The alias is unnecessary since `os` is not imported elsewhere in the file.

### Determinism

- [MED] tests/test_launcher_registry.py:58–89 — (see also Flakiness above) Neither GC test freezes the clock; both anchor to live `time.time()`. Under clock skew or NTP stepping during a CI run, the test result is non-deterministic.  Fix: inject a clock or use `freezegun`.

- [LOW] tests/test_launch_resolver.py:137–141 — `test_token_is_random_per_call` asserts `a.token != b.token`. This is the correct test for token uniqueness, but if the token generation has very low entropy (e.g. uses a time-based source that collides on a fast machine), the test would give a false-positive pass on one run and a false-positive fail on another. This is an inherent property of testing randomness without seeding.  Fix: Either seed the RNG in the test and assert the result matches, or — better — assert `len(a.token) >= 16` as a proxy for sufficient entropy alongside the inequality check.

### Accuracy

- [HIGH] tests/test_launcher_local.py:81–86 — `test_status_unknown_token_raises` asserts `pytest.raises(LauncherError)` with no `match=` argument. If the implementation raises a `LauncherError` but with an empty message, or with a completely different error message (e.g. after a refactor), this test still passes. The raises-without-match pattern means a broken implementation that raises `LauncherError("internal error")` where it should raise `LauncherError("unknown token: ...")` would silently pass.  Fix: Add `match=r"does-not-exist"` or `match=r"[Uu]nknown token"` to pin the error wording.

- [MED] tests/test_input_hardening.py:125–129 — `test_ipv6_loopback_rejected` asserts `assert err` (truthy check only — line 129). This is weaker than the sibling tests which assert `err.startswith('disallowed IP range:')`. An implementation that returns any non-empty string as the rejection reason would pass this test even if it's silently swallowing a different error (e.g. DNS resolution failure returning an error string that has nothing to do with SSRF rejection).  Fix: Assert `err.startswith('disallowed IP range:')` matching the canonical prefix used for all other loopback/private tests at lines 97, 104, 112.

- [MED] tests/test_input_hardening.py:136–138 — `test_ipv6_link_local_rejected` has the same bare `assert err` pattern (line 138) as the IPv6 loopback test. Same consequence and same fix.  Fix: Assert the canonical prefix `'disallowed IP range:'` (consistent with RFC1918/127.0.0.1 tests).

- [MED] tests/test_input_hardening.py:79 — `test_unknown_system_returns_400` accepts `(400, 302, 403)` as valid responses. The comment says "302 (not authed on fresh CI DB)" which means the test passes vacuously in CI if auth is not set up. A test that accepts a redirect (302) as proof of security enforcement is not actually testing the security guard — it's testing "the endpoint exists". If the production guard were removed, a 302 redirect would still make this test pass.  Fix: Set up a minimal auth session properly (or use TESTING mode which bypasses auth), so only 400 is accepted. The `monkeypatch.setitem(app.config, 'TESTING', True)` on line 70 and the session injection on lines 72–73 suggest auth bypass is already attempted — if it's still returning 302, the auth bypass isn't working and the test is measuring nothing.

- [LOW] tests/test_input_hardening.py:156–161 — `test_oversize_upload_rejected_via_max_content_length` asserts `hasattr(config, 'MUSEUM_UPLOAD_MAX_BYTES')` and `hasattr(config, 'MAX_UPLOAD_BYTES')` plus a size inequality. This is a configuration-existence check, not a functional test. If `MUSEUM_UPLOAD_MAX_BYTES` were set to 0, it would satisfy `<= MAX_UPLOAD_BYTES` but would disable the museum cap entirely. The test doesn't verify that the cap is actually enforced at the HTTP boundary.  Fix: Either document explicitly that this is an intentional config-contract pin (not a functional test), or add a companion integration test that actually POST-s an oversized body.

### Security

- [LOW] tests/test_input_hardening.py:172–180 — `test_try_finally_cleanup` in `TestCLZPDFBounds` uses source-grep (`assert 'finally:' in src`, `assert 'os.unlink(tmp_path)' in src`) to verify structural cleanup. This passes as long as the string `'finally:'` exists anywhere in the file — even in a comment or a different function. The CLZ import module has multiple `finally:` blocks (confirmed: lines 412 and 646 in `routes/clz_import.py`). This test would still pass if the PDF-specific `finally` were removed as long as any other `finally` remains.  Fix: Use `tests/_util.slice_function()` (already available via conftest) to extract the relevant function body, then assert within that slice.

### Coverage Gaps

- [MED] tests/test_launch_resolver.py:20–21 — The `tmpdb` fixture creates a `bonus_discs` table and seeds it empty, but no test exercises the resolver with a bonus-disc game. If the resolver has a code path that loads bonus disc paths into `LaunchContext.argv`, that path is entirely untested.  Fix: Add a test that inserts a bonus disc row and asserts its path appears in the resolved `ctx.argv`.

- [MED] tests/test_launch_resolver.py:20 — The `games` table has a `launch_args_override` column (schema line 20), but no test exercises a game with `launch_args_override` set. If the resolver has a branch that substitutes per-game arg overrides, it is unexercised.  Fix: Add `test_per_game_launch_args_override_applied` that sets `launch_args_override` on a game row and asserts the override appears in `ctx.argv`.

- [MED] tests/test_metadata_merger.py:360–418 — `TestApplyAi` never calls `apply_ai_to_metadata` with `fill_only=False` explicitly. All tests either omit `fill_only` (using default) or pass `fill_only=True`. The overwrite path is untested.  Fix: Add `test_fill_only_false_overwrites_existing_fields` that sets a non-empty field, calls with `fill_only=False`, and asserts it was replaced.

- [LOW] tests/test_image_pipeline.py:156–207 — `TestBoxartSrcset` and `TestFinalizePipeline` test `boxart_srcset` with WebP variants only. There is no test for srcset behaviour when `IMAGE_FORMAT='jpeg'` — specifically whether jpeg variants (`-sm.jpg`, `-md.jpg`) are emitted or if the function falls back gracefully. If the implementation has format-specific branch logic, the JPEG path is uncovered.  Fix: Add a test variant that writes JPEG siblings and asserts the srcset is correct.

### Splitting

- [MED] tests/test_metadata_merger.py:54–76 — `test_fills_empty_text_fields` in `TestApplyTgdb` asserts 8 distinct fields in one test body (title, publisher, developer, release_date, description, players, esrb_rating, modes, filled_fields). If publisher mapping breaks, the test fails and all downstream assertions are hidden. The test intentionally covers the "full happy path" which is valid, but the multi-assertion failure masking is real.  Fix: The `apply_igdb_to_metadata` counterpart at line 114 has the same pattern. Both are borderline; acceptable for "fills all basic fields" happy-path tests if the project prefers this style. Low priority — flag rather than mandate.

### Duplication

- [MED] tests/test_metadata_merger.py:54 and 114 — `test_fills_empty_text_fields` is the same method name in both `TestApplyTgdb` (line 54) and `TestApplyIgdb` (line 114). These are distinct pytest nodes (disambiguated by class), so no collision occurs. However, renaming one of them to reflect what makes the IGDB path distinct (e.g. `test_fills_empty_text_fields_with_game_modes_and_companies`) would make test output less ambiguous when one fails in a filtered run.  Fix: Rename `TestApplyIgdb::test_fills_empty_text_fields` to `test_fills_empty_text_fields_including_company_mapping` or similar.

- [LOW] tests/test_metadata_merger.py:78–95 — `TestApplyTgdb` has two `fill_only=True` tests for the same invariant from slightly different angles: `test_fill_only_true_preserves_existing_non_title_fields` (non-title field preserved) and `test_fill_only_true_keeps_existing_title` (title preserved). The distinction is real but the tests are structurally identical. A single parametrized test `@pytest.mark.parametrize('field', ['publisher', 'title'])` would cover both with one test body.  Fix: Merge into one parametrized test (low priority — current form is readable).

### Parametrisation

- [MED] tests/test_log_redactor.py:8–37 — `TestRedactPatterns` has 5 distinct tests that each assert `<secret> not in redact(input)` for a different secret type (JWT, access_token, Authorization header, apikey, hex). The structure is `input, redact_call, negative-assert, positive-assert` verbatim in each. These could be a parametrized table: `@pytest.mark.parametrize('input,secret,tag', [...])` which would reduce 5×4 lines to a 5-row table plus one 4-line test body.  Fix: Parametrize `TestRedactPatterns` tests that share the not-in/in assertion pair structure. Note: `test_jwt_is_redacted` has a dual assertion (both `not in` and `in` on the same call) which makes it slightly richer than the others — keep it separate or adjust the parametrize shape.

- [LOW] tests/test_launcher_local.py:32–115 — All 6 test functions import `LocalLauncher` and `LaunchContext` inside the function body (deferred imports). This is a deliberate pattern to avoid importing at collection time (protects against import errors on constrained environments), which is valid. However, the imports are repeated 6 times identically. Moving them to module scope or a local `@pytest.fixture` would eliminate the repetition without breaking the skipif-guarded conditional execution.  Fix: Module-level imports guarded by a `try/except ImportError: pytest.skip(...)`, or a session-scoped fixture.

### Naming / AAA Structure

- [LOW] tests/test_metadata_merger.py:115 — Comment on line 115 reads `# Renamed from test_fills_basic_text_fields → test_fills_empty_text_fields`. This is a stale comment explaining a past rename. It adds noise now that the rename has landed.  Fix: Delete line 115–117 comment block (the rename is historical, not contractual).

### Verbosity

- [LOW] tests/test_input_hardening.py:85–138 — `TestMuseumSSRFGuard` repeats the same 3-assertion pattern (`assert safe_url is None`, `assert pinned_ip is None`, `assert err...`) in 6 tests. The per-test setup is trivially different (URL input). These 6 tests are a strong parametrize candidate that would shrink the class from ~55 lines to a 6-row table + one 4-line test.  Fix: `@pytest.mark.parametrize('url,expected_err_prefix', [...])` across the 6 tests. Retain `test_ipv6_loopback_rejected` and `test_ipv6_link_local_rejected` as separate named cases if the comment/docstring justification is important; otherwise include them in the table.

### Doc Strings

- [LOW] tests/test_launcher_local.py — No module-level docstring (compare: `test_launcher_base.py` has none either, but `test_job_history_sweep.py` and `test_metadata_merger.py` do). Module docstring is missing for `test_launcher_local.py`, `test_launcher_factory.py`, `test_launcher_registry.py`, and `test_launch_settings_validators.py`. A single-sentence description of what subsystem each file pins would pay off at the "why is this test failing?" phase.  Fix: Add one-line docstrings to the four files. Low priority.

---

## Cross-file patterns (within this chunk)

1. **Deferred imports** (`from services.launcher... import ...` inside every test function body) appear in `test_launcher_factory.py`, `test_launcher_local.py`, `test_launch_resolver.py`, and `test_launcher_base.py`. This is intentional isolation from import-time failures, but the repetition across 4 files is a maintainability cost. A conftest fixture or module-level `try/except ImportError: pytest.skip()` guard would centralise the decision.

2. **`blank` fixture pattern** in `test_metadata_merger.py` (line 41) is exactly the right extraction — it replaced 30+ inline `_blank_metadata()` calls (noted in the fixture docstring). The pattern is well-executed.

3. **Configuration-existence assertions** (`assert hasattr(config, 'X')` + `assert config.X >= N`) appear in `test_input_hardening.py` across 5 separate test classes (TestMuseumUploadCap, TestCLZPDFBounds, TestVideoUploadCap, TestScraperDownloadCaps, TestListRowCaps). This pattern tests that constants exist and are reasonable, but does not test that the enforcement code actually uses them. These are config-contract pins, which is a legitimate but weak form of coverage.

4. **`_pick_best_fallback` / `_pick_best_secondary` in `test_hybrid_scraper.py`** — no parametrize is used across 8 tests that each pass a different candidates list and query string. The tests are concise enough (3–5 lines each) that parametrizing would not meaningfully shorten them; current form is acceptable.

---

## Summary
- CRITICAL: 0
- HIGH: 2
- MED: 12
- LOW: 9
- INFO: 1
