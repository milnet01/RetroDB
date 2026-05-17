# Test Audit — 2026-05-17

Framework: **pytest** · Files scanned: **65** · Chunks: **7** ·
Findings: **123 raw → 119 actionable** after triage (4 pre-pass false-positives ruled out)

Severity totals: **1 CRITICAL · 11 HIGH · 54 MED · 57 LOW**

Per-chunk reports: `.test-audit-reports/c-00{1..7}.md`.

---

## TL;DR — three themes do most of the work

If you only fix three things, fix these. ~40 of the 119 findings collapse into them.

1. **Mutating module-level singletons without `monkeypatch`** (12+ sites across 6 chunks). `app.config['TESTING']`, `sec._login_attempts`, `igdb._igdb_token_cache`, `ra._ra_console_cache`, `database._db_pool`, `migrations.MIGRATIONS`, root-logger `filters`, `SESSION_COOKIE_SECURE`. All bleed across tests under any non-trivial ordering — silent today, an `xdist` migration away from real flakes. **Fix shape:** session-scoped `restore_global_state` fixture in `conftest.py` that snapshots and restores the known global mutables, plus `monkeypatch.setattr` / `monkeypatch.setitem` at every direct-assignment site.

2. **Source-grep tests as the only assertion** (12+ sites across c-001/c-003/c-005/c-006). Tests open `routes/auth.py` / `app.py` / `static/js/*.js` and assert that some literal string is present. Today they pass when the string is in a comment, in dead code, or behind `if False:`. **Fix shape:** pair every source-grep with one minimal behavioural assertion that actually exercises the path; or, where the contract is structural, parse with `ast` instead of `str.count`.

3. **`_REPO_ROOT` + `sys.path.insert` + `open(__file__).read()` boilerplate** copy-pasted in 5+ files, ~15 occurrences inside `test_pass40_security.py` alone. **Fix shape:** `tests/_util.py` with `repo_root`, `read_source(rel_path)`, `slice_function(src, name)` — `conftest.py` is already in the import path. The pass-history "append-only" rule applies to test bodies, not to shared helpers, so this is safe.

---

## 🚨 CRITICAL (1)

- **`tests/test_bulk_scrape_race.py:111`** — Two back-to-back assertions contradict each other. Line 111 always fails (`job_id == first_id`), making the real regression assertion on line 116 (`job_id == queued_id`) unreachable. The whole test for the swap-race fix never reaches its meaningful check.
  **Fix:** Delete line 111 and its preceding comment; keep line 116. This test is in the working tree (`M tests/test_bulk_scrape_race.py`) so it's already being touched.

---

## 🔥 HIGH (11)

### Flakiness / timing
- **`tests/test_graceful_shutdown.py:87`** — `assert elapsed < 1.5` on a call that uses `request_shutdown(timeout=2.0)`. Upper bound narrower than the timeout under test → false fail on loaded CI. Fix: shrink the timeout or scale the bound (`< timeout * 1.5`).
- **`tests/test_launcher_local.py:46/66/101`** — `while time.time() < deadline: time.sleep(0.05)` × 3 tests with no diagnostic on timeout breach. Total wall time up to 6 s. Fix: `_poll_exited()` helper with `pytest.fail(f"timed out; last={st!r}")`.
- **`tests/test_migrations.py:210`** — `time.sleep(0.01)` to force SQLite trigger timestamp to advance; 10 ms is tight enough to produce equal strings under scheduler jitter. Fix: seed an explicit old `updated_at` then verify the trigger overwrites it; no sleep needed.

### Isolation (the big theme)
- **`tests/test_input_hardening.py:52`** — `app_module.app.config['TESTING'] = True` mutates Flask global config with no teardown. Race under `pytest-xdist`. Fix: `monkeypatch.setitem(...)`.
- **`tests/test_log_redactor.py:94-105`** — `install_global_redactor()` adds a `SecretRedactor` to root-logger filters with no removal. Pollutes every subsequent test's log records.
- **`tests/test_pass32_hardening.py:199-208`** — `ra._ra_console_cache` mutated by `_ra_cache_set()` and never restored.
- **`tests/test_pass33_34_hardening.py:117-131`** — `sec._login_attempts.clear()` without restore; leaves IP `203.0.113.99` rate-limit state populated.
- **`tests/test_pass41_security.py:509-551`** — `igdb._igdb_token_cache` directly mutated and left in `'FRESH'` state after the test.
- **`tests/test_emulator_registry_routes.py:16`** — `open('routes/emulators.py')` is CWD-relative; fails when pytest is invoked outside repo root (common in CI containers, IDE runners).

