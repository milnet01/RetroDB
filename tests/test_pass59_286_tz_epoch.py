"""PASS-59-286: the `tz` filter must turn a Unix time into a date.

Steam stores an achievement's `unlock_time` as whole seconds since 1970. The
filter only knew datetimes and strings, so the Steam achievement page showed
the raw number instead of the date it was unlocked.
"""
from flask import Flask, g

from services.template_filters import tz_filter


def _render(value, fmt, tz='UTC'):
    with Flask(__name__).app_context():
        g.user_settings = {'timezone': tz}
        return tz_filter(value, fmt)


def test_epoch_seconds_become_a_date():
    assert _render(1700000000, 'short') == '2023-11-14 22:13'


def test_epoch_follows_the_users_timezone():
    assert _render(1700000000, 'short', 'Africa/Johannesburg') == '2023-11-15 00:13'


def test_float_epoch_is_accepted():
    assert _render(1700000000.5, 'date') == '2023-11-14'


def test_strings_still_work():
    assert _render('2023-11-14 22:13:20', 'short') == '2023-11-14 22:13'
