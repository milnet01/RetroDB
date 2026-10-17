# =============================================================================
# METADATA NORMALIZER
# =============================================================================
# Field-level helpers used across every per-source `apply_*_to_metadata()`
# in `scraper/metadata_merger.py`:
#
#   - normalize_title()        — subtitle dash → colon, punctuation spacing,
#                                article placement (per settings)
#   - normalize_esrb_rating()  — legacy ESRB values (KA, E10, …) → modern
#                                canonical values (E, E10+, …)
#   - alt_title_entry()        — build a {title, region?, source?} dict
#   - merge_alt_titles()       — merge new alt-title entries into the
#                                existing list, case-insensitive dedup
#
# Genre / modes / rating-image normalization lives in services/ because it
# ships cross-cut DB-custom rules; this module is intentionally scraper-local.
# =============================================================================

import json
import re


def normalize_title(title):
    """Normalize title formatting.

    - Convert leading " - " subtitle pattern to ": " when it looks like a
      franchise subtitle ("Call of Duty - World at War" → "Call of Duty: World at War").
    - Collapse spacing around existing colons and commas.
    - Apply the user's article-placement preference (beginning or end).
    """
    if not title:
        return title

    # If title already has a colon, just fix spacing issues
    if ':' not in title:
        # Convert first " - " to ": " for subtitle pattern
        # (word - word, not abbreviations)
        match = re.match(
            r'^([A-Za-z0-9][A-Za-z0-9\s\'\&\!\.]+?)\s+-\s+([A-Z][a-zA-Z0-9\s\-\'\&\!\.]+)$',
            title,
        )
        if match:
            base_name = match.group(1).strip()
            subtitle = match.group(2).strip()
            if len(base_name) >= 3 and len(subtitle) >= 3:
                title = f"{base_name}: {subtitle}"

    # " : " → ": "; " :" → ":"; " ," → ","
    title = title.replace(' : ', ': ')
    title = title.replace(' :', ':')
    title = title.replace(' ,', ',')
    # Ensure space after colon/comma if followed by a letter
    title = re.sub(r':([A-Za-z])', r': \1', title)
    title = re.sub(r',([A-Za-z])', r', \1', title)
    # Apply article placement setting (beginning or end)
    from services.game_utils import apply_article_placement
    title = apply_article_placement(title)
    return title.strip()


# ESRB rating normalization map.
# KA (Kids to Adults) was replaced by E (Everyone) in 1998; older scraper
# data carries KA / K-A and human-readable forms that need collapsing.
_ESRB_NORMALIZATION = {
    'KA': 'E',
    'K-A': 'E',
    'KIDS TO ADULTS': 'E',
    'E10': 'E10+',
    'EVERYONE 10+': 'E10+',
    'EVERYONE 10': 'E10+',
    'EVERYONE': 'E',
    'TEEN': 'T',
    'MATURE': 'M',
    'MATURE 17+': 'M',
    'ADULTS ONLY': 'AO',
    'ADULTS ONLY 18+': 'AO',
    'RATING PENDING': 'RP',
    'EARLY CHILDHOOD': 'EC',
}


def normalize_esrb_rating(rating):
    """Normalize ESRB rating values for consistency.

    Handles legacy ratings like KA (Kids to Adults) → E (Everyone), and
    collapses human-readable forms (e.g. "Teen") to canonical codes (T).
    Unknown values are returned unchanged so we don't silently drop data.
    """
    if not rating:
        return rating
    rating_upper = rating.upper().strip()
    return _ESRB_NORMALIZATION.get(rating_upper, rating)


# =============================================================================
# ALTERNATE TITLES
# =============================================================================
# Regional / alternate names for games (e.g. Japanese vs USA vs PAL titles).
# Stored as JSON list of {title, region?, source?} dicts on
# games.alternate_titles.
#
# Dedupe is case-insensitive on title. Entries whose title matches the game's
# primary title are dropped — no point storing the same string twice.
#
# PASS-59-105: `region` is stored as a CLDR territory code ("JP", "US", "150"
# Europe, "001" World) so the game page can name it in the user's language via
# Babel. Sources send raw tags: ScreenScraper short codes ("jp", "eu", "wor")
# and IGDB free-text comments ("Japanese title - romanization"). An IGDB
# comment is kept as `note`. ScreenScraper's "ss" (its own house name for the
# game) and "cus" (custom) are not regions.

