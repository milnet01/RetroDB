# Auth & Authorization — Spec

> Status: living spec. Source of truth = the code referenced inline. When code
> diverges, fix the code or amend this doc — don't let the two drift.

## 1. Purpose

RetroDB is a multi-user retro-library manager. Auth and authorization exist
to (a) keep one user's library, ratings, sync history, completion progress,
recently-viewed list, and platform-account credentials from leaking into or
being mutated by another user; (b) gate destructive and admin-only routes
behind explicit role / permission checks; (c) ship a credible password and
session story for a Flask-on-localhost-or-LAN deployment without depending
on an enterprise IdP. This spec captures the contract every route, migration,
and feature has to honour — it supersedes the half-page summary in
`docs/RETRODB_DESIGN_STANDARDS.md §22`, which is now a pointer.

---

## 2. Roles

Defined in `services/auth.py::ROLE_PERMISSIONS`. Four roles; full permission
breakdown in §3. `VALID_ROLES = tuple(ROLE_PERMISSIONS.keys())` is the
single source of truth for accepted role values on user create/update
(Pass 44 hoist).

| Role   | Intent                                       |
|--------|----------------------------------------------|
| admin  | Owner / operator of the install              |
| editor | Trusted user who curates the library         |
| player | Household / LAN user who plays the library   |
| viewer | Read-only browser of the library             |

**Constraints:**
- Every role requires a password (Pass 24.1). Pre-Pass-24 editor/viewer
  rows with `password_hash IS NULL` are dormant — login refuses with
  *"This account has no password set. Ask an administrator to set one."*
- The last active admin cannot be deleted (`api_delete_user` guard); a
  user cannot delete themselves.

---

## 3. Permissions

Permissions are discrete strings. `has_permission(perm)` returns True iff
`perm in ROLE_PERMISSIONS[g.user['role']]`. Adding a permission means
(a) granting it to the right rows in the table and (b) decorating the
guarded routes — never just one.

| Permission         | Meaning                                                                 | admin | editor | player | viewer |
|--------------------|-------------------------------------------------------------------------|-------|--------|--------|--------|
| `view`             | Read the library (games, systems, collections, reports)                 | yes   | yes    | yes    | yes    |
| `edit`             | Mutate game metadata (manual edits, AI Fill, bulk edit)                 | yes   | yes    | no     | no     |
| `delete_metadata`  | Delete a game row from the DB (keeps the ROM file)                      | yes   | yes    | no     | no     |
| `delete_rom`       | Delete the ROM file from disk                                           | yes   | no     | no     | no     |
| `scrape`           | Run single or bulk scrapes; sync RA / Steam / Xbox / PSN libraries      | yes   | yes    | no     | no     |
| `launch`           | Launch a game via the configured emulator command                       | yes   | yes    | yes    | no     |
| `track_progress`   | Toggle completion status, record last-viewed timestamps                 | yes   | yes    | yes    | yes    |
| `manage_users`     | Create / update / delete / reset users                                  | yes   | no     | no     | no     |
| `manage_settings`  | Mutate global settings, scraper settings, rom-tools config              | yes   | no     | no     | no     |
| `system_functions` | Log management, maintenance, restart, log rotation                      | yes   | no     | no     | no     |

**Tricky cells:**
- `track_progress` belongs to every signed-in role (Pass 45.1) — marking
  your own copy as played and recording last-viewed are self-tracking,
  not library-editing. Pass 41.9.A decorated `/api/game/<id>/track-view`
  + `/completion` without granting the permission to anyone; both
  endpoints were unreachable until Pass 45.1 (CRITICAL) fixed the matrix.
- `delete_rom` is admin-only; editor's `delete_metadata` removes the DB
  row but not the file on disk — two destructive surfaces, two perms.
- `viewer` can read everything (`view`) and self-track (`track_progress`); no mutating perms — read-only with one self-mutation carve-out.

---

## 4. Route Gating

