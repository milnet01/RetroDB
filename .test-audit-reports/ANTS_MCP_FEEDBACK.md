# Ants MCP feedback — `test_audit_*` trio (from RetroDB /test-audit run 2026-05-17)

Please find below three issues encountered while running the `/test-audit` skill against a 65-test-file pytest project (RetroDB), using the Ants MCP `test_audit_partition` / `test_audit_brief` / `test_audit_synthesis_prompt` tools.

Project context: caller is Claude Code orchestrating the `/test-audit` skill end-to-end. Project root is a Flask app at `/mnt/Games/Scripts/Linux/RetroDB`. Tests live in `tests/*.py` (66 files). The trio is the supported critical path for that skill.

---

## Issue 1 — `test_audit_partition` ignores `test_globs`, walks the whole project

**Severity:** HIGH — produces non-test files as audit chunks; silently wastes 60–70% of subagent work auditing app source as if it were tests.

**Repro:**

```
mcp__ants__test_audit_partition(caller_cwd="/mnt/Games/Scripts/Linux/RetroDB", chunk_size=12)
```

**Observed:**

```json
{
  "test_globs": ["tests/**/*.py", "test_*.py", "*_test.py"],
  "total_files": 194,
  "chunks": [
    {"id": "c-001", "paths": [
      "/mnt/Games/Scripts/Linux/RetroDB/app.py",
      "/mnt/Games/Scripts/Linux/RetroDB/build_css.py",
      "/mnt/Games/Scripts/Linux/RetroDB/build_dist.py",
      "/mnt/Games/Scripts/Linux/RetroDB/build_js.py",
      "/mnt/Games/Scripts/Linux/RetroDB/config.example.py",
      "/mnt/Games/Scripts/Linux/RetroDB/config.py",
      "/mnt/Games/Scripts/Linux/RetroDB/install.py",
      ...
    ]},
    ...
  ]
}
```

The first ~10 chunks contain `routes/*.py`, `services/*.py`, `scraper/*.py` — application source, not tests. Test files start mid-chunk c-011 and run through c-017. **Note the contradiction:** `test_globs` correctly contains only test patterns (`tests/**/*.py`, `test_*.py`, `*_test.py`), but the chunker walks every `.py` in the project regardless.

The pre-pass findings even prove the bug — they're flagging `datetime.now()` in `routes/scraper.py` and `services/jobs/base.py` as "test determinism" smells when those are production code.

**Workaround:** `scope="path:tests"` produces the correct partition. So the underlying `test_globs` field is correct but unused in the default scope branch.

**Expected behaviour:** when `scope` is absent (default), the file walk should honour `test_globs`. Pre-pass findings should never include files outside `test_globs`.

**Spec check:** `/home/ants/.claude/skills/test-audit/references/framework-detection.md` defines the test globs as the canonical scope; the MCP correctly detects them, then ignores them.

---

## Issue 2 — `test_audit_synthesis_prompt` rejects `reports_dir` outside project root with an unhelpful error

**Severity:** MED — easy workaround but the friction is real, the error message is misleading.

**Repro:**

```
mcp__ants__test_audit_synthesis_prompt(
  caller_cwd="/mnt/Games/Scripts/Linux/RetroDB",
  partition_token="1a2613d5",
  reports_dir="/tmp/test-audit-retrodb-reports"
)
```

**Observed:**

```
{
  "code": "reports_dir_missing",
  "error": "test_audit_synthesis_prompt: reports_dir \"/tmp/test-audit-retrodb-reports\" does not resolve under project root",
  "ok": false
}
```

**Problems:**

