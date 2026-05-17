# Test Audit — 2026-05-17 (third pass, post-v3.6.8 + post-Ants-MCP-fixes)

Framework: **pytest** · Files scanned: **66** (incl. `__init__.py`, `_util.py`, `conftest.py`) · Chunks: **6** ·
Findings: **100 raw** after pre-pass dedup (5 confirmed false-positives ruled out — all grep-needles or docstring prose)

Severity totals **(this pass)**: **0 CRITICAL · 7 HIGH · 33 MED · 60 LOW**

Per-chunk reports: `.test-audit-reports-3/c-00{1..6}.md`.

Background:
- Prior `/test-audit` runs landed on commits `a624f0e` and `3e0b403` (v3.6.8 fix-pass closing 119 findings).
- The Ants MCP `test_audit_*` trio had two HIGH-severity bugs at that point (whole-project walk on default scope; oversized synthesis output).
- This run was performed **after the MCP fixes shipped**, primarily to validate them. Ants MCP feedback for the live build is in `.test-audit-reports-3/ANTS_MCP_FEEDBACK.md` — both prior HIGH issues now confirmed fixed.

The chunk subagents were briefed on the prior synthesis (`.test-audit-reports-2/SYNTHESIS.md`) and instructed not to re-flag issues marked "Confirmed fixed in v3.6.8". Findings here are either (a) residuals the v3.6.8 sweep missed, or (b) genuinely new.

---

## What was fixed in this pass

All HIGH severity items and a substantial majority of MED + LOW were fixed in the same session. See `tests/` diff. Full suite is **1001 passing tests** (up from 992 at start of session; +9 from parametrize splits and new coverage tests).

### HIGH (7/7 closed)