Four decorators in `services.auth`. Apply exactly one per route — never stack.

| Decorator                       | Passes when                                              | Failure response                                                   |
|---------------------------------|----------------------------------------------------------|--------------------------------------------------------------------|
| `@login_required`               | `g.user` is set                                          | flash + 302 to `/login?next=<url>`                                 |
| `@editor_required`              | role in `('admin', 'editor')`                            | flash + 302 to `/login` (anon) or `/dashboard` (signed in)         |
| `@admin_required`               | role == `'admin'`                                        | same shape as `@editor_required`                                   |
| `@permission_required(perm)`    | `has_permission(perm)` returns True                      | JSON envelope on `/api/*` (401/403), flash + 302 on page routes    |

```python
@bp.route('/api/game/<int:game_id>/completion', methods=['POST'])
@permission_required('track_progress')
def api_update_completion(game_id):
    ...
```

**Where to put each one:**
- `@login_required` for any-signed-in-user endpoints (account settings,
  profile reads). Use a permission decorator instead if the access is
  finer-grained.
- `@editor_required` for every destructive metadata / scrape endpoint
  (delete game, rename ROM, edit, bulk edit, bulk scrape). Pinned by
  `tests/test_auth_hardening.py::TestEditorRequiredOnDestructiveEndpoints`
  — regex over each file asserts `@editor_required` (not
  `@login_required`) appears above each named view.
- `@admin_required` for user / settings management and install-global
  actions.
- `@permission_required(perm)` for finer-grained gates (`launch`,
  `track_progress`, `system_functions`).

**Footgun history (Pass 41.1.A):** the legacy 5-name endpoint allow-list
inside `login_required` (`auth.login`, `auth.api_login`, `static`,
`help_page`, `changelog`) was removed. Any future endpoint colliding with
one of those names became silently public. Public pages must simply not
apply the decorator — there is no allow-list.

**Pass 45.1 contract, now on all four decorators:** the JSON-envelope
branch on `/api/*` is mandatory. A pre-Pass-45.1 decorator returned a 302
on every failure; `fetch()` followed it transparently and the caller saw a
200 of dashboard HTML, which is impossible to handle. Pinned by
`tests/test_pass45_security.py::TestPass45_1TrackProgressPermission`.

`login_required`, `admin_required`, `editor_required` and
`permission_required` all route their refusals through two shared helpers
in `services/auth.py` — `_deny_unauthenticated()` (401 JSON on `/api/*`,
else a 302 to the login page) and `_deny_forbidden()` (403 JSON, else a
flash and a 302 to the dashboard). **Do not re-implement that split inside
a decorator.** Sharing it is the point: the defect below was three
decorators missing a branch the fourth already had, and
`test_all_four_decorators_share_the_api_split` fails if one hand-rolls it
again.

> **Corrected 2026-09-01.** This block previously read: *"`admin_required`
> and `editor_required` still emit the redirect form on `/api/*` failures
> — Pass 45.1 only migrated `permission_required`. Today this is safe
> because the two decorators are used only on page routes."*
>
> The first half was true and is now fixed. **The second half was never
> true.** A count taken on 2026-09-01 found **115** `/api/*` routes gated
> by those two decorators, across 22 route modules — `maintenance.py` (19),
> `settings.py` (13), `bulk_scrape.py` (11), `museum.py` (8), and this
> file's own `/api/users*` endpoints (4) among them. Every one answered a
> denial with a 302 that `fetch()` followed into 200-with-HTML.
>
> It is recorded rather than deleted because the sentence is why the defect
> survived: five independent review lanes found the routes, and three of
> them separately flagged that this paragraph had told every reader the
> problem did not exist. A false reassurance in a contract document is more
> durable than the bug it describes.

### Adding a new permission
1. Add the key to the right rows in `services.auth.ROLE_PERMISSIONS`.
2. Decorate every guarded route with `@permission_required('<key>')`.
3. Add a regression test (style: `tests/test_auth_player_role.py`)
   pinning (a) which roles hold the permission and (b) which routes
   carry the decorator. Pass 45.1 — adding a decorator without granting
   the permission — must not recur.

