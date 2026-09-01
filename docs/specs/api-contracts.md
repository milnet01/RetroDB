# RetroDB API Contracts

> Wire-level contract for every `/api/*` route in RetroDB: response envelope,
> error shape, status-code policy, ETag / gzip / rate-limit / security-header
> behaviour, CSRF, pagination, request-body limits, and known invariants.
>
> Cross-reference: `docs/RETRODB_DESIGN_STANDARDS.md` §22 (Security Standards,
> including "Error Message Sanitization"). The API response envelope is owned
> by this spec (not the standards doc) — `services/api_helpers.py` is the
> canonical implementation. Other helpers referenced here live in
> `services/security.py`, `services/auth.py`, and `app.py` (middleware section).

---

## 1. Purpose

Every `/api/*` route in RetroDB returns JSON, never HTML or a redirect, so the
browser-side `API.get` / `API.post` / `API.postForm` helpers in `static/js/utils.js`
can rely on a single decode path. This document pins the wire format that every
route — auth, settings, scraper, bulk-scrape jobs, achievements, platform
imports, maintenance — must conform to. New routes that diverge from this
contract are bugs, not features.

The contract is split across four files in practice — keep this spec in lockstep
with them when any one changes:

| Concern | File |
|---|---|
| Envelope helpers | `services/api_helpers.py` |
| Decorators (`login_required`, `permission_required`, `editor_required`, `admin_required`) | `services/auth.py` |
| Login rate-limit | `services/security.py` |
| Per-route rate-limit, ETag, gzip, security headers, CSRF, error handlers | `app.py` |

---

## 2. Response envelope

The canonical helpers live in `services/api_helpers.py`. Every route returns one
of these shapes — building the dict by hand is a code-smell that has historically
drifted (extra keys, missing `success`, wrong status). Use the helper.

### 2.1 Success

```python
from services.api_helpers import success

return success()                           # → {"success": true}
return success({"id": 5})                  # → {"success": true, "data": {"id": 5}}
return success(games, total=len(games))    # → {"success": true, "data": [...], "total": N}
return success(message="Settings updated") # → {"success": true, "message": "..."}
```

Top-level keys:

- `success` — always `true`.
- `data` — optional. Present only when caller passed a positional arg.
- Extra kwargs (`total`, `page`, `ids`, `message`, `csrf_token`, `games`,
  `users`, `settings`, `redirect`, …) ride alongside `data` at the top level.
  Routes are free to pick the key that reads best at the call-site; clients
  must not assume `data` is the only place results live.

### 2.2 Error

```python
from services.api_helpers import error

return error('Game not found', 404)
return error('Validation failed', 422, field='title')
return error('Too many login attempts. Please try again later.', 429)
```

Top-level keys:

- `success` — always `false`.
- `error` — human-readable message. Must be safe to surface to the client (see
  §13).
- Extra kwargs ride alongside (`field`, `needs_password`, `details`, …).

Return type is `(jsonify(...), status_code)` — return it directly, do not unpack.

### 2.3 No envelope variants

`/health` and `/ready` are the only intentional exceptions — both predate the
helper and exist for systemd / Docker / reverse-proxy probes that expect a
status string. Actual shapes:

- `/health` → `{"status": "ok"}` (HTTP 200).
- `/ready` (DB probe pass) → `{"status": "ready"}` (HTTP 200).
- `/ready` (DB probe fail) → `{"status": "not_ready", "error": str(e)}` (HTTP 503).

The `str(e)` in the 503 failure body is a deliberate operator-debug carve-out
— `/ready` is operator-facing, not a public `/api/*` endpoint, so the §13
sanitisation rule does not apply. Do not copy this shape for new routes.

---

## 3. Status-code policy