### Accuracy
- **`tests/test_pass29_frontend.py:59-66`** — `assert src.count('options.allowHtml') >= 2` only counts occurrences anywhere in the file; passes even if both hits are in comments or dead code, not in the actual `show` / `showInfo` function bodies. Fix: slice each function body and assert within.
- **`tests/test_hltb_bulk.py:46`** — `test_all_three` uses substring-presence on `_format_playtime_str` output; separator, order, and numeric formatting all unverified. Fix: assert the exact string.

### Performance
- **`tests/test_auth_hashing.py:19,31,65`** — 4 × `hash_password()` calls at production PBKDF2 iteration count (600 000). Adds ~1.5–3 s per suite run. Fix: pass `iterations=1` everywhere except one dedicated test that asserts `PBKDF2_ITERATIONS >= 600_000`.

---

## ⚠️ MED (54 — selected highlights, full list in per-chunk reports)

**Isolation (8 more sites)** — same theme as HIGH. `test_auth_hardening.py:204` (`_db_pool={}`), `test_database_backup.py:136` (`sqlite3.connect` swap without monkeypatch), `test_graceful_shutdown.py:60` (`shutdown_requested.clear()` not in `try/finally`), `test_pass33_34_hardening.py:80` (`TESTING=True` on app singleton), `test_pass41_security.py:111` (rate-limit bucket inline clear), `test_pass40_security.py:248/389` (TESTING never reset), `test_observability.py:13` (module-scoped `client` installs request-id factory globally), `test_security_headers.py:62` (`SESSION_COOKIE_SECURE` flipped without restore).

**Assertion quality** —
- `test_pass35_36_hardening.py:261` — `assert ... or "Pass 36.8" in gm` — the `or` makes the left side irrelevant whenever the comment string exists anywhere in the file. **Vacuous pass.**
- `test_pass42_normalize_game_edit.py:132` — `assert out['sort_title'] != 'Final Fantasy IX' or 'IX' not in out['title']` — disjunctive, always-true in practice. **Vacuous pass.**
- `test_pass40_security.py:259` — Validator test passes via 302-auth-block branch without exercising the validator. **Vacuous pass.**
- `test_pass33_34_hardening.py:98` — `"csrf_token=" in body` matches comments and assignments, not dict-key construction.
- `test_pass37_a11y.py:143` — Heading hierarchy test asserts exact emoji-bearing strings; emoji removal would falsely flag a heading regression.
- `test_input_hardening.py:75` — SSRF rejection-reason test uses loose `or` chain; sibling tests assert only `assert err` (non-empty).
- `test_museum_job.py:81`, `test_launcher_local.py:47` — compound/short-circuit assertions hide which sub-condition failed.

**Splitting / parametrisation** — 9 sites where one test bundles 3–5 logically distinct cases:
- `test_pass32_hardening.py:17, 56, 67` — path validator, bool validator, port-range each lump 2–5 cases.
- `test_launch_settings_validators.py:23, 43` — concurrent-game enum, command-injection payloads.
- `test_pass40_security.py:41-133` — 12 single-call validator test methods that should be one parametrize.
- `test_pass42_normalize_game_edit.py:66-83` — 5 single-input `players` tests.
- `test_metadata_merger.py` — `_blank_metadata()` + `_blank_result()` repeated 30+ times; convert to fixtures.

**Duplication** —
- `test_pass40_security.py` — ~15 inlined `open(mod.__file__).read()` blocks; extract helper.
- `test_pass31_migrations.py` — tempdir + connect + `apply_pending` + close scaffold repeated 6+ times.
- `test_scan_library_rom_path.py` — `_FakeCursor`/`_FakeConn` duplicated, already with subtle behavioural divergence.
- `test_slow_query_log.py` — manual `_CaptureHandler` + `try/finally` in 6 tests; pytest's `caplog` collapses this entirely.