# ScreenScraper region codes that are not the CLDR code upper-cased.
_SS_REGION_CODES = {
    'eu': '150', 'wor': '001', 'asi': '142', 'ame': '019', 'oce': '009',
    'afr': '002', 'mor': '145', 'uk': 'GB', 'sp': 'ES',
    'ss': None, 'cus': None,
}

# First word(s) of an IGDB alternative-name comment → CLDR code.
_IGDB_REGION_WORDS = {
    'japanese': 'JP', 'japan': 'JP',
    'us': 'US', 'usa': 'US', 'american': 'US', 'north american': 'US',
    'european': '150', 'europe': '150', 'eu': '150', 'pal': '150',
    'uk': 'GB', 'british': 'GB',
    'german': 'DE', 'french': 'FR', 'spanish': 'ES', 'italian': 'IT',
    'russian': 'RU', 'chinese': 'CN', 'taiwanese': 'TW', 'korean': 'KR',
    'brazilian': 'BR', 'portuguese': 'PT', 'swedish': 'SE', 'hebrew': 'IL',
    'australia': 'AU', 'australian': 'AU', 'polish': 'PL', 'dutch': 'NL',
    'turkish': 'TR', 'greek': 'GR', 'czech': 'CZ', 'hungarian': 'HU',
    'finnish': 'FI', 'danish': 'DK', 'norwegian': 'NO', 'canadian': 'CA',
    'mexican': 'MX', 'latin american': '419', 'asian': '142',
    'world': '001', 'worldwide': '001', 'international': '001',
}

_CLDR_REGION_RE = re.compile(r'^(?:[A-Z]{2}|\d{3})$')
_SS_CODE_RE = re.compile(r'^[a-z]{2,3}$')


def alt_title_region(raw):
    """Split a raw alt-title region tag into `(cldr_code, note)`.

    Either part may be None. A CLDR code passes through unchanged, so the
    function is safe to run again on stored data.
    """
    if not raw:
        return None, None
    r = str(raw).strip()
    if not r:
        return None, None
    if _CLDR_REGION_RE.match(r):
        return r, None
    if _SS_CODE_RE.match(r):
        if r in _SS_REGION_CODES:
            return _SS_REGION_CODES[r], None
        return (r.upper() if len(r) == 2 else None), None
    words = re.findall(r'[a-z]+', r.lower())
    for n in (2, 1):
        code = _IGDB_REGION_WORDS.get(' '.join(words[:n]))
        if code:
            return code, r
    return None, r


def alt_title_entry(title, region=None, source=None, note=None):
    """Build a normalized alt-title dict, or None if title is empty/whitespace.

    `region` may be a raw source tag; see alt_title_region().
    """
    if not title:
        return None
    t = str(title).strip()
    if not t:
        return None
    entry = {'title': t}
    code, raw_note = alt_title_region(region)
    if code:
        entry['region'] = code
    note = (str(note).strip() if note else '') or raw_note
    if note:
        entry['note'] = note
    if source:
        entry['source'] = source
    return entry


def _as_alt_entry(e):
    """Re-normalize a stored or source alt-title dict (idempotent)."""
    return alt_title_entry(e.get('title'), region=e.get('region'),
                           source=e.get('source'), note=e.get('note'))


def merge_alt_titles(existing, new_entries, primary_title=None):
    """Merge `new_entries` into `existing`, deduping case-insensitively on title.

    `existing` may be a list, a JSON string, or None. Returns a plain list
    (caller json.dumps on save). Entries matching `primary_title` are dropped.
    """
    if existing is None:
        merged = []
    elif isinstance(existing, list):
        merged = [e for e in existing if isinstance(e, dict) and e.get('title')]
    elif isinstance(existing, str):
        try:
            parsed = json.loads(existing)
            merged = (
                [e for e in parsed if isinstance(e, dict) and e.get('title')]
                if isinstance(parsed, list)
                else []
            )
        except (ValueError, TypeError):
            merged = []
    else:
        merged = []
    merged = [_as_alt_entry(e) for e in merged]

    by_title = {e['title'].lower(): e for e in merged}
    primary = str(primary_title).strip().lower() if primary_title else None

    for entry in new_entries or []:
        if not entry or not entry.get('title'):
            continue
        entry = _as_alt_entry(entry)
        key = entry['title'].lower()
        if key == primary:
            continue
        if key in by_title:
            # A name stored before regions were kept gains its region here.
            held = by_title[key]
            for field in ('region', 'note'):
                if entry.get(field) and not held.get(field):
                    held[field] = entry[field]
            continue
        merged.append(entry)
        by_title[key] = entry

    return merged
