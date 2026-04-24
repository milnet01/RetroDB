"""Regression tests for Pass 30.6 — `resolve_terminal_status(cancelled)`
must distinguish a SIGTERM-triggered cancel (→ 'interrupted', recoverable
via the dashboard banner) from a user-initiated cancel (→ 'cancelled',
final and not recoverable) so `mark_jobs_interrupted` at startup can see
the running rows again.
"""

from services.jobs.base import resolve_terminal_status, shutdown_requested


def test_clean_completion_returns_completed():
    shutdown_requested.clear()
    assert resolve_terminal_status(cancelled=False) == 'completed'


def test_user_cancel_returns_cancelled():
    shutdown_requested.clear()
    assert resolve_terminal_status(cancelled=True) == 'cancelled'


def test_shutdown_takes_precedence_over_user_cancel():
    # During SIGTERM drain, j.cancel() sets self.cancelled = True, so the
    # terminal branch sees both signals. Shutdown must win — the row stays
    # recoverable for the next startup's sweep rather than being filed as
    # a final user cancel.
    shutdown_requested.set()
    try:
        assert resolve_terminal_status(cancelled=True) == 'interrupted'
        assert resolve_terminal_status(cancelled=False) == 'interrupted'
    finally:
        shutdown_requested.clear()


def test_event_clear_restores_normal_mapping():
    shutdown_requested.set()
    shutdown_requested.clear()
    assert resolve_terminal_status(cancelled=False) == 'completed'
    assert resolve_terminal_status(cancelled=True) == 'cancelled'
