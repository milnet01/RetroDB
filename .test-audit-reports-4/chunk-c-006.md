# Chunk c-006 audit
Files: 6  ·  Findings: 18 raw

Files read:
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_routes_smoke.py
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_scan_library_rom_path.py
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_scrape_fill_only.py
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_security_headers.py
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_slow_query_log.py
- /mnt/Games/Scripts/Linux/RetroDB/tests/test_terminal_status.py

---

## Findings by dimension

### Performance

- [LOW] test_security_headers.py:25–136 — `/health` is fetched once per individual test method inside a module-scoped `client` fixture, but several single-assertion tests (e.g. `test_content_type_options`, `test_frame_options`, `test_referrer_policy`, `test_xxss_protection_absent`, `test_permissions_policy_present`, `test_csp_report_only_present`, `test_csp_enforcing_not_sent`, `test_csp_blocks_objects`) each make a redundant HTTP round-trip to the same `/health` route that always returns identical headers. The parametrized directives tests (lines 53–64, 121–130) are correctly using one request per parametrize call but the single-assertion class tests multiply the request count needlessly. Fix: coalesce the same-class single-HTTP-call tests that inspect different header fields from the same response into one test with multiple asserts, or cache the response in a session-scoped fixture. Low severity because this is a local test client (no real network) and the suite is ~3.4 s total.

- [LOW] test_security_headers.py:53–64, 121–130 — `client.get('/health')` is called once per parametrize parameter (7 calls for `test_permissions_policy_disables_sensors`, 9 calls for `test_csp_includes_core_directives`). The response is identical across all parameters. Fix: fetch once in the parametrized setup and pass the pre-fetched headers in, or use `@pytest.fixture(scope="class")` cached response. Net saving: 16 redundant app round-trips per suite run.

---

### Flakiness

- [MED] test_security_headers.py:176–182 — `test_response_header_nonce_matches_template_nonce` mutates the live app-global `app.before_request_funcs[None]` list by appending a lambda and then `pop()`-ing it in a `finally`. If any other test running concurrently (or a future test added before this position in the list) also mutates `before_request_funcs[None]`, the `.pop()` removes the wrong entry — the last one appended, not the one this test added. Under `pytest-xdist` or if a nested/parallel call inserts a hook between append and pop, the teardown silently removes a different hook (or none at all, leaving a dangling capture hook that corrupts subsequent test requests). Fix: store the index or reference at append time and remove by value (`list.remove(fn)`) instead of positional pop, or use `monkeypatch.setitem` to replace the whole list for the duration of the test.

- [LOW] test_slow_query_log.py:34–36 — `test_fast_query_below_threshold_does_not_log` calls `_log_if_slow("SELECT 1", (), time.perf_counter())` where `start = time.perf_counter()` is captured *inside* the `patch.object` context manager and the elapsed time is approximately zero. On an extremely loaded CI runner, the line between `time.perf_counter()` (line 35) and `_log_if_slow`'s internal `time.perf_counter()` call could exceed the 100 ms threshold if the scheduler pre-empts in that window. Extremely unlikely but non-zero. Fix: use a fixed future start time like `time.perf_counter() + 100` to make it structurally impossible to trip. Not flagging as HIGH because the 100 ms window is generous and the suite is fast.

---

### Duplication

- [MED] test_routes_smoke.py:8–22 and test_security_headers.py:8–19 — Identical `client` module-scoped fixture (snapshot `TESTING`, yield test client, restore) is inlined verbatim in both files. The same pattern likely exists in other chunks too (noted as cross-chunk hypothesis). Fix: promote to `conftest.py` as `@pytest.fixture(scope="module") def app_client()`. Both files could then drop their local fixture definition.

- [MED] test_scan_library_rom_path.py:35–37 — Re-implements `_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` + `sys.path.insert(0, _REPO_ROOT)` (lines 35–37), which is identical to what `tests/_util.py:REPO_ROOT` (introduced in the 2026-05-17 audit) already provides via `conftest.py`. The shared helper exists precisely to eliminate this pattern. Fix: remove lines 29–37 from this file and import `from tests._util import REPO_ROOT as _REPO_ROOT` (or simply rely on `conftest.py` which re-exports `REPO_ROOT`).

- [LOW] test_scan_library_rom_path.py:155–175 — `TestScanRomsImportTimeBinding` opens source files with an inline `with open(path, encoding='utf-8') as f: src = f.read()` pattern (lines 157–158 and 170–171) rather than calling `read_source(rel_path)` from `tests/_util.py`, which was extracted for exactly this purpose. Fix: replace both open calls with `from tests._util import read_source` and `src = read_source('scraper/scan_roms.py')`.

