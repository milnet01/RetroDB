# Audit Hygiene — reducing false-positive rate on `/audit`

Standalone document intended for the Claude Code session / maintainer
responsible for the **Project Audit tool** (ants-audit) and the `/audit`
skill configuration.  Written from the perspective of a project
(RetroDB) whose recent audit runs produced 228 raw findings with only
~3 actionable (~1.3% signal rate).

The goal is not to silence findings — it is to make the audit tool
more useful by cutting noise that is already documented as accepted by
the project's threat model.

---

## Context

RetroDB at `/mnt/Storage/Scripts/Linux/RetroDB` is a single-user
localhost Flask + SQLite retro-gaming ROM library manager.  It
maintains three project-local config files that document accepted noise:

- `.semgrep.yml` — threat model header (lines 40-80) + list of 13
  upstream rule IDs to exclude, with one-line anchors explaining WHY
  each fires but isn't a bug.
- `.gitleaks.toml` — allowlist for `logs/`, `data/*.json` tokens,
  admin-editable settings files.
- `pyproject.toml` `[tool.ruff.lint.ignore]` — project-accepted Ruff
  S-codes (bandit equivalents), mirroring the semgrep excludes.

Three consecutive audits (2026-04-20, 2026-04-21 ×2) produced
**0 actionable findings**.  The threat model is stable; the noise
categories are known.  What's missing is tool-side orchestration that
actually reads these files.

---

## The noise breakdown (from 2026-04-21 run)

| Tool | Raw | Documented-accepted | Actionable |
|------|-----|--------------------|------------|
| Semgrep | 74 | 70 (excluded in `.semgrep.yml`) | ~4 |
| Bandit | 60 | 60 (mirrored in `pyproject.toml`) | 0 |
| Custom grep — secrets | 28 | 28 (admin-settings lookups) | 0 |
| Custom grep — debug/temp | 24 | 24 (diagnostic logging) | 0 |
| Mypy | 20 | 20 (missing stub packages) | 0 |
| Custom grep — cmd injection | 9 | 9 (subprocess on validated paths) | 0 |
| Hardcoded IPs/HTTP | 7 | 7 (vendor hostnames) | 0 |
| Weak crypto (MD5/SHA1) | 4 | 4 (API contract) | 0 |
| Silent catch JS | 2 | 2 (belt-and-suspenders) | 0 |
| Trivy (PSN JWT in data file) | 1 | 1 (gitleaks allowlist) | 0 |
| Large files / git info | ~30 | informational | 0 |

**1.3% signal rate.**  Target: **>20%.**

---

## Remediation items (for the audit tool / `/audit` skill)

### 1. Respect `.semgrep.yml`'s documented invocation (HIGH impact, S)

The `.semgrep.yml` file in the project root documents, **in the header
comment block (lines 18-34)**, the exact Semgrep invocation that
produces zero noise on this codebase:

```bash
EXCLUDES=$(awk '/^# Excluded upstream rules/,/^# RetroDB-specific/' .semgrep.yml \
           | grep -oE '^#   [a-z][a-z0-9._-]+\.[a-z0-9._-]+' \
           | awk '{print "--exclude-rule " $2}' | tr '\n' ' ')
semgrep \
  --config p/security-audit --config p/python --config p/flask \
  --config .semgrep.yml \
  --exclude logs --exclude data --exclude database --exclude static \
  --exclude __pycache__ --exclude node_modules --exclude .venv \
  $EXCLUDES \
  --json --timeout 120 --metrics=off .
```

The audit dump from 2026-04-21 shows semgrep was run with the upstream
packs but WITHOUT the `--exclude-rule` loop.  Result: 74 findings,
~70 in the documented exclude list.

**Fix**: when the audit orchestrator detects a `.semgrep.yml` at the
project root whose header block references an `awk` excluder, run that
excluder and pass the flags through.  Alternatively, detect the literal
`# Excluded upstream rules` comment block and parse rule IDs directly.

**Expected impact**: 74 semgrep findings → ~4.

---

### 2. Respect `pyproject.toml`'s `[tool.ruff.lint.ignore]` as a bandit skip-list (HIGH impact, S)

Ruff and bandit overlap on the `S` (security) rule family.  RetroDB's
`pyproject.toml` already declares its accepted-noise list:

```toml
[tool.ruff.lint]
select = ["E", "F", "B", "S"]
ignore = [
    # ...
    "S101",    # assert — used in test scaffolding
    "S104",    # hardcoded 0.0.0.0 — intentional default for LAN access
    "S110",    # try-except-pass — common in scraper retry/fallback paths
    "S112",    # try-except-continue — same rationale
    "S201",    # Flask debug=True — env-gated behind RETRODB_DEBUG
    "S301",    # pickle — we don't use it
    "S310",    # urllib.request.urlopen — validated upstream URLs
    "S311",    # non-crypto random — placeholder shuffles only
    "S324",    # insecure hash — RA + ScreenScraper APIs require MD5/SHA1
    "S603",    # subprocess — rom tools with validated paths
    "S606",    # subprocess partial path — bundled helpers
    "S607",    # subprocess partial path — same
    "S608",    # hard-coded SQL string — safe_column() allowlist
]
```

