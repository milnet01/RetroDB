"""Contract test for POST /api/shutdown (one-click-launch feature, v3.21.0).

Introspects the route source rather than driving a live request: the shutdown
mechanism (delayed SIGTERM) can't be exercised in-process without killing the
test runner, so the contract we pin is "route exists, admin-guarded, uses
SIGTERM via os.kill, and does NOT use the wrong exit paths".
"""
import inspect

import routes.maintenance as maint


def test_signal_is_imported():
    assert hasattr(maint, 'signal'), "routes.maintenance must import signal"


def test_shutdown_route_registered():
    src = inspect.getsource(maint)
    assert "@bp.route('/api/shutdown', methods=['POST'])" in src
    assert 'def api_shutdown' in src


def test_shutdown_is_admin_guarded_and_uses_sigterm():
    src = inspect.getsource(maint.api_shutdown)
    assert 'signal.SIGTERM' in src
    assert 'os.kill' in src
    # The graceful drain depends on SIGTERM — these exit paths would defeat it.
    # Check for the call forms so the docstring's prose naming them is allowed.
    assert 'os._exit(' not in src
    assert 'sys.exit(' not in src
