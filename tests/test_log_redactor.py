"""Tests for the SecretRedactor log filter."""

import logging
from services.log_redactor import redact, SecretRedactor


class TestRedactPatterns:
    def test_jwt_is_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSIsIm5hbWUiOiJhYWFhIn0.abc123DEF456ghi"
        assert "<redacted-jwt>" in redact(f"got token {jwt} from idp")
        assert jwt not in redact(f"got token {jwt} from idp")

    def test_access_token_json_field_is_redacted(self):
        payload = '{"access_token": "super-secret-value-1234", "token_type": "Bearer"}'
        out = redact(payload)
        assert "super-secret-value-1234" not in out
        assert "<redacted>" in out

    def test_authorization_header_is_redacted(self):
        line = "Request: Authorization: Bearer abc.def.ghi"
        out = redact(line)
        assert "abc.def.ghi" not in out
        assert "<redacted>" in out

    def test_apikey_query_param_is_redacted(self):
        url = "https://api.example.com/search?apikey=ABCD1234&q=zelda"
        out = redact(url)
        assert "ABCD1234" not in out
        assert "q=zelda" in out  # non-secret params preserved

    def test_long_hex_string_is_redacted(self):
        h = "a" * 64  # SHA256 style
        assert "<redacted-hex>" in redact(f"hash={h}")

    def test_short_hex_is_not_redacted(self):
        # CRC32, md5-hash-as-id fragments (8 chars) should pass through
        assert "abc12345" in redact("crc=abc12345")

    def test_none_returns_none_safely(self):
        assert redact(None) is None
        assert redact("") == ""


class TestSecretRedactorFilter:
    def test_filter_redacts_record_msg(self):
        f = SecretRedactor()
        record = logging.LogRecord(
            name="scraper",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='Response: {"access_token": "leakme"}',
            args=(),
            exc_info=None,
        )
        f.filter(record)
        assert "leakme" not in record.msg
        assert "<redacted>" in record.msg

    def test_filter_redacts_positional_args(self):
        f = SecretRedactor()
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abc123DEFghi456jklMNOpqrSTU"
        record = logging.LogRecord(
            name="scraper",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="got token %s",
            args=(jwt,),
            exc_info=None,
        )
        f.filter(record)
        # Record arg is redacted
        formatted = record.getMessage()
        assert jwt not in formatted
        assert "<redacted-jwt>" in formatted

    def test_filter_always_returns_true(self):
        # The filter must never drop a record — it's a mutator, not a gate.
        f = SecretRedactor()
        record = logging.LogRecord(
            name="scraper",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="plain message",
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True


class TestInstallGlobalRedactor:
    def test_root_filter_is_idempotent(self):
        import log_manager

        root = logging.getLogger()
        # Start clean so a prior test run doesn't taint the count.
        root.filters = [f for f in root.filters if not isinstance(f, SecretRedactor)]

        try:
            log_manager.install_global_redactor()
            log_manager.install_global_redactor()  # second call must not duplicate

            redactors = [f for f in root.filters if isinstance(f, SecretRedactor)]
            assert len(redactors) == 1
        finally:
            # Strip whatever SecretRedactor instances this test installed so
            # subsequent tests / files see a clean root logger.
            root.filters = [f for f in root.filters if not isinstance(f, SecretRedactor)]

    def test_install_covers_basicconfig_handler(self):
        # caplog removed — it was an unused fixture parameter (the assertion
        # below reads `handler.filters`, not captured log records).
        import io
        import log_manager

        # Set up a fresh root StreamHandler (what basicConfig would install)
        # and confirm install_global_redactor() attaches SecretRedactor to it.
        buf = io.StringIO()
        root = logging.getLogger()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
        try:
            log_manager.install_global_redactor()
            attached = any(isinstance(f, SecretRedactor) for f in handler.filters)
            assert attached, (
                "install_global_redactor() did not attach a SecretRedactor "
                "to the root StreamHandler"
            )
        finally:
            root.removeHandler(handler)
            # Strip any redactor this call attached to the root logger so
            # subsequent tests / files see a clean filter list.
            root.filters = [f for f in root.filters if not isinstance(f, SecretRedactor)]

    def test_filter_redacts_dict_args(self):
        """Coverage gap (audit MED): SecretRedactor.filter must also redact
        dict-style log args. `logger.info("%(token)s", {'token': ...})` lands
        in a LogRecord as `args=({'token': ...},)` — a 1-tuple wrapping the
        mapping; that's the form the filter must handle."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abc123DEFghi456jklMNOpqrSTU"
        f = SecretRedactor()
        record = logging.LogRecord(
            name="scraper",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="got token %(val)s",
            args=({'val': jwt},),
            exc_info=None,
        )
        f.filter(record)
        formatted = record.getMessage()
        assert jwt not in formatted
        assert "<redacted-jwt>" in formatted