---

### Isolation

- [HIGH] test_security_headers.py:77–87 — `test_hsts_present_when_secure_cookies_enabled` mutates `app_module.app.config['SESSION_COOKIE_SECURE']` via a manual `try/finally` instead of `monkeypatch`. This test takes the `client` fixture (which is module-scoped), and `monkeypatch` *is* available in function-scoped tests even when the fixture they depend on is module-scoped. The comment at line 11–14 explains why the fixture itself can't use `monkeypatch`, but that constraint does not apply to the test method. If the test throws before reaching the `try` block (e.g. an import error or setup failure), the `original = ...` assignment on line 79 will not have fired and the config will be left as `True` for the remaining tests in the module. Currently the `original = ...` is before `try`, so the assignment itself is safe — but the manual pattern is fragile and inconsistent with `test_hsts_absent_on_plain_http` which correctly uses `monkeypatch`. Fix: replace lines 79–87 with `monkeypatch.setitem(app_module.app.config, 'SESSION_COOKIE_SECURE', True)` (same as the sibling test at line 73).

- [MED] test_terminal_status.py:23–33 — `test_shutdown_takes_precedence_over_user_cancel` calls `shutdown_requested.set()` and relies on the `finally: shutdown_requested.clear()` for cleanup. If the process-global `shutdown_requested` event is left set by a prior test failure that did not clear it (or by a test running in a different order), this test would pass trivially rather than testing the intended behaviour. The `test_clean_completion_returns_completed` (line 11–14) and `test_user_cancel_returns_cancelled` (line 17–20) both call `shutdown_requested.clear()` as their first line — this implies awareness of the leakage risk, but doesn't protect against a prior test that set the event and failed mid-execution. Fix: add `shutdown_requested.clear()` as the first line of every test that depends on the cleared state, or use a function-scoped autouse fixture that resets `shutdown_requested` before each test.

- [MED] test_security_headers.py:161–192 — `test_response_header_nonce_matches_template_nonce` appends to `app_module.app.before_request_funcs[None]` which is a global list shared across the module-scoped `client` fixture. Even with the `finally` pop, this test is not isolated: if the module-scoped `client` fixture is shared with other tests running after this one and a previous run leaked a hook (due to an exception in a broader teardown), subsequent tests would capture `g.csp_nonce` unexpectedly. Fix: use monkeypatch or replace the list wholesale for the duration of this test rather than mutating the shared list.

---

### Determinism

No determinism findings. All tests use `monkeypatch` for external dependencies, no unfrozen clocks or random seeds in assertions. The `test_csp_nonce_changes_per_request` test (test_security_headers.py:108–119) correctly asserts nonce inequality, not a specific value, so it is not sensitive to hash randomisation.

---

### Accuracy

- [MED] test_routes_smoke.py:117–121 — `test_hltb_search_requires_auth` accepts `status_code in (301, 302, 303, 401, 403)` — a range of five status codes. 301/302/303 are redirect-to-login, 401/403 are explicit rejection. This is correct as a "not-200" guard, but a 302 redirect to `/login` and a 403 JSON error are semantically different auth outcomes and one could regress into the other undetected. The test comment says "should reject" but a 302 is not a rejection — it's a redirect. Fix: split into two parametrize groups or narrow the acceptable set to what the endpoint actually returns (check source) and document why the other codes are tolerated.

- [LOW] test_slow_query_log.py:46 — `assert len(capture_db_log.records) == 1` is exact. If `_log_if_slow` were ever called more than once in the same `with patch.object` block (e.g. if a future refactor adds a secondary log call), this assertion would catch it — that is intentional and good. No action needed; noted here for completeness as a non-issue.

- [LOW] test_slow_query_log.py:82–87 — `test_non_sequence_args_still_logs` passes `None` (not a non-iterable non-None value) to exercise the `None` branch. The `TypeError` branch in `_log_if_slow` (database.py:42–43) that sets `arg_count = -1` is exercised only when `len(args)` raises — e.g. passing an integer. That branch is not covered by any test. Fix: add a second parametrize case with `args=42` (an integer) and assert `'args=-1'` in the message.

---

### Security

- [LOW] test_scan_library_rom_path.py:280 — `fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}` is an auth-bypass fixture that injects a hardcoded admin identity. It is used only inside `_client()` which is a method of `TestApiScanRomPathNotConfigured` — never exported or called outside this test class, and `monkeypatch` is used so the bypass resets automatically. No real credential value. Per dimension 18 guidance: this pattern is intentional and properly scoped; the inline dict is obviously fake. No action needed. (Included as a confirmation that this was reviewed and is not a finding.)

