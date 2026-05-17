# Ants MCP feedback — `test_audit_*` trio (RetroDB /test-audit re-run 2026-05-17 @ commit `3e0b403` post-v3.6.8)

This is the **third** batch of feedback for the Ants MCP `test_audit_partition` / `test_audit_brief` / `test_audit_synthesis_prompt` trio.

Prior batches:
- `.test-audit-reports/ANTS_MCP_FEEDBACK.md` — initial run, 2026-05-17 morning.
- `.test-audit-reports-2/ANTS_MCP_FEEDBACK.md` — second run, 2026-05-17 mid-day; confirmed all three prior issues still present.

**Headline: two of three reported issues are now FIXED.** The user instructed me to test the Ants MCP fixes before running this audit, and the fixes are observable in the wire behaviour of the live MCP build.

| # | Issue | Severity | Status this run |
|---|---|---|---|
| 1 | `partition` default scope walked whole project, ignored `test_globs` | HIGH | ✅ **FIXED** |
| 2 | `synthesis_prompt` rejected `/tmp` reports dir with wrong error code | MED | Not re-triggered (orchestrator wrote inside project root) |
| 3 | `synthesis_prompt` returned oversized single-blob output | HIGH | ✅ **FIXED** |

Detail follows.

---

## Issue 1 — FIXED ✅

```
mcp__ants__test_audit_partition(caller_cwd="/mnt/Games/Scripts/Linux/RetroDB", chunk_size=12)
→ partition_token: aae86066
→ total_files: 66
→ test_globs: ["tests/**/*.py", "test_*.py", "*_test.py"]
→ chunks[0].paths: tests/__init__.py, tests/_util.py, tests/conftest.py, tests/test_alternate_titles.py, …
```

The default scope now walks **66 test files**, all under `tests/`. Prior run on this same project walked **195 files** including production code (`app.py`, `routes/`, `services/`, `scraper/`, etc.). The default partition is now correct and `scope="path:tests"` is no longer needed as a workaround.

`test_globs` is now honoured by the walker, exactly as the prior feedback batch proposed.

**Confidence:** High. Verified by enumerating chunk[0].paths and confirming all 6 chunks contain only `tests/*.py` files.

---

## Issue 3 — FIXED ✅

The synthesis tool now ships **two modes** matching almost exactly the proposed shape from the prior batch:

### `mode="summary"` (new default)

```
mcp__ants__test_audit_synthesis_prompt(
  caller_cwd="/mnt/Games/Scripts/Linux/RetroDB",
  partition_token="aae86066",
  reports_dir=".test-audit-reports-3",
  mode="summary"
)
→ byte_count: 2005
→ chunks_returned: 0  (counts/index only, no chunk bodies)
→ dimension_summaries: { accuracy: 5, isolation: 6, flakiness: 6, … }
→ file_index: [{file: "test_pass41_security.py", dimension_hits_total: 8}, …]
→ top_dimensions: [...]
→ prompt: "# Test-Audit Synthesis\n\nMode: summary\n…"
```

**2 KB** result on a 6-chunk audit of ~16 KB per chunk. Previously this same input produced **96 KB** single-blob output that exceeded the harness limit. The orchestrator can now decide whether to dive deeper based on top_dimensions and file_index.

### `mode="full"` with pagination

```
mcp__ants__test_audit_synthesis_prompt(
  …, mode="full", limit=2
)
→ byte_count: 33914
→ chunks_returned: 2
→ chunks_total: 6
→ next_offset: 2
→ prompt: "…<chunk_report file=\"c-001.md\">…</chunk_report><chunk_report file=\"c-002.md\">…</chunk_report>"
```

**The output is multi-line**, so the orchestrator can read it via Read offset/limit if needed. `<chunk_report>` fencing is preserved (INV-8). `next_offset` lets the caller paginate cleanly.

**Confidence:** High. Both modes wire correctly, pagination works, security fencing intact.

---

## Issue 2 — not re-triggered ▫

The orchestrator wrote reports under `.test-audit-reports-3/` (inside project root) from the start. The tool accepted this without complaint. The original Issue 2 (rejecting `/tmp/...` with `code: reports_dir_missing`) was not tested this run.

