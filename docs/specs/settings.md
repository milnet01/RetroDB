# Settings Architecture

> Where each RetroDB setting lives, how it is validated, and how to add a new
> one without breaking the precedence rules or the atomic-write contract.

## Purpose

RetroDB has accumulated six overlapping settings stores. Some are baked at
install time (`config.py`), some are operator-overridable via environment
variables, some are user-editable through the admin UI as JSON blobs on disk,
and one (per-user OAuth tokens) lives in SQLite so multi-user installs don't
leak credentials. This split exists for good reasons — different settings have
different update cadences, owners, and crash-safety needs — but it makes "where
does this live?" a recurring question. This document is the single map of the
territory: pick the right store, wire a validator, and the rest of the system
will load the value through helpers that handle caching, atomic writes, and
authorization.

## The six stores

We count by storage medium (file / env / SQLite row): two storage media for
`config.py` + env vars, three JSON files, and one DB table. Source-of-truth
precedence is the separate axis covered under "Precedence" below.

| Store | Format | Owner | Writeable from UI? | Validator |
| --- | --- | --- | --- | --- |
| `config.py` + `config.example.py` | Python module | dev / installer | No (edit file + restart) | n/a — module-load is the validator |
| Environment variables (`RETRODB_*`, plus `PORT`) | env | operator / process manager | No | n/a — read into `config.py` at import time, EXCEPT the bind port, which `server_port.py` range-validates |
| `data/settings.json` | JSON object | UI (Settings page, `@admin_required`) | Yes | `services/settings_validators.py` (`validate_settings_value`) |
| `data/scraper_settings.json` | JSON object | UI (Scraper Config page, `@admin_required`) | Yes | `services/scraper_settings_validators.py` (`validate_scraper_settings` + `validate_scraper_api_keys`) |
| `data/rom_tools_config.json` | JSON object | UI (ROM Tools Settings, `@admin_required` on POST) | Yes | `services/rom_tools_validators.py` (`validate_rom_tools_value`) |
| DB `user_platform_tokens` table | SQLite row per `(user_id, platform)` | UI (login / OAuth flow, per user) | Yes — owned by the authenticated user | `services/platform_tokens.py` accessor (typed JSON blob) |

The DB-backed token row lives behind the same kind of typed accessor module
as the JSON stores; it appears in the table for symmetry.

### What lives where

- **`config.py`** — `APP_VERSION`, `APP_LAST_UPDATE`, `BASE_DIR`, `BUNDLE_DIR`,
  `DB_PATH`, `STATIC_PATH`, `IMAGE_PATH`, slow-query thresholds, image-format
  default, max upload size, backup retention, job-history retention. These are
  knobs the developer needs to touch when shipping a release or when an
  operator wants to harden the deployment. The legacy stub fields (`ROM_PATH`,
  `THEGAMESDB_API_KEY`, …) are kept as empty defaults so any old code path
  importing `config.ROM_PATH` still resolves — the real values live in the
  JSON stores. Also the server block (`SERVER_HOST`, `SERVER_PORT`,
  `DEBUG_MODE`) — see Precedence for why `SERVER_PORT` is *not* the bound
  port.
- **Env vars** — `RETRODB_DB_PATH`, `RETRODB_HOST`, `RETRODB_PORT`,
  `RETRODB_DEBUG`, `RETRODB_SECRET_KEY`, `RETRODB_SLOW_QUERY_MS`,
  `RETRODB_SLOW_REQUEST_MS`, `RETRODB_IMAGE_FORMAT`, `RETRODB_MAX_UPLOAD_MB`,
  `RETRODB_MAX_BACKUPS`, `RETRODB_JOB_HISTORY_RETENTION_DAYS`,
  `RETRODB_STATIC_PATH`, `RETRODB_IMAGE_PATH`, and **`PORT`**
  (deliberately un-prefixed — it is the conventional name an external process
  manager sets). All but the bind port are read once at `config.py` import
  time via `os.environ.get(...)`; the port pair (`PORT` / `RETRODB_PORT`) goes
  through `server_port.resolve_server_port()` instead, because a malformed
  value must produce a message and a non-zero exit rather than a `ValueError`
  traceback out of an import. See Precedence below.
