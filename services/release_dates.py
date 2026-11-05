# =============================================================================
# RETRODB - Release dates by region
# =============================================================================
# `games.release_dates` (migration 024) holds the date a game came out in each
# region, as a JSON object keyed by region code:
#     {"JP": "2002-11-17", "NA": "2002-11-18", "EU": "2003-03-21"}
# A date is YYYY-MM-DD, or YYYY-MM / YYYY when only that much is known (as
# `release_date`, PASS-59-164). IGDB and ScreenScraper fill it from their own
# per-region dates, and the AI fills what is left, in a scrape's gap-fill and in
# AI Fill. `release_date` stays the date of the row's own release, and every
# source's date reaches it through source_date() or igdb_regional_dates(), so it
# never claims a day the source does not know (PASS-59-207).
# =============================================================================

import json
import re
from datetime import date, datetime, timezone

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
    # Region names RetroDB stores or reads from a ROM's file name.
    'ntsc': 'NA', 'france': 'EU', 'germany': 'EU', 'spain': 'EU', 'italy': 'EU',
    'uk': 'EU', 'united kingdom': 'EU',
}

# ScreenScraper's region codes, the general Europe entry ahead of its countries.
_SCREENSCRAPER_REGIONS = {
    'us': 'NA', 'eu': 'EU', 'uk': 'EU', 'fr': 'EU', 'de': 'EU', 'sp': 'EU', 'it': 'EU',
    'jp': 'JP', 'au': 'AU', 'kr': 'KR', 'cn': 'CN', 'tw': 'TW', 'br': 'BR',
    'asi': 'AS', 'wor': 'WW',
}

# IGDB's release_date_regions ids (read live 2026-11-02). New Zealand (4) has no
# code here.
_IGDB_REGIONS = {1: 'EU', 2: 'NA', 3: 'AU', 5: 'JP', 6: 'CN', 7: 'AS', 8: 'WW', 9: 'KR', 10: 'BR'}

# IGDB's date_formats ids: 0 a full date, 1 a month, 2 a year, 3-6 a quarter of a
# year, 7 not known yet.
_IGDB_FULL_DATE, _IGDB_MONTH, _IGDB_TBD = 0, 1, 7

# IGDB lists the Japanese release of these under a console of its own.
_IGDB_SAME_CONSOLE = {18: {18, 99}, 99: {18, 99}, 19: {19, 58}, 58: {19, 58}}

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


def source_date(value, padded_months=False):
    """A date from a source, only as exact as the source really knows, or None.

    Sources write "some time in 1987" as 1 January 1987, so that day becomes the
    year. 1 January 1970 is an empty date, not a release. `padded_months` also
    turns the first of any month into the month, for ES-DE: 42% of its dates fall
    on the first (PASS-59-162, esde finding 6).
    """
    cleaned = _clean_date(str(value or '').strip().replace('/', '-')[:10])
    if not cleaned or cleaned == '1970-01-01':
        return None
    if cleaned.endswith('-01-01'):
        return cleaned[:4]
    if padded_months and len(cleaned) == 10 and cleaned.endswith('-01'):
        return cleaned[:7]
    return cleaned


def is_fuller_date(new, old):
    """Does `new` say more about the same date, such as 1987-06 against 1987?"""
    return len(new) > len(old) and new.startswith(old)


def _igdb_entry_date(entry):
    """One IGDB release date as exactly as IGDB states it, or None."""
    fmt, year, month = entry.get('date_format'), entry.get('y'), entry.get('m')
    if not year or fmt == _IGDB_TBD:
        return None
    if fmt == _IGDB_FULL_DATE and entry.get('date') is not None:
        day = datetime.fromtimestamp(entry['date'], tz=timezone.utc)
        return _clean_date(day.strftime('%Y-%m-%d'))
    if fmt == _IGDB_MONTH and month:
        return _clean_date(f'{year:04d}-{month:02d}')
    return _clean_date(f'{year:04d}')


def igdb_regional_dates(entries, platform_id=None):
    """{region code: date} from an IGDB game's `release_dates`, in REGIONS order.

    Only entries for this console count; with no console known, all of them do.
    A region listed twice keeps its earliest date.
    """
    consoles = _IGDB_SAME_CONSOLE.get(platform_id, {platform_id})
    found = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if platform_id is not None and entry.get('platform') not in consoles:
            continue
        code, when = _IGDB_REGIONS.get(entry.get('release_region')), _igdb_entry_date(entry)
        if code and when and (code not in found or when < found[code]):
            found[code] = when
    return {code: found[code] for code in REGIONS if code in found}


def screenscraper_regional_dates(items):
    """{region code: date} from ScreenScraper's `dates` list, in REGIONS order.

    Its generic `ss` entry belongs to no region, so it is left out.
    """
    listed = {(i.get('region') or '').lower(): i.get('text')
              for i in items or [] if isinstance(i, dict)}
    found = {}
    for ss_code, code in _SCREENSCRAPER_REGIONS.items():
        when = source_date(listed.get(ss_code))
        if when and code not in found:
            found[code] = when
    return {code: found[code] for code in REGIONS if code in found}


def _own_codes(region):
    """Region codes for a stored or file-name region, which may be combined."""
    codes = (_region_code(part) for part in re.split(r'[/,]', region or ''))
    return [code for code in codes if code]


def pick_release_date(dates, own_region):
    """(date, is it this copy's own) from {region code: date}.

    This copy's region, then a worldwide release, which counts as its own; then
    the user's preferred regions, then the earliest date.
    """
    from services.version_groups import preferred_regions
    if not dates:
        return None, False
    for code in [*_own_codes(own_region), 'WW']:
        if code in dates:
            return dates[code], True
    for name in preferred_regions():
        for code in _own_codes(name):
            if code in dates:
                return dates[code], False
    return min(dates.values()), False


def year_gap_with_own_region(release_date, regional, own_region):
    """Is `release_date` over a year from the regional date of this copy's region?"""
    dates = parse_release_dates(regional)
    own = next((dates[code] for code in _own_codes(own_region) if code in dates), None)
    year = str(release_date or '')[:4]
    # An unreadable year ("TBA", "199?") is no gap: raising rolled back the
    # whole scrape (PASS-59-247).
    if not own or not year.isdigit() or not own[:4].isdigit():
        return False
    return abs(int(own[:4]) - int(year)) > 1


def merge_release_dates(stored, found):
    """Stored regional dates plus `found` for regions they lack, as stored text.

    None when `found` adds nothing. A stored region keeps its date: scrapers fill
    gaps (docs/decisions/0002-fill-only-scraping.md).
    """
    merged = parse_release_dates(stored)
    added = {code: when for code, when in found.items() if code not in merged}
    return release_dates_json({**merged, **added}) if added else None


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
