# =============================================================================
# RETRODB - CLZ Import Blueprint
# =============================================================================
# Handles importing game collections from CLZ Games PDF exports.
# =============================================================================

from flask import Blueprint, request, redirect, url_for
import os
import re
import tempfile
import logging
import unicodedata
from datetime import datetime, timezone

import config
from services.analytics import invalidate_analytics_cache
from services.database import get_db, query, execute
from flask import g

from services.auth import editor_required, login_required
from services.api_helpers import handle_api_errors, success, error

logger = logging.getLogger(__name__)

bp = Blueprint('clz_import', __name__)


def normalize_title(title):
    """Normalize a game title for fuzzy matching.

    Strips diacritical marks (û→u, é→e), lowercases, removes punctuation,
    and collapses whitespace so that titles like "Abzû" and "Abzu" or
    "AC/DC Live: Rock Band" and "ACDC Live Rock Band" compare equal.
    """
    if not title:
        return ''
    # Decompose unicode and strip combining marks (accents/diacritics)
    nfkd = unicodedata.normalize('NFKD', title)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase, strip punctuation, collapse whitespace
    stripped = stripped.lower()
    stripped = re.sub(r'[^a-z0-9\s]', '', stripped)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    return stripped


# =============================================================================
# CLZ PLATFORM MAPPING
# =============================================================================

