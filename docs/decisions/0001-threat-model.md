# 0001 — Designed for a trusted home network

**Status:** accepted. **Recorded:** 2026-10-17 (roadmap PASS-59-65).

## Context

RetroDB serves one household's game library. People in the house use it
from their own phones, laptops and TVs, so the server has to be reachable
from other devices on the home network.

Every security finding needs a severity. A severity needs an attacker in
mind. Before this record, no design document named that attacker (roadmap
PASS-59-65).

Origins:

- The server has bound every interface by default since the repository's
  first commit (`f2e7335`). `SERVER_HOST` in `config.example.py` defaults to
  `0.0.0.0`, and `RETRODB_HOST` overrides it.
- The changelog entry for v2.77.6 turned debug mode off by default. Its
  reason was that the `0.0.0.0` default made the debugger reachable on a
  home network (`data/changelog.yaml`).
- Pass 24.1 made every role sign in with a password
  (`routes/auth.py::api_login`).
- The user confirmed on 2026-06-10 that reaching RetroDB from other devices
  is intended. That confirmation was held in agent notes, not in the
  repository.

## Decision

- RetroDB is designed for a trusted home network: one household, one
  install.
- The server binds every interface by default, on purpose, so household
  devices can reach it. `app.py` and `start.sh` print a Network address
  for exactly this use.
- RetroDB is not designed to face the internet directly. Anyone who exposes
  it follows [`../PROXY-DEPLOY.md`](../PROXY-DEPLOY.md): a reverse proxy that
  terminates TLS, with `RETRODB_TRUST_PROXY=1`.
- Every role signs in with a password.
- The viewer role can only read the library and track its own progress
  (`services/auth.py::ROLE_PERMISSIONS`).
- A finding's severity is judged against a curious guest on the home
  Wi-Fi, not a remote attacker.

## Consequences

- A finding that needs internet exposure to matter is low severity, unless
  the deployment changes.
- A finding a guest on the Wi-Fi could exploit without an account keeps its
  full severity.
- Hardening that adds friction to a household's sign-in needs a reason
  under this model, not under a remote-attacker model.
- Where another document describes RetroDB as localhost-only, this record
  governs.