- **`data/settings.json`** — every UI-editable preference: paths
  (`rom_path`, `esde_gamelists_path`, …), server port, theme, scraper
  priority/enabled flags, notification timeouts, naming convention, logging
  config, RetroArch launch settings. Full default set lives in
  `settings_manager.DEFAULT_SETTINGS`.

> **Module location.** `settings_manager.py` lives at the **project root**
> (next to `app.py`, `config.py`) and is imported as `import settings_manager`
> — there is no `services.settings_manager` package. Every reference to
> `settings_manager.X` in this spec means the root module.
- **`data/scraper_settings.json`** — scraper `priority`, `enabled`,
  `minimum_match_score`, `match_mode`, `match_criteria`, and the `api_keys`
  block (TGDB, IGDB, RAWG, ScreenScraper, RetroAchievements, Steam, Xbox, and
  the AI provider keys).
- **`data/rom_tools_config.json`** — ROM Tools paths (`roms_path`,
  `output_path`, `temp_path`), `chdman_path`, scanner toggles
  (`scanner_types`, `scanner_modes`), CHD options
  (`chd_verify_after_convert`, `chd_delete_originals`, `chd_skip_existing`),
  duplicate-finder mode, archive-type allowlist.
- **`user_platform_tokens`** — JSON-encoded OAuth blob per
  `(user_id, platform)` for `psn` and `xbox` sync. Replaced the legacy shared
  `data/psn_tokens.json` / `data/xbox_tokens.json` files in Pass 27.2 because
  those leaked the first authenticated user's tokens to every subsequent
  user.

## Precedence

For values that exist in more than one store, the resolution order is:

1. **Environment variable** (`RETRODB_*`, plus `PORT` for the bind port) —
   wins if set. Read at `config.py` import time, so changes require a
   restart.
2. **`data/settings.json` user value** — wins for every key present in the
   file, `_RETIRED_SETTINGS` excepted. Membership in
   `settings_manager.DEFAULT_SETTINGS` governs whether a key gets a *default*,
   not whether its saved value wins. For paths specifically, the helper
   `settings_manager.get_effective_path(key, config_fallback='')` returns the
   user value when non-empty, otherwise the `config_fallback` (which is
   always `''` in normal operation — paths are UI-only since Pass 32.1).
3. **`settings_manager.DEFAULT_SETTINGS` literal** — the fallback baked into
   `settings_manager.py`, used when `settings.json` is missing the key. The
   `_deep_merge` in `load_settings()` overlays saved values on top of these
   defaults so a newly-added default automatically appears for existing
   installs. **Caveat:** `_deep_merge` recurses on dicts only — list-valued
   defaults (e.g. `scraper_priority`, `region_options`) are replaced
   wholesale by the saved value, so adding a new entry to a list default
   will NOT appear for an existing install. For those, ship a migration
   that mutates `data/settings.json` instead of relying on default-overlay.
4. **`config.py` literal** — the last-resort floor, NOT a tier above the
   saved value. It is what a resolver passes as its `default` argument
   (`resolve_server_port(default=config.SERVER_PORT, …)`,
   `get_effective_path(key, config.ROM_PATH)`), so a saved user value beats
   it. Ranking it second — which this list did until v3.23.1 — inverts the
   order for every dual-store key.

The collision points worth knowing:

- `server_port` exists as the `PORT` / `RETRODB_PORT` env vars AND as a
  `server_port` key in `settings.json`. The root-level `server_port.py`
  resolves the whole chain in one place — `PORT` → `RETRODB_PORT` → saved
  `server_port` → 5000. The environment always wins, so an external process
  manager is never overridden by a stored value. The saved tier is read
  *inside* the resolver, never at module scope: `settings_manager` imports
  `config`, so `config.py` cannot read the setting back without a circular
  import. That direction-of-dependency is why the key sat unread from its
  introduction until v3.23.1 — validated, stored, and reported as
  restart-required while nothing ever bound it.
  - **Absence and invalidity are different, and differ by channel.** An unset
    or empty env var falls through to the next tier; a *malformed* one is
    fatal — `resolve_server_port()` raises and `app.py`'s `__main__` prints
    the offending value and exits non-zero, because a supervisor that asked
    for a port and silently got another has been lied to. The saved tier is
    the opposite: a missing, corrupt, unreadable or no-longer-valid
    `settings.json` warns on stderr and falls through. The port the
    environment gave you never depends on the settings file being loadable.
  - **Three channels, two ranges, on purpose.** `PORT` is machine-facing and
    accepts 1024-65535 only; `RETRODB_PORT` and the settings-UI validator
    accept 1-65535, because a human choosing a privileged port for their own
    machine is their call. Both `server_port.py` and
    `services/settings_validators.py` carry a do-not-unify comment. Pinned by
    `tests/test_server_port.py` and `tests/test_settings_bind_config.py`.
  - **Five consumers resolve this chain; all of them include the saved tier.**
    `app.py`'s `__main__` (`use_saved=True`) is the one that binds;
    `scripts/retrodb_launcher.py` uses it for the `/health` probe and browser
    URL; and `start.sh` / `start.command` / `start.bat` shell out to
    `python3 server_port.py` for their banner and browser-open URL. A change
    to the chain that misses one leaves a script announcing a port the server
    did not bind — or a launcher probing the wrong port, seeing "down", and
    starting a second instance that dies on EADDRINUSE.
  - **`config.SERVER_PORT` is NOT the bound port.** It omits the saved tier by
    design (it is computed at import, before the settings layer is safe to
    touch), so it is env-or-5000 and diverges from the bind whenever a
    `server_port` is saved. It is the resolver's `default` argument, never the
    authoritative answer — ask `resolve_server_port(..., use_saved=True)`.
- **Bind address and debug mode are environment-only**, via `RETRODB_HOST` /
  `RETRODB_DEBUG` → `config.SERVER_HOST` / `config.DEBUG_MODE`, both fixed at
  import of `config`. They were once `server_host` / `debug_mode` keys in
  `settings.json` that nothing read; v3.23.1 removed them rather than wiring
  them up. `debug_mode` would have let a settings request enable Flask's
  debug server, and the Werkzeug debugger is an interactive Python console —
  a remote-code-execution surface reachable from a form, admin-gated or not.
  `server_host` changes which interfaces the app answers on.
  `settings_manager._RETIRED_SETTINGS` drops both from an older
  `settings.json` on load. Do not re-add them to `DEFAULT_SETTINGS`.
- API keys exist as zero-default attributes in `config.py`
  (`THEGAMESDB_API_KEY`, `IGDB_CLIENT_ID`, …) AND as fields under
  `scraper_settings.json#api_keys`. The JSON values always win — the
  `config.py` attributes are vestigial fallbacks for old import paths.

## Atomic-write contract

Every JSON store goes through `services/atomic_io.py:atomic_write_json` (Pass
35). The contract:

1. Open a sibling tempfile `<path>.tmp`.
2. Write the JSON, `flush()`, `fsync(fd)`.
3. `os.replace(tmp, path)` — atomic on POSIX and Windows.
4. `fsync()` the parent directory so the rename's directory-entry update is
   durable.
5. On any exception, `os.remove(tmp)` and re-raise.

Why it matters: power loss or kernel panic between step 2 and step 3 leaves
the original file intact; between step 3 and step 4 (on XFS or a `nobarrier`
mount) the rename can be lost, but never a half-written JSON blob. The plain
`open('w') + json.dump` pattern these helpers replaced could truncate the
target file mid-write — a single crash mid-save would wipe every setting.

