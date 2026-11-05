# =============================================================================
# ES-DE GAMELIST SCRAPER
# =============================================================================
# Reads metadata from ES-DE's gamelist.xml files
# This allows importing existing scraped data from ES-DE
# =============================================================================

import os
import defusedxml.ElementTree as ET
import logging
import shutil
import sys

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from config import IMAGE_PATH, STATIC_PATH
from scraper.base_scraper import get_scraper_conn
from scraper.image_dedup import get_existing_screenshot_hashes, keep_screenshot_if_unique
from scraper.match_scorer import sequel_numbers_agree

# Import settings_manager for dynamic path resolution
# (config.py has empty defaults; actual paths live in data/settings.json)
import settings_manager
from services.release_dates import source_date


def _get_rom_path():
    return settings_manager.get_effective_path('rom_path', '')


def esde_date(raw):
    """An ES-DE `<releasedate>` (YYYYMMDDTHHMMSS) as a date, or '' for none.

    ES-DE pads a date it only partly knows, so a first of the month is a month.
    """
    if not raw or len(raw) < 8:
        return ''
    return source_date(f'{raw[:4]}-{raw[4:6]}-{raw[6:8]}', padded_months=True) or ''


def _get_esde_gamelists_path():
    # `~/` as typed in Settings means the home folder (PASS-59-247).
    return os.path.expanduser(settings_manager.get_effective_path('esde_gamelists_path', ''))


def _get_esde_media_path():
    return os.path.expanduser(settings_manager.get_effective_path('esde_downloaded_media_path', ''))

logger = logging.getLogger(__name__)


def _allowed_esde_roots(gamelist_dir=None, esde_base=None, downloaded_media_base=None):
    """Return realpath roots that ES-DE media paths must sit under.

    Lifted to module scope (was a closure inside apply_esde_metadata)
    so the path-traversal guard is directly importable from tests.
    """
    roots = []
    for p in (gamelist_dir, esde_base, downloaded_media_base,
              _get_esde_media_path(), _get_rom_path()):
        if p:
            try:
                roots.append(os.path.realpath(p))
            except OSError:
                continue
    return roots


def _within_allowed_root(candidate, allowed_roots):
    """Return True iff `candidate` resolves under one of `allowed_roots`.

    Lifted to module scope from apply_esde_metadata so the test suite
    can exercise the Pass 25.1 ES-DE path-traversal guard without
    reaching into a nested closure.
    """
    try:
        resolved = os.path.realpath(candidate)
    except OSError:
        return False
    for root in allowed_roots:
        try:
            if os.path.commonpath([resolved, root]) == root:
                return True
        except ValueError:
            continue
    return False


# =============================================================================
# PLATFORM NAME NORMALIZATION
# =============================================================================

PLATFORM_NAME_MAP = {
    # PlayStation family
    'psx': 'PlayStation', 'ps1': 'PlayStation', 'playstation': 'PlayStation',
    'ps2': 'PlayStation 2', 'playstation2': 'PlayStation 2',
    'ps3': 'PlayStation 3', 'playstation3': 'PlayStation 3',
    'ps4': 'PlayStation 4', 'ps5': 'PlayStation 5',
    'psp': 'PSP', 'psvita': 'PS Vita',
    # Nintendo family
    'nes': 'NES', 'famicom': 'NES', 'fds': 'Famicom Disk System',
    'snes': 'SNES', 'sfc': 'SNES', 'superfamicom': 'SNES',
    'n64': 'Nintendo 64', 'gc': 'GameCube', 'gamecube': 'GameCube',
    'wii': 'Wii', 'wiiu': 'Wii U', 'switch': 'Switch',
    'gb': 'Game Boy', 'gbc': 'GBC', 'gba': 'GBA',
    'nds': 'Nintendo DS', 'n3ds': '3DS', '3ds': '3DS',
    'virtualboy': 'Virtual Boy',
    # Sega family
    'mastersystem': 'Master System', 'sms': 'Master System',
    'genesis': 'Genesis', 'megadrive': 'Genesis', 'md': 'Genesis',
    'segacd': 'Sega CD', 'sega32x': '32X', '32x': '32X',
    'saturn': 'Saturn', 'dreamcast': 'Dreamcast', 'dc': 'Dreamcast',
    'gamegear': 'Game Gear', 'gg': 'Game Gear',
    'sg-1000': 'SG-1000', 'sg1000': 'SG-1000',
    # Microsoft family
    'xbox': 'Xbox', 'xbox360': 'Xbox 360', 'xboxone': 'Xbox One',
    # Atari family
    'atari2600': 'Atari 2600', 'atari5200': 'Atari 5200',
    'atari7800': 'Atari 7800', 'atarilynx': 'Atari Lynx',
    'atarijaguar': 'Atari Jaguar', 'atarist': 'Atari ST',
    'atari800': 'Atari 8-bit', 'atari8bit': 'Atari 8-bit',  # Atari 400/800/XL/XE
    'atarixe': 'Atari 8-bit', 'atarixl': 'Atari 8-bit',
    # PC/Computer
    'dos': 'DOS', 'pc': 'PC', 'windows': 'PC',
    'amiga': 'Amiga', 'amiga1200': 'Amiga', 'amiga500': 'Amiga',
    'amigacd32': 'Amiga CD32',
    'c64': 'Commodore 64', 'commodore64': 'Commodore 64',
    'c128': 'Commodore 128', 'vic20': 'VIC-20',
    'amstradcpc': 'Amstrad CPC', 'cpc': 'Amstrad CPC',
    'msx': 'MSX', 'msx2': 'MSX2', 'msxturbor': 'MSX turbo R',
    'zxspectrum': 'ZX Spectrum', 'spectrum': 'ZX Spectrum',
    'bbc': 'BBC Micro', 'bbcmicro': 'BBC Micro',
    'apple2': 'Apple II', 'appleii': 'Apple II',
    'pc88': 'PC-88', 'pc98': 'PC-98',
    'x68000': 'X68000', 'fm7': 'FM-7', 'fmtowns': 'FM Towns',
    'scummvm': 'ScummVM',
    # Neo Geo
    'neogeo': 'Neo Geo', 'neogeoaes': 'Neo Geo', 'neogeocd': 'Neo Geo CD',
    'ngp': 'Neo Geo Pocket', 'ngpc': 'Neo Geo Pocket Color',
    # TurboGrafx / PC Engine
    'tg16': 'TurboGrafx-16', 'pcengine': 'TurboGrafx-16',
    'tg-cd': 'TurboGrafx-CD', 'pcenginecd': 'TurboGrafx-CD',
    'supergrafx': 'SuperGrafx',
    # Others
    '3do': '3DO', 'arcade': 'Arcade', 'mame': 'Arcade',
    'fbneo': 'Arcade', 'fba': 'Arcade', 'naomi': 'Arcade',
    'wonderswan': 'WonderSwan', 'wonderswancolor': 'WonderSwan Color',
    'colecovision': 'ColecoVision', 'coleco': 'ColecoVision',
    'intellivision': 'Intellivision',
    'odyssey2': 'Odyssey 2', 'videopac': 'Odyssey 2',
    'channelf': 'Channel F', 'fairchildchannelf': 'Channel F',
    'vectrex': 'Vectrex',
    'jaguar': 'Atari Jaguar', 'jaguarcd': 'Atari Jaguar CD',
    # Handhelds
    'lynx': 'Atari Lynx',
    'pokemini': 'Pokemon Mini',
    'supervision': 'Supervision', 'gamate': 'Gamate',
}