| Status | When to use |
|---|---|
| **200 OK** | Successful read or write that returned data. Default for `success()`. |
| **201 Created** | A new resource was persisted and you want the client to know the canonical URL — include the new id in the envelope. RetroDB rarely uses this; `success(id=…)` at 200 is more common. |
| **202 Accepted** | Reserved for job-style endpoints that hand off to a background thread. **Not currently emitted by any route** — today's job-start endpoints (e.g. `/api/bulk-scrape-job/start`, `/api/maintenance/alt-titles-backfill/start`) return 200 with `success(job_id=…)`. Treat 202 as the target shape for new background-hand-off routes if they need an explicit "queued, not done" signal. |
| **204 No Content** | Reserved; not currently used. Prefer `success()` so the envelope stays uniform. |
| **400 Bad Request** | Malformed request (missing required field, unparseable JSON, invalid query-param combo). |
| **401 Unauthorized** | `/api/*` caller is not logged in. Emitted by `permission_required` when `g.user` is None on an API path (`services/auth.py:276-278`). |
| **403 Forbidden** | Logged-in caller lacks the required permission, or the request failed CSRF validation, or the action is blocked (e.g. last-admin delete). Pass 45.1: **API routes return 403 JSON, never a 302 to `/dashboard`** — `fetch()` follows redirects transparently and the JS sees 200 HTML, which is impossible to handle. |
| **404 Not Found** | Resource id does not exist, or path is unrecognised. The global 404 handler (`app.py:543-548`) emits the standard envelope for any `/api/*` path. |
| **409 Conflict** | A write would violate a uniqueness constraint or duplicate an in-flight job. Currently used sparingly; most write conflicts surface as 400 with a descriptive `error`. |
| **413 Payload Too Large** | Werkzeug raises this from `MAX_CONTENT_LENGTH` before the handler runs. `app.py:560-575` converts it to the standard envelope for `/api/*`. |
| **422 Unprocessable Entity** | **Spec target for new routes**; not currently emitted on the auth/profile paths. Legacy validators in `routes/auth.py` return 200 with `success: false` and no `field` kwarg (e.g. password < 12 chars, invalid rating value) — see §3.2 below. New routes that validate well-formed input should emit 422 with a `field=` kwarg when the failure is field-scoped. |
| **429 Too Many Requests** | Rate-limit triggered. Both the custom IP/user bucket (login + change-password) and Flask-Limiter use 429 as the status code. Envelope shape differs — the custom bucket returns the standard `error()` envelope; Flask-Limiter returns plain HTML/text (its built-in default). See §7.3. |
| **500 Internal Server Error** | Unhandled exception. The `@handle_api_errors` decorator (§4) emits the standard envelope; the global 500 handler does the same for anything that escapes. |
| **503 Service Unavailable** | `/ready` only — DB probe failed. |

### 3.1 Auth-vs-redirect rule

The decorator family in `services/auth.py` distinguishes API and HTML paths via
`request.path.startswith('/api/')`:

- **API path, no user** → 401 JSON envelope.
- **API path, user but no permission** → 403 JSON envelope.
- **HTML path, no user** → 302 to `/login?next=…`.
- **HTML path, user but no permission** → flash + 302 to `/dashboard`.

All four decorators — `login_required`, `admin_required`, `editor_required` and
`permission_required` — produce the table above, because all four route their
refusals through `services/auth.py`'s `_deny_unauthenticated()` and
`_deny_forbidden()`. **Do not re-implement the API-vs-page split inside a
decorator**; that divergence is what Pass 49.5 closed.

> **Corrected 2026-09-01 (Pass 49.5).** This read: *"`admin_required` and
> `editor_required` currently emit the redirect form even on API paths — they
> predate Pass 45.1's API-aware split."* That was true, and the migration it
> deferred has now happened, so composing `permission_required` is no longer
> required to get an envelope from admin gating. `login_required` had the same
> gap and this paragraph never mentioned it.

### 3.2 Validation-failure shape (current vs target)

