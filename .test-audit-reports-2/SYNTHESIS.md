# Test Audit — 2026-05-17 (post-v3.6.8)

Framework: **pytest** · Files scanned: **66** (incl. `__init__.py`, `_util.py`, `conftest.py`) · Chunks: **6** ·
Findings: **99 actionable** after triage (4 pre-pass false-positives ruled out — all are grep-needle string literals or docstring prose)

Severity totals: **0 CRITICAL · 7 HIGH · 31 MED · 61 LOW**

Per-chunk reports: `.test-audit-reports-2/c-00{1..6}.md`.

This run was performed after `v3.6.8: Test-suite audit fix-pass — 119 findings resolved`. The chunk subagents were briefed on the prior synthesis (`.test-audit-reports/SYNTHESIS.md`) and explicitly instructed not to re-flag fixed-and-shipped issues. The findings below are either (a) genuinely new, or (b) sites in the prior themes that were missed by the v3.6.8 sweep.

---

## TL;DR — three themes do most of the work (again)

If you only fix three things, fix these. ~50 of the 99 findings collapse into them.

1. **Unguarded `app.config['TESTING'] = True` mutations (17 sites across 8 files).** v3.6.8 fixed some of these but left a long tail. The new sites: `test_auth_hardening.py:53,134,373` (3) · `test_etag_and_gzip.py:20,75` (2) · `test_observability.py:26` (1 — fixture restores other globals but omits TESTING) · `test_pass41_security.py:1102` (1, HIGH — sole survivor in a file where every other site already uses `monkeypatch.setitem`) · `test_pass45_security.py:81,237,1257,1421,1445,1538,1602` (7, HIGH — entirely missed by the prior sweep) · `test_routes_smoke.py:14`, `test_security_headers.py:11`, `test_scan_library_rom_path.py:292` (3, HIGH). **Fix shape:** for function-scoped tests, `monkeypatch.setitem(app_module.app.config, 'TESTING', True)`. For module-scoped fixtures (where `monkeypatch` cannot be used), snapshot the prior value and restore in a `try/finally` around `yield`.

2. **Bare `open(path).read()` and `_REPO_ROOT` boilerplate that should use `tests/_util.py` (~70 sites across 8 files).** The `_util.read_source()` / `read_module_source()` helpers were extracted in v3.6.8 to centralise this exact pattern, but several files were not migrated. The egregious cases: `test_auth_hardening.py` (6 bare opens, ~MED), `test_pass40_security.py` (7 bare opens incl. one HIGH in a loop), `test_pass41_security.py` (~51 bare opens, MED). `test_pass38_normalize_ratings_helper.py:16–18` is the sole remaining `_REPO_ROOT` boilerplate site in chunk c-004 (the rest of the pass-history files were migrated). Four files carry a now-dead `_REPO_ROOT = REPO_ROOT` backwards-compat alias that has no external importer.

3. **Source-grep / comment-anchor tests that pass vacuously.** Theme persists in c-002 (`test_emulator_registry_routes.py:21` — decorator grep with no body scoping), c-003 (`test_input_hardening.py:33–58` — re-implements production helper instead of importing it), c-004 (`test_pass35_36_hardening.py:290–292` — aria-live grep checked *before* `init_body` is sliced), c-005 (`test_pass41_security.py:97–126` — `src[A:B]` slice with no guard that A precedes B; on rename, slice becomes negative-length empty string and assertion vacuously passes). Several "Pass NN.N" comment-marker anchors duplicate a structural check immediately below and add no coverage (`test_pass33_34_hardening.py:273`, `test_pass35_36_hardening.py:68`).

---

## 🔥 HIGH (7)

### Isolation (the dominant theme — 6 of 7)