---

## 5. Per-User Data Partitioning

Pre-Pass-24, RetroDB was single-tenant: any signed-in user could see and
mutate every other user's tags, lists, wishlist, sync history, completion,
trophies, and recently-viewed list. Passes 27 / 31 / 41.9 / 45.15 added
per-user ownership on every table holding user-specific state. **Going
forward: any new user-scoped table MUST include `owner_id` (collections-
style) or `user_id` (sync-style), and every read MUST scope by it.**

| Table                          | Migration       | Owner column | Constraint                                       |
|--------------------------------|-----------------|--------------|--------------------------------------------------|
| `tags`, `lists`, `wishlist`    | 005 (Pass 27.1) | `owner_id`   | indexed                                          |
| `user_platform_tokens`         | 006 (Pass 27.2) | `user_id`    | PK `(user_id, platform)`                         |
| `psn_sync_status`              | 006             | `user_id`    | UNIQUE `WHERE user_id IS NOT NULL`               |
| `psn_games`                    | 007 (Pass 31.1) | `user_id`    | UNIQUE `(npwr_id, user_id)` (rebuild)            |
| `psn_trophies`                 | 007             | `user_id`    | UNIQUE `(psn_game_id, trophy_id)` (rebuild)      |
| `collector_trophies`           | 008 (Pass 31.3) | `user_id`    | PK `(id, user_id)` (rebuild)                     |
| `game_achievement_progress`    | 009 (Pass 31.2) | `user_id`    | UNIQUE `(game_id, user_id)` (rebuild)            |
| `steam_achievements`           | 009             | `user_id`    | UNIQUE `(game_id, apiname, user_id)` (rebuild)   |
| `xbox_achievements`            | 009             | `user_id`    | UNIQUE `(game_id, achievement_id, user_id)` (rb) |
| `user_game_views`              | 010 + 011 (45.15)| `user_id`   | PK `(user_id, game_id)`, CASCADE FKs (rebuild)   |

Every rebuild follows the 12-step
<https://sqlite.org/lang_altertable.html#otheralter> procedure (SQLite
cannot drop / add inline UNIQUE / PK / FK clauses in place), uses
`PRAGMA defer_foreign_keys = ON` (the no-op `PRAGMA foreign_keys = OFF`
is ignored inside a transaction), and runs a scoped
`PRAGMA foreign_key_check(<table>)` at the end (Pass 45.10).

### The `_backfill_null_owner_ids` self-heal

`services/database_init.py::_backfill_null_owner_ids` runs every startup,
after `ensure_user_tables()` seeds the default admin. Targets:
`(tags, owner_id)`, `(lists, owner_id)`, `(wishlist, owner_id)`,
`(psn_sync_status, user_id)`. Each gets
`UPDATE {table} SET {column} = ? WHERE {column} IS NULL`.

**Why it exists:** Pass 30.1 fixed a migration-order bug where
`ensure_user_tables()` ran AFTER `init_database()` on an upgrade path
with no pre-existing users table. Migrations 005 / 006 stamped
`user_version` past their backfill steps without ever seeing an admin
row, leaving collection rows with `owner_id IS NULL` (effectively
orphaned — every read with `WHERE owner_id = ?` missed them). The
self-heal is idempotent on healthy DBs (`rowcount == 0`), surgical on
bitten ones. Pinned by `tests/test_owner_id_self_heal.py`.

### Read / write contract

Every read of a per-user-scoped table MUST carry
`WHERE owner_id = g.user['id']` (or `user_id = ...`). Writes MUST include
the owner column on `INSERT` and the owner predicate on `UPDATE / DELETE`.
A bare `SELECT * FROM tags` is a cross-user leak.

---

## 6. Per-User Platform Tokens