# Mapping from external scraper names to standardized names
# This handles variations returned by ScreenScraper, IGDB, TGDB, etc.
EXTERNAL_PLATFORM_NAME_MAP = {
    # ScreenScraper variations
    'atari 8bit': 'Atari 8-bit', 'atari8bit': 'Atari 8-bit',
    'atari 800': 'Atari 8-bit', 'atari800': 'Atari 8-bit',
    'atari 400': 'Atari 8-bit', 'atari 130xe': 'Atari 8-bit',
    'atari 65xe': 'Atari 8-bit', 'atari 1200xl': 'Atari 8-bit',
    'atari computers': 'Atari 8-bit',
    # Nintendo
    'nes': 'NES', 'nintendo entertainment system': 'NES',
    'nintendo entertainment system (nes)': 'NES',  # TGDB format
    'famicom': 'NES', 'nintendo famicom': 'NES',
    'famicom disk system': 'Famicom Disk System',
    'super nintendo': 'SNES', 'super famicom': 'SNES', 'super nes': 'SNES',
    'super nintendo (snes)': 'SNES',  # TGDB format
    'super nintendo entertainment system': 'SNES',  # IGDB format
    'nintendo 64': 'Nintendo 64', 'n64': 'Nintendo 64',
    'nintendo gamecube': 'GameCube', 'gamecube': 'GameCube',
    'nintendo wii': 'Wii', 'nintendo wii u': 'Wii U',
    'nintendo switch': 'Switch',
    'nintendo ds': 'Nintendo DS', 'nds': 'Nintendo DS',
    'nintendo 3ds': '3DS', '3ds': '3DS',
    'game boy': 'Game Boy', 'nintendo game boy': 'Game Boy',
    'game boy color': 'GBC', 'nintendo game boy color': 'GBC',
    'game boy advance': 'GBA', 'nintendo game boy advance': 'GBA',
    'virtual boy': 'Virtual Boy', 'nintendo virtual boy': 'Virtual Boy',
    # Sony
    'playstation': 'PlayStation', 'sony playstation': 'PlayStation',
    'playstation 2': 'PlayStation 2', 'ps2': 'PlayStation 2',
    'sony playstation 2': 'PlayStation 2',
    'playstation 3': 'PlayStation 3', 'ps3': 'PlayStation 3',
    'sony playstation 3': 'PlayStation 3',
    'playstation 4': 'PlayStation 4', 'ps4': 'PlayStation 4',
    'sony playstation 4': 'PlayStation 4',
    'playstation 5': 'PlayStation 5', 'ps5': 'PlayStation 5',
    'sony playstation 5': 'PlayStation 5',
    'playstation portable': 'PSP', 'sony playstation portable': 'PSP',
    'playstation vita': 'PS Vita', 'psvita': 'PS Vita',
    'sony playstation vita': 'PS Vita',
    # Sega
    'sega mega drive': 'Genesis', 'mega drive': 'Genesis',
    'sega genesis': 'Genesis',
    'sega mega drive/genesis': 'Genesis',  # IGDB format
    'sega master system': 'Master System',
    'sega master system/mark iii': 'Master System',  # IGDB format
    'sega saturn': 'Saturn', 'sega dreamcast': 'Dreamcast',
    'dreamcast': 'Dreamcast',
    'sega game gear': 'Game Gear', 'game gear': 'Game Gear',
    'sega cd': 'Sega CD',
    'sega 32x': '32X', '32x': '32X',
    'sega sg-1000': 'SG-1000',
    # Microsoft
    'microsoft xbox': 'Xbox', 'xbox': 'Xbox',
    'microsoft xbox 360': 'Xbox 360', 'xbox 360': 'Xbox 360',
    'microsoft xbox one': 'Xbox One', 'xbox one': 'Xbox One',
    # SNK / Neo Geo
    'neo geo': 'Neo Geo', 'neo-geo': 'Neo Geo', 'snk neo geo': 'Neo Geo',
    'neo geo aes': 'Neo Geo',  # IGDB format
    'neo geo cd': 'Neo Geo CD', 'neo-geo cd': 'Neo Geo CD',
    'neo geo pocket': 'Neo Geo Pocket', 'neo geo pocket color': 'Neo Geo Pocket Color',
    # NEC / TurboGrafx
    'turbografx-16': 'TurboGrafx-16', 'turbografx 16': 'TurboGrafx-16',
    'turbografx-16/pc engine': 'TurboGrafx-16',  # IGDB format
    'pc engine': 'TurboGrafx-16', 'nec pc engine': 'TurboGrafx-16',
    'turbografx cd': 'TurboGrafx-CD', 'pc engine cd': 'TurboGrafx-CD',
    'supergrafx': 'SuperGrafx',
    'pc-fx': 'PC-FX',
    # Other consoles
    '3do': '3DO', 'panasonic 3do': '3DO', '3do interactive multiplayer': '3DO',
    'colecovision': 'ColecoVision', 'coleco vision': 'ColecoVision',
    'mattel intellivision': 'Intellivision', 'intellivision': 'Intellivision',
    'vectrex': 'Vectrex', 'gce vectrex': 'Vectrex',
    'wonderswan': 'WonderSwan', 'bandai wonderswan': 'WonderSwan',
    'wonderswan color': 'WonderSwan Color',
    # Computers
    'commodore 64': 'Commodore 64', 'c64': 'Commodore 64',
    'commodore c64/128/max': 'Commodore 64',  # IGDB format
    'amiga': 'Amiga', 'commodore amiga': 'Amiga',
    'amiga cd32': 'Amiga CD32',
    'atari 2600': 'Atari 2600', 'atari vcs': 'Atari 2600',
    'atari 5200': 'Atari 5200', 'atari 7800': 'Atari 7800',
    'atari lynx': 'Atari Lynx', 'atari jaguar': 'Atari Jaguar',
    'atari st': 'Atari ST', 'atari st/ste': 'Atari ST',
    'msx': 'MSX', 'msx2': 'MSX2', 'msx turbo r': 'MSX turbo R',
    'zx spectrum': 'ZX Spectrum', 'sinclair zx spectrum': 'ZX Spectrum',
    'amstrad cpc': 'Amstrad CPC',
    'pc': 'PC', 'dos': 'DOS', 'pc dos': 'DOS', 'ms-dos': 'DOS',
    'windows': 'PC', 'microsoft windows': 'PC',
    'pc-88': 'PC-88', 'pc-98': 'PC-98',
    'x68000': 'X68000', 'sharp x68000': 'X68000',
    'fm towns': 'FM Towns',
    'bbc micro': 'BBC Micro',
    'apple ii': 'Apple II',
    'scummvm': 'ScummVM',
    # Arcade
    'arcade': 'Arcade', 'coin-op': 'Arcade',
}

