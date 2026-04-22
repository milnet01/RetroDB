# =============================================================================
# RETRODB - Title Normalization
# =============================================================================
# Strips noise (region tags, disc markers, edition tags, version tags) from
# titles before they're fed to the match scorer, and normalizes apostrophes,
# punctuation, and Roman numerals so cosmetic differences don't tank scores.
#
# Split from scraper/scraper_manager.py — the regex chain was the single
# largest conditional block in that file.
# =============================================================================

import re

from scraper.base_scraper import normalize_roman_numerals


# Bracketed content: [NTSC], [USA], [PAL], etc.
_BRACKETED = re.compile(r'\s*\[[^\]]*\]')

# Region tags inside parentheses: (USA), (Europe), (Japan), (World), (En,Fr,De), etc.
_REGION_CODES = (
    'USA|Europe|Japan|World|Asia|Australia|Brazil|Canada|China|France|Germany|Italy|'
    'Korea|Netherlands|Russia|Spain|Sweden|Taiwan|UK|En|Fr|De|Es|It|Ja|Ko|Nl|Pt|Ru|Sv|'
    'Zh|Da|Fi|No|Pl|Tr|Cs|Hu|Ro|El|Ar|He|Th|Vi|U|E|J|W'
)
_REGIONS = re.compile(
    rf'\s*\((?:{_REGION_CODES})(?:\s*,\s*(?:{_REGION_CODES}))*\)',
    re.IGNORECASE,
)

# Disc indicators: (Disc 1), (Disc 1 of 3), (Disk 2), (CD1)
_DISC = re.compile(
    r'\s*\((?:Disc|Disk|CD)\s*\d+(?:\s*of\s*\d+)?\)',
    re.IGNORECASE,
)

# Version/revision: (Rev 1), (Rev A), (v1.0), (Beta), (Proto), (Sample), (Demo), (Unl)
_VERSION = re.compile(
    r'\s*\((?:Rev\s*[A-Za-z0-9.]+|v\d+[.\d]*|Beta|Proto(?:type)?|Sample|Demo|Promo|Preview|Unl)\)',
    re.IGNORECASE,
)

# Edition tags: (Greatest Hits), (GOTY), (Remastered), (Collector's Edition), etc.
_EDITION = re.compile(
    r"\s*\((?:Greatest\s+Hits|Platinum|Player'?s?\s+Choice|Nintendo\s+Selects|Classics|"
    r"Budget|GOTY|Game\s+of\s+the\s+Year|Remaster(?:ed)?|Collector'?s?\s+Edition|"
    r"Special\s+Edition|Limited\s+Edition|Definitive\s+Edition|Complete\s+Edition|"
    r"Gold\s+Edition|Premium\s+Edition|Deluxe\s+Edition|Ultimate\s+Edition|"
    r"Standard\s+Edition|Digital\s+Edition|Anniversary\s+Edition|Enhanced\s+Edition|"
    r"Director'?s?\s+Cut|Black\s+Label|Not\s+for\s+Resale|NFR|Rental)\)",
    re.IGNORECASE,
)

# Ordered strip pipeline — each pattern runs once, earliest first.
_NOISE_PATTERNS = (_BRACKETED, _REGIONS, _DISC, _VERSION, _EDITION)
_WHITESPACE = re.compile(r'\s+')


def strip_title_noise(title):
    """Strip region tags, disc markers, edition tags, and version tags from a title.

    Case-insensitive where appropriate. Multiple whitespace collapsed to single
    space; leading/trailing whitespace stripped.
    """
    if not title:
        return title
    for pattern in _NOISE_PATTERNS:
        title = pattern.sub('', title)
    return _WHITESPACE.sub(' ', title).strip()


# Apostrophe-like characters — all variants we want to flatten before matching.
# U+0027 = ' (ASCII), U+2019 = ' (right curly), U+2018 = ' (left curly),
# U+02BC = ʼ (modifier), U+02BB = ʻ (turned comma), U+0060 = ` (grave),
# U+00B4 = ´ (acute), U+2032 = ′ (prime), U+02B9 = ʹ (modifier prime).
_APOSTROPHES = "'’‘ʼʻ`´′ʹ"
_POSSESSIVE = re.compile(rf"[{_APOSTROPHES}]s\b")
_ANY_APOSTROPHE = re.compile(rf"[{_APOSTROPHES}]")
_PUNCT_TO_SPACE = re.compile(r'[:\-–—/]')


def normalize_for_matching(title):
    """Normalize a title for case-insensitive word-set comparison.

    - Lowercases.
    - Strips possessive 's (e.g. "Assassin's" -> "Assassin").
    - Drops all apostrophe variants.
    - Replaces colons, dashes, and slashes with spaces.
    - Collapses whitespace.
    - Converts Roman numerals (II → 2, VII → 7) so "Rick Dangerous II" matches
      "Rick Dangerous 2".
    """
    if not title:
        return ''
    lower = title.lower()
    lower = _POSSESSIVE.sub('', lower)
    lower = _ANY_APOSTROPHE.sub('', lower)
    lower = _PUNCT_TO_SPACE.sub(' ', lower)
    lower = _WHITESPACE.sub(' ', lower).strip()
    return normalize_roman_numerals(lower)
