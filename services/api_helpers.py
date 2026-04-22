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


def success(data=None, **extra):
    """Build the canonical success JSON response.

    Produces `{'success': True, 'data': ..., **extra}` when `data` is
    supplied, or `{'success': True, **extra}` otherwise. `extra` lets callers
    attach additional top-level keys (counts, ids, pagination) without having
    to assemble the envelope by hand.

    Usage:
        return success()                       # {'success': True}
        return success({'id': 5})              # {'success': True, 'data': {'id': 5}}
        return success(games, total=len(games))# {'success': True, 'data': [...], 'total': N}
    """
    payload = {'success': True}
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    return jsonify(payload)


def error(message, code=400, **extra):
    """Build the canonical error JSON response.

    Returns a `(response, code)` tuple suitable for direct `return` from a
    Flask route. `extra` allows additional context fields (e.g. `field`,
    `details`) to ride alongside the error message.

    Usage:
        return error('Game not found', 404)
        return error('Validation failed', 422, field='title')

    For unhandled exceptions use @handle_api_errors — it emits a 500 with the
    same envelope shape and logs the stack trace.
    """
    return jsonify({'success': False, 'error': message, **extra}), code
