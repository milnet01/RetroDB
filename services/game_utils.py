# =============================================================================
# RETRODB - Game Utilities Service
# =============================================================================
# Provides utility functions for game title parsing, sorting, platform 
# normalization, bonus disc detection, and rating mappings.
# =============================================================================

import os
import re


# =============================================================================
# CONSTANTS
# =============================================================================

# Computer systems use Year + Publisher naming in ROM filenames
# This is a comprehensive list of all computer system folder names
COMPUTER_SYSTEMS = frozenset({
    # Commodore
    'c64', 'c128', 'vic20', 'amiga', 'amiga500', 'amiga600', 'amiga1200', 
    'amigacd32', 'plus4', 'pet',
    # Sinclair/ZX
    'zxspectrum', 'spectrum', 'zx81',
    # Amstrad
    'amstradcpc', 'cpc',
    # MSX
    'msx', 'msx1', 'msx2', 'msxturbor',
    # Atari computers
    'atarist', 'atari800', 'atarixe', 'atari520st', 'atari1040st',
    # Apple
    'apple2', 'apple2gs', 'macintosh',
    # Acorn/BBC
    'bbcmicro', 'bbc', 'electron', 'archimedes', 'atom',
    # DOS/PC
    'dos', 'pc', 'windows',
    # Tandy/TRS
    'coco', 'trs-80', 'dragon32',
    # Texas Instruments
    'ti99',
    # Sharp/NEC Japan
    'x1', 'x68000', 'pc88', 'pc98', 'fm7', 'fmtowns', 'sharp',
    # Thomson
    'moto', 'to8', 'mo5',
    # Other European
    'oric', 'sam', 'samcoupe', 'spectravideo'
})

# Handheld systems use Region naming by default (same as consoles)
HANDHELD_SYSTEMS = frozenset({
    # Nintendo
    'gb', 'gbc', 'gba', 'virtualboy', 'nds', 'n3ds',
    # Sony
    'psp', 'psvita',
    # Sega
    'gamegear', 'gg',
    # Atari
    'atarilynx', 'lynx',
    # SNK
    'ngp', 'ngpc', 'neogeopocket', 'neogeopocketcolor',
    # Bandai
    'wonderswan', 'wonderswancolor', 'swancrystal',
    # Nokia
    'ngage',
    # Tiger
    'gamecom',
    # Watara
    'supervision',
})


# Engine systems — game engines, frameworks, and fantasy consoles
ENGINE_SYSTEMS = frozenset({
    'ags', 'chailove', 'doom', 'easyrpg', 'flash', 'lowresnx', 'lutro',
    'mugen', 'openbor', 'pico8', 'tic80', 'wasm4',
    'ports', 'quake', 'scummvm', 'solarus', 'vircon32',
})


def get_system_type(system_folder):
    """Return 'computer', 'handheld', 'engine', or 'console' for a system folder name."""
    folder = system_folder.lower().strip()
    if folder in COMPUTER_SYSTEMS:
        return 'computer'
    if folder in HANDHELD_SYSTEMS:
        return 'handheld'
    if folder in ENGINE_SYSTEMS:
        return 'engine'
    return 'console'


# Tags that are NOT publisher names (used by extract_filename_hints)
_KNOWN_NON_PUBLISHER_TAGS = re.compile(
    r'^('
    # Regions
    r'USA|Europe|Japan|World|Germany|France|Spain|Italy|Australia|Brazil'
    r'|Korea|China|Taiwan|Asia'
    r'|U|E|J|W|En|Fr|De|Es|It|Ja'
    r'|En,\s*Fr|En,\s*De|En,\s*Es|En,\s*Fr,\s*De|En,\s*Fr,\s*De,\s*Es,\s*It'
    # Versions/revisions
    r'|Rev\s*\d*[A-Z]?|v\d+\.?\d*|Version\s*\d+\.?\d*'
    r'|Beta|Proto|Demo|Sample|Unl|Hack|PD|Pirate'
    # Editions
    r'|Greatest Hits|Player\'s Choice|Platinum'
    r'|Collector\'s Edition|Limited Edition|Special Edition'
    r'|Game of the Year|GOTY|Remastered'
    # Disc indicators
    r'|Disc\s*\d+(?:\s*of\s*\d+)?'
    r')$',
    re.IGNORECASE
)


def extract_filename_hints(rom_path):
    """Extract year and publisher hints from parenthetical tags in a ROM filename.

    For computer systems: 'Cabal (1989) (Ocean).adf' -> {'year': '1989', 'publisher': 'Ocean'}
    For consoles: 'Cabal (USA).iso' -> {'year': None, 'publisher': None}
    """
    filename = os.path.basename(rom_path)
    name = os.path.splitext(filename)[0]

    # Extract all parenthetical groups
    tags = re.findall(r'\(([^)]+)\)', name)

    year = None
    publisher = None

    remaining = []
    for tag in tags:
        tag_stripped = tag.strip()
        # Check for year (1970-2030)
        if re.fullmatch(r'\d{4}', tag_stripped):
            val = int(tag_stripped)
            if 1970 <= val <= 2030:
                year = tag_stripped
                continue
        # Skip known non-publisher tags
        if _KNOWN_NON_PUBLISHER_TAGS.match(tag_stripped):
            continue
        remaining.append(tag_stripped)

    # The first remaining tag is likely the publisher
    if remaining:
        publisher = remaining[0]

    return {'year': year, 'publisher': publisher}


# =============================================================================
# ARTICLE PLACEMENT FUNCTIONS
# =============================================================================

# Matches articles at the start of a title (e.g., "The Legend of Zelda")
# Negative lookahead (?![.\-]) prevents matching abbreviations like "A.L.F." or "A-Team"
_ARTICLE_AT_START_RE = re.compile(r'^(The|An|A)\s+(?![.\-])', re.IGNORECASE)

# Matches articles at the end of a title (e.g., "Legend of Zelda, The")
_ARTICLE_AT_END_RE = re.compile(r'^(.+),\s*(The|An|A)$', re.IGNORECASE)


def move_article_to_end(title):
    """Move a leading article to the end of the title.

    'The Legend of Zelda' → 'Legend of Zelda, The'
    'A Bug\\'s Life' → 'Bug\\'s Life, A'
    """
    if not title:
        return title
    m = _ARTICLE_AT_START_RE.match(title)
    if m:
        article = m.group(1)
        rest = title[m.end():]
        return f"{rest}, {article}"
    return title


def move_article_to_beginning(title):
    """Move a trailing article to the beginning of the title.

    'Legend of Zelda, The' → 'The Legend of Zelda'
    'Bug\\'s Life, A' → 'A Bug\\'s Life'
    """
    if not title:
        return title
    m = _ARTICLE_AT_END_RE.match(title)
    if m:
        rest = m.group(1)
        article = m.group(2)
        return f"{article} {rest}"
    return title


def normalize_article_for_comparison(title):
    """Always move article to the beginning for comparison so both forms match."""
    if not title:
        return title
    return move_article_to_beginning(title)


def apply_article_placement(title):
    """Read article_placement setting and move the article accordingly."""
    if not title:
        return title
    import settings_manager
    placement = settings_manager.get_setting('article_placement', 'beginning')
    if placement == 'end':
        return move_article_to_end(title)
    else:
        return move_article_to_beginning(title)


def _sanitize_filename_value(value):
    """Replace filesystem-unsafe characters in a filename component."""
    if not value:
        return ''
    for char, repl in [(':', ' -'), ('?', ''), ('*', ''), ('/', '-'),
                        ('\\', '-'), ('"', "'"), ('<', ''), ('>', ''), ('|', '-')]:
        value = value.replace(char, repl)
    return value.strip()