The harder-edged sibling `atomic_write_bytes` (Pass 45.5) is used for
secret-bearing writes (`.secret_key`, DB backups) and `chmod`s the tmpfile
to `0o600` *before* the rename, so the final path never exists at the
default umask. Settings JSON uses the `0o644` `atomic_write_json` variant
because the data dir's own permissions are the access boundary.

## Validator pattern

Every persisted UI-writable key has a validator function with the signature:

```python
def _validator(value) -> tuple[bool, str | None, Any]:
    """Returns (ok, reason, cleaned).
    - ok=True,  reason=None,  cleaned=<normalized value>  on success
    - ok=False, reason=<msg>, cleaned=None               on failure
    """
```

Validator constructors live in the three `*_validators.py` modules and
return closures so they can carry parameters (allowed enum sets, length
caps, range bounds). The canonical shape is the `_enum_validator` from
`services/settings_validators.py`:

```python
def _enum_validator(allowed, label):
    def _inner(value):
        if not isinstance(value, str) or value not in allowed:
            return False, f'must be one of {sorted(allowed)}', None
        return True, None, value
    return _inner
```

And the `_positive_int_validator` for ranged ints:

```python
def _positive_int_validator(lo, hi):
    def _inner(value):
        if isinstance(value, bool) or not isinstance(value, int):
            return False, f'must be an integer between {lo} and {hi}', None
        if not (lo <= value <= hi):
            return False, f'must be between {lo} and {hi}', None
        return True, None, value
    return _inner
```

Note the explicit `isinstance(value, bool)` rejection — without it, Python's
`bool ⊂ int` would let `True` slip through as `1` and break downstream
consumers that switch on the value.

**Convention (not enforced by code):** validators are invoked at the
**route layer** (every POST handler runs them before persistence), never
inside service code. Service code reads cached values via the store's
manager helper and trusts the shape. This separation means:

- Route validates → cleaned value → write.
- Service reads → already-clean value → use.

The validator modules themselves live under `services/`
(`services/settings_validators.py`, `services/scraper_settings_validators.py`,
`services/rom_tools_validators.py`), but the call-sites are the route
modules (`routes/settings.py`, `routes/scraper.py`, `routes/tools.py`). No
test pins this — if a future service-layer caller imported a validator the
build would still pass; the rule is a code-review concern.

**The one sanctioned exception is re-validation on read at startup.**
`server_port.saved_server_port()` calls `validate_settings_value('server_port',
…)` outside any route, because `data/settings.json` is a plain file an operator
can hand-edit — a stored value need not have come through a POST handler, so
"service reads → already-clean value" does not hold for it. Deleting that call
as a convention violation would restore the hole. A read-side validator is
correct wherever the store is hand-editable AND the consumer cannot tolerate a
bad value; it is not a licence to validate everywhere.

The settings-validators module has an import-time cross-check
(`services/settings_validators.py:315`, inside the block starting at line
313) that raises `RuntimeError` if anyone adds a new key to
`DEFAULT_SETTINGS` without wiring a validator entry. Adding a key without
the validator turns the next `import settings_validators` into a startup
error — the test suite catches it before merge.

## API endpoints

All routes below are admin-gated (`@admin_required`) after Pass 41.10
unless explicitly noted.

| Endpoint | Method | Validator | Store |
| --- | --- | --- | --- |
| `/api/settings` | GET | n/a | `data/settings.json` |
| `/api/settings` | POST | `validate_settings_value` per key (Pass 32.2) | `data/settings.json` |
| `/api/settings/reset` | POST | n/a (reset to `DEFAULT_SETTINGS`) | `data/settings.json` |
| `/api/settings/paths` | GET | n/a | `data/settings.json` |
| `/api/settings/paths` | POST | `validate_settings_path` (Pass 32.1) | `data/settings.json` |
| `/api/settings/logging` | POST | `validate_settings_value('logging', …)` (Pass 45.11) | `data/settings.json` |
| `/api/settings/retroarch/detect` | POST | n/a (probe only) | reads only |
| `/api/settings/emulators/detect` | POST | n/a (probe only) | reads only |
| `/api/scraper-settings` | GET | n/a | `data/scraper_settings.json` |
| `/api/scraper-settings` | POST | `validate_scraper_settings` (Pass 45.11) | `data/scraper_settings.json` |
| `/api/scraper-api-keys` | POST | `validate_scraper_api_keys` (Pass 45.11) | `data/scraper_settings.json#api_keys` |
| `/api/rom-tools/settings` | GET | n/a (login-required, not admin — scanner UI reads it) | `data/rom_tools_config.json` |
| `/api/rom-tools/settings` | POST | `validate_rom_tools_value` per key (Pass 40.1) | `data/rom_tools_config.json` |
| `/api/dropdown-options/<category>` | GET/POST/DELETE | column allowlist via `safe_column` | DB (`dropdown_options`) |