def normalize_platform_name(folder_name):
    """Convert system folder name to a display-friendly platform name"""
    if not folder_name:
        return 'Unknown'
    # Strip any region suffixes and lowercase for lookup
    clean_name = folder_name.lower().strip()
    return PLATFORM_NAME_MAP.get(clean_name, folder_name.upper())


def normalize_external_platform_name(platform_name):
    """
    Normalize platform names from external scrapers to standard names.
    Use this when processing platforms returned by ScreenScraper, IGDB, TGDB, etc.
    """
    if not platform_name:
        return None
    
    clean_name = platform_name.lower().strip()
    
    # First try exact match in external map
    if clean_name in EXTERNAL_PLATFORM_NAME_MAP:
        return EXTERNAL_PLATFORM_NAME_MAP[clean_name]
    
    # Then try the folder name map
    if clean_name in PLATFORM_NAME_MAP:
        return PLATFORM_NAME_MAP[clean_name]
    
    # Return original with title case if no match
    return platform_name.title()


def resolve_publisher_developer(value, value_type='publisher'):
    """
    Resolve publisher/developer - if numeric ID, try to look up or return None.
    If text, cache it for future lookups.
    
    value_type: 'publisher' or 'developer'
    """
    if not value:
        return None
    
    value = str(value).strip()
    
    # Digits alone can be a real name: 989 Studios is listed as "989".
    return value


def find_gamelist_xml(system_folder):
    """
    Find the gamelist.xml file for a system
    ES-DE stores gamelists in various locations depending on configuration
    """
    # Get user home directory
    home = os.path.expanduser('~')
    
    possible_paths = []
    
    # If custom path is set in config, check it first
    esde_gl_path = _get_esde_gamelists_path()
    rom_path = _get_rom_path()
    if esde_gl_path:
        possible_paths.append(os.path.join(esde_gl_path, system_folder, 'gamelist.xml'))

    # Add other possible paths
    possible_paths.extend([
        # In ROM folder (ES-DE default when "Save gamelists and metadata in ROM directory" is enabled)
        os.path.join(rom_path, system_folder, 'gamelist.xml'),
        os.path.join(rom_path, system_folder, '.gamelist.xml'),
        
        # ES-DE default locations (Linux)
        os.path.join(home, '.es-de', 'gamelists', system_folder, 'gamelist.xml'),
        os.path.join(home, 'ES-DE', 'gamelists', system_folder, 'gamelist.xml'),
        
        # ES-DE Flatpak location
        os.path.join(home, '.var', 'app', 'org.es_de.frontend', 'data', 'ES-DE', 'gamelists', system_folder, 'gamelist.xml'),
        
        # Legacy EmulationStation locations
        os.path.join(home, '.emulationstation', 'gamelists', system_folder, 'gamelist.xml'),
        
        # RetroPie location
        os.path.join(home, 'RetroPie', 'gamelists', system_folder, 'gamelist.xml'),
        
        # Batocera/Recalbox locations
        os.path.join('/userdata', 'system', '.emulationstation', 'gamelists', system_folder, 'gamelist.xml'),
        
        # Windows ES-DE location
        os.path.join(home, 'ES-DE', 'gamelists', system_folder, 'gamelist.xml'),
        os.path.join(home, 'AppData', 'Roaming', 'ES-DE', 'gamelists', system_folder, 'gamelist.xml'),
    ])
    
    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found gamelist.xml at: {path}")
            return path
    
    # Log paths we checked for debugging
    logger.debug(f"No gamelist.xml found for {system_folder}. Checked paths:")
    for path in possible_paths[:5]:  # Log first 5 paths
        logger.debug(f"  - {path}")
    
    return None


def _sanitize_xml(raw_xml):
    """Sanitize common XML issues in gamelist.xml files.

    Handles:
    - <3dbox> tags (digit-prefixed element names are invalid XML)
    - Unescaped '&' characters in text content (e.g. "Tom & Jerry")
    """
    import re
    raw_xml = raw_xml.replace('<3dbox>', '<_3dbox>').replace('</3dbox>', '</_3dbox>')
    # Fix unescaped '&' that aren't already part of an entity (&amp; &lt; &gt; &quot; &apos; &#..;)
    raw_xml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', raw_xml)
    return raw_xml


# Parsed gamelists keyed on path -> ((mtime_ns, size), games). A bulk scrape
# searches ES-DE once per game, and each search would otherwise re-read the
# whole file (PASS-59-136).
_gamelist_cache = {}


def parse_gamelist_xml(xml_path):
    """
    Parse a gamelist.xml file and return list of game entries.
    The parse is reused until the file's modified time or size changes.
    """
    try:
        st = os.stat(xml_path)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    cached = _gamelist_cache.get(xml_path)
    if stamp and cached and cached[0] == stamp:
        return list(cached[1])
    games = _read_gamelist_xml(xml_path)
    if stamp and games:
        _gamelist_cache[xml_path] = (stamp, games)
    return list(games)