- **`tests/test_pass45_security.py:81,237,1257,1421,1445,1538,1602`** — Seven bare `app_module.app.config['TESTING'] = True` assignments across 6 test methods. None use `monkeypatch.setitem`. **This file was missed entirely by the v3.6.8 fix-pass.** Fix: replace each with `monkeypatch.setitem(app_module.app.config, 'TESTING', True)`.
- **`tests/test_pass41_security.py:1102`** — Sole surviving bare TESTING mutation in this file. Every other site (lines 224, 330, 405, 462, 553, etc.) was correctly migrated to `monkeypatch.setitem`. Fix: same.
- **`tests/test_routes_smoke.py:14`** — Module-scoped `client` fixture mutates `app.config['TESTING']` without teardown. `monkeypatch` is not available in module-scoped fixtures; use snapshot + `try/finally` around `yield`.
- **`tests/test_security_headers.py:11`** — Same shape as `test_routes_smoke.py:14`. The prior synthesis fixed `SESSION_COOKIE_SECURE` (line 76 now has `try/finally`) but left the initial `TESTING` mutation unguarded.
- **`tests/test_scan_library_rom_path.py:292`** — `_client()` helper mutates `app.config['TESTING']` directly. `monkeypatch` is in scope at the call site but not passed in. Fix: accept `monkeypatch` as a parameter and use `monkeypatch.setitem`.

### Flakiness (1)

- **`tests/test_graceful_shutdown.py:92`** — `assert elapsed < 1.5` with underlying `timeout=0.5`. Flagged in the prior synthesis but still present. On a loaded CI runner, thread scheduling overhead can push elapsed above 1.5s. The alive-check on line 93 is the stronger assertion; line 92 is redundant if 93 is kept. Fix: drop line 92 or scale to `< timeout * 3.0`.

### Dangerous patterns (1)

- **`tests/test_pass40_security.py:921`** — `src = open(path).read()` bare (no context manager) *inside a loop*, opening 5 source files. If any `open` raises mid-loop (file moved, permissions changed), up to 5 file descriptors leak. The adjacent method `test_each_job_imports_shutdown_event` uses the correct `with open(...) as f:` pattern. Fix: `with open(path, encoding='utf-8') as f: src = f.read()`.

---

## ⚠️ MED (31 — selected highlights; full list in per-chunk reports)

### Isolation continuation (more TESTING / cache mutations not at HIGH severity)

- `test_auth_hardening.py:53,134,373` (×3) — three bare TESTING mutations in function/class-scoped contexts. Fix: `monkeypatch.setitem`.
- `test_etag_and_gzip.py:20` — module-scoped `client` sets TESTING with no teardown.
- `test_etag_and_gzip.py:75` — `test_request_parity` constructs its own client *outside* the module fixture and re-mutates TESTING inline.
- `test_observability.py:26` — `client` fixture restores log-factory and `_request_id_installed` but silently omits TESTING. Fix: snapshot before `yield`, restore after.
- `test_graceful_shutdown.py:69–79` — `shutdown_requested.clear()` not wrapped in `try/finally`; assertion failures leak the SET state to subsequent tests. The sibling `test_sets_shutdown_event` uses the correct pattern.
- `test_pass31_migrations.py:183–187` — `migrations.MIGRATIONS` mutated via bare `try/finally` instead of `monkeypatch`. Sister file `test_migrations.py:324–329` performs the *identical* mutation with `monkeypatch.setattr` and an inline comment explaining why (`"so the global list is restored even if the test is killed mid-run (SIGKILL/OOM)"`).
- `test_launcher_factory.py:5–12` — `_singleton = None` set via direct attribute mutation in `_reset_singleton` autouse fixture. `monkeypatch.setattr` would handle collection-time errors that bypass `yield`/teardown.
- `test_pass41_security.py:848,849` — `hltb_lookup._auth_token = None` reset without restore.
- `test_pass45_security.py:70,92` — `auth_mod.ROLE_PERMISSIONS['admin']` mutated in `try/finally`; asymmetric teardown if the inner `app.config['TESTING'] = True` assignment (above) fails.

### Dangerous patterns (bare opens, no context manager)

- `test_pass40_security.py:1017,1040,1053,1074,1084,1201` (×6) — single-file bare opens. One fd per test, not five — bounded but inconsistent with the file's own `_read()` helper and `read_module_source()` calls.
- `test_pass41_security.py` (~51 sites) — file-wide pattern. `_read(rel)` is already defined twice in two classes (line 225 and 300) but used only locally; ~51 inline opens reinvent it. `from tests._util import read_source` is even already imported at line 459, used in exactly one place.

