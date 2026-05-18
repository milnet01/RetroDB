# Security Policy

RetroDB is a self-hosted, solo-developed Flask application intended to run
on `localhost` (or a trusted LAN reverse-proxy host) under a single
operator's control. Most attack surface is therefore *internal* —
hardened against accidental misuse, scraper response trust boundaries,
and credential leakage in logs.

## Reporting a Vulnerability

**Please report security issues privately.** Do **not** open a public
GitHub issue for a suspected vulnerability — that would advertise the
problem before a fix is available.

- **Preferred:** email **aant.schemel@gmail.com** with `[RetroDB Security]`
  in the subject line.
- **Alternative:** GitHub's
  [private vulnerability reporting](https://github.com/milnet01/RetroDB/security/advisories/new)
  on this repository (Security tab → "Report a vulnerability").

Please include:

- A description of the issue and the impact (what an attacker can do).
- Concrete reproduction steps — env, version (`config.py:APP_VERSION`),
  request/response or stack trace if available.
- Your assessment of severity if you have one. Don't worry about
  scoring; rough wording is fine.

## Response Expectations

This project is solo-developed on a best-effort cadence. Realistic
timelines:

- **Acknowledgement:** within 7 days.
- **Triage + initial assessment:** within 14 days.
- **Fix or workaround:** depends on severity and complexity. Critical
  remote-code-execution or authentication-bypass bugs are prioritised
  ahead of everything else; lower-severity issues are bundled into the
  next normal release.

There is **no bug bounty**. This is a hobby project; financial reward
isn't on offer. Credit in the changelog is offered (unless you ask to
remain anonymous).

## In Scope

The following classes of issue are in scope and welcome:

- **Authentication / authorization** — privilege escalation between
  the `viewer` / `editor` / `admin` roles, IDOR across the
  per-user-partitioned data, session-handling weaknesses, CSRF gaps
  on state-changing routes.
- **Injection** — SQL injection, command injection (notably anywhere a
  user-supplied path or filename flows into a subprocess), template
  injection, header injection.
- **XSS** — stored or reflected, in any template or in any JS sink
  (`innerHTML`, `showNotification`, `showModal`/`showConfirm`,
  toast bodies). The project intentionally uses a CSP nonce; bypasses
  count.
- **Path traversal / arbitrary file read or write** — anywhere a
  user-supplied filename or directory flows into a filesystem
  operation, including the ROM scanner, archive extractor, CHD
  converter, image-resize job, and scraped-media downloaders.
- **SSRF** — anywhere a user-supplied URL or a scraper-response URL
  flows into a network request. The project filters private CIDRs
  but defence-in-depth bypasses are interesting.
- **Decompression bombs / resource exhaustion** — anywhere the app
  opens an untrusted image, archive, or CHD without a size or
  decompressed-size bound.
- **Credential leakage in logs** — anything that bypasses the log
  redactor (`services/log_redactor.py`).
- **Race conditions with security impact** — TOCTOU on path
  validation, double-fetch on scraper URL resolution, etc.

## Out of Scope

- **Reports purely against running the app exposed to the open internet.**
  RetroDB is designed for `localhost` or a trusted LAN. "I exposed
  port 5000 to the public internet without a reverse proxy and got
  pwned" is a deployment issue, not a RetroDB issue. The
  `docs/PROXY-DEPLOY.md` guide documents the supported deployment
  shape.
- **Denial-of-service on a self-hosted single-user app** — by design,
  one user can exhaust their own server. Reports that require an
  attacker to *already* be an authenticated admin to "DoS the admin's
  own machine" aren't useful.
- **Defaults that the operator can tighten** (rate-limit values,
  upload size caps that ship lenient for usability). If the setting
  is admin-editable, treat the bug report as "default could be
  tighter" rather than a vulnerability.
- **Bugs in pinned upstream dependencies** unless RetroDB *uses* the
  dependency in a way that exposes the bug. Please report those
  upstream; we'll pick up the fix on the next dependency-floor bump.
- **Missing security headers that are explicitly configured** in
  `services/security.py` — open an issue for "I'd like header X
  enabled by default", not a security advisory.
- **Social-engineering / phishing concerns against the operator** —
  out of scope for an app that lives on the operator's own LAN.

## Disclosure Timeline

Coordinated disclosure is preferred:

1. You report privately (email or GitHub PVR).
2. We confirm receipt and start triage.
3. A fix lands on `main` and is included in the next release.
4. The changelog entry credits the reporter (unless they prefer to
   stay anonymous) and describes the issue at the level needed to
   understand the fix.
5. A GitHub Security Advisory is published once the fix is in a
   released version, with a CVE if the issue warrants one.

If a reported issue is also independently disclosed publicly before a
fix lands, we may publish a hot-fix release with limited detail and
follow up with the full advisory once the patch has had time to
propagate.

Thank you for helping keep RetroDB and its users safe.