def build_filename(title, ext, tags, game_data):
    """
    Build a ROM filename from title + ordered tags.

    Args:
        title: Clean game title (already sanitized for filesystem).
        ext: File extension including dot (e.g., '.zip').
        tags: List of tag keys in order, e.g. ['region', 'year', 'publisher'].
        game_data: Dict with keys 'region', 'release_date', 'publisher',
                   'developer', 'genre', 'system_type', 'system_name'.

    Returns:
        Filename string, e.g., "Lemmings (1991) (Psygnosis).zip"
    """
    title = apply_article_placement(title)

    # First, compute all tag values that will be appended
    tag_values = []
    for tag in tags:
        value = ''
        if tag == 'region':
            value = game_data.get('region') or ''
        elif tag == 'year':
            rd = game_data.get('release_date') or ''
            m = re.search(r'(19|20)\d{2}', rd)
            value = m.group(0) if m else ''
        elif tag == 'publisher':
            value = game_data.get('publisher') or ''
        elif tag == 'developer':
            value = game_data.get('developer') or ''
        elif tag == 'genre':
            # Use first genre only for filename
            g = game_data.get('genre') or ''
            value = g.split(',')[0].strip() if g else ''
        elif tag == 'system_type':
            value = (game_data.get('system_type') or '').capitalize()
        elif tag == 'system_name':
            value = game_data.get('system_name') or ''
        tag_values.append(_sanitize_filename_value(value))

    # Strip parenthetical tags from title that duplicate convention tag values.
    # e.g., title "Armageddon (Ocean)" with publisher="Ocean" in tags
    # → strip "(Ocean)" from title since it will be added as a convention tag.
    tag_value_set = {v.lower() for v in tag_values if v}
    if tag_value_set:
        def _replace_if_dup(m):
            content = m.group(1).strip().lower()
            return '' if content in tag_value_set else m.group(0)
        title = re.sub(r'\s*\(([^)]+)\)', _replace_if_dup, title).strip()

    parts = [title]
    for value in tag_values:
        if value:
            parts.append(f'({value})')
    return ' '.join(parts) + ext


# Roman numeral to Arabic mapping for title sorting
ROMAN_NUMERAL_MAP = {
    'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5',
    'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10',
    'XI': '11', 'XII': '12', 'XIII': '13', 'XIV': '14', 'XV': '15',
    'XVI': '16', 'XVII': '17', 'XVIII': '18', 'XIX': '19', 'XX': '20'
}

# ESRB to PEGI rating mapping (legacy — prefer RATING_CROSS_MAP for new code)
ESRB_TO_PEGI_MAP = {
    'E': 'PEGI 3',      # Everyone -> PEGI 3
    'EC': 'PEGI 3',     # Early Childhood -> PEGI 3
    'E10+': 'PEGI 7',   # Everyone 10+ -> PEGI 7
    'E10': 'PEGI 7',    # Everyone 10+ (alternate format)
    'T': 'PEGI 12',     # Teen -> PEGI 12
    'M': 'PEGI 16',     # Mature -> PEGI 16
    'AO': 'PEGI 18',    # Adults Only -> PEGI 18
    'RP': None,          # Rating Pending - no mapping
}

# =============================================================================
# MULTI-RATING SYSTEM SUPPORT
# =============================================================================

# All supported rating systems with metadata
RATING_SYSTEMS = {
    'esrb':     {'name': 'ESRB',      'full_name': 'Entertainment Software Rating Board',   'region': 'North America', 'db_column': 'esrb_rating'},
    'pegi':     {'name': 'PEGI',      'full_name': 'Pan European Game Information',          'region': 'Europe',        'db_column': 'pegi_rating'},
    'cero':     {'name': 'CERO',      'full_name': 'Computer Entertainment Rating Org.',     'region': 'Japan',         'db_column': 'cero_rating'},
    'usk':      {'name': 'USK',       'full_name': 'Unterhaltungssoftware Selbstkontrolle',  'region': 'Germany',       'db_column': 'usk_rating'},
    'acb':      {'name': 'ACB',       'full_name': 'Australian Classification Board',        'region': 'Australia',     'db_column': 'acb_rating'},
    'fpb':      {'name': 'FPB',       'full_name': 'Film and Publication Board',             'region': 'South Africa',  'db_column': 'fpb_rating'},
    'grac':     {'name': 'GRAC',      'full_name': 'Game Rating and Administration Comm.',   'region': 'South Korea',   'db_column': 'grac_rating'},
    'classind': {'name': 'CLASS_IND', 'full_name': 'Classificação Indicativa',               'region': 'Brazil',        'db_column': 'classind_rating'},
    'china':    {'name': 'CADPA',     'full_name': 'China Game Rating (CADPA age reminder)',  'region': 'China',         'db_column': 'china_rating'},
}

# Valid values per rating system (order = least to most restrictive)
RATING_VALUES = {
    'esrb':     ['EC', 'E', 'E10+', 'T', 'M', 'AO', 'RP'],
    'pegi':     ['PEGI 3', 'PEGI 7', 'PEGI 12', 'PEGI 16', 'PEGI 18'],
    'cero':     ['A', 'B', 'C', 'D', 'Z'],
    'usk':      ['0', '6', '12', '16', '18'],
    'acb':      ['G', 'PG', 'M', 'MA15+', 'R18+'],
    'fpb':      ['A', 'PG', '7-9 PG', '10', '10-12 PG', '13', '16', '18'],
    'grac':     ['ALL', '12', '15', '18'],
    'classind': ['L', '10', '12', '14', '16', '18'],
    # China's CADPA scheme has no "all ages" or "adults only" badge — the
    # floor is 8+ and the ceiling is 16+ (three tiers only).
    'china':    ['8+', '12+', '16+'],
}

# Maturity tier mapping: (system, value) -> tier (0-6)
# Tier 0=All Ages, 1=Young Children, 2=Mild, 3=Teen, 4=Mature, 5=Strong Mature, 6=Adults Only
_RATING_TO_TIER = {
    # ESRB
    ('esrb', 'EC'):   0, ('esrb', 'E'):    1, ('esrb', 'E10+'): 2, ('esrb', 'E10'): 2,
    ('esrb', 'T'):    3, ('esrb', 'M'):    4, ('esrb', 'AO'):   6,
    # PEGI
    ('pegi', 'PEGI 3'):  1, ('pegi', 'PEGI 7'):  2, ('pegi', 'PEGI 12'): 3,
    ('pegi', 'PEGI 16'): 4, ('pegi', 'PEGI 18'): 6,
    # CERO
    ('cero', 'A'): 1, ('cero', 'B'): 3, ('cero', 'C'): 4, ('cero', 'D'): 5, ('cero', 'Z'): 6,
    # USK
    ('usk', '0'): 1, ('usk', '6'): 2, ('usk', '12'): 3, ('usk', '16'): 4, ('usk', '18'): 6,
    # ACB
    ('acb', 'G'): 1, ('acb', 'PG'): 2, ('acb', 'M'): 3, ('acb', 'MA15+'): 4, ('acb', 'R18+'): 6,
    # FPB
    ('fpb', 'A'): 1, ('fpb', 'PG'): 2, ('fpb', '7-9 PG'): 2, ('fpb', '10'): 3,
    ('fpb', '10-12 PG'): 3, ('fpb', '13'): 3, ('fpb', '16'): 4, ('fpb', '18'): 6,
    # GRAC
    ('grac', 'ALL'): 1, ('grac', '12'): 3, ('grac', '15'): 4, ('grac', '18'): 6,
    # CLASS_IND
    ('classind', 'L'): 1, ('classind', '10'): 2, ('classind', '12'): 3,
    ('classind', '14'): 4, ('classind', '16'): 5, ('classind', '18'): 6,
    # China (CADPA): 8+ ~ E10+/USK-6 (tier 2), 12+ ~ Teen (tier 3), 16+ ~ Mature (tier 4).
    ('china', '8+'): 2, ('china', '12+'): 3, ('china', '16+'): 4,
}

