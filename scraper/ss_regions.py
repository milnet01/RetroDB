# =============================================================================
# SCREENSCRAPER REGIONS
# =============================================================================
# The one order for choosing among ScreenScraper's per-region entries (names,
# dates, media): the game's own region, then the user's preferred regions
# (services.version_groups.preferred_regions), then ScreenScraper's generic
# `ss` entry, then the rest as listed (PASS-59-202).
# =============================================================================

import os
import re

# A region name RetroDB stores or reads from a file name -> ScreenScraper's
# codes for it, nearest first.
_REGION_CODES = {
    'usa': ('us',), 'ntsc': ('us',), 'north america': ('us',),
    'europe': ('eu', 'uk', 'fr', 'de', 'sp', 'it'),
    'pal': ('eu', 'uk', 'fr', 'de', 'sp', 'it'),
    'japan': ('jp',),
    'world': ('wor',),
    'france': ('fr', 'eu'), 'germany': ('de', 'eu'), 'spain': ('sp', 'eu'),
    'italy': ('it', 'eu'), 'uk': ('uk', 'eu'), 'united kingdom': ('uk', 'eu'),
    'australia': ('au', 'eu'),
    'brazil': ('br',), 'korea': ('kr',), 'china': ('cn',), 'asia': ('asi',),
}


def region_codes(region):
    """ScreenScraper codes for a region value, which may be a combined one
    such as `USA/Europe` or `USA, Europe`."""
    codes = []
    for part in re.split(r'[/,]', region or ''):
        codes.extend(_REGION_CODES.get(part.strip().lower(), ()))
    return codes


def by_region(items, own=None):
    """The dict items of a ScreenScraper list, nearest the game's region first.

    Items no rule ranks keep their listed order, after those that are ranked.
    """
    from services.version_groups import preferred_regions
    order = region_codes(own)
    for name in preferred_regions():
        order.extend(region_codes(name))
    order.append('ss')
    rank = {}
    for code in order:
        rank.setdefault(code, len(rank))
    dicts = [i for i in items or [] if isinstance(i, dict)]
    return sorted(dicts, key=lambda i: rank.get((i.get('region') or '').lower(), len(rank)))


def own_region(game):
    """The region of this copy: its file name's tag, else the stored value.

    The file name comes first because the stored value can be the AI's guess
    (PASS-59-162, merge_and_stored finding 1).
    """
    from scraper.scrape_esde import extract_region_from_filename
    name = os.path.basename(game.get('rom_path') or '')
    return extract_region_from_filename(name) or game.get('region') or None
