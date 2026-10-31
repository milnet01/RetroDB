#!/usr/bin/env bash
#
# scripts/ci_local.sh — the CI checks. One list, used in both places.
#
# .github/workflows/ci.yml sets up a machine and calls this script once per job,
# so GitHub and the local gate cannot disagree about what runs:
#
#     ./scripts/ci_local.sh                 # every job, every Python version
#     ./scripts/ci_local.sh --job semgrep   # one job (ci.yml calls this form)
#     ./scripts/ci_local.sh --job lint-and-smoke --python <version>
#     ./scripts/ci_local.sh --docs          # the documentation checks only
#
# The Python versions are read from ci.yml's matrix. Tool versions come from
# requirements.lock and requirements-ci.txt. Locally, each job runs in its own
# throwaway environment built the way GitHub builds it, kept under
# ~/.cache/retrodb-ci (RETRODB_CI_ENVS moves it) and rebuilt when a version
# changes. It never touches the Python packages the app itself runs on.
#
# What stays different from GitHub, because one computer cannot reproduce it:
# the operating system (Ubuntu there) and the Python and Node patch versions.
# GitHub also measures test coverage, a report that cannot fail the run. One check
# runs locally only: the workflow lint.
#
# The git PRE-PUSH hook (.githooks/pre-push, installed by scripts/setup-hooks.sh)
# hands off to the machine-wide hook, which runs the secret scan and then this
# script inside a fresh checkout of the pushed commit, with --docs when every
# pushed file is prose.
#
# Exit 0 = every check passed (safe to push). Nonzero = a check failed; the
# failing checks are listed at the end. Skipping the gate is commits.md § 2.3's
# call (SKIP_LOCAL_CI=1, or git push --no-verify), not this script's.
#
# Design notes:
#   - A check whose tool is MISSING or BROKEN is a FAILURE, not a skip: a
#     locally-skipped check is precisely one whose CI verdict you have not seen.
#     Learned on 2026-08-06, when pip-compile was broken locally (skip, "safe to
#     push") and broken identically on the runner (hard fail, red main).
#   - Docs-only pushes run documentation mode (see below), never nothing.
#   - pytest uses `-n 4 --dist=loadfile`. Without the per-file isolation,
#     cross-file order-pollution (test_pass48_media_cleanup et al.) produces
#     false failures.
#   - The import smoke runs against a THROWAWAY temp DB via RETRODB_DB_PATH, so
#     it never touches a real database/roms.db.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || { echo "cannot cd to repo root"; exit 2; }

GREEN=$'\e[32m'; RED=$'\e[31m'; BOLD=$'\e[1m'; RST=$'\e[0m'
FAILED=()
step() { printf '\n%s▶ %s%s\n' "$BOLD" "$1" "$RST"; }
ok()   { printf '%s  ✓ %s%s\n' "$GREEN" "$1" "$RST"; }
fail() { printf '%s  ✗ %s%s\n' "$RED" "$1" "$RST"; FAILED+=("$1"); }
have() { command -v "$1" >/dev/null 2>&1; }
# A check whose tool is absent is a failure, not a skip — see the header.
missing() { fail "$1 not installed  ($2)"; }

WORKFLOW=.github/workflows/ci.yml
read -r -a PYTHONS <<< "$(sed -n 's/^ *python-version: *\[\(.*\)\]/\1/p' "$WORKFLOW" | tr ',"' '  ')"
PRIMARY="$(sed -n 's/^ *PRIMARY_PYTHON: *"\(.*\)"/\1/p' "$WORKFLOW")"
if [ "${#PYTHONS[@]}" -eq 0 ] || [ -z "$PRIMARY" ]; then
  echo "cannot read the Python versions from $WORKFLOW"; exit 2
fi

# A fresh checkout has no config.py (it holds the user's own settings and is
# untracked). The example stands in, on GitHub and in the pre-push hook's fresh
# worktree. Every mode needs it: tests/test_backup_rotation.py imports config.
if [ ! -f config.py ]; then cp config.example.py config.py; fi

# Environments ----------------------------------------------------------------
# The tools each job installs; requirements-ci.txt holds their versions.
packages_for() {
  case "$1" in
    lint-and-smoke) echo "ruff pytest pytest-cov pytest-xdist pytest-randomly beautifulsoup4" ;;
    semgrep)        echo "semgrep" ;;
    pip-audit)      echo "pip-audit" ;;
    lockfile-drift) echo "uv" ;;
    i18n-fresh)     echo "" ;;
  esac
}

install_job() {
  local tools
  case "$1" in
    # --require-hashes: fail-closed install under PyPI tamper or MITM, matching
    # install.py's secure path (Pass 39.4).
    lint-and-smoke|i18n-fresh)
      uv pip install --quiet --require-hashes -r requirements.lock || return 1 ;;
  esac
  tools="$(packages_for "$1")"
  [ -z "$tools" ] && return 0
  # shellcheck disable=SC2086  # the list is meant to split into package names
  uv pip install --quiet -c requirements-ci.txt $tools
}

