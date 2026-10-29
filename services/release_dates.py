# =============================================================================
# RETRODB - Release dates by region
# =============================================================================
# `games.release_dates` (migration 024) holds the date a game came out in each
# region, as a JSON object keyed by region code:
#     {"JP": "2002-11-17", "NA": "2002-11-18", "EU": "2003-03-21"}
# A date is YYYY-MM-DD, or YYYY-MM / YYYY when only that much is known (as
# `release_date`, PASS-59-164). Only the AI fills it, in a scrape's gap-fill and
# in AI Fill. `release_date` stays the date of the row's own release.
# =============================================================================

import json
import re
from datetime import date, datetime

# Region code -> CLDR territory, which names the region in the user's language
# (services.i18n.region_display_name). The order is the AI prompt's.
REGIONS = {
    'NA': '003',   # North America
    'EU': '150',   # Europe (PAL)
    'JP': 'JP',
    'AU': 'AU',
    'KR': 'KR',
    'CN': 'CN',
    'TW': 'TW',
    'BR': 'BR',
    'AS': '142',   # Asia, when no single country is given
    'WW': '001',   # one worldwide release
}

# What a model writes instead of the code it was asked for.
_ALIASES = {
    'north america': 'NA', 'usa': 'NA', 'us': 'NA', 'america': 'NA', 'ntsc-u': 'NA',
    'europe': 'EU', 'pal': 'EU', 'eur': 'EU',
    'japan': 'JP', 'jpn': 'JP', 'ntsc-j': 'JP',
    'australia': 'AU', 'aus': 'AU',
    'korea': 'KR', 'south korea': 'KR', 'kor': 'KR',
    'china': 'CN', 'chn': 'CN',
    'taiwan': 'TW',
    'brazil': 'BR', 'bra': 'BR',
    'asia': 'AS',
    'world': 'WW', 'worldwide': 'WW', 'global': 'WW',
}

_DATE_FORMATS = {4: '%Y', 7: '%Y-%m', 10: '%Y-%m-%d'}
_EARLIEST_YEAR = 1950


def _region_code(name):
    key = str(name or '').strip()
    if key.upper() in REGIONS:
        return key.upper()
    return _ALIASES.get(key.lower())


def _clean_date(value):
    """A YYYY, YYYY-MM or YYYY-MM-DD date that exists and is not far in the
    future, or None."""
    text = str(value or '').strip().replace('/', '-')
    fmt = _DATE_FORMATS.get(len(text))
    if not fmt or not re.fullmatch(r'\d{4}(-\d{2}){0,2}', text):
        return None
    try:
        parsed = datetime.strptime(text, fmt)
    except ValueError:
        return None
    if not _EARLIEST_YEAR <= parsed.year <= date.today().year + 2:
        return None
    return text


def parse_release_dates(value):
    """Regional release dates as {code: date}, in REGIONS order; {} when
    nothing usable is given.

    Takes the stored JSON text, or what an AI returns: an object keyed by
    region code or name, or a list of {"region", "date"} objects. Unknown
    regions and impossible dates are dropped.
    """
    if not value:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    if isinstance(value, list):
        pairs = [(item.get('region'), item.get('date'))
                 for item in value if isinstance(item, dict)]
    elif isinstance(value, dict):
        pairs = list(value.items())
    else:
        return {}
    found = {}
    for region, when in pairs:
        code, cleaned = _region_code(region), _clean_date(when)
        if code and cleaned and code not in found:
            found[code] = cleaned
    return {code: found[code] for code in REGIONS if code in found}


def release_dates_json(value):
    """parse_release_dates() as the text stored in `games.release_dates`,
    or None when there is nothing to store."""
    dates = parse_release_dates(value)
    return json.dumps(dates, separators=(',', ':')) if dates else None


def _format_date(text, locale):
    from babel.dates import format_date, format_skeleton
    parsed = datetime.strptime(text, _DATE_FORMATS[len(text)]).date()
    if len(text) == 10:
        return format_date(parsed, 'medium', locale=locale)
    if len(text) == 7:
        return format_skeleton('yMMM', parsed, locale=locale)
    return text


def display_release_dates(value, locale):
    """The stored dates for a page, earliest first: a list of
    {'code', 'region', 'date', 'iso'} with the region and date written for
    `locale`."""
    from services.i18n import region_display_name
    dates = parse_release_dates(value)
    order = list(REGIONS)
    rows = []
    for code, iso in sorted(dates.items(), key=lambda kv: (kv[1], order.index(kv[0]))):
        try:
            shown = _format_date(iso, str(locale or 'en'))
        except Exception:
            shown = iso
        rows.append({'code': code, 'region': region_display_name(REGIONS[code], locale),
                     'date': shown, 'iso': iso})
    return rows
