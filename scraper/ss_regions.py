# =============================================================================
# SCREENSCRAPER REGIONS
# =============================================================================
# The one order for choosing among ScreenScraper's per-region entries (names,
# dates, media): the game's own region, then the user's preferred regions
# (services.version_groups.preferred_regions), then any country in a language
# someone who scrapes reads, then ScreenScraper's generic `ss` entry, then the
# rest as listed (PASS-59-202).
#
# Boxes and titles are shared by the whole household, so where the order has
# a choice of countries it takes those in a language someone who scrapes can
# read (`readable_regions`): a Europe copy with no general Europe box gets the
# World box, not the German one, in an English-reading household.
# =============================================================================

import os
import re
import sqlite3

# ScreenScraper's European codes: the general one, then each country.
_EUROPE = ('eu', 'uk', 'fr', 'de', 'sp', 'it', 'nl', 'pt', 'se', 'dk', 'no',
           'fi', 'gr', 'hu', 'cz', 'sk', 'pl', 'bg')

# A region name RetroDB stores or reads from a file name -> ScreenScraper's
# codes for it, nearest first.
_REGION_CODES = {
    'usa': ('us',), 'ntsc': ('us',), 'north america': ('us',),
    'europe': _EUROPE, 'pal': _EUROPE,
    'japan': ('jp',),
    'world': ('wor',),
    'france': ('fr', 'eu'), 'germany': ('de', 'eu'), 'spain': ('sp', 'eu'),
    'italy': ('it', 'eu'), 'uk': ('uk', 'eu'), 'united kingdom': ('uk', 'eu'),
    'australia': ('au', 'eu'),
    'brazil': ('br',), 'korea': ('kr',), 'china': ('cn',), 'asia': ('asi',),
}


# Regions made of several countries. Ranked as the region, only the general
# code and the countries in a readable language count.
_SEVERAL_COUNTRIES = ('europe', 'pal')

# A language a person may say they read -> ScreenScraper's country codes whose
# boxes and titles are in it (its regionsListe.php).
LANGUAGE_REGIONS = {
    'en': ('us', 'uk', 'au', 'nz', 'ca', 'za'),
    'fr': ('fr', 'ca'), 'de': ('de',), 'es': ('sp', 'mex', 'cl', 'pe'),
    'it': ('it',), 'pt': ('pt', 'br'), 'nl': ('nl',), 'sv': ('se',),
    'da': ('dk',), 'nb': ('no',), 'fi': ('fi',), 'el': ('gr',), 'hu': ('hu',),
    'cs': ('cz',), 'sk': ('sk',), 'pl': ('pl',), 'bg': ('bg',), 'ru': ('ru',),
    'tr': ('tr',), 'he': ('il',), 'ar': ('sa', 'ae', 'kw'), 'ja': ('jp',),
    'ko': ('kr',), 'zh': ('cn', 'tw'),
}


def region_codes(region, readable=None):
    """ScreenScraper codes for a region value, which may be a combined one
    such as `USA/Europe` or `USA, Europe`.

    With `readable`, a region of several countries keeps its general code
    and only the countries in that list.
    """
    codes = []
    for part in re.split(r'[/,]', region or ''):
        part = part.strip().lower()
        # ScreenScraper's own two-letter codes pass through (a file's `romregions`).
        found = _REGION_CODES.get(part, (part,) if len(part) == 2 else ())
        if readable is not None and part in _SEVERAL_COUNTRIES:
            found = found[:1] + tuple(c for c in found[1:] if c in readable)
        codes.extend(found)
    return codes


def reading_languages():
    """The languages someone who may scrape reads, from their profiles.

    A person who ticked none reads their screen language. With nobody to ask,
    such as a database without users, English.
    """
    from services.auth import ROLE_PERMISSIONS
    from services.database import query
    roles = [r for r, perms in ROLE_PERMISSIONS.items() if 'scrape' in perms]
    try:
        rows = query(
            "SELECT s.read_languages, s.locale_preference FROM users u "
            "JOIN user_settings s ON s.user_id = u.id "
            f"WHERE u.role IN ({','.join('?' * len(roles))})", roles)
    except sqlite3.Error:                  # no user tables yet
        rows = []
    languages = []
    for row in rows:
        ticked = [c for c in (row['read_languages'] or '').split(',') if c]
        screen = re.split(r'[_-]', row['locale_preference'] or 'en')[0]
        languages.extend(ticked or [screen])
    languages = [c for c in dict.fromkeys(languages) if c in LANGUAGE_REGIONS]
    return languages or ['en']


def readable_regions():
    """ScreenScraper country codes in a language someone who scrapes reads."""
    return [code for lang in reading_languages() for code in LANGUAGE_REGIONS[lang]]


def rank_order(own=None, readable=None):
    """ScreenScraper region code -> its rank for a copy from region `own`,
    nearest first. `readable` defaults to `readable_regions()`."""
    from services.version_groups import preferred_regions
    readable = readable_regions() if readable is None else readable
    order = region_codes(own, readable)
    for name in preferred_regions():
        order.extend(region_codes(name, readable))
    order.extend(readable)
    order.append('ss')
    rank = {}
    for code in order:
        rank.setdefault(code, len(rank))
    return rank


def by_region(items, own=None):
    """The dict items of a ScreenScraper list, nearest the game's region first.

    The order: this copy's region, the preferred regions, any country in a
    readable language, then the generic `ss` entry. A region of several
    countries counts only its readable ones (`region_codes`). Items no rule
    ranks keep their listed order, after those that are ranked.
    """
    rank = rank_order(own)
    dicts = [i for i in items or [] if isinstance(i, dict)]
    return sorted(dicts, key=lambda i: rank.get((i.get('region') or '').lower(), len(rank)))


def own_region(game, ss_record=None):
    """The region of this copy: its file name's tag, else what ScreenScraper
    says of this exact file, else the stored value.

    The file name comes first because the stored value can be the AI's guess
    (PASS-59-162, merge_and_stored finding 1).
    """
    from scraper.scrape_esde import extract_region_from_filename
    name = os.path.basename(game.get('rom_path') or '')
    file_regions = ''
    if ss_record and ss_record.get('_matched_file'):
        file_regions = ((ss_record.get('rom') or {}).get('romregions') or '').split(',')[0].strip()
    return extract_region_from_filename(name) or file_regions or game.get('region') or None
