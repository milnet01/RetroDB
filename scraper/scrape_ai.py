# =============================================================================
# AI METADATA SCRAPER
# =============================================================================
# Multi-provider AI scraper (Google Gemini, OpenAI, Anthropic Claude) that
# fills missing game metadata fields using structured prompts.
# Handles text fields only — never images, screenshots, videos, or manuals.
#
# Public interface:
#   get_game_details(game_id, title, system_name, system_folder, existing_metadata)
#   check_api_status()
# =============================================================================

import json
import re
import logging
import os
import time

import config
from scraper.base_scraper import http_post, rate_limit, safe_json

logger = logging.getLogger(__name__)

# Settings file path (same as scraper_manager)
SCRAPER_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'scraper_settings.json'
)

# Fields the AI scraper can fill (text-only, no media)
AI_FILLABLE_FIELDS = [
    'genre', 'description', 'developer', 'publisher', 'release_date',
    'players', 'modes', 'esrb_rating', 'pegi_rating', 'cero_rating',
    'usk_rating', 'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
    'region', 'franchise', 'similar_games', 'controller_support', 'save_type',
    'game_structure', 'perspective', 'dimension', 'campaign',
    'other_platforms', 'edition',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
]

# Schema constraints for validation (values AI must pick from)
FIELD_SCHEMAS = {
    'genre': [
        'Action', 'Action-Adventure', 'Action-Platformer', 'Action-RPG',
        'Adventure', 'Battle-Royale', 'Beat-em-up', 'Board-Card', 'Casual',
        'City-Builder', 'Driving', 'Educational', 'Fighting',
        'First-Person-Shooter', 'Flight', 'Hack-n-Slash', 'Horror',
        'Hunting', 'JRPG', 'Life-Simulation', 'Light-Gun', 'Management',
        'MMORPG', 'Music-Rhythm', 'Party', 'Platformer',
        'Psychological-Horror', 'Puzzle', 'Racing', 'Real-Time Strategy',
        'RPG', 'Shoot-em-up', 'Shooter', 'Simulation', 'Sports', 'Stealth',
        'Strategy', 'Survival', 'Survival-Horror', 'Tower-Defence', 'Trivia',
        'Turn-Based Strategy', 'Vehicular-Combat', 'Visual-Novel',
    ],
    'game_structure': [
        'Hub-Based', 'Immersive-Sim', 'Interactive-Drama', 'Labyrinth',
        'Level-Based', 'Linear', 'Match-Based', 'Metroidvania',
        'Open-World', 'Procedural', 'Roguelike', 'Sandbox', 'Turn-Based',
    ],
    'perspective': [
        'First-Person', 'Isometric', 'Side-Scroller', 'Third-Person',
        'Top-Down', 'Vertical-Scroller',
    ],
    'dimension': [
        '2D', '2.5D', '3D', 'AR (Augmented Reality)',
        'FMV (Full Motion Video)', 'Pseudo-3D', 'VR',
    ],
    'modes': [
        'Asynchronous Multiplayer', 'Cross-Platform Play', 'LAN-System Link',
        'Local Co-op', 'Local Multiplayer', 'MMO', 'Online Co-op',
        'Online Multiplayer', 'Single-Player', 'Split-Screen', 'Versus',
    ],
    'save_type': [
        'Battery-Backed RAM', 'Cartridge-RAM', 'Cassette-Tape', 'Cloud Save',
        'Floppy-Disk', 'Internal Storage', 'Memory Card', 'None', 'Password',
        'Virtual Memory Unit',
    ],
    'other_platforms': [
        # Special
        'Exclusive',
        # PlayStation
        'PlayStation', 'PlayStation 2', 'PlayStation 3', 'PlayStation 4',
        'PlayStation 5', 'PSP', 'PS Vita',
        # Nintendo
        'NES', 'SNES', 'Nintendo 64', 'GameCube', 'Wii', 'Wii U', 'Switch',
        'Game Boy', 'Game Boy Color', 'Game Boy Advance',
        'Nintendo DS', 'Nintendo 3DS', 'Virtual Boy',
        'Famicom Disk System', 'Game & Watch',
        # Sega
        'Master System', 'Genesis', 'Mega Drive', 'Saturn', 'Dreamcast',
        'Sega CD', 'Mega CD', '32X', 'Game Gear', 'SG-1000',
        # Microsoft
        'Xbox', 'Xbox 360', 'Xbox One', 'Xbox Series X', 'Xbox Series S',
        # Atari consoles
        'Atari 2600', 'Atari 5200', 'Atari 7800', 'Atari Lynx',
        'Atari Jaguar', 'Atari Jaguar CD',
        # Atari computers
        'Atari ST', 'Atari 800', 'Atari XE',
        # PC / modern
        'PC', 'DOS', 'Linux', 'Mac', 'Steam', 'iOS', 'Android', 'Stadia',
        # Commodore
        'Amiga', 'Amiga 600', 'Amiga 1200', 'Amiga CD32', 'CDTV',
        'C64', 'VIC-20', 'Commodore Plus/4',
        # British micros
        'Amstrad CPC', 'Amstrad GX4000', 'BBC Micro',
        'Acorn Electron', 'Acorn Archimedes',
        'ZX Spectrum', 'ZX81', 'SAM Coupe', 'Oric',
        # Japanese micros
        'MSX', 'MSX2', 'MSX Turbo R',
        'Sharp X68000', 'Sharp X1',
        'NEC PC-8801', 'NEC PC-9801', 'FM Towns', 'FM-7',
        # Apple
        'Apple II', 'Apple IIGS',
        # Other computers
        'Dragon 32', 'TRS-80', 'TRS-80 CoCo', 'TI-99/4A',
        'Thomson MO/TO', 'Spectravideo',
        # Neo Geo
        'Neo Geo', 'Neo Geo CD', 'Neo Geo Pocket', 'Neo Geo Pocket Color',
        # TurboGrafx / PC Engine
        'TurboGrafx-16', 'TurboGrafx-CD',
        'PC Engine', 'PC Engine CD', 'PC Engine SuperGrafx', 'PC-FX',
        # 3DO / CD-i
        '3DO', 'CD-i',
        # Other consoles
        'ColecoVision', 'Intellivision', 'Vectrex',
        'Odyssey 2', 'Videopac', 'Channel F', 'Bally Astrocade',
        # Handhelds
        'N-Gage', 'WonderSwan', 'WonderSwan Color',
        'Watara Supervision', 'Game.com', 'Pokemon Mini',
        # Arcade
        'Arcade',
    ],
    'campaign': ['Yes', 'No'],
    'esrb_rating': ['EC', 'E', 'E10+', 'T', 'M', 'AO', 'RP'],
    'pegi_rating': ['PEGI 3', 'PEGI 7', 'PEGI 12', 'PEGI 16', 'PEGI 18'],
    'cero_rating': ['A', 'B', 'C', 'D', 'Z'],
    'usk_rating': ['0', '6', '12', '16', '18'],
    'acb_rating': ['G', 'PG', 'M', 'MA15+', 'R18+'],
    'fpb_rating': ['A', 'PG', '7-9 PG', '10', '10-12 PG', '13', '16', '18'],
    'grac_rating': ['ALL', '12', '15', '18'],
    'classind_rating': ['L', '10', '12', '14', '16', '18'],
}

