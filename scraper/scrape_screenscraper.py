"""
ScreenScraper.fr API Scraper for RetroDB
https://www.screenscraper.fr/

ScreenScraper is one of the most comprehensive retro gaming databases.
It provides game metadata, box art, screenshots, manuals, videos, and more.

API Documentation: https://www.screenscraper.fr/webapi2.php
"""

import requests
import logging
import time
import hashlib
import os

logger = logging.getLogger(__name__)

# ScreenScraper API endpoints
API_BASE = "https://api.screenscraper.fr/api2"
MEDIA_BASE = "https://third.screenscraper.fr/api2"
GAME_INFO_URL = f"{API_BASE}/jeuInfos.php"
GAME_SEARCH_URL = f"{API_BASE}/jeuRecherche.php"
SYSTEMS_URL = f"{API_BASE}/systemesListe.php"
USER_INFO_URL = f"{API_BASE}/ssuserInfos.php"
SYSTEM_MEDIA_URL = f"{MEDIA_BASE}/mediaSysteme.php"

# Software identifier for RetroDB
SOFTWARE_NAME = "RetroDB"

# System ID mappings from ES-DE/RetroDB folder names to ScreenScraper system IDs
# Full list: https://www.screenscraper.fr/webapi2.php
SYSTEM_ID_MAP = {
    # Nintendo
    "nes": 3,
    "famicom": 3,
    "fds": 106,
    "snes": 4,
    "sfc": 4,
    "satellaview": 107,
    "sufami": 108,
    "n64": 14,
    "n64dd": 122,
    "gamecube": 13,
    "gc": 13,
    "wii": 16,
    "wiiu": 18,
    "switch": 225,
    "gb": 9,
    "gbc": 10,
    "gba": 12,
    "nds": 15,
    "3ds": 17,
    "n3ds": 17,
    "virtualboy": 11,
    "pokemon-mini": 211,
    "pokemini": 211,
    "gameandwatch": 52,

    # Sega
    "genesis": 1,
    "megadrive": 1,
    "megadrivejp": 1,
    "mastersystem": 2,
    "sms": 2,
    "gamegear": 21,
    "sg-1000": 109,
    "sc-3000": 109,
    "segacd": 20,
    "sega32x": 19,
    "sega32xjp": 19,
    "sega32xna": 19,
    "saturn": 22,
    "saturnjp": 22,
    "dreamcast": 23,
    "naomi2": 56,
    
    # Sony
    "psx": 57,
    "ps2": 58,
    "ps3": 59,
    "ps4": 60,
    "ps5": 284,
    "psp": 61,
    "psvita": 62,

    # Microsoft
    "xbox": 32,
    "xbox360": 33,
    "xboxone": 34,
    
    # Atari
    "atari2600": 26,
    "atari5200": 40,
    "atari7800": 41,
    "atarijaguar": 27,
    "atarijaguarcd": 171,
    "atarilynx": 28,
    "atarist": 42,
    "atari800": 43,
    "atarixe": 43,
    
    # NEC
    "pcengine": 31,
    "tg16": 31,
    "pcenginecd": 114,
    "tg-cd": 114,
    "supergrafx": 105,
    "pcfx": 72,
    
    # SNK
    "neogeo": 142,
    "neogeocd": 70,
    "ngp": 25,
    "ngpc": 82,
    
    # Other Consoles
    "3do": 29,
    "colecovision": 48,
    "intellivision": 115,
    "odyssey2": 104,
    "vectrex": 102,
    "channelf": 80,
    "astrocade": 44,
    "astrocde": 44,
    "cdimono1": 133,
    "cdi": 133,
    
    # Computers
    "amiga": 64,
    "amstradcpc": 65,
    "c64": 66,
    "vic20": 73,
    "msx": 113,
    "msx1": 113,
    "msx2": 116,
    "msxturbor": 118,
    "zxspectrum": 76,
    "dos": 135,
    "windows9x": 137,
    "windows": 138,
    "pc": 138,
    "pc88": 221,
    "pc98": 208,
    "x68000": 79,
    "sharp-x1": 220,
    "fm7": 97,
    "fmtowns": 253,
    
    # Handhelds
    "wonderswan": 45,
    "wonderswancolor": 46,
    "gp32": 101,
    "ngauge": 30,
    
    # Arcade
    "arcade": 75,
    "mame": 75,
    "fbneo": 75,
    "fba": 75,
    "cps1": 6,
    "cps2": 7,
    "cps3": 8,
    "naomi": 56,
    "atomiswave": 53,
    "model2": 54,
    "model3": 55,
    
    # Other
    "scummvm": 123,
    "ports": 137,
}

