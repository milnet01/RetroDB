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
import re

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_PATH, STATIC_PATH
from scraper.base_scraper import get_scraper_conn

# Import settings_manager for dynamic path resolution
# (config.py has empty defaults; actual paths live in data/settings.json)
import settings_manager


def _get_rom_path():
    return settings_manager.get_effective_path('rom_path', '')


def _get_esde_gamelists_path():
    return settings_manager.get_effective_path('esde_gamelists_path', '')


def _get_esde_media_path():
    return settings_manager.get_effective_path('esde_downloaded_media_path', '')

logger = logging.getLogger(__name__)


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
    
    # If it's a numeric ID (ScreenScraper style), skip it
    # The hybrid scraper will fill this from TGDB/IGDB
    if value.isdigit():
        logger.debug(f"Skipping numeric {value_type} ID: {value}")
        return None
    
    # It's a real name - return it
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


def parse_gamelist_xml(xml_path):
    """
    Parse a gamelist.xml file and return list of game entries
    """
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
        r'\(En\)': 'English',
        r'\(Fr\)': 'France',
        r'\(De\)': 'Germany',
        r'\(Es\)': 'Spain',
        r'\(It\)': 'Italy',
        r'\(Br\)': 'Brazil',
        r'\(K\)': 'Korea',
        r'\(Ch\)': 'China',
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
    """Derive game modes from players string"""
    if not players_str:
        return 'Single-Player'

    try:
        # Handle formats like "1-4", "1-2", "1", "2", "4+"
        players_str = str(players_str).strip()

        if '-' in players_str:
            parts = players_str.split('-')
            max_players = int(parts[1].replace('+', ''))
        elif '+' in players_str:
            max_players = int(players_str.replace('+', ''))
        else:
            max_players = int(players_str)

        if max_players > 1:
            return 'Single-Player, Multiplayer'
        else:
            return 'Single-Player'
    except Exception:
        return 'Single-Player'


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
            release_date = game.get('releasedate', '')
            if release_date and len(release_date) >= 8:
                # ES-DE format: YYYYMMDDTHHMMSS
                release_date = f"{release_date[:4]}-{release_date[4:6]}-{release_date[6:8]}"
            
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
    logger.info(f"Sample stored paths from gamelist:")
    for i, g in enumerate(games[:5]):
        logger.info(f"  [{i}] {g.get('path', 'NO PATH')}")
    
    # Try to match the game by path
    for game in games:
        stored_path = game.get('path', '')
        
        # Normalize paths for comparison
        stored_normalized = stored_path.replace('./', '').strip()
        search_normalized = decoded_game_path.replace('./', '').strip()
        
        # Also try with just the filename
        stored_filename = os.path.basename(stored_path)
        search_filename = os.path.basename(decoded_game_path)
        
        # Try multiple matching strategies
        matched = False
        if stored_path == decoded_game_path:
            logger.info(f"Found exact match for path: {decoded_game_path}")
            matched = True
        elif stored_normalized == search_normalized:
            logger.info(f"Found match after normalizing: {search_normalized}")
            matched = True
        elif stored_filename == search_filename:
            logger.info(f"Found match by filename: {search_filename}")
            matched = True
        elif stored_normalized.lower() == search_normalized.lower():
            logger.info(f"Found case-insensitive match: {search_normalized}")
            matched = True
        
        if not matched:
            continue
        
        # Found a match - format and return
        release_date = game.get('releasedate', '')
        if release_date and len(release_date) >= 8:
            release_date = f"{release_date[:4]}-{release_date[4:6]}-{release_date[6:8]}"
        
        return {
            'name': game.get('name', ''),
            'description': game.get('desc', ''),
            'developer': game.get('developer', ''),
            'publisher': game.get('publisher', ''),
            'genre': game.get('genre', ''),
            'players': game.get('players', '1'),
            'release_date': release_date,
            'rating': game.get('rating', ''),
            'image_path': game.get('image', ''),
            'screenshot_path': game.get('screenshot', ''),
            'video_path': game.get('video', ''),
            'esde_data': game
        }
    
    logger.error(f"No matching game found for path: {game_path} (decoded: {decoded_game_path}) in {system_folder}")
    return None


