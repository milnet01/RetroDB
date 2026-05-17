"""Regression tests for Pass 30.6 — `resolve_terminal_status(cancelled)`
must distinguish a SIGTERM-triggered cancel (→ 'interrupted', recoverable
via the dashboard banner) from a user-initiated cancel (→ 'cancelled',
final and not recoverable) so `mark_jobs_interrupted` at startup can see
the running rows again.
"""

import pytest

from services.jobs.base import resolve_terminal_status, shutdown_requested


@pytest.fixture(autouse=True)
def reset_shutdown_event():
    """Ensure every test sees a cleared `shutdown_requested` event, regardless
    of leakage from a prior test that set it and failed before its own cleanup
    ran. Clearing on both sides of the yield protects subsequent tests too."""
    shutdown_requested.clear()
    yield
    shutdown_requested.clear()


@pytest.mark.parametrize("set_event,cancelled,expected", [
    # Clean completion — no shutdown, not cancelled — maps to 'completed'.
    (False, False, 'completed'),
    # User-initiated cancel — no shutdown pending — maps to final 'cancelled'.
    (False, True, 'cancelled'),
    # SIGTERM drain — shutdown set, j.cancel() also flipped cancelled=True.
    # Shutdown must win so the row stays recoverable for the next startup
    # sweep rather than being filed as a final user cancel.
    (True, True, 'interrupted'),
    # SIGTERM drain on a job that hadn't been user-cancelled yet — same
    # interrupted outcome.
    (True, False, 'interrupted'),
])
def test_resolve_terminal_status_mapping(set_event, cancelled, expected):
    """Truth table for resolve_terminal_status across the (shutdown × cancelled)
    matrix. Shutdown overrides the user-cancel signal in both columns."""
    if set_event:
        shutdown_requested.set()
    assert resolve_terminal_status(cancelled=cancelled) == expected