# Tier -> best rating value per system (for cross-mapping)
_TIER_TO_RATING = {
    ('esrb', 0): 'EC',   ('esrb', 1): 'E',      ('esrb', 2): 'E10+',   ('esrb', 3): 'T',
    ('esrb', 4): 'M',    ('esrb', 5): 'M',      ('esrb', 6): 'AO',
    ('pegi', 0): 'PEGI 3',  ('pegi', 1): 'PEGI 3',  ('pegi', 2): 'PEGI 7',
    ('pegi', 3): 'PEGI 12', ('pegi', 4): 'PEGI 16', ('pegi', 5): 'PEGI 16', ('pegi', 6): 'PEGI 18',
    ('cero', 0): 'A',    ('cero', 1): 'A',      ('cero', 2): 'A',      ('cero', 3): 'B',
    ('cero', 4): 'C',    ('cero', 5): 'D',      ('cero', 6): 'Z',
    ('usk', 0): '0',     ('usk', 1): '0',       ('usk', 2): '6',       ('usk', 3): '12',
    ('usk', 4): '16',    ('usk', 5): '16',      ('usk', 6): '18',
    ('acb', 0): 'G',     ('acb', 1): 'G',       ('acb', 2): 'PG',      ('acb', 3): 'M',
    ('acb', 4): 'MA15+', ('acb', 5): 'MA15+',   ('acb', 6): 'R18+',
    ('fpb', 0): 'A',     ('fpb', 1): 'A',       ('fpb', 2): 'PG',      ('fpb', 3): '13',
    ('fpb', 4): '16',    ('fpb', 5): '16',      ('fpb', 6): '18',
    ('grac', 0): 'ALL',  ('grac', 1): 'ALL',    ('grac', 2): 'ALL',    ('grac', 3): '12',
    ('grac', 4): '15',   ('grac', 5): '18',     ('grac', 6): '18',
    ('classind', 0): 'L', ('classind', 1): 'L',  ('classind', 2): '10',  ('classind', 3): '12',
    ('classind', 4): '14', ('classind', 5): '16', ('classind', 6): '18',
    # China (CADPA): floor 8+ absorbs tiers 0-2; ceiling 16+ absorbs tiers 4-6.
    ('china', 0): '8+',  ('china', 1): '8+',  ('china', 2): '8+',  ('china', 3): '12+',
    ('china', 4): '16+', ('china', 5): '16+', ('china', 6): '16+',
}

# Rating image file mapping: (system, value) -> path relative to /static/images/ratings/
RATING_IMAGE_MAP = {
    # ESRB
    ('esrb', 'EC'):   'ESRB/ESRB_E.svg',
    ('esrb', 'E'):    'ESRB/ESRB_E.svg',
    ('esrb', 'E10+'): 'ESRB/ESRB_E10plus.svg',
    ('esrb', 'T'):    'ESRB/ESRB_T.svg',
    ('esrb', 'M'):    'ESRB/ESRB_M.svg',
    ('esrb', 'AO'):   'ESRB/ESRB_AO.svg',
    ('esrb', 'RP'):   'ESRB/ESRB_RP.svg',
    # PEGI
    ('pegi', 'PEGI 3'):  'PEGI/PEGI_3.png',
    ('pegi', 'PEGI 7'):  'PEGI/PEGI_7.png',
    ('pegi', 'PEGI 12'): 'PEGI/PEGI_12.png',
    ('pegi', 'PEGI 16'): 'PEGI/PEGI_16.png',
    ('pegi', 'PEGI 18'): 'PEGI/PEGI_18.png',
    # CERO
    ('cero', 'A'): 'CERO/CERO_A.png',
    ('cero', 'B'): 'CERO/CERO_B.png',
    ('cero', 'C'): 'CERO/CERO_C.png',
    ('cero', 'D'): 'CERO/CERO_D.png',
    ('cero', 'Z'): 'CERO/CERO_Z.png',
    # USK
    ('usk', '0'):  'USK/USK_0.png',
    ('usk', '6'):  'USK/USK_6.png',
    ('usk', '12'): 'USK/USK_12.png',
    ('usk', '16'): 'USK/USK_16.png',
    ('usk', '18'): 'USK/USK_18.png',
    ('usk', 'RP'): 'USK/USK_RP.png',
    # ACB
    ('acb', 'G'):     'ACB/ACB_G.png',
    ('acb', 'PG'):    'ACB/ACB_PG.png',
    ('acb', 'M'):     'ACB/ACB_M.png',
    ('acb', 'MA15+'): 'ACB/ACB_MA15+_Restrict.png',
    ('acb', 'R18+'): 'ACB/ACB_R18+_Restrict.png',
    # FPB
    ('fpb', 'A'):       'FPB/FPB_A.svg',
    ('fpb', 'PG'):      'FPB/FPB_PG.svg',
    ('fpb', '7-9 PG'):  'FPB/FPB_7-9_PG.svg',
    ('fpb', '10'):      'FPB/FPB_10.svg',
    ('fpb', '10-12 PG'):'FPB/FPB_10-12_PG.svg',
    ('fpb', '13'):      'FPB/FPB_13.svg',
    ('fpb', '16'):      'FPB/FPB_16.svg',
    ('fpb', '18'):      'FPB/FPB_18.svg',
    # GRAC
    ('grac', 'ALL'): 'GRAC/GRAC_All.png',
    ('grac', '12'):  'GRAC/GRAC_12.png',
    ('grac', '15'):  'GRAC/GRAC_15.png',
    ('grac', '18'):  'GRAC/GRAC_18.png',
    # ClassInd
    ('classind', 'L'):  'CLASSIND/CLASSIND_L.svg',
    ('classind', '10'): 'CLASSIND/CLASSIND_10.svg',
    ('classind', '12'): 'CLASSIND/CLASSIND_12.svg',
    ('classind', '14'): 'CLASSIND/CLASSIND_14.svg',
    ('classind', '16'): 'CLASSIND/CLASSIND_16.svg',
    ('classind', '18'): 'CLASSIND/CLASSIND_18.svg',
    # China (CADPA)
    ('china', '8+'):  'CHINA/CHINA_8.svg',
    ('china', '12+'): 'CHINA/CHINA_12.svg',
    ('china', '16+'): 'CHINA/CHINA_16.svg',
}

# DB column names for all rating systems (order matters for cross-map preference)
RATING_DB_COLUMNS = ['esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating', 'china_rating']
RATING_SYSTEM_KEYS = ['esrb', 'pegi', 'cero', 'usk', 'acb', 'fpb', 'grac', 'classind', 'china']


ESRB_CODES = ('E10+', 'EC', 'E', 'T', 'M', 'AO', 'RP')


def parse_esrb_code(rating):
    """Extract the ESRB code from a free-form rating string, else ''.

    TGDB sends 'T - Teen', 'M - Mature 17+', 'AO - Adults Only 18+'. A
    substring test mis-assigns four of the six real strings: 'E' is a
    substring of TEEN, MATURE and PENDING, and 'T' of ADULTS. Match whole
    tokens instead. ESRB_CODES is the complete set, so a string matching none
    of them is not an ESRB rating and must not be stored as one — it would
    seed all nine boards through cross_map_ratings (Pass 59.19).
    """
    if not rating:
        return ''
    tokens = set(re.split(r'[^A-Z0-9+]+', re.sub(r'(?i)\besrb\b', '', rating).upper()))
    for code in ESRB_CODES:
        if code in tokens:
            return code
    return ''


def map_rating(from_system, from_value, to_system):
    """Cross-map a rating from one system to another via maturity tier.

    Args:
        from_system: Source system key (e.g., 'esrb')
        from_value: Source rating value (e.g., 'T')
        to_system: Target system key (e.g., 'pegi')

    Returns:
        str or None: Equivalent rating in target system, or None if unmappable
    """
    if not from_value or not from_system or not to_system:
        return None
    if from_system == to_system:
        return from_value
    tier = _RATING_TO_TIER.get((from_system, from_value.strip()))
    if tier is None:
        return None
    return _TIER_TO_RATING.get((to_system, tier))


def get_preferred_rating(game, preferred_system):
    """Get a game's rating in the preferred system, cross-mapping if needed.

    Args:
        game: dict or sqlite3.Row with rating columns
        preferred_system: System key (e.g., 'cero')

    Returns:
        tuple: (value, image_path, is_crossmapped) or (None, None, False)
    """
    # Try direct value first
    col = RATING_SYSTEMS.get(preferred_system, {}).get('db_column', '')
    direct = game.get(col) if hasattr(game, 'get') else (game[col] if col in (game.keys() if hasattr(game, 'keys') else []) else None)
    if direct:
        img = RATING_IMAGE_MAP.get((preferred_system, direct), '')
        return (direct, img, False)

    # Cross-map from any available rating
    for sys_key in RATING_SYSTEM_KEYS:
        if sys_key == preferred_system:
            continue
        src_col = RATING_SYSTEMS[sys_key]['db_column']
        src_val = game.get(src_col) if hasattr(game, 'get') else (game[src_col] if src_col in (game.keys() if hasattr(game, 'keys') else []) else None)
        if src_val:
            mapped = map_rating(sys_key, src_val, preferred_system)
            if mapped:
                img = RATING_IMAGE_MAP.get((preferred_system, mapped), '')
                return (mapped, img, True)

    return (None, None, False)


