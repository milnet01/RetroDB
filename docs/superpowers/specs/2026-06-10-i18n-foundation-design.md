# i18n Foundation — Design (Pass 43.1, machinery + pilot)

**Date:** 2026-06-10
**Roadmap:** PASS-43-1 (this spec). PASS-43-2 (canonical-label helper) and
PASS-43-3 (JS-side `window.I18N`) are explicitly deferred to their own passes.
**Status:** design — pending cold-eyes + implementation plan.

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
- Translating canonical genre/perspective/dimension **labels** — that is PASS-43-2.
- JS-constructed strings (toasts, modals) via `window.I18N` — that is PASS-43-3.
  The pilot deliberately leaves `login.html`'s `<script>` error strings in English
  to mark this boundary.
- An anonymous-user locale-switcher UI. Anonymous requests fall back to the
  `Accept-Language` header.

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
`query(..., one=True)`, which returns `dict(row)`), so access is `.get()`, not
`sqlite3.Row` idioms:

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

- **Global settings** (`settings.json`) — keys in `settings_manager.DEFAULT_SETTINGS`,
  saved via `/api/settings`, validated by `services/settings_validators.py::_VALIDATORS`
  (whose import-time `_missing` check asserts every `DEFAULT_SETTINGS` key has a
  validator). The `theme` key here is a *different, unrelated* setting.
- **Per-user settings** (`user_settings` DB columns, e.g. `theme_preference`,
  `timezone`, `ra_username` — note `avatar` is a column too but is deliberately
  kept OUT of `allowed_fields` for path-traversal safety, so don't copy it into the
  list) — saved via `routes/auth.py::api_user_settings`
  (`/api/users/settings`) through a hard-coded `allowed_fields` list. **This is where
  `locale_preference` lives.** Do **not** register it in `settings_validators.py`.

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
  id="themeSelector" role="radiogroup">` at `library.html:58`). The Theme control is
  a radiogroup of clickable divs that applies instantly and auto-saves via
  `ThemeManager.apply()`. The Language control does **not** mirror that: it is a
  plain `<select>` POSTed to `/api/users/settings` like the other per-user fields. On
  a `200` the settings JS calls `location.reload()` so the page re-renders in the
  new locale; an already-open second tab keeps the old locale until its own reload
  (acceptable for v1 — no live broadcast). Options are enumerated from
  `available_locales()`, each labelled via
  `babel.Locale.parse(code).get_display_name(code)` (endonym). Two label
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
- **Distribution check:** confirm `translations/` is not dropped by `.gitignore`,
  by `build_dist.py`'s exclude lists, or by `retrodb.spec` (PyInstaller must bundle
  `translations/**`). Add to the spec's `datas`/whitelist if absent.

### 6. Pilot migration

- `templates/login.html`: wrap server-rendered visible strings in `{{ _() }}`,
  including `title=` / `aria-label=` / `placeholder=` attributes. The `<script>`
  block's JS error strings are **left in English on purpose** — that is the
  PASS-43-3 boundary, and the pilot makes it visible. Mark it with a
  `{# i18n: PASS-43-3 boundary — JS strings localized separately #}` comment above
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
  block's JS strings, which stay English (the PASS-43-3 boundary) — and the logout
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
- **Pilot completeness scan:** render `login.html` under the pseudolocale, remove
  the `<script>…</script>` block, and assert every remaining visible text run that
  contains letters carries the pseudolocale bracket marker — i.e. no English string
  survived unwrapped outside the JS boundary. This is the test that actually pins
  §6's "every visible string" acceptance criterion (a single-string assertion would
  let a missed string pass silently).

Per project rules, run the new test against a staged-only tree
(`git stash --keep-index && pytest tests/test_i18n.py && git stash pop`) before
committing, since it imports new symbols.

### 8. Docs & workflow

- New project spec `docs/specs/i18n.md`: the wrap-new-strings contract, the
  selector chain, the catalog regeneration workflow (`pybabel extract` →
  `gen_pseudolocale.py` → `pybabel compile`), and the chosen pseudolocale code.
  Use **"catalog"** as the canonical term for a locale's `.po`/`.mo` pair
  throughout; "language pack" is the roadmap's user-facing synonym, not a second
  concept.
- Add a one-line "wrap user-facing strings in `_()`" item to the CLAUDE.md
  mandatory-workflow — in this pass, as part of landing the foundation (not a
  follow-up).
- Version bump (minor — new feature: `3.6.37` → `3.7.0`) + `data/changelog.yaml`
  entry per mandatory workflow.
- **Audit gate:** a minor bump (`x.N+1.0`) is a CLAUDE.md trigger for the Periodic
  Independent Review. Run it before shipping 3.7.0, or explicitly record a deferral
  — do not let the bump skip the gate silently.
- **Roadmap re-scope:** update roadmap Pass 43.1 to reflect this machinery+pilot
  scope (it currently reads as "extract first language pack" across all ~45 files
  with a `de/fr/es/it/ja/pt_BR` roster and a `settings.html` Language section). The
  bulk template migration + real language roster move to a new follow-on pass — see
  the §Out-of-scope list. Do this when the foundation lands so the roadmap entry
  doesn't read as silently abandoned.

## Risks / open items

- **INV-1** (pseudolocale code parseability) — verify before committing the
  generator; see §5.
- **Distribution bundling** — `translations/` must reach both the source zip and
  the PyInstaller bundle; verify against `build_dist.py` and `retrodb.spec`.
- **`g.user_settings` shape** — it is a plain `dict` (`get_user_settings` →
  `query(..., one=True)` → `dict(row)`), so access is `.get('locale_preference')`, which
  returns `None` on a legacy row that predates the column — the selector chain
  treats that the same as "unset" and falls through. No `sqlite3.Row` / `.keys()`
  idioms.

## Out-of-scope follow-ons (roadmap)

- PASS-43-2 — canonical-label display helper (`services/i18n_labels.py`).
- PASS-43-3 — JS `window.I18N` bundle + `t()` helper + missing-key CI check.
- Bulk migration of the remaining 60 templates + Python flash/error sites.
- Real human-language catalogs + a CI extraction-freshness gate.