Today's auth/profile validators return `error('…', code=200)` with no `field=`
kwarg — see `routes/auth.py` (every validate-and-reject site uses
`success: false` at HTTP 200). The 400/422 row in the table above is the spec
target for new routes, not a description of what ships. When migrating an
existing validator, switch the call from `error('…', code=200)` to
`error('…', code=422, field='username')` in lockstep with any test that
asserts on the status code.

---

## 4. `@handle_api_errors`

Defined in `services/api_helpers.py`. Innermost decorator on a JSON route:

```python
@bp.route('/api/foo')
@login_required
@handle_api_errors
def api_foo():
    ...
```

What it catches: every exception that escapes the wrapped function. Logs with
`logger.error(..., exc_info=True)` under the wrapped function's module logger,
then returns:

```json
{"success": false, "error": "An internal error occurred"}
```

with HTTP 500.

**When to use it**: every `/api/*` handler that does non-trivial work
(DB queries, file I/O, calls into a service). Pure dispatch handlers that only
call `success(...)` after a hand-curated validation can skip it, but the cost
of adding it is nil and the safety net is real.

**Decorator order**: place `@handle_api_errors` innermost so auth decorators
(login_required, permission_required, editor_required, admin_required) execute
first. Otherwise an unauthenticated request would land in the try/except and
return a misleading 500 instead of the proper redirect/401.

**When to skip it**: when you actively want a 4xx to escape (Werkzeug aborts,
explicit `error(...)` returns) — the decorator doesn't catch those, only
unhandled exceptions, so it's safe to keep on. The only true reason to omit it
is a route that streams (no exceptions can fire post-yield) or one whose
exception path should render HTML.

---

## 5. ETag

Only one route currently sets `ETag` / honours `If-None-Match`:
`/api/games/card-data` (`routes/games.py:220-298`, Pass 21.1 + Pass 40.5).

### 5.1 Key composition

The etag payload must include every input that affects the response body:

```python
etag_payload = f"cd:{g.user['id']}:{','.join(str(i) for i in sorted_ids)}:{max_updated}"
etag = f'W/"{hashlib.md5(etag_payload.encode(), usedforsecurity=False).hexdigest()}"'
```

- `cd:` — route discriminator (`card-data`).
- `g.user['id']` — **Pass 40.5 multi-user discriminator**. The response embeds
  per-user PSN progress + achievement progress, so a globally-keyed ETag would
  let one user's browser serve another user's progress out of cache. CWE-524.
- Sorted ids — request determinism (clients hitting the same set in different
  orders share cache).
- `max(games.updated_at)` over the requested ids — migration 004 guarantees
  every INSERT/UPDATE on `games` bumps `updated_at`, so this is a reliable
  freshness key.

Weak validator (`W/"..."`) — the body is semantically equivalent under gzip
re-compression and irrelevant trailing-whitespace changes, but the response is
not byte-for-byte stable.

### 5.2 304 behaviour

```python
if request.headers.get('If-None-Match') == etag:
    resp = make_response('', 304)
    resp.headers['ETag'] = etag
    resp.headers['Cache-Control'] = 'private, must-revalidate'
    return resp
```

- 304 must have no body (RFC 7232) — gzip middleware short-circuits on 304
  (`app.py:458`).
- `Cache-Control: private, must-revalidate` — shared caches must never store
  the per-user response; private caches must re-check freshness on every use.

### 5.3 Adding ETag to new routes

Same pattern: include caller's user id whenever the response is user-scoped,
a freshness column (or table-level `MAX(updated_at)`), and a route prefix to
avoid collisions across endpoints. Pin the contract with a `tests/test_etag_*`
case modeled on `tests/test_etag_and_gzip.py::TestCardDataETag`.

---

## 6. gzip

`compress_response` `@after_request` hook (`app.py:443-484`). Pass 21.2.

### 6.1 Compression rules

A response is gzipped when **all** of these hold:

1. `RETRODB_DISABLE_GZIP` is unset (set to `1`/`true`/`yes` in reverse-proxy
   deploys where Caddy/nginx already compresses at the edge).