### Accuracy / assertion quality

- `test_emulator_registry_routes.py:21` — `test_mutating_routes_require_admin` is pure source-grep with no behavioural assertion. Behavioural counterparts exist (`test_viewer_cannot_create`/`test_viewer_cannot_delete`) and cover the contract — this test name is misleading. Either delete or pair with `assert rv.status_code in (302, 403)` and rename.
- `test_pass40_security.py:175–178` — `"g.user.get('role') != 'admin'" in body or "g.user['role'] != 'admin'" in body` — disjunction is legitimate (style tolerance), but neither branch is scoped to the POST function body. Strip comments via `re.sub(r'#[^\n]*', '', body)` before assert (already done in `test_no_includes_lt_gt_heuristic` in the same file).
- `test_pass41_security.py:97–126` — `body = src[src.index("def api_change_password"):src.index("def api_force_change_password")]` with no order guard. If functions are reordered, the slice may be negative-length empty, vacuously satisfying `assert "rate_limit_login(client_ip)" not in body`. Fix: assert order before slicing, or use `slice_function(src, "api_change_password")`.
- `test_input_hardening.py:33–58` — `TestESDEPathTraversal` re-implements `_within_allowed_root` locally and tests *that* instead of the production helper at `scraper/scrape_esde.py:819`. A divergence in the production copy is invisible to the test. Extract the real helper to module scope and import it, or invoke `apply_esde_metadata` with a crafted traversal path.
- `test_security_headers.py:127–135` — `TestCspNonceInTemplateContext` class docstring states "`{{ csp_nonce }}` Jinja global **must match** what's sent in the header." The sole test only asserts the rendered nonce is non-empty (`len >= 20`). **A refactor that makes the context processor and the security middleware generate independent nonces would silently break every inline script.** Fix: capture nonce via `flask.g`, render template, assert equality; then issue a real `/health` request and assert the nonce appears in the `Content-Security-Policy-Report-Only` header.

### Flakiness

- `test_graceful_shutdown.py:114` — `assert elapsed < 1.0` with underlying `timeout=0.3`. Margin tighter than it looks; under VM/CI jitter 0.3+overhead approaches 1.0. The liveness check on line 116–117 is the stronger assertion.
- `test_bulk_scrape_race.py:102,106,150,152` — Thread synchronisation timeouts (2.0s, 5.0s) without diagnostic on breach. Capture the wait result: `observed = ev.wait(timeout=2.0); assert observed, f"Worker never observed cancel — job.cancelled={job.cancelled!r}"`.

### Coverage gaps

- `test_input_hardening.py:85–119` — IPv6 private-range SSRF rejection still untested (only IPv4 covered). Flagged in prior synthesis as still-open; confirmed unresolved. Add `test_ipv6_loopback_rejected` and `test_ipv6_link_local_rejected`.
- `test_hybrid_scraper.py` — `_pick_best_fallback([])` and `_pick_best_secondary([])` (empty-list paths) untested. A regression turning these into `IndexError`/`StopIteration` would not be caught.
- `test_emulator_autodetect.py` — `_detect_emulators([])` (empty scan paths) untested; rogue `.sh` script in a known emulator's directory untested.
- `test_graceful_shutdown.py` — `test_calls_cancel_on_running_jobs` populates 2 of 10 singletons; 8 `None` slots not exercised. A regression where `request_shutdown` AttributeErrors on `None` singletons would not be caught.
- `test_pass41_security.py` — `_search_hltb` when auth-token succeeds but search itself fails is untested.
- `test_pass39_supply_chain.py` — `select_pip_args()` fallback branch (no lockfile present) is untested.

### Parametrisation / verbosity (loops that hide failures)