# Region priority for media selection (prefer English/US/World)
REGION_PRIORITY = ["us", "wor", "eu", "uk", "jp", "ss"]

# Language priority
LANGUAGE_PRIORITY = ["en", "us", "wor", "eu", "uk"]


def get_system_id(system_folder):
    """Convert ES-DE/RetroDB system folder name to ScreenScraper system ID"""
    folder_lower = system_folder.lower()
    return SYSTEM_ID_MAP.get(folder_lower)


def calculate_checksums(file_path):
    """Calculate CRC32, MD5, and SHA1 checksums for a file"""
    checksums = {"crc": None, "md5": None, "sha1": None}
    
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return checksums
    
    # Skip large files (> 100MB) to avoid memory issues
    file_size = os.path.getsize(file_path)
    if file_size > 100 * 1024 * 1024:
        logger.debug(f"Skipping checksum for large file: {file_path}")
        return checksums
    
    try:
        import zlib
        
        md5_hash = hashlib.md5()
        sha1_hash = hashlib.sha1()
        crc32_value = 0
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5_hash.update(chunk)
                sha1_hash.update(chunk)
                crc32_value = zlib.crc32(chunk, crc32_value)
        
        checksums["crc"] = format(crc32_value & 0xFFFFFFFF, '08X')
        checksums["md5"] = md5_hash.hexdigest()
        checksums["sha1"] = sha1_hash.hexdigest()
        
    except Exception as e:
        logger.error(f"Error calculating checksums: {e}")
    
    return checksums