The `/api/rom-tools/settings` GET is intentionally `@login_required` rather
than `@admin_required` because the archive-scanner page (accessible to
Player role) reads `roms_path`, `excluded_paths`, and `unwanted_patterns` to
populate its scan UI. POST is gated at the handler with an explicit role
check (`g.user.get('role') != 'admin'`) — the only mutating-but-not-`@admin_required`
endpoint in this surface.

## Per-key vs full-replace POST

| Endpoint | Validation strategy | Why |
| --- | --- | --- |
| `/api/settings` POST | Per-key loop, validator per key (Pass 32.2) | Frontend posts only the keys it changed; reject unknown keys with 400, write cleaned values into a copy of current settings, save once. |
| `/api/settings/paths` POST | Per-key loop over four fixed path keys | Same shape as `/api/settings` POST but bypasses the full validator table — paths predate the per-key map and have their own filesystem-path validator (`validate_settings_path`). |
| `/api/settings/logging` POST | Single-key (`'logging'`) full-replace | The logging block is treated atomically because a half-applied logging config breaks `log_manager.setup_all_logging()` on next start. |
| `/api/scraper-settings` POST | Full-body validate-then-merge | Validator returns the cleaned body; route then preserves `api_keys` and the match-filter keys from disk so the Scraper Config page can save priority/enabled without touching credentials. |
| `/api/scraper-api-keys` POST | Full-body validate-then-merge | Same shape as scraper-settings, but with masked-sentinel pass-through (Pass 26.5): the route swaps `***`-prefixed values for the prior stored value before validation, so the UI can echo masked keys back without losing them. |
| `/api/rom-tools/settings` POST | Per-key loop, validator per key (Pass 40.1) | Same per-key strategy as `/api/settings` POST. `chdman_path` flows into `subprocess.run` argv[0], so the per-key validator is the security boundary against CWE-78. |

## Adding a new setting

Worked example: adding `enable_telemetry` (boolean, defaults off, UI toggle
in the Settings page).

0. **Name the consumer.** Write down which code path will read the key,
   before anything else. A key that nothing reads does not go on the surface
   at all — see Known invariants; this is the check `server_port` went years
   without, and it is the cheapest step here to skip and the most expensive
   to discover later.
1. **Pick the store.** UI-editable boolean preference → `data/settings.json`,
   not `config.py` (no env-var override needed) and not `scraper_settings.json`
   (not scraper-scoped).
2. **Add the default.** In `settings_manager.DEFAULT_SETTINGS`, add
   `'enable_telemetry': False`. Place it near the other feature-toggle
   booleans for readability. Steps 2 and 3 are one edit: a default with no
   validator raises `RuntimeError` at import of `services.settings_validators`,
   so a tree stopped between them will neither boot nor test. If the default
   is a **list** (or you are adding an entry to an existing list default),
   stop and read Precedence tier 3 — `_deep_merge` replaces lists wholesale,
   so existing installs will silently not pick it up and you need a migration
   instead.
3. **Add the validator entry.** In `services/settings_validators.py`,
   add `'enable_telemetry': _bool_validator,` to the `_VALIDATORS` dict.
   The import-time cross-check at the bottom of that module fails the
   import if you skip this step.
