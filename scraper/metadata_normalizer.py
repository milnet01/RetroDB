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

def alt_title_entry(title, region=None, source=None):
    """Build a normalized alt-title dict, or None if title is empty/whitespace."""
    if not title:
        return None
    t = str(title).strip()
    if not t:
        return None
    entry = {'title': t}
    if region:
        r = str(region).strip()
        if r:
            entry['region'] = r
    if source:
        entry['source'] = source
    return entry


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

    seen = {e['title'].lower() for e in merged}
    if primary_title:
        seen.add(str(primary_title).strip().lower())

    for entry in new_entries or []:
        if not entry or not entry.get('title'):
            continue
        key = entry['title'].lower()
        if key in seen:
            continue
        merged.append(entry)
        seen.add(key)

    return merged
