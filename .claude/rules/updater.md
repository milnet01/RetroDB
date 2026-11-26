---
paths:
  - "app.py"
  - "updater_apply.py"
  - "services/updater.py"
  - "build_dist.py"
  - "routes/updates.py"
  - ".github/workflows/release.yml"
---

# Self-updater

- The block at the top of `app.py` hands `--apply-update` to `updater_apply.py` before any other import; keep it first (the rest of `app.py` opens and migrates the database). `updater_apply.py` stays standard-library only: the standalone binary runs it inside its own bundle.
- Install runs the NEW version's helper, so a change to the plan file (`plan_version`) or to which paths an update may write (`updater_apply.PROTECTED`) must stay readable from the previous release's `services/updater.py`.
- The updater picks release assets by name (`RetroDB-v{V}-{Platform}.zip` + `SHA256SUMS.txt`, `RetroDB-v{V}-{Platform}[-CPU]-Standalone.zip` + `.sha256`, each zip + `.cosign.bundle`); renaming them in `build_dist.py` / `release.yml` stops updates. Spec: `docs/specs/PASS-59-169-self-updater.md`.