# Aliases for platform names AI may return in non-canonical form
PLATFORM_ALIASES = {
    # PlayStation
    'ps1': 'PlayStation', 'psx': 'PlayStation', 'playstation 1': 'PlayStation',
    'ps2': 'PlayStation 2', 'ps3': 'PlayStation 3', 'ps4': 'PlayStation 4',
    'ps5': 'PlayStation 5', 'playstation portable': 'PSP',
    'playstation vita': 'PS Vita', 'ps vita': 'PS Vita', 'psvita': 'PS Vita',
    'sony playstation': 'PlayStation', 'sony playstation 2': 'PlayStation 2',
    'sony playstation 3': 'PlayStation 3', 'sony playstation 4': 'PlayStation 4',
    'sony playstation 5': 'PlayStation 5',
    # Nintendo
    'nintendo entertainment system': 'NES', 'famicom': 'NES',
    'super nintendo': 'SNES', 'super nintendo entertainment system': 'SNES',
    'super famicom': 'SNES', 'n64': 'Nintendo 64', 'gc': 'GameCube',
    'nintendo gamecube': 'GameCube', 'nintendo wii': 'Wii',
    'wiiu': 'Wii U', 'nintendo switch': 'Switch',
    'gameboy': 'Game Boy', 'gb': 'Game Boy',
    'gbc': 'Game Boy Color', 'gba': 'Game Boy Advance',
    'nds': 'Nintendo DS', 'ds': 'Nintendo DS', '3ds': 'Nintendo 3DS',
    'fds': 'Famicom Disk System',
    # Sega
    'sega genesis': 'Genesis', 'sega mega drive': 'Mega Drive',
    'megadrive': 'Mega Drive', 'sega master system': 'Master System',
    'sms': 'Master System', 'sega saturn': 'Saturn',
    'sega dreamcast': 'Dreamcast', 'dc': 'Dreamcast',
    'segacd': 'Sega CD', 'megacd': 'Mega CD',
    'sega 32x': '32X', 'sega game gear': 'Game Gear',
    'gamegear': 'Game Gear', 'gg': 'Game Gear',
    'sega sg-1000': 'SG-1000',
    # Microsoft
    'microsoft xbox': 'Xbox', 'xbox360': 'Xbox 360',
    'xboxone': 'Xbox One', 'xbox series x/s': 'Xbox Series X',
    # Atari
    'atari 400': 'Atari 800',
    # PC
    'windows': 'PC', 'microsoft windows': 'PC', 'ibm pc': 'PC',
    'ms-dos': 'DOS', 'macos': 'Mac', 'macintosh': 'Mac',
    'apple macintosh': 'Mac',
    # Commodore
    'commodore 64': 'C64', 'commodore amiga': 'Amiga',
    'commodore vic-20': 'VIC-20', 'vic20': 'VIC-20',
    'amiga cd32': 'Amiga CD32', 'commodore amiga cd32': 'Amiga CD32',
    'commodore cdtv': 'CDTV',
    # British micros
    'cpc': 'Amstrad CPC', 'sinclair zx spectrum': 'ZX Spectrum',
    'spectrum': 'ZX Spectrum', 'sinclair zx81': 'ZX81',
    'bbcmicro': 'BBC Micro', 'sam coupé': 'SAM Coupe',
    # Japanese micros
    'msx1': 'MSX', 'x68000': 'Sharp X68000', 'x1': 'Sharp X1',
    'pc-8801': 'NEC PC-8801', 'pc88': 'NEC PC-8801',
    'pc-9801': 'NEC PC-9801', 'pc98': 'NEC PC-9801',
    'fm towns': 'FM Towns', 'fujitsu fm-7': 'FM-7',
    # TurboGrafx
    'tg16': 'TurboGrafx-16', 'turbografx16': 'TurboGrafx-16',
    'pc engine cd-rom': 'PC Engine CD', 'pcfx': 'PC-FX',
    # Neo Geo
    'neogeo': 'Neo Geo', 'snk neo geo': 'Neo Geo',
    'neo geo aes': 'Neo Geo', 'neo geo mvs': 'Neo Geo',
    'ngp': 'Neo Geo Pocket', 'ngpc': 'Neo Geo Pocket Color',
    # Other
    '3do interactive multiplayer': '3DO', 'philips cd-i': 'CD-i',
    'coleco vision': 'ColecoVision', 'mattel intellivision': 'Intellivision',
    'fairchild channel f': 'Channel F',
    'magnavox odyssey 2': 'Odyssey 2', 'philips videopac': 'Videopac',
    'nokia n-gage': 'N-Gage', 'n-gage': 'N-Gage',
    'bandai wonderswan': 'WonderSwan', 'wonderswan color': 'WonderSwan Color',
    'game and watch': 'Game & Watch',
    'dragon32': 'Dragon 32', 'trs-80 color computer': 'TRS-80 CoCo',
    'coco': 'TRS-80 CoCo', 'ti-99': 'TI-99/4A',
    'texas instruments ti-99/4a': 'TI-99/4A',
}

