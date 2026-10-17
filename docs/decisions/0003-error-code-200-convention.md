# 0003 — Some error replies still use HTTP 200

**Status:** accepted, transitional. **Recorded:** 2026-10-17 (roadmap
PASS-59-65).

## Context

The JSON reply envelope carries a `success` field. Early routes answered a failed
request with `success: false` and HTTP status 200. Some browser callers
depend on that status (roadmap PASS-59-114, *Plan*).

Origins:

- Roadmap Pass 2 moved routes onto the `success()` and `error()` helpers in
  `services/api_helpers.py`. It kept every status unchanged, and passed
  `code=200` where a route had answered 200 (v2.83.6 and v2.83.7,
  `data/changelog.yaml`).
- [`../specs/api-contracts.md`](../specs/api-contracts.md) § 3.2 set 4xx as
  the target and named the 200 replies as legacy (commit `2eb831b`,
  2026-05-18).
- PASS-2-9 finished the helper migration in v3.29.1. It left the 200
  failure replies as they were, because converting one changes the status
  its caller sees.

## Decision

- A new route answers a failure with a 4xx status
  ([`../specs/api-contracts.md`](../specs/api-contracts.md) § 3).
- An existing route that answers `success: false` at HTTP 200 keeps doing so
  until it is converted on purpose.
- Converting a route means checking its browser callers first. A caller that
  tests `response.ok` before reading the body must read the envelope instead.

## Consequences

- On these routes, the status code alone does not show a failure. A caller
  reads the `success` field.
- The auth and profile validators in `routes/auth.py` call
  `error(..., code=200)`. Other route files still build the reply by hand
  with no status code.
- The conversion is tracked by roadmap PASS-59-114. This record ends when
  that item ships.