- [INFO] test_security_headers.py:103–119 — `test_csp_has_nonce` and `test_csp_nonce_changes_per_request` correctly pin the CSP nonce contract. The CSP header tested is `Content-Security-Policy-Report-Only`, not the enforcing header. `test_csp_enforcing_not_sent` (line 97–101) pins that the enforcing header is absent. These three together form an adequate security smoke test for the current report-only posture. No finding.

---

### Verbosity

- [MED] test_terminal_status.py:36–41 — `test_event_clear_restores_normal_mapping` makes two assert calls that duplicate the same assertions already covered by `test_clean_completion_returns_completed` (line 11–14) and `test_user_cancel_returns_cancelled` (line 17–20). The only new behaviour being tested is "after set+clear, the mapping is back to normal" — but the body checks both `cancelled=False` and `cancelled=True`, which is equivalent to re-running both existing tests with a set-then-cleared prefix. Consider collapsing to a single assert for the most meaningful case (`cancelled=False` → `'completed'`) since the set+clear sequence is the contract being pinned, not the individual mapping values.

- [LOW] test_scan_library_rom_path.py:71–115 — `_FakeCursor`, `_FakeConn`, `_stub_db`, and `_stub_db_context` are 45 lines of fake-DB infrastructure defined at module scope in the source-grep test file. These are well-documented and self-contained. However, since these fakes are specific to the scan path they are unlikely to be reused across files. No action required; included as a note that if similar fakes appear in other chunk files, extraction to `tests/_util.py` would be warranted.

---

### Naming