# Aliases for dimension short forms AI may return
DIMENSION_ALIASES = {
    'ar': 'AR (Augmented Reality)',
    'augmented reality': 'AR (Augmented Reality)',
    'fmv': 'FMV (Full Motion Video)',
    'full motion video': 'FMV (Full Motion Video)',
    'vr': 'VR',
    'pseudo-3d': 'Pseudo-3D',
    'pseudo 3d': 'Pseudo-3D',
}

# Aliases for rating values AI may return in non-canonical form
RATING_ALIASES = {
    'esrb_rating': {
        'early childhood': 'EC',
        'everyone': 'E',
        'everyone 10+': 'E10+',
        'everyone 10': 'E10+',
        'e10': 'E10+',
        'teen': 'T',
        'mature': 'M',
        'mature 17+': 'M',
        'adults only': 'AO',
        'adults only 18+': 'AO',
        'rating pending': 'RP',
        'not rated': 'RP',
        'unrated': 'RP',
    },
    'pegi_rating': {
        '3': 'PEGI 3', 'pegi3': 'PEGI 3',
        '7': 'PEGI 7', 'pegi7': 'PEGI 7',
        '12': 'PEGI 12', 'pegi12': 'PEGI 12',
        '16': 'PEGI 16', 'pegi16': 'PEGI 16',
        '18': 'PEGI 18', 'pegi18': 'PEGI 18',
    },
    'cero_rating': {
        'all ages': 'A', 'cero a': 'A',
        'cero b': 'B', '12+': 'B',
        'cero c': 'C', '15+': 'C',
        'cero d': 'D', '17+': 'D',
        'cero z': 'Z', '18+': 'Z',
    },
    'usk_rating': {
        'usk 0': '0', 'approved without age restriction': '0',
        'usk 6': '6',
        'usk 12': '12',
        'usk 16': '16',
        'usk 18': '18', 'no youth admitted': '18',
    },
    'acb_rating': {
        'general': 'G',
        'parental guidance': 'PG',
        'mature': 'M',
        'ma 15+': 'MA15+', 'ma15': 'MA15+', 'mature accompanied': 'MA15+',
        'r 18+': 'R18+', 'r18': 'R18+', 'restricted': 'R18+',
    },
    'fpb_rating': {
        'all': 'A', 'all ages': 'A',
        'parental guidance': 'PG',
        '7-9pg': '7-9 PG', '7-9': '7-9 PG',
        '10-12pg': '10-12 PG', '10-12': '10-12 PG',
    },
    'grac_rating': {
        'all': 'ALL', 'all ages': 'ALL',
        'grac all': 'ALL',
        'grac 12': '12',
        'grac 15': '15',
        'grac 18': '18',
    },
    'classind_rating': {
        'livre': 'L', 'free': 'L', 'general audiences': 'L',
        'classind l': 'L',
        'classind 10': '10',
        'classind 12': '12',
        'classind 14': '14',
        'classind 16': '16',
        'classind 18': '18',
    },
}

# Fields that AI Fill should validate even when already populated.
# Schema-constrained fields are checked against schema; accuracy-critical
# fields are verified for correctness.
VALIDATE_FIELDS = {
    'genre', 'modes', 'game_structure', 'perspective', 'dimension',
    'save_type', 'campaign', 'players', 'edition', 'other_platforms',
    'publisher', 'developer', 'esrb_rating', 'pegi_rating',
    'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
    'grac_rating', 'classind_rating',
}