def get_all_ratings(game):
    """Get all applicable ratings for a game (direct values only, no cross-mapping).

    Returns:
        list: List of dicts with keys: system, name, region, value, image
    """
    ratings = []
    for sys_key in RATING_SYSTEM_KEYS:
        col = RATING_SYSTEMS[sys_key]['db_column']
        val = game.get(col) if hasattr(game, 'get') else (game[col] if col in (game.keys() if hasattr(game, 'keys') else []) else None)
        if val:
            ratings.append({
                'system': sys_key,
                'name': RATING_SYSTEMS[sys_key]['name'],
                'region': RATING_SYSTEMS[sys_key]['region'],
                'value': val,
                'image': RATING_IMAGE_MAP.get((sys_key, val), ''),
            })
    return ratings


def get_rating_image(system, value):
    """Get the image path for a specific rating.

    Returns:
        str: Path relative to /static/images/ratings/, or empty string
    """
    return RATING_IMAGE_MAP.get((system, value), '')


def get_rating_image_map_js():
    """Return RATING_IMAGE_MAP in a JSON-serializable format for JavaScript.

    Returns:
        dict: Keys like "esrb:E" → image path strings
    """
    return {f"{sys}:{val}": img for (sys, val), img in RATING_IMAGE_MAP.items()}


def get_rating_system_names_js():
    """Return rating system display names with regions for JavaScript.

    Returns:
        dict: Keys like "esrb" → "ESRB (North America)"
    """
    return {k: f"{v['name']} ({v['region']})" for k, v in RATING_SYSTEMS.items()}


def get_rating_crossmap_js():
    """Return cross-mapping tables as JSON-serializable dicts for JS.

    Returns:
        tuple: (rating_to_tier, tier_to_rating) where:
            - rating_to_tier: {"esrb:E": 1, ...}
            - tier_to_rating: {"esrb:1": "E", ...}
    """
    r2t = {f"{sys}:{val}": tier for (sys, val), tier in _RATING_TO_TIER.items()}
    t2r = {f"{sys}:{tier}": val for (sys, tier), val in _TIER_TO_RATING.items()}
    return r2t, t2r


# =============================================================================
# CONTENT-BASED RATING INFERENCE
# =============================================================================
# Infers age ratings from game metadata (genre, description, game structure,
# perspective, franchise) when scrapers and AI fill cannot provide ratings.
# Uses the existing maturity tier system to generate all 8 regional ratings.

# Genre -> maturity tier mapping (conservative — errs toward higher rating)
_GENRE_TIER = {
    # Tier 0-1: Family-friendly
    'Educational':          0,
    'Puzzle':               1,
    'Board-Card':           1,
    'Trivia':               1,
    'Music-Rhythm':         1,
    'Party':                1,
    'Casual':               1,
    # Tier 1-2: Mild content
    'Platformer':           1,
    'Action-Platformer':    1,
    'Driving':              1,
    'Racing':               2,
    'Sports':               1,
    'Flight':               2,
    'Life-Simulation':      1,
    'City-Builder':         1,
    'Management':           1,
    'Simulation':           2,
    'Visual-Novel':         2,
    'Light-Gun':            2,
    # Tier 2-3: Teen content
    'Adventure':            2,
    'Action':               3,
    'Action-Adventure':     3,
    'RPG':                  2,
    'JRPG':                 2,
    'Action-RPG':           3,
    'Strategy':             2,
    'Real-Time Strategy':   2,
    'Turn-Based Strategy':  2,
    'Tower-Defence':        2,
    'Shoot-em-up':          2,
    'Vehicular-Combat':     3,
    'MMORPG':               3,
    # Tier 3-4: Mature content
    'Shooter':              3,
    'First-Person-Shooter': 3,
    'Fighting':             3,
    'Beat-em-up':           3,
    'Hack-n-Slash':         3,
    'Stealth':              3,
    'Battle-Royale':        3,
    'Hunting':              2,
    # Tier 4-5: Strong mature content
    'Survival':             3,
    'Horror':               4,
    'Survival-Horror':      4,
    'Psychological-Horror': 4,
}

# Game structure modifiers (add to base tier)
_STRUCTURE_MODIFIER = {
    'Open-World':       0,   # neutral (depends on genre)
    'Sandbox':          0,
    'Roguelike':        0,
    'Procedural':       0,
    'Metroidvania':     0,
    'Linear':           0,
    'Level-Based':      0,
    'Hub-Based':        0,
    'Match-Based':      0,
    'Immersive-Sim':    1,   # tends toward mature
    'Interactive-Drama': 1,  # often deals with mature themes
    'Labyrinth':        0,
    'Turn-Based':       0,
}

# Description keywords that push the tier up
_CONTENT_KEYWORDS_TIER = {
    # Tier 4+ triggers (strong violence/mature themes)
    4: [
        r'\bgore\b', r'\bgoriest\b', r'\bgory\b', r'\bgruesome\b',
        r'\bmassacre\b', r'\btorture\b', r'\bmutilat', r'\bdismember',
        r'\bsexual\s+content\b', r'\bnudity\b', r'\berotic\b',
        r'\bdrug\s+use\b', r'\bdrug\s+dealing\b', r'\bcocaine\b',
        r'\bheroin\b', r'\bstrip\s*club\b',
    ],
    # Tier 3 triggers (moderate violence/themes)
    3: [
        r'\bblood\b', r'\bbloody\b', r'\bbloodshed\b',
        r'\bviolent\b', r'\bviolence\b', r'\bkill\b', r'\bkilling\b',
        r'\bmurder\b', r'\bassassin', r'\bwar\b', r'\bwarfare\b',
        r'\bcombat\b', r'\bweapon', r'\bgun\b', r'\bguns\b',
        r'\bshoot', r'\bexplosion', r'\bdestruction\b',
        r'\bcrime\b', r'\bcriminal\b', r'\bmafia\b', r'\bgang\b',
        r'\balcohol\b', r'\bsmoking\b', r'\btobacco\b',
        r'\bhorror\b', r'\bterrif', r'\bfear\b',
        r'\bdark\s+themes?\b', r'\bmature\s+themes?\b',
    ],
    # Tier 2 triggers (mild themes)
    2: [
        r'\bfight', r'\bbattle\b', r'\benemy\b', r'\benemies\b',
        r'\bdefeat\b', r'\bdanger', r'\bthreat',
        r'\bscary\b', r'\bspooky\b', r'\bhaunt',
        r'\bmild\s+violence\b', r'\bcartoon\s+violence\b',
        r'\bromantic?\b', r'\brelationship',
    ],
}

# Known franchise -> tier overrides (strong signals from well-known series)
_FRANCHISE_TIER = {
    # Family-friendly franchises (tier 1)
    'mario':          1, 'super mario':    1, 'kirby':          1,
    'yoshi':          1, 'donkey kong':    1, 'animal crossing': 1,
    'pokemon':        1, 'tetris':         1, 'pac-man':        1,
    'sonic':          1, 'mega man':       1, 'rayman':         1,
    'lego':           1, 'littlebigplanet': 1, 'sackboy':       1,
    'crash bandicoot': 1, 'spyro':        1, 'ratchet & clank': 2,
    'jak and daxter': 2, 'sly cooper':    2,
    # Teen franchises (tier 3)
    'zelda':          2, 'legend of zelda': 2, 'metroid':       3,
    'final fantasy':  3, 'kingdom hearts': 2, 'fire emblem':   3,
    'persona':        3, 'tales of':      2, 'dragon quest':  2,
    'star fox':       2, 'star wars':     3, 'halo':          3,
    'fortnite':       3, 'overwatch':     3, 'destiny':       3,
    'uncharted':      3, 'tomb raider':   3, 'metal gear':    3,
    'batman':         3, 'spider-man':    3,
    # Mature franchises (tier 4+)
    'grand theft auto': 4, 'gta':         4, 'call of duty':  4,
    'resident evil':  4, 'silent hill':   4, 'dead space':    4,
    'doom':           4, 'mortal kombat': 4, 'diablo':        4,
    'the witcher':    4, 'witcher':       4, 'god of war':    4,
    'gears of war':   4, 'dark souls':    3, 'bloodborne':    4,
    'bayonetta':      4, 'devil may cry': 3, 'red dead':      4,
    'assassin\'s creed': 4, 'far cry':    4, 'hitman':        4,
    'last of us':     4, 'cyberpunk':     4, 'saints row':    4,
    'max payne':      4, 'manhunt':       6, 'postal':        6,
}