**Coverage gaps** —
- No test for the DELETE handler in `test_emulator_registry_routes.py` (CRUD without D).
- IPv6 private-range SSRF rejection untested (only IPv4 covered).
- `_FakeCursor`-divergence path in `test_scan_library_rom_path.py` could mask multi-cursor bugs.
- HLTB `except Exception → return None` path uncovered.
- `backup_database` with missing destination dir uncovered.

**Determinism** —
- `test_pass33_34_hardening.py:201` — `_FixedDateTime` patches `now()` but not `utcnow()`/`today()`; refactor of the SUT silently breaks the freeze.
- `test_emulator_seeder.py:76` — `assert n_emu == 12` will break the moment the emulator seed file grows; should be `>=` or before/after diff.
- `test_migration_012.py:78` — `MIGRATIONS.index('012_emulators') == 11` brittle on any earlier insertion.

**Security** —
- `test_auth_hardening.py:261` — `AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234567` carries the real Google API-key prefix `AIzaSy`. Slips gitleaks today (one char over the rule window) but a rule update will turn this into a CI red. **Fix shape:** replace with `FAKE_API_KEY_…` or add a scoped allowlist in `.gitleaks.toml`. (Also: normalising the prefix in test code desensitises reviewers to real leaks.)

---

## 💡 LOW (57) — full enumeration

Grouped by dimension. Each entry is `file:line — problem · fix`. Severity is LOW unless tagged INFO.

### Accuracy (5)

- `tests/test_auth_hardening.py:42-45, 51-54` — Source-grep on error message string literals passes even if string is in dead code or unreachable. Fix: pair each grep with one behavioural assertion that calls the auth flow.
- `tests/test_auth_hardening.py:64-73` — Ordering verified by comparing string indexes of `session.clear()` and `session['user_id']`; satisfied if the strings appear in comments. Fix: behavioural test via test client that checks session state before and after login.
- `tests/test_pass32_hardening.py:192-196` — `is True` / `is False` asymmetry between the two `_check_response_size_cap` calls (one tests truthy, one tests exact `False`). Fix: document the asymmetric contract or assert both with `is`.
- `tests/test_pass41_security.py:442-453` — Asserts `'Pass 41.4.B' in body` (comment-marker presence) plus `except Exception` near a 4 KB window. A refactor that removes the actual `try/except` but keeps the comment still passes. Fix: use `inspect.getsource` to count `except` blocks, or inject a raising fake for one source and confirm others complete.
- `tests/test_launcher_base.py:15-16` — `assert ctx.argv[0].endswith('retroarch')` — `/usr/games/libretro_retroarch_wrapper` would still pass. Fix: assert exact resolved binary path.

### Assertion quality (4)

- `tests/test_security_headers.py:102-103` — `pat.search(csp).group(1)` with no `None` guard; mismatch raises `AttributeError` rather than `AssertionError`. Fix: `m = pat.search(csp); assert m, f"nonce not found in {csp[:100]}"`.
- `tests/test_scan_library_rom_path.py:254, 265` (×2) — `pytest.raises(RomPathNotConfigured)` without `match=`. The user-facing remediation message ("Go to Settings → Paths") is asserted nowhere. Fix: `match=r'[Ss]ettings'`.
- `tests/test_pass32_hardening.py:192` — Intentional `is True` vs `is False` asymmetry (also listed above under Accuracy). Same single fix.

### Coverage gaps (7)

- `tests/test_alternate_titles.py` — `merge_alt_titles` filters out malformed dicts in the `existing` list (line 131 of `metadata_normalizer.py`); only the `new_entries` side is tested. Fix: add `merge_alt_titles([{"region": "JP"}, {"title": "Rockman"}], [])` test.
- `tests/test_bulk_scrape_job.py` — `BulkScrapeJob.start([], system_id=1)` is an unguarded call path; behaviour not pinned. Fix: assert either `total==0` succeeds or empty list is rejected at API layer.
- `tests/test_image_pipeline.py` — `_ensure_format_matches_extension` against a corrupt file (PIL `UnidentifiedImageError`) is untested. Fix: write corrupt bytes, call, assert no raise or specific exception.
- `tests/test_retroarch_detect.py` — `shutil.which` returning `None` (no RetroArch anywhere) is uncovered. Fix: monkeypatch `shutil.which` to return `None`, assert falsy.
- `tests/test_pass38_ra_check_helper.py:133` — Swallowed-exception test only uses `RuntimeError`; `requests.Timeout` / `ConnectionError` (the real-world cases) untested. Fix: parametrize over the network exception types.
- `tests/test_launcher_factory.py` — `get_setting` returning `None` (setting absent) is uncovered — unclear whether factory raises or defaults to `'local'`. Fix: add test pinning the contract.
- `tests/test_scrape_fill_only.py` — Both tests cover only the "empty API response preserves existing" path. The return-`False` path (game not found, DB error) is what the COALESCE invariant guards — uncovered. Fix: add `test_igdb_apply_returns_false_when_game_not_found` for each scraper.

