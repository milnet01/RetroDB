# Ants MCP feedback — `test_audit_*` trio (RetroDB /test-audit re-run 2026-05-17 @ commit `3e0b403` post-v3.6.8)

This is the **second** batch of feedback for the Ants MCP `test_audit_partition` / `test_audit_brief` / `test_audit_synthesis_prompt` trio. Prior batch is at `.test-audit-reports/ANTS_MCP_FEEDBACK.md` and was filed on the first audit run (2026-05-17 earlier, against commit `a624f0e`). All three issues from that batch were reproduced again on this second run, **so none of them have been fixed in the intervening MCP releases yet** (or, more cautiously: still reproduces against whichever MCP build is wired into this Claude Code session).

The summary table at the bottom of the prior document remains accurate:

| # | Issue | Severity | This run still hits it? |
|---|---|---|---|
| 1 | `partition` default scope walks whole project, ignoring `test_globs` | HIGH | **Yes — same numbers (195 files walked, 17 of 17 chunks half production code).** |
| 2 | `synthesis_prompt` rejects `/tmp` reports dir with wrong error code | MED | **Not re-triggered** — orchestrator wrote reports directly under `<project>/.test-audit-reports-2/` to pre-empt the rejection. Issue likely still present but not validated this run. |
| 3 | `synthesis_prompt` returns oversized single-blob output | HIGH | **Yes — 96,273 chars on 6 chunks of ~14 KB markdown each.** Same root cause: every chunk report is fenced verbatim and returned as one single-line blob that exceeds tool-result token limits. The orchestrator skipped the tool entirely and did the synthesis by Reading each chunk report directly. |

Below: fresh repros from this run for confirmation. Anything in the original doc that I don't repeat here is unchanged.

---

## Issue 1 (still HIGH) — fresh repro

```
mcp__ants__test_audit_partition(caller_cwd="/mnt/Games/Scripts/Linux/RetroDB", chunk_size=12)
→ partition_token: 8d5c0927
→ total_files: 195
→ test_globs: ["tests/**/*.py", "test_*.py", "*_test.py"]
→ chunks[0].paths: ["…/app.py", "…/build_css.py", "…/build_dist.py", "…/build_js.py", "…/config.example.py", "…/config.py", "…/install.py", "…/install_gui.py", "…/installer_core.py", "…/log_manager.py", "…/platform_utils.py", "…/routes/__init__.py"]
```

`test_globs` is still set correctly. The walker still ignores it.

Pre-pass findings in the same response are populated for `routes/`, `services/`, `scraper/`, `log_manager.py`, etc. — production code being flagged for `datetime_now` (a test-determinism smell). E.g.:

```
"c-002": [
  {"dimension": "determinism", "file": ".../routes/achievements.py", "line": 251, "pattern_id": "datetime_now"},
  {"dimension": "determinism", "file": ".../routes/auth.py", "line": 103, "pattern_id": "datetime_now"},
  ...
]
```

This is non-sensical (a SUT using `datetime.now()` is not a test-quality finding) and confirms that the pre-pass walks the same overly-broad file set.

Workaround applied again: `scope="path:tests"` produces the correct partition (6 chunks of 66 files, all under `tests/`).

The cost of this bug to the caller — every `/test-audit` run on every pytest project — is that the orchestrator must either know the magic `scope="path:tests"` invocation (undocumented in the tool description), or burn 60–70% of subagent capacity reviewing production code under test-dimension prompts.

**Proposed fix** (unchanged from prior batch): when `scope` is not specified, the default walk should honour `test_globs`. The detection logic that populated `test_globs` is correct; the file-walking path is the broken half. Either rename `scope` semantics so the default behaviour is `scope="auto"` → use `test_globs`, or have the walker consult `test_globs` unconditionally.

---

## Issue 3 (still HIGH) — fresh repro

```
mcp__ants__test_audit_synthesis_prompt(
  caller_cwd="/mnt/Games/Scripts/Linux/RetroDB",
  partition_token="dc3e23ce",
  reports_dir=".test-audit-reports-2"
)
→ Error: result (96,273 characters across 1 line) exceeds maximum allowed tokens.
  Output has been saved to .../tool-results/mcp-ants-test_audit_synthesis_prompt-1779040536285.txt.
```

This run had **6 chunks** (vs 7 in the prior run because the orchestrator used `scope="path:tests"` from the start). Per-chunk reports averaged ~16 KB markdown. Total fenced output: 96 KB, single line. Down 15 KB from last run, still 2× the tool-result limit.

The harness even prints an explicit instruction for the orchestrator: *"Slice the file in ~80,000-char spans via python … in 80,000-char spans until you have read 100% of it."* That instruction is correct for the orchestrator's workaround path, but it amounts to "the tool's output is too big — read it yourself in chunks." Which is to say, the synthesis tool no longer serves its stated purpose: any project with more than ~5 chunks of ~16 KB reports will trip this.

**Empirical sizing data** (in case it informs the fix):

| Run | Chunks | Avg report size | Tool output |
|---|---|---|---|
| First (2026-05-17 morning) | 7 | ~16 KB | 112,605 chars |
| Second (this run) | 6 | ~16 KB | 96,273 chars |

The relationship is `~16 KB × chunks + minor overhead`. With the harness limit at ~80 KB, the breakpoint is **5 chunks**. Any pytest suite of ~60+ files at `chunk_size=12` will exceed it. A `chunk_size=18` config knob (allowed by the schema, `[4, 30]`) would help marginally — 4 chunks of ~25 KB each is still ~100 KB output. The structural problem is single-blob fencing, not chunk count.

**Proposed fix** (refined from prior batch):