def _read_gamelist_xml(xml_path):
    games = []

    try:
        # ES-DE uses <3dbox> tags which violate XML spec (element names can't
        # start with a digit).  Pre-process the raw text so the standard parser
        # can handle it, then map the sanitised name back to '3dbox' in results.
        with open(xml_path, 'r', encoding='utf-8') as f:
            raw_xml = f.read()
        raw_xml = _sanitize_xml(raw_xml)
        root = ET.fromstring(raw_xml)

        for game_elem in root.findall('game'):
            game = {}

            # Required fields
            path_elem = game_elem.find('path')
            if path_elem is not None:
                game['path'] = path_elem.text
            else:
                continue  # Skip if no path

            # Optional fields - include all ES-DE media types
            # Note: '3dbox' is renamed to '_3dbox' during pre-processing above
            fields = [
                'name', 'desc', 'rating', 'releasedate',
                'developer', 'publisher', 'genre', 'players',
                'favorite', 'hidden', 'kidgame', 'playcount', 'lastplayed',
                # Media fields
                'image', 'thumbnail', 'video', 'marquee',
                'screenshot', 'titlescreen', 'cover', 'boxback',
                '_3dbox', 'fanart', 'manual', 'physicalmedia', 'miximage'
            ]

            for field in fields:
                elem = game_elem.find(field)
                if elem is not None and elem.text:
                    # Map sanitised name back to original ES-DE key
                    key = '3dbox' if field == '_3dbox' else field
                    game[key] = elem.text

            games.append(game)

        logger.info(f"Parsed {len(games)} games from gamelist.xml")
        return games

    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        return []
    except Exception as e:
        logger.error(f"Error parsing gamelist.xml: {e}")
        return []


def extract_region_from_filename(filename):
    """Extract region from ROM filename using common patterns"""
    import re
    
    region_patterns = {
        r'\(USA\)': 'USA',
        r'\(US\)': 'USA', 
        r'\(U\)': 'USA',
        r'\(Europe\)': 'Europe',
        r'\(EU\)': 'Europe',
        r'\(E\)': 'Europe',
        r'\(Japan\)': 'Japan',
        r'\(JP\)': 'Japan',
        r'\(J\)': 'Japan',
        r'\(World\)': 'World',
        r'\(W\)': 'World',
        r'\((?:Fr|France)\)': 'France',
        r'\((?:De|Germany)\)': 'Germany',
        r'\((?:Es|Spain)\)': 'Spain',
        r'\((?:It|Italy)\)': 'Italy',
        r'\((?:Br|Brazil)\)': 'Brazil',
        r'\((?:K|Korea)\)': 'Korea',
        r'\((?:Ch|China)\)': 'China',
        r'\(Asia\)': 'Asia',
        r'\(PAL\)': 'PAL',
        r'\(NTSC\)': 'NTSC',
        r'\(USA, Europe\)': 'USA/Europe',
        r'\(Japan, USA\)': 'Japan/USA',
        r'\(JU\)': 'Japan/USA',
        r'\(UE\)': 'USA/Europe',
    }
    
    for pattern, region in region_patterns.items():
        if re.search(pattern, filename, re.IGNORECASE):
            return region
    
    return None


def derive_game_modes(players_str):
    """Derive canonical game modes from an ES-DE players string ("1-4").

    Delegates to services.normalization so the three copies of this
    derivation cannot diverge again; an unknown count keeps this function's
    existing 'Single-Player' contract (Pass 59.29).
    """
    from services.normalization import modes_from_player_count
    return modes_from_player_count(players_str) or 'Single-Player'


def search_esde_games(title, system_folder, limit=10):
    """
    Search for a game in ES-DE's gamelist.xml
    Returns list of matching games with their metadata
    """
    xml_path = find_gamelist_xml(system_folder)
    
    if not xml_path:
        logger.debug(f"No gamelist.xml found for {system_folder}")
        return []
    
    games = parse_gamelist_xml(xml_path)
    
    if not games:
        return []
    
    # Search for matching games
    title_lower = title.lower()
    # Normalize title - replace various separators with space for comparison
    from scraper.base_scraper import normalize_roman_numerals
    title_normalized = title_lower.replace(':', ' ').replace('-', ' ').replace('  ', ' ').strip()
    title_normalized = normalize_roman_numerals(title_normalized)
    title_words = set(title_normalized.split())
    results = []
    
    for game in games:
        game_name = game.get('name', '')
        game_path = game.get('path', '')

        if not sequel_numbers_agree(game_name, title):
            continue
        
        # Get filename from path for matching
        filename = os.path.basename(game_path) if game_path else ''
        filename_no_ext = os.path.splitext(filename)[0]
        
        # Normalize game name for comparison
        game_name_lower = game_name.lower()
        game_name_normalized = game_name_lower.replace(':', ' ').replace('-', ' ').replace('  ', ' ').strip()
        game_name_normalized = normalize_roman_numerals(game_name_normalized)
        game_words = set(game_name_normalized.split())
        
        # Calculate match score
        score = 0
        
        # Exact name match (highest priority)
        if game_name_lower == title_lower or game_name_normalized == title_normalized:
            score += 200
        else:
            # Check if search contains game name (partial match - e.g., searching "AC IV Black Flag", find "AC IV Black Flag")
            if title_lower in game_name_lower or title_normalized in game_name_normalized:
                score += 150
            # Check if game name contains search (e.g., searching "Zelda Ocarina", find "Legend of Zelda Ocarina of Time")
            elif game_name_lower in title_lower or game_name_normalized in title_normalized:
                # Penalize short matches - "Assassin's Creed" shouldn't rank high when searching "Assassin's Creed IV: Black Flag"
                # Calculate length ratio: how much of the search term does the game name cover?
                length_ratio = len(game_name_normalized) / len(title_normalized) if title_normalized else 0
                # Only give significant score if the game name is at least 70% the length of the search
                if length_ratio >= 0.7:
                    score += int(100 * length_ratio)
                else:
                    # Short partial match - low score
                    score += int(30 * length_ratio)
        
        # Word matching with similarity calculation
        if game_words and title_words:
            common_words = title_words & game_words
            # Calculate Jaccard similarity: intersection / union
            union_words = title_words | game_words
            word_similarity = len(common_words) / len(union_words) if union_words else 0
            
            # Bonus for word overlap - heavily favor high similarity
            if word_similarity >= 0.8:
                score += 80
            elif word_similarity >= 0.6:
                score += 60
            elif word_similarity >= 0.4:
                score += 40
            elif word_similarity >= 0.2:
                score += 20
            elif common_words:
                score += 10
        
        # Filename matching
        if filename_no_ext.lower() == title_lower:
            score += 80
        elif title_lower in filename_no_ext.lower():
            score += 30
        
        if score > 0:
            # Format release date
            release_date = esde_date(game.get('releasedate'))
            
            # Extract region from filename
            region = extract_region_from_filename(filename)
            
            # Derive game modes from players
            players = game.get('players', '')
            modes = derive_game_modes(players)
            
            results.append({
                'id': game_path,  # Use path as ID
                'name': game_name,
                'source': 'esde',
                'scraper': 'esde',
                'score': score,
                'release_date': release_date,
                'developer': game.get('developer', ''),
                'publisher': game.get('publisher', ''),
                'genre': game.get('genre', ''),
                'players': players,
                'modes': modes,
                'region': region,
                'description': game.get('desc', ''),
                'image_path': game.get('image', ''),
                'screenshot_path': game.get('screenshot', ''),
                'system_folder': system_folder,
                'platform': normalize_platform_name(system_folder),
                'platform_match': True,  # ES-DE results are always from the correct system
                'matched_platform': normalize_platform_name(system_folder),
                'esde_data': game
            })
    
    # Sort by score and return top results
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:limit]


