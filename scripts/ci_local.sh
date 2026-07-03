#!/usr/bin/env bash
#
# scripts/ci_local.sh — run the GitHub Actions CI checks locally.
#
# Mirrors every job in .github/workflows/ci.yml 1:1 — ruff, import smoke,
# pytest, i18n freshness, semgrep, pip-audit, and lockfile-drift — against the
# LOCAL interpreter and installed tools, so a push that would go red in CI fails
# here first. Adds ONE local-only extra: a lint of the workflow files themselves
# (ci.yml + release.yml). That extra is deliberately NOT a CI gate — GitHub
# validates workflow YAML natively when it loads a run, and the release
# pipeline's keyless cosign signing needs a GitHub OIDC token and can't run
# locally, so linting the workflows before push is a pre-push nicety, not part
# of the CI-parity contract.
#
# CI-only differences that can't be reproduced on one local box (environmental,
# NOT check-logic gaps): the 3.12/3.13 interpreter matrix and the coverage-XML
# upload. Every pass/fail check itself is mirrored, with CI's exact invocation.
#
# Wired as a git PRE-PUSH gate via pre-commit (.pre-commit-config.yaml). Also
# runnable by hand at any time:
#
#     ./scripts/ci_local.sh
#
# Exit 0 = every check passed (safe to push). Nonzero = a check failed; the
# failing checks are listed at the end. To push anyway (e.g. a docs-only branch
# where a flaky check is irrelevant), use:  git push --no-verify
#
# Design notes:
#   - No dependency (re)install — unlike CI's fresh runner, your box already has
#     the deps. Each check is skipped with an install hint if its tool is absent
#     (a skip never blocks the push, but is reported so coverage gaps are loud).
#   - pytest uses CI's exact `-n 4 --dist=loadfile` invocation. Without the
#     per-file isolation, cross-file order-pollution (test_pass48_media_cleanup
#     et al.) produces false failures that CI never sees.
#   - The import smoke runs against a THROWAWAY temp DB via RETRODB_DB_PATH, so
#     it never touches your real database/roms.db (CI gets the same isolation
#     from a fresh config.py on the runner).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || { echo "cannot cd to repo root"; exit 2; }

GREEN=$'\e[32m'; RED=$'\e[31m'; YELLOW=$'\e[33m'; BOLD=$'\e[1m'; RST=$'\e[0m'
FAILED=(); SKIPPED=()
step() { printf '\n%s▶ %s%s\n' "$BOLD" "$1" "$RST"; }
ok()   { printf '%s  ✓ %s%s\n' "$GREEN" "$1" "$RST"; }
fail() { printf '%s  ✗ %s%s\n' "$RED" "$1" "$RST"; FAILED+=("$1"); }
skip() { printf '%s  ⚠ SKIP: %s%s\n' "$YELLOW" "$1" "$RST"; SKIPPED+=("$1"); }
have() { command -v "$1" >/dev/null 2>&1; }

# 1. Ruff (bugs only — E, F, B, S; config in pyproject.toml) -----------------
step "Ruff lint  ·  ruff check ."
if have ruff; then ruff check . && ok "ruff" || fail "ruff"
else skip "ruff not installed  (pip install ruff)"; fi

# 2. Import smoke — catch import-time errors against an isolated temp DB ------
step "Import smoke  ·  python -c 'import app'"
SMOKE_DIR="$(mktemp -d)"
if RETRODB_DB_PATH="$SMOKE_DIR/smoke.db" RETRODB_DEBUG=false \
     python3 -c "import app; print('app imports cleanly')"; then ok "import smoke"
else fail "import smoke"; fi
rm -rf "$SMOKE_DIR"

# 3. Pytest — CI's exact invocation (xdist + per-file dist + durations) -------
# `--durations=20` matches ci.yml so the slowest-20 report is identical; `-q`
# is a local readability choice (verbosity only, no pass/fail impact). CI also
# layers coverage on the primary interpreter — reporting-only, omitted here.
step "Pytest  ·  -n 4 --dist=loadfile --durations=20"
if have pytest; then pytest -n 4 --dist=loadfile --durations=20 -q && ok "pytest" || fail "pytest"
else skip "pytest not installed  (pip install pytest pytest-xdist)"; fi

