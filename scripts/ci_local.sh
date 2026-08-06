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
# failing checks are listed at the end. To push anyway, use:
#
#     git push --no-verify
#
# Design notes:
#   - No dependency (re)install — unlike CI's fresh runner, your box already has
#     the deps.
#   - A CI-mirrored check whose tool is MISSING or BROKEN is a FAILURE, not a
#     skip. It used to be a skip, on the reasoning that a missing tool is the
#     box's problem rather than the branch's. That reasoning is wrong: CI will
#     run the check regardless, so a locally-skipped check is precisely a check
#     whose CI verdict you have not seen — which is the one thing this script
#     exists to prevent. Learned the hard way on 2026-08-06: pip-compile was
#     broken locally (skip, "safe to push") and broken identically on the
#     runner (hard fail, red main). The install hint is printed with the
#     failure; `--no-verify` is still there for when you mean it.
#   - Docs-only pushes short-circuit to exit 0 (see the fast path below).
#   - pytest uses CI's exact `-n 4 --dist=loadfile` invocation. Without the
#     per-file isolation, cross-file order-pollution (test_pass48_media_cleanup
#     et al.) produces false failures that CI never sees.
#   - The import smoke runs against a THROWAWAY temp DB via RETRODB_DB_PATH, so
#     it never touches your real database/roms.db (CI gets the same isolation
#     from a fresh config.py on the runner).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || { echo "cannot cd to repo root"; exit 2; }

GREEN=$'\e[32m'; RED=$'\e[31m'; BOLD=$'\e[1m'; RST=$'\e[0m'
FAILED=()
step() { printf '\n%s▶ %s%s\n' "$BOLD" "$1" "$RST"; }
ok()   { printf '%s  ✓ %s%s\n' "$GREEN" "$1" "$RST"; }
fail() { printf '%s  ✗ %s%s\n' "$RED" "$1" "$RST"; FAILED+=("$1"); }
have() { command -v "$1" >/dev/null 2>&1; }
# A CI-mirrored check whose tool is absent is a failure, not a skip — see the
# header. `hint` is the install line, shown with the failure.
missing() { fail "$1 not installed  ($2)"; }

# Docs-only fast path ---------------------------------------------------------
# A push whose every file is prose cannot change the outcome of a single check
# below — no Python, no templates, no workflows, no lockfile. Running the full
# ~40 s suite to prove that is pure latency, so short-circuit it.
#
# "Prose" is deliberately narrow: *.md, anything under docs/, and LICENSE.
# NOT *.txt (requirements.txt lives there), NOT *.yaml (data/changelog.yaml is
# read at runtime), NOT .github/workflows/*.yml.
#
# Scope is what would actually be pushed — @{upstream}..HEAD. With no upstream,
# or nothing to push (a bare manual run), everything runs. CI_LOCAL_FORCE=1
# runs everything regardless.
if [ "${CI_LOCAL_FORCE:-0}" != "1" ] && UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
  CHANGED="$(git diff --name-only "$UPSTREAM..HEAD" 2>/dev/null)"
  if [ -n "$CHANGED" ] && ! printf '%s\n' "$CHANGED" | grep -qvE '(\.md$|^docs/|^LICENSE$)'; then
    printf '%s%s✓ Docs-only push (%d file(s) vs %s) — CI-local skipped.%s\n' \
      "$BOLD" "$GREEN" "$(printf '%s\n' "$CHANGED" | wc -l)" "$UPSTREAM" "$RST"
    printf '  Run anyway with: %sCI_LOCAL_FORCE=1 ./scripts/ci_local.sh%s\n' "$BOLD" "$RST"
    exit 0
  fi
fi

# 1. Ruff (bugs only — E, F, B, S; config in pyproject.toml) -----------------
step "Ruff lint  ·  ruff check ."
if have ruff; then ruff check . && ok "ruff" || fail "ruff"
else missing "ruff" "pip install ruff"; fi

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
else missing "pytest" "pip install pytest pytest-xdist"; fi