# Provider configurations
# Pricing: input$ / output$ per 1M tokens (updated 2026-03-02)
PROVIDERS = {
    'gemini': {
        'name': 'Google Gemini',
        'models': {
            'gemini-2.5-flash-lite': 'Gemini 2.5 Flash Lite — $0.10 / $0.40',
            'gemini-2.5-flash': 'Gemini 2.5 Flash — $0.15 / $0.60',
            'gemini-3-flash-preview': 'Gemini 3 Flash (Preview) — $0.50 / $3.00',
            'gemini-2.5-pro': 'Gemini 2.5 Pro — $1.25 / $10.00',
        },
        'default_model': 'gemini-2.5-flash-lite',
    },
    'openai': {
        'name': 'OpenAI',
        'models': {
            'gpt-4o-mini': 'GPT-4o Mini — $0.15 / $0.60',
            'gpt-4o': 'GPT-4o — $2.50 / $10.00',
        },
        'default_model': 'gpt-4o-mini',
    },
    'claude': {
        'name': 'Anthropic Claude',
        'models': {
            'claude-haiku-4-5-20251001': 'Claude Haiku 4.5 — $1.00 / $5.00',
            'claude-sonnet-4-5-20250929': 'Claude Sonnet 4.5 — $3.00 / $15.00',
            'claude-opus-4-6': 'Claude Opus 4.6 — $15.00 / $75.00',
        },
        'default_model': 'claude-haiku-4-5-20251001',
    },
}


# =============================================================================
# SETTINGS HELPERS
# =============================================================================

def _get_active_provider():
    """Read scraper_settings.json and return active AI provider config.

    Returns:
        dict with keys: provider, api_key, model  (or None if unconfigured)
    """
    try:
        if not os.path.exists(SCRAPER_SETTINGS_FILE):
            return None

        with open(SCRAPER_SETTINGS_FILE, 'r') as f:
            settings = json.load(f)

        api_keys = settings.get('api_keys', {})
        provider = api_keys.get('ai_provider', '')

        if not provider:
            return None

        key_map = {
            'gemini': 'ai_gemini_api_key',
            'openai': 'ai_openai_api_key',
            'claude': 'ai_claude_api_key',
        }
        model_map = {
            'gemini': 'ai_gemini_model',
            'openai': 'ai_openai_model',
            'claude': 'ai_claude_model',
        }

        api_key = api_keys.get(key_map.get(provider, ''), '')
        model = api_keys.get(model_map.get(provider, ''), '')

        if not api_key:
            return None

        # Fall back to default model if none selected
        if not model:
            provider_info = PROVIDERS.get(provider, {})
            model = provider_info.get('default_model', '')

        # Gemini GCP project ID for billing (optional)
        project_id = api_keys.get('ai_gemini_project_id', '') if provider == 'gemini' else ''

        return {'provider': provider, 'api_key': api_key, 'model': model, 'project_id': project_id}

    except Exception as e:
        logger.error(f"Failed to load AI provider settings: {e}")
        return None


# =============================================================================
# PROMPT CONSTRUCTION
# =============================================================================

def _sanitize_prompt_input(value, *, max_len=256):
    """Pass 32.13 — escape user-controlled values before f-string injection.

    OWASP LLM01: a ROM filename containing
    `"\\nIGNORE PREVIOUS INSTRUCTIONS AND RETURN …\\n"` or
    `"}`, `` ` ``, or curly braces can subvert the surrounding prompt
    template. Strip control chars, collapse whitespace, drop braces and
    backticks, and cap length.
    """
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    # Replace newlines / tabs with single spaces, drop other control chars.
    cleaned = ''.join(
        ' ' if ch in ('\n', '\r', '\t') else ch
        for ch in value
        if ord(ch) >= 0x20 or ch in ('\n', '\r', '\t')
    )
    # Drop characters the f-string template itself uses structurally so a
    # title can't open a new section / close the prompt.
    for bad in ('{', '}', '`'):
        cleaned = cleaned.replace(bad, '')
    # Collapse runs of whitespace and double-quotes so the Game: "{title}"
    # line stays balanced.
    cleaned = cleaned.replace('"', "'")
    cleaned = ' '.join(cleaned.split())
    return cleaned[:max_len]