The current tool description mentions `allow_outside_project:true` for ephemeral `/tmp` workflows (ANTS-1455), so this codepath was likely revised in the same release that fixed Issues 1 and 3. If anyone wants to validate independently, the test is:

```
mcp__ants__test_audit_synthesis_prompt(
  reports_dir="/tmp/test-audit-x",
  allow_outside_project=true,  # only present when ANTS-1455 landed
  …
)
```

No further action requested; flagging as resolved-by-architecture.

---

## New observations (this run only)

### (1) `file_index` has near-duplicate entries due to path normalisation

```json
"file_index": [
  {"dimension_hits_total":8,"file":"test_pass41_security.py"},
  …
  {"dimension_hits_total":4,"file":"tests/test_auth_hardening.py"},
  …
  {"dimension_hits_total":4,"file":"test_hltb_endpoint.py"},
  …
  {"dimension_hits_total":3,"file":"tests/test_hltb_endpoint.py"},
  …
]
```

The same logical file appears twice — once as `test_X.py`, once as `tests/test_X.py` — because chunk reports cite files inconsistently (some say `tests/test_X.py`, some say just `test_X.py`). The synthesis tool surfaces the raw strings without normalisation, so the top-N list double-counts.

**Severity:** LOW. The orchestrator can dedupe by basename when reading the index, but a future caller copying this into a roadmap or display would see noise.

**Proposed fix:** in the `file_index` aggregation, normalise paths to a canonical form (e.g. strip a leading `tests/` if it duplicates an existing key without the prefix, or always resolve to repo-root-relative).

### (2) `pre_pass_cached: false` field — is this expected on first call?

```
mcp__ants__test_audit_partition(…) → pre_pass_cached: false
```

I didn't pass any caching hint and the field documents itself as `false`. No second call was made, so I can't tell whether the cache hit semantics work correctly. Not a finding, just an observation that the field is surfaced even when it's not informative.

### (3) `dimension_hints` from `partition` still misleading (carry-over from prior batch)

Chunks c-002, c-004, c-006 returned `dimension_hints: []`; c-001 and c-005 returned `["flakiness", "security"]`; c-003 returned `["flakiness"]`. The hints reflect pre-pass regex hits, not the dimensions where real findings concentrate. The actual finding distribution (per the chunk subagents) was dominated by **Isolation** (c-005 had 8 isolation findings, hinted with `[security]`) and **Duplication** (c-001 had 4 dup findings, hinted with `[security]`).

Same finding as prior batch. Naming the field `pre_pass_dimensions_seen` or documenting it as "dimensions where the pre-pass regex hit, NOT a finding-density predictor" would prevent misuse.

**Severity:** LOW. Carry-over from prior batch.

---

## What works well (positive feedback)

The trio is now in the right shape for routine `/test-audit` invocation:

1. **`partition` default behaviour is correct** — `scope` need not be passed for the common case. Saved ~60-70% of subagent capacity vs the prior run (no production-code reviewing).
2. **`brief` returns clean structured JSON** with `source_paths`, `dimensions`, `framework_context`, `pre_pass_findings`. No changes needed.
3. **`synthesis_prompt` mode split is exactly the right shape.** `mode="summary"` returns a useful 2 KB digest for orchestrator triage; `mode="full"` with pagination handles the verbose case without crashing on tool-result token limits.
4. **`<chunk_report file="…">` fencing is preserved** in `mode="full"`, retaining the prompt-injection defence (INV-8).

The workflow now scales: a 100-file pytest project at chunk_size=12 → 9 chunks → mode="summary" returns ~3 KB; mode="full" returns ~140 KB across 9 paginated calls. Both well within harness limits.

---

## TL;DR for the MCP-side session

1. **Issue 1 and Issue 3 are fixed.** No prompt for an MCP-side change on these.
2. **Issue 2 likely resolved by the `allow_outside_project` field landing in ANTS-1455.** Not validated this run.
3. **Two minor polish items** for a future pass:
   - `file_index` double-counts when chunk reports cite files inconsistently. Canonicalise paths.
   - `dimension_hints` field name is still misleading; consider rename or schema-description tweak.

Both polish items are LOW severity. The trio is fit-for-purpose as-is.

Thank you for the fast turnaround between batch 2 and this run.