### Dead test code (2)

- `tests/test_launch_resolver.py:2` — `import os` unused (AST-confirmed). Fix: remove.
- `tests/test_launch_resolver.py:4` — `from pathlib import Path` unused (AST-confirmed). Fix: remove.

### Doc-strings (8)

- `tests/test_alternate_titles.py:1` — No module docstring; alone among siblings in chunk c-001. Fix: one-line module docstring.
- `tests/test_hltb_bulk.py` — `TestClassifyMatch`, `TestFormatPlaytimeStr`, `TestExtractAltTitlesList` methods lack docstrings; names like `test_none`, `test_valid`, `test_all_three` are not self-documenting.
- `tests/test_launcher_base.py` — 5 dataclass-pin test classes have no class docstrings. Fix: one-liner each ("Pin the LaunchContext dataclass field names and types").
- `tests/test_launcher_local.py` — Subprocess tests lack docstrings stating expected OS/platform behaviour.
- `tests/test_pass29_frontend.py:77` — `test_29_1_achievements_render_escapes_badge_url` lacks docstring while sibling `test_29_1_*` tests all have one.
- `tests/test_pass31_migrations.py:103, 113` — `TestCollectorTrophiesUserIdMigration` methods lack docstrings while sibling classes (`TestPSNUserIdMigration`, `TestAchievementUserIdMigration`) document every method.
- `tests/test_retroarch_detect.py` — No module docstring; no docstrings on 8 test functions. Security-relevant file; should at minimum document the invariant being pinned.
- `tests/test_terminal_status.py:11-38` — None of 4 top-level tests have docstrings; `test_shutdown_takes_precedence_over_user_cancel` (the subtlest invariant) most needs one. Fix: promote the existing block comment at lines 22-25 to a docstring.

### Duplication (1)

- `tests/test_hltb_bulk.py:76, 84, 94` — `import json` inlined inside 3 separate test methods. Fix: move to module level.

### Error handling (1)

- `tests/test_pass32_hardening.py:150-155` — `test_32_8_clz_pdf_constants_exist` only checks `hasattr(config, 'CLZ_PDF_MAX_PAGES')`. If always-present: assert specific type/default. If optional: the test is asserting nothing meaningful. Fix: clarify the contract.

### Fixtures (3)

- `tests/test_atomic_io.py:14-76` (all 6 tests) — Uses `tempfile.TemporaryDirectory()` inline rather than pytest's `tmp_path` fixture. Less debuggable in CI. Fix: switch to `tmp_path`, drop `import tempfile`.
- `tests/test_pass38_region_helper.py:27-42` — `stub_settings` returns a factory function the caller must invoke; if forgotten, `load_settings` is undefined and raises a confusing `AttributeError`. Fix: rename to `stub_settings_factory` and document, or provide a default payload.
- `tests/test_scrape_fill_only.py:60` — Fixture named `_noop_download` with leading underscore breaks pytest naming convention (underscores signal "private helper", not fixture). Fix: rename to `noop_download`.

### Hardcoded data (1)

- `tests/test_pass31_migrations.py:197-209` — `/tmp/legacy_gap_test.rom` hardcoded as a DB string value; fragile on Windows, theoretical collision with real files. Fix: `str(tmp_path / 'legacy_gap_test.rom')`.

### Isolation / setup-teardown (2)

- `tests/test_pass40_security.py:248, 389` — `app_module.app.config['TESTING'] = True` mutated on app singleton without reset; latent isolation problem. Fix: `monkeypatch.setitem(...)`. (Same root cause as the MED list above.)
- `tests/test_emulator_registry_routes.py:36` — Auth-bypass fixture is correctly `monkeypatch`-scoped — no actual leak. Flagged for awareness that the pattern should not be replicated outside the test layer.