1. Error code `reports_dir_missing` is the wrong name — the dir is not missing (it exists and has files in it). It's *rejected*. Use a code like `reports_dir_outside_project_root`.
2. The natural place to keep ephemeral reports is `/tmp` — the test-audit skill specifically says "Capture to `/tmp/test-audit-...`" at step 4. Forcing `reports_dir` under the project root collides with `.gitignore` semantics (now we have to add `.test-audit-reports/` to `.gitignore` or risk committing the reports).
3. The orchestrator's natural workflow — chunk subagents write to `/tmp` because that's outside the working tree — is incompatible with the synthesis step. We had to `cp /tmp/test-audit-retrodb-reports/*.md ./.test-audit-reports/` as a workaround.

**Expected behaviour:** either accept absolute `/tmp/…` paths (safer? optional `allow_outside_project=True`), or document the requirement explicitly in the tool description (the schema description doesn't mention it). At minimum, name the error correctly: this isn't "missing", it's "outside project root".

**Spec check:** `dimensions.md` does not require reports under project root; the test-audit skill workflow ("Capture to `/tmp/test-audit-timing-<sid>.txt`") suggests `/tmp` is expected.

---

## Issue 3 — `test_audit_synthesis_prompt` output is too large for the orchestrator to consume

**Severity:** HIGH — the tool's output is unusable as-is for orchestrator synthesis.

**Repro:** any 7-chunk run where chunk reports are 10–25 KB markdown each. After working around Issue 2 by moving reports into the project:

```
mcp__ants__test_audit_synthesis_prompt(reports_dir=".test-audit-reports", ...)
```

**Observed:**

```
Error: result (112,605 characters across 1 line) exceeds maximum allowed tokens.
Output has been saved to /home/ants/.claude/projects/.../mcp-ants-test_audit_synthesis_prompt-1779036533484.txt.
```

The tool fences every chunk report verbatim and returns one giant 112 KB single-line blob. For a 65-file pytest project with default chunk size, **the tool fails on its own happy path** — there's no overflow case here, just "ran 7 chunks at ~16 KB each = exceeds the result size limit."

**Problems:**

1. The fencing-with-`<chunk_report file=...>` defense against prompt injection (INV-8, per the tool description) is correct and important. But it can't help if the orchestrator can't read the output.
2. Saving to a file and asking the orchestrator to slice in 80 KB spans defeats the synthesis tool — at that point the orchestrator may as well read the 7 chunk reports directly (which is what I ended up doing).
3. Single-line output is also user-hostile for grep/eyeball debugging. Multi-line markdown would render in the saved file.

**Suggestions (any one would help):**

- Return only a *summary* (per-dimension counts, top-N severities, file references) with a path/handle to the full fenced bundle for the orchestrator to fetch on demand. The fenced bundle is still needed for the *final* synthesis-LLM call, but not for the orchestrator's first read.
- Support a `mode` parameter: `mode="summary"` (default) → counts + finding pointers; `mode="full"` → the current behaviour.
- Add a `limit` / `offset` for chunked retrieval (same pattern as `test_audit_partition`).
- At minimum, emit multi-line markdown rather than a single line so the saved-file workaround is greppable.

**Spec check:** ANTS-1397 says Phase 3 returns "a single synth prompt + per-dimension summaries" — the per-dimension summaries are present in the saved file but inaccessible to the orchestrator. The "single synth prompt" component is the part that should be deliverable in tool-result space; the verbatim chunk bundle should be a fetchable artifact, not the response body.

---

## Summary

| # | Issue | Severity | Workaround in current run |
|---|---|---|---|
| 1 | `partition` default scope walks whole project, ignoring `test_globs` | HIGH | `scope="path:tests"` |
| 2 | `synthesis_prompt` rejects `/tmp` reports dir with wrong error code | MED | `cp` reports under project root |
| 3 | `synthesis_prompt` returns oversized single-blob output | HIGH | Skip the tool; orchestrator read per-chunk markdown directly |

All three issues are reproducible against the head of RetroDB (`main` @ commit `a624f0e`, working tree dirty per `git status`). Happy to provide tool traces if needed.

If issue 3 is fixed but issue 1 isn't, the audit *appears* to succeed but produces mostly noise — chunks of app source code being audited under test-dimension prompts. So fix 1 first.
