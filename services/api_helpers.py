# =============================================================================
# RETRODB - API Helpers
# =============================================================================
# Shared decorators and helpers for JSON API route handlers.
# =============================================================================

import logging
from functools import wraps

from flask import abort, jsonify, request
from werkzeug.exceptions import HTTPException
from flask_babel import gettext as _


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
        except HTTPException:
            # A client's 4xx (bad JSON, oversized body, abort()) must reach
            # Flask's error handling, not become a 500 (Pass 59.45).
            raise
        except Exception as e:
            logging.getLogger(func.__module__).error(
                f"{func.__name__} failed: {e}", exc_info=True
            )
            return jsonify({'success': False, 'error': _('An internal error occurred')}), 500
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


def job_reply(result, code=409):
    """Send a background job's own reply dict. A refusal from the job (one
    is already running, or none is to pause or cancel) answers `code`
    instead of 200 (PASS-59-264, decision 0003)."""
    return jsonify(result), (200 if result.get('success') else code)


def json_body():
    """The request's JSON object, or {} when the body is missing or not an object.

    A list or a number as the body would otherwise reach `data.get(...)` and
    end as a 500 (PASS-59-248).
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def text_field(data, key, default=''):
    """`data[key]` as a string; a non-text value answers 400 (PASS-59-248).

    A missing key or JSON null gives `default`. A number, list or object in a
    field the route treats as text is the caller's mistake, not a server error.
    """
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        abort(400, description=_('%(field)s must be text', field=key))
    return value