2. Response is not a streamed / direct-passthrough body (`send_file`,
   `StreamResponse`). Compressing those would break the streaming contract.
3. Status code is 2xx, 3xx, 4xx — **but never 204 or 304**.
4. `Content-Encoding` is not already set.
5. `Content-Type` matches `json` or `javascript` (substring check).
6. Client sent `Accept-Encoding: gzip`.
7. Body is at least `_GZIP_MIN_BYTES = 1024` bytes uncompressed.

When all hold, body is replaced with `gzip.compress(data, compresslevel=6)`,
`Content-Encoding: gzip` set, `Content-Length` updated to the compressed size.

### 6.2 Vary header

`Vary: Accept-Encoding` is set on every response that *could have been*
compressed — even when the client opted out or the body was too small. This
guarantees shared caches key on `Accept-Encoding` and never serve a gzipped
body to a client that didn't advertise gzip support. The hook is careful to
append, not overwrite, any pre-existing `Vary` (e.g. `Vary: Cookie` from
session-aware responses).

### 6.3 Operator opt-out

In a reverse-proxied deploy (`docs/PROXY-DEPLOY.md`), Caddy / nginx compresses
on the way out. Setting `RETRODB_DISABLE_GZIP=1` in the systemd unit avoids
the double-work; the proxy will set its own `Content-Encoding` and `Vary`.

---

## 7. Rate-limit buckets

Two independent systems are in play:

### 7.1 Login / change-password — `services/security.py`

Custom in-process counter with a 10 000-entry OrderedDict (LRU-evict on insert,
lazy TTL expiry on read). 5 failures per bucket per 300 s triggers a 429.

| Endpoint | Bucket key | Source |
|---|---|---|
| `POST /api/login` | `request.remote_addr` (raw IP) | `routes/auth.py:54-56` |
| `POST /api/profile/password` | `f"{ip}:cpw:{user_id}"` — Pass 41.1.B per-(ip, user) | `routes/auth.py:350-354` |

Pass 41.1.B isolates change-password from login: previously both used the
bare IP bucket, so 5 failed change-password attempts from user A on a shared
LAN locked out `/api/login` for every other user behind the same NAT.

### 7.2 Per-route rate-limit — Flask-Limiter (`app.py:282-367`)

`Limiter(get_remote_address, default_limits=[], storage_uri="memory://")`.
Per-IP buckets. Registered post-blueprint via `_rate_limit(endpoint, spec)`,
which **raises at import time** if the named endpoint isn't registered (Pass
34.4) — a renamed route can never silently lose its limit.

Current registrations (read `app.py:303-367` for the live list):

| Tier | Cap | Endpoints |
|---|---|---|
| Heavy AI / scrape | 5–10/min | `games_ai.api_game_ai_fill`, `bulk_scrape.api_bulk_scrape_job_start` |
| Login brute-force | 10/min | `auth.api_login` (supplements the custom IP bucket) |
| Admin destructive | 2–3/min | `maintenance.api_restart`, `maintenance.api_scan`, `maintenance.api_database_optimize`, `maintenance.api_image_resize_start`, `settings.api_backup` |
| Long-running scans | 5/min | `tools.api_archive_scanner_scan`, `tools.api_chd_converter_scan`, `tools.api_chd_verify_scan`, `tools.api_duplicate_finder_scan`, `tools.api_screenshot_dedup_scan`, `reports.api_reports_multidisc_scan` (Pass 39.7, 41.10.D) |
| HLTB | 60/hour lookup/search, 5/hour bulk | `games_hltb.api_hltb_lookup`, `…api_hltb_search`, `…api_hltb_bulk_start` |
| Museum / trophy refresh | 2–20/hour | `museum.generate_system`, `museum.generate_all`, `collector_trophies.refresh_trophies` |
| Third-party fan-out (Pass 45.8) | 5/min library, 2/hour bulk-sync | `platform_import.api_{steam,xbox,psn}_fetch_library` / `…_import`, `…_sync_achievements`, `steam_achievements.api_steam_sync_all`, `xbox_achievements.api_xbox_sync_all`, `trophies.api_psn_sync_all`, `trophies.api_psn_bulk_refresh_start`, `collections.api_scrape_all_wishlist` |
| Scraper credit probes | 30/min | `scraper.api_check_scraper`, `scraper.api_scraper_allowance` |