def fetch_esde_game_details(game_path, system_folder=None):
    """
    Fetch full game details from ES-DE gamelist.xml
    game_path is the path element from the XML (can be relative like ./game.chd)
    """
    logger.info(f"ES-DE fetch_game_details called with path: {game_path}, folder: {system_folder}")
    
    if not system_folder:
        logger.error("Cannot determine system folder for ES-DE lookup - system_folder is required")
        return None
    
    xml_path = find_gamelist_xml(system_folder)
    if not xml_path:
        logger.error(f"No gamelist.xml found for system: {system_folder}")
        return None
    
    logger.info(f"Found gamelist.xml at: {xml_path}")
    games = parse_gamelist_xml(xml_path)
    logger.info(f"Parsed {len(games)} games from gamelist.xml")
    
    # URL-decode the game_path in case it was encoded
    from urllib.parse import unquote
    decoded_game_path = unquote(game_path)
    
    logger.info(f"Looking for path: {game_path}")
    logger.info(f"Decoded path: {decoded_game_path}")
    
    # Log first few stored paths for debugging
    logger.info("Sample stored paths from gamelist:")
    for i, g in enumerate(games[:5]):
        logger.info(f"  [{i}] {g.get('path', 'NO PATH')}")
    
    # Try to match the game by path. A full-path match wins over a bare
    # filename match: games kept in their own folders can share a filename
    # ("./Game A/disc1.chd", "./Game B/disc1.chd"), and returning the first
    # filename hit picked whichever came first in the gamelist.
    search_normalized = decoded_game_path.replace('./', '').strip()
    search_filename = os.path.basename(decoded_game_path)
    match = None
    filename_match = None
    for game in games:
        stored_path = game.get('path') or ''
        stored_normalized = stored_path.replace('./', '').strip()
        if (stored_path == decoded_game_path
                or stored_normalized.lower() == search_normalized.lower()):
            logger.info(f"Found path match: {decoded_game_path}")
            match = game
            break
        if filename_match is None and os.path.basename(stored_path) == search_filename:
            filename_match = game
    if match is None and filename_match is not None:
        logger.info(f"Found match by filename: {search_filename}")
        match = filename_match

    if match is not None:
        game = match
        release_date = esde_date(game.get('releasedate'))

        return {
            'name': game.get('name', ''),
            'description': game.get('desc', ''),
            'developer': game.get('developer', ''),
            'publisher': game.get('publisher', ''),
            'genre': game.get('genre', ''),
            'players': game.get('players', ''),
            'release_date': release_date,
            'rating': game.get('rating', ''),
            'image_path': game.get('image', ''),
            'screenshot_path': game.get('screenshot', ''),
            'video_path': game.get('video', ''),
            'esde_data': game
        }

    # Not an error: a game often has no row, and every caller handles None.
    logger.info(f"No matching game found for path: {game_path} (decoded: {decoded_game_path}) in {system_folder}")
    return None


def _find_esde_media_base(system_folder, esde_gl_path, esde_base):
    """The first existing downloaded_media folder for a system, or None."""
    possible_media_bases = []
    # Try explicit config setting first
    esde_media = _get_esde_media_path()
    if esde_media:
        possible_media_bases.append(os.path.join(esde_media, system_folder))

    # Try multiple possible locations for downloaded_media
    if esde_base:
        # Standard: gamelists and downloaded_media are siblings
        possible_media_bases.append(os.path.join(esde_base, 'downloaded_media', system_folder))
        # In case esde_gl_path is the ES-DE root
        possible_media_bases.append(os.path.join(esde_gl_path, 'downloaded_media', system_folder))
        # AppImage location
        possible_media_bases.append(os.path.join(esde_base, 'ES-DE', 'downloaded_media', system_folder))
        # Check parent of parent (if gamelists is deep)
        parent_of_base = os.path.dirname(esde_base)
        possible_media_bases.append(os.path.join(parent_of_base, 'downloaded_media', system_folder))

    # Also check common ES-DE locations
    home = os.path.expanduser('~')
    possible_media_bases.extend([
        os.path.join(home, '.es-de', 'downloaded_media', system_folder),
        os.path.join(home, 'ES-DE', 'downloaded_media', system_folder),
        os.path.join(home, '.var', 'app', 'org.es_de.frontend', 'data', 'ES-DE', 'downloaded_media', system_folder),
    ])

    for path in possible_media_bases:
        if os.path.exists(path):
            logger.info(f"  Found downloaded_media at: {path}")
            return path

    logger.warning(f"  Could not find downloaded_media folder for {system_folder}")
    logger.warning(f"  Tried: {possible_media_bases[:3]}...")  # Log first 3 attempts
    return None