Pre-Pass-27, PSN / Xbox tokens lived in shared JSON files (`data/psn_tokens.json`,
`data/xbox_tokens.json`); Steam / RA creds lived in the shared
`scraper_settings.json` blob. First user to authenticate leaked their
account to every signed-in user. Pass 27 moved everything per-user.

All credentials are stored plaintext (DB file is 0o600; threat model
matches the legacy JSON files). At-rest encryption would be a future
swap inside `services/platform_tokens.py` — call sites unchanged.

| Credential                          | Storage location                              |
|-------------------------------------|-----------------------------------------------|
| Steam API key / ID                  | `user_settings.steam_api_key`, `.steam_id`    |
| RetroAchievements user / key        | `user_settings.ra_username`, `.ra_api_key`    |
| PSN username / NPSSO                | `user_settings.psn_username`, `.psn_npsso`    |
| PSN + Xbox OAuth token blobs        | `user_platform_tokens.tokens` (JSON-encoded)  |

**Accessor:** `services/platform_tokens.py` is the single shared module for
PSN + Xbox OAuth blobs. Functions: `load_tokens(user_id, platform)`,
`save_tokens(user_id, platform, tokens)` (upsert),
`clear_tokens(user_id, platform)`. All three short-circuit
`if not user_id: return` — defence-in-depth pin for misconfigured
callers. Routes MUST go through this module, not raw SQL. Pinned by
`tests/test_auth_hardening.py::TestPerUserPlatformTokens`.

**RA credential resolution** —
`services.auth.get_user_ra_credentials()` prefers the logged-in user's
per-account creds from `user_settings` and, on miss, delegates to
`scraper.retroachievements.get_ra_credentials()`, which reads the install-wide
fallback from `config.py` / `settings.json`. This is the **only** install-wide
fallback permitted; every other read scopes by `g.user['id']` strictly.

---

## 7. Session Model

Flask's signed-cookie session, configured in `app.py`:

- `SESSION_COOKIE_HTTPONLY = True` — unreachable from JS.
- `SESSION_COOKIE_SAMESITE = 'Lax'` — primary CSRF defence (cross-origin
  POSTs do not send the cookie). The explicit token (§10) is
  defence-in-depth.
- `SESSION_COOKIE_SECURE` — env-gated via `RETRODB_SECURE_COOKIES`.
  Default off (a localhost HTTP deploy would silently break login).
  Operators on TLS MUST set it to `true`.
- `PERMANENT_SESSION_LIFETIME = timedelta(days=7)`. `session.permanent =
  True` is set on login.
- `RETRODB_TRUST_PROXY=true` installs `werkzeug.ProxyFix` trusting one
  hop of `X-Forwarded-For` — required behind nginx / Caddy so the
  IP-based rate limiter doesn't collapse every client into the proxy's
  loopback bucket.

### Session rotation boundaries

Per OWASP ASVS V3.7, the session ID rotates on every credentials
boundary. Flask has no `regenerate()`; the idiomatic equivalent is
`session.clear()` then re-seed `session['user_id']`. Three rotation
points, all pinned by AST tests in
`tests/test_auth_hardening.py::TestSessionRotationOnLogin` /
Pass 33.5 equivalents:

1. **`api_login`** (Pass 24.2) — discards pre-login state including
   attacker-planted cookies.
2. **`api_change_password`** (Pass 33.5) — invalidates hijacked cookies
   and concurrent sessions of the same account.
3. **`api_force_change_password`** (Pass 33.5) — first authenticated
   touch after a `changeme` / admin-reset login; bootstrap cookie cannot
   be replayed after.

`logout` also calls `session.clear()` (Pass 33.6) so the CSRF token,
`permanent` flag, and other ambient state don't survive into the next
login.

---

## 8. Password Policy

### Hashing

`PBKDF2-HMAC-SHA256` with 600,000 iterations (OWASP 2026 Password Storage
Cheat Sheet floor for PBKDF2-SHA256). 16-byte hex salt. Stored format:

```
# Current format (v2.84.0 onward)
pbkdf2:<iterations_decimal>:<salt_hex>:<hash_hex>

# Legacy format (pre-v2.84.0) — no prefix, iteration count fixed at 100,000
<salt_hex>:<hash_hex>
```

`verify_password()` accepts both formats; `needs_rehash()` flags any
below-floor or malformed hash, and `api_login` rehashes to the current
format on successful login. Compliance pin:
`tests/test_auth_hashing.py::test_pbkdf2_iterations_meets_owasp_floor`.

### Stale-hash startup sweep (Pass 41.1.C)

`needs_rehash` only fires on the next successful login, so dormant
accounts keep weak hashes indefinitely (OWASP ASVS V2.4.5).
`services.auth.count_stale_password_hashes()` returns the count of
active users whose hash is below the floor / malformed; `app.py`
emits a `logger.warning` at startup when non-zero so an operator can
force-change idle accounts.

### Minimum length

12 characters everywhere (Pass 24.4), enforced in `api_create_user`,
`api_update_user` (admin reset), `api_change_password`,
`api_force_change_password`. Old 8-char floor let `password` pass.
Pinned by `TestPasswordPolicyAndRateLimit::test_min_length_raised_to_12`.

### Bootstrap / force-change

- Default admin (created by `ensure_user_tables` if no admin exists):
  username `admin`, password `admin`, `force_password_change = 1`.
  Bootstrap password is documented in the README, NOT logged
  (Pass 41.3.B — the redactor only catches `password=X` field triggers,
  not plaintext in free text).
- New users without an explicit password get `changeme` +
  `force_password_change = 1`.
- Admin reset (`api_update_user` with `new_password`) sets the flag
  unless `skip_force_change: true` is passed (Pass 33.4).
- `app.py::check_force_password_change` `@before_request` hook
  intercepts any flagged user and serves the force-change template for
  every endpoint outside `{auth.api_change_password,
  auth.api_force_change_password, auth.logout, static,
  serve_static_image, setup_page, setup_api}`. Pinned by
  `TestForcePasswordChangeMiddleware`.

---

## 9. Login Security

In-memory `OrderedDict` rate limiter in `services/security.py`:
`MAX_ATTEMPTS = 5`, `WINDOW_SECONDS = 300`. Five failed attempts in five
minutes → 429; bucket clears on the next successful login. Pass 33.9
replaced an O(N) + O(N log N) sweep with eviction-on-insert + lazy
per-key TTL (the previous form was a soft-DoS amplifier).

**Bucket keys:**
- `/api/login` — bare client IP (`request.remote_addr or '127.0.0.1'`).
- `/api/profile/password` — `f"{ip}:cpw:{user_id}"` (Pass 41.1.B). The
  legacy IP-only bucket was shared with `/api/login`, so 5 failed
  change-password attempts on a shared LAN locked everyone else out of
  `/api/login`. The composite bucket isolates change-password from
  login AND from other users on the same IP. Backing storage: the same
  `_login_attempts` `OrderedDict` in `services/security.py` that serves
  `/api/login`; `_MAX_ENTRIES = 10000` LRU eviction is therefore global
  across both bucket families.
- `/api/profile/force-change-password` — **intentionally not rate-limited.**
  The endpoint re-verifies the user's current password before accepting
  the new one, so it carries some brute-force surface, but the caller is
  already authenticated and the bootstrap credential pair is documented
  publicly in the README. Reconsider this carve-out if the endpoint ever
  becomes reachable pre-auth.

**Open-redirect protection:** `api_login` parses `next` via `urlparse`
and rejects any URL with a `netloc`, `scheme`, or backslash
(CVE-2023-49438 family); rejected `next` falls back to
`url_for('dashboard')`.

**No login-form CSRF token:** `/api/login` is in the CSRF exempt set
(§10) — there is no authenticated session to bind a token to.
Rate-limit + password verify are the only gates.

