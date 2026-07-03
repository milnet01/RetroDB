# RetroDB Dependency Policy

> **Standing rule:** every dependency tracks its **latest** release — for
> features *and* for security. A dependency is held below latest **only** when a
> newer version explicitly breaks a RetroDB feature and there is no reasonable
> workaround, and every such hold is recorded in the [Held-Back Dependency
> Ledger](#held-back-dependency-ledger) so it is deliberate, visible, and
> re-tested as soon as a fixed version ships.

This extends the global rule in `~/.claude/CLAUDE.md` §5 ("use the latest
external-library version, with current idioms") §5a (runtimes + CI tooling) §5b
(bump the code that calls it in the same change) §5c (sweep posture: check,
don't wait). Read this doc before pinning, capping, or holding back any
dependency.

---

## 1. The rule

Keep **all** dependencies current. "Current" means the latest stable release
the project can adopt without a *documented* reason not to. This applies equally
to feature-motivated bumps and security-motivated bumps — we do not wait for a
CVE to update, and we do not skip a security update because "the feature works
on the old version."

The only sanctioned reason to sit below latest is a **documented breakage**
(§6). Everything else — "haven't gotten around to it", "the old one is fine",
"don't want to test" — is not a reason; it is drift.

## 2. What counts as a dependency

Every one of these is in scope:

| Surface | Where it lives | Who bumps it |
|---|---|---|
| Python packages | `requirements.txt` (ranges) + `requirements.lock` (exact + hashes) | Dependabot `pip` group, weekly |
| GitHub Actions | `.github/workflows/*.yml` (SHA-pinned + `# vX.Y.Z` comment) | Dependabot `github-actions` group, weekly |
| pre-commit hooks | `.pre-commit-config.yaml` (ruff, gitleaks, …) | Dependabot `pre-commit` group, weekly |
| CI runner images | `runs-on:` in the workflows (e.g. `ubuntu-latest`) | manual — see §5 |
| Python runtime matrix | `.github/workflows/ci.yml` `python-version` | manual — see §5 |

Dependabot config: `.github/dependabot.yml` (weekly Monday scan, grouped PRs,
4-day cooldown on the pip group to dodge day-of-release breakage).

## 3. How "latest" is enforced

1. **Ranges in `requirements.txt`** allow every compatible update without a
   manual edit (§4). Dependabot opens a grouped PR when a newer version lands in
   range.
2. **`requirements.lock`** pins the exact resolved versions with `--generate-hashes`
   so installs are reproducible and tamper-evident (`--require-hashes`). Regenerate
   after editing `requirements.txt`:
   `pip-compile requirements.txt -o requirements.lock --strip-extras --generate-hashes`.
3. **CI gates** (`.github/workflows/ci.yml`, mirrored locally by
   `scripts/ci_local.sh`):
   - `pip-audit --requirement requirements.lock --strict` — fails on any known CVE.
   - `lockfile-drift` — fails if `requirements.txt` changed without recompiling the lock.
4. **Sweep posture** (global §5c): at the start of a release cycle, or whenever
   you touch `requirements.txt` / a workflow for any other reason, check what is
   behind and bump it:
   - Python: `pip list --outdated` (or let the weekly Dependabot PR do it).
   - Actions: `gh api repos/<owner>/<action>/releases/latest -q .tag_name`.
   - Distro/runtime: compare the `python-version` matrix + `runs-on:` image to current.

## 4. Version-range convention

`requirements.txt` uses **`>=<min>,<<next-major>`** (e.g. `Flask>=3.1.3,<4.0`):

- **`>=<min>`** is the lowest version we have actually tested / that carries a
  feature we rely on. When the reason is non-obvious, state it inline — e.g.
  `Flask-Babel>=4.0.0,<5.0` carries a comment explaining 4.0 introduced the
  `locale_selector=` ctor kwarg that replaced the removed
  `@babel.localeselector` decorator. **A non-obvious lower bound gets a
  one-line reason or it looks like superstition.**
- **`<<next-major>`** is a **SemVer-major guard**, *not* a hold-back. Minor and
  patch releases are taken automatically (that is the whole point); a new
  **major** is gated for a manual review (§5) because SemVer says a major may
  break the API. This ceiling is not a ledger entry — it is the default posture.

## 5. Major-version bumps (the review gate)

When a dependency ships a new major (or you want to raise a `<next-major>`
ceiling / bump the Python matrix / a runner image):

1. Read the upstream changelog / migration notes for breaking changes.
2. Update **our** calling code to the new major's current idioms **in the same
   change** (global §5b — the bump and the idiom-refresh ship together, or the
   codebase rots into "compiles but nobody meant it").
3. Run the full local gate (`./scripts/ci_local.sh`) — ruff, import smoke, full
   pytest, i18n freshness, semgrep, pip-audit, lockfile-drift.
4. Raise the ceiling, regenerate the lock, commit.

If step 3 surfaces a genuine, unworkable breakage, the bump becomes a **held-back
dependency** — go to §6.

## 6. Exception: holding a dependency below latest

A hold is allowed **only** when **both** are true:

1. A specific newer version **explicitly breaks** a RetroDB feature (a failing
   test, a runtime error, a regression you can point at), **and**
2. There is **no reasonable workaround** (no code change on our side restores the
   feature at acceptable cost).

When you hold one back you **must**, in the same commit:

1. **Cap the version** in `requirements.txt` at the last-good release
   (e.g. `somepkg>=1.4.0,<1.7  # capped — see docs/DEPENDENCY_POLICY.md ledger`).
   The inline comment is mandatory so the cap never reads as neglect
   (global development rule 1).
2. **Add a row to the [ledger](#held-back-dependency-ledger)** recording the
   first broken version, the exact symptom, the evidence (test name / issue /
   commit), and the re-test trigger.
3. Regenerate `requirements.lock`.

A hold with no ledger row, or a ledger row with no inline cap comment, is a bug —
fix whichever is missing.

## 7. Held-Back Dependency Ledger

Each row is a dependency we are **deliberately** keeping below its latest
release, with everything needed to re-test and lift the hold the moment upstream
fixes it. Keep it sorted by package name.

| Package | Ecosystem | Capped at | First broken version | Broken feature / symptom | Evidence | Re-test trigger | Last verified |
|---|---|---|---|---|---|---|---|
| _(none)_ | — | — | — | — | — | — | — |

> **Status: empty.** No RetroDB dependency is currently held below its latest
> compatible release. The `<next-major>` ceilings in `requirements.txt` are
> SemVer-major review gates (§4/§5), not holds, and do **not** belong in this
> table.

## 8. Re-test workflow (lifting a hold)

The ledger exists so a hold is never permanent-by-forgetting. A held-back
dependency is re-tested when **any** of these fire:

- Dependabot proposes (or a sweep finds) a version **newer than the "First
  broken version"** in that row — this is the primary trigger.
- The upstream changelog/issue for the recorded breakage is marked fixed.
- At every release-cycle sweep (§3.4), scan the ledger for stale "Last verified"
  dates.

To re-test:

1. Try the newest available version against the recorded broken feature (run the
   evidence test; exercise the feature).
2. **Fixed →** raise/remove the cap in `requirements.txt`, regenerate the lock,
   delete the ledger row (note the lift in the commit message), refresh idioms
   per §5b.
3. **Still broken →** update the row's **Last verified** date and, if a version
   *between* the recorded break and now was the newest tested, note it; keep the
   cap. This records that we checked, so the next session doesn't re-do the same
   dead-end.

## 9. Security (CVE) fast path

A CVE against a pinned dependency is not subject to the normal weekly cadence:

- `pip-audit` fails CI the moment a CVE is published against a lock entry —
  treat a red `pip-audit` as release-blocking.
- Bump to the patched version immediately (out-of-band from the weekly
  Dependabot batch if needed), regenerate the lock, push.
- If the only patched version is a new **major**, do the §5 review under time
  pressure — but the security fix wins; a documented, tested major bump beats a
  known-exploitable pin.
- If a patched version genuinely does not exist yet, that is a §6 hold with the
  CVE as the evidence, plus the mitigation we applied in the meantime.

---

## Cross-references

- Global policy: `~/.claude/CLAUDE.md` §5 / §5a / §5b / §5c
- Version-bump + lockfile step: project `CLAUDE.md` → Mandatory Workflow
- Dependabot config: `.github/dependabot.yml`
- CI gates: `.github/workflows/ci.yml` (`pip-audit`, `lockfile-drift`) and the
  local mirror `scripts/ci_local.sh`
- Lockfile: `requirements.lock` (exact pins + hashes)