### Naming / AAA structure (5)

- `tests/test_bulk_scrape_race.py:63-64` — `TestSwapWaitsForWorkerExit` / `test_swap_does_not_reset_state_until_worker_exits` name the mechanism (join/wait), not the user-visible behaviour. Fix: rename to behaviour form.
- `tests/test_hltb_bulk.py:11-41` — Test names describe inputs (`test_none_result`, `test_auto_apply_at_threshold`) not behaviour. Fix: `test_none_result_classified_as_skip`, etc.
- `tests/test_metadata_merger.py:53, 119` — `test_fills_empty_text_fields` (TGDB) vs `test_fills_basic_text_fields` (IGDB) are the same test shape with diverged names. Fix: standardise.
- `tests/test_migrations.py:164` — `test_idempotent_baseline_can_run_twice` sits in `TestApplyPending` but is really a forced-rerun regression guard. Fix: rename to `test_forced_rerun_from_zero_does_not_raise` or move under a `TestIdempotency` class.
- `tests/test_pass35_36_hardening.py:52-61` — Bare `try/except OSError: pass` with trailing `raise AssertionError` in `else` branch is equivalent to `pytest.raises(OSError)`. Fix: use `with pytest.raises(OSError): _fsync_path("/nonexistent/...")`.
- `tests/test_pass38_scrape_history_helper.py:23` — Fixture named `cursor` returns a `sqlite3.Connection`, not a cursor; every test then calls `cursor.cursor()`. Fix: rename to `connection`.

### Parametrisation / verbosity (12)

- `tests/test_formatters.py:38-56` — Four manufacturer-lookup methods (`test_nintendo_consoles` etc.) differ only in `(folder, expected)` tuples. Fix: single `@pytest.mark.parametrize` table.
- `tests/test_game_utils.py:21-50` — 9 single-input/single-output `test_leading_*_moves_to_end` methods. Fix: parametrize.
- `tests/test_emulator_seeder.py:28-64` — Three consecutive tests start with identical `seed_emulators_from_file` call. Fix: autouse fixture or wrapper fixture around `db`.
- `tests/test_hltb_bulk.py:10-41` — 7 tests on `classify_match` that differ only in dict shape + expected string. Fix: single parametrize block (table-driven).
- `tests/test_image_pipeline.py:158-204` — `test_emits_candidates_when_variants_exist` and `test_skips_missing_variant_siblings` share 8 lines of setup. Fix: `boxart_with_files(tmp_path, monkeypatch, files)` fixture.
- `tests/test_launch_settings_validators.py:28-32` — Four asserts (3 accept, 1 reject) for permission enum. Fix: parametrize or split into accepts/rejects.
- `tests/test_metadata_merger.py:53-112` — Fill-only contract tested per-source with diverged naming (`preserves_existing_non_title` vs `keeps_existing`). Same invariant, two shapes. Fix: cross-source parametrize.
- `tests/test_pass33_34_hardening.py:63-70` — Loop over `('api_change_password', 'api_force_change_password')` obscures which function failed in pytest output. Fix: parametrize so each is its own node.
- `tests/test_pass38_resume_helpers.py:163-179` — Inline parametrize list hardcodes 3 paths already in named `JOB_MODULES` constant. Fix: `_SINGLETON_MODULES = JOB_MODULES[:4]` and reference.
- `tests/test_pass41_security.py:33-52` — 4-needle loop on lines 44-51 should be parametrize (currently first failing needle hides the others).
- `tests/test_pass41_security.py:506-551` — `test_request_retries_with_fresh_token_on_401` bundles 4 contracts: return value, call count, retry bearer token, cache update. Fix: split into `test_401_retry_returns_correct_result` + `test_401_retry_updates_cache`.
- `tests/test_pass40_security.py:209-265` — 55-line test for `test_post_rejects_attacker_chdman_path` carries defensive scaffolding around auth-bypass uncertainty. Trims to ~15 lines once the MED-level auth-fix (`A-1`) is applied.
- `tests/test_slow_query_log.py:28-104` — `try/finally` boilerplate repeated in all 6 tests. Collapses to nothing with `caplog`. Fix shape: see MED-1 in c-007.

### Performance / fixture scope (1)