`editor_required` is the standard substitute on low-cost write paths — no
rate-limit, but only admin/editor roles can mutate. Add `_rate_limit` *in
addition to* `editor_required` (not instead of it) whenever fan-out cost is
non-trivial.

### 7.3 429 envelope

Custom buckets emit the standard `error(...)` envelope. Flask-Limiter's
default 429 page is plain text — operators expecting JSON from `/api/*` should
register a Flask-Limiter error handler that uses `services.api_helpers.error`.
(Not yet wired; tracked separately if it becomes a real issue.)

---

## 8. Security headers

Set on every response by `set_security_headers` `@after_request`
(`app.py:389-432`).

| Header | Value | Notes |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Always. |
| `X-Frame-Options` | `SAMEORIGIN` | Always. Stronger than the deprecated `ALLOW-FROM`. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Always. |
| `Permissions-Policy` | `browsing-topics=(), camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=(), accelerometer=(), gyroscope=(), magnetometer=(), midi=()` | Opt out of every browser API RetroDB never touches. |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | **Only** when `SESSION_COOKIE_SECURE` is on. Sending HSTS over plain HTTP would be misleading; on localhost it's a no-op anyway. |
| `Content-Security-Policy-Report-Only` | `default-src 'self'; script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; …` | **Report-only currently.** Flipping to enforcing mode is the FU.1 follow-up chain in `roadmap.md`; v3.6.20 landed phase A (every inline `onclick=` migrated to event-bound listeners + `csp_nonce` wired through `base.html`). Phase B flips to enforcing; Phase C removes `unsafe-inline`/`unsafe-eval`. Nonce is per-request, generated in `before_request` (`g.csp_nonce`), and exposed to templates as `{{ csp_nonce }}`. |
| `X-XSS-Protection` | *(intentionally absent)* | The XSS Auditor was removed from Chromium/Edge and lives only in Safari; leaving it unset matches current OWASP guidance. |

Pinned by `tests/test_security_headers.py`.

---

## 9. CSRF

Custom per-session random token (`secrets.token_hex(32)`), constant-time
compared with `secrets.compare_digest`. **Not** an HMAC — no key, no message.
See design-standards §22 "CSRF Protection" for the rationale (we don't need
HMAC because the token is opaque session state, not signed content).

### 9.1 Server side

- `before_request load_user` (`app.py:600-611`) ensures `session['_csrf_token']`
  is a 64-hex-char token (`secrets.token_hex(32)`).
- `before_request validate_csrf` (`app.py:614-641`) checks the token on every
  state-changing request (POST/PUT/DELETE). Compared with
  `secrets.compare_digest` against either:
  - `X-CSRF-Token` request header, or
  - `_csrf_token` form field (multipart uploads).