Every code listed here is an accepted-noise category the project has
already triaged.  The audit tool currently runs bandit separately and
ignores this list, producing 60 findings.

**Fix (option A)**: when the audit tool detects ruff's S rules are
selected in `pyproject.toml`, skip running bandit entirely.  Ruff already
implements the same checks faster and respects the ignore list natively.

**Fix (option B)**: parse `pyproject.toml`'s `[tool.ruff.lint.ignore]`
for any `S<nnn>` codes, map them to bandit rule IDs (the mapping is
1:1 — `S101` → `B101`), and pass `--skip B101,B104,...` to bandit.

**Expected impact**: 60 bandit findings → 0 (option A) or <5 (option B).

---

### 3. Support a project-local grep-rule allowlist (MEDIUM impact, M)

The ants-audit runner ships with hard-coded custom grep rules that fire
on patterns like:

- `api_key`, `password`, `token` — the "hardcoded secrets" rule
- `console.debug`, `TODO`, `FIXME`, `DEBUG=True` — the "debug/temp" rule

These patterns are too coarse to self-regulate.  On a single-user
localhost app, `settings['api_key']` is a legitimate dict lookup from
admin-authored config; `console.debug(...)` is diagnostic logging not
leftover scaffolding.  There is currently no way to tell the audit tool
"this pattern is expected in this project".

**Proposal**: support a `.audit_allowlist.toml` (or similar) at the
project root:

```toml
# Suppress custom grep-rule findings that match these patterns.
# The audit tool post-filters its findings list against these rules.

[[allowlist]]
rule = "hardcoded_secrets"
path_glob = "routes/**/*.py"
line_regex = "settings\\[['\"]?(api_key|password|token)"
reason = "Admin-authored settings lookups; admin == operator on localhost."

[[allowlist]]
rule = "debug_temp_code"
path_glob = "static/js/**/*.js"
line_regex = "console\\.debug\\("
reason = "Diagnostic logging, not leftover scaffolding."

[[allowlist]]
rule = "hardcoded_ip"
path_glob = "app.py"
line_regex = "0\\.0\\.0\\.0"
reason = "Intentional LAN-access default; documented in .semgrep.yml."
```

The format is sympathetic to what `.gitleaks.toml` already does for
secrets — familiar shape, file-scoped + regex-scoped.

**Expected impact**: custom grep findings 52 → <10.  Overall signal
rate to 25%+.

---

### 4. Document the calibration chain (LOW impact, S)

For any project using the audit tool, generate (or prompt the user to
create) a single `docs/AUDIT_CALIBRATION.md` that indexes:

- Where each tool's config lives (`.semgrep.yml`, `.gitleaks.toml`,
  `pyproject.toml`, `.audit_allowlist.toml`)
- The project's threat model in one paragraph
- How to re-run the audit locally with the same flags the tool uses

This isn't a tool-side change — it's a project template the `/audit`
skill could scaffold on first run when it detects no calibration doc
exists.

---

### 5. Auto-install stub packages for mypy (LOW impact, S)

Mypy's 20 findings on RetroDB are all "Library stubs not installed" for
`requests`, `PyYAML`, `waitress`, etc.  These are free to install
(`pip install types-requests types-PyYAML types-waitress`) and
deterministic — the audit tool could detect them in a dry run and
either auto-install in an isolated venv or emit a single "install
these stubs" hint rather than 20 separate findings.

---

## Why `.semgrep.yml`'s header approach is the model

The header block of `.semgrep.yml` in RetroDB is the most effective
noise-reduction mechanism in the project.  It:

1. Documents the threat model inline (so readers understand *why*
   rules are excluded).
2. Lists each excluded rule with a **one-line anchor** stating what
   site fires and why it's not a bug.
3. Provides the exact shell incantation to synthesise
   `--exclude-rule` flags from the list (so the exclude list and the
   runner command cannot drift out of sync).

Every other tool-side calibration should follow this shape:
**document the suppression, not just perform it.**  An opaque
`skip = ["B101", "B104"]` hides the reasoning; a commented list
where each entry explains the site is self-maintaining.

---

## Summary

The project (RetroDB) already maintains high-quality calibration docs
for its accepted-noise patterns.  The audit tool currently ignores most
of them.  Closing that gap — wiring `.semgrep.yml`, `pyproject.toml`,
and a new `.audit_allowlist.toml` into the runner — would cut the
false-positive rate from ~99% to ~75% on this codebase, and establish
a template other projects can follow.

**Contact**: RetroDB project at `/mnt/Storage/Scripts/Linux/RetroDB`
— see `.semgrep.yml` header for threat-model context.