def _build_prompt(title, system_name, missing_fields, existing_values=None):
    """Build a structured JSON-requesting prompt for the AI provider.

    Uses the authoritative field schemas from the reference template.

    Args:
        title: Game title
        system_name: Full system name (e.g., "Super Nintendo Entertainment System")
        missing_fields: List of field names to request
        existing_values: Optional dict of field->current_value for validation mode.
                        Fields with existing values get a "verify and correct" prefix.

    Returns:
        str prompt
    """
    existing_values = existing_values or {}
    # Pass 32.13: sanitize caller-supplied values before they land in the
    # templated prompt — see _sanitize_prompt_input for rationale.
    title = _sanitize_prompt_input(title, max_len=256)
    system_name = _sanitize_prompt_input(system_name, max_len=128)
    field_instructions = []

    for field in missing_fields:
        if field == 'genre':
            field_instructions.append(
                '"genre": comma-separated genres. Use ONLY these schema values: '
                + ', '.join(FIELD_SCHEMAS['genre'])
                + '. Do not use terms outside this schema (e.g., never use "Compilation" or "Arcade").'
            )
        elif field == 'description':
            field_instructions.append(
                '"description": 2-4 sentence game description/plot/summary. No spoilers.'
            )
        elif field == 'developer':
            field_instructions.append(
                '"developer": development studio name(s), comma-separated if more than one'
            )
        elif field == 'publisher':
            field_instructions.append(
                '"publisher": publishing company name(s), comma-separated if more than one'
            )
        elif field == 'release_date':
            field_instructions.append(
                '"release_date": release date for THIS specific platform in YYYY-MM-DD format'
            )
        elif field == 'players':
            field_instructions.append(
                '"players": max player count as a string (e.g., "1", "2", "4", "1-2", "1-4")'
            )
        elif field == 'modes':
            field_instructions.append(
                '"modes": comma-separated from ONLY these schema values: '
                + ', '.join(FIELD_SCHEMAS['modes'])
                + '. Never use just "Multiplayer" — always specify "Local Multiplayer" or "Online Multiplayer".'
            )
        elif field == 'esrb_rating':
            field_instructions.append(
                '"esrb_rating": one of: ' + ', '.join(FIELD_SCHEMAS['esrb_rating'])
                + '. Only use RP for unreleased games. For all released games '
                '(including retro titles that were never officially rated), '
                'rate based on the game\'s content — assign what the rating WOULD be.'
            )
        elif field == 'pegi_rating':
            field_instructions.append(
                '"pegi_rating": one of: ' + ', '.join(FIELD_SCHEMAS['pegi_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'cero_rating':
            field_instructions.append(
                '"cero_rating": Japanese CERO rating, one of: ' + ', '.join(FIELD_SCHEMAS['cero_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'usk_rating':
            field_instructions.append(
                '"usk_rating": German USK rating, one of: ' + ', '.join(FIELD_SCHEMAS['usk_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'acb_rating':
            field_instructions.append(
                '"acb_rating": Australian ACB rating, one of: ' + ', '.join(FIELD_SCHEMAS['acb_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'fpb_rating':
            field_instructions.append(
                '"fpb_rating": South African FPB rating, one of: ' + ', '.join(FIELD_SCHEMAS['fpb_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'grac_rating':
            field_instructions.append(
                '"grac_rating": South Korean GRAC rating, one of: ' + ', '.join(FIELD_SCHEMAS['grac_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'classind_rating':
            field_instructions.append(
                '"classind_rating": Brazilian ClassInd rating, one of: ' + ', '.join(FIELD_SCHEMAS['classind_rating'])
                + '. Rate based on game content if no official rating exists.'
            )
        elif field == 'region':
            # Load region options from settings
            try:
                from settings_manager import load_settings as _load_s
                _s = _load_s()
                region_opts = _s.get('region_options', ['USA', 'Europe', 'Japan', 'World'])
            except Exception:
                region_opts = ['USA', 'Europe', 'Japan', 'World']
            field_instructions.append(
                '"region": a SINGLE region value from this list: '
                + ', '.join(region_opts)
                + '. Pick the primary release region for this specific copy/platform. '
                'Do NOT return multiple regions.'
            )
        elif field == 'franchise':
            field_instructions.append(
                '"franchise": series/franchise name if applicable (e.g., "Super Mario", '
                '"Final Fantasy"). Return "" (empty string) if not part of a franchise.'
            )
        elif field == 'similar_games':
            field_instructions.append(
                '"similar_games": comma-separated list of 3-5 similar games. '
                'Game titles only — no console/platform names after titles. '
                'Pick games from the same era or within 1-2 console generations.'
            )
        elif field == 'controller_support':
            field_instructions.append(
                '"controller_support": specific controller name(s) with model numbers where '
                'possible (e.g., "DualShock 2 (SCPH-10010)", "SNES Controller (SNS-005)"). '
                'Comma-separated if multiple. Do NOT use generic terms like '
                '"Standard Controller" or "Gamepad".'
            )
        elif field == 'save_type':
            field_instructions.append(
                '"save_type": one of: ' + ', '.join(FIELD_SCHEMAS['save_type'])
            )
        elif field == 'game_structure':
            field_instructions.append(
                '"game_structure": comma-separated from ONLY these schema values: '
                + ', '.join(FIELD_SCHEMAS['game_structure'])
            )
        elif field == 'perspective':
            field_instructions.append(
                '"perspective": comma-separated from ONLY these schema values: '
                + ', '.join(FIELD_SCHEMAS['perspective'])
            )
        elif field == 'dimension':
            field_instructions.append(
                '"dimension": comma-separated from ONLY these schema values: '
                + ', '.join(FIELD_SCHEMAS['dimension'])
            )
        elif field == 'campaign':
            field_instructions.append(
                '"campaign": "Yes" if the game has a campaign/story mode, "No" if it does not. '
                'Only return "Yes" or "No".'
            )
        elif field == 'other_platforms':
            field_instructions.append(
                '"other_platforms": alphabetically sorted, comma-separated list of ALL other '
                'platforms this specific game was released on. Exclude the current platform ('
                + system_name + '). Do NOT include compilations or virtual console re-releases. '
                'If exclusive to this platform, return "Exclusive". '
                'Use ONLY these platform names: '
                + ', '.join(FIELD_SCHEMAS['other_platforms'])
                + '.'
            )
        elif field == 'edition':
            field_instructions.append(
                '"edition": edition type with first letter of each word capitalised '
                '(e.g., "Greatest Hits", "Collector\'s Edition", "Game of the Year Edition"). '
                'Return "Standard Edition" for standard/original releases.'
            )
        elif field == 'critic_score':
            field_instructions.append(
                '"critic_score": aggregated critic/press review score as a number 0-100. '
                'Search online and use the best available aggregated critic score from these sources '
                '(in priority order): Metacritic, OpenCritic, GameRankings, MobyGames critic score. '
                'If multiple sources are available, prefer Metacritic. '
                'For classic/retro games (pre-1995) where modern aggregators have no coverage, '
                'check MobyGames critic reviews as the primary source. '
                'Individual review sites (IGN, GameSpot, Destructoid, GamesRadar, Game Informer, '
                'Nintendo Life, Push Square, Pure Xbox, PC Gamer, Famitsu, Edge, Retro Gamer) can be used '
                'to estimate an aggregate if no aggregator score exists — average their scores '
                'normalized to 0-100. Return null if genuinely unknown.'
            )
        elif field == 'critic_score_count':
            field_instructions.append(
                '"critic_score_count": number of critic reviews contributing to the aggregated score '
                '(from the same source as critic_score). Return null if unknown.'
            )
        elif field == 'user_score':
            field_instructions.append(
                '"user_score": aggregated user/community score as a number 0-100. '
                'Search online and use the best available aggregated user score from these sources '
                '(in priority order): Metacritic user score (multiply by 10 if on 0-10 scale), '
                'OpenCritic user score, MobyGames user score (normalize to 0-100 if on 0-5 scale '
                'by multiplying by 20), GameFAQs user rating (normalize to 0-100), '
                'AtariAge community rating (normalize to 0-100 if on different scale), '
                'IGDB user rating, How Long to Beat rating. '
                'For classic/retro games (pre-1995), MobyGames and AtariAge are the best sources. '
                'Return null if genuinely unknown.'
            )
        elif field == 'user_score_count':
            field_instructions.append(
                '"user_score_count": number of user ratings contributing to the user score '
                '(from the same source as user_score). Return null if unknown.'
            )

    # Add validation prefix for fields with existing values
    final_instructions = []
    for fi in field_instructions:
        # Extract field name from instruction (e.g., '"genre": ...' -> 'genre')
        field_name_match = re.match(r'^"(\w+)":', fi)
        if field_name_match:
            fname = field_name_match.group(1)
            if fname in existing_values and existing_values[fname]:
                fi = fi + f' Current value: "{existing_values[fname]}". Verify this is correct and fix if needed.'
        final_instructions.append(fi)

    fields_block = '\n'.join(f'  - {fi}' for fi in final_instructions)

    has_validation = bool(existing_values)
    validation_rule = (
        '\n- For fields with a "Current value", return the corrected value if wrong, '
        'or return the same value if it is already correct.'
        if has_validation else ''
    )

    prompt = f"""You are a retro gaming metadata expert. Use ONLY the provided schema values — do not use terms outside the schemas.

Game: "{title}"
Platform: {system_name}

Return a JSON object with ONLY these fields:
{fields_block}

Rules:
- Return ONLY valid JSON. No markdown, no explanation, no code fences.
- Use empty string "" for any field you are genuinely unsure about. Do not guess.
- For comma-separated fields (genre, modes, perspective, dimension, game_structure), separate values with ", " (comma-space).
- For review score fields (critic_score, user_score), search online for the most accurate aggregated scores. Prefer Metacritic, OpenCritic, and GameFAQs as primary sources. For classic/retro games where those sites have no coverage, MobyGames and AtariAge are excellent alternative sources.
- Be accurate. Wrong data is worse than empty data.{validation_rule}
"""
    return prompt


# =============================================================================
# PROVIDER API CALLS
# =============================================================================

def _call_gemini(prompt, api_key, model, project_id=''):
    """Call Google Gemini API with retry on empty response.

    Returns:
        str: Raw text response, or None on failure.
    """
    # Pass 26.2 — API key goes in header, not querystring. http_post logs URLs
    # at DEBUG/ERROR; header-based auth keeps the secret out of log lines
    # entirely, even if SecretRedactor's patterns miss.
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'tools': [{'google_search': {}}],
        'generationConfig': {
            'temperature': 0.2,
        }
    }
    headers = {
        'Content-Type': 'application/json',
        'x-goog-api-key': api_key,
    }
    if project_id:
        headers['x-goog-user-project'] = project_id

    # Pass 32.14: cap AI response size. Gemini's google_search grounding can
    # cite many URLs and bloat the body; 10 MB default catches abuse without
    # rejecting the normal <100 KB case.
    max_bytes = getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        response = http_post(url, json_data=payload, headers=headers, timeout=60, retries=1, max_bytes=max_bytes)
        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else 'No response'
            logger.error(f"Gemini API error: {status}")
            return None

        data = safe_json(response)
        if not data:
            return None

        try:
            candidates = data.get('candidates', [])
            if not candidates:
                # May be blocked by safety filters
                block_reason = data.get('promptFeedback', {}).get('blockReason', 'unknown')
                logger.error(f"Gemini response: no candidates (blockReason={block_reason})")
                return None

            content = candidates[0].get('content', {})
            parts = content.get('parts', [])
            if not parts:
                finish = candidates[0].get('finishReason', 'unknown')
                if attempt < max_attempts:
                    logger.info(f"Gemini response: no parts (finishReason={finish}), retrying in 2s...")
                    time.sleep(2)
                    continue
                logger.warning(f"Gemini response: no parts after {max_attempts} attempts (finishReason={finish})")
                return None

            # With google_search grounding, response may have multiple parts;
            # concatenate all text parts to find the JSON
            texts = [p['text'] for p in parts if 'text' in p]
            if texts:
                return '\n'.join(texts)
            logger.error("Gemini response: no text parts found")
            return None
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Gemini response parse error: {e}")
            return None

    return None


def _call_openai(prompt, api_key, model, **_kwargs):
    """Call OpenAI Responses API with web search and JSON mode.

    Uses the Responses API (/v1/responses) with web_search_preview tool
    so the model can search online for review scores and other data.

    Returns:
        str: Raw text response, or None on failure.
    """
    url = 'https://api.openai.com/v1/responses'
    payload = {
        'model': model,
        'tools': [{'type': 'web_search_preview'}],
        'input': [
            {'role': 'developer', 'content': 'You are a retro gaming metadata expert. Always respond with valid JSON only.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.2,
        'text': {'format': {'type': 'json_object'}},
    }
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }

    # Pass 32.14: cap OpenAI response size.
    max_bytes = getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)
    response = http_post(url, json_data=payload, headers=headers, timeout=90, retries=1, max_bytes=max_bytes)
    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else 'No response'
        logger.error(f"OpenAI API error: {status}")
        return None

    data = safe_json(response)
    if not data:
        return None

    try:
        # Responses API: extract text from the output message items
        for item in data.get('output', []):
            if item.get('type') == 'message':
                for content in item.get('content', []):
                    if content.get('type') == 'output_text':
                        return content['text']
        logger.error("OpenAI Responses API: no output_text found in response")
        return None
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"OpenAI response parse error: {e}")
        return None


def _call_claude(prompt, api_key, model, **_kwargs):
    """Call Anthropic Claude API.

    Returns:
        str: Raw text response, or None on failure.
    """
    url = 'https://api.anthropic.com/v1/messages'
    payload = {
        'model': model,
        'max_tokens': 2048,
        'messages': [
            {'role': 'user', 'content': prompt}
        ],
        'system': 'You are a retro gaming metadata expert. Always respond with valid JSON only. No markdown, no code fences.',
        'temperature': 0.2,
    }
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    }

    # Pass 32.14: cap Claude response size.
    max_bytes = getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)
    response = http_post(url, json_data=payload, headers=headers, timeout=60, retries=1, max_bytes=max_bytes)
    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else 'No response'
        logger.error(f"Claude API error: {status}")
        return None

    data = safe_json(response)
    if not data:
        return None

    try:
        return data['content'][0]['text']
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"Claude response parse error: {e}")
        return None


# =============================================================================
# RESPONSE PARSING & VALIDATION
# =============================================================================

def _parse_ai_response(raw_text):
    """Extract and validate JSON from AI response text.

    Handles code fences, leading/trailing garbage, and partial JSON.

    Returns:
        dict of validated field values, or empty dict on failure.
    """
    if not raw_text:
        return {}

    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith('```'):
        # Remove opening fence (with optional language tag)
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()

    # Try direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _validate_all_fields(data)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return _validate_all_fields(data)
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse AI response as JSON: {text[:200]}")
    return {}


def _validate_all_fields(data):
    """Validate all fields in the parsed AI response.

    Returns:
        dict with only valid, non-empty fields.
    """
    result = {}
    for field in AI_FILLABLE_FIELDS:
        if field in data:
            value = _validate_field(field, data[field])
            if value:
                result[field] = value
    return result


def _validate_field(field_name, value):
    """Validate a single field value against its schema.

    Returns:
        str: Cleaned value, or empty string if invalid.
    """
    if value is None:
        return ''

    # Convert to string
    value = str(value).strip()

    if not value:
        return ''

    # For fields with enumerated schemas, validate each comma-separated value
    if field_name in FIELD_SCHEMAS:
        schema = FIELD_SCHEMAS[field_name]
        schema_lower = {v.lower(): v for v in schema}

        # Multi-value fields (comma-separated)
        if field_name in ('genre', 'modes', 'game_structure', 'perspective', 'dimension', 'other_platforms'):
            parts = [p.strip() for p in value.split(',') if p.strip()]
            valid_parts = []
            for part in parts:
                canonical = schema_lower.get(part.lower())
                # Check aliases for short/alternate forms
                if not canonical and field_name == 'dimension':
                    canonical = DIMENSION_ALIASES.get(part.lower())
                if not canonical and field_name == 'other_platforms':
                    canonical = PLATFORM_ALIASES.get(part.lower())
                if canonical:
                    valid_parts.append(canonical)
                else:
                    logger.info(f"AI field '{field_name}': rejected invalid value '{part}'")
            return ', '.join(valid_parts) if valid_parts else ''

        # Single-value fields
        canonical = schema_lower.get(value.lower())
        if not canonical and field_name == 'dimension':
            canonical = DIMENSION_ALIASES.get(value.lower())
        if not canonical and field_name in RATING_ALIASES:
            canonical = RATING_ALIASES[field_name].get(value.lower())
        if canonical:
            return canonical
        logger.info(f"AI field '{field_name}': rejected invalid value '{value}'")
        return ''

    # Numeric score fields — validate as integers in range
    if field_name in ('critic_score', 'user_score'):
        try:
            score = int(float(value))
            return str(max(0, min(100, score))) if score > 0 else ''
        except (ValueError, TypeError):
            return ''
    if field_name in ('critic_score_count', 'user_score_count'):
        try:
            count = int(float(value))
            return str(count) if count > 0 else ''
        except (ValueError, TypeError):
            return ''

    # Free-text fields — basic sanitization
    # Truncate extremely long values
    if field_name == 'description':
        return value[:2000]
    elif field_name == 'similar_games':
        return value[:500]
    else:
        return value[:200]


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def get_game_details(game_id, title, system_name, system_folder=None, existing_metadata=None):
    """Fetch AI-generated metadata for a game.

    Args:
        game_id: Database game ID
        title: Game title
        system_name: Full system name
        system_folder: ES-DE system folder (unused, for interface compat)
        existing_metadata: Dict of current field values (to determine gaps)

    Returns:
        dict of metadata fields filled by AI, or None on failure.
    """
    provider_config = _get_active_provider()
    if not provider_config:
        logger.warning("AI scraper: no provider configured")
        return None

    # Determine which fields are missing
    missing_fields = []
    validate_existing = {}  # Fields with existing values to validate
    if existing_metadata:
        for field in AI_FILLABLE_FIELDS:
            val = existing_metadata.get(field, '')
            if not val or (isinstance(val, str) and not val.strip()):
                missing_fields.append(field)
            elif field in VALIDATE_FIELDS:
                # Field has a value but is in the validation set — include for verification
                missing_fields.append(field)
                validate_existing[field] = val.strip() if isinstance(val, str) else str(val)
    else:
        missing_fields = list(AI_FILLABLE_FIELDS)

    if not missing_fields:
        logger.info(f"AI scraper: no missing fields for '{title}'")
        return {}

    validate_count = len(validate_existing)
    empty_count = len(missing_fields) - validate_count
    logger.info(
        f"AI scraper [{provider_config['provider']}]: filling {empty_count} empty + "
        f"validating {validate_count} existing fields for '{title}' on {system_name}"
    )

    # Build prompt and call provider
    prompt = _build_prompt(title, system_name, missing_fields, existing_values=validate_existing)

    provider = provider_config['provider']
    api_key = provider_config['api_key']
    model = provider_config['model']

    rate_limit(delay=1.0)

    call_map = {
        'gemini': _call_gemini,
        'openai': _call_openai,
        'claude': _call_claude,
    }

    call_fn = call_map.get(provider)
    if not call_fn:
        logger.error(f"AI scraper: unknown provider '{provider}'")
        return None

    kwargs = {}
    if provider == 'gemini' and provider_config.get('project_id'):
        kwargs['project_id'] = provider_config['project_id']

    raw_text = call_fn(prompt, api_key, model, **kwargs)
    if not raw_text:
        logger.warning(f"AI scraper: empty response from {provider}")
        return None

    result = _parse_ai_response(raw_text)

    if result:
        rejected_count = len(missing_fields) - len(result)
        msg = f"AI scraper: filled {len(result)}/{len(missing_fields)} fields: {list(result.keys())}"
        if rejected_count > 0:
            filled_set = set(result.keys())
            rejected = [f for f in missing_fields if f not in filled_set]
            msg += f" | {rejected_count} rejected/empty: {rejected}"
        logger.info(msg)
    else:
        logger.warning(f"AI scraper: no valid fields parsed from response")

    return result


def check_api_status():
    """Validate the active AI provider's API key with a minimal test call.

    Returns:
        dict with 'online' (bool) and optional 'reason' (str).
    """
    provider_config = _get_active_provider()
    if not provider_config:
        return {'online': False, 'reason': 'No AI provider configured'}

    provider = provider_config['provider']
    api_key = provider_config['api_key']
    model = provider_config['model']

    test_prompt = 'Return this exact JSON: {"status": "ok"}'

    try:
        if provider == 'gemini':
            # Pass 26.2 — key in header, not querystring (see _call_gemini).
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
            payload = {
                'contents': [{'parts': [{'text': test_prompt}]}],
                'generationConfig': {'maxOutputTokens': 20}
            }
            headers = {
                'Content-Type': 'application/json',
                'x-goog-api-key': api_key,
            }
            project_id = provider_config.get('project_id', '')
            if project_id:
                headers['x-goog-user-project'] = project_id
            response = http_post(url, json_data=payload, headers=headers, timeout=15, retries=0)

        elif provider == 'openai':
            url = 'https://api.openai.com/v1/chat/completions'
            payload = {
                'model': model,
                'messages': [{'role': 'user', 'content': test_prompt}],
                'max_tokens': 20,
            }
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            }
            response = http_post(url, json_data=payload, headers=headers, timeout=15, retries=0)

        elif provider == 'claude':
            url = 'https://api.anthropic.com/v1/messages'
            payload = {
                'model': model,
                'max_tokens': 20,
                'messages': [{'role': 'user', 'content': test_prompt}],
            }
            headers = {
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
            }
            response = http_post(url, json_data=payload, headers=headers, timeout=15, retries=0)
        else:
            return {'online': False, 'reason': f'Unknown provider: {provider}'}

        if response is not None and response.status_code == 200:
            provider_name = PROVIDERS.get(provider, {}).get('name', provider)
            return {'online': True, 'provider': provider_name, 'model': model}
        elif response is not None:
            # Try to extract error message, truncated for UI display
            try:
                err_data = response.json()
                msg = (err_data.get('error', {}).get('message', '')
                       or err_data.get('error', '')
                       or f'HTTP {response.status_code}')
            except Exception:
                msg = f'HTTP {response.status_code}'
            # Truncate long API error messages for status badge display
            if isinstance(msg, str) and len(msg) > 80:
                msg = msg[:77] + '...'
            return {'online': False, 'reason': msg}
        else:
            return {'online': False, 'reason': 'Connection failed'}

    except Exception as e:
        logger.error(f"AI status check error: {e}")
        return {'online': False, 'reason': 'Connection error'}