def apply_esde_metadata(db_game_id, game_data, system_folder=None, existing_boxart=None, existing_screenshots=None, force_overwrite=False):
    """
    Apply ES-DE metadata to a game in the database.
    Copies images, screenshots, videos from ES-DE media folders.

    IMPORTANT: This function follows the "augment, don't replace" principle:
    - Boxart is only copied if existing_boxart is None/empty (unless force_overwrite=True)
    - Screenshots are always appended to existing_screenshots, never replaced

    Args:
        force_overwrite: If True, replace existing media even if present in DB
    """
    conn = None
    try:
        conn = get_scraper_conn()
        c = conn.cursor()

        # Get game info including system folder and ROM path
        c.execute("""
            SELECT g.rom_path, s.folder, g.boxart, g.screenshots, g.boxart_3d 
            FROM games g 
            JOIN systems s ON g.system_id = s.id 
            WHERE g.id = ?
        """, (db_game_id,))
        result = c.fetchone()
        
        if not result:
            logger.error(f"Game {db_game_id} not found")
            conn.close()
            return False
        
        rom_path, sys_folder, db_boxart, db_screenshots, db_boxart_3d = result
        system_folder = system_folder or sys_folder
        
        # Use existing values from DB if not provided as parameters
        # UNLESS force_overwrite is True - then we want to replace existing media
        # Track old filenames for deferred cleanup (only delete after replacements found)
        _old_boxart = None
        _old_boxart_3d = None
        if force_overwrite:
            # In force overwrite mode, treat as if no existing media so ES-DE
            # tries to find new files. Old files are only deleted later if
            # replacements are successfully found.
            existing_boxart = None
            existing_screenshots = None
            existing_boxart_3d = None
            _old_boxart = db_boxart
            _old_boxart_3d = db_boxart_3d
        else:
            if existing_boxart is None:
                existing_boxart = db_boxart
            if existing_screenshots is None:
                existing_screenshots = db_screenshots
            existing_boxart_3d = db_boxart_3d
        
        # Get ROM filename without extension - ES-DE names media files after the ROM
        rom_filename = os.path.basename(rom_path)
        rom_name_no_ext = os.path.splitext(rom_filename)[0]
        
        # Get the ES-DE base path and downloaded_media location
        # esde_gl_path could be:
        #   /path/to/ES-DE/gamelists  -> downloaded_media is /path/to/ES-DE/downloaded_media
        #   /path/to/gamelists -> downloaded_media could be /path/to/downloaded_media
        esde_gl_path = _get_esde_gamelists_path()
        esde_base = os.path.dirname(esde_gl_path) if esde_gl_path else None
        downloaded_media_base = None
        gamelist_dir = os.path.join(esde_gl_path, system_folder) if esde_gl_path else None

        # Try explicit config setting first
        possible_media_bases = []
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
        
        # Find the first valid downloaded_media path
        for path in possible_media_bases:
            if os.path.exists(path):
                downloaded_media_base = path
                logger.info(f"  Found downloaded_media at: {path}")
                break
        
        if not downloaded_media_base:
            logger.warning(f"  Could not find downloaded_media folder for {system_folder}")
            logger.warning(f"  Tried: {possible_media_bases[:3]}...")  # Log first 3 attempts
        
        logger.info(f"Applying ES-DE metadata for game {db_game_id}")
        logger.info(f"  ROM filename: {rom_filename}")
        logger.info(f"  ROM name (no ext): {rom_name_no_ext}")
        logger.info(f"  System folder: {system_folder}")
        logger.info(f"  Downloaded media base: {downloaded_media_base}")
        
        # Helper function to find media in ES-DE downloaded_media folder by ROM name
        def find_media_by_rom_name(media_type):
            """Find media file in ES-DE downloaded_media/{system}/{media_type}/"""
            if not downloaded_media_base:
                return None
            
            media_folder = os.path.join(downloaded_media_base, media_type)
            if not os.path.exists(media_folder):
                logger.debug(f"  Media folder not found: {media_folder}")
                return None
            
            # Look for file matching ROM name with various extensions
            for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.mkv', '.avi', '.webm', '.pdf']:
                media_path = os.path.join(media_folder, rom_name_no_ext + ext)
                if os.path.exists(media_path):
                    logger.info(f"  Found {media_type}: {os.path.basename(media_path)}")
                    return media_path
            
            logger.debug(f"  No {media_type} found for: {rom_name_no_ext}")
            return None
        
        # Helper function to resolve ES-DE media paths from gamelist.xml
        def resolve_media_path(media_path):
            if not media_path:
                return None
            
            if media_path.startswith('/'):
                if os.path.exists(media_path):
                    return media_path
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
                if os.path.exists(full_path):
                    logger.info(f"  Found media at: {full_path}")
                    return full_path
            
            return None
        
        # Helper function to copy media file
        def copy_media(src_path, dest_folder, prefix):
            if not src_path or not os.path.exists(src_path):
                return None
            
            ext = os.path.splitext(src_path)[1].lower()
            filename = f"{db_game_id}_{prefix}{ext}"
            dest_dir = os.path.join(IMAGE_PATH, dest_folder)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)
            
            try:
                shutil.copy2(src_path, dest_path)
                # Standardize image size for supported types
                if dest_folder in ('boxart', 'screenshots', 'boxart_3d', 'controllers'):
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
        
        # Prepare metadata
        esde_data = game_data.get('esde_data', game_data)
        
        name = esde_data.get('name', '') or game_data.get('name', '')
        description = esde_data.get('desc', '') or game_data.get('description', '')
        
        # Resolve publisher/developer - skip numeric IDs
        raw_developer = esde_data.get('developer', '') or game_data.get('developer', '')
        raw_publisher = esde_data.get('publisher', '') or game_data.get('publisher', '')
        developer = resolve_publisher_developer(raw_developer, 'developer')
        publisher = resolve_publisher_developer(raw_publisher, 'publisher')
        
        genre = esde_data.get('genre', '') or game_data.get('genre', '')
        players = esde_data.get('players', '1') or game_data.get('players', '1')
        
        # Format release date
        release_date = esde_data.get('releasedate', '') or game_data.get('release_date', '')
        if release_date and len(release_date) >= 8 and 'T' in release_date:
            release_date = f"{release_date[:4]}-{release_date[4:6]}-{release_date[6:8]}"
        
        logger.info(f"  Title: {name}")
        logger.info(f"  Developer: {developer}")
        logger.info(f"  Publisher: {publisher}")
        
        # === IMPORT BOXART === (only if not already present)
        # First try gamelist.xml paths, then search downloaded_media folders by ROM name
        # Prioritize 2D boxart for main boxart field, store 3D boxart separately
        boxart_filename = None
        boxart_3d_filename = None
        
        if existing_boxart:
            logger.info(f"  Skipping boxart import - already has: {existing_boxart}")
            boxart_filename = existing_boxart
        else:
            # Try gamelist.xml paths first - ONLY use actual cover art
            # IMPORTANT: 'image' and 'miximage' in ES-DE are often screenshots, NOT covers
            # Only 'cover' is reliable as actual box art
            for img_field in ['cover']:
                img_path = esde_data.get(img_field, '')
                if img_path:
                    resolved = resolve_media_path(img_path)
                    if resolved:
                        boxart_filename = copy_media(resolved, 'boxart', f'esde_{img_field}')
                        if boxart_filename:
                            break
            
            # If no boxart from gamelist, search downloaded_media/covers folder ONLY
            # IMPORTANT: Do NOT search miximages - those are composite screenshots, not box art
            if not boxart_filename:
                src_path = find_media_by_rom_name('covers')
                if src_path:
                    boxart_filename = copy_media(src_path, 'boxart', 'esde_covers')
            
            # If ES-DE doesn't have actual cover art, leave boxart_filename as None
            # This allows the hybrid scraper to try other sources (ScreenScraper, RAWG, IGDB, etc.)
        
        # === IMPORT 3D BOXART === (separate from regular boxart)
        # Check for existing 3D boxart (fetched from DB at start of function)
        
        if not existing_boxart_3d:
            # Try gamelist.xml '3dbox' field first
            box3d_path = esde_data.get('3dbox', '')
            if box3d_path:
                resolved = resolve_media_path(box3d_path)
                if resolved:
                    boxart_3d_filename = copy_media(resolved, 'boxart_3d', 'esde_3dbox')
            
            # If no 3D boxart from gamelist, search downloaded_media/3dboxes
            if not boxart_3d_filename:
                src_path = find_media_by_rom_name('3dboxes')
                if src_path:
                    boxart_3d_filename = copy_media(src_path, 'boxart_3d', 'esde_3dboxes')
            
            if boxart_3d_filename:
                logger.info(f"  Imported 3D boxart: {boxart_3d_filename}")
        else:
            boxart_3d_filename = existing_boxart_3d
        
        # === DEFERRED CLEANUP: delete old media only if replacements were found ===
        if _old_boxart and boxart_filename and boxart_filename != _old_boxart:
            old_path = os.path.join(IMAGE_PATH, 'boxart', _old_boxart)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    logger.info(f"  Deleted old boxart (replaced): {_old_boxart}")
                except Exception as e:
                    logger.warning(f"  Could not delete old boxart: {e}")
        if _old_boxart_3d and boxart_3d_filename and boxart_3d_filename != _old_boxart_3d:
            old_path = os.path.join(IMAGE_PATH, 'boxart_3d', _old_boxart_3d)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    logger.info(f"  Deleted old 3D boxart (replaced): {_old_boxart_3d}")
                except Exception as e:
                    logger.warning(f"  Could not delete old 3D boxart: {e}")

        # === IMPORT SCREENSHOTS === (always append, never replace)
        # Parse existing screenshots
        existing_ss_list = []
        if existing_screenshots:
            existing_ss_list = [s.strip() for s in existing_screenshots.split(',') if s.strip()]
            logger.info(f"  Existing screenshots: {len(existing_ss_list)}")
        
        new_screenshots = []
        
        # Try gamelist.xml paths first
        for ss_field, prefix in [('screenshot', 'esde_ss'), ('titlescreen', 'esde_ts')]:
            ss_path = esde_data.get(ss_field, '')
            if ss_path:
                resolved = resolve_media_path(ss_path)
                if resolved:
                    ss_file = copy_media(resolved, 'screenshots', prefix)
                    if ss_file and ss_file not in existing_ss_list:
                        new_screenshots.append(ss_file)
        
        # If no new screenshots from gamelist, search downloaded_media folders by ROM name
        if not new_screenshots:
            for media_type, prefix in [('screenshots', 'esde_ss'), ('titlescreens', 'esde_ts')]:
                src_path = find_media_by_rom_name(media_type)
                if src_path:
                    ss_file = copy_media(src_path, 'screenshots', prefix)
                    if ss_file and ss_file not in existing_ss_list:
                        new_screenshots.append(ss_file)
        
        # Combine existing + new screenshots
        all_screenshots = existing_ss_list + new_screenshots
        screenshots_str = ','.join(all_screenshots) if all_screenshots else None
        
        if new_screenshots:
            logger.info(f"  Added {len(new_screenshots)} new screenshots")
        
        # === IMPORT FANART (separate from screenshots for background use) ===
        fanart_filename = None
        
        # Try gamelist.xml path first
        fanart_path = esde_data.get('fanart', '')
        if fanart_path:
            resolved = resolve_media_path(fanart_path)
            if resolved:
                fanart_filename = copy_media(resolved, 'fanart', 'esde_fanart')
        
        # If no fanart from gamelist, search downloaded_media
        if not fanart_filename:
            src_path = find_media_by_rom_name('fanart')
            if src_path:
                fanart_dir = os.path.join(IMAGE_PATH, 'fanart')
                os.makedirs(fanart_dir, exist_ok=True)
                ext = os.path.splitext(src_path)[1].lower()
                fanart_filename = f"{db_game_id}_esde_fanart{ext}"
                try:
                    shutil.copy2(src_path, os.path.join(fanart_dir, fanart_filename))
                    logger.info(f"  Copied fanart: {fanart_filename}")
                except Exception as e:
                    logger.warning(f"  Failed to copy fanart: {e}")
                    fanart_filename = None
        
        # === IMPORT VIDEO ===
        video_filename = None
        video_path = esde_data.get('video', '')
        if video_path:
            resolved = resolve_media_path(video_path)
            if resolved:
                video_dir = os.path.join(STATIC_PATH, 'videos')
                os.makedirs(video_dir, exist_ok=True)
                ext = os.path.splitext(resolved)[1].lower()
                video_filename = f"{db_game_id}_esde{ext}"
                try:
                    shutil.copy2(resolved, os.path.join(video_dir, video_filename))
                    logger.info(f"  Copied video: {video_filename}")
                except Exception as e:
                    logger.warning(f"  Failed to copy video: {e}")
                    video_filename = None
        
        # If no video from gamelist, search downloaded_media
        if not video_filename:
            src_path = find_media_by_rom_name('videos')
            if src_path:
                video_dir = os.path.join(STATIC_PATH, 'videos')
                os.makedirs(video_dir, exist_ok=True)
                ext = os.path.splitext(src_path)[1].lower()
                video_filename = f"{db_game_id}_esde{ext}"
                try:
                    shutil.copy2(src_path, os.path.join(video_dir, video_filename))
                    logger.info(f"  Copied video: {video_filename}")
                except Exception as e:
                    logger.warning(f"  Failed to copy video: {e}")
                    video_filename = None
        
        # === IMPORT MANUAL ===
        manual_filename = None
        manual_path = esde_data.get('manual', '')
        if manual_path:
            resolved = resolve_media_path(manual_path)
            if resolved:
                manual_dir = os.path.join(IMAGE_PATH, 'manuals')
                os.makedirs(manual_dir, exist_ok=True)
                ext = os.path.splitext(resolved)[1].lower()
                manual_filename = f"{db_game_id}_esde{ext}"
                try:
                    shutil.copy2(resolved, os.path.join(manual_dir, manual_filename))
                    logger.info(f"  Copied manual: {manual_filename}")
                except Exception as e:
                    logger.warning(f"  Failed to copy manual: {e}")
                    manual_filename = None
        
        # If no manual from gamelist, search downloaded_media
        if not manual_filename:
            src_path = find_media_by_rom_name('manuals')
            if src_path:
                manual_dir = os.path.join(IMAGE_PATH, 'manuals')
                os.makedirs(manual_dir, exist_ok=True)
                ext = os.path.splitext(src_path)[1].lower()
                manual_filename = f"{db_game_id}_esde{ext}"
                try:
                    shutil.copy2(src_path, os.path.join(manual_dir, manual_filename))
                    logger.info(f"  Copied manual: {manual_filename}")
                except Exception as e:
                    logger.warning(f"  Failed to copy manual: {e}")
                    manual_filename = None
        
        # Extract region from ROM filename
        region = extract_region_from_filename(rom_filename)
        
        # Derive game modes from players
        modes = derive_game_modes(players)
        
        # Update database - use COALESCE to preserve existing data if new data is empty
        c.execute("""
            UPDATE games SET
                title = COALESCE(?, title),
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
                region = COALESCE(?, region),
                scraped = 1
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
            boxart_filename,
            boxart_3d_filename,
            screenshots_str,
            fanart_filename,
            video_filename,
            manual_filename,
            region,
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


def bulk_import_esde(system_folder=None):
    """
    Bulk import all ES-DE metadata for a system (or all systems)
    Matches games by ROM filename
    """
    conn = None
    imported = 0
    skipped = 0

    try:
        conn = get_scraper_conn()
        c = conn.cursor()

        # Get systems to process
        if system_folder:
            c.execute("SELECT id, folder FROM systems WHERE folder = ?", (system_folder,))
        else:
            c.execute("SELECT id, folder FROM systems")

        systems = c.fetchall()

        for system_id, sys_folder in systems:
            xml_path = find_gamelist_xml(sys_folder)

            if not xml_path:
                logger.debug(f"No gamelist.xml for {sys_folder}")
                continue

            games = parse_gamelist_xml(xml_path)

            if not games:
                continue

            # Get all unscraped games for this system
            c.execute("""
                SELECT id, rom_path, title FROM games
                WHERE system_id = ? AND scraped = 0
            """, (system_id,))

            db_games = c.fetchall()

            # Build lookup dicts for O(1) matching instead of O(n²) nested loop
            esde_by_filename = {}
            esde_by_relpath = {}
            for esde_game in games:
                esde_path = esde_game.get('path', '')
                esde_filename = os.path.basename(esde_path)
                esde_by_filename.setdefault(esde_filename, esde_game)
                rel_path = esde_path.replace('./', '')
                if rel_path:
                    esde_by_relpath.setdefault(rel_path, esde_game)

            for db_id, rom_path, db_title in db_games:
                rom_filename = os.path.basename(rom_path)

                # O(1) lookup by filename or relative path
                esde_game = esde_by_filename.get(rom_filename) or esde_by_relpath.get(rom_filename)
                if esde_game:
                    game_data = {
                        'name': esde_game.get('name', ''),
                        'description': esde_game.get('desc', ''),
                        'developer': esde_game.get('developer', ''),
                        'publisher': esde_game.get('publisher', ''),
                        'genre': esde_game.get('genre', ''),
                        'players': esde_game.get('players', '1'),
                        'release_date': esde_game.get('releasedate', ''),
                        'image_path': esde_game.get('image', ''),
                        'screenshot_path': esde_game.get('screenshot', ''),
                    }

                    if apply_esde_metadata(db_id, game_data, sys_folder):
                        imported += 1
                    else:
                        skipped += 1
    except Exception as e:
        logger.error(f"ES-DE bulk import failed: {e}")
    finally:
        if conn:
            conn.close()

    logger.info(f"ES-DE bulk import complete: {imported} imported, {skipped} skipped")
    return imported, skipped


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
                        # Keep original extension for webp files
                        dest_ext = ext if ext in ['.webp', '.svg'] else '.png'
                        dest_path = os.path.join(dest_dir, f'{system_folder}{dest_ext}')
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
                    # Check if this looks like a system logo
                    file_lower = file.lower()
                    for system in ['nes', 'snes', 'n64', 'gb', 'gba', 'gbc', 'nds', 'psx', 'ps2', 
                                   'genesis', 'megadrive', 'dreamcast', 'saturn', 'gamegear',
                                   'atari2600', 'atari7800', 'mame', 'arcade', 'neogeo']:
                        if system in file_lower or system in root.lower():
                            src_path = os.path.join(root, file)
                            # Keep original extension for webp/svg
                            dest_ext = file_ext if file_ext in ['.webp', '.svg'] else '.png'
                            dest_path = os.path.join(dest_dir, f'{system}{dest_ext}')
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