def _media_names(rom_path, esde_data):
    """The names ES-DE may have filed this game's media under, best first.

    A folder ROM's media keeps the whole folder name ("Game (USA).PS3.png"), a
    file's drops its extension. The game's own ROM comes before a row chosen
    under another file name, whose media is then the row's.
    """
    names = []
    row_path = (esde_data.get('path') or '').rstrip('/')
    for path in ((rom_path or '').rstrip('/'), row_path):
        filename = os.path.basename(path)
        if filename:
            names += [filename, os.path.splitext(filename)[0]]
    return list(dict.fromkeys(names))


# field, gamelist tag, downloaded_media folder, destination folder and file
# stem for a gamelist tag's copy and a folder's copy. `boxart` is only ever
# 'cover': ES-DE's 'image' and 'miximage' are often screenshots, not box art.
_ESDE_SINGLE_MEDIA = (
    ('boxart', 'cover', 'covers', 'boxart', 'esde_cover', 'esde_covers'),
    ('boxart_3d', '3dbox', '3dboxes', 'boxart_3d', 'esde_3dbox', 'esde_3dboxes'),
    ('fanart', 'fanart', 'fanart', 'fanart', 'esde_fanart', 'esde_fanart'),
    ('game_logo', 'marquee', 'marquees', 'game_logos', 'esde_logo', 'esde_logos'),
    ('boxart_back', 'backcover', 'backcovers', 'boxart_back', 'esde_back', 'esde_backs'),
    ('video', 'video', 'videos', 'videos', 'esde', 'esde'),
    ('manual', 'manual', 'manuals', 'manuals', 'esde', 'esde'),
)
_ESDE_SCREENSHOTS = (
    ('screenshot', 'screenshots', 'esde_ss'),
    ('titlescreen', 'titlescreens', 'esde_ts'),
)