---

## 10. CSRF

Custom per-session token, **not Flask-WTF / CSRFProtect** — the impl is
~30 lines and the deployment target (single- or LAN-user localhost) has
`SameSite=Lax` as primary defence. Adding `wtforms` + `itsdangerous` for
ergonomics alone would require migrating every existing `_csrf_token`
form field; a future contributor considering the switch should weigh
the cost.

**Lifecycle.** Minted on first request by `app.py::load_user` if absent
(`session['_csrf_token'] = secrets.token_hex(32)`). Rotated on every
session-rotation boundary (login / change-password / force-change-password)
— `api_login`, `api_change_password`, `api_force_change_password` return
the new token in the JSON response (`csrf_token=...`) so the client
keeps POSTing without a GET round-trip.

**Validation.** `app.py::validate_csrf` is a `@before_request` hook.
Skipped for `GET / HEAD / OPTIONS` and the exempt endpoint set
`{static, serve_static_image, auth.api_login, auth.login, setup_api,
setup_browse_folders}`. Otherwise compares
`request.headers['X-CSRF-Token']` (or `_csrf_token` form field) against
`session['_csrf_token']` via `secrets.compare_digest`; mismatch → 403
JSON envelope.

**JS plumbing.** Token rendered in base template as
`<meta name="csrf-token" content="{{ csrf_token }}">`.
`templates/base.html` wraps `fetch` to auto-inject the `X-CSRF-Token`
header on any state-changing call that doesn't already have one;
`API.post` / `API.postForm` ride on top, so route callers don't plumb
the token manually. Standalone scripts that use raw `fetch`
(`game-launch.js`, `emulators-settings.js`, `launch-indicator.js`)
attach the header explicitly.

---

## 11. API Auth Error Contract

For `/api/*` routes (any path whose `request.path.startswith('/api/')`):

| Failure                          | Status | Body (`{'success': false, 'error': ...}`)   |
|----------------------------------|--------|---------------------------------------------|
| Not signed in                    | 401    | `Authentication required`                   |
| Signed in, lacks permission      | 403    | `You do not have permission ...`            |
| CSRF token missing / mismatch    | 403    | `Invalid or missing CSRF token`             |
| Rate limit exceeded (login)      | 429    | `Too many login attempts ...`               |
| Unhandled exception              | 500    | `An internal error occurred`                |

Non-`/api/*` page routes flash + 302 to `/login?next=...` or `/dashboard`
on the same failures.

**Why the split (Pass 45.1):** `fetch()` with `credentials: 'include'`
follows 302 redirects transparently. A pre-Pass-45.1 `/api/*` 401-as-302
made the calling JS see a 200 of dashboard HTML — silent failure, no
toast, server log showed a 200. JSON envelope on `/api/*` is mandatory.

Builders live in `services/api_helpers.py`: `success(...)`,
`error(message, code=400, **extra)`, `@handle_api_errors`. The JSON envelope
contract is owned by [`api-contracts.md`](api-contracts.md); see also §22 of
`docs/RETRODB_DESIGN_STANDARDS.md` for the surrounding security-headers
context.

---

## 12. Testability

### Auth-related test files

| File                                | Pins                                                                                       |
|-------------------------------------|--------------------------------------------------------------------------------------------|
| `test_auth_hashing.py`              | PBKDF2 floor, legacy-format verify, `needs_rehash` thresholds                              |
| `test_auth_hardening.py`            | Passes 24 / 27 / 22.7 — session rotation, force-change middleware, password length, `editor_required` on destructive endpoints, per-user token isolation, redactor |
| `test_auth_player_role.py`          | Pass 44 — player role, `has_permission` routing, `VALID_ROLES` in routes                   |
| `test_owner_id_self_heal.py`        | Pass 30.1 — `_backfill_null_owner_ids` idempotency + degradation                           |
| `test_pass41_security.py`           | Pass 41.1.A/B/C — `login_required` footgun, change-password bucket, stale-hash sweep       |
| `test_pass45_security.py`           | Pass 45.1 — `track_progress` grants + JSON envelope on `/api/*`                            |

