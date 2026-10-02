#!/usr/bin/env bash
# Run once in every clone: ./scripts/setup-hooks.sh
#
# Installs RetroDB's two git hooks into .git/hooks:
#   pre-commit — pre-commit's ruff + gitleaks hook (.pre-commit-config.yaml)
#   pre-push   — a link to the tracked .githooks/pre-push, which hands off to
#                the machine-wide push gate (secret scan, then
#                scripts/ci_local.sh on a fresh checkout of the pushed commit)
#
# The repository pins core.hooksPath to .git/hooks, because this machine sets
# a global hooksPath and pre-commit refuses to install while any hooksPath is
# set. So the pin is lifted for the install and restored after it.
# The gate's own settings travel in the committed .ants/gate.conf.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

command -v pre-commit >/dev/null || {
    echo 'setup-hooks: pre-commit is not installed (pip install pre-commit)' >&2
    exit 1
}

GIT_CONFIG_GLOBAL=/dev/null git config --local --unset core.hooksPath || true
GIT_CONFIG_GLOBAL=/dev/null pre-commit install --hook-type pre-commit
git config --local core.hooksPath .git/hooks
ln -sf ../../.githooks/pre-push .git/hooks/pre-push

ls -l .git/hooks/pre-commit .git/hooks/pre-push
