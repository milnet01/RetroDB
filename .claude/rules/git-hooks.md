---
paths:
  - "scripts/setup-hooks.sh"
  - "scripts/ci_local.sh"
  - ".githooks/**"
  - ".pre-commit-config.yaml"
  - ".ants/gate.conf"
  - ".github/workflows/ci.yml"
---

# Git hooks and the local gate

- **Git hooks** — install both with `./scripts/setup-hooks.sh` (needs `pip install pre-commit`; venv / `--user` / `--break-system-packages` on PEP-668 distros), then check `ls -l .git/hooks` shows `pre-commit` and a `pre-push` link. Per-commit: `.pre-commit-config.yaml` runs `ruff check --fix` + `gitleaks`. Pre-push: the tracked `.githooks/pre-push` hands off to the machine-wide `~/.claude/githooks/pre-push`. That hook scans the pushed commits for secrets. It then runs `scripts/ci_local.sh` in a fresh checkout of the pushed commit, with `--docs` when every pushed file matches `docsGlob`. The hook's settings are in the committed `.ants/gate.conf`. The repo pins `core.hooksPath=.git/hooks`, because this machine sets a global one and `pre-commit install` refuses under any hooksPath; the setup script lifts and restores the pin. `ruff-format` / `mypy` intentionally excluded.
- `scripts/ci_local.sh` — the gate script. It mirrors `.github/workflows/ci.yml` (ruff · import smoke · pytest · i18n freshness · semgrep · pip-audit · lockfile-drift · workflow lint). Run it by hand any time with `./scripts/ci_local.sh` (~40 s warm), or with `--docs` for the documentation checks alone (the tests that open markdown files). Exit 0 = safe to push. A CI-mirrored check whose tool is missing or broken **fails** (a skip would be a check whose CI verdict you haven't seen — Pass 57.3). With no `config.py`, it copies `config.example.py` into place, as CI does. Skipping the gate (`SKIP_LOCAL_CI=1`, `git push --no-verify`) needs the user (`commits.md` § 2.3).
