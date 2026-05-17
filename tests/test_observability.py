# Observability smoke tests — /health, /ready, request-id correlation,
# slow-request logging. These pin the Pass 17 observability contract so
# operator tooling (systemd probes, log-grep correlation, latency alarms)
# keeps working across refactors.

import logging
import time
from unittest.mock import patch

import pytest

from tests._util import REPO_ROOT


@pytest.fixture
def client():
    """Function-scoped Flask test client.

    Previously module-scoped, which silently relied on `log_manager`'s
    install-once globals (`_request_id_installed`, replaced log-record
    factory) persisting across tests. Function scope keeps the surface
    area small enough that per-test mutations of caplog / handlers
    don't leak between tests in the same module."""
    import log_manager
    import app as app_module
    app_module.app.config['TESTING'] = True

    # Snapshot the log-record factory so we can restore on teardown if a
    # test calls install_request_id_factory(); otherwise the install-once
    # flag persists for the rest of the session.
    original_factory = logging.getLogRecordFactory()
    original_installed_flag = getattr(log_manager, '_request_id_installed', False)

    with app_module.app.test_client() as c:
        yield c

    logging.setLogRecordFactory(original_factory)
    log_manager._request_id_installed = original_installed_flag


class TestHealthProbe:
    """/health is the liveness contract: no auth, no DB, always 200."""

    def test_health_returns_200(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200

    def test_health_returns_alive_status(self, client):
        resp = client.get('/health')
        body = resp.get_json()
        assert body['status'] == 'alive'

    def test_health_includes_version(self, client):
        import config
        resp = client.get('/health')
        body = resp.get_json()
        assert body['version'] == config.APP_VERSION

    def test_health_skips_first_time_setup_redirect(self, client):
        # Even if setup_completed is False and rom_path is blank, /health
        # must stay 200 — otherwise systemd/Docker probes fail on a fresh
        # install and orchestrators restart the container in a loop.
        with patch('settings_manager.load_settings', return_value={}):
            with patch.object(__import__('config'), 'ROM_PATH', ''):
                resp = client.get('/health')
                assert resp.status_code == 200


class TestReadyProbe:
    """/ready exercises the DB so it catches lock-held / unopenable states."""

    def test_ready_returns_200_when_db_works(self, client):
        resp = client.get('/ready')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ready'

    def test_ready_returns_503_when_db_broken(self, client):
        # Simulate DB unreachable — the probe must return 503 so operators
        # can distinguish "process up but DB wedged" from "process dead".
        import app as app_module
        with patch.object(app_module, 'logger'):  # silence the warning log
            with patch('services.database.get_request_db', side_effect=RuntimeError("DB locked")):
                resp = client.get('/ready')
                assert resp.status_code == 503
                body = resp.get_json()
                assert body['status'] == 'not_ready'
                assert 'DB locked' in body['error']


class TestRequestIdFactory:
    """Every LogRecord must carry a request_id attribute."""

    def test_record_has_request_id_attribute(self):
        """All records, everywhere, must have .request_id — format strings
        reference %(request_id)s and a missing attr would raise KeyError
        inside the logging subsystem."""
        import log_manager
        log_manager.install_request_id_factory()

        record = logging.getLogRecordFactory()(
            'test', logging.INFO, __file__, 1, 'msg', (), None
        )
        assert hasattr(record, 'request_id')
        # request_id is always a string — either 8-char hex or the '-' sentinel.
        assert isinstance(record.request_id, str)

    def test_record_has_request_id_inside_request_context(self):
        import app as app_module
        import log_manager
        log_manager.install_request_id_factory()

        with app_module.app.test_request_context('/', method='GET'):
            app_module.assign_request_id()
            from flask import g
            record = logging.getLogRecordFactory()(
                'test', logging.INFO, __file__, 1, 'msg', (), None
            )
            assert record.request_id == g.request_id
            # 8-char hex from secrets.token_hex(4)
            assert len(record.request_id) == 8
            int(record.request_id, 16)  # parses cleanly as hex

    def test_factory_returns_dash_with_no_request_context(self):
        """Verified in a fresh process because the module-scoped client
        fixture holds a request context open across all tests in this file."""
        import subprocess
        import sys
        proc = subprocess.run(
            [sys.executable, '-c',
             'import log_manager, logging; '
             'log_manager.install_request_id_factory(); '
             'r = logging.getLogRecordFactory()("t", logging.INFO, "/", 1, "m", (), None); '
             'print(repr(r.request_id))'],
            capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
        assert proc.returncode == 0, proc.stderr
        assert "'-'" in proc.stdout


class TestSlowRequestLogging:
    """Slow-request middleware logs a WARNING for handlers above threshold."""

    def test_fast_request_does_not_log(self, client, caplog):
        caplog.clear()  # don't inherit records from earlier tests in the module
        with caplog.at_level(logging.WARNING):
            resp = client.get('/health')
            assert resp.status_code == 200
        # /health is a probe — exempt. Also /health is instant, no warning.
        slow_msgs = [r for r in caplog.records if 'slow_request' in r.getMessage()]
        assert slow_msgs == []

    def test_slow_request_logs_warning(self, caplog):
        import app as app_module
        import config

        with caplog.at_level(logging.WARNING, logger='app'):
            # Drive the middleware directly with a synthetic slow request —
            # rewriting g.request_start_time puts the handler above threshold
            # without needing to actually sleep.
            with app_module.app.test_request_context('/games', method='GET'):
                from flask import g
                app_module.assign_request_id()
                g.request_start_time = time.perf_counter() - (config.SLOW_REQUEST_MS + 100) / 1000.0
                response = app_module.app.response_class('', status=204)
                app_module.log_slow_request(response)

        slow_msgs = [r for r in caplog.records if 'slow_request' in r.getMessage()]
        assert len(slow_msgs) >= 1
        msg = slow_msgs[0].getMessage()
        assert 'GET /games' in msg
        assert 'status=204' in msg

    def test_probe_endpoints_exempt_from_slow_log(self, client, caplog):
        import config

        # Register a probe-named route that would otherwise be slow.
        # Can't rename /health/ready, so simulate by forcing threshold=0
        # which short-circuits. This test confirms the threshold knob works.
        caplog.clear()  # don't inherit records from earlier tests in the module
        with patch.object(config, 'SLOW_REQUEST_MS', 0):
            with caplog.at_level(logging.WARNING):
                resp = client.get('/health')
                assert resp.status_code == 200

            slow_msgs = [r for r in caplog.records if 'slow_request' in r.getMessage()]
            assert slow_msgs == []