# Retro systems that predate modern rating standards (pre-ESRB, 1994)
# Games on these systems rarely had content beyond "Teen" tier
_RETRO_SYSTEMS = frozenset({
    # Pre-ESRB consoles
    'nes', 'famicom', 'snes', 'superfamicom', 'megadrive', 'genesis',
    'mastersystem', 'sg-1000', 'gamegear', 'gb', 'gbc',
    'pcengine', 'pcenginecd', 'supergrafx', 'tg16', 'tg-cd',
    'neogeo', 'neogeocd', 'neogeomvs',
    'atari2600', 'atari5200', 'atari7800', 'atarijaguar', 'atarilynx',
    'colecovision', 'intellivision', 'vectrex', 'odyssey2',
    '3do', 'cdi',
    # Retro computers
    'c64', 'c128', 'vic20', 'amiga', 'amstradcpc', 'cpc',
    'zxspectrum', 'spectrum', 'zx81', 'msx', 'msx1', 'msx2',
    'atarist', 'atari800', 'atarixe',
    'apple2', 'apple2gs',
    'dos', 'pc88', 'pc98', 'x68000', 'fm7', 'fmtowns',
    'samcoupe', 'bbc', 'acorn', 'dragon32', 'ti99',
})


def infer_rating_from_content(game):
    """Infer age ratings from game metadata when no ratings are available.

    Analyzes genre, description, game structure, franchise, and system era
    to estimate a maturity tier, then maps it to all 8 rating systems.

    Args:
        game: dict with keys like 'genre', 'description', 'game_structure',
              'franchise', 'system_folder', rating columns, etc.

    Returns:
        dict: {db_column: rating_value} for each system, or empty dict
              if ratings already exist or inference isn't possible.
    """
    # Don't infer if any rating already exists
    for sys_key in RATING_SYSTEM_KEYS:
        col = RATING_SYSTEMS[sys_key]['db_column']
        val = game.get(col) if hasattr(game, 'get') else None
        if val:
            return {}

    genre_str = str(game.get('genre', '') or '').strip()
    desc = str(game.get('description', '') or '').strip().lower()
    structure = str(game.get('game_structure', '') or '').strip()
    franchise = str(game.get('franchise', '') or '').strip().lower()
    system_folder = str(game.get('system_folder', '') or '').strip().lower()

    # Need at least genre or description to make an inference
    if not genre_str and not desc:
        return {}

    # 1. Genre-based tier (take highest from multi-genre)
    genre_tier = 1  # default: Everyone
    genres = [g.strip() for g in genre_str.split(',') if g.strip()]
    for g in genres:
        tier = _GENRE_TIER.get(g, 1)
        genre_tier = max(genre_tier, tier)

    # 2. Game structure modifier
    struct_mod = 0
    structures = [s.strip() for s in structure.split(',') if s.strip()]
    for s in structures:
        struct_mod = max(struct_mod, _STRUCTURE_MODIFIER.get(s, 0))

    # 3. Description keyword analysis (highest matching tier wins)
    desc_tier = 0
    if desc:
        for tier in sorted(_CONTENT_KEYWORDS_TIER.keys(), reverse=True):
            for pattern in _CONTENT_KEYWORDS_TIER[tier]:
                if re.search(pattern, desc):
                    desc_tier = max(desc_tier, tier)
                    break
            if desc_tier >= tier:
                break  # no need to check lower tiers

    # 4. Franchise override (strong signal — takes priority if higher)
    franchise_tier = 0
    if franchise:
        for key, tier in _FRANCHISE_TIER.items():
            if key in franchise:
                franchise_tier = max(franchise_tier, tier)

    # 5. Combine signals — take the highest
    inferred_tier = max(genre_tier + struct_mod, desc_tier, franchise_tier)

    # 6. Retro system adjustment — cap at tier 3 (Teen) unless strong
    #    content signals push higher
    if system_folder in _RETRO_SYSTEMS:
        content_signal = max(desc_tier, franchise_tier)
        if content_signal < 4:
            # No strong content signal — cap at Teen
            inferred_tier = min(inferred_tier, 3)

    # 7. Clamp to valid range
    inferred_tier = max(0, min(6, inferred_tier))

    # 8. Map tier to all rating systems
    result = {}
    for sys_key in RATING_SYSTEM_KEYS:
        col = RATING_SYSTEMS[sys_key]['db_column']
        rating = _TIER_TO_RATING.get((sys_key, inferred_tier))
        if rating:
            result[col] = rating

    return result


# Supported image file extensions
SUPPORTED_IMAGE_EXTENSIONS = ['.png', '.webp', '.jpg', '.jpeg', '.svg']

# Patterns that indicate a bonus/extra disc (case-insensitive)
BONUS_DISC_PATTERNS = [
    r'\(bonus[)\-]',           # (Bonus) or (Bonus-Something) - common in ROM naming
    r'\bbonus\s*disc\b',
    r'\bbonus\s*dvd\b',
    r'\bbonus\s*content\b',
    r'\bmaking\s*of\b',
    r'\bbehind\s*the\s*scenes\b',
    r'\bdocumentary\b',
    r'\bspecial\s*features\b',
    r'\bextra\s*disc\b',
    r'\bextras?\s*dvd\b',
    r'\bhistory\s*disc\b',
    r'\bartwork\s*disc\b',
    r'\bsoundtrack\s*disc\b',
    r'\bmusic\s*disc\b',
    r'\binstall\s*disc\b',
    r'\binstallation\s*disc\b',
    r'\b[-–]\s*bonus\b',
    r'\b[-–]\s*extras?\b',
    r'\bdocument\s*of\b',       # "The Document of Metal Gear Solid 2"
    r'\bthe\s*art\s*of\b',      # "The Art of..." documentaries
]