- `test_pass40_security.py:100–158` — `test_bool_fields` loops over 9 keys; first failure stops the loop. Parametrize so all 9 run and each names the failing key.
- `test_pass41_security.py:1367–1400` — 5-route loop in `test_each_scan_requires_editor`.
- `test_hltb_alt_titles.py` — 6 of 7 methods in `TestAltTitleFallback` are parametric in (primary, alts, expected_game_id, expected_via_alt) — collapse via `@pytest.mark.parametrize`.

### Splitting

- `test_security_headers.py:47–53` and `110–116` — `for feature in (...)` over 7 permissions-policy keys, then 9 CSP directives. Security-relevant header contract — seeing all failures at once reduces "fix one, miss another" risk.

### Duplication (resource boilerplate)

- `test_pass38_normalize_ratings_helper.py:16–18` — sole remaining raw `_REPO_ROOT` + `sys.path.insert` boilerplate in chunk c-004; also carries unused `import pytest`.
- `test_database_backup.py:25,43,68,98,149` — 5 inline `tempfile.TemporaryDirectory()` blocks where `tmp_path` fixture would do.

### Fixture scope

- `test_etag_and_gzip.py:17` — module-scoped `client` fixture, but `test_request_parity` (line 76) builds its own client outside the scope, doubling app-context setups for the module.

---

## 💡 LOW (61) — selected highlights; full enumeration in per-chunk reports

### Boilerplate not migrated to `tests/_util.py` (8 sites)

- `test_auth_hardening.py:24` — `_REPO_ROOT` literal that duplicates `_util.REPO_ROOT`.
- `test_auth_player_role.py:5` — same, third variant (`pathlib.Path` style).
- `test_hltb_endpoint.py:29–32` — local `_REPO_ROOT` + `sys.path.insert`; also `_read_source()` static method that duplicates `_util.read_source()`.
- `test_scan_library_rom_path.py:35–37` — same boilerplate.
- `test_pass40_security.py` / `test_pass41_security.py` — module-top `_REPO_ROOT` boilerplate (each could become `from tests._util import REPO_ROOT as _REPO_ROOT`).
- `test_pass32_hardening.py:15` — dead `from tests._util import REPO_ROOT  # noqa: F401`; the `sys.path` side-effect it triggers is already guaranteed by `conftest.py`.
- `test_pass33_34_hardening.py:288`, `test_pass35_36_hardening.py:300`, `test_pass29_frontend.py:173`, `test_pass37_a11y.py:236` — four `_REPO_ROOT = REPO_ROOT` backwards-compat aliases with comment "retained for any external imports"; grep confirms no external importers.

### Source-grep tests that should be tightened

- `test_pass35_36_hardening.py:290–292` — aria-live / assertive grep checked *before* `init_body` is sliced (lines 293–294); a stray mention anywhere in the 2000-line `utils.js` satisfies both.
- `test_pass37_a11y.py:105–106` — `>= 4` lower bound on `deactivate` calls, but the file now has 7. Three deactivate calls can be removed before the test catches it.
- `test_pass37_a11y.py:136` — `re.search(r'\brel\s*=', tag)` accepts any `rel=` value including `rel="nofollow"`. Docstring claims "ships rel=noopener noreferrer" but the assertion doesn't verify either token.
- `test_pass35_36_hardening.py:163` — `src.index("Pass 36.1")` anchors on a comment marker; comment-cleanup pass turns the failure mode from informative AssertionError into `ValueError: substring not found`. Anchor on `"function escAttr("` instead.
- `test_pass33_34_hardening.py:273`, `test_pass35_36_hardening.py:68` — redundant Pass-marker assertions paired with a structural check immediately below. The marker can never catch what the structural check doesn't.
- `test_pass41_security.py:995–1000` — `'Pass 41.8'` comment-marker + 800-char window; reformat that moves the marker past the window silently breaks the inner assertions.

### Coverage gaps

