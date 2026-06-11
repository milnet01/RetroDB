# i18n Foundation — Design (Pass 43.1, machinery + pilot)

**Date:** 2026-06-10
**Roadmap:** Pass 43.1 (this spec). Pass 43.2 (canonical-label helper) and
Pass 43.3 (JS-side `window.I18N`) are explicitly deferred to their own passes.
(Roadmap headings are `#### Pass 43.N` — that is what an implementer greps in
`roadmap.md`; `PASS-43-N` is only the Ants-MCP item-id form and never appears in
`roadmap.md` itself — don't grep for it there.)
**Status:** design — **cold-eyes clean** (5 loops, 2026-06-11); ready for
implementation. See the Cold-eyes loop log at the end of this doc.

> **Roadmap-first reader, note:** roadmap `#### Pass 43.1` already carries a
> `> Re-scoped (design pending)` banner pointing here, but its **body bullets
> below that banner** still describe the original full-scope plan ("wrap all ~45
> files" + a `de/fr/es/it/ja/pt_BR` roster + a `settings.html` Language section).
> **This spec supersedes those bullets** — 43.1 is re-scoped to machinery + a
> single-page pilot (see §8 "Roadmap re-scope", which trims the stale bullets and
> creates the Pass 43.5 follow-on). Trust this spec, not the body bullets, for the
> actual 43.1 scope.

## Goal & non-goals

**Goal.** Stand up the server-side internationalization *machinery* for RetroDB
and prove it end-to-end on one pilot page, without committing to the multi-session
grind of wrapping all 61 templates or sourcing real translations. (The roadmap's
"45 files" is approximate; top-level `templates/*.html` is currently 46, and the
full tree is 61 — 46 top-level + 15 nested under `templates/_settings_tabs/`,
`templates/_modals/`, and `templates/_macros/`.)

This pass delivers:

1. Flask-Babel wired into `app.py` with a documented locale-selection chain.
2. A per-user `locale_preference` setting (DB column + validator + Settings UI).
3. A generated **pseudolocale** that doubles as a coverage/QA tool.
4. A pilot migration of `templates/login.html` + one Python flash message.
5. Extraction config (`babel.cfg`, `messages.pot`) and a regression test file.

**Non-goals (deferred, not in this spec):**

- Wrapping the other 60 templates / ~3-4k strings (follow-on mechanical passes).
- Real translated catalogs for any human language (de/fr/es/…). The only shipped
  non-English catalog is the pseudolocale.
- Translating canonical genre/perspective/dimension **labels** — that is Pass 43.2.
- JS-constructed strings (toasts, modals) via `window.I18N` — that is Pass 43.3.
  The pilot deliberately leaves `login.html`'s `<script>` error strings in English
  to mark this boundary.
- An anonymous-user locale-switcher UI. Anonymous requests fall back to the
  `Accept-Language` header.

## Components at a glance

| § | Component | Key artifact |
|---|-----------|--------------|
| §1 | Dependency & extraction config | `babel.cfg`, `messages.pot` |
| §2 | Babel init & locale-selection chain | `app.py` |
| §3 | `available_locales()` helper | `services/i18n.py` (new) |
| §4 | Locale persistence (settings) | `user_settings.locale_preference` |
| §5 | Pseudolocale | `scripts/gen_pseudolocale.py` (new) |
| §6 | Pilot migration | `templates/login.html` |
| §7 | Tests | `tests/test_i18n.py` (new) |
| §8 | Docs & workflow | `docs/specs/i18n.md` (new) |

**Key constants** (all in `services/i18n.py` / `app.config`):
`BABEL_DEFAULT_LOCALE = 'en'`, `BABEL_TRANSLATION_DIRECTORIES = 'translations'`,
`PSEUDO_LOCALE` (resolved per INV-1, §5).
**Locale-selection chain (§2):** user pref → `session['locale']` →
`Accept-Language` → `'en'`.

## Approach

**Flask-Babel with source-text message IDs** (the gettext standard). Strings are
wrapped as `{{ _('Save') }}` / `flash(_('Logged out'))`; the English source text
*is* the catalog key, so wrapping is zero-friction with no separate key registry.
`pybabel extract` walks templates + Python into `messages.pot`; per-locale
`.po`/`.mo` catalogs live under `translations/`.

Rejected alternatives: a custom JSON `t(key)` layer (reinvents extraction +
pluralization, non-standard), and key-based msgids like `_('login.submit')`
(forces a hand-invented key for every string — overkill for v1).

## Components

### 1. Dependency & extraction config

- Add `flask-babel` to `requirements.txt`, pinned `>= 3.0` — the
  `locale_selector=` constructor kwarg used in §2 replaced the removed
  `@babel.localeselector` decorator in flask-babel 3.0; verify the exact API
  against the resolved version at implementation (the dep is not yet installed).
- Regenerate `requirements.lock` with the mandatory-workflow step-6 command
  verbatim: `pip-compile requirements.txt -o requirements.lock --strip-extras
  --generate-hashes`.
- `babel.cfg` at repo root — extraction mapping for `jinja2` and `python`
  source, including the `jinja2.ext.i18n` / autoescape extensions so
  `{% trans %}` blocks extract.
- `messages.pot` — committed canonical extraction snapshot (regenerated with
  `pybabel extract -F babel.cfg -o messages.pot .`). **Ordering matters:** extract
  *after* the pilot strings are wrapped (§6), or the pilot msgids won't be in the
  `.pot`, won't reach the pseudolocale catalog, and the §7 completeness scan will
  fail. Implementation order is wrap → extract → `gen_pseudolocale.py` → compile.

### 2. Babel init & locale-selection chain (`app.py`)

`g.user_settings` is a plain `dict` (`get_user_settings` calls
`query(..., one=True)`, which returns `dict(row)`). The selector uses `.get()` so a
missing key returns `None` rather than raising; subscript works too (existing
call-sites like `services/auth.py:198` already do `g.user_settings['ra_username']`),
but `.get()` is the safe idiom for a column a legacy row may predate:

```python
from flask_babel import Babel

def select_locale():
    locales = available_locales()
    # 1. logged-in user's saved preference (guarded: still installed)
    if g.get('user_settings'):
        pref = g.user_settings.get('locale_preference')
        if pref and pref in locales:
            return pref
    # 2. transient per-session switch — intentionally retained but unreachable in
    #    v1 (no UI writes session['locale']); kept for a future anon-switcher. Do
    #    not delete as "dead code".
    sess = session.get('locale')
    if sess and sess in locales:
        return sess
    # 3. browser Accept-Language
    best = request.accept_languages.best_match(locales)
    if best:
        return best
    # 4. default
    return 'en'

babel = Babel(app, locale_selector=select_locale)  # requires flask-babel >= 3.0
```

- Config (set in `app.config` in `app.py`, before the `Babel(...)` construction):
  `BABEL_DEFAULT_LOCALE = 'en'`, `BABEL_TRANSLATION_DIRECTORIES = 'translations'`.
- The chain must never raise on a stale/removed locale — every branch is guarded
  by membership in `available_locales()`, so it degrades to `'en'`.

### 3. `available_locales()` helper

- Enumerates `translations/*/LC_MESSAGES/messages.mo`, plus the implicit `'en'`
  (the source language — no catalog needed). Returns a sorted list of locale codes.
- Single source of truth used by `select_locale()`, the `/api/users/settings` locale
  validation (§4), and the Settings dropdown, so they can never drift.
- Lives in a new `services/i18n.py` (decided — keeps it import-testable without
  pulling in the Flask app). It also exports the `PSEUDO_LOCALE` constant (§5).

### 4. Locale persistence (settings)

**`locale_preference` is a per-user setting** — it follows the *same path as
`theme_preference`*, NOT the global `settings.json` path. Two distinct subsystems
exist and must not be confused:

- **Global settings** (`settings.json`) — keys in `settings_manager.DEFAULT_SETTINGS`
  (repo-root module `settings_manager.py`, `import settings_manager` — **not** under
  `services/`, unlike its siblings cited below),
  saved via `/api/settings`, validated by `services/settings_validators.py::_VALIDATORS`
  (whose import-time `_missing` check asserts every `DEFAULT_SETTINGS` key has a
  validator). The `theme` key here is a *different, unrelated* setting.
- **Per-user settings** (`user_settings` DB columns) — saved via
  `routes/auth.py::api_user_settings` (`/api/users/settings`) through a hard-coded
  `allowed_fields` list (the canonical list is the block at `routes/auth.py:320-323`
  — currently 8 fields, several of them secrets/paths; read the full list there
  rather than trusting any partial enumeration here). Note `avatar` is a
  `user_settings` column too but
  is deliberately kept OUT of `allowed_fields` for path-traversal safety (Pass 33.2),
  so don't copy it into the list. **This is where `locale_preference` lives.** Do
  **not** register it in `settings_validators.py`.

Components:

- **Schema:** `locale_preference TEXT DEFAULT 'en'` added to `user_settings` via
  the existing idempotent `_add_column_if_missing` probe in
  `services/database_init.py` (the same mechanism that adds `avatar`, `timezone`,
  `steam_id` — note `theme_preference` happens to sit in the `CREATE TABLE` body,
  but the probe is the right tool for a *new* additive column). No numbered
  migration needed — `user_settings` is a bootstrap-owned table.
- **Save + validation:** add `'locale_preference'` to the `allowed_fields` list in
  `routes/auth.py::api_user_settings` (alongside `theme_preference`). Validate the
  submitted value against `available_locales()` **in that route at request time**
  (reject an unknown locale with the route's existing error path), so a locale
  added after process start is accepted and a removed one cannot be persisted.
- **UI:** a "Language" `<select>` added in `templates/_settings_tabs/library.html`,
  next to the Theme selector block (the `<div class="theme-selector"
  id="themeSelector" role="radiogroup" aria-labelledby="themeSelectorLabel">` at
  `library.html:58`, whose accessible name comes from the sibling
  `<div class="form-label" id="themeSelectorLabel">Theme</div>` at `library.html:57` —
  replicate that label-div + `aria-labelledby` pairing for the Language control so it
  has an accessible name too). The Theme control is
  a radiogroup of clickable divs that applies instantly and auto-saves via
  `ThemeManager.apply()`. The Language control does **not** mirror that: it is a
  plain `<select>` POSTed to `/api/users/settings` like the other per-user fields. On
  a `200` the settings JS calls `location.reload()` so the page re-renders in the
  new locale; an already-open second tab keeps the old locale until its own reload
  (acceptable for v1 — no live broadcast). Options are enumerated from
  `available_locales()`, each labelled via
  `babel.Locale.parse(code).get_display_name(code)` (endonym — verify this API
  shape against the resolved Babel version at implementation, as with INV-1:
  `get_display_name`'s optional locale arg and per-locale CLDR coverage are
  version-dependent). Two label
  exceptions: **the pseudolocale always shows the fixed label "Pseudo"**, never its
  parsed display name — special-case `code == PSEUDO_LOCALE` *before* the
  `Locale.parse` call (otherwise the `eo` fallback, should INV-1 select it, would surface as
  "Esperanto"); and any other unparseable code falls back to the raw code string.
- Anonymous users get Accept-Language detection — no extra switcher UI in v1 (YAGNI).

### 5. Pseudolocale

- `scripts/gen_pseudolocale.py` reads `messages.pot` and writes
  `translations/<code>/LC_MESSAGES/messages.po`, transforming each `msgstr` into a
  bracketed + accented version of its `msgid` (e.g. `Save` → `⟦Šàⱴé⟧`), then
  `pybabel compile` produces the `.mo`.
- Bracketing surfaces any **unwrapped** string (it renders plain English) and the
  length-padding surfaces layout/truncation bugs — the pseudolocale is a permanent
  QA tool, not throwaway scaffolding.
- **INV-1 (verify at implementation, do not assume):** the pseudolocale *code*
  must be parseable by `babel.Locale.parse()` or Babel raises `UnknownLocaleError`
  on date/number formatting and display-name lookup. Candidate is the CLDR
  pseudo-locale `en_XA`. Decision tree if `Locale.parse('en_XA')` raises: fall back
  to housing the pseudolocale catalog under a real CLDR code the project does not
  otherwise ship — candidate `eo` (Esperanto), which Babel carries and parses — while
  keeping the human-facing dropdown label as the fixed string "Pseudo" (per §4,
  which special-cases `PSEUDO_LOCALE` before the display-name lookup). (Verify the
  chosen code parses; do not assume.) **Resolving INV-1 and pinning the code is the first step of the
  implementation plan.** The resolved value is stored once as
  `services/i18n.py::PSEUDO_LOCALE`; everything that needs it — the Settings label
  fallback (§4), the test (§7), and `docs/specs/i18n.md` (§8) — reads that constant
  rather than hard-coding a string, so a change to the resolved code propagates
  automatically.
- Both `.po` and `.mo` are committed so no runtime compile step is needed — this
  matters for the source-zip and PyInstaller distributions, which have no build
  step on the user's machine.
- **Distribution check:** `.gitignore` has no rule touching `translations/` /
  `.po` / `.mo` / `.pot`, and `build_dist.py`'s exclude lists (`EXCLUDE_DIRS`,
  `EXCLUDE_EXTENSIONS`) don't drop them — so the **source zip** is safe (re-confirm
  at implementation). The **PyInstaller standalone is NOT safe as-is:**
  `retrodb.spec`'s `DATAS` list (an explicit whitelist, `retrodb.spec:84`) has no
  `translations/` entry, so the bundle would silently ship without catalogs. Add
  `('translations', 'translations')` to `DATAS` — confirmed-required, not
  conditional.

### 6. Pilot migration

- `templates/login.html`: wrap server-rendered visible strings in `{{ _() }}`,
  including any user-visible attribute strings **where present** (`title=` /
  `aria-label=` / `placeholder=`) — on this page that is `placeholder="Enter admin
  password"` (login.html has no `title=`/`aria-label=`), so don't hunt for absent
  attributes. The `<script>`
  block's JS error strings are **left in English on purpose** — that is the
  Pass 43.3 boundary, and the pilot makes it visible. Mark it with a
  `{# i18n: Pass 43.3 boundary — JS strings localized separately #}` comment above
  the `<script nonce="{{ csp_nonce }}">` block (note the nonce attribute — it is not
  a bare `<script>`) so a later reviewer/CI does not "helpfully" wrap them.
- `routes/auth.py`: wrap the logout flash as `flash(_('You have been logged out'),
  'info')`. The msgid must match the source literal byte-for-byte; confirm it at
  `routes/auth.py:141` at implementation (currently `'You have been logged out'`),
  since a mismatched msgid silently makes the pilot's only Python-path test a no-op.
- **Pilot is `login.html`** (decided): highest-visibility page (first screen every
  user sees), pure server-rendered body. `force_change_password.html` is *not* the
  pilot — it is noted only as the smallest pure-server template, should a partly
  localized login page ever need a fallback demonstration.
- **Acceptance criterion:** under the pseudolocale, every visible string in the
  rendered `login.html` body shows the pseudolocale brackets — except the `<script>`
  block's JS strings, which stay English (the Pass 43.3 boundary) — and the logout
  flash renders bracketed after a logout. This is the observable done-condition the
  §7 tests pin.

### 7. Tests (`tests/test_i18n.py`)

Regression pins (not correctness proofs):

- **Selector precedence:** user pref > session > Accept-Language > default, each
  branch exercised, including the guard that a stale/removed locale falls through
  to `'en'` rather than raising.
- **`available_locales()`** enumerates installed catalogs + `'en'`.
- **Validator:** accepts an installed locale, rejects an unknown one.
- **Pseudolocale render:** a wrapped pilot string renders differently from English
  under the pseudo-locale; a deliberately-**unwrapped** control string stays
  English (this is the coverage signal the pseudolocale exists to provide). The
  test parametrizes on `services/i18n.py::PSEUDO_LOCALE` (§5), never a hard-coded
  locale string, so resolving INV-1 updates it automatically.
- **Pilot completeness scan:** render `login.html` under the pseudolocale using the
  project's existing `app_client` fixture (`tests/conftest.py` — function-scoped,
  sets `TESTING=True`; reuse it, don't hand-roll `app.test_client()`). Drive the
  locale by sending an `Accept-Language: <PSEUDO_LOCALE>` header on the request
  (the canonical drive — simplest, and it exercises the selector's real
  `best_match` branch; the `session['locale']` path would need
  `client.session_transaction()` and is not worth it here). Then remove the
  `<script>…</script>` block, and assert the pseudolocale bracket marker appears on
  **both** (a) every remaining visible text run that contains letters, **and**
  (b) every **non-empty** user-visible attribute value among `placeholder` /
  `title` / `aria-label` — skip empty/whitespace values (login.html carries two
  decorative `alt=""` attributes that are correctly untranslated). On this page the
  lone in-scope attribute string is `placeholder="Enter admin password"` (§6).
  Checking text runs alone would let a missed `placeholder`/`title`/`aria-label`
  pass silently, leaving §6's "every visible string" acceptance criterion unpinned
  for attributes. (A single-string assertion would likewise let a missed text run
  pass.)

Per project rules, run the new test against a staged-only tree
(`git stash --keep-index && pytest tests/test_i18n.py && git stash pop`) before
committing, since it imports new symbols.

### 8. Docs & workflow

- New project spec `docs/specs/i18n.md` — **note the tree:** this *design* doc
  lives under `docs/superpowers/specs/` (the cold-eyes-gated design-doc tree); the
  shipped *contract* doc lands in the pre-existing `docs/specs/` tree alongside the
  other contract docs (`auth.md`, `api-contracts.md`, `themes.md`). Don't file
  `i18n.md` under `docs/superpowers/specs/`. It covers the wrap-new-strings
  contract, the selector chain, the catalog regeneration workflow (`pybabel
  extract` → `gen_pseudolocale.py` → `pybabel compile`), and the chosen pseudolocale
  code. (CLAUDE.md's "Reference Documents" list enumerates the standards docs but
  **none** of the `docs/specs/` contract docs (8 today — `api-contracts`, `auth`,
  `image-pipeline`, `jobs`, `migrations`, `scrapers`, `settings`, `themes`; 9 once
  `i18n.md` lands). Rather than cherry-pick `i18n.md` into the list — a lopsided
  one-of-nine index — add a single directory-level entry for the whole tree, e.g.
  `docs/specs/` — per-feature design contracts. See the Definition-of-done item
  below; this CLAUDE.md edit lands together with `i18n.md` so the entry never
  dangles.)
  Use **"catalog"** as the canonical term for a locale's `.po`/`.mo` pair
  throughout; "language pack" is the roadmap's user-facing synonym, not a second
  concept.
- Add a one-line "wrap user-facing strings in `_()`" item to the CLAUDE.md
  **"After Every Code Change"** mandatory-workflow list — in this pass, as part of
  landing the foundation (not a follow-up).
- Version bump (minor — new feature) to `3.7.0` + `data/changelog.yaml` entry per
  mandatory workflow. Bump *from whatever `config.py::APP_VERSION` reads at
  implementation* (it is `3.6.37` as of this spec, but patch releases may land
  first — don't hard-code the source version).
- **Audit gate:** a minor bump (`x.N+1.0`) is a CLAUDE.md trigger for the Periodic
  Independent Review. Run it before shipping 3.7.0, or explicitly record a deferral
  — do not let the bump skip the gate silently.
- **Roadmap re-scope:** roadmap `#### Pass 43.1` already carries the interim
  `> Re-scoped (design pending)` banner (added with this spec). When the foundation
  lands, **trim the now-stale body bullets** below that banner to the machinery+pilot
  scope (they currently still read as "extract first language pack" across all ~45
  files with a `de/fr/es/it/ja/pt_BR` roster and a `settings.html` Language section).
  Then **create** a new numbered follow-on pass — next free id under the
  i18n section is `#### Pass 43.5` (43.4 is RTL), e.g. `#### Pass 43.5 Bulk
  template/string migration + real-language catalogs` — and move the bulk template
  migration + real-language roster into it; the §Out-of-scope list below enumerates
  its contents. Referencing the out-of-scope list is **not** a substitute for a real
  roadmap home — without the numbered pass, the deferred scope reads as silently
  abandoned. Both edits land when the foundation lands. (Hand-edit `roadmap.md`
  directly — the `roadmap_log` flip/annotate path is unreliable on this
  `#### Pass N.M` heading format.)

### Definition of done (this pass)

The roadmap edits below are **deliverables of this pass, not optional follow-ups** —
an implementer who completes §1–§7 but skips them leaves the deferred scope homeless
and the roadmap entry stale. Done = all of:

1. §1–§3 machinery wired; `services/i18n.py` + `available_locales()` import-testable.
2. §4 `locale_preference` column + validator + Settings `<select>` shipped.
3. §5 pseudolocale generated (`.po` + `.mo` committed); `translations/` bundled in
   `retrodb.spec` `DATAS`.
4. §6 pilot (`login.html` + logout flash) passes the §7 completeness scan.
5. §7 `tests/test_i18n.py` green against a staged-only tree.
6. §8 docs: `docs/specs/i18n.md` created **and the `docs/specs/` tree added as a
   directory-level entry in CLAUDE.md's "Reference Documents" list** (it lists none
   of the contract docs today); CLAUDE.md "After Every Code Change" line added.
7. **Roadmap: `#### Pass 43.1` re-scoped to machinery+pilot, AND `#### Pass 43.5`
   (bulk migration + real catalogs) created** with the §Out-of-scope contents moved in.
8. Version bumped to `3.7.0`; changelog entry; audit gate run or deferral recorded.

## Risks / open items

- **INV-1** (pseudolocale code parseability) — verify before committing the
  generator; see §5.
- **Distribution bundling** — `translations/` must reach both the source zip and
  the PyInstaller bundle; verify against `build_dist.py` and `retrodb.spec`.
- **`g.user_settings` shape** — it is a plain `dict` (derivation in §2), so
  `.get('locale_preference')` returns `None` on a legacy row that predates the
  column — the selector chain treats that the same as "unset" and falls through. No
  `sqlite3.Row` / `.keys()` idioms. Note that some existing call-sites
  (`app.py:750`, `app.py:802`) still
  hedge with `hasattr(obj, 'get')` / `.keys()` for legacy defensiveness; the new
  selector relies on the verified `dict` guarantee and need not copy that hedge —
  but do **not** "fix" those existing sites in this pass (out of scope).

## Out-of-scope follow-ons (roadmap)

- Pass 43.2 — canonical-label display helper (`services/i18n_labels.py`).
- Pass 43.3 — JS `window.I18N` bundle + `t()` helper + missing-key CI check.
- Bulk migration of the remaining 60 templates + Python flash/error sites.
- Real human-language catalogs + a CI extraction-freshness gate.

## Cold-eyes loop log

Reviewed per global rule §14 (3 independent cold reviewers per loop — machinery
§1–§4, pseudolocale/pilot/tests/dist §5–§8, cross-cutting spec↔roadmap↔CLAUDE.md —
each briefed with no prior-loop context). Every actionable finding (CRITICAL→LOW)
verified against current source before fixing.

- **Loop 1 (2026-06-10):** 9 verified fixed — `PASS-43-N`→`Pass 43.N` (roadmap greps
  the heading form), repo-root `settings_manager` qualified, full a11y `themeSelector`
  quote, `retrodb.spec DATAS` confirmed-required, `get_display_name` verify-at-impl
  hedge, §8 follow-on-pass creation, "Components at a glance" + key-constants index,
  roadmap-first redirect note, `.get()`-vs-hedge note.
- **Loop 2 (2026-06-11):** 5 verified fixed — two-spec-tree split explained, version
  bump source de-hardcoded, `allowed_fields` pointed at canonical block, CLAUDE.md
  list named, Definition-of-done checklist added.
- **Loop 3:** 7 fixed (incl. one HIGH self-introduced in loop 2 — the CLAUDE.md
  "Reference Documents" claim — corrected); `:320-323` block cite, §7 test-client
  mechanism, §6 attribute scope, roadmap `> Re-scoped` banner added, dedup.
- **Loop 4:** 6 fixed — §7 reuse existing `app_client` fixture + pin attribute values,
  §2 subscript-also-works clarification, stale "still full-scope" wording, `docs/specs/`
  directory-entry recommendation.
- **Loop 5 (cap):** 3 fixed — `docs/specs/` count `~9`→8, §7 skip empty `alt=""` +
  scope attributes, `Accept-Language` named canonical drive. 1 finding dismissed
  (a reviewer's off-by-one on `auth.py:198` — verified the cite is correct).
  Accepted as known: the 45/46/60/61 template counts are individually correct,
  internally consistent, and reconciled in §Goal.

Substance (locale chain, settings persistence, INV-1/pseudolocale, pilot,
distribution, tests) verified stable from loop 1; later loops converged on prose in
the fixes themselves. Accepted implementation-ready at the loop-5 cap.