def copy_esde_media(db_game_id, game_data, system_folder=None, existing=None,
                    force_overwrite=False):
    """Copy one game's ES-DE media into RetroDB's folders; writes no column.

    `existing` maps a media field to its current value. A field that has one
    is left alone, whatever mode this is, so a file another source just
    downloaded is never replaced or deleted. Screenshots are appended to
    `existing['screenshots']`, skipping any that look like one already there.

    `force_overwrite` (Full Re-scrape) deletes the row's old box art once ES-DE
    has really supplied a replacement.

    Returns the names copied in this run only: {field: filename} for single
    media, and {'screenshots': [new names]} when any were added.
    """
    existing = existing or {}
    copied = {}
    conn = None
    try:
        conn = get_scraper_conn()
        row = conn.execute("""
            SELECT g.rom_path, s.folder, g.boxart, g.boxart_3d
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (db_game_id,)).fetchone()
        conn.close()
        conn = None
        if not row:
            logger.error(f"Game {db_game_id} not found")
            return copied

        rom_path, sys_folder, db_boxart, db_boxart_3d = tuple(row)
        system_folder = system_folder or sys_folder
        esde_data = game_data.get('esde_data', game_data)
        names = _media_names(rom_path, esde_data)

        # esde_gl_path could be:
        #   /path/to/ES-DE/gamelists  -> downloaded_media is /path/to/ES-DE/downloaded_media
        #   /path/to/gamelists -> downloaded_media could be /path/to/downloaded_media
        esde_gl_path = _get_esde_gamelists_path()
        esde_base = os.path.dirname(esde_gl_path) if esde_gl_path else None
        gamelist_dir = os.path.join(esde_gl_path, system_folder) if esde_gl_path else None
        downloaded_media_base = _find_esde_media_base(system_folder, esde_gl_path, esde_base)
        logger.info(f"Copying ES-DE media for game {db_game_id}: names {names}, "
                    f"from {downloaded_media_base}")

        def find_media_by_rom_name(media_type):
            """Find media file in ES-DE downloaded_media/{system}/{media_type}/"""
            if not downloaded_media_base:
                return None
            media_folder = os.path.join(downloaded_media_base, media_type)
            if not os.path.exists(media_folder):
                logger.debug(f"  Media folder not found: {media_folder}")
                return None
            for name in names:
                for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.mkv', '.avi', '.webm', '.pdf']:
                    media_path = os.path.join(media_folder, name + ext)
                    if os.path.exists(media_path):
                        logger.info(f"  Found {media_type}: {os.path.basename(media_path)}")
                        return media_path
            logger.debug(f"  No {media_type} found for: {names}")
            return None

        # Helper function to resolve ES-DE media paths from gamelist.xml.
        #
        # Pass 25.1 — path-traversal guard. Earlier versions accepted any
        # absolute `/`-prefixed path verbatim, so a crafted gamelist.xml
        # entry `<image>/etc/passwd</image>` would happily return that path
        # and the outer `copy_media()` would then `shutil.copy2` it into
        # `IMAGE_PATH`. We now verify the resolved path sits under an
        # allowlist of known ES-DE / ROM roots via `os.path.commonpath`,
        # which handles `..` segments and symlinks-as-components correctly.
        def _check_allowed(candidate):
            roots = _allowed_esde_roots(gamelist_dir, esde_base, downloaded_media_base)
            return _within_allowed_root(candidate, roots)

        def resolve_media_path(media_path):
            if not media_path:
                return None

            if media_path.startswith('/'):
                if os.path.exists(media_path) and _check_allowed(media_path):
                    return media_path
                if os.path.exists(media_path):
                    logger.warning(
                        f"  Rejected ES-DE media path outside allowed roots: {media_path}"
                    )
                return None

            if media_path.startswith('./') or media_path.startswith('~'):
                media_path = media_path.lstrip('./')

            # Try relative to gamelist directory
            possible_bases = []
            if gamelist_dir:
                possible_bases.append(gamelist_dir)
            if esde_base:
                possible_bases.append(os.path.join(esde_base, 'downloaded_media', system_folder))
                possible_bases.append(esde_base)
            possible_bases.append(os.path.join(_get_rom_path(), system_folder))

            for base in possible_bases:
                full_path = os.path.join(base, media_path)
                if os.path.exists(full_path) and _check_allowed(full_path):
                    logger.info(f"  Found media at: {full_path}")
                    return full_path

            return None

        def copy_media(src_path, dest_folder, stem):
            ext = os.path.splitext(src_path)[1].lower()
            filename = f"{db_game_id}_{stem}{ext}"
            root = STATIC_PATH if dest_folder == 'videos' else IMAGE_PATH
            dest_dir = os.path.join(root, dest_folder)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)
            # The caps a download has, so a stray huge file is not copied
            # (PASS-59-247): videos and manuals the upload cap, pictures the
            # scraper's download cap.
            cap = (getattr(config, 'MAX_VIDEO_SIZE', 500 * 1024 * 1024)
                   if dest_folder in ('videos', 'manuals')
                   else getattr(config, 'MAX_MEDIA_DOWNLOAD_BYTES', 50 * 1024 * 1024))
            try:
                if os.path.getsize(src_path) > cap:
                    logger.warning(f"  Not copying {dest_folder}: {src_path} is over {cap} bytes")
                    return None
                shutil.copy2(src_path, dest_path)
                # Standardize image size for supported types
                if dest_folder in ('boxart', 'screenshots', 'boxart_3d', 'boxart_back'):
                    try:
                        from services.image_utils import standardize_downloaded_image
                        standardize_downloaded_image(dest_path, dest_folder)
                    except Exception:
                        pass
                logger.info(f"  Copied to {dest_folder}: {filename}")
                return filename
            except Exception as e:
                logger.error(f"  Failed to copy {dest_folder}: {e}")
                return None

        for field, tag, media_type, dest_folder, tag_stem, folder_stem in _ESDE_SINGLE_MEDIA:
            if existing.get(field):
                logger.info(f"  Skipping {field} import - already has: {existing[field]}")
                continue
            filename = None
            tag_src = resolve_media_path(esde_data.get(tag, ''))
            if tag_src:
                filename = copy_media(tag_src, dest_folder, tag_stem)
            if not filename:
                folder_src = find_media_by_rom_name(media_type)
                if folder_src:
                    filename = copy_media(folder_src, dest_folder, folder_stem)
            if filename:
                copied[field] = filename

        # Old box art goes only once its replacement is really here.
        if force_overwrite:
            for field, old in (('boxart', db_boxart), ('boxart_3d', db_boxart_3d)):
                if old and copied.get(field) and copied[field] != old:
                    old_path = os.path.join(IMAGE_PATH, field, old)
                    if os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                            logger.info(f"  Deleted old {field} (replaced): {old}")
                        except OSError as e:
                            logger.warning(f"  Could not delete old {field}: {e}")

        # Screenshots: always appended, never replaced.
        listed = [s.strip() for s in (existing.get('screenshots') or '').split(',') if s.strip()]
        hashes = get_existing_screenshot_hashes(listed, db_game_id)
        new_screenshots = []
        for tag, media_type, stem in _ESDE_SCREENSHOTS:
            src = resolve_media_path(esde_data.get(tag, '')) or find_media_by_rom_name(media_type)
            if not src:
                continue
            ext = os.path.splitext(src)[1].lower()
            if f"{db_game_id}_{stem}{ext}" in listed:
                continue
            filename = copy_media(src, 'screenshots', stem)
            if filename and keep_screenshot_if_unique(
                    os.path.join(IMAGE_PATH, 'screenshots', filename),
                    filename, hashes, 'ES-DE'):
                new_screenshots.append(filename)
        if new_screenshots:
            logger.info(f"  Added {len(new_screenshots)} new screenshots")
            copied['screenshots'] = new_screenshots

    except Exception as e:
        logger.error(f"Error copying ES-DE media: {e}")
    finally:
        if conn:
            conn.close()
    return copied


def apply_esde_metadata(db_game_id, game_data, system_folder=None):
    """Apply ES-DE data straight to a game's row: the single-source route.

    Fill-only for media (a field that has a value keeps it); text from ES-DE
    replaces text it has a value for. A hybrid scrape does not come here: it
    merges through hybrid_scraper._merge_esde.
    """
    conn = None
    try:
        conn = get_scraper_conn()
        c = conn.cursor()

        c.execute("""
            SELECT g.rom_path, g.boxart, g.boxart_3d, g.screenshots, g.fanart, g.video, g.manual,
                   g.game_logo, g.boxart_back
            FROM games g
            WHERE g.id = ?
        """, (db_game_id,))
        result = c.fetchone()

        if not result:
            logger.error(f"Game {db_game_id} not found")
            return False

        rom_path, *media = tuple(result)
        existing = dict(zip(('boxart', 'boxart_3d', 'screenshots', 'fanart', 'video', 'manual',
                             'game_logo', 'boxart_back'), media))
        rom_filename = os.path.basename((rom_path or '').rstrip('/'))
        copied = copy_esde_media(db_game_id, game_data, system_folder, existing)
        new_screenshots = copied.get('screenshots')
        screenshots_str = None
        if new_screenshots:
            old = [s.strip() for s in (existing['screenshots'] or '').split(',') if s.strip()]
            screenshots_str = ','.join(old + new_screenshots)

        # Prepare metadata
        esde_data = game_data.get('esde_data', game_data)

        name = esde_data.get('name', '') or game_data.get('name', '')
        description = esde_data.get('desc', '') or game_data.get('description', '')

        # Resolve publisher/developer - skip numeric IDs
        raw_developer = esde_data.get('developer', '') or game_data.get('developer', '')
        raw_publisher = esde_data.get('publisher', '') or game_data.get('publisher', '')
        developer = resolve_publisher_developer(raw_developer, 'developer')
        publisher = resolve_publisher_developer(raw_publisher, 'publisher')

        # Normalize genre to canonical hyphenated forms and players to the max
        # int — consistent with the IGDB/TGDB apply paths. Without this, ES-DE
        # gamelist genres ("Shoot 'Em Up") fragment the genre filter and a
        # players range ("1-4") lands as a string in the INTEGER column.
        from services.normalization import normalize_genre
        from services.game_utils import normalize_players_value
        genre = normalize_genre(esde_data.get('genre', '') or game_data.get('genre', ''))
        # No default: a gamelist row without <players> must leave the column
        # alone. A '1' default wrote players=1 / modes='Single-Player' through
        # COALESCE over curated values on every ES-DE import (Pass 40.6 class).
        players = normalize_players_value(esde_data.get('players') or game_data.get('players'))

        # Format release date
        release_date = (esde_date(esde_data.get('releasedate'))
                        or source_date(game_data.get('release_date'), padded_months=True) or '')

        logger.info(f"  Title: {name}")
        logger.info(f"  Developer: {developer}")
        logger.info(f"  Publisher: {publisher}")

        # Extract region from ROM filename
        region = extract_region_from_filename(rom_filename)

        # Derive game modes from players (only when the gamelist gave a count)
        from services.normalization import modes_from_player_count
        modes = modes_from_player_count(esde_data.get('players') or game_data.get('players')) or None

        # Pass 48.3 — only flip `scraped = 1` when ES-DE actually filled at least
        # one metadata/media field. `region` is excluded from the test: it's
        # derived from the ROM filename, not from ES-DE, so it's always present
        # and would make the gate trivially true. Without this gate a game that
        # ES-DE has no data for is marked scraped and silently dropped from later
        # `WHERE scraped = 0` bulk passes. COALESCE(?, scraped) keeps the prior
        # flag (0) when nothing was filled.
        any_field_filled = any((
            name, publisher, developer, release_date, genre, players, modes,
            description, *copied.values(),
        ))

        # Update database - use COALESCE to preserve existing data if new data is empty
        c.execute("""
            UPDATE games SET
                title = CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END,
                publisher = COALESCE(?, publisher),
                developer = COALESCE(?, developer),
                release_date = COALESCE(?, release_date),
                genre = COALESCE(?, genre),
                players = COALESCE(?, players),
                modes = COALESCE(?, modes),
                description = COALESCE(?, description),
                boxart = COALESCE(?, boxart),
                boxart_3d = COALESCE(?, boxart_3d),
                screenshots = COALESCE(?, screenshots),
                fanart = COALESCE(?, fanart),
                video = COALESCE(?, video),
                manual = COALESCE(?, manual),
                game_logo = COALESCE(?, game_logo),
                boxart_back = COALESCE(?, boxart_back),
                region = COALESCE(?, region),
                scraped = COALESCE(?, scraped)
            WHERE id = ?
        """, (
            name if name else None,
            publisher if publisher else None,
            developer if developer else None,
            release_date if release_date else None,
            genre if genre else None,
            players if players else None,
            modes if modes else None,
            description if description else None,
            copied.get('boxart'),
            copied.get('boxart_3d'),
            screenshots_str,
            copied.get('fanart'),
            copied.get('video'),
            copied.get('manual'),
            copied.get('game_logo'),
            copied.get('boxart_back'),
            region,
            1 if any_field_filled else None,
            db_game_id
        ))

        conn.commit()

        logger.info(f"Applied ES-DE metadata to game {db_game_id}")
        return True

    except Exception as e:
        logger.error(f"Error applying ES-DE metadata: {e}")
        return False
    finally:
        if conn:
            conn.close()


def import_system_logos():
    """
    Import system logos from ES-DE installation
    ES-DE stores system images in the themes folder
    Supports: png, webp, jpg, jpeg, svg
    """
    import shutil
    
    # Supported image extensions (in order of preference)
    SUPPORTED_EXTENSIONS = ['.png', '.webp', '.jpg', '.jpeg', '.svg']
    
    # Get ES-DE base path from the gamelists path
    esde_gl_path = _get_esde_gamelists_path()
    esde_base = os.path.dirname(esde_gl_path) if esde_gl_path else None
    
    if not esde_base:
        logger.warning("ESDE_GAMELISTS_PATH not set, cannot import system logos")
        return 0
    
    # Common ES-DE theme locations for system logos
    theme_paths = [
        os.path.join(esde_base, 'themes'),
        os.path.join(esde_base, 'downloaded_media', 'logos'),
        os.path.join(esde_base, '..', 'themes'),
    ]
    
    # Also check for downloaded_media which has system logos
    downloaded_media = os.path.join(esde_base, 'downloaded_media')
    
    dest_dir = os.path.join(IMAGE_PATH, 'systems')
    os.makedirs(dest_dir, exist_ok=True)
    
    imported = 0
    
    # Try to find system logos in downloaded_media (per-system folders)
    if os.path.exists(downloaded_media):
        for system_folder in os.listdir(downloaded_media):
            system_media_path = os.path.join(downloaded_media, system_folder)
            if not os.path.isdir(system_media_path):
                continue
            
            # Look for system logo images with multiple extensions
            logo_found = False
            for ext in SUPPORTED_EXTENSIONS:
                possible_logo_names = [
                    f'logo{ext}', f'system{ext}', f'controller{ext}',
                    os.path.join('..', '..', 'themes', 'system', f'{system_folder}{ext}'),
                ]
                
                for logo_name in possible_logo_names:
                    logo_path = os.path.join(system_media_path, logo_name)
                    if os.path.exists(logo_path):
                        dest_path = os.path.join(dest_dir, f'{system_folder}{ext}')
                        if not os.path.exists(dest_path):
                            try:
                                shutil.copy2(logo_path, dest_path)
                                logger.info(f"Imported logo for {system_folder} ({ext})")
                                imported += 1
                            except Exception as e:
                                logger.warning(f"Failed to copy logo for {system_folder}: {e}")
                        logo_found = True
                        break
                if logo_found:
                    break
    
    # Also check themes for system logos
    for theme_base in theme_paths:
        if not os.path.exists(theme_base):
            continue
        
        # Walk through theme folders looking for system images
        for root, dirs, files in os.walk(theme_base):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in SUPPORTED_EXTENSIONS:
                    # A logo is named for its system (nes.svg), or sits in the
                    # system's own folder (nes/logo.svg). A part of a word is no
                    # match: "gb" is inside "background_gbstyle".
                    stem = os.path.splitext(file)[0].lower()
                    folder = os.path.basename(root).lower()
                    for system in ['nes', 'snes', 'n64', 'gb', 'gba', 'gbc', 'nds', 'psx', 'ps2', 
                                   'genesis', 'megadrive', 'dreamcast', 'saturn', 'gamegear',
                                   'atari2600', 'atari7800', 'mame', 'arcade', 'neogeo']:
                        if stem == system or (folder == system and stem in ('logo', 'system')):
                            src_path = os.path.join(root, file)
                            dest_path = os.path.join(dest_dir, f'{system}{file_ext}')
                            if not os.path.exists(dest_path):
                                try:
                                    shutil.copy2(src_path, dest_path)
                                    logger.info(f"Imported logo for {system} from theme ({file_ext})")
                                    imported += 1
                                except Exception as e:
                                    logger.warning(f"Failed to copy theme logo: {e}")
                            break
    
    logger.info(f"Imported {imported} system logos from ES-DE")
    return imported


# Test function
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Test search
    results = search_esde_games("Super Mario", "n64")
    for r in results:
        print(f"Found: {r['name']} (score: {r['score']})")