The synthesis tool's real value is the **fencing-with-`<chunk_report file="…">` tags for prompt-injection defence (INV-8)**. That value should be preserved. The current API conflates "fence the bundle" with "return the bundle inline" — split them:

1. **`mode="summary"` (new default)** — return only:
   - Per-dimension finding counts across all chunks.
   - The top-N severities (file:line + 1-line problem each).
   - A path/handle (e.g. `synth_bundle_path: "/tmp/.../bundle.md"` or `synth_bundle_token: "abc123"`) the orchestrator can fetch on demand.
2. **`mode="full"` (opt-in)** — current behaviour, but emit multi-line markdown rather than single-line. Even at 100 KB, multi-line content is greppable / Read-with-offsetable; the current single-line blob is opaque to every tool.
3. **`mode="bundle_only"` (for downstream LLM calls)** — return just the fenced bundle without the synth prompt prefix; the orchestrator inlines into its own prompt.

Even just option 2 alone (multi-line) would let the orchestrator slice with Read's `offset`/`limit`, which is the natural Claude Code workflow. Single-line forces the awkward `python3 -c "print(...read()[A:B])"` workaround in the harness's own instruction text.

**Defensive note:** the `<chunk_report file="…">` fencing should NOT be relaxed in any of these modes. It's the right defence and it's worth the size overhead — the fix is to deliver the fenced bundle via a fetch handle, not to drop the fence.

---

## Issue 2 — not re-triggered this run

Prior repro forced `reports_dir="/tmp/test-audit-retrodb-reports"` and got back `code: reports_dir_missing` (wrong error name; the dir existed but was rejected for being outside the project root).

This run sidestepped the issue by writing reports to `.test-audit-reports-2/` under project root from the start, which the tool accepts without complaint. So **the tool is consistent with what it accepts**; the issue is purely about (a) the error code name being misleading and (b) the constraint not being mentioned in the tool description.

If Issue 1 and Issue 3 are fixed but Issue 2 is left as-is, the friction is mostly invisible (orchestrators learn to write reports under project root). If a future fix lets `reports_dir="/tmp/…"` work, the error code at minimum should rename: `reports_dir_outside_project_root` rather than `reports_dir_missing`.

---

## New observation (this run only) — `dimension_hints` from `partition` are noisy

Each chunk's `dimension_hints` array in the partition response reflects the pre-pass findings within that chunk. When the pre-pass walks production code (Issue 1), the hints inherit that noise. Even after the `scope="path:tests"` workaround, the hints for test-file chunks are sparse and mostly populated by `flakiness` (any test file with a sleep_call hit) or `security` (any test with a hardcoded_password hit). For example:

```
c-001 → ["flakiness", "security"]
c-002 → []
c-003 → ["flakiness"]
c-004 → []
c-005 → ["flakiness", "security"]
c-006 → []
```

For the four chunks with non-empty hints, the actual finding distribution across the full 18 dimensions was nothing like the hint suggested. c-005's hints were `["flakiness", "security"]` but its biggest theme was **Isolation** (4 findings including 2 HIGH). c-001 was hinted `["flakiness", "security"]` but had zero security findings and a single LOW flakiness; its real theme was **Duplication** (3 findings).

This isn't a bug per se (the hints are about pre-pass coverage, not predicted findings), but the field name `dimension_hints` is misleading — they're not hints, they're "dimensions that pre-pass regexes happened to hit in this chunk." A subagent that read these hints as "focus on these dimensions" would mis-allocate effort. Either rename the field (`pre_pass_dimensions_seen`?) or document the semantic gap in the schema description.

This is LOW severity; called out for completeness so the MCP team can decide if it warrants a tweak.

---

## What still works well (positive feedback)

- `test_audit_brief` returns clean structured JSON every time. No issues with that tool in either run.
- `test_audit_partition` with `scope="path:tests"` produces correct partitions in milliseconds.
- The `pre_pass_findings_by_chunk` field is genuinely useful when scoped correctly — the orchestrator can include it in the subagent brief as "confirm or refute" hints, which several chunk reports cited as "ruled out as docstring prose" with one-line justifications. This is exactly the right shape for a pre-pass.
- The `partition_token` round-trip between phases is clean and obviates re-walking.
- The `dimensions_active` array correctly reflects the full 18 dimensions even when `dimensions="auto"` is left as the default.

These three tools are valuable shape for the workflow; the issues above are about (a) one bug, (b) one architectural decision (whole-blob output) that doesn't scale past a small suite, and (c) one documentation/error-message polish.

---

## TL;DR for the MCP-side session

1. **Fix Issue 1.** The walker ignoring `test_globs` is the single biggest cost to every `/test-audit` invocation. Without this fix, the trio's default behaviour is wrong on every project that has a `tests/` directory. The workaround (`scope="path:tests"`) is undocumented and not discoverable from the tool description.
2. **Fix Issue 3.** The synthesis tool fails on its own happy path for any suite > ~5 chunks. Either split into `mode="summary"` / `mode="full"` or return the bundle as a fetch handle. **Preserve the `<chunk_report file=…>` fencing** — the security shape is right; the delivery shape is the problem.
3. **Polish Issue 2's error code name** if the rest of that codepath isn't being changed.
4. **Document the `dimension_hints` semantics** or rename the field.

If forced to prioritise: **Issue 1 first.** Until it's fixed, Issue 3 only matters once you've worked around Issue 1 — and the cost of Issue 1 alone (60–70% wasted subagent capacity per run) dominates Issue 3 (which the orchestrator can route around by Reading the per-chunk reports it wrote anyway).

The prior feedback document at `.test-audit-reports/ANTS_MCP_FEEDBACK.md` has the same severity ordering. Two runs, same conclusion.