BASE_PATH="$PATH"
ENV_ROOT="${RETRODB_CI_ENVS:-${XDG_CACHE_HOME:-$HOME/.cache}/retrodb-ci}"

# Build the job's environment, or reuse it while no version has changed, and
# put it first on PATH. On GitHub the runner is the environment.
enter_env() {
  local job="$1" python="$2" key dir
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    UV_SYSTEM_PYTHON=1 install_job "$job"
    return
  fi
  PATH="$BASE_PATH"; unset VIRTUAL_ENV
  if ! have uv; then missing "uv" "pip install uv"; return 1; fi
  key="$(cat requirements.lock requirements-ci.txt <(declare -f packages_for) | sha256sum | cut -c1-12)"
  dir="$ENV_ROOT/$job-py$python-$key"
  mkdir -p "$ENV_ROOT"
  (
    # Two pushes at once must not build the same environment together.
    flock 9
    [ -f "$dir/.ready" ] && exit 0
    step "Building the $job environment (Python $python)"
    # Older environments for this job and Python are stale: a version changed.
    rm -rf "$ENV_ROOT/$job-py$python-"*
    uv venv --quiet --seed --python "$python" "$dir" \
      && VIRTUAL_ENV="$dir" install_job "$job" \
      && touch "$dir/.ready"
  ) 9> "$ENV_ROOT/.lock" || { fail "$job environment (Python $python) did not build"; return 1; }
  export VIRTUAL_ENV="$dir"
  export PATH="$dir/bin:$BASE_PATH"
}

# Documentation mode ----------------------------------------------------------
# `--docs` is for a push whose every file is prose: *.md and LICENSE, the
# `ants.gate.docsGlob` in .ants/gate.conf. Not docs/* — docs/ also holds
# requirements.txt and an env example. Not *.yaml (data/changelog.yaml is read
# at runtime). The pre-push hook decides which push is prose; this script never
# skips on its own.
#
# A prose edit can still break a test: some tests open markdown files
# (docs/PROXY-DEPLOY.md, docs/specs/scrapers.md). So documentation mode runs
# every test file that names a .md path in a string, found fresh each run so a
# new one is picked up without editing this list.
if [ "${1:-}" = "--docs" ]; then
  step "Pytest (documentation mode)  ·  tests that read markdown"
  mapfile -t DOC_TESTS < <(grep -lE "\.md['\"]" tests/test_*.py)
  if enter_env lint-and-smoke "$PRIMARY"; then
    if [ "${#DOC_TESTS[@]}" -eq 0 ]; then fail "no markdown-reading tests found"
    else pytest -q "${DOC_TESTS[@]}" && ok "pytest (${#DOC_TESTS[@]} files)" || fail "pytest"; fi
  fi
  if [ "${#FAILED[@]}" -gt 0 ]; then
    printf '\n%s%sDocumentation checks FAILED:%s %s\n' "$BOLD" "$RED" "$RST" "${FAILED[*]}"
    exit 1
  fi
  printf '\n%s%s✓ Documentation checks passed.%s\n' "$BOLD" "$GREEN" "$RST"
  exit 0
fi