# CLZ platform to RetroDB system folder mapping
# Keys must be lowercase - lookup converts to lowercase
CLZ_PLATFORM_MAP = {
    # PlayStation - ALL variants
    'playstation': 'psx',
    'playstation 1': 'psx',
    'ps1': 'psx',
    'psx': 'psx',
    'sony playstation': 'psx',
    'playstation 2': 'ps2',
    'ps2': 'ps2',
    'sony playstation 2': 'ps2',
    'playstation 3': 'ps3',
    'ps3': 'ps3',
    'sony playstation 3': 'ps3',
    'playstation 4': 'ps4',
    'ps4': 'ps4',
    'sony playstation 4': 'ps4',
    'playstation 5': 'ps5',
    'ps5': 'ps5',
    'sony playstation 5': 'ps5',
    'psp': 'psp',
    'playstation portable': 'psp',
    'sony psp': 'psp',
    'playstation vita': 'psvita',
    'ps vita': 'psvita',
    'psvita': 'psvita',
    'vita': 'psvita',
    'playstation 4 vr': 'ps4',
    'playstation vr': 'ps4',
    'psvr': 'ps4',
    'ps vr': 'ps4',
    'playstation vr2': 'ps5',
    'psvr2': 'ps5',
    # Xbox - ALL variants
    'xbox': 'xbox',
    'microsoft xbox': 'xbox',
    'xbox 360': 'xbox360',
    'microsoft xbox 360': 'xbox360',
    'xbox one': 'xboxone',
    'microsoft xbox one': 'xboxone',
    'xbox series x': 'xboxseriesx',
    'xbox series s': 'xboxseriesx',
    'xbox series x/s': 'xboxseriesx',
    'xbox series': 'xboxseriesx',
    # Nintendo - ALL variants
    'nes': 'nes',
    'nintendo entertainment system': 'nes',
    'nintendo': 'nes',
    'famicom': 'nes',
    'snes': 'snes',
    'super nintendo': 'snes',
    'super nintendo entertainment system': 'snes',
    'super famicom': 'snes',
    'nintendo 64': 'n64',
    'n64': 'n64',
    'gamecube': 'gc',
    'nintendo gamecube': 'gc',
    'gc': 'gc',
    'ngc': 'gc',
    'wii': 'wii',
    'nintendo wii': 'wii',
    'wii u': 'wiiu',
    'nintendo wii u': 'wiiu',
    'wiiu': 'wiiu',
    'nintendo switch': 'switch',
    'switch': 'switch',
    'game boy': 'gb',
    'gameboy': 'gb',
    'nintendo game boy': 'gb',
    'gb': 'gb',
    'game boy color': 'gbc',
    'gameboy color': 'gbc',
    'gbc': 'gbc',
    'game boy advance': 'gba',
    'gameboy advance': 'gba',
    'gba': 'gba',
    'nintendo ds': 'nds',
    'ds': 'nds',
    'nds': 'nds',
    '3ds': 'n3ds',
    'nintendo 3ds': 'n3ds',
    'n3ds': 'n3ds',
    'new 3ds': 'n3ds',
    'new nintendo 3ds': 'n3ds',
    'virtual boy': 'virtualboy',
    'virtualboy': 'virtualboy',
    # Sega - ALL variants
    'genesis': 'megadrive',
    'sega genesis': 'megadrive',
    'mega drive': 'megadrive',
    'sega mega drive': 'megadrive',
    'genesis / mega drive': 'megadrive',
    'megadrive': 'megadrive',
    'sega cd': 'segacd',
    'mega cd': 'segacd',
    'segacd': 'segacd',
    'saturn': 'saturn',
    'sega saturn': 'saturn',
    'dreamcast': 'dreamcast',
    'sega dreamcast': 'dreamcast',
    'dc': 'dreamcast',
    'game gear': 'gamegear',
    'sega game gear': 'gamegear',
    'gamegear': 'gamegear',
    'gg': 'gamegear',
    'master system': 'mastersystem',
    'sega master system': 'mastersystem',
    'sms': 'mastersystem',
    '32x': 'sega32x',
    'sega 32x': 'sega32x',
    'sega32x': 'sega32x',
    'sg-1000': 'sg1000',
    'sega sg-1000': 'sg1000',
    # Computers - ALL variants
    'pc': 'windows9x',
    'dos': 'dos',
    'ms-dos': 'dos',
    'msdos': 'dos',
    'ibm pc': 'dos',
    'pc dos': 'dos',
    'windows': 'windows9x',
    'pc (windows)': 'windows9x',
    'commodore 64': 'c64',
    'c64': 'c64',
    'c-64': 'c64',
    'cbm 64': 'c64',
    'cbm64': 'c64',
    'commodore64': 'c64',
    'amiga': 'amiga',
    'commodore amiga': 'amiga',
    'zx spectrum': 'zxspectrum',
    'spectrum': 'zxspectrum',
    'sinclair zx spectrum': 'zxspectrum',
    'amstrad cpc': 'amstradcpc',
    'cpc': 'amstradcpc',
    'atari st': 'atarist',
    'atari ste': 'atarist',
    'st': 'atarist',
    'msx': 'msx',
    'msx2': 'msx',
    'apple ii': 'apple2',
    'apple 2': 'apple2',
    'apple iigs': 'apple2gs',
    # Atari consoles
    'atari 2600': 'atari2600',
    'atari vcs': 'atari2600',
    'vcs': 'atari2600',
    'atari 5200': 'atari5200',
    'atari 7800': 'atari7800',
    'atari jaguar': 'atarijaguar',
    'jaguar': 'atarijaguar',
    'atari lynx': 'atarilynx',
    'lynx': 'atarilynx',
    # Other consoles
    '3do': '3do',
    '3do interactive multiplayer': '3do',
    'panasonic 3do': '3do',
    'neo geo': 'neogeo',
    'neogeo': 'neogeo',
    'neo-geo': 'neogeo',
    'snk neo geo': 'neogeo',
    'neo geo aes': 'neogeo',
    'neo geo cd': 'neogeocd',
    'neogeo cd': 'neogeocd',
    'neo geo pocket': 'ngp',
    'neo geo pocket color': 'ngpc',
    'ngpc': 'ngpc',
    'turbografx-16': 'pcengine',
    'turbografx 16': 'pcengine',
    'pc engine': 'pcengine',
    'tg16': 'pcengine',
    'pc engine cd': 'pcenginecd',
    'turbografx-cd': 'pcenginecd',
    'colecovision': 'colecovision',
    'coleco': 'colecovision',
    'intellivision': 'intellivision',
    'mattel intellivision': 'intellivision',
    'vectrex': 'vectrex',
    'wonderswan': 'wonderswan',
    'wonderswan color': 'wonderswancolor',
    'arcade': 'arcade',
    'mame': 'arcade',
}

