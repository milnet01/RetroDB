# Test Audit — 2026-05-17 (run #3, post-v3.6.13)

Framework: pytest · Files scanned: 66 · Suite size: 1001 passing tests

## Raw counts (6 chunks)
| Chunk | Files | Raw | CRIT | HIGH | MED | LOW | INFO |
|---|---|---|---|---|---|---|---|
| c-001 | 12 | 18 | 0 | 2 | 7 | 8 | 1 |
| c-002 | 12 | 22 | 0 | 4 | 10 | 7 | 1 |
| c-003 | 12 | 24 | 0 | 2 | 12 | 9 | 1 |
| c-004 | 12 | 28 | 0 | 2 | 15 | 11 | 0 |
| c-005 | 12 | 23 | 0 | 1 | 9 | 13 | 0 |
| c-006 | 6  | 18 | 0 | 1 | 9 | 8 | 2 |
| **Total** | **66** | **133** | **0** | **12** | **62** | **56** | **5** |

Plus **8 deferred items** from the v3.6.9 fix-pass.

## Triage outcome

**False positives confirmed (7):**
- c-001 pre-pass — `legacy_password` is a fixture; `time.sleep` references in `test_bulk_scrape_race.py` are in docstring/comment
- c-003 pre-pass — `time.sleep(0.05)` in `_poll_exited` is a bounded poll helper
- c-005 pre-pass — `time.sleep(`, `password: admin` string literals used as grep needles in security tests
- c-004 — 2026-04-27 hardcoded date is intentional (clock-pin test)
- c-006 — fake_admin dict is intentional auth-bypass fixture

**Dismissed as no-action (~8):** style-only naming nits where the existing form is clear; INFO confirmations; intentional patterns explicitly documented in source (e.g. file headers of `test_pass40_security.py`).

**Cross-chunk dedup (4 patterns):**
1. Inline `_REPO_ROOT` boilerplate — present in 9 files; `tests/_util.py` exists exactly for this.
2. Bare `open(path).read()` without context manager — ~44 sites across 4 files; `tests/_util.read_source()` exists for this.
3. `src.index("def fn_name")` source-locator fragility — 18 sites across 3 files; `tests/_util.slice_function` exists.
4. Comment-as-proof anti-pattern — 2 sites assert `"Pass XX.Y"` string in source as evidence of behavioural change.

## Actionable list (post-triage, prior calibration anchor: 92 actionable / 100 raw)

Estimated actionable: **~98** (12 HIGH + 49 MED + 29 LOW + 8 deferred from v3.6.9).

See per-chunk reports for full detail. Fix-pass below operates on these chunks in parallel.