- `tests/test_observability.py:13` — Module-scoped `client` fixture reused across `TestSlowRequestLogging` tests that use `caplog`. Background log records from earlier tests may pollute later assertions. Currently mitigated by message filter, but fragile. Fix: function-scoped client, or `caplog.clear()` at the start of each slow-log test.

### Security (3)

- `tests/test_input_hardening.py:131` — `src = open(mod.__file__).read()` bare-`open` without context manager. Fix: `with open(...) as f: src = f.read()`.
- `tests/test_hltb_endpoint.py:63-78` — Stale-URL check skips docstrings line-by-line (only on lines containing triple-quotes). Multi-line docstring bodies that mention `/api/find/init` would trigger a spurious failure. Fix: `ast`-based docstring stripping, or track `in_docstring` across lines.
- **[INFO]** `tests/test_job_history_sweep.py:43-54` — `_insert_job` builds SQL via f-string with `completed_days_ago` interpolated. All call sites are int literals or `None`, no injection risk. `pyproject.toml` already suppresses `S608` globally for `tests/`. **No action required** — flagged for completeness only.

### Determinism (3)

- `tests/test_pass32_hardening.py:125-147` — Thread-local accessed via `getattr(module, '_pinned', None)`; if the attribute is renamed the test silently returns `None` and asserts `None is None` — vacuous pass. Fix: assert the attribute name exists on the module *before* the thread starts (`hasattr` check up front).
- `tests/test_migrations.py:209-215` — String lexicographic comparison of ISO timestamps works only because both formats are identical. If trigger format ever changes (drops `Z`, different precision), comparison silently becomes wrong. Fix: parse with `datetime.fromisoformat(...rstrip('Z'))`.
- `tests/test_launcher_registry.py:64-66` — `started_at=time.time() - 3.0` and `exit_time=time.time() - 2.0` use two separate `time.time()` calls; under virtualised time sources, drift between calls could violate the relative TTL invariant. Fix: single baseline `t = time.time()`, use offsets from `t`.

---

## Additional INFO

- `tests/test_job_history_sweep.py:43` (above) — SQL f-string in test helper, intentional. No action.

---



---

## Filtered (4 pre-pass false-positives)

| File:line | Pattern | Reason |
|---|---|---|
| `test_auth_hashing.py:40` | hardcoded_password | `"legacy_password"` — obviously-fake test scaffolding for PBKDF2 legacy-format migration. No credential shape. |
| `test_auth_hashing.py:49` | hardcoded_password | Same. |
| `test_bulk_scrape_race.py:4` | sleep_call | Line is in the module docstring describing the old buggy `time.sleep(0.5)`. Prose, not code. |
| `test_pass40_security.py:815/834` | sleep_call (×2) | Lines are inside `test_no_bare_time_sleep_in_jobs` and contain the literal string `'time.sleep('` as a grep needle, not an invocation. |
| `test_pass41_security.py:369` | hardcoded_password | Loop iterates over `('password: admin', "password='admin'", ...)` as needles asserting the credential does NOT appear in `database_init.py`. No secret committed. |

---

## Suggested roadmap shape (group by fix, not by file)

| Pass | Theme | Surface |
|---|---|---|
| A | Critical assertion fix in `test_bulk_scrape_race.py` | 1 line, ship today |
| B | Sweep all module-global mutations to `monkeypatch.setattr/setitem` + add `restore_app_config` autouse fixture | ~12 sites, 6 files |
| C | Extract `tests/_util.py` with `read_source` / `slice_function`; collapse 15+ open-and-grep blocks in test_pass40 | ~5 files |
| D | Pair every source-grep assertion with one behavioural assert (or use `ast`) | ~12 sites |
| E | PBKDF2 iteration drop in `test_auth_hashing.py` | 1 file, ~1.5–3 s suite saving |
| F | Replace `time.sleep` poll patterns with `threading.Event` / `pytest.fail()` on deadline breach | 4 files |
| G | Parametrise the 9 split-candidate tests | scattered |
| H | IPv6 SSRF coverage, DELETE-route coverage, HLTB exception coverage | 3 small additions |
| I | Replace gitleaks-bait literal `AIzaSy…` with `FAKE_…` | 1 line in `test_auth_hardening.py` |

Items A, E, I are one-line fixes that close real risk and pay for themselves.