# The jobs ---------------------------------------------------------------------
job_lint_and_smoke() {
  local py="$1" smoke_dir js_bad=0
  # Ruff (bugs only — E, F, B, S; config in pyproject.toml)
  step "Ruff lint  ·  Python $py  ·  ruff check ."
  ruff check . && ok "ruff (Python $py)" || fail "ruff (Python $py)"

  # PASS-58-1: no linter covers static/js, so at least catch a syntax error.
  step "JS syntax  ·  node --check static/js/*.js"
  if have node; then
    for f in static/js/*.js; do node --check "$f" || js_bad=1; done
    [ "$js_bad" -eq 0 ] && ok "node --check" || fail "node --check"
  else missing "node" "install Node.js"; fi

  step "Import smoke  ·  Python $py  ·  import app"
  smoke_dir="$(mktemp -d)"
  if RETRODB_DB_PATH="$smoke_dir/smoke.db" RETRODB_DEBUG=false \
       python -c "import app; print('app imports cleanly')"; then ok "import smoke (Python $py)"
  else fail "import smoke (Python $py)"; fi
  rm -rf "$smoke_dir"

  # `-n 4 --dist=loadfile` keeps a file's tests on one worker, so module-scoped
  # fixtures stay correct. pytest-randomly logs its seed at the top of the
  # output: `pytest --randomly-seed=<N>` reproduces a flake. Coverage is a report
  # with no pass mark, so only GitHub produces it, on the primary Python.
  step "Pytest  ·  Python $py  ·  -n 4 --dist=loadfile --durations=20"
  local args=(-n 4 --dist=loadfile --durations=20)
  if [ "${GITHUB_ACTIONS:-}" = "true" ] && [ "$py" = "$PRIMARY" ]; then
    args+=(--cov=services --cov=scraper --cov=routes --cov-report=term-missing --cov-report=xml)
  fi
  pytest "${args[@]}" && ok "pytest (Python $py)" || fail "pytest (Python $py)"
}

# Mirrors CLAUDE.md step 8. Needs the LOCKED Babel and Jinja2: a newer Babel can
# extract a slightly different msgid set and fail against the committed
# messages.pot.
job_i18n_fresh() {
  step "i18n freshness  ·  scripts/check_i18n_fresh.py"
  if python scripts/check_i18n_fresh.py; then ok "i18n freshness"
  else fail "i18n freshness  (regenerate catalogs — see CLAUDE.md step 8)"; fi
}

# Security scan. Hard-fail since v2.98.1 (Pass 30): green should mean zero. A new
# finding is a real bug, or noise needing a documented exclusion, with its
# rationale in .semgrep.yml and its ID in .semgrep-excludes.txt.
job_semgrep() {
  local rule_ids excludes=()
  step "Semgrep  ·  calibrated security scan"
  mapfile -t rule_ids < <(grep -vE '^\s*(#|$)' .semgrep-excludes.txt | awk '{print $1}')
  # An empty list means the file was renamed or emptied, not that nothing is
  # excluded.
  if [ ${#rule_ids[@]} -eq 0 ]; then fail "semgrep — .semgrep-excludes.txt yielded no rule IDs"; return; fi
  for id in "${rule_ids[@]}"; do excludes+=(--exclude-rule "$id"); done
  if semgrep --config p/security-audit --config p/python --config p/flask --config .semgrep.yml \
       --error --timeout 60 --metrics=off \
       --exclude logs --exclude data --exclude database --exclude static/images --exclude static/videos \
       "${excludes[@]}" . ; then ok "semgrep"
  else fail "semgrep"; fi
}

# CVEs in the pinned lockfile. Hard-fail since Pass 39.3.
job_pip_audit() {
  step "pip-audit  ·  requirements.lock --strict"
  pip-audit --requirement requirements.lock --strict && ok "pip-audit" || fail "pip-audit"
}

# Catches "added a dep to requirements.txt but forgot to recompile the lock", not
# "upstream released something newer" (Dependabot's job). The compiler keeps the
# pins already in its output file unless the input forces a change, so a clean
# tree gives an identical body; the header names the output path, so it is
# stripped before comparing.
job_lockfile_drift() {
  local fresh errlog
  step "Lockfile drift  ·  uv pip compile round-trip"
  fresh="$(mktemp)"; errlog="$(mktemp)"
  # The scratch file starts as a copy of the lock, which makes a *crashed* compile
  # look like a clean round-trip: the diff would compare the lock against itself.
  # So check the exit status first. pip-compile broke exactly this way against
  # pip 26 (Pass 57.3): the gate reported green and CI went red on the same check.
  cp requirements.lock "$fresh"
  if uv pip compile requirements.txt --strip-extras --generate-hashes --universal \
       --quiet -o "$fresh" >/dev/null 2>"$errlog"; then
    if diff -u <(grep -v '^#' requirements.lock) <(grep -v '^#' "$fresh"); then ok "lockfile in sync"
    else fail "lockfile drift — run: uv pip compile requirements.txt --strip-extras --generate-hashes --universal -o requirements.lock"; fi
  else
    tail -n 3 "$errlog"
    fail "uv pip compile failed to run — drift NOT checked (see error above)"
  fi
  rm -f "$fresh" "$errlog"
}

# Local only. GitHub validates workflow YAML itself when it loads a run. A linter
# catches bad expressions, shell-quoting and unknown keys before they reach
# GitHub, release.yml included. Falls back to a YAML parse, so this always runs.
workflow_lint() {
  PATH="$BASE_PATH"; unset VIRTUAL_ENV
  step "Workflow lint  ·  .github/workflows/*.yml"
  if have actionlint; then
    actionlint && ok "actionlint" || fail "actionlint"
  elif python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]" 2>/dev/null; then
    ok "workflow YAML valid  (install actionlint for expression/shell checks: https://github.com/rhysd/actionlint)"
  else
    fail "workflow YAML invalid in .github/workflows/"
  fi
}

run_job() {
  local job="$1" py="$2"
  enter_env "$job" "$py" || { fail "$job: could not set up its tools"; return; }
  case "$job" in
    lint-and-smoke) job_lint_and_smoke "$py" ;;
    i18n-fresh)     job_i18n_fresh ;;
    semgrep)        job_semgrep ;;
    pip-audit)      job_pip_audit ;;
    lockfile-drift) job_lockfile_drift ;;
    *) fail "unknown job: $job" ;;
  esac
}

# Choose what to run -----------------------------------------------------------
if [ "${1:-}" = "--job" ]; then
  JOB="${2:-}"
  # `--python` names the matrix leg; without it, the primary Python.
  if [ "${3:-}" = "--python" ]; then JOB_PYTHON="${4:-}"; else JOB_PYTHON="$PRIMARY"; fi
  run_job "$JOB" "$JOB_PYTHON"
elif [ "$#" -gt 0 ]; then
  echo "unknown option: $1  (see the top of this script)"; exit 2
else
  for py in "${PYTHONS[@]}"; do run_job lint-and-smoke "$py"; done
  for job in i18n-fresh semgrep pip-audit lockfile-drift; do run_job "$job" "$PRIMARY"; done
  workflow_lint
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