# =============================================================================
# CLZ IMPORT ROUTES
# =============================================================================

@bp.route('/clz-import')
@login_required
def clz_import():
    """CLZ Games Import — redirect to unified Game Imports page."""
    return redirect(url_for('game_imports.game_imports_page', tab='clz'))


@bp.route('/api/clz-import/parse', methods=['POST'])
@editor_required
@handle_api_errors
def api_clz_parse():
    """Parse CLZ PDF export and return game list"""
    try:
        import pdfplumber
    except ImportError:
        return error(
            'pdfplumber module not installed. Please run: pip install pdfplumber --break-system-packages',
            400,
        )

    if 'file' not in request.files:
        return error('No file uploaded', code=200)

    file = request.files['file']
    if not file.filename.lower().endswith('.pdf'):
        return error('File must be a PDF', code=200)

    # Read file content for size and magic byte validation
    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB
    content = file.read()

    if len(content) > MAX_PDF_SIZE:
        return error(f'File too large ({len(content) // (1024*1024)}MB). Maximum size is 50MB', 400)

    if not content.startswith(b'%PDF'):
        return error('Invalid PDF file (bad magic bytes)', 400)

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    games = []

    # Pass 25.5 — page-count ceiling + unconditional tmp cleanup. A
    # pathological 10 000-page PDF would block a worker for minutes
    # otherwise; the prior `os.unlink(tmp_path)` below only ran on the
    # success path so any pdfplumber exception leaked the temp file.
    max_pages = getattr(config, 'CLZ_PDF_MAX_PAGES', 500)
    # Pass 32.8: per-cell and per-list caps. Page count alone doesn't stop
    # a crafted PDF with a 100 MB text run in a single cell, or a "legal"
    # 500-page PDF with 500k rows — both land massive strings in re.sub
    # and subsequently in SQLite inserts.
    MAX_CELL_LEN = getattr(config, 'CLZ_PDF_MAX_CELL_BYTES', 4096)
    MAX_GAMES = getattr(config, 'CLZ_PDF_MAX_GAMES', 50_000)
    try:
        with pdfplumber.open(tmp_path) as pdf:
            if len(pdf.pages) > max_pages:
                return error(
                    f'PDF has {len(pdf.pages)} pages; maximum is {max_pages}.',
                    code=400,
                )
            # Store column mapping from first page (subsequent pages may not have headers)
            persistent_col_map = None

            for page_num, page in enumerate(pdf.pages):
                # Extract tables from the page
                tables = page.extract_tables()

                for table in tables:
                    if not table:
                        continue

                    # Find header row (only on pages that have one)
                    header_row = None
                    for i, row in enumerate(table):
                        if row and any('Platform' in str(cell) for cell in row if cell):
                            header_row = i
                            break

                    # Determine column mapping
                    if header_row is not None:
                        # This page has headers - parse them
                        headers = [str(h).strip().lower() if h else '' for h in table[header_row]]

                        col_map = {}
                        for i, h in enumerate(headers):
                            if 'platform' in h:
                                col_map['platform'] = i
                            elif 'title' in h:
                                col_map['title'] = i
                            elif 'release' in h:
                                col_map['release'] = i
                            elif 'publisher' in h:
                                col_map['publisher'] = i
                            elif 'developer' in h:
                                col_map['developer'] = i
                            elif 'genre' in h:
                                col_map['genre'] = i

                        if 'title' not in col_map:
                            continue

                        # Save for subsequent pages
                        persistent_col_map = col_map
                        data_start_row = header_row + 1
                    else:
                        # No header row - use mapping from previous page
                        if persistent_col_map is None:
                            continue  # Can't process without knowing columns
                        col_map = persistent_col_map
                        data_start_row = 0  # Data starts at first row

                    # Parse data rows
                    for row in table[data_start_row:]:
                        if not row or len(row) <= max(col_map.values()):
                            continue

                        title = str(row[col_map['title']]).strip() if col_map.get('title') is not None and row[col_map['title']] else ''
                        if not title or title.lower() in ('title', '', 'none'):
                            continue

                        platform = str(row[col_map.get('platform', 0)]).strip() if col_map.get('platform') is not None and row[col_map.get('platform', 0)] else ''
                        release = str(row[col_map.get('release', -1)]).strip() if col_map.get('release') is not None and col_map['release'] < len(row) and row[col_map['release']] else ''
                        publisher = str(row[col_map.get('publisher', -1)]).strip() if col_map.get('publisher') is not None and col_map['publisher'] < len(row) and row[col_map['publisher']] else ''
                        developer = str(row[col_map.get('developer', -1)]).strip() if col_map.get('developer') is not None and col_map['developer'] < len(row) and row[col_map['developer']] else ''
                        genre = str(row[col_map.get('genre', -1)]).strip() if col_map.get('genre') is not None and col_map['genre'] < len(row) and row[col_map['genre']] else ''

                        # Pass 32.8: truncate each cell to MAX_CELL_LEN before
                        # the re.sub passes below. Without this a single 100 MB
                        # cell becomes a 100 MB regex input + SQLite insert.
                        title = title[:MAX_CELL_LEN]
                        platform = platform[:MAX_CELL_LEN]
                        release = release[:MAX_CELL_LEN]
                        publisher = publisher[:MAX_CELL_LEN]
                        developer = developer[:MAX_CELL_LEN]
                        genre = genre[:MAX_CELL_LEN]

                        # Clean up extracted text - replace newlines/tabs with spaces, normalize whitespace
                        title = re.sub(r'[\n\r\t]+', ' ', title).strip()
                        title = re.sub(r'\s+', ' ', title)
                        platform = re.sub(r'[\n\r\t]+', ' ', platform).strip()
                        platform = re.sub(r'\s+', ' ', platform)
                        release = re.sub(r'[\n\r\t]+', ' ', release).strip()
                        publisher = re.sub(r'[\n\r\t]+', ' ', publisher).strip()
                        developer = re.sub(r'[\n\r\t]+', ' ', developer).strip()
                        genre = re.sub(r'[\n\r\t]+', ' ', genre).strip()

                        # Clean up None strings
                        if release == 'None': release = ''
                        if publisher == 'None': publisher = ''
                        if developer == 'None': developer = ''
                        if genre == 'None': genre = ''

                        games.append({
                            'title': title,
                            'clz_platform': platform,
                            'release_date': release,
                            'publisher': publisher,
                            'developer': developer,
                            'genre': genre
                        })
                        if len(games) >= MAX_GAMES:
                            break
                    if len(games) >= MAX_GAMES:
                        break
                if len(games) >= MAX_GAMES:
                    break
            if len(games) >= MAX_GAMES:
                logger.warning(
                    f"CLZ PDF truncated at MAX_GAMES={MAX_GAMES}; further rows skipped"
                )
    finally:
        # Always clean up the temp file, even if pdfplumber raised.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # -----------------------------------------------------------------
    # Merge rows split across PDF page boundaries
    # -----------------------------------------------------------------
    # pdfplumber extracts each page independently, so a table row that
    # spans a page break becomes two partial rows:
    #   Page N  : "PlayStation"  | "Assassin's Creed: Rogue" | "Mar 20,"
    #   Page N+1: "4"           | "Remastered"              | "2018"
    # Detect continuations: if a row's platform is unrecognized but,
    # when appended to the previous row's platform, forms a known CLZ
    # platform (or is a pure numeric fragment like "2", "4", "360").
    merged_games = []
    merge_count = 0
    for game in games:
        plat = game['clz_platform'].lower().strip()
        if plat and plat not in CLZ_PLATFORM_MAP and merged_games:
            prev = merged_games[-1]
            combined = f"{prev['clz_platform'].lower().strip()} {plat}"
            if combined in CLZ_PLATFORM_MAP or plat.isdigit():
                # Merge continuation into previous row
                prev['clz_platform'] = f"{prev['clz_platform']} {game['clz_platform']}".strip()
                for field in ('title', 'release_date', 'publisher', 'developer', 'genre'):
                    cont_val = game.get(field, '').strip()
                    if cont_val and cont_val != 'None':
                        prev_val = prev.get(field, '').strip()
                        prev[field] = f"{prev_val} {cont_val}".strip() if prev_val else cont_val
                merge_count += 1
                continue

        merged_games.append(game)

    if merge_count:
        logger.info(f"CLZ Import: Merged {merge_count} page-boundary split rows")
    games = merged_games

    # Get all systems for mapping
    systems = query("SELECT id, name, folder FROM systems ORDER BY name")
    systems_dict = {s['folder']: {'id': s['id'], 'name': s['name']} for s in systems}
    systems_map = {str(s['id']): s['name'] for s in systems}

    # Auto-create missing systems that CLZ games need
    # Collect all unique target folders from the parsed games
    needed_folders = set()
    for game in games:
        platform_lower = game['clz_platform'].lower().strip()
        matched_folder = CLZ_PLATFORM_MAP.get(platform_lower)
        if matched_folder and matched_folder not in systems_dict:
            needed_folders.add(matched_folder)

    # Auto-creating systems rows is an admin-only operation (Pass 31.7):
    # editors can import into existing systems but cannot add new ones, since
    # that's a schema-level decision and the system folder / logo convention
    # is part of library structure.
    if needed_folders and g.user and g.user.get('role') == 'admin':
        for folder in needed_folders:
            system_name = config.SYSTEM_NAME_MAP.get(folder, folder.upper())
            logo = f"{folder}.png" if os.path.isfile(os.path.join(config.IMAGE_PATH, 'systems', f'{folder}.png')) else None
            try:
                execute(
                    "INSERT OR IGNORE INTO systems (name, folder, logo) VALUES (?, ?, ?)",
                    (system_name, folder, logo)
                )
                row = query("SELECT id, name FROM systems WHERE folder = ?", (folder,), one=True)
                if row:
                    systems_dict[folder] = {'id': row['id'], 'name': row['name']}
                    systems_map[str(row['id'])] = row['name']
                    logger.info(f"CLZ Import: Auto-created system '{system_name}' (folder: {folder})")
            except Exception as e:
                logger.warning(f"CLZ Import: Failed to auto-create system '{folder}': {e}")
    elif needed_folders:
        logger.info(
            "CLZ Import: %d system folder(s) not in DB and caller is non-admin; "
            "skipping auto-create. Rows for these platforms will be unmatched: %s",
            len(needed_folders), sorted(needed_folders),
        )

    # Log available systems for debugging
    logger.info(f"CLZ Import: Available system folders: {sorted(systems_dict.keys())}")

    # Get existing games for duplicate detection (normalized for fuzzy matching).
    # Pass 25.5 — scope the SELECT to only the systems this import actually
    # references. On a 5 000+ game library importing a 50-game CLZ export of
    # just PSX + PS2, this reads ~1 000 rows instead of the whole table.
    target_system_ids = set()
    for game in games:
        platform_lower = game['clz_platform'].lower().strip()
        matched_folder = CLZ_PLATFORM_MAP.get(platform_lower)
        if matched_folder and matched_folder in systems_dict:
            target_system_ids.add(systems_dict[matched_folder]['id'])

    existing_games = {}
    if target_system_ids:
        id_list = sorted(target_system_ids)
        placeholders = ','.join('?' * len(id_list))
        rows = query(
            f"SELECT id, title, system_id FROM games WHERE system_id IN ({placeholders})",
            tuple(id_list),
        )
        for game in rows:
            key = (normalize_title(game['title']), game['system_id'])
            existing_games[key] = game['id']

    # Match platforms and check for duplicates
    unmatched_platforms = set()
    for game in games:
        platform_lower = game['clz_platform'].lower().strip()

        # Try to find matching system
        matched_folder = CLZ_PLATFORM_MAP.get(platform_lower)
        if matched_folder and matched_folder in systems_dict:
            system_info = systems_dict[matched_folder]
            game['system_id'] = system_info['id']
            game['system_name'] = system_info['name']
            game['system_folder'] = matched_folder

            # Check if game already exists (normalized matching)
            key = (normalize_title(game['title']), system_info['id'])
            game['existing'] = key in existing_games
        else:
            game['system_id'] = None
            game['system_name'] = None
            game['system_folder'] = None
            game['existing'] = False
            # Track unmatched for logging
            if platform_lower:
                if matched_folder:
                    unmatched_platforms.add(f"{platform_lower} -> {matched_folder} (system not in DB)")
                else:
                    unmatched_platforms.add(f"{platform_lower} (no mapping)")

        game['selected'] = False

    # Log unmatched platforms to help with debugging
    if unmatched_platforms:
        logger.info(f"CLZ Import: Unmatched platforms: {sorted(unmatched_platforms)}")

    logger.info(f"CLZ Import: Parsed {len(games)} games from PDF")

    return success(games=games, systems_map=systems_map)


