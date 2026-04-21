# =============================================================================
# RETRODB - API Helpers
# =============================================================================
# Shared decorators and helpers for JSON API route handlers.
# =============================================================================

import logging
from functools import wraps

from flask import jsonify


def handle_api_errors(func):
    """Catch unhandled exceptions in a JSON route handler.

    Logs the exception with stack trace under the wrapped function's module
    logger, then returns the project-standard 500 response:
        {'success': False, 'error': 'An internal error occurred'}, 500

    Usage:
        @bp.route('/api/foo')
        @login_required
        @handle_api_errors
        def api_foo():
            ...

    Decorator order matters: place @handle_api_errors innermost so it wraps
    the route body directly. Auth decorators above it then skip the try/except
    for unauthorized requests (which should short-circuit with a redirect or
    401, not a 500).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.getLogger(func.__module__).error(
                f"{func.__name__} failed: {e}", exc_info=True
            )
            return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
    return wrapper
