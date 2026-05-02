"""Tests for PBKDF2 password hashing and the legacy-hash migration path.

Covers the Pass 11.1 upgrade from 100k to 600k iterations and the
"<salt>:<hash>" → "pbkdf2:<iters>:<salt>:<hash>" format change.
"""

import hashlib


from services.auth import (
    PBKDF2_ITERATIONS,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_new_hash_uses_current_format_and_iterations():
    h = hash_password("hunter2")
    parts = h.split(":")
    assert parts[0] == "pbkdf2"
    assert int(parts[1]) == PBKDF2_ITERATIONS
    assert len(parts) == 4
    # salt is 32 hex chars (16 bytes)
    assert len(parts[2]) == 32
    # sha256 hex is 64 chars
    assert len(parts[3]) == 64


def test_verify_roundtrip_current_format():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_verify_accepts_legacy_format():
    # Hand-construct a legacy "<salt>:<hash>" at 100k iterations, the
    # pre-v2.84.0 format, to ensure existing stored credentials still
    # verify after the upgrade.
    password = "legacy_password"
    salt = "deadbeef" * 4  # 32 hex chars
    legacy_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    legacy_stored = f"{salt}:{legacy_hash}"
    assert verify_password(password, legacy_stored) is True
    assert verify_password("wrong", legacy_stored) is False


def test_needs_rehash_flags_legacy_format():
    password = "legacy_password"
    salt = "deadbeef" * 4
    legacy_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    legacy_stored = f"{salt}:{legacy_hash}"
    assert needs_rehash(legacy_stored) is True


def test_needs_rehash_flags_low_iteration_pbkdf2():
    # Explicitly-prefixed hashes with old iteration counts should also
    # be flagged for upgrade.
    old = hash_password("x", iterations=100_000)
    assert old.startswith("pbkdf2:100000:")
    assert needs_rehash(old) is True


def test_needs_rehash_accepts_current_hash():
    fresh = hash_password("x")
    assert needs_rehash(fresh) is False


def test_needs_rehash_flags_malformed_hash():
    # Defensively reject anything unparseable, so callers migrate the
    # stored credential on next login rather than trust it forever.
    assert needs_rehash("not-a-hash") is True
    assert needs_rehash("") is True
    assert needs_rehash("pbkdf2:notanumber:salt:hash") is True


def test_verify_rejects_malformed_hash():
    assert verify_password("x", "") is False
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "pbkdf2:bad:salt:hash") is False