- `test_metadata_merger.py:259–264` — `TestApplyRawg.test_franchise_only_fills_empty` covers `fill_only=False`; matching `fill_only=True` case missing to pin the invariant from the other direction.
- `test_launcher_factory.py` — `test_factory_raises_for_remote_in_v1` and `test_factory_raises_for_unknown` pin error types but not messages. Add `match=r"remote"` / `match=r"spaceship"`.
- `test_backup_rotation.py` — `_prune_old_backups` on a non-existent directory is uncovered.
- `test_hltb_bulk.py` — `_format_playtime_str(None, 8.0, 12.0)` (main missing, others present) uncovered.
- `test_game_query.py` — `not_franchise` / `not_developer` / `not_publisher` null-safe variants untested (only `not_genre` covered).
- `test_image_pipeline.py` — `finalize_downloaded_image` on a corrupt source at the pipeline level (vs. the isolation-level `_ensure_format_matches_extension` test) untested.
- `test_bulk_scrape_race.py:120–154` — `TestDemoteJobOrdering` asserts timing safety (join doesn't time out) but doesn't assert post-demote state (queue contents, job_id swap).

### Naming / AAA / docstrings

- `test_routes_launch.py:45–130` — `logged_in_client` fixture name hides that it also stubs `settings_manager.load_settings`. Rename to `player_client` and document.
- `test_pass38_resume_helpers.py:141–182` — `TestCallsitesUseHelpers` methods named for mechanism (`test_module_imports_pad_and_restore`) instead of behaviour; also source-grep where `hasattr(mod, 'pad_resume_game_ids')` (import identity) would be stricter.
- `test_retroarch_detect.py` — 9 test functions without docstrings on a security-sensitive endpoint.
- `test_metadata_merger.py:114` — two `test_fills_empty_text_fields` methods across `TestApplyTgdb` / `TestApplyIgdb`; same name but diverged shapes (7 vs 4 fields).
- `test_emulator_registry_routes.py` — `test_unauth_list_blocked` is a module-level function but `test_viewer_cannot_create/delete` are class methods; asymmetry deserves a one-line docstring.
- `test_auth_player_role.py:2` — unused `import os`.

### Splitting (LOW severity — loops over independent contract facets)

- `test_launch_settings_validators.py:65–79` — 5-key loop in `test_default_values_are_valid`.
- `test_launcher_base.py:86–93` — protocol-methods loop (4 distinct contracts).
- `test_auth_player_role.py:73–87` — `test_routes_use_permission_decorator` bundles 4 structural checks; failure of #1 masks #2–4.
- `test_pass37_a11y.py:197–198` — compound `and` assertions hide which half failed.

### Determinism / flakiness (LOW)

- `test_launcher_registry.py:81–82` — `test_gc_keeps_recent_exited` uses two separate `time.time()` calls for `started_at` / `exit_time`. Sibling `test_gc_removes_exited_after_ttl` was fixed in v3.6.8 (single `t = time.time()` baseline) but this twin was missed.
- `test_pass46_frozen_paths.py:62–101` — manually pops and re-imports `app` + `config` + `routes.scraper` etc.; ~300–400ms cost. The `reloaded_app` fixture (line 131) does this more cleanly — consolidate.

### Assertion quality (LOW)

- `test_slow_query_log.py:61,69` — bare `capture_db_log.records[0]` without `len() >= 1` guard. Sibling `test_non_sequence_args_still_logs:77` already does this correctly.
- `test_slow_query_log.py:71` — `assert '...' in msg` is the only truncation check; the documented 500-char cap is unverified. A 5000-char cap or no cap would still pass as long as `...` appears anywhere.
- `test_game_query.py:52` — `assert 42 in vals or '42' in vals` — type-ambiguous disjunction hides whether the SUT inserts int or str.
- `test_game_query.py:67` — `assert "'Z'" in str(vals) or 'Z' in vals` — substring on stringified list would pass for `['ZERO']`.
- `test_log_redactor.py:126` — `assert attached is True` on an `any(...)` result loses diff on failure; bare `assert attached` (+ msg) is clearer.

### Resource hygiene (LOW)

- `test_migration_012.py:28,53,64` (×3), `test_owner_id_self_heal.py:38,58,72,82` (×4) — in-memory `sqlite3.connect(':memory:')` never explicitly `.close()`ed. Reference counting closes under CPython today; fragile on PyPy or with `pytest-xdist` process reuse.
- `test_pass35_36_hardening.py:64` — `test_35_2_atomic_write_json_fsync_dir(tmp_path)` accepts `tmp_path` but never uses it; misleading signature and discardable per-test temp dir overhead.
- `test_log_redactor.py:112` — unused `caplog` fixture parameter.

### Performance / fixture scope (LOW)

- `test_database_backup.py` — Five tests write SQLite files to `tempfile.TemporaryDirectory()`; a session/module-scoped fixture for the populated source DB would remove repeated disk I/O.
- `test_launcher_local.py:35–116` — `LocalLauncher()` + `LaunchContext(...)` inline in every test body (×6); extract module fixtures.
- `test_pass41_security.py:683–743` — `test_each_start_acquires_lock_with_correct_name` instantiates 9 job classes in one method; parametrize so each gets its own node.

### Dead code / misc (LOW)

- `test_pass39_supply_chain.py` — no `import pytest` but `import yaml` at test level with no `pytest.importorskip` guard; `ImportError` rather than skip if `yaml` is missing.

---

## ✅ Confirmed fixed in v3.6.8 (selected verifications by chunk subagents)

- The CRITICAL contradicting-assertion race at `test_bulk_scrape_race.py:111` is gone; lines 113–114 now hold the correct non-contradicting assertions.
- `AIzaSy…` gitleaks-bait at `test_auth_hardening.py:333` is now `FAKE_API_KEY_…`.
- PBKDF2 production-iteration cost: `TEST_ITERATIONS = 1` in effect; only the compliance-pin test reads `PBKDF2_ITERATIONS` without hashing.
- `tests/test_atomic_io.py` migrated from `tempfile.TemporaryDirectory()` to `tmp_path` across all 6 tests.
- `tests/test_alternate_titles.py` `merge_alt_titles` malformed-entry path now covered.
- `test_log_redactor.py` SecretRedactor cleanup now `try/finally`-wrapped.
- `test_pass32_hardening.py` `ra._ra_console_cache` mutation now `monkeypatch.setattr`.
- `test_pass33_34_hardening.py` `sec._login_attempts.clear()` now `monkeypatch.setattr(sec, '_login_attempts', OrderedDict())`.
- `test_pass29_frontend.py:59–66` source-grep now `_js_method_body()` scoped.
- `test_observability.py:13` module-scoped client → function-scoped with teardown (TESTING omission noted above is a separate residual).
- `test_pass35_36_hardening.py:261` vacuous `or "Pass 36.8"` → unconditional `== 0`.
- `test_pass37_a11y.py:143` emoji-bearing heading strings → regex match.
- `test_migrations.py:164` rename to behaviour form.
- `test_migrations.py` ISO timestamp lex-comparison → `datetime.fromisoformat`.
- `test_pass31_migrations.py` `/tmp/legacy_gap_test.rom` hardcoded path → `tmp_path / 'legacy_gap_test.rom'`.
- `test_security_headers.py:62` `SESSION_COOKIE_SECURE` now `try/finally`-restored.
- `test_scrape_fill_only.py:60` `_noop_download` fixture renamed (leading underscore removed).
- `test_scrape_fill_only.py` failure-path uncovered branch added (`_FailingConn` + two `test_*_apply_returns_false_when_db_fails`).
- `test_scan_library_rom_path.py:254,265` `pytest.raises(RomPathNotConfigured)` now uses `match=r'[Ss]ettings'`.
- `test_slow_query_log.py` manual `_CaptureHandler` boilerplate replaced by `caplog` via `capture_db_log` fixture.

---

## Filtered (4 pre-pass false-positives, all chunk-subagent confirmed)

| File:line | Pattern | Reason |
|---|---|---|
| `test_auth_hashing.py:26` | hardcoded_password | `password="legacy_password"` is the default arg to `_make_legacy_hash()` — a private helper that synthesises pre-v2.84.0 hashes for migration tests. Not a credential. |
| `test_bulk_scrape_race.py:4` | sleep_call | Line is inside the module docstring describing the *old buggy* `time.sleep(0.5)` pattern that the test exists to guard against. Prose, not code. |
| `test_bulk_scrape_race.py:132` | sleep_call | Comment in `test_demoted_job_state_only_resets_after_worker_exits`: `# … instead of busy-polling with time.sleep()`. The actual wait uses `worker_can_exit.wait(timeout=0.05)` (correct Event pattern). |
| `test_pass40_security.py:907,926` (×2) | sleep_call | Lines are inside `test_no_bare_time_sleep_in_jobs` — the literal `'time.sleep('` is a grep needle asserting job source files do NOT use bare sleep. Not an invocation. |
| `test_pass41_security.py:384` | hardcoded_password | Loop iterates over `('password: admin', "password='admin'", ...)` as needles asserting those credential strings do NOT appear in `database_init.py`. No secret committed. |

---

## Suggested roadmap shape (group by fix, not by file)

| Pass | Theme | Surface | One-liner saving |
|---|---|---|---|
| A | Sweep `app.config['TESTING'] = True` → `monkeypatch.setitem` across the 17 remaining sites; for module-scoped fixtures use snapshot + `try/finally` around `yield`. Add a `restore_app_config` autouse fixture in `conftest.py` to make this the default. | 8 files, 17 sites | Closes prior-synthesis theme #1 tail |
| B | Migrate `test_pass40_security.py` and `test_pass41_security.py` to `tests/_util.read_source()` / `read_module_source()`; remove the duplicated `_REPO_ROOT` boilerplate. Also remove the four `_REPO_ROOT = REPO_ROOT` dead aliases (`test_pass29_frontend.py:173`, `test_pass33_34_hardening.py:288`, `test_pass35_36_hardening.py:300`, `test_pass37_a11y.py:236`) and the dead `# noqa: F401` import in `test_pass32_hardening.py:15`. | 2 files, ~60 sites + 5 cleanups | Closes prior-synthesis theme #3 tail |
| C | Fix the CSP-nonce match contract in `test_security_headers.py:127–135`. This is the single most consequential finding — a real silent-failure mode for inline-script blocking. | 1 file, ~10 lines | New |
| D | Drop `test_graceful_shutdown.py:92` `elapsed < 1.5` and `:114` `elapsed < 1.0` (the alive-check / liveness assertions on the next line already pin the contract). | 1 file, 2 lines | Removes CI flake risk |
| E | Sweep source-grep tests for "vacuous when comment present" — slice via `slice_function()` or strip comments before assert. Eight sites: `test_pass35_36_hardening.py:290`, `test_pass37_a11y.py:105,136`, `test_pass35_36_hardening.py:163`, `test_pass33_34_hardening.py:273`, `test_pass35_36_hardening.py:68`, `test_pass40_security.py:175`, `test_pass41_security.py:97`. | ~6 files, 8 sites | Real-coverage uplift |
| F | Add IPv6 SSRF coverage (`test_input_hardening.py`) and the missing empty-list paths for `_pick_best_fallback/secondary` (`test_hybrid_scraper.py`). Both flagged in prior synthesis as open. | 2 files | Closes prior-synthesis coverage tail |
| G | Convert the 7 loop-over-N tests to `@pytest.mark.parametrize` (`test_pass40_security.py:100`, `test_pass41_security.py:1367,1395,683`, `test_security_headers.py:47,110`, `test_hltb_alt_titles.py`). Each becomes a self-naming pytest node. | scattered | Better diagnostics, no behaviour change |
| H | Fix `test_launcher_registry.py:81–82` single-baseline `time.time()` (twin of `test_gc_removes_exited_after_ttl`). One-line. | 1 file | One-liner |
| I | Migrate `test_pass31_migrations.py:183–187` `migrations.MIGRATIONS` to `monkeypatch.setattr` (sister `test_migrations.py:324` has the canonical comment explaining why). | 1 file, 1 site | One-liner |

Pass A is the biggest wedge (17 sites). Pass C is the highest-value individual fix. D, H, I are one-liners.
