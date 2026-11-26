# RetroDB - Claude Code Project Guide

> Flask-based retro gaming ROM library manager with cyberpunk UI theme.

This file holds only the mandatory workflow and what RetroDB adds to or
overrides in the global rules. Topic contracts live in `.claude/rules/` (below).

---

## Mandatory Workflow

### After Every Code Change
1. **Bundle changes into releases** (user, 2026-10-17): a release with one changelog item is too small. A release carries at least 5 changelog items, with no upper limit (user, 2026-10-27: the floor only stops a release going out with one item; an open entry may grow past 10). While the version at the top of `data/changelog.yaml` has no `v<version>` git tag, it is still open: add the change to that entry and keep the version. Otherwise bump `config.py` AND `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`) and open a new entry. Keep `APP_LAST_UPDATE` current either way.
2. Add or extend the changelog entry at top of `data/changelog.yaml`. For a real release, run `scripts/translate_release.py` (`docs/specs/i18n.md` §9), or otherwise translate the **recent** entry (current line onward; deep history stays English) into each per-locale `data/changelog.<locale>.yaml` (the human-translation locales in `docs/specs/i18n.md` §9). Repeat `version`, `date`, and every tag verbatim — the `/changelog` route swaps the whole entry in by version, so anything omitted is dropped, not inherited. Skip for internal/no-release bumps.
3. Rebuild CSS if any `static/css/**.css` changed: `python3 build_css.py`
4. Rebuild JS if any bundled `static/js/*.js` changed: `python3 build_js.py`
5. Run tests if any `services/*.py` or `scraper/*.py` changed: `python3 -m pytest`
6. Regenerate lockfile if `requirements.txt` was edited: `uv pip compile requirements.txt --strip-extras --generate-hashes --universal -o requirements.lock` (uv, not pip-tools, which breaks against pip 26; `--universal` keeps Windows-only deps in a lock compiled on Linux; `installer_core.py` installs from the lock with `--require-hashes` when it exists). Dependencies track **latest-always**; a hold below latest needs a documented breakage in `docs/DEPENDENCY_POLICY.md` — read it before pinning, capping, or bumping a major.
7. Update this file, or the `.claude/rules/` file for that topic, if a change adds/removes/renames routes, templates, bundled JS, CSS files, or alters page/asset wiring contracts.
8. Wrap any new user-facing string for i18n and regenerate catalogs: `.claude/rules/i18n.md`.

### Verification Before Declaring Done
Tests written alongside the implementation are regression pins, not correctness
proofs. Never mark a task complete just because those tests pass.

- **UI changes** (templates / CSS / JS / page-rendering routes): start dev
  server, walk the golden path in browser at desktop + mobile (~375px). DevTools
  Network to confirm runtime assumptions (WebP served? srcset picked `-md`? API
  shape matches template?). DevTools Console for errors/warnings. Trigger one
  error path (empty input, missing record, cancelled action), not just happy.
- **Backend-only**: unit tests + a single end-to-end smoke call (curl / invoke job).
- **Tests that import new symbols (or grep for new strings) must run against a
  staged-only tree**: `git stash --keep-index && pytest <that test file> && git
  stash pop` before committing. Otherwise the unstaged production half keeps
  the test green locally while a fresh checkout of `main` fails.
- State what was verified in the session summary. If something couldn't be
  tested in-session, say so — never imply coverage that wasn't produced.
- Architecturally significant passes (multi-subsystem, reshapes an abstraction,
  touches security/auth/data flow): recommend the user run `/code-review ultra`
  before merging (user-triggered and billed).

### Contract Reviews (Global Rule 14)
Rule 14's contract gate is **cancelled for this project** (user,
2026-10-17). The practice kept instead: run `review-contract` on a spec, plan
or standard only when its author is unsure of details in the planned work,
and say which details. Otherwise the code and the user's viewing of the result
are the review.

### Periodic Independent Review (Multi-Agent Audit)
Run a multi-agent independent sweep at one of these triggers (whichever first):
1. Every 5 landed roadmap passes
2. Before any minor version bump (`x.N+1.0`)
3. After an architectural change touching >3 subsystems

How: see `roadmap.md` §Periodic Independent Review (the lane partition and
triage rules). Run `review-code` over the source and `review-tests` over
`tests/`. Surface reports verbatim — don't filter or summarize before the user
has seen the raw output. Triage into new roadmap passes after.

### Version Bumping
- **Patch** (x.x.N+1): bug fixes, cleanup, refactoring, accessibility
- **Minor** (x.N+1.0): new features, enhancements, new options
- **Major** (N+1.0.0): major releases, breaking changes

---

## Topic rules (`.claude/rules/`)

Each loads by itself when a file it names is read. Read the matching one
before planning work on its topic.

- `data-contracts.md` — schema shapes, media fill rules, the scraper fill-only invariant and its exceptions, service limits, AI answers, Steam imports
- `ratings.md` — the nine rating systems
- `emulators.md` — cheats and RetroAchievements sign-in
- `updater.md` — the self-updater
- `frontend.md` — page wiring and the CSS / JS build contracts
- `js-template-contracts.md` — JS globals and template `<script>` contracts
- `i18n.md` — wrapping strings and regenerating catalogs
- `distribution.md` — release builds, launchers, app icons
- `git-hooks.md` — the hooks and `scripts/ci_local.sh`, the pre-push gate (`--docs` for the documentation checks alone); read it before pushing past a failed gate

---

## Reference Documents

- `docs/design.md` — What RetroDB is for, its threat model, its subsystems and the spec that owns each
- `docs/decisions/` — Decision records; index in its `README.md`
- `docs/RETRODB_DESIGN_STANDARDS.md` — Full UI/CSS/JS/API standards (§23 controller naming, §25 schema migrations)
- `docs/STANDARDS_ADDENDUM.md` — Version checklist, logging system
- `docs/ROM_NAMING_STANDARD.md` — ROM file naming
- `docs/specs/` — Per-feature design/contract docs. Read the relevant one before touching that subsystem.
- `docs/theme_contrast.md` — Generated WCAG output (`scripts/audit_contrast.py`); regenerate when theme colors change
- `roadmap.md` — Backlog, including "Scope notes — considered and dropped". Check before proposing net-new architectural work.
- `.semgrep.yml` — Documented threat model + excluded upstream rule IDs (read before triaging new audit findings)
- `.gitleaks.toml` — scan scope (`logs/`, `data/*.json` tokens, admin-editable settings, media) plus one anchored model-name rule. A false positive in tracked source is excused per finding: inline `gitleaks:allow`, or its fingerprint in `.gitleaksignore` — never a path allow

## Common DB Access

`get_db()` in `services/database.py` returns the connection; `safe_column()`
there is the allowlist validator for any column name interpolated into an SQL
f-string.
