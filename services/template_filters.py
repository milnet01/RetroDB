# =============================================================================
# RETRODB - Jinja Template Filters
# =============================================================================
# Call `register_filters(app)` from the Flask app setup to install these.
# =============================================================================

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import g

from services.formatters import format_size
from services.image_utils import boxart_srcset


def timestamp_to_date(timestamp):
    """Convert Unix timestamp to date string."""
    if timestamp:
        try:
            dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError, OSError):
            return str(timestamp)
    return ""


def trophy_type_name_filter(trophy_type):
    """Convert trophy type letter to full name for image filename."""
    return {'P': 'platinum', 'G': 'gold', 'S': 'silver', 'B': 'bronze'}.get(trophy_type, 'bronze')


def format_number_filter(num):
    """Format number with space as thousand separator (e.g., 12573 → 12 573)."""
    if num is None:
        return '0'
    try:
        n = int(num)
        return '{:,}'.format(n).replace(',', ' ')
    except (ValueError, TypeError):
        return str(num)


def format_size_filter(bytes_size):
    """Format bytes to human readable size (also available as Jinja filter)."""
    return format_size(bytes_size)


def format_ratio_filter(numerator, denominator):
    """Format a ratio as 'X / Y' with proper number formatting."""
    num = format_number_filter(numerator)
    den = format_number_filter(denominator)
    return f"{num} / {den}"


def tz_filter(value, fmt='datetime'):
    """Convert a UTC datetime string to the current user's timezone.

    fmt: 'datetime' → 'YYYY-MM-DD HH:MM:SS'
         'date'     → 'YYYY-MM-DD'
         'short'    → 'YYYY-MM-DD HH:MM'
    """
    if not value:
        return value

    try:
        user_tz_name = 'UTC'
        user_settings_obj = g.get('user_settings')
        if user_settings_obj:
            if hasattr(user_settings_obj, 'get'):
                user_tz_name = user_settings_obj.get('timezone', 'UTC') or 'UTC'
            elif hasattr(user_settings_obj, 'keys') and 'timezone' in user_settings_obj.keys():
                user_tz_name = user_settings_obj['timezone'] or 'UTC'

        user_tz = ZoneInfo(user_tz_name)

        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            clean = value.strip()
            if clean.endswith('Z'):
                clean = clean[:-1] + '+00:00'
            dt = None
            try:
                dt = datetime.fromisoformat(clean)
            except (ValueError, TypeError):
                pass
            if dt is None:
                clean2 = clean.replace('T', ' ')
                for pattern in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f',
                                '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                    try:
                        dt = datetime.strptime(clean2[:len('2000-01-01 00:00:00.000000')], pattern)
                        break
                    except ValueError:
                        continue
            if dt is None:
                return value
        else:
            return value

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        local_dt = dt.astimezone(user_tz)

        if fmt == 'date':
            return local_dt.strftime('%Y-%m-%d')
        elif fmt == 'short':
            return local_dt.strftime('%Y-%m-%d %H:%M')
        else:
            return local_dt.strftime('%Y-%m-%d %H:%M:%S')

    except (ValueError, TypeError, KeyError, AttributeError):
        return value


def register_filters(app):
    """Register all RetroDB Jinja filters on the given Flask app."""
    app.template_filter('timestamp_to_date')(timestamp_to_date)
    app.template_filter('trophy_type_name')(trophy_type_name_filter)
    app.template_filter('format_number')(format_number_filter)
    app.template_filter('format_size')(format_size_filter)
    app.template_filter('format_ratio')(format_ratio_filter)
    app.template_filter('tz')(tz_filter)
    app.jinja_env.globals['boxart_srcset'] = boxart_srcset