# 4. i18n freshness gate — mirrors ci.yml's `i18n-fresh` job (CLAUDE.md step 8) -
step "i18n freshness  ·  scripts/check_i18n_fresh.py"
if python3 scripts/check_i18n_fresh.py; then ok "i18n freshness"
else fail "i18n freshness  (regenerate catalogs — see CLAUDE.md step 8)"; fi

# 5. Semgrep — calibrated via .semgrep-excludes.txt --------------------------
step "Semgrep  ·  calibrated security scan"
if have semgrep; then
  # Same array construction as ci.yml's semgrep step — the flags must arrive as
  # separate words, and an array says so without relying on word-splitting an
  # unquoted expansion (SC2086).
  mapfile -t RULE_IDS < <(grep -vE '^\s*(#|$)' .semgrep-excludes.txt | awk '{print $1}')
  if [ ${#RULE_IDS[@]} -eq 0 ]; then fail "semgrep — .semgrep-excludes.txt yielded no rule IDs"
  else
    EXCLUDES=()
    for id in "${RULE_IDS[@]}"; do EXCLUDES+=(--exclude-rule "$id"); done
    if semgrep --config p/security-audit --config p/python --config p/flask --config .semgrep.yml \
         --error --timeout 60 --metrics=off \
         --exclude logs --exclude data --exclude database --exclude static/images --exclude static/videos \
         "${EXCLUDES[@]}" . ; then ok "semgrep"
    else fail "semgrep"; fi
  fi
else missing "semgrep" "pip install semgrep"; fi

# 6. pip-audit — CVEs in the pinned lockfile ---------------------------------
step "pip-audit  ·  requirements.lock --strict"
if have pip-audit; then pip-audit --requirement requirements.lock --strict && ok "pip-audit" || fail "pip-audit"
else missing "pip-audit" "pip install pip-audit"; fi

# 7. Lockfile drift — requirements.txt vs requirements.lock ------------------
step "Lockfile drift  ·  uv pip compile round-trip"
if have uv; then
  FRESH="$(mktemp)"; ERRLOG="$(mktemp)"
  # The output file must already exist for the compiler to reuse its pins, so
  # the scratch file starts as a copy of the lock. That makes a *crashed*
  # compile indistinguishable from a clean round-trip — the diff below would
  # compare the lock against itself and report "in sync". So check the exit
  # status first and fail loudly, never pass silently. This is not
  # hypothetical: pip-compile broke exactly this way against pip 26 (Pass
  # 57.3), the gate reported green, and CI went red on the same check.
  cp requirements.lock "$FRESH"
  if uv pip compile requirements.txt --strip-extras --generate-hashes \
       --quiet -o "$FRESH" >/dev/null 2>"$ERRLOG"; then
    if diff -u <(grep -v '^#' requirements.lock) <(grep -v '^#' "$FRESH") >/dev/null; then ok "lockfile in sync"
    else fail "lockfile drift — run: uv pip compile requirements.txt --strip-extras --generate-hashes -o requirements.lock"; fi
  else
    tail -n 3 "$ERRLOG"
    fail "uv pip compile failed to run — drift NOT checked (see error above)"
  fi
  rm -f "$FRESH" "$ERRLOG"
else missing "uv" "pip install uv"; fi

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
if [ ${#FAILED[@]} -gt 0 ]; then
  printf '%s%s✗ CI-local FAILED — %d check(s):%s\n' "$BOLD" "$RED" "${#FAILED[@]}" "$RST"
  printf '   - %s\n' "${FAILED[@]}"
  printf 'Push blocked. Fix the above, or override with: %sgit push --no-verify%s\n' "$BOLD" "$RST"
  exit 1
fi
printf '%s%s✓ CI-local PASSED — safe to push.%s\n' "$BOLD" "$GREEN" "$RST"
exit 0
