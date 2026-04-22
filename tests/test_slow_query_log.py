"""Tests for the slow-query log gate in services.database._log_if_slow."""

import logging
import time
from unittest.mock import patch

import config
from services.database import _log_if_slow


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestSlowQueryGate:
    def _capture(self):
        handler = _CaptureHandler()
        logger = logging.getLogger('services.database')
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        return handler, logger

    def test_disabled_when_threshold_zero(self):
        handler, logger = self._capture()
        try:
            with patch.object(config, 'SLOW_QUERY_MS', 0):
                # Start far enough in the past that any nonzero threshold
                # would trip — but threshold is 0, so nothing should log.
                _log_if_slow("SELECT 1", (), time.perf_counter() - 10.0)
            assert handler.records == []
        finally:
            logger.removeHandler(handler)

    def test_fast_query_below_threshold_does_not_log(self):
        handler, logger = self._capture()
        try:
            with patch.object(config, 'SLOW_QUERY_MS', 100):
                _log_if_slow("SELECT 1", (), time.perf_counter())
            assert handler.records == []
        finally:
            logger.removeHandler(handler)

    def test_slow_query_above_threshold_logs_warning(self):
        handler, logger = self._capture()
        try:
            with patch.object(config, 'SLOW_QUERY_MS', 50):
                # Back-date the start by 1 second so (now - start) >> 50 ms.
                _log_if_slow(
                    "SELECT * FROM games WHERE id = ?",
                    (42,),
                    time.perf_counter() - 1.0,
                )
            assert len(handler.records) == 1
            record = handler.records[0]
            assert record.levelno == logging.WARNING
            msg = record.getMessage()
            assert 'slow_query' in msg
            assert 'SELECT * FROM games WHERE id = ?' in msg
            assert 'args=1' in msg
        finally:
            logger.removeHandler(handler)

    def test_sql_whitespace_is_compacted(self):
        handler, logger = self._capture()
        try:
            with patch.object(config, 'SLOW_QUERY_MS', 10):
                _log_if_slow(
                    "SELECT\n    *\n    FROM\n    games",
                    (),
                    time.perf_counter() - 1.0,
                )
            msg = handler.records[0].getMessage()
            assert 'SELECT * FROM games' in msg
            assert '\n' not in msg
        finally:
            logger.removeHandler(handler)

    def test_long_sql_is_truncated(self):
        handler, logger = self._capture()
        try:
            long_sql = "SELECT * FROM games WHERE title = '" + ("x" * 1000) + "'"
            with patch.object(config, 'SLOW_QUERY_MS', 10):
                _log_if_slow(long_sql, (), time.perf_counter() - 1.0)
            msg = handler.records[0].getMessage()
            # Truncated to 500 chars + ellipsis sentinel
            assert '...' in msg
        finally:
            logger.removeHandler(handler)

    def test_non_sequence_args_still_logs(self):
        # execute_script passes a raw string, not a tuple.
        handler, logger = self._capture()
        try:
            with patch.object(config, 'SLOW_QUERY_MS', 10):
                _log_if_slow("CREATE TABLE x (...)", None, time.perf_counter() - 1.0)
            assert len(handler.records) == 1
            assert 'args=0' in handler.records[0].getMessage()
        finally:
            logger.removeHandler(handler)