4. **Decide on restart semantics.** List the key in
   `settings_manager.RESTART_REQUIRED_SETTINGS` if a restart is what makes
   the new value take effect — a startup-bound key like `server_port` must be
   listed; a per-call reader may still be listed where a restart is the
   conservative advice (`rom_path` is). A key with no reader at all is never
   listed, because it should not be on the surface in the first place — that
   is step 0, and Known invariants states it.
5. **Wire the UI.** Add the toggle to the relevant settings-page partial
   under `templates/_settings_tabs/<tab>.html` — pick from `account`,
   `library`, `scraping`, `data`, `customization`, `system` (Pass 38.6 split
   `templates/settings.html` into these six partials). The frontend save
   handler lives in `static/js/settings-page.js` (launch-emulator-specific
   keys belong in `static/js/emulators-settings.js`). The value rides in
   the next `/api/settings` POST.
6. **Add a test.** In `tests/test_launch_settings_validators.py` (the
   canonical home for new validator tests; previously-named
   `test_settings_validators.py` does not exist — don't create it),
   add `_ok('enable_telemetry', True)` and `_ok('enable_telemetry', 'yes')`
   asserting accept/reject. The fixture pattern (see Testability) does the
   per-test isolation for you.

For `scraper_settings.json` or `rom_tools_config.json` the shape is the
same: add an entry to `_SETTINGS_VALIDATORS` /
`_VALIDATORS` in the corresponding module, then a test.

For a new `RETRODB_*` env var: read it at module top in **both `config.py`
and `config.example.py`**, set the default explicitly, and document it in the
env-var block at the top of both files. `config.py` is gitignored and
user-owned — `installer_core.py` seeds a fresh install from
`config.example.py` — so an edit to `config.py` alone works on your box and
ships nothing. There is no validator; parsing is inline (`int(...)`,
`.lower() in ('true', '1', 'yes')` — match the existing triple, not a
two-value variant). **Exception:** anything whose malformed value should stop the
process with a message rather than a traceback needs a resolver function
called from `app.py`'s `__main__`, not a bare `os.environ.get` at import —
`server_port.py` is the worked example.

## Retiring a setting

The inverse of the above, and not symmetric with it — a stored key outlives
the code that read it. Worked example: `server_host` and `debug_mode` in
v3.23.1, removed rather than wired up because neither belongs behind a web
form (see Precedence).

1. **Drop the default** from `settings_manager.DEFAULT_SETTINGS`.
2. **Drop the `_VALIDATORS` entry** in `services/settings_validators.py`. Skip
   this and `/api/settings` POST keeps *accepting* the key — a write that
   reports success and changes nothing, since `load_settings()` then prunes
   it. The import-time cross-check will not catch the omission — it is
   one-directional; see Known invariants.
3. **Drop it from `RESTART_REQUIRED_SETTINGS`**, or it keeps promising a
   restart will apply a key that no longer exists.
4. **Add it to `settings_manager._RETIRED_SETTINGS`.** `load_settings()`
   filters these out of the saved dict before the default-merge, so an
   existing `settings.json` degrades quietly. Skip this and the dead key is
   carried forward, re-saved forever, and served by `GET /api/settings` as a
   setting that configures nothing.
5. **Remove the UI control** from the relevant `templates/_settings_tabs/`
   partial and its save handler.
6. **Pin it.** `tests/test_settings_bind_config.py` is the pattern — assert
   the key is absent from `settings_manager.DEFAULT_SETTINGS` and from
   `services.settings_validators.known_keys()`, that
   `settings_manager.requires_restart([key])` is False, and that a
   `settings.json` still containing it loads with the key dropped and its
   neighbours intact.

`_RETIRED_SETTINGS` exists only in `settings_manager.py`, and step 4 needs no
counterpart in the other two stores — for opposite reasons, both worth knowing
before you assume either behaves like `settings.json`:

- `scraper_settings.json` — `scraper_manager._load_scraper_settings_locked()`
  merges by an explicit **key allowlist** (`priority`, `enabled`, `api_keys`,
  `minimum_match_score`, `match_mode`, `match_criteria`), so an unknown or
  retired key never reaches the loaded dict at all. Nothing to prune.
- `rom_tools_config.json` — `routes/tools.py::load_rom_tools_config()` does a
  blanket `defaults.update(saved)`, so a retired key **does** survive into the
  loaded dict and gets re-saved, exactly as `settings.json` behaved before
  `_RETIRED_SETTINGS`. It is inert (with the validator gone no POST can set
  it again) but it will keep appearing in that store's GET response. Add the
  analogue there if a retirement ever needs to be invisible.

## Authentication

After Pass 41.10, every settings-mutating endpoint is `@admin_required`.
The exceptions are the GET-only paths used by non-admin pages:

- `/api/rom-tools/settings` GET — `@login_required` only, as above.
- `/api/scraper-settings` GET — `@admin_required` (api_keys are sensitive
  even when displayed; the response masks secret values via
  `mask_api_keys_for_response`).
- `/api/settings` GET — `@admin_required`.

`@admin_required` is the strictest gate in `services/auth.py`'s role
hierarchy. Player and Viewer roles cannot reach any settings mutation;
attempts return 403. CSRF protection applies to every POST through the
Flask app's session middleware.

Per-user OAuth tokens (`user_platform_tokens`) are different — the
`load_tokens(user_id, platform)` accessor takes the `user_id` as a
parameter, and callers must pass the authenticated user's id from
`g.user['id']`. There is no admin path that reads another user's tokens.

## Testability

`tests/test_launch_settings_validators.py` is the canonical pattern. The
helper:

```python
def _ok(key, value):
    from services.settings_validators import validate_settings_value
    ok, _reason, _cleaned = validate_settings_value(key, value)
    return ok
```

…wraps the validator call so test bodies are one-liners
(`assert _ok('launcher_backend', 'local')`). For ROM-tools keys, the
equivalent entry point is `validate_rom_tools_value(key, value)` from
`services.rom_tools_validators` (same shape — `ok, reason, cleaned`).
For tests that need a clean settings file on disk (i.e. exercising the
full route handler, not just the validator), use a `tmp_path` fixture and
monkeypatch `settings_manager.SETTINGS_FILE` to point at the tempdir. The
cache (`_settings_cache_mtime`) invalidates itself by mtime so the test
doesn't need to call `_invalidate_cache()` manually unless it's mutating
the file outside of `save_settings`.

After adding a new validator entry, run
`python3 -m pytest tests/test_launch_settings_validators.py` to confirm
the import-time cross-check still fires — the run fails at import if any
`DEFAULT_SETTINGS` key lacks a validator entry. It is a module-import side
effect, not an assertion in that file, so every other test importing
`services.settings_validators` fails the same way; that file is just the
cheapest place to see it.

**Port resolution** is testable without touching the process environment or
the real settings file: `resolve_server_port(env={...}, use_saved=…)` takes
the environment mapping as a parameter, and the saved tier reads through
`settings_manager.SETTINGS_FILE`, which the fixture above monkeypatches.
`tests/test_server_port.py` covers the two env tiers, the absent/invalid
split and the CLI; `tests/test_settings_bind_config.py` covers the saved
tier, the retired keys and the never-block-the-boot fallbacks.

For the scraper-settings validators, call `validate_scraper_settings(body)`
and `validate_scraper_api_keys(body)` directly with crafted dicts — they're
pure functions with no filesystem dependency.

## Known invariants

- **Every UI-writable key has a validator entry.** The import-time check in
  `services/settings_validators.py` enforces it for `DEFAULT_SETTINGS`;
  add the equivalent guard to any future store that grows past a handful
  of keys. (One-directional — see below.)
- **No key claims a restart applies it unless a restart applies it.** Every
  entry in `settings_manager.RESTART_REQUIRED_SETTINGS` must be a key that
  something actually reads, so that restarting genuinely results in the new
  value being used — `requires_restart()` reports it to the client and the
  client tells the operator to restart. The bar is a real consumer, not a
  startup-time one: `server_port` is startup-bound, while `rom_path` is read
  per call (`settings_manager.get_effective_path`) and is listed only because
  a restart is the conservative advice. **A key that is validated and stored
  but never read at all does not belong on the settings surface** — wire it
  up or retire it (v3.23.1, which did one of each). Half machine-checked:
  `tests/test_settings_bind_config.py::test_every_restart_required_key_is_a_real_setting`
  pins surface-membership only; "something reads it" is a review gate, since
  no test can see a reader that does not exist.
- **The environment always beats a stored value, and a broken settings file
  never changes the port.** `PORT` / `RETRODB_PORT` win over the saved
  `server_port`, and a corrupt, missing or unreadable `settings.json` can
  neither move the bind port nor stop the server booting. Pinned by
  `test_environment_still_beats_the_saved_port` and
  `test_environment_port_survives_an_unloadable_settings_file`.
- **The validator cross-check is one-directional.** The import-time guard is
  `set(DEFAULT_SETTINGS) - set(_VALIDATORS)`, so a default without a
  validator raises and a *validator without a default* does not. Retirements
  need the explicit test above; the guard will not catch a half-done one.
- **Every write goes through `atomic_write_json` (or `atomic_write_bytes`
  for secrets).** Plain `open('w') + json.dump` is forbidden — grep
  catches drift at audit time.
- **Read JSON stores via their manager helper, never a fresh `open()` in a
  request handler.** `settings_manager.load_settings()` mtime-caches; the
  scraper-settings reader in `app.py:inject_config` also mtime-caches (Pass
  34.2). Bypassing the cache costs a re-parse per request, which is what
  Pass 34 went out of its way to remove.
- **Path validators run before persistence.** Any path-shaped string (rom
  path, ESDE paths, chdman path, RetroArch binary path) goes through a
  validator that rejects traversal sequences, NUL bytes, and unsafe
  directory roots. The validator is the security boundary — never trust
  the value at the consumer (Pass 32.1, Pass 40.1).
- **Secret round-trip uses masked sentinels.** `/api/scraper-api-keys` POST
  treats any `***`-prefixed value as "unchanged" and keeps the prior
  stored secret (Pass 26.5). The mask-then-validate order is load-bearing:
  the validator sees the *real* value, not the display string.
- **Per-user tokens never share a row.** The `user_platform_tokens` PK is
  `(user_id, platform)`; calls without a `user_id` log a warning and
  return without writing. Multi-user installs depend on this — the legacy
  shared-file design leaked tokens across users (Pass 27.2).

## Cold-eyes loop log

| Loop | Date | Lanes | Findings (C/H/M/L/I) | Dimensions | Outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-08-06 | 2 (general-purpose) | 0/4/9/3/1 | dim 2×5, dim 5×7, dim 4×4, dim 8×3, dim 15×4, dim 6×2 | All verified findings fixed. Two were in text written that same session (the `RESTART_REQUIRED_SETTINGS` invariant was worded so narrowly it condemned `rom_path`; the `server_port` bullet omitted the range split, the absence-vs-invalidity rule and four of five consumers). Pre-existing: the precedence ladder ranked the `config.py` literal above the saved value, inverting the order for every dual-store key. |
| 2 | 2026-08-06 | 2 (general-purpose) | 0/3/8/9/1 | dim 2×6, dim 5×6, dim 4×5, dim 12×3, dim 6×3, dim 1×1 | Converged **for the changed section** — one lane checked the `server_port` ladder, every sub-bullet and the new "Retiring a setting" procedure step-by-step and returned no finding against them. Remaining loop-2 findings in text written this session were fixed (step-4 ordering contradiction, unqualified `known_keys()`, missing cross-store note, over-broad claim about the other two loaders — corrected after executing it). The rest are pre-existing defects in sections this change never touched (atomic-write contract, dropdown-options endpoints, CSRF description, admin-gating contradiction, secret-key precedence) and are filed, not folded into a bug-fix commit. |