# Platform name normalization mapping
PLATFORM_NAME_MAP = {
    # PlayStation family
    'playstation': 'PlayStation',
    'playstation 1': 'PlayStation',
    'playstation1': 'PlayStation',
    'psx': 'PlayStation',
    'ps1': 'PlayStation',
    'playstation 2': 'PlayStation 2',
    'playstation2': 'PlayStation 2',
    'ps2': 'PlayStation 2',
    'ps2 (usa)': 'PlayStation 2',
    'ps2 (eur)': 'PlayStation 2',
    'ps2 (jpn)': 'PlayStation 2',
    'sony playstation 2': 'PlayStation 2',
    'playstation 3': 'PlayStation 3',
    'playstation3': 'PlayStation 3',
    'ps3': 'PlayStation 3',
    'playstation 4': 'PlayStation 4',
    'ps4': 'PlayStation 4',
    'playstation 5': 'PlayStation 5',
    'ps5': 'PlayStation 5',
    'playstation portable': 'PSP',
    'psp': 'PSP',
    'playstation vita': 'PS Vita',
    'psvita': 'PS Vita',
    'ps vita': 'PS Vita',
    
    # Nintendo family
    'nintendo entertainment system': 'NES',
    'nintendo entertainment system (nes)': 'NES',
    'nes': 'NES',
    'famicom': 'NES',
    'super nintendo entertainment system': 'SNES',
    'super nintendo': 'SNES',
    'snes': 'SNES',
    'super famicom': 'SNES',
    'nintendo 64': 'Nintendo 64',
    'n64': 'Nintendo 64',
    'nintendo gamecube': 'GameCube',
    'gamecube': 'GameCube',
    'gc': 'GameCube',
    'wii': 'Wii',
    'nintendo wii': 'Wii',
    'wii u': 'Wii U',
    'wiiu': 'Wii U',
    'nintendo switch': 'Switch',
    'switch': 'Switch',
    'game boy': 'Game Boy',
    'gameboy': 'Game Boy',
    'gb': 'Game Boy',
    'game boy color': 'Game Boy Color',
    'gbc': 'Game Boy Color',
    'game boy advance': 'Game Boy Advance',
    'gba': 'Game Boy Advance',
    'nintendo ds': 'Nintendo DS',
    'nds': 'Nintendo DS',
    'ds': 'Nintendo DS',
    'nintendo 3ds': 'Nintendo 3DS',
    '3ds': 'Nintendo 3DS',
    
    # Sega family
    'sega master system': 'Master System',
    'master system': 'Master System',
    'sms': 'Master System',
    'sega genesis': 'Genesis',
    'genesis': 'Genesis',
    'sega mega drive': 'Genesis',
    'mega drive': 'Genesis',
    'megadrive': 'Genesis',
    'sega saturn': 'Saturn',
    'saturn': 'Saturn',
    'sega dreamcast': 'Dreamcast',
    'dreamcast': 'Dreamcast',
    'dc': 'Dreamcast',
    'sega cd': 'Sega CD',
    'segacd': 'Sega CD',
    'sega 32x': '32X',
    '32x': '32X',
    'game gear': 'Game Gear',
    'gamegear': 'Game Gear',
    'gg': 'Game Gear',
    
    # Microsoft family
    'xbox': 'Xbox',
    'microsoft xbox': 'Xbox',
    'xbox 360': 'Xbox 360',
    'xbox360': 'Xbox 360',
    'xbox one': 'Xbox One',
    'xboxone': 'Xbox One',
    'xbox series x': 'Xbox Series X',
    'xbox series s': 'Xbox Series S',
    
    # Atari family
    'atari 2600': 'Atari 2600',
    'atari2600': 'Atari 2600',
    'atari 5200': 'Atari 5200',
    'atari 7800': 'Atari 7800',
    'atari lynx': 'Atari Lynx',
    'lynx': 'Atari Lynx',
    'atari jaguar': 'Atari Jaguar',
    'jaguar': 'Atari Jaguar',
    
    # PC/Computer
    'pc': 'PC',
    'pc (microsoft windows)': 'PC',
    'microsoft windows': 'PC',
    'windows': 'PC',
    'ibm pc': 'PC',
    'dos': 'DOS',
    'ms-dos': 'DOS',
    'linux': 'Linux',
    'mac': 'Mac',
    'macos': 'Mac',
    'macintosh': 'Mac',
    'apple macintosh': 'Mac',
    'apple ii': 'Apple II',
    'apple iigs': 'Apple IIGS',
    'amiga': 'Amiga',
    'commodore amiga': 'Amiga',
    'amiga 600': 'Amiga 600',
    'amiga600': 'Amiga 600',
    'amiga 1200': 'Amiga 1200',
    'amiga1200': 'Amiga 1200',
    'amiga cd32': 'Amiga CD32',
    'commodore amiga cd32': 'Amiga CD32',
    'cdtv': 'CDTV',
    'commodore cdtv': 'CDTV',
    'commodore 64': 'C64',
    'c64': 'C64',
    'commodore vic-20': 'VIC-20',
    'vic-20': 'VIC-20',
    'vic20': 'VIC-20',
    'commodore plus/4': 'Commodore Plus/4',

    # British micros
    'amstrad cpc': 'Amstrad CPC',
    'cpc': 'Amstrad CPC',
    'amstrad gx4000': 'Amstrad GX4000',
    'bbc micro': 'BBC Micro',
    'bbcmicro': 'BBC Micro',
    'acorn electron': 'Acorn Electron',
    'acorn archimedes': 'Acorn Archimedes',
    'zx spectrum': 'ZX Spectrum',
    'sinclair zx spectrum': 'ZX Spectrum',
    'spectrum': 'ZX Spectrum',
    'zx81': 'ZX81',
    'sinclair zx81': 'ZX81',
    'sam coupe': 'SAM Coupe',
    'sam coupé': 'SAM Coupe',
    'oric': 'Oric',

    # Japanese micros
    'msx': 'MSX',
    'msx1': 'MSX',
    'msx2': 'MSX2',
    'msx turbo r': 'MSX Turbo R',
    'sharp x68000': 'Sharp X68000',
    'x68000': 'Sharp X68000',
    'sharp x1': 'Sharp X1',
    'x1': 'Sharp X1',
    'nec pc-8801': 'NEC PC-8801',
    'pc-8801': 'NEC PC-8801',
    'pc88': 'NEC PC-8801',
    'nec pc-9801': 'NEC PC-9801',
    'pc-9801': 'NEC PC-9801',
    'pc98': 'NEC PC-9801',
    'fm towns': 'FM Towns',
    'fujitsu fm-7': 'FM-7',
    'fm-7': 'FM-7',

    # Atari computers
    'atari st': 'Atari ST',
    'atari 800': 'Atari 800',
    'atari 400': 'Atari 800',
    'atari xe': 'Atari XE',

    # Other home computers
    'dragon 32': 'Dragon 32',
    'dragon32': 'Dragon 32',
    'trs-80': 'TRS-80',
    'trs-80 color computer': 'TRS-80 CoCo',
    'coco': 'TRS-80 CoCo',
    'texas instruments ti-99/4a': 'TI-99/4A',
    'ti-99': 'TI-99/4A',
    'thomson mo/to': 'Thomson MO/TO',
    'spectravideo': 'Spectravideo',

    # Arcade
    'arcade': 'Arcade',

    # Neo Geo
    'neo geo': 'Neo Geo',
    'neogeo': 'Neo Geo',
    'snk neo geo': 'Neo Geo',
    'neo geo aes': 'Neo Geo',
    'neo geo mvs': 'Neo Geo',
    'neo geo cd': 'Neo Geo CD',
    'neo geo pocket': 'Neo Geo Pocket',
    'neo geo pocket color': 'Neo Geo Pocket Color',
    'ngp': 'Neo Geo Pocket',
    'ngpc': 'Neo Geo Pocket Color',

    # TurboGrafx / PC Engine
    'turbografx-16': 'TurboGrafx-16',
    'turbografx16': 'TurboGrafx-16',
    'tg16': 'TurboGrafx-16',
    'pc engine': 'PC Engine',
    'pc engine cd': 'PC Engine CD',
    'pc engine supergrafx': 'PC Engine SuperGrafx',
    'turbografx-cd': 'TurboGrafx-CD',
    'pc-fx': 'PC-FX',
    'pcfx': 'PC-FX',

    # 3DO
    '3do': '3DO',
    '3do interactive multiplayer': '3DO',

    # Other consoles
    'colecovision': 'ColecoVision',
    'intellivision': 'Intellivision',
    'mattel intellivision': 'Intellivision',
    'vectrex': 'Vectrex',
    'magnavox odyssey 2': 'Odyssey 2',
    'odyssey 2': 'Odyssey 2',
    'philips videopac': 'Videopac',
    'videopac': 'Videopac',
    'fairchild channel f': 'Channel F',
    'channel f': 'Channel F',
    'bally astrocade': 'Bally Astrocade',
    'virtual boy': 'Virtual Boy',
    'philips cd-i': 'CD-i',
    'cd-i': 'CD-i',
    'sg-1000': 'SG-1000',
    'sega sg-1000': 'SG-1000',

    # Handheld
    'nokia n-gage': 'N-Gage',
    'n-gage': 'N-Gage',
    'bandai wonderswan': 'WonderSwan',
    'wonderswan': 'WonderSwan',
    'wonderswan color': 'WonderSwan Color',
    'game & watch': 'Game & Watch',
    'game and watch': 'Game & Watch',
    'watara supervision': 'Watara Supervision',
    'tiger game.com': 'Game.com',
    'pokemon mini': 'Pokemon Mini',

    # Disc systems
    'famicom disk system': 'Famicom Disk System',
    'fds': 'Famicom Disk System',
    'mega cd': 'Mega CD',
    'megacd': 'Mega CD',

    # Modern / digital
    'steam': 'Steam',
    'ios': 'iOS',
    'android': 'Android',
    'stadia': 'Stadia',
}