- [LOW] test_scan_library_rom_path.py:276 — `_client` is a private method on a test class (line 276 `def _client(self, monkeypatch)`), which is an unusual pattern: pytest class test methods are conventionally `test_*` or fixtures. The `_client` method builds and returns a `Flask` test client — this is fixture logic embedded in a helper method. The method name does not describe the setup it performs (`_client_with_empty_rom_path` would be clearer). Fix: rename to `_make_client_with_empty_rom_path` or extract as a proper `@pytest.fixture` (though the `monkeypatch` argument complicates this since it can't be passed as an argument in a standard fixture). Low priority.

---

### Coverage Gaps

- [MED] test_slow_query_log.py — The `TypeError` path in `_log_if_slow` (services/database.py:42–43, reached when `len(args)` raises) is exercised by passing an integer args value, which yields `arg_count = -1`. No existing test covers this branch. `test_non_sequence_args_still_logs` only passes `None` (hits `args is not None` check → arg_count = 0 via the `None is not None` branch); it does not trigger `TypeError`. Fix: add `test_non_iterable_args_logs_minus_one` passing `args=42` and asserting `'args=-1'` in the message.

- [LOW] test_routes_smoke.py:83–102 — `TestAuthGuards` covers `GET` redirects for 5 endpoints but covers no `POST`/`DELETE`/`PATCH` endpoints (e.g. `api_delete_game`, `api_rename_rom`, `api_hltb_bulk_start`) that are also declared in `EXPECTED_ENDPOINTS`. An unauthenticated POST to a write endpoint could be more dangerous than an unauthenticated GET. `TestHLTBSearchAuth` adds one POST case for `/api/hltb/search`; extending the same pattern to 3–4 more write endpoints would be low effort. Fix: parametrize a `test_protected_post_redirects_unauthenticated` test with a sample of mutating endpoints.

- [LOW] test_scrape_fill_only.py — Both `test_igdb_apply_preserves_existing_values_when_response_is_empty` and `test_tgdb_apply_preserves_existing_values_when_response_is_empty` seed all fields pre-populated and pass an empty response. There is no test for the *partial* case: some fields populated, response has data for a *subset* — the COALESCE should preserve the other fields while updating the provided ones. Fix: add a test where the response provides `publisher` but not `developer`, and assert `developer` is preserved.

---

### Splitting

- [LOW] test_security_headers.py:146–159 — `test_nonce_in_template_matches_g_csp_nonce` performs three distinct assertions in one test body: (a) nonce is rendered correctly by template, (b) template value equals `g.csp_nonce`, (c) token length is >= 20. All three assertions fit in ~15 lines and share an identical setup (one `test_request_context`), so splitting would add ceremony without clarity. No action required.

---

### Fixtures

- [MED] test_scrape_fill_only.py:59–63 — The `noop_download` fixture is `function`-scoped (default) but it only sets `monkeypatch` attributes that monkeypatch resets anyway. The fixture rebuilds the monkeypatch every test call. This is harmless and correct — monkeypatch is function-scoped. No issue.

- [LOW] test_slow_query_log.py:13–21 — `capture_db_log` is a function-scoped fixture wrapping `caplog`. This is the right scope. No issue.

---

### Hardcoded Data

- [LOW] test_scrape_fill_only.py:67–73 — Game data literals (`'Chrono Trigger'`, `'Squaresoft'`, `1995-03-11`, etc.) and test_tgdb (`'Mega Man X'`, `'Capcom'`, `1993-12-17`) are hardcoded inline in the test functions rather than defined as constants or a `pytest.fixture`. This is fine for a two-test file pinning a specific regression shape — the games are chosen for recognisability. No action needed at current scale.

---

### Setup / Teardown

- [MED] test_terminal_status.py — There is no autouse fixture to reset `shutdown_requested` between tests. Tests rely on explicit `shutdown_requested.clear()` calls at the start of each test that needs the cleared state, but `test_shutdown_takes_precedence_over_user_cancel` calls `shutdown_requested.set()` and clears it in `finally`. If a test is added after this block and the author forgets to call `.clear()`, it will inherit a dirty event. Fix: add a module-level or function-scoped autouse fixture:
  ```python
  @pytest.fixture(autouse=True)
  def reset_shutdown_event():
      shutdown_requested.clear()
      yield
      shutdown_requested.clear()
  ```

---

### Parametrisation

- [MED] test_terminal_status.py:11–41 — The four test functions all follow the same pattern: set/clear `shutdown_requested`, call `resolve_terminal_status(cancelled=True/False)`, assert return value. This is a natural parametrize table: `(set_event, cancelled_arg, expected_status)`. The current 4-function expansion is clear and explicit — this is borderline. The duplication is most visible in `test_event_clear_restores_normal_mapping` which re-asserts both mappings already covered by the first two tests. Fix: consider `@pytest.mark.parametrize("set_event, cancelled, expected", [...])` for the first three tests, and remove the fourth as redundant.

- [LOW] test_routes_smoke.py:83–91 — `TestAuthGuards.test_protected_get_redirects_unauthenticated` is already well-parametrized. Good pattern; no finding.

---

### Error Handling

- [LOW] test_scan_library_rom_path.py:251 — `pytest.raises(RomPathNotConfigured, match=r'[Ss]ettings')` uses a case-insensitive-first-char regex `[Ss]`. This works but the intent is to match any capitalisation of "settings". The regex is correct but slightly unusual; `re.IGNORECASE` via `match=r'(?i)settings'` would be clearer. Minor.

---

### Doc Strings

- [INFO] test_routes_smoke.py — All four `class`-level docstrings are concise and explain the regression context. Good pattern.

- [INFO] test_scan_library_rom_path.py — The top-of-file block comment (lines 1–25) is thorough and correctly captures the bug shape, the two affected files, and what the three test classes pin. Exemplary regression documentation.

- [LOW] test_slow_query_log.py:25 — `class TestSlowQueryGate` has no docstring. Given the file's module-level docstring is minimal (line 1: one line), a class docstring explaining what contract is being pinned (`_log_if_slow` should log slow queries above threshold, suppress fast ones, and be disabled at threshold=0) would aid future readers. Low priority.

- [LOW] test_terminal_status.py — Module-level docstring (lines 1–7) is well-written. Individual test functions have inline docstrings. Good pattern; no action needed.

---

## Cross-file patterns (within this chunk)

1. **Duplicate `client` fixture** — `test_routes_smoke.py:11–22` and `test_security_headers.py:8–19` are byte-for-byte identical module-scoped client fixtures. Both files work around the `monkeypatch`-not-available-in-module-scope constraint identically. This is a strong candidate for a shared `conftest.py` fixture (`app_client`). Possibly also in other chunks (cross-chunk hypothesis: `test_auth_hardening.py`, `test_pass41_security.py`, etc.).

2. **`_REPO_ROOT` re-invention** — `test_scan_library_rom_path.py:35–37` re-invents what `tests/_util.py:REPO_ROOT` provides. The same anti-pattern appears in many other files (confirmed by cross-repo grep: 134 remaining usages). This chunk's file predates or missed the `_util.py` extraction. The fix is the same as the prior audit recommended: `from tests._util import REPO_ROOT`.

3. **Source-file reads via `open()`** — `test_scan_library_rom_path.py:157–158, 170–171` use raw `open()` instead of `read_source()` from `_util.py`. The `_util.py` helper was introduced specifically to replace this pattern. Same remediation as point 2.

4. **`shutdown_requested` event leakage** — `test_terminal_status.py` has no autouse reset fixture. This is a contained, 4-test file today, but the risk grows as tests are added. The fix (autouse fixture) is a 5-line addition.

---

## Summary

- CRITICAL: 0
- HIGH: 1
- MED: 9
- LOW: 8
- INFO: 2