# 4. i18n freshness gate — mirrors ci.yml's `i18n-fresh` job (CLAUDE.md step 8) -
step "i18n freshness  ·  scripts/check_i18n_fresh.py"
if python3 scripts/check_i18n_fresh.py; then ok "i18n freshness"
else fail "i18n freshness  (regenerate catalogs — see CLAUDE.md step 8)"; fi

# 5. Semgrep — calibrated via .semgrep-excludes.txt --------------------------
step "Semgrep  ·  calibrated security scan"
if have semgrep; then
  EXCLUDES=$(grep -vE '^\s*(#|$)' .semgrep-excludes.txt | awk '{print "--exclude-rule " $1}' | tr '\n' ' ')
  if [ -z "$EXCLUDES" ]; then fail "semgrep — .semgrep-excludes.txt yielded no rule IDs"
  else
    # shellcheck disable=SC2086
    if semgrep --config p/security-audit --config p/python --config p/flask --config .semgrep.yml \
         --error --timeout 60 --metrics=off \
         --exclude logs --exclude data --exclude database --exclude static/images --exclude static/videos \
         $EXCLUDES . ; then ok "semgrep"
    else fail "semgrep"; fi
  fi
else skip "semgrep not installed  (pip install semgrep)"; fi

# 6. pip-audit — CVEs in the pinned lockfile ---------------------------------
step "pip-audit  ·  requirements.lock --strict"
if have pip-audit; then pip-audit --requirement requirements.lock --strict && ok "pip-audit" || fail "pip-audit"
else skip "pip-audit not installed  (pip install pip-audit)"; fi

# 7. Lockfile drift — requirements.txt vs requirements.lock ------------------
step "Lockfile drift  ·  pip-compile round-trip"
if have pip-compile; then
  FRESH="$(mktemp)"
  cp requirements.lock "$FRESH"
  pip-compile --quiet --strip-extras --generate-hashes --output-file "$FRESH" requirements.txt >/dev/null 2>&1
  if diff -u <(grep -v '^#' requirements.lock) <(grep -v '^#' "$FRESH") >/dev/null; then ok "lockfile in sync"
  else fail "lockfile drift — run: pip-compile requirements.txt -o requirements.lock --strip-extras --generate-hashes"; fi
  rm -f "$FRESH"
else skip "pip-compile not installed  (pip install pip-tools)"; fi

# 8. Workflow lint — .github/workflows/*.yml (ci.yml + release.yml) -----------
# LOCAL-ONLY extra (not a CI gate — see the header note). The release pipeline
# (release.yml) isn't exercised by the CI mirror above and can't be fully run
# locally (its keyless cosign signing needs a GitHub OIDC token), but a linter
# still catches workflow-config bugs — bad expressions, shell-quoting, unknown
# keys — before they reach GitHub. Prefer actionlint (deep checks); fall back to
# a YAML-parse of each workflow so this step ALWAYS runs without a new tool.
step "Workflow lint  ·  .github/workflows/*.yml"
if have actionlint; then
  actionlint && ok "actionlint" || fail "actionlint"
elif python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]" 2>/dev/null; then
  ok "workflow YAML valid  (install actionlint for expression/shell checks: https://github.com/rhysd/actionlint)"
else
  fail "workflow YAML invalid in .github/workflows/"
fi

# Summary --------------------------------------------------------------------
echo
if [ ${#SKIPPED[@]} -gt 0 ]; then
  printf '%s%d check(s) skipped (tool not installed) — local coverage is partial:%s\n' "$YELLOW" "${#SKIPPED[@]}" "$RST"
  printf '   - %s\n' "${SKIPPED[@]}"
fi
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '%s%s✗ CI-local FAILED — %d check(s):%s\n' "$BOLD" "$RED" "${#FAILED[@]}" "$RST"
  printf '   - %s\n' "${FAILED[@]}"
  printf 'Push blocked. Fix the above, or override with: %sgit push --no-verify%s\n' "$BOLD" "$RST"
  exit 1
fi
printf '%s%s✓ CI-local PASSED — safe to push.%s\n' "$BOLD" "$GREEN" "$RST"
exit 0