# =============================================================================
# TITLE PARSING FUNCTIONS
# =============================================================================

def derive_title_from_filename(rom_path, is_computer_system=False):
    """
    Convert a ROM filename back to a proper game title following naming standards.
    
    This reverses the ROM naming conventions:
    - Removes file extension
    - Removes region tags: (USA), (Europe), (Japan), (World), etc.
    - Removes revision/version tags: (Rev 1), (v1.1), etc.
    - Removes edition tags: (Greatest Hits), (Platinum), etc.
    - Converts ' - ' to ': ' (reversing the colon replacement)
    - For computer systems: also removes (Year) (Publisher) tags
    
    Args:
        rom_path: Full path to ROM file or just filename
        is_computer_system: If True, also remove year and publisher tags
    
    Returns:
        str: Cleaned game title
    
    Examples:
        'Assassin's Creed - Revelations (USA).iso' -> "Assassin's Creed: Revelations"
        'The Legend of Zelda - Ocarina of Time (USA).n64' -> 'The Legend of Zelda: Ocarina of Time'
        'Lemmings (1991) (Psygnosis).adf' -> 'Lemmings' (if is_computer_system=True)
    """
    # Get just the filename from the path
    filename = os.path.basename(rom_path)
    
    # Remove file extension
    name = os.path.splitext(filename)[0]
    
    # Remove Disc indicators like (Disc 1 of 3) - must be done before general parentheses removal
    name = re.sub(r'\s*\(Disc\s*\d+(?:\s*of\s*\d+)?\)', '', name, flags=re.IGNORECASE)
    
    # Region tags to remove
    region_tags = [
        r'\(USA\)', r'\(Europe\)', r'\(Japan\)', r'\(World\)', r'\(Germany\)',
        r'\(France\)', r'\(Spain\)', r'\(Italy\)', r'\(Australia\)', r'\(Brazil\)',
        r'\(Korea\)', r'\(China\)', r'\(Taiwan\)', r'\(Asia\)',
        r'\(U\)', r'\(E\)', r'\(J\)', r'\(W\)',
        r'\(En\)', r'\(Fr\)', r'\(De\)', r'\(Es\)', r'\(It\)', r'\(Ja\)',
        r'\(En,Fr\)', r'\(En,De\)', r'\(En,Es\)', r'\(En,Fr,De\)', r'\(En,Fr,De,Es,It\)',
    ]
    
    for tag in region_tags:
        name = re.sub(r'\s*' + tag, '', name, flags=re.IGNORECASE)
    
    # Version/Revision tags to remove
    version_tags = [
        r'\(Rev\s*\d*[A-Z]?\)', r'\(v\d+\.?\d*\)', r'\(Version\s*\d+\.?\d*\)',
        r'\(Beta\)', r'\(Proto\)', r'\(Demo\)', r'\(Sample\)', r'\(Unl\)',
        r'\(Hack\)', r'\(PD\)', r'\(Pirate\)',
    ]
    
    for tag in version_tags:
        name = re.sub(r'\s*' + tag, '', name, flags=re.IGNORECASE)
    
    # Edition tags to remove (keep these common ones)
    edition_tags = [
        r'\(Greatest Hits\)', r"\(Player's Choice\)", r'\(Platinum\)',
        r"\(Collector's Edition\)", r'\(Limited Edition\)', r'\(Special Edition\)',
        r'\(Game of the Year\)', r'\(GOTY\)', r'\(Remastered\)',
    ]
    
    for tag in edition_tags:
        name = re.sub(r'\s*' + tag, '', name, flags=re.IGNORECASE)
    
    # For computer systems, remove (Year) and (Publisher) tags
    if is_computer_system:
        # Remove year tag (4 digits in parentheses)
        name = re.sub(r'\s*\(\d{4}\)', '', name)
        # Remove remaining parenthetical tags (likely publisher)
        name = re.sub(r'\s*\([^)]+\)$', '', name)
    
    # Convert ' - ' back to ': ' (reversing the naming standard)
    # But be careful: "The Legend of Zelda - A Link to the Past" should become
    # "The Legend of Zelda: A Link to the Past"
    # We only convert the FIRST ' - ' if it looks like a subtitle separator
    # A subtitle separator typically has a capital letter after it
    name = re.sub(r' - (?=[A-Z])', ': ', name)
    
    # Normalize colon formatting: " : " -> ": " and " :" -> ":"
    name = name.replace(' : ', ': ')
    name = name.replace(' :', ':')
    
    # Clean up any remaining artifacts
    name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single
    name = name.strip()
    
    return name


