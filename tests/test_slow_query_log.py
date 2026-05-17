"""Tests for the slow-query log gate in services.database._log_if_slow."""

import logging
import time
from unittest.mock import patch

import pytest

import config
from services.database import _log_if_slow


@pytest.fixture
def capture_db_log(caplog):
    """Capture WARNING-and-above records from the services.database logger.

    Replaces the manual `_CaptureHandler` + `try/finally` boilerplate that
    leaked the handler if a test threw before reaching the cleanup line
    (test-audit c-007 MED-1 / LOW-5).
    """
    caplog.set_level(logging.WARNING, logger='services.database')
    return caplog


class TestSlowQueryGate:
    def test_disabled_when_threshold_zero(self, capture_db_log):
        with patch.object(config, 'SLOW_QUERY_MS', 0):
            # Start far enough in the past that any nonzero threshold
            # would trip — but threshold is 0, so nothing should log.
            _log_if_slow("SELECT 1", (), time.perf_counter() - 10.0)
        assert capture_db_log.records == []

    def test_fast_query_below_threshold_does_not_log(self, capture_db_log):
        with patch.object(config, 'SLOW_QUERY_MS', 100):
            _log_if_slow("SELECT 1", (), time.perf_counter())
        assert capture_db_log.records == []

    def test_slow_query_above_threshold_logs_warning(self, capture_db_log):
        with patch.object(config, 'SLOW_QUERY_MS', 50):
            # Back-date the start by 1 second so (now - start) >> 50 ms.
            _log_if_slow(
                "SELECT * FROM games WHERE id = ?",
                (42,),
                time.perf_counter() - 1.0,
            )
        assert len(capture_db_log.records) == 1
        record = capture_db_log.records[0]
        assert record.levelno == logging.WARNING
        msg = record.getMessage()
        assert 'slow_query' in msg
        assert 'SELECT * FROM games WHERE id = ?' in msg
        assert 'args=1' in msg

    def test_sql_whitespace_is_compacted(self, capture_db_log):
        with patch.object(config, 'SLOW_QUERY_MS', 10):
            _log_if_slow(
                "SELECT\n    *\n    FROM\n    games",
                (),
                time.perf_counter() - 1.0,
            )
        assert len(capture_db_log.records) >= 1, "_log_if_slow did not emit a WARNING record"
        msg = capture_db_log.records[0].getMessage()
        assert 'SELECT * FROM games' in msg
        assert '\n' not in msg

    def test_long_sql_is_truncated(self, capture_db_log):
        long_sql = "SELECT * FROM games WHERE title = '" + ("x" * 1000) + "'"
        with patch.object(config, 'SLOW_QUERY_MS', 10):
            _log_if_slow(long_sql, (), time.perf_counter() - 1.0)
        assert len(capture_db_log.records) >= 1, "_log_if_slow did not emit a WARNING record"
        msg = capture_db_log.records[0].getMessage()
        # Truncated to 500 chars + ellipsis sentinel; pin the size bound so a
        # regression that removes the cap (or bumps it 10×) is caught — prior
        # assertion only checked for the '...' marker, which can appear in
        # any-length message.
        assert '...' in msg
        assert len(msg) < 700, (
            f"Message length {len(msg)} exceeds the 500-char SQL truncation "
            f"budget (plus ~200 chars of label/duration prefix)."
        )

    def test_non_sequence_args_still_logs(self, capture_db_log):
        # execute_script passes a raw string, not a tuple.
        with patch.object(config, 'SLOW_QUERY_MS', 10):
            _log_if_slow("CREATE TABLE x (...)", None, time.perf_counter() - 1.0)
        assert len(capture_db_log.records) == 1
        assert 'args=0' in capture_db_log.records[0].getMessage()

    def test_non_iterable_args_logs_minus_one(self, capture_db_log):
        """The `TypeError` fallback in _log_if_slow (services/database.py:42-43)
        fires when `len(args)` raises — e.g. when a future caller passes an
        integer or other non-Sized object. The handler files this as
        `arg_count = -1` so the log line still emits cleanly. Mirror shape of
        `test_non_sequence_args_still_logs` — same threshold/back-date pattern,
        same single-record assertion."""
        with patch.object(config, 'SLOW_QUERY_MS', 10):
            _log_if_slow("SELECT * FROM games", 42, time.perf_counter() - 1.0)
        assert len(capture_db_log.records) == 1
        assert 'args=-1' in capture_db_log.records[0].getMessage()
