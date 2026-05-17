"""Tests for PBKDF2 password hashing and the legacy-hash migration path.

Covers the Pass 11.1 upgrade from 100k to 600k iterations and the
"<salt>:<hash>" → "pbkdf2:<iters>:<salt>:<hash>" format change.
"""

import hashlib

import pytest

from services.auth import (
    PBKDF2_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)


# Cheap iteration count for format / round-trip / structural tests. The one
# dedicated compliance test below (`test_pbkdf2_iterations_meets_owasp_floor`)
# is the only place the production cost is paid; everything else runs in
# milliseconds. See PERF-1 in `.test-audit-reports/c-001.md`.
TEST_ITERATIONS = 1


def _make_legacy_hash(password="legacy_password"):
    """Hand-construct a pre-v2.84.0 `<salt>:<hash>` (100k iterations).

    Shared by `test_verify_accepts_legacy_format` +
    `test_needs_rehash_flags_legacy_format` so the legacy format is
    described in one place — see DUP-1 in `.test-audit-reports/c-001.md`.
    """
    salt = "deadbeef" * 4  # 32 hex chars
    legacy_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100_000
    ).hex()
    return password, f"{salt}:{legacy_hash}"


def test_pbkdf2_iterations_meets_owasp_floor():
    """Compliance pin: the production iteration count must stay at or above
    the OWASP 2026 PBKDF2-SHA256 floor (600k). Lowering this is a security
    regression even if every other test in this file passes."""
    assert PBKDF2_ITERATIONS >= 600_000


def test_new_hash_uses_current_format_and_iterations():
    h = hash_password("hunter2", iterations=TEST_ITERATIONS)
    parts = h.split(":")
    assert parts[0] == "pbkdf2"
    assert int(parts[1]) == TEST_ITERATIONS
    assert len(parts) == 4
    # salt is 32 hex chars (16 bytes)
    assert len(parts[2]) == 32
    # sha256 hex is 64 chars
    assert len(parts[3]) == 64


def test_verify_roundtrip_current_format():
    h = hash_password("correct horse battery staple", iterations=TEST_ITERATIONS)
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_verify_accepts_legacy_format():
    # Hand-construct a legacy "<salt>:<hash>" at 100k iterations, the
    # pre-v2.84.0 format, to ensure existing stored credentials still
    # verify after the upgrade.
    password, legacy_stored = _make_legacy_hash()
    assert verify_password(password, legacy_stored) is True
    assert verify_password("wrong", legacy_stored) is False


def test_needs_rehash_flags_legacy_format():
    _password, legacy_stored = _make_legacy_hash()
    assert needs_rehash(legacy_stored) is True


def test_needs_rehash_flags_low_iteration_pbkdf2():
    # Explicitly-prefixed hashes with old iteration counts should also
    # be flagged for upgrade.
    old = hash_password("x", iterations=100_000)
    assert old.startswith("pbkdf2:100000:")
    assert needs_rehash(old) is True


def test_needs_rehash_accepts_current_hash():
    # `needs_rehash` only reads the iteration count from the prefix — it
    # doesn't verify the hash bytes. We can synthesise a "fresh" hash
    # string at the production iteration count without actually paying
    # for 600k PBKDF2 rounds. The compliance floor itself is pinned by
    # `test_pbkdf2_iterations_meets_owasp_floor`.
    fresh = f"pbkdf2:{PBKDF2_ITERATIONS}:" + ("a" * 32) + ":" + ("b" * 64)
    assert needs_rehash(fresh) is False


@pytest.mark.parametrize("h", ["not-a-hash", "", "pbkdf2:notanumber:salt:hash"])
def test_needs_rehash_flags_malformed_hash(h):
    # Defensively reject anything unparseable, so callers migrate the
    # stored credential on next login rather than trust it forever.
    assert needs_rehash(h) is True


@pytest.mark.parametrize("h", ["", "garbage", "pbkdf2:bad:salt:hash"])
def test_verify_rejects_malformed_hash(h):
    assert verify_password("x", h) is False