- Failure → 403 JSON envelope (never a redirect).
- Exempt endpoints: see [`auth.md §10 CSRF`](auth.md#10-csrf) — `auth.md` is the canonical owner of the exempt set so the list does not drift between specs.
- Logout (`session.clear()`) drops the old token; `ensure_csrf_token` re-seeds
  on the next request.

### 9.2 Client side

- `base.html` exposes `<meta name="csrf-token" content="{{ csrf_token }}">`
  and patches `fetch()` to inject `X-CSRF-Token` from that meta tag on every
  request (`templates/base.html:340-352`).
- `API.get` / `API.post` / `API.postForm` (`static/js/utils.js:277-359`) ride
  on patched `fetch`, so they get the header automatically.
- After a successful login the `/api/login` response surfaces a fresh
  `csrf_token` in the envelope (Pass 33.8 — `routes/auth.py:120-126`). The
  caller's JS replaces the meta tag's `content` so the next POST uses the new
  session's token without an HTML round-trip.

---

## 10. Pagination

Single convention (page/per_page with server-side cap), modeled by
`/api/games` (`routes/games.py:116-164`):

```python
page = request.args.get('page', 1, type=int)
per_page = min(request.args.get('per_page', 100, type=int), 200)
# ... data query ...
data_sql += " LIMIT ? OFFSET ?"
data_vals.extend([per_page, (page - 1) * per_page])
```

Response shape:

```json
{
  "success": true,
  "games": [...],
  "total": 1234,
  "page": 1,
  "per_page": 100,
  "total_pages": 13,
  "has_more": true
}
```

**Invariant**: `per_page` must be clamped server-side (`min(..., 200)`). Never
trust the client. New paginated routes must do the same — `min(value, ceiling)`
inline, not after a "validate" call that might be skipped.

Bulk-id endpoints (`/api/games/ids`, `/api/games/card-data`) use a different
cap pattern — see Pass 25.8: `LIMIT 20 * MAX_LIST_ROWS` (default 10 000) on
id-only fetches, and a hard `[1, 50]` range on card-data ids. Match the
relevant pattern by route shape; the rule is "always cap", not "always paginate".

---

## 11. Request body limits

- `app.config['MAX_CONTENT_LENGTH'] = config.MAX_UPLOAD_BYTES` (`app.py:137`).
- Default 64 MB. Override via `RETRODB_MAX_UPLOAD_MB` env var (`config.py:144-147`).
- Werkzeug raises `RequestEntityTooLarge` (413) before the handler runs.
  `app.py:560-575` converts it to the standard envelope for `/api/*` and
  includes the configured cap in the message so operators know what to raise.

**Reverse-proxy alignment** (`docs/PROXY-DEPLOY.md`): the proxy's
`client_max_body_size` (nginx) / equivalent (Caddy) **must be at least as high
as `MAX_UPLOAD_BYTES`**. If the proxy cap is lower, the user sees a
proxy-generated 413 with no JSON envelope and no useful message. Default
example deploys ship `client_max_body_size 100m;` to leave headroom over the
64 MB default.

Per-file image cap is independently 10 MB, enforced in the image-validation
path (`services/image_utils.py`) — distinct from the request-body cap, which
governs the multipart total.

---

## 12. Long-poll / SSE / WebSocket

**None.** RetroDB has no Server-Sent-Event endpoints, no WebSocket upgrade
paths, no long-polling (in the HTTP-hold sense). Every job-style endpoint uses
short polls against a status route:

```
POST /api/bulk-scrape-job/start     → 200 + success(job_id=…)
GET  /api/bulk-scrape-job/status    → 200 + success(processing=…, complete=…, results=…)
POST /api/bulk-scrape-job/cancel    → 200 + success(…)
```

(Note the path segment is `bulk-scrape-job` — single hyphen-separated noun —
not `bulk-scrape/job/...`. Same applies to `webp-migrate-job` and
`alt-titles-backfill` job-start endpoints; verify against `routes/` before
copying.)

UI polls `…/status` at ~1 Hz from JS. Cancellation flips a flag the worker
checks between items.

If a future feature needs streaming (e.g. live log tail), document the proxy
contract here: nginx requires `proxy_buffering off; proxy_read_timeout 1h;` per
connection, Caddy needs `flush_interval -1`. Until then the rule is: no
streaming, no upgrades.

---

## 13. Error message sanitization

Per design-standards §22 "Error Message Sanitization":

- **Never** return `str(e)` from an exception path to the client. Exception
  messages can leak internal paths, DB schema, library stack traces, file
  permissions.
- **Always** log the actual error with `logger.error(f"...: {e}", exc_info=True)`
  (or rely on `@handle_api_errors`, which does this for you).
- Return a generic, user-actionable message:
  `error('Game not found', 404)`, `error('An internal error occurred', 500)`,
  `error('Validation failed', 422, field='title')`.

The `@handle_api_errors` decorator enforces this at the 500 boundary —
`{'success': False, 'error': 'An internal error occurred'}`. Routes that build
their own error path must self-police; `log_redactor` in `services/` strips
known-sensitive substrings (API keys, paths) from the log line, but it doesn't
guard the wire.

Validation errors **may** name a field (`error('...', 422, field='title')`)
since field names are public schema, not secrets. Don't echo the offending
*value* back unless you're sure it can't be a credential / path / PII.

---

## 14. Testability

### 14.1 Assert the envelope, not the body

```python
def test_api_foo_success(app_client):
    resp = app_client.get('/api/foo')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert 'data' in body  # or whatever key the route uses
```

### 14.2 Smoke tests

`tests/test_routes_smoke.py` pins:

- `TestRouteRegistration` — every blueprint endpoint is reachable. Add new
  routes here so a missing `app.register_blueprint` fails CI loudly.
- `TestAuthGuards` — GETs to protected paths 30x to `/login`; POSTs reject
  with 30x, 401, or 403.
- Per-route specifics (HLTB auth, local search input validation) live in their
  own classes alongside.

### 14.3 ETag + gzip

`tests/test_etag_and_gzip.py` is the canonical example. The pattern:

- gzip — hit any unauthenticated JSON endpoint (`/api/timezones`), assert
  magic bytes, `Content-Length` matches body, `Vary` always set.
- ETag — log in via `session_transaction()`, fetch once for the ETag, fetch
  again with `If-None-Match`, assert 304 + matching header + empty body.

### 14.4 Security headers

`tests/test_security_headers.py` parametrises per-header. When you add a header
to `set_security_headers`, add a test there to pin it.

---

## 15. Known invariants

All of these are bugs if violated. New routes must conform; new tests should
pin them as they're added.

1. **Every `/api/*` route returns JSON, never HTML or a redirect.** API-shaped
   responses with HTML body are unrecoverable from the JS layer. Use the
   `permission_required` decorator (not `admin_required` / `editor_required`)
   when the route is `/api/*` and needs role gating.
2. **Every mutating route (POST/PUT/DELETE) is CSRF-validated.** The
   `validate_csrf` `before_request` hook enforces this app-wide; the exempt
   set is small and explicit. Adding a new route exempt requires editing
   `app.py` — surface that change in code review.
3. **Every paginated route caps `limit` / `per_page` server-side.** Inline
   `min(value, ceiling)`, not validator-call. The ceiling lives close to the
   route so it survives refactors.
4. **Every error envelope's `error` field is sanitized.** No `str(e)`, no path
   strings, no SQL fragments. The `@handle_api_errors` 500 path is automatic;
   handcrafted 4xx must self-police.
5. **Every rate-limited endpoint name appears in `app.py::_rate_limit(...)`
   calls.** Renaming a route without updating the registration raises at
   import time (Pass 34.4) — do not silence the exception, fix the rename.
6. **Every ETag includes the caller's `user_id` whenever the response is
   user-scoped.** Pass 40.5; CWE-524.
7. **Every login / change-password failure path calls `record_login_attempt`.**
   Otherwise the rate-limit counter never increments and the brute-force
   defence is silently disabled.
8. **`Vary: Accept-Encoding` rides on every response that could have been
   gzipped**, including the un-gzipped fallback. Shared caches need it to key
   correctly.
9. **`/health` and `/ready` stay unauthenticated and probe-safe.** They are
   exempt from first-time-setup redirect and slow-request log noise; do not
   add per-request work there.
10. **Request body cap stays in lockstep with the reverse-proxy cap.** Raising
    `RETRODB_MAX_UPLOAD_MB` without raising `client_max_body_size` produces a
    bare 413 with no envelope — a usability regression that's hard to debug
    from the browser. Document changes in `docs/PROXY-DEPLOY.md` alongside.