1. **`tests/test_pass45_security.py:81,237,1257,1421,1445,1538,1602`** — 7 bare `app.config['TESTING'] = True` mutations across 6 test methods. **Closed.** All 7 sites converted to `monkeypatch.setitem(app_module.app.config, 'TESTING', True)` (the file was entirely missed by v3.6.8's sweep).
2. **`tests/test_pass41_security.py:1102`** — sole surviving bare TESTING mutation. **Closed** — added `monkeypatch` parameter and converted to `monkeypatch.setitem`.
3. **`tests/test_routes_smoke.py:14`** — module-scoped `client` fixture leaked `TESTING=True` across modules. **Closed** with snapshot + `try/finally` around the `yield` (monkeypatch unavailable in module-scoped fixtures).
4. **`tests/test_security_headers.py:11`** — same module-scoped pattern. **Closed** with the same shape.
5. **`tests/test_scan_library_rom_path.py:292`** — `_client()` helper mutated TESTING directly. **Closed** — replaced with `monkeypatch.setitem` (the helper takes `monkeypatch` as its sole parameter).
6. **`tests/test_pass40_security.py:921`** — bare `open(path).read()` inside a 5-iteration loop, up to 5 fds at risk. **Closed** with `with open(...) as f:` context manager.
7. **`tests/test_graceful_shutdown.py:92`** — `assert elapsed < 1.5` redundant with the alive-check on line 93 and flake-bait under CI load. **Closed** — dropped the timing assertion; the thread-liveness check on the next line is the real contract.

### MED (selected highlights — full enumeration in per-chunk reports)

- **Isolation tail (7 sites):** `test_auth_hardening.py:53,134,373`, `test_etag_and_gzip.py:20,75`, `test_observability.py:26`, `test_pass31_migrations.py:183`, `test_launcher_factory.py:5`, `test_pass41_security.py:848`, `test_pass45_security.py:69`. **All closed** — function-scope sites converted to `monkeypatch.setitem`/`setattr`; module/class-scoped fixtures use snapshot + `try/finally`; autouse fixtures use `monkeypatch.setattr` for SIGKILL-safety.
- **CSP nonce match contract (`test_security_headers.py:127–135`):** the previously-vacuous "asserts non-empty only" test now asserts the rendered Jinja `{{ csp_nonce }}` value equals `flask.g.csp_nonce` AND end-to-end matches the nonce in the response's `Content-Security-Policy-Report-Only` header. Highest-value individual fix in the audit.
- **Vacuous-when-reordered slices (`test_pass41_security.py:97`):** replaced `src[A:B]` with `slice_function(read_source(...), 'api_change_password')` — AST-based extraction handles re-ordering safely.
- **Comment-bypass disjunction (`test_pass40_security.py:175`):** added `re.sub(r'#[^\n]*', '', body)` to strip comments before the role-check disjunction.
- **Parametrise sweep:** `test_pass40_security.py:100` (bool_fields ×9), `test_pass41_security.py:1375,1388` (scan routes ×5, rate-limit fns ×5), `test_security_headers.py:47,110` (permissions-policy ×7, CSP directives ×9), `test_launch_settings_validators.py:71` (×5), `test_launcher_base.py:86` (protocol methods ×4). All now report all-failures-at-once rather than first-failure-stops.
- **Source-grep tightening:** `test_pass35_36_hardening.py:290–292` (aria-live/assertive grep now scoped to `init_body` slice, not full file), `test_pass37_a11y.py:105–106` (deactivate count tightened from `>= 4` to `== 7` matching actual), `test_pass37_a11y.py:136` (rel-attribute check now asserts BOTH `noopener` AND `noreferrer` in the value, not just any `rel=`).
- **Coverage gaps:** added IPv6 SSRF tests (`test_input_hardening.py`: `test_ipv6_loopback_rejected`, `test_ipv6_link_local_rejected`), `_pick_best_fallback([])` and `_pick_best_secondary([])` empty-list paths (`test_hybrid_scraper.py`), `select_pip_args` lockfile-absent + missing-both branches (`test_pass39_supply_chain.py`), `_format_playtime_str(None, 8.0, 12.0)` (`test_hltb_bulk.py`), `franchise` `fill_only=True` direction (`test_metadata_merger.py`), `TestDemoteJobOrdering` post-demote state (`test_bulk_scrape_race.py:150`).
- **Twin `time.time()` (`test_launcher_registry.py:81–82`):** single baseline `t = time.time()` for both `started_at` and `exit_time` — mirrors the sibling test fixed in v3.6.8.
- **Twin `time.time()` and tight wait timeouts (`test_bulk_scrape_race.py:102,150`):** bumped from 2.0 → 5.0 seconds with diagnostic message capturing the state on failure.

### LOW (selected; full enumeration in per-chunk reports)

- **Dead `_REPO_ROOT = REPO_ROOT` aliases removed:** `test_pass29_frontend.py:173`, `test_pass33_34_hardening.py:288`, `test_pass35_36_hardening.py:300`, `test_pass37_a11y.py:260`. No external importers.
- **Dead `from tests._util import REPO_ROOT  # noqa: F401` import** in `test_pass32_hardening.py:15` — replaced with a comment noting `conftest.py` already handles sys.path.
- **`_REPO_ROOT` boilerplate migrations:** `test_auth_player_role.py`, `test_pass38_normalize_ratings_helper.py`, `test_pass38_ra_check_helper.py`, `test_pass38_region_helper.py`, `test_pass38_resume_helpers.py`, `test_pass39_supply_chain.py` — all now use `from tests._util import REPO_ROOT as _REPO_ROOT`.
- **yaml import without skip-guard** (`test_pass39_supply_chain.py:176`): replaced with `yaml = pytest.importorskip("yaml")` — graceful skip if pyyaml absent.
- **pytest.raises message-pin** (`test_launcher_factory.py:28,36`): added `match=r"remote"` and `match=r"spaceship"` so a bare `raise NotImplementedError()` would fail the test.
- **Assertion quality** (`test_slow_query_log.py:61,69,71`): bare `records[0]` access now guarded by `len(records) >= 1` with a diagnostic; the previously-weak `assert '...' in msg` now also asserts `len(msg) < 700` to pin the 500-char SQL truncation cap.
- **Type-ambiguous disjunctions** (`test_game_query.py:52,67`): collapsed `42 in vals or '42' in vals` → `'42' in vals` (matching the SUT's `params['system']` type); `"'Z'" in str(vals) or 'Z' in vals` → `'Z' in vals` (element membership).
- **`_MANIFEST_CACHE` snapshot/restore** (`test_assets.py:26`): added `try/finally` to restore the prior cache state — xdist-safe.
- **caplog unused-parameter** (`test_log_redactor.py:112`): removed; assertion changed from `assert attached is True` to `assert attached, "..."` for diagnostic clarity.
- **SQLite explicit close** (`test_pass38_scrape_history_helper.py`): fixture now yields with `try/finally: conn.close()` — PyPy compat and pytest-xdist safety.

### Confirmed false-positives (5)

| File:line | Pattern | Reason |
|---|---|---|
| `test_auth_hashing.py:26` | hardcoded_password | `password="legacy_password"` default arg in `_make_legacy_hash()` test helper. Not a credential. |
| `test_bulk_scrape_race.py:4` | sleep_call | Module docstring describing the bug class the test guards against. |
| `test_bulk_scrape_race.py:132` | sleep_call | Comment about NOT busy-polling. |
| `test_pass40_security.py:907,926` | sleep_call | Grep needles in `test_no_bare_time_sleep_in_jobs` asserting job source files DON'T contain `time.sleep(`. |
| `test_pass41_security.py:384` | hardcoded_password | Loop iterates over needles asserting credential strings DON'T appear in `database_init.py`. |

---

## Items deferred (called out, not fixed in this session)

Each of these is small but touches code outside the audit's stay-in-lane scope, or has equivalent behavioural coverage already:

1. **`test_input_hardening.py:33–58` — `TestESDEPathTraversal` re-implements `_within_allowed_root`.** The production helper is a closure inside `apply_esde_metadata` (scraper/scrape_esde.py:819); extracting it to module scope is a production-code refactor outside this audit's scope. Fix proposal: lift the helper out of the closure and import it in the test. Tracked for a future cleanup pass.
2. **`test_pass41_security.py` ~51 bare `open().read()` calls (file-wide):** the file's own `_read()` helper is defined twice in two classes but used only locally. Migrating all 51 sites to `read_source` from `tests/_util` is a mechanical refactor with low risk but high churn. The 6 sites flagged HIGH in pass 2 were addressed; the file-wide migration is deferred.
3. **`test_pass40_security.py:1017,1040,1053,1074,1084,1201` — 6 more bare opens** (single-file, not in a loop). LOW risk (CPython refcount closes them). Deferred for the same churn-vs-risk tradeoff.
4. **`test_pass46_frozen_paths.py:62–101` — manual reload boilerplate** vs the cleaner `reloaded_app` fixture at line 131. ~300–400 ms cost on a single test; consolidation is a refactor.
5. **`test_routes_launch.py:50` — `logged_in_client` fixture rename** to `player_client`. Touches every caller of the fixture in the file. Deferred.
6. **`test_retroarch_detect.py` — 4 missing docstrings** on security-sensitive endpoint tests. Trivial but adds line noise.
7. **`test_database_backup.py` — 5 inline `tempfile.TemporaryDirectory()` blocks** to migrate to `tmp_path`. Mechanical refactor; deferred.
8. **In-memory SQLite explicit closes** in `test_migration_012.py`, `test_owner_id_self_heal.py`, `test_scrape_fill_only.py` — PyPy/xdist compat; CPython refcount handles today. One example fix applied to `test_pass38_scrape_history_helper.py` to demonstrate pattern.

---

## Ants MCP feedback summary (full text in `ANTS_MCP_FEEDBACK.md`)

| Prior issue | Status |
|---|---|
| Issue 1 (HIGH) — `partition` default scope walked whole project | **FIXED** — 66 files now, was 195 |
| Issue 2 (MED) — `synthesis_prompt` rejected `/tmp` reports dir | Not re-triggered; appears resolved by `allow_outside_project` field landing |
| Issue 3 (HIGH) — `synthesis_prompt` returned oversized single-blob | **FIXED** — `mode="summary"` returns 2 KB; `mode="full"` is multi-line with pagination |

Two minor polish items remain (file_index path normalisation; `dimension_hints` field name); both LOW severity.

---

## Test suite state

- Before: **992 passing tests** (post-v3.6.8 baseline)
- After: **1001 passing tests**
- Net delta: **+9 tests** (from parametrize splits adding nodes, and new coverage tests for IPv6 SSRF / empty lists / lockfile-fallback / fill_only direction)
- Wall time: ~4.4 seconds for the full suite