def reset_game_title_from_filename(game_id, conn=None):
    """
    Reset a game's title to be derived from its ROM filename.
    
    This function is imported and used by routes that need to reset titles.
    Note: This requires database access, so it imports query/execute locally
    to avoid circular imports.
    
    Args:
        game_id: Database ID of the game
        conn: Optional database connection (creates one if not provided)
    
    Returns:
        The new title, or None if failed
    """
    from services.database import get_db
    
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    
    try:
        cursor = conn.cursor()
        
        # Get game info
        cursor.execute("""
            SELECT g.id, g.rom_path, g.title, s.folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,))
        game = cursor.fetchone()
        
        if not game:
            return None
        
        rom_path = game[1] if isinstance(game, tuple) else game['rom_path']
        system_folder = game[3] if isinstance(game, tuple) else game['folder']
        
        if not rom_path:
            return None
        
        # Check if it's a computer system
        is_computer = system_folder.lower() in COMPUTER_SYSTEMS
        
        # Derive title from filename
        new_title = derive_title_from_filename(rom_path, is_computer)
        
        if new_title:
            # Generate sort title
            new_sort_title = generate_sort_title(new_title)
            
            # Update the game
            cursor.execute("""
                UPDATE games SET title = ?, sort_title = ? WHERE id = ?
            """, (new_title, new_sort_title, game_id))
            
            if close_conn:
                conn.commit()
            
            return new_title
        
        return None
    finally:
        if close_conn:
            conn.close()


def normalize_players_value(value):
    """Coerce a `players` value to int | None for the games.players INTEGER column.

    The DB column is INTEGER but SQLite weak typing happily accepts strings
    like "1-4" or "" — Pass 40.6 closed two routes that did exactly that
    (api_game_edit JSON body, edit_metadata form-POST).  Scraper "1-4"
    ranges normalize to the maximum (4) per the existing fill-only contract.

    Returns:
        int >= 1 if a valid number was extracted, else None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool is an int subclass — explicitly reject so True doesn't become 1.
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        return int(value) if value >= 1 else None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    # A trailing '+' ("4+", "1-4+") is an open-ended upper bound; the
    # number is still the largest count the source states. ES-DE sends this
    # form and only its own copy of the parse handled it (Pass 59.29).
    def _as_int(token):
        try:
            return int(token.rstrip('+').strip())
        except ValueError:
            return None

    # Range form "1-4" / "2-8" — take the maximum.
    if '-' in stripped:
        nums = [n for n in (_as_int(p) for p in stripped.split('-') if p.strip())
                if n is not None]
        if nums:
            return max(nums) if max(nums) >= 1 else None
        return None
    # Plain integer string.
    n = _as_int(stripped)
    return n if n is not None and n >= 1 else None


def generate_sort_title(title):
    """
    Generate a sortable title from a game title.
    
    Converts Roman numerals to Arabic numerals and pads numbers for proper sorting.
    
    Args:
        title: Game title string
    
    Returns:
        str: Title optimized for alphabetical sorting
    
    Examples:
        "Final Fantasy IX" -> "Final Fantasy 09"
        "Final Fantasy VII" -> "Final Fantasy 07"
        "Mega Man X2" -> "Mega Man X02"
        "I-Ninja" -> "I-Ninja" (NOT converted - single letter at start with hyphen)
        "V-Rally 3" -> "V-Rally 03" (NOT converted for V, but 3 is padded)
    """
    if not title:
        return title
    
    sort_title = title

    # Single-letter Roman numerals that could be part of compound game names
    # (I-Ninja, V-Rally, X-Men) — skip when adjacent to a hyphen
    single_letter_romans = {'I', 'V', 'X'}

    # Replace Roman numerals with Arabic (longest first to prevent partial matches)
    for roman, arabic in sorted(ROMAN_NUMERAL_MAP.items(), key=lambda x: -len(x[0])):
        padded = arabic.zfill(2)

        if roman in single_letter_romans:
            # Pass 41.9.C — tightened heuristic. Previously the pattern was
            # `(?<![-\w])X(?![-\w])`, which converts "I" inside any title
            # where it stands as a separate word (e.g. "I am Setsuna" became
            # "01 am Setsuna" — wrong; "I" there is the pronoun, not the
            # numeral). The fix narrows the post-context to one of:
            #   - end-of-title (`$`) — the conventional sequel position
            #   - subtitle separator: `:` `(` `[` (with optional whitespace)
            #   - whitespace + digit (e.g. "Mega Man X 2")
            # The pre-context still rejects hyphen/word-char (X-Men, I-Ninja).
            pattern = r'(?<![-\w])' + roman + r'(?=\s*$|\s*[:(\[]|\s+\d)'
        else:
            pattern = r'\b' + roman + r'\b'

        sort_title = re.sub(pattern, padded, sort_title)
    
    # Also pad any existing Arabic numerals in the title
    def pad_number(match):
        num = match.group(0)
        return num.zfill(2) if len(num) == 1 else num
    
    sort_title = re.sub(r'\b(\d+)\b', pad_number, sort_title)
    
    return sort_title


# =============================================================================
# RATING MAPPING FUNCTIONS
# =============================================================================

def map_esrb_to_pegi(esrb_rating):
    """
    Map an ESRB rating to its PEGI equivalent.
    
    Args:
        esrb_rating: ESRB rating string (e.g., 'E', 'T', 'M')
    
    Returns:
        str: PEGI rating or None if no mapping exists
    """
    if not esrb_rating:
        return None
    
    # Normalize the ESRB rating
    esrb_clean = esrb_rating.upper().strip()
    
    # Try exact match first
    if esrb_clean in ESRB_TO_PEGI_MAP:
        return ESRB_TO_PEGI_MAP[esrb_clean]
    
    # Try partial match (e.g., "ESRB-M" or "Mature 17+")
    # Sort by key length descending so 'E10+' matches before 'E'
    for key, value in sorted(ESRB_TO_PEGI_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if key in esrb_clean:
            return value
    
    return None


# =============================================================================
# PLATFORM NORMALIZATION
# =============================================================================

def normalize_platform_name(platform_name):
    """
    Normalize a platform name to a standard display format.
    
    Args:
        platform_name: Raw platform name from various sources
    
    Returns:
        str: Standardized platform name for display
    """
    if not platform_name:
        return 'Unknown'
    
    # Try lowercase match
    key = platform_name.lower().strip()
    if key in PLATFORM_NAME_MAP:
        return PLATFORM_NAME_MAP[key]
    
    # Return original as-is if no mapping found (don't .title() — it breaks acronyms)
    return platform_name.strip()


# =============================================================================
# FILE UTILITIES
# =============================================================================

def find_image_file(base_path, base_name, extensions=None):
    """
    Find an image file with any supported extension.
    
    Args:
        base_path: Directory to search in
        base_name: Filename without extension
        extensions: List of extensions to try (defaults to SUPPORTED_IMAGE_EXTENSIONS)
    
    Returns:
        tuple: (filename, full_path) or (None, None) if not found
    """
    if extensions is None:
        extensions = SUPPORTED_IMAGE_EXTENSIONS
    
    for ext in extensions:
        filename = f"{base_name}{ext}"
        full_path = os.path.join(base_path, filename)
        if os.path.exists(full_path):
            return filename, full_path
    return None, None


# =============================================================================
# BONUS DISC DETECTION
# =============================================================================

def is_bonus_disc_title(title):
    """
    Check if a game title matches bonus disc patterns.
    
    Args:
        title: Game title to check
    
    Returns:
        bool: True if the title appears to be a bonus/extra disc
    """
    if not title:
        return False
    
    title_lower = title.lower()
    
    for pattern in BONUS_DISC_PATTERNS:
        if re.search(pattern, title_lower):
            return True
    
    return False


def extract_base_game_title(bonus_title):
    """
    Extract the base game title from a bonus disc title.
    
    Args:
        bonus_title: Title of the bonus disc
    
    Returns:
        str: Extracted base game title, or None if extraction fails
    
    Examples:
        'God of War - Making Of' -> 'God of War'
        'Ratchet & Clank Bonus Disc' -> 'Ratchet & Clank'
        'Metal Gear Solid 3 - Documentary' -> 'Metal Gear Solid 3'
        'Call of Duty 3 Special Edition (Bonus) (USA)' -> 'Call of Duty 3'
        'The Document of Metal Gear Solid 2' -> 'Metal Gear Solid 2'
        'The Art of Resident Evil' -> 'Resident Evil'
        'Persona 2 Eternal Punishment (Bonus Disc) (USA)' -> 'Persona 2 Eternal Punishment'
    """
    if not bonus_title:
        return None
    
    # Special patterns where we want what comes AFTER (e.g., "The Document of X" -> X)
    after_patterns = [
        r'^the\s+document\s+of\s+(.+)',
        r'^the\s+art\s+of\s+(.+)',
        r'^the\s+making\s+of\s+(.+)',
        r'^making\s+of\s+(.+)',
    ]
    
    for pattern in after_patterns:
        match = re.search(pattern, bonus_title, re.IGNORECASE)
        if match:
            base_title = match.group(1).strip()
            # Clean up trailing region/edition tags
            base_title = re.sub(r'\s*\([^)]*\)\s*$', '', base_title).strip()
            if base_title and len(base_title) > 2:
                return base_title
    
    # Handle parenthesized bonus patterns first: "(Bonus)", "(Bonus Disc)", "(Extras)",
    # "(Special Features)", "(The Making Of)", "(Making Of)", "(The Art of X)", etc.
    paren_bonus_match = re.search(
        r'^(.+?)\s*\((?:the\s+)?(?:bonus|extras?|special\s*features|making\s*of|art\s*of|behind\s*the\s*scenes|documentary)\b[^)]*\)', 
        bonus_title, re.IGNORECASE
    )
    if paren_bonus_match:
        base_title = paren_bonus_match.group(1).strip()
        # Clean up trailing separators and region tags
        base_title = re.sub(r'[\s\-–:]+$', '', base_title)
        base_title = re.sub(r'\s*\([^)]*\)\s*$', '', base_title).strip()
        if base_title and len(base_title) > 2:
            return base_title
    
    # Standard patterns - extract what comes BEFORE the bonus pattern
    for pattern in BONUS_DISC_PATTERNS:
        # Create a regex that captures everything before the bonus pattern
        full_pattern = r'^(.+?)[\s\-–]*' + pattern
        match = re.search(full_pattern, bonus_title, re.IGNORECASE)
        if match:
            base_title = match.group(1).strip()
            
            # Skip if we captured something too short that looks like an article
            if base_title.lower() in ('the', 'a', 'an'):
                continue
                
            # Clean up trailing separators and parentheses
            base_title = re.sub(r'[\s\-–:(]+$', '', base_title)
            # Clean up trailing region/edition tags for cleaner matching
            base_title = re.sub(r'\s*\([^)]*\)\s*$', '', base_title).strip()
            if base_title and len(base_title) > 2:
                return base_title

    return None


# =============================================================================
# RETROACHIEVEMENTS HELPERS
# =============================================================================

def is_ra_supported(system_folder):
    """Check if a system supports RetroAchievements"""
    try:
        from scraper.retroachievements import RA_CONSOLE_MAP
        return system_folder.lower() in RA_CONSOLE_MAP
    except ImportError:
        return False
    except Exception:
        return False


def get_ra_supported_systems():
    """Get list of all RA-supported system folders"""
    try:
        from scraper.retroachievements import RA_CONSOLE_MAP
        return list(RA_CONSOLE_MAP.keys())
    except ImportError:
        return []
    except Exception:
        return []