@bp.route('/api/clz-import/import', methods=['POST'])
@editor_required
@handle_api_errors
def api_clz_import():
    """Import selected games from CLZ"""
    data = request.get_json()
    games = data.get('games', [])

    if not games:
        return error('No games to import', code=200)

    imported = 0
    skipped = 0
    failed = 0

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        # Build normalized lookup for duplicate detection (handles diacritics/punctuation)
        existing_norm = set()
        for row in c.execute("SELECT title, system_id FROM games").fetchall():
            existing_norm.add((normalize_title(row['title']), row['system_id']))

        for game in games:
            try:
                # Check if game already exists (normalized matching)
                if (normalize_title(game['title']), game['system_id']) in existing_norm:
                    skipped += 1
                    continue

                # Generate a placeholder ROM path (CLZ games don't have ROMs)
                system_folder = game.get('system_folder', 'unknown')
                safe_title = re.sub(r'[<>:"/\\|?*]', '', game['title'])
                rom_path = f"clz_import/{system_folder}/{safe_title}"

                # Parse release date if present
                release_date = None
                if game.get('release_date'):
                    try:
                        # Handle "Nov 09, 2018" format
                        dt = datetime.strptime(game['release_date'], '%b %d, %Y')
                        release_date = dt.strftime('%Y-%m-%d')
                    except (ValueError, TypeError):
                        try:
                            # Try just year
                            year = re.search(r'\d{4}', game['release_date'])
                            if year:
                                release_date = f"{year.group()}-01-01"
                        except (TypeError, AttributeError):
                            pass

                # Insert the game
                c.execute("""
                    INSERT INTO games (
                        title, system_id, rom_path, scraped,
                        publisher, developer, genre, release_date,
                        clz_title, created_at
                    ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """, (
                    game['title'],
                    game['system_id'],
                    rom_path,
                    game.get('publisher', ''),
                    game.get('developer', ''),
                    game.get('genre', ''),
                    release_date,
                    game['title'],
                    datetime.now(timezone.utc).isoformat()
                ))

                imported += 1
                # Track newly imported game to prevent batch duplicates
                existing_norm.add((normalize_title(game['title']), game['system_id']))

            except Exception as e:
                logger.error(f"CLZ Import: Failed to import '{game.get('title')}': {e}")
                failed += 1

        conn.commit()

        logger.info(f"CLZ Import complete: {imported} imported, {skipped} skipped, {failed} failed")

        if imported:
            invalidate_analytics_cache()
        return success(imported=imported, skipped=skipped, failed=failed)
    finally:
        if conn:
            conn.close()
