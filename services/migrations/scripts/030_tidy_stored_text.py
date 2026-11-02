# =============================================================================
# Migration 030 — tidy text older scrapes stored as it came
# =============================================================================
# PASS-59-213. The scrape's save step now cleans these, so only older rows need
# it: web codes and marks in descriptions, one company under several spellings,
# executable names listed as alternate titles, "NOT RATED" as an ESRB rating, a
# region of two values, and platform names outside the list.
# =============================================================================

import json

from services.migrations._helpers import _has_column, _table_exists

_REGIONS = {'north america': 'USA'}


def _alternate_titles(value):
    try:
        titles = json.loads(value)
    except (ValueError, TypeError):
        return value
    if not isinstance(titles, list):
        return value
    kept = [t for t in titles if not (
        isinstance(t, dict) and (t.get('note') == 'Windows Executable'
                                 or str(t.get('title') or '').lower().endswith('.exe')))]
    return value if len(kept) == len(titles) else json.dumps(kept)


def _region(value):
    return _REGIONS.get(value.lower()) or value.split('/')[0].strip()


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    # Imported here: a fresh install's first migrations run before these load.
    from scraper.scrape_ai import FIELD_SCHEMAS, PLATFORM_ALIASES
    from services.normalization import canonical_companies, clean_description

    schema = {name.lower(): name for name in FIELD_SCHEMAS['other_platforms']}

    def platforms(value):
        names = (name.strip() for name in value.split(','))
        return ', '.join(dict.fromkeys(
            schema.get(name.lower()) or PLATFORM_ALIASES.get(name.lower()) or name
            for name in names if name))

    tidiers = {
        'description': lambda value: clean_description(value) or None,
        'publisher': canonical_companies,
        'developer': canonical_companies,
        'alternate_titles': _alternate_titles,
        'screenshots': lambda value: value.replace(', ', ','),
        'esrb_rating': lambda value: None if value.upper() == 'NOT RATED' else value,
        'region': _region,
        'other_platforms': platforms,
    }
    for field, tidy in tidiers.items():
        if not _has_column(cursor, 'games', field):
            continue
        rows = cursor.execute(f"SELECT id, {field} FROM games "
                              f"WHERE {field} IS NOT NULL AND {field} != ''").fetchall()
        for game_id, value in rows:
            tidied = tidy(value)
            if tidied != value:
                cursor.execute(f"UPDATE games SET {field} = ? WHERE id = ?", (tidied, game_id))