### Patterns

- **Spin up a user with a role:** `client.session_transaction()` to stub
  `session['user_id']`, then seed the DB inline. For pure permission
  unit tests (no Flask request), monkeypatch `services.auth.g` with a
  stub user dict.
- **Test a role-gated route — two-level guarantee:** source-level
  decorator-stack regex (asserts the right decorator above the view)
  PLUS a functional reject test (call anonymously, assert 401/403 or
  redirect-to-login). Either alone is the Pass-45.18 source-grep
  anti-pattern.
- **Test per-user partitioning:** seed two users → insert under user A
  → log in as user B → assert the row is not visible / mutable.
  Canonical model: `TestPerUserPlatformTokens` in
  `tests/test_auth_hardening.py` (`_isolated_db` builds a temp SQLite,
  tests assert round-trip + per-`(user, platform)` isolation +
  `user_id=None` no-op).

---

## 13. Known Invariants

Contracts any new code / refactor MUST honour. Each is a bug if violated.

1. **Every mutating route has an auth decorator.** No bare `@bp.route`
   on `POST` / `PUT` / `DELETE`. `@editor_required` for metadata
   mutation, `@admin_required` for user/settings management,
   `@permission_required(perm)` for finer grain.
2. **Read-only API routes still need `@login_required` (or stronger).**
   Public exceptions are small and explicit (login, setup, static,
   analytics).
3. **Per-user data is ALWAYS queried with `WHERE owner_id = ?` or
   `WHERE user_id = ?`.** Bare reads / writes on the §5 tables are
   cross-user leaks.
4. **New user-scoped tables MUST add `owner_id` / `user_id` in their
   creating migration.** `_backfill_null_owner_ids` is a one-shot patch
   for Pass 30.1, not a general escape hatch.
5. **Every role requires a password.** No passwordless branch in
   `api_login` or `api_create_user`. Re-introducing one is the Pass 24.1
   bypass.
6. **`VALID_ROLES = tuple(ROLE_PERMISSIONS.keys())` is the only
   role-list source.** No hard-coded `['admin', 'editor', 'viewer']`
   allow-lists in routes (Pass 44 hoist).
7. **Session rotates on every credentials boundary.** `session.clear()`
   precedes `session[...] = ...` on login, change-password, and
   force-change-password. AST test:
   `TestSessionRotationOnLogin::test_login_calls_session_clear`.
8. **The `login_required` allow-list stays empty.** Re-introducing the
   5-name allow-list re-opens the Pass 41.1.A silent-public-route
   footgun.
9. **CSRF exempt set stays small** and is reviewed on every change.
   Adding a POST-taking entry is almost always a bug.
10. **`permission_required` on `/api/*` returns JSON, not 302.** The
    `is_api = request.path.startswith('/api/')` branch is load-bearing
    (Pass 45.1).
11. **Per-user platform tokens go through `services/platform_tokens.py`.**
    Direct `INSERT INTO user_platform_tokens` from a route bypasses the
    `if not user_id` guard.
12. **The default-admin bootstrap password is not logged.** Pass 41.3.B
    — username only; the redactor does not catch plaintext in free text.

---

## Cross-references

- `docs/RETRODB_DESIGN_STANDARDS.md §22` — high-level security standards;
  this spec is the deep dive it points to.
- `CLAUDE.md` — mandatory workflow + project contracts.
- `roadmap.md` Passes 24 / 27 / 30.1 / 31 / 33 / 41.1 / 41.9 / 44 /
  45.1 / 45.10 / 45.15 / 45.18 — fix passes that built this contract.
- `services/auth.py`, `services/security.py`,
  `services/platform_tokens.py`,
  `services/database_init.py::_backfill_null_owner_ids`,
  `services/migrations/scripts/005_*` through `011_*`.