def check_credentials(username, password, dev_id=None, dev_password=None):
    """Test if ScreenScraper credentials are valid"""
    try:
        # Build params with correct order: devid/devpassword MUST come before ssid/sspassword
        params = []
        if dev_id and dev_password:
            params.append(("devid", dev_id))
            params.append(("devpassword", dev_password))
        params.extend([
            ("softname", SOFTWARE_NAME),
            ("ssid", username),
            ("sspassword", password),
            ("output", "json")
        ])
        
        response = requests.get(USER_INFO_URL, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if "response" in data and "ssuser" in data["response"]:
                user_info = data["response"]["ssuser"]
                return {
                    "valid": True,
                    "username": user_info.get("id", username),
                    "level": user_info.get("niveau", "Unknown"),
                    "contribution": user_info.get("contribution", "0"),
                    "threads": user_info.get("maxthreads", "1"),
                    "requests_today": user_info.get("requeststoday", "0"),
                    "max_requests": user_info.get("maxrequestsperday", "20000"),
                }
        
        return {"valid": False, "error": "Invalid credentials or API unavailable"}
        
    except requests.exceptions.Timeout:
        return {"valid": False, "error": "Connection timeout"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def search_game(game_title, system_folder, username, password, dev_id=None, dev_password=None):
    """
    Search for a game by title on ScreenScraper
    
    Args:
        game_title: Name of the game to search for
        system_folder: ES-DE system folder name
        username: ScreenScraper username
        password: ScreenScraper password
        dev_id: Optional developer ID
        dev_password: Optional developer password
    
    Returns:
        List of matching games or None if error
    """
    system_id = get_system_id(system_folder)
    if not system_id:
        logger.warning(f"ScreenScraper: Unknown system folder '{system_folder}' - no mapping found")
        return None
    
    # Sanitize search query for ScreenScraper API
    # Keep sanitization minimal — SS search is strict and over-cleaning kills matches
    import re
    # Remove parenthesized noise (region codes, disc indicators, etc.)
    sanitized_title = re.sub(r'\([^)]*\)', '', game_title)
    sanitized_title = re.sub(r'\[[^\]]*\]', '', sanitized_title)
    # Remove backslashes (never in real titles)
    sanitized_title = sanitized_title.replace('\\', ' ')
    # Normalize multiple spaces and trim
    sanitized_title = ' '.join(sanitized_title.split()).strip()

    logger.info(f"ScreenScraper: Searching for '{sanitized_title}' (original: '{game_title}') on system {system_folder} (ID: {system_id})")
    
    # Try with dev credentials first, then without if they fail
    for attempt, use_dev_creds in enumerate([(True, dev_id, dev_password), (False, None, None)]):
        use_dev, current_dev_id, current_dev_pass = use_dev_creds
        
        # Skip second attempt if we didn't have dev credentials to begin with
        if attempt == 1 and not dev_id:
            break
            
        try:
            # Build params with correct order: devid/devpassword MUST come before ssid/sspassword
            params = []
            if use_dev and current_dev_id and current_dev_pass:
                params.append(("devid", current_dev_id))
                params.append(("devpassword", current_dev_pass))
            params.extend([
                ("softname", SOFTWARE_NAME),
                ("ssid", username),
                ("sspassword", password),
                ("output", "json"),
                ("recherche", sanitized_title),
                ("systemeid", str(system_id)),
            ])
            
            logger.debug(f"ScreenScraper API URL: {GAME_SEARCH_URL}")
            response = _ss_request_with_retry(GAME_SEARCH_URL, params, timeout=60)

            if response is None:
                logger.warning("ScreenScraper: Request failed after retries")
                return None

            logger.info(f"ScreenScraper response status: {response.status_code}")
            
            if response.status_code == 200:
                # Check for empty response (common "not found" response)
                if not response.text or not response.text.strip():
                    logger.info("ScreenScraper: Empty response (game not found)")
                    return None
                
                # Check if response looks like JSON before parsing
                response_text = response.text.strip()
                if not response_text.startswith('{') and not response_text.startswith('['):
                    # Plain text response - likely an error or "not found" message
                    response_lower = response_text.lower()
                    if "aucun jeu" in response_lower or "no game" in response_lower:
                        logger.info("ScreenScraper: No game found")
                        return None
                    elif "quota" in response_lower or "maximum" in response_lower or "api fermé" in response_lower:
                        logger.warning("ScreenScraper: API quota/rate limit reached")
                        return None
                    elif "identifiants développeur" in response_lower or "developer" in response_lower:
                        # Dev credentials rejected - retry without them
                        if attempt == 0 and dev_id:
                            logger.warning(f"ScreenScraper: Dev credentials rejected, retrying without them...")
                            continue  # Try again without dev credentials
                        else:
                            logger.warning(f"ScreenScraper: Credentials error: {response_text[:100]}")
                            return None
                    elif "erreur" in response_lower or "error" in response_lower:
                        logger.info(f"ScreenScraper: API message: {response_text[:100]}")
                        return None
                    else:
                        logger.info(f"ScreenScraper: Non-JSON response (game not found): {response_text[:50]}")
                    return None
                
                # Try to parse JSON
                try:
                    data = response.json()
                except Exception as json_err:
                    logger.info(f"ScreenScraper: Could not parse response as JSON (game likely not found)")
                    return None
                
                if "response" in data and "jeux" in data["response"]:
                    results = data["response"]["jeux"]
                    # Handle SS API quirk: single result may be a dict instead of list
                    if isinstance(results, dict):
                        results = [results]
                    elif not isinstance(results, list):
                        logger.warning(f"ScreenScraper: Unexpected jeux type: {type(results)}")
                        return None
                    # Filter out empty/null results but keep valid ones with any truthy id
                    valid_results = []
                    for r in results:
                        if not isinstance(r, dict) or not r:
                            logger.debug(f"ScreenScraper: Skipping non-dict result: {type(r)}")
                            continue
                        rid = r.get('id')
                        if rid is not None and rid != '' and rid != 0:
                            valid_results.append(r)
                        else:
                            # Log what we're filtering to help debug missing results
                            r_name = ''
                            noms = r.get('noms', [])
                            if noms and isinstance(noms, list) and len(noms) > 0:
                                r_name = noms[0].get('text', '') if isinstance(noms[0], dict) else ''
                            logger.info(f"ScreenScraper: Filtered result with id={rid!r}, keys={list(r.keys())[:5]}, name='{r_name}'")
                    logger.info(f"ScreenScraper found {len(valid_results)} valid games (raw: {len(results)})")
                    if attempt == 1:
                        logger.info("ScreenScraper: Success without dev credentials")
                    return valid_results
                else:
                    logger.info(f"ScreenScraper: No 'jeux' in response")
            else:
                logger.warning(f"ScreenScraper API returned status {response.status_code}: {response.text[:200]}")
            
            return None

        except Exception as e:
            logger.error(f"ScreenScraper unexpected error: {e}")
            return None

    return None


def get_game_info(rom_path, system_folder, username, password, dev_id=None, dev_password=None, use_checksums=True):
    """
    Get game information from ScreenScraper
    
    Args:
        rom_path: Path to the ROM file
        system_folder: ES-DE system folder name
        username: ScreenScraper username
        password: ScreenScraper password
        dev_id: Optional developer ID
        dev_password: Optional developer password
        use_checksums: Whether to calculate and use file checksums
    
    Returns:
        Dictionary with game data or None if not found
    """
    system_id = get_system_id(system_folder)
    if not system_id:
        logger.warning(f"Unknown system for ScreenScraper: {system_folder}")
        return None
    
    # Get ROM filename and size
    rom_name = os.path.basename(rom_path)
    rom_size = 0
    
    if os.path.exists(rom_path):
        if os.path.isfile(rom_path):
            rom_size = os.path.getsize(rom_path)
        elif os.path.isdir(rom_path):
            # For PS3 games (folder-based), use folder name
            rom_name = os.path.basename(rom_path.rstrip('/\\'))
    
    # Calculate checksums upfront (if needed) - only once
    checksums = {"crc": None, "md5": None, "sha1": None}
    if use_checksums and os.path.isfile(rom_path):
        checksums = calculate_checksums(rom_path)
    
    # Try with dev credentials first, then without if they fail
    for attempt, use_dev_creds in enumerate([(True, dev_id, dev_password), (False, None, None)]):
        use_dev, current_dev_id, current_dev_pass = use_dev_creds
        
        # Skip second attempt if we didn't have dev credentials to begin with
        if attempt == 1 and not dev_id:
            break
        
        try:
            # Build params with correct order: devid/devpassword MUST come before ssid/sspassword
            params = []
            if use_dev and current_dev_id and current_dev_pass:
                params.append(("devid", current_dev_id))
                params.append(("devpassword", current_dev_pass))
            params.extend([
                ("softname", SOFTWARE_NAME),
                ("ssid", username),
                ("sspassword", password),
                ("output", "json"),
                ("systemeid", str(system_id)),
                ("romnom", rom_name),
                ("romtype", "rom"),
            ])

            if rom_size > 0:
                params.append(("romtaille", str(rom_size)))

            # Add checksums for better matching
            if checksums["crc"]:
                params.append(("crc", checksums["crc"]))
            if checksums["md5"]:
                params.append(("md5", checksums["md5"]))
            if checksums["sha1"]:
                params.append(("sha1", checksums["sha1"]))
            
            logger.debug(f"ScreenScraper request for: {rom_name}")
            response = _ss_request_with_retry(GAME_INFO_URL, params, timeout=60)

            if response is None:
                return {"error": "timeout", "message": "Request failed after retries"}

            if response.status_code == 404:
                logger.debug(f"Game not found: {rom_name}")
                return None
            
            if response.status_code == 430:
                logger.warning("ScreenScraper: Daily request limit reached")
                return {"error": "rate_limit", "message": "Daily request limit reached"}
            
            if response.status_code == 423:
                logger.warning("ScreenScraper: API closed for non-contributors")
                return {"error": "api_closed", "message": "API closed - try again later or contribute to ScreenScraper"}
            
            if response.status_code == 200:
                # Check for plain text error response (dev credentials issue)
                response_text = response.text.strip()
                if response_text and not response_text.startswith('{'):
                    response_lower = response_text.lower()
                    if "identifiants développeur" in response_lower or "developer" in response_lower:
                        if attempt == 0 and dev_id:
                            logger.warning(f"ScreenScraper: Dev credentials rejected, retrying without them...")
                            continue  # Try again without dev credentials
                        else:
                            logger.warning(f"ScreenScraper: Credentials error: {response_text[:100]}")
                            return None
                
                try:
                    data = response.json()
                except Exception:
                    logger.warning(f"ScreenScraper: Invalid JSON response")
                    return None
                
                if "response" not in data or "jeu" not in data["response"]:
                    return None
                
                if attempt == 1:
                    logger.info("ScreenScraper: Success without dev credentials")
                return parse_game_data(data["response"]["jeu"])
            
            if response.status_code != 200:
                logger.warning(f"ScreenScraper API error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"ScreenScraper error: {e}")
            return None

    return None


def parse_game_data(jeu):
    """Parse ScreenScraper JSON response into RetroDB format"""
    result = {
        "source": "ScreenScraper",
        "screenscraper_id": jeu.get("id"),
    }
    
    # Get title (prefer English/region name)
    names = jeu.get("noms", [])
    result["title"] = get_localized_text(names, "text", region_key="region")
    
    # Get description/synopsis
    synopsis_list = jeu.get("synopsis", [])
    result["description"] = get_localized_text(synopsis_list, "text", lang_key="langue")
    
    # Get release date
    dates = jeu.get("dates", [])
    for date_entry in dates:
        region = date_entry.get("region", "").lower()
        if region in REGION_PRIORITY[:4]:  # US, World, EU, UK
            result["release_date"] = date_entry.get("text", "")
            break
    if not result.get("release_date") and dates:
        result["release_date"] = dates[0].get("text", "")
    
    # Get developer
    developer = jeu.get("developpeur", {})
    result["developer"] = developer.get("text", "")
    
    # Get publisher
    publisher = jeu.get("editeur", {})
    result["publisher"] = publisher.get("text", "")
    
    # Get genres
    genres = jeu.get("genres", [])
    genre_names = []
    for genre in genres:
        names = genre.get("noms", [])
        genre_name = get_localized_text(names, "text", lang_key="langue")
        if genre_name:
            genre_names.append(genre_name)
    result["genres"] = ", ".join(genre_names)

    # Get franchise/series (familles)
    familles = jeu.get("familles", [])
    franchise_names = []
    for famille in familles:
        names = famille.get("noms", [])
        franchise_name = get_localized_text(names, "text", lang_key="langue")
        if franchise_name:
            franchise_names.append(franchise_name)
    result["franchise"] = ", ".join(franchise_names) if franchise_names else ""

    # Get game modes
    modes_list = jeu.get("modes", [])
    mode_names = []
    for mode in modes_list:
        names = mode.get("noms", [])
        mode_name = get_localized_text(names, "text", lang_key="langue")
        if mode_name:
            mode_names.append(mode_name)
    result["modes"] = ", ".join(mode_names) if mode_names else ""

    # Get player count
    joueurs = jeu.get("joueurs", {})
    result["players"] = joueurs.get("text", "")
    
    # Get community rating (note) - ScreenScraper uses 0-20 scale, convert to 0-100
    note = jeu.get("note", {}).get("text", "")
    if note:
        try:
            note_value = float(note)
            # Convert 0-20 scale to 0-100
            result["user_score"] = round(note_value * 5, 1)
        except (ValueError, TypeError):
            result["user_score"] = None
    else:
        result["user_score"] = None
    
    # Get classification/age ratings - capture BOTH ESRB and PEGI separately
    classifications = jeu.get("classifications", [])
    result["esrb_rating"] = None
    result["pegi_rating"] = None
    
    for classification in classifications:
        rating_type = classification.get("type", "").upper()
        rating_text = classification.get("text", "")
        
        if rating_type == "PEGI" and rating_text:
            result["pegi_rating"] = f"PEGI {rating_text}"
        elif rating_type == "ESRB" and rating_text:
            # Normalize ESRB rating text
            esrb_text = rating_text.upper().strip()
            if esrb_text in ['E', 'EVERYONE']:
                result["esrb_rating"] = 'E'
            elif esrb_text in ['E10', 'E10+', 'EVERYONE 10+']:
                result["esrb_rating"] = 'E10+'
            elif esrb_text in ['T', 'TEEN']:
                result["esrb_rating"] = 'T'
            elif esrb_text in ['M', 'MATURE', 'MATURE 17+']:
                result["esrb_rating"] = 'M'
            elif esrb_text in ['AO', 'ADULTS ONLY', 'ADULTS ONLY 18+']:
                result["esrb_rating"] = 'AO'
            elif esrb_text in ['RP', 'RATING PENDING']:
                result["esrb_rating"] = 'RP'
            elif esrb_text in ['EC', 'EARLY CHILDHOOD']:
                result["esrb_rating"] = 'EC'
            else:
                result["esrb_rating"] = esrb_text
    
    # Get media URLs
    medias = jeu.get("medias", [])
    result["media"] = parse_media(medias)
    
    # Get ROM info
    roms = jeu.get("roms", [])
    if roms:
        result["rom_info"] = {
            "romfilename": roms[0].get("romfilename", ""),
            "romregions": roms[0].get("romregions", ""),
        }
    
    return result


def parse_media(medias):
    """Parse media list and select best options by region"""
    result = {}
    
    media_type_map = {
        "box-2D": "boxart_front",
        "box-2D-back": "boxart_back",
        "box-3D": "boxart_3d",
        "screenshot": "screenshot",
        "ss": "screenshot",
        "sstitle": "titlescreen",  # Title screen
        "screenmarquee": "marquee",
        "wheel": "wheel",
        "wheel-hd": "wheel_hd",
        "fanart": "fanart",
        "video": "video",
        "video-normalized": "video",
        "manuel": "manual",
        "maps": "map",
    }
    
    # Group media by type
    media_by_type = {}
    for media in medias:
        media_type = media.get("type", "")
        if media_type not in media_by_type:
            media_by_type[media_type] = []
        media_by_type[media_type].append(media)
    
    # Select best media for each type based on region
    for ss_type, retrodb_type in media_type_map.items():
        if ss_type in media_by_type:
            media_list = media_by_type[ss_type]
            selected = select_best_media(media_list)
            if selected:
                result[retrodb_type] = selected.get("url", "")
    
    return result


def select_best_media(media_list):
    """Select best media item based on region priority"""
    if not media_list:
        return None
    
    # Try to find media matching region priority
    for region in REGION_PRIORITY:
        for media in media_list:
            media_region = media.get("region", "").lower()
            if media_region == region:
                return media
    
    # Fall back to first available
    return media_list[0]


def get_localized_text(items, text_key="text", lang_key=None, region_key=None):
    """Get text from a list of localized items, preferring English"""
    if not items:
        return ""
    
    # Try language-based selection
    if lang_key:
        for lang in LANGUAGE_PRIORITY:
            for item in items:
                if item.get(lang_key, "").lower() == lang:
                    return item.get(text_key, "")
    
    # Try region-based selection
    if region_key:
        for region in REGION_PRIORITY:
            for item in items:
                if item.get(region_key, "").lower() == region:
                    return item.get(text_key, "")
    
    # Fall back to first item
    if items:
        return items[0].get(text_key, "")
    
    return ""


def download_media(url, dest_path, timeout=60):
    """Download media file from ScreenScraper"""
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        if response.status_code == 200:
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        logger.error(f"Error downloading media: {e}")
    return False


# Main scraper function for integration with RetroDB
def scrape(game_title, system_folder, rom_path=None, settings=None):
    """
    Main entry point for ScreenScraper scraping
    
    Args:
        game_title: Title of the game
        system_folder: ES-DE system folder name
        rom_path: Optional path to ROM file (for checksum matching)
        settings: Dictionary with scraper settings including credentials
    
    Returns:
        Dictionary with scraped data or None
    """
    if not settings:
        logger.error("ScreenScraper requires credentials in settings")
        return None
    
    username = settings.get("screenscraper_username")
    password = settings.get("screenscraper_password")
    dev_id = settings.get("screenscraper_devid")
    dev_password = settings.get("screenscraper_devpassword")
    
    if not username or not password:
        logger.error("ScreenScraper username and password required")
        return None
    
    # If we have a ROM path, try to get game info by file matching first
    if rom_path and os.path.exists(rom_path):
        result = get_game_info(
            rom_path, 
            system_folder, 
            username, 
            password,
            dev_id,
            dev_password
        )
        if result and "error" not in result:
            return result
    
    # Fall back to title search
    games = search_game(game_title, system_folder, username, password, dev_id, dev_password)
    if games and len(games) > 0:
        # Get full info for first match
        first_match = games[0]
        # Return basic info from search
        return {
            "source": "ScreenScraper",
            "screenscraper_id": first_match.get("id"),
            "title": get_localized_text(first_match.get("noms", []), "text", region_key="region"),
        }
    
    return None


def get_game_by_id(game_id, username, password, dev_id=None, dev_password=None, system_id=None):
    """
    Get game information by ScreenScraper game ID
    
    Args:
        game_id: ScreenScraper game ID
        username: ScreenScraper username
        password: ScreenScraper password
        dev_id: Optional developer ID
        dev_password: Optional developer password
        system_id: Optional ScreenScraper system ID
    
    Returns:
        Dictionary with game data or None if not found
    """
    try:
        # Build params with correct order - devid/devpassword BEFORE ssid/sspassword
        params = []
        if dev_id and dev_password:
            params.append(("devid", dev_id))
            params.append(("devpassword", dev_password))
        params.extend([
            ("softname", SOFTWARE_NAME),
            ("ssid", username),
            ("sspassword", password),
            ("output", "json"),
            ("jeuid", str(game_id)),
        ])
        
        # Add system ID if provided
        if system_id:
            params.append(("systemeid", str(system_id)))
        
        logger.debug(f"ScreenScraper fetching game ID: {game_id}, system ID: {system_id}")
        response = _ss_request_with_retry(GAME_INFO_URL, params, timeout=60)

        if response is None:
            logger.warning(f"ScreenScraper request failed for game ID: {game_id}")
            return None

        if response.status_code == 404:
            logger.debug(f"Game not found: {game_id}")
            return None

        if response.status_code != 200:
            logger.warning(f"ScreenScraper API error: {response.status_code}")
            return None

        data = response.json()

        if "response" not in data or "jeu" not in data["response"]:
            return None

        return data["response"]["jeu"]

    except Exception as e:
        logger.error(f"Error fetching game by ID: {e}")
        return None


def fetch_system_media(system_id, media_type, username, password, dev_id=None, dev_password=None, region="us"):
    """Fetch system-level media from ScreenScraper (logos, controllers, bezels, etc.).

    Args:
        system_id: ScreenScraper system ID.
        media_type: Media type string (e.g. 'photo-console', 'photo-manette',
                     'illustration', 'logo-monochrome', 'bezel-4-3', 'bezel-16-9').
        username: ScreenScraper username.
        password: ScreenScraper password.
        dev_id: Optional developer ID.
        dev_password: Optional developer password.
        region: Region code (default 'us').

    Returns:
        URL string for the media, or None.
    """
    try:
        params = []
        if dev_id and dev_password:
            params.append(("devid", dev_id))
            params.append(("devpassword", dev_password))
        params.extend([
            ("softname", SOFTWARE_NAME),
            ("ssid", username),
            ("sspassword", password),
            ("systemeid", str(system_id)),
            ("media", media_type),
            ("region", region),
        ])

        # System media uses a different CDN host
        logger.info(f"Fetching ScreenScraper system media: system={system_id}, type={media_type}")

        response = _ss_request_with_retry(SYSTEM_MEDIA_URL, params, timeout=30, retries=1)

        if response is None:
            logger.warning("ScreenScraper system media request failed")
            return None

        if response.status_code == 200 and response.content:
            # The endpoint returns the image binary directly, not JSON
            # Return the full URL so the caller can download it
            return response.url

        logger.warning(f"ScreenScraper system media not found: {response.status_code}")
        return None

    except Exception as e:
        logger.error(f"ScreenScraper system media error: {e}")
        return None


def _ss_request_with_retry(url, params, timeout=60, retries=2):
    """Make a ScreenScraper API request with retry logic for transient failures.

    Retries on timeouts, 429/430 (rate limit), and 5xx (server errors)
    with exponential backoff.  Returns the Response object or None.
    """
    import time as _time

    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)

            if response.status_code == 200:
                return response
            elif response.status_code in (429, 430):
                if attempt < retries:
                    wait = 2 ** attempt
                    logger.warning(f"ScreenScraper rate limited ({response.status_code}), waiting {wait}s...")
                    _time.sleep(wait)
                    continue
                return response
            elif response.status_code >= 500:
                # SS is notorious for 5xx errors under load — retry these
                if attempt < retries:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"ScreenScraper server error ({response.status_code}), retrying in {wait}s...")
                    _time.sleep(wait)
                    continue
                logger.warning(f"ScreenScraper server error ({response.status_code}) after {retries + 1} attempts")
                return response
            else:
                return response

        except requests.exceptions.Timeout:
            if attempt < retries:
                wait = 1 * (attempt + 1)
                logger.warning(f"ScreenScraper timeout (attempt {attempt + 1}), retrying in {wait}s...")
                _time.sleep(wait)
                continue
            logger.warning(f"ScreenScraper timed out after {retries + 1} attempts")
            return None
        except requests.exceptions.ConnectionError:
            if attempt < retries:
                wait = 1 * (attempt + 1)
                logger.warning(f"ScreenScraper connection error (attempt {attempt + 1}), retrying in {wait}s...")
                _time.sleep(wait)
                continue
            return None
        except Exception as e:
            logger.error(f"ScreenScraper request error: {e}")
            return None

    return None


if __name__ == "__main__":
    # Test the module
    import sys
    
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
        
        print("Testing ScreenScraper credentials...")
        result = check_credentials(username, password)
        print(f"Result: {result}")
    else:
        print("Usage: python scrape_screenscraper.py <username> <password>")
