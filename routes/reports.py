# =============================================================================
# RETRODB - Reports Blueprint
# =============================================================================
# ROM Reports and naming validation routes
# Extracted from app.py for better code organization
# =============================================================================

from flask import Blueprint, render_template, request
from flask_babel import gettext as _
import os
import shutil
import re
import glob
import logging

# Import configuration
import config

# Import services layer
from services.database import query, execute
from services.game_utils import get_system_type, build_filename
from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, editor_required
from services.security import safe_filename, safe_path
import settings_manager

# Configure logger
logger = logging.getLogger('rom_reports')

# Create blueprint
reports_bp = Blueprint('reports', __name__)


def _get_rom_path():
    """v3.6.5 — resolve rom_path at call time via settings_manager.
    config.ROM_PATH is the hardcoded `""` default and is never mutated at
    runtime; reading it directly meant multi-disc scan / create-M3U used an
    empty base path regardless of user settings."""
    return settings_manager.get_effective_path('rom_path', config.ROM_PATH)

# =============================================================================
# CONSTANTS - ROM Naming Standards
# =============================================================================

# Invalid filename characters to check
INVALID_CHARS = [':', '?', '*', '/', '\\', '"', '<', '>', '|']

# Region patterns to match
REGION_PATTERNS = [
    r'\(USA\)', r'\(Europe\)', r'\(Japan\)', r'\(World\)',
    r'\(Germany\)', r'\(France\)', r'\(Spain\)', r'\(Italy\)',
    r'\(Australia\)', r'\(Brazil\)', r'\(Korea\)', r'\(Asia\)',
    r'\(En\)', r'\(Eu\)', r'\(JP\)', r'\(US\)'
]

# Year pattern
YEAR_PATTERN = r'\((?:19|20)\d{2}\)'

# Publisher pattern (any word in parentheses that's not a region/year)
PUBLISHER_PATTERN = r'\([A-Za-z][A-Za-z0-9\s\.\-&]+\)'


# =============================================================================
# PAGE ROUTES
# =============================================================================

@reports_bp.route('/reports')
@login_required
def reports():
    """ROM Reports page"""
    return render_template('reports.html')


# =============================================================================
# API ROUTES - Naming Check
# =============================================================================

@reports_bp.route('/api/reports/naming-check')
@login_required
@handle_api_errors
def api_reports_naming_check():
    """Check ROM filenames against naming standard"""
    issues = []
    systems = set()
    
    # Get all games from database (join with systems to get system folder)
    games = query("""
        SELECT g.id, g.title, s.folder AS system, s.name AS system_name,
               g.rom_path, g.region, g.release_date, g.publisher,
               g.developer, g.genre
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.rom_path IS NOT NULL AND g.rom_path != ''
          AND g.rom_path NOT LIKE '%_import/%'
    """)
    
    for game in games:
        game_id = game['id']
        title = game['title'] or ''
        system = game['system'] or 'unknown'
        rom_path = game['rom_path'] or ''
        region = game['region'] or ''
        release_date = game['release_date'] or ''
        publisher = game['publisher'] or ''
        
        systems.add(system)
        
        if not rom_path:
            continue
        
        filename = os.path.basename(rom_path)
        name_without_ext = os.path.splitext(filename)[0]
        
        found_issues = []
        suggested = None
        
        # Check for invalid characters
        for char in INVALID_CHARS:
            if char in filename:
                found_issues.append('invalid-chars')
                break
        
        # Check for underscores
        if '_' in name_without_ext:
            found_issues.append('underscore')
        
        # Check for square brackets (should be parentheses)
        if '[' in filename or ']' in filename:
            found_issues.append('bracket')
        
        # Check for moved article based on article_placement setting
        article_placement = settings_manager.get_setting('article_placement', 'beginning')
        if article_placement == 'beginning':
            # Articles at end are wrong when placement is 'beginning'
            if re.search(r',\s*(The|A|An)$', name_without_ext, re.IGNORECASE):
                found_issues.append('moved-article')
        else:
            # Articles at beginning are wrong when placement is 'end'
            if re.search(r'^(The|An|A)\s+(?![.\-])', name_without_ext, re.IGNORECASE):
                found_issues.append('moved-article')
        
        system_type = get_system_type(system)
        system_name = game['system_name'] or ''
        developer = game['developer'] or ''
        genre = game['genre'] or ''

        # Load user's naming convention for this system type
        naming_settings = settings_manager.get_setting('naming_convention', {})
        tags = naming_settings.get(system_type, ['region'])

        # Check which tags are expected but missing in the filename
        if 'region' in tags:
            has_region = any(re.search(pattern, filename, re.IGNORECASE) for pattern in REGION_PATTERNS)
            if not has_region:
                found_issues.append('missing-region')

        if 'year' in tags:
            has_year = bool(re.search(YEAR_PATTERN, filename))
            if not has_year:
                found_issues.append('missing-year')

        if 'publisher' in tags:
            paren_contents = re.findall(r'\(([^)]+)\)', filename)
            has_publisher = False
            for content in paren_contents:
                if not re.match(r'^(?:19|20)\d{2}$', content):
                    has_publisher = True
                    break
            if not has_publisher:
                found_issues.append('missing-publisher')

        # Generate suggested name using build_filename
        if found_issues and title:
            clean_title = title
            for char, repl in [(':', ' -'), ('?', ''), ('*', ''), ('/', '-'), ('\\', '-'), ('"', "'"), ('<', ''), ('>', ''), ('|', '-')]:
                clean_title = clean_title.replace(char, repl)
            clean_title = clean_title.strip()

            if clean_title:
                ext = os.path.splitext(filename)[1]
                game_data = {
                    'region': region or 'USA',
                    'release_date': release_date,
                    'publisher': publisher or 'Publisher',
                    'developer': developer or 'Developer',
                    'genre': genre,
                    'system_type': system_type,
                    'system_name': system_name,
                }
                suggested = build_filename(clean_title, ext, tags, game_data)
        
        if found_issues:
            issues.append({
                'game_id': game_id,
                'system': system,
                'filename': filename,
                'issues': found_issues,
                'suggested': suggested
            })
    
    return success(
        issues=issues,
        systems=list(systems),
        total_checked=len(games),
    )
    


# =============================================================================
# API ROUTES - Name Mismatch Check
# =============================================================================

@reports_bp.route('/api/reports/name-mismatch')
@login_required
@handle_api_errors
def api_reports_name_mismatch():
    """Check if ROM filenames match scraped titles"""
    mismatches = []
    
    # Get all games with scraped titles (join with systems to get system folder)
    games = query("""
        SELECT g.id, g.title, s.folder AS system, s.name AS system_name,
               g.rom_path, g.region, g.release_date,
               g.publisher, g.developer, g.genre
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.rom_path IS NOT NULL AND g.rom_path != ''
          AND g.title IS NOT NULL AND g.title != ''
          AND g.rom_path NOT LIKE '%_import/%'
    """)
    
    # Helper: normalise a string for title comparison
    def normalize(s):
        from services.game_utils import normalize_article_for_comparison
        s = normalize_article_for_comparison(s)
        s = s.lower()
        s = re.sub(r"[''`]", "'", s)
        s = re.sub(r'[:\-–—/\\]', ' ', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    # Helper: extract the region tag value from a filename (e.g. "USA")
    region_re = re.compile(
        r'\((USA|Europe|Japan|World|Germany|France|Spain|Italy|'
        r'Australia|Brazil|Korea|Asia|En|Eu|JP|US'
        r'(?:,\s*(?:USA|Europe|Japan|World|Germany|France|Spain|Italy|'
        r'Australia|Brazil|Korea|Asia|En|Eu|JP|US))*)\)',
        re.IGNORECASE
    )
    year_re = re.compile(r'\(((?:19|20)\d{2})\)')

    # Region alias map for comparison (filename value → canonical forms)
    region_aliases = {
        'usa': ['usa', 'us', 'north america'],
        'us': ['usa', 'us', 'north america'],
        'north america': ['usa', 'us', 'north america'],
        'europe': ['europe', 'eu', 'pal'],
        'eu': ['europe', 'eu', 'pal'],
        'pal': ['europe', 'eu', 'pal'],
        'japan': ['japan', 'jp'],
        'jp': ['japan', 'jp'],
        'world': ['world', 'worldwide'],
        'worldwide': ['world', 'worldwide'],
        'en': ['usa', 'us', 'north america', 'en'],
    }

    def regions_match(file_region, db_region):
        """Case-insensitive region comparison with alias support."""
        fr = file_region.lower().strip()
        dr = db_region.lower().strip()
        if fr == dr:
            return True
        aliases = region_aliases.get(fr, [fr])
        return dr in aliases

    for game in games:
        game_id = game['id']
        scraped_title = game['title']
        system = game['system'] or 'unknown'
        rom_path = game['rom_path']

        filename = os.path.basename(rom_path)
        name_without_ext = os.path.splitext(filename)[0]

        # Extract game name from filename (remove parenthetical tags)
        filename_name = re.sub(r'\s*\([^)]+\)\s*', ' ', name_without_ext).strip()

        norm_filename = normalize(filename_name)
        norm_scraped = normalize(scraped_title)

        # --- Detect mismatch types ---
        mismatch_types = []

        # Title mismatch
        if norm_filename != norm_scraped:
            common = len(set(norm_filename.split()) & set(norm_scraped.split()))
            total = max(len(norm_filename.split()), len(norm_scraped.split()))
            similarity = common / total if total > 0 else 0
            if similarity < 0.7:
                mismatch_types.append('title')

        # Region mismatch: compare filename region tag with DB region
        db_region = game['region'] or ''
        file_region_m = region_re.search(name_without_ext)
        if file_region_m and db_region:
            # Handle multi-region tags like "(USA, Europe)" — check first value
            file_region_val = file_region_m.group(1).split(',')[0].strip()
            if not regions_match(file_region_val, db_region):
                mismatch_types.append('region')

        # Year mismatch: compare filename year tag with DB release year
        db_release = game['release_date'] or ''
        db_year_m = re.search(r'(19|20)\d{2}', db_release)
        db_year = db_year_m.group(0) if db_year_m else ''
        file_year_m = year_re.search(name_without_ext)
        if file_year_m and db_year:
            if file_year_m.group(1) != db_year:
                mismatch_types.append('year')

        if not mismatch_types:
            continue

        region = db_region or 'USA'
        release_date = game['release_date'] or ''
        publisher = game['publisher'] or ''
        developer = game['developer'] or ''
        genre = game['genre'] or ''
        system_name = game['system_name'] or ''
        system_type = get_system_type(system)

        # Load user's naming convention for this system type
        naming_settings = settings_manager.get_setting('naming_convention', {})
        tags = naming_settings.get(system_type, ['region'])

        # Build the suggested filename so the UI can show it
        clean_title = scraped_title
        for char, repl in [(':', ' -'), ('?', ''), ('*', ''), ('/', '-'), ('\\', '-'), ('"', "'"), ('<', ''), ('>', ''), ('|', '-')]:
            clean_title = clean_title.replace(char, repl)
        clean_title = clean_title.strip()
        ext = os.path.splitext(filename)[1].lower()

        suggested = ''
        if clean_title:
            game_data = {
                'region': region,
                'release_date': release_date,
                'publisher': publisher,
                'developer': developer,
                'genre': genre,
                'system_type': system_type,
                'system_name': system_name,
            }
            suggested = build_filename(clean_title, ext, tags, game_data)

        # Skip if the suggested name matches the current filename
        # (rename would be a no-op)
        if suggested and suggested == filename:
            continue

        mismatches.append({
            'game_id': game_id,
            'system': system,
            'system_name': system_name,
            'filename': filename,
            'scraped_title': scraped_title,
            'mismatch_types': mismatch_types,
            'system_type': system_type,
            'convention_tags': tags,
            'region': region,
            'release_date': release_date,
            'suggested_name': suggested
        })
    
    return success(
        mismatches=mismatches,
        total_checked=len(games),
    )
    


# =============================================================================
# API ROUTES - Multi-Disc Scan
# =============================================================================

@reports_bp.route('/api/reports/multidisc-scan', methods=['POST'])
@login_required
@handle_api_errors
def api_reports_multidisc_scan():
    """Scan for loose multi-disc files that need to be organized"""
    data = request.get_json() or {}
    system_filter = data.get('system', '')
    
    # Disc-based systems (expanded list)
    disc_systems = [
        'psx', 'ps2', 'ps3', 'saturn', 'segacd', 'dreamcast', 
        '3do', 'pcenginecd', 'pcfx', 'neogeocd', 'gc', 'wii', 'wiiu'
    ]
    
    if system_filter:
        # Look up the system folder name from the database.
        # Pass 25.2 — previously fell back to `disc_systems = [system_filter]`
        # on lookup miss, so a `system='../../etc'` value flowed into the
        # subsequent `os.path.join(config.ROM_PATH, system)` + glob() calls
        # and enumerated outside ROM_PATH. Reject unknown values outright.
        system_info = query("SELECT folder FROM systems WHERE id = ? OR folder = ?",
                          (system_filter, system_filter), one=True)
        if not system_info:
            return error(_('Unknown system'), 400)
        disc_systems = [system_info['folder']]
    
    # Disc file extensions (expanded)
    disc_extensions = ['.bin', '.iso', '.cue', '.img', '.mdf', '.chd', '.cso', '.pbp', '.rvz', '.wbfs', '.gcz']
    
    # Pattern to match disc numbers
    disc_patterns = [
        r'\(Disc\s*(\d+)\s*(?:of\s*(\d+))?\)',  # (Disc 1 of 3) or (Disc 1)
        r'\(CD\s*(\d+)\)',  # (CD 1)
        r'\(Disk\s*(\d+)\)',  # (Disk 1)
        r'Disc\s*(\d+)',  # Disc 1
        r'CD\s*(\d+)',  # CD 1
        r'd(\d+)(?!\d)',  # d1, d2 (but not d10 matched as d1)
    ]
    
    multi_disc_games = []
    scanned_systems = []

    rom_path = _get_rom_path()
    if not rom_path:
        return error(_('ROM path not configured. Go to Settings → Paths to set it.'), 400)

    for system in disc_systems:
        system_path = os.path.join(rom_path, system)
        if not os.path.exists(system_path):
            continue
        
        scanned_systems.append(system)
        
        # Find all disc files in this system folder (top level only - not in subdirectories)
        disc_files = []
        for ext in disc_extensions:
            # Only look at top level files
            found = glob.glob(os.path.join(system_path, f'*{ext}'))
            disc_files.extend(found)
            # Also check case-insensitive
            if ext != ext.upper():
                found_upper = glob.glob(os.path.join(system_path, f'*{ext.upper()}'))
                disc_files.extend(found_upper)
        
        logger.info(f"Multi-disc scan: Found {len(disc_files)} top-level disc files in {system}")
        
        # Also scan subdirectories for multi-disc games that might need M3U files
        subfolders = [d for d in os.listdir(system_path) 
                     if os.path.isdir(os.path.join(system_path, d)) 
                     and not d.startswith('.')]
        
        for subfolder in subfolders:
            subfolder_path = os.path.join(system_path, subfolder)
            m3u_exists = os.path.exists(os.path.join(system_path, f"{subfolder}.m3u"))
            
            # Count disc files in this subfolder
            subfolder_disc_files = []
            for ext in disc_extensions:
                found = glob.glob(os.path.join(subfolder_path, f'*{ext}'))
                subfolder_disc_files.extend(found)
                if ext != ext.upper():
                    found_upper = glob.glob(os.path.join(subfolder_path, f'*{ext.upper()}'))
                    subfolder_disc_files.extend(found_upper)
            
            # Check if any files look like multi-disc
            has_disc_indicator = False
            for filepath in subfolder_disc_files:
                filename = os.path.basename(filepath)
                for pattern in disc_patterns:
                    if re.search(pattern, filename, re.IGNORECASE):
                        has_disc_indicator = True
                        break
                if has_disc_indicator:
                    break
            
            # If folder has multiple disc files without M3U, report it
            if len(subfolder_disc_files) >= 2 and has_disc_indicator and not m3u_exists:
                multi_disc_games.append({
                    'system': system,
                    'name': subfolder,
                    'disc_count': len(subfolder_disc_files),
                    'files': sorted([os.path.basename(f) for f in subfolder_disc_files]),
                    'path': system_path,
                    'in_folder': True,
                    'needs_m3u': True
                })
                logger.info(f"Multi-disc scan: Found folder '{subfolder}' with {len(subfolder_disc_files)} discs but no M3U")
        
        # Group by base game name
        game_groups = {}
        
        for filepath in disc_files:
            filename = os.path.basename(filepath)
            name_without_ext = os.path.splitext(filename)[0]
            
            # Check if this is a disc file
            disc_match = None
            for pattern in disc_patterns:
                match = re.search(pattern, name_without_ext, re.IGNORECASE)
                if match:
                    disc_match = match
                    break
            
            if disc_match:
                # Extract base game name (everything BEFORE the disc indicator)
                # Find the start position of the disc indicator match
                disc_start = disc_match.start()
                base_name = name_without_ext[:disc_start].strip()
                
                # If base_name is empty (disc indicator at start), use the whole name without disc
                if not base_name:
                    base_name = re.sub(r'\s*\(Disc\s*\d+(?:\s*of\s*\d+)?\)\s*', ' ', name_without_ext, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s*\(CD\s*\d+\)\s*', ' ', base_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s*\(Disk\s*\d+\)\s*', ' ', base_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s*Disc\s*\d+\s*', ' ', base_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s*CD\s*\d+\s*', ' ', base_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s*d\d+\s*', ' ', base_name, flags=re.IGNORECASE)
                    base_name = re.sub(r'\s+', ' ', base_name).strip()
                
                # Look for region tag in the full filename (usually at the end)
                region_pattern = r'\((USA|Europe|Japan|World|Germany|France|Spain|Italy|Australia|Brazil|Korea|En|Ja|De|Fr|Es|It|Pt|Nl|Sv|No|Da|Fi|Ru|Pl|Zh|Ko)\)'
                region_match = re.search(region_pattern, name_without_ext, re.IGNORECASE)
                if region_match:
                    region = region_match.group(0)  # e.g., "(USA)"
                    # Only append if not already in base_name
                    if region.lower() not in base_name.lower():
                        base_name = f"{base_name} {region}"
                
                key = (system, base_name)
                if key not in game_groups:
                    game_groups[key] = []
                game_groups[key].append(filename)
                logger.info(f"Multi-disc scan: Matched '{filename}' -> base name '{base_name}'")
        
        # Add games with multiple discs that are NOT already organized
        for (sys, name), files in game_groups.items():
            if len(files) >= 2:
                # Check if there's already an M3U or folder for this game
                m3u_path = os.path.join(system_path, f"{name}.m3u")
                folder_path = os.path.join(system_path, name)
                
                has_m3u = os.path.exists(m3u_path)
                has_folder = os.path.isdir(folder_path)
                
                if not has_m3u and not has_folder:
                    multi_disc_games.append({
                        'system': sys,
                        'name': name,
                        'disc_count': len(files),
                        'files': sorted(files),
                        'path': system_path
                    })
                    logger.info(f"Multi-disc scan: Found loose game '{name}' with {len(files)} discs")
                else:
                    logger.info(f"Multi-disc scan: Skipping '{name}' - already organized (M3U: {has_m3u}, Folder: {has_folder})")
    
    logger.info(f"Multi-disc scan complete: {len(multi_disc_games)} loose games found, scanned systems: {scanned_systems}")
    
    return success(
        games=multi_disc_games,
        scanned_systems=scanned_systems,
        debug_info={
            'systems_checked': scanned_systems,
            'total_loose_games': len(multi_disc_games),
        },
    )
    


# =============================================================================
# API ROUTES - Organize Multi-Disc
# =============================================================================

@reports_bp.route('/api/reports/organize-multidisc', methods=['POST'])
@editor_required
@handle_api_errors
def api_reports_organize_multidisc():
    """Organize loose multi-disc files into a folder with M3U"""
    data = request.get_json() or {}
    system = data.get('system')
    name = data.get('name')
    files = data.get('files', [])
    in_folder = data.get('in_folder', False)  # True if files are already in a folder
    
    if not system or not name or not files:
        return error(_('Missing required parameters'), 400)

    rom_path = _get_rom_path()
    if not rom_path:
        return error(_('ROM path not configured. Go to Settings → Paths to set it.'), 400)

    system_path = os.path.join(rom_path, system)
    folder_path = os.path.join(system_path, name)

    if safe_path(folder_path, rom_path) is None:
        return error(_('Invalid path'), 400)
    m3u_path = os.path.join(system_path, f"{name}.m3u")

    if in_folder:
        # Files are already in folder, just create M3U
        if not os.path.isdir(folder_path):
            return error(_('Folder does not exist: %(folder_path)s') % {'folder_path': folder_path}, 400)
        
        # Create noload.txt if it doesn't exist
        noload_path = os.path.join(folder_path, 'noload.txt')
        if not os.path.exists(noload_path):
            with open(noload_path, 'w') as f:
                pass  # Empty file
        
        # Create M3U file
        with open(m3u_path, 'w', encoding='utf-8') as f:
            for filename in sorted(files):
                if safe_filename(filename):
                    f.write(f"{name}/{filename}\n")
        
        logger.info(f"Created M3U for existing folder: {name} ({len(files)} discs)")
        
        return success(
            m3u_path=m3u_path,
            folder_path=folder_path,
            files_moved=0,
            created_m3u_only=True,
        )
    
    # Standard case: move loose files into folder
    
    # Create the folder
    os.makedirs(folder_path, exist_ok=True)
    
    # Move files to the folder
    moved_files = []
    for filename in files:
        if not safe_filename(filename):
            continue
        src = os.path.join(system_path, filename)
        dst = os.path.join(folder_path, filename)
        
        if os.path.exists(src):
            shutil.move(src, dst)
            moved_files.append(filename)
    
    # Create noload.txt
    noload_path = os.path.join(folder_path, 'noload.txt')
    with open(noload_path, 'w') as f:
        pass  # Empty file
    
    # Create M3U file
    with open(m3u_path, 'w', encoding='utf-8') as f:
        for filename in sorted(moved_files):
            f.write(f"{name}/{filename}\n")
    
    logger.info(f"Organized multi-disc game: {name} ({len(moved_files)} discs)")
    
    return success(
        m3u_path=m3u_path,
        folder_path=folder_path,
        files_moved=len(moved_files),
    )
    


# =============================================================================
# API ROUTES - Rename ROM
# =============================================================================

@reports_bp.route('/api/reports/rename-rom', methods=['POST'])
@editor_required
@handle_api_errors
def api_reports_rename_rom():
    """Rename a ROM file (handles M3U files with associated folders)"""
    data = request.get_json() or {}
    game_id = data.get('game_id')
    new_name = data.get('new_name')
    
    if not game_id or not new_name:
        return error(_('Missing game_id or new_name'), 400)

    if not safe_filename(new_name):
        return error(_('Invalid filename'), 400)

    # Get game info
    game = query("SELECT rom_path FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    old_path = game['rom_path']
    if not old_path:
        return error(_('No ROM path set'), 404)

    # CLZ imports have virtual paths — just update the database
    is_virtual = old_path.startswith(('clz_import/', 'steam_import/', 'xbox_import/', 'psn_import/'))
    if is_virtual:
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))
        return success(
            old_name=os.path.basename(old_path),
            new_name=new_name,
            new_path=new_path,
            is_m3u=False,
        )

    if not os.path.exists(old_path):
        return error(_('ROM file not found'), 404)

    # Build new path
    dir_path = os.path.dirname(old_path)
    new_path = os.path.join(dir_path, new_name)

    # Check if new name already exists
    if os.path.exists(new_path) and new_path != old_path:
        return error(_('A file with that name already exists'), 400)

    # Check if this is an M3U file
    old_ext = os.path.splitext(old_path)[1].lower()
    new_ext = os.path.splitext(new_name)[1].lower()
    is_m3u = old_ext == '.m3u'

    # Validate extension match for M3U
    if is_m3u and new_ext != '.m3u':
        return error(_('M3U files must keep the .m3u extension'), 400)

    # Handle M3U files specially - need to rename folder and update M3U contents
    if is_m3u:
        old_base_name = os.path.splitext(os.path.basename(old_path))[0]
        new_base_name = os.path.splitext(new_name)[0]
        old_folder = os.path.join(dir_path, old_base_name)
        new_folder = os.path.join(dir_path, new_base_name)
        
        # Check if associated folder exists
        if os.path.isdir(old_folder):
            # Check if new folder name already exists
            if os.path.exists(new_folder) and new_folder != old_folder:
                return error(_('A folder with the new name already exists'), 400)

            # Rename the folder first
            if new_folder != old_folder:
                os.rename(old_folder, new_folder)
                logger.info(f"Renamed M3U folder: {old_folder} -> {new_folder}")

            # Update M3U contents to reference new folder name
            if os.path.exists(old_path):
                try:
                    with open(old_path, 'r', encoding='utf-8') as f:
                        m3u_contents = f.read()

                    # Replace old folder name with new folder name in paths
                    updated_contents = m3u_contents.replace(f"{old_base_name}/", f"{new_base_name}/")

                    # Write updated contents
                    with open(old_path, 'w', encoding='utf-8') as f:
                        f.write(updated_contents)

                    logger.info(f"Updated M3U contents: {old_base_name}/ -> {new_base_name}/")
                except Exception as e:
                    logger.warning(f"Failed to update M3U contents: {e}")

    # Rename the main file (ROM or M3U)
    if new_path != old_path:
        os.rename(old_path, new_path)

    # Update database
    execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))

    logger.info(f"Renamed ROM: {old_path} -> {new_path}")

    return success(
        old_name=os.path.basename(old_path),
        new_name=new_name,
        new_path=new_path,
        is_m3u=is_m3u,
    )
    


# =============================================================================
# API ROUTES - Rename to Scraped Title
# =============================================================================

@reports_bp.route('/api/reports/rename-to-scraped', methods=['POST'])
@editor_required
@handle_api_errors
def api_reports_rename_to_scraped():
    """Rename a ROM file to match its scraped title"""
    data = request.get_json() or {}
    game_id = data.get('game_id')
    
    if not game_id:
        return error(_('Missing game_id'), 400)

    # Get game info (join with systems to get system folder)
    game = query("""
        SELECT g.rom_path, s.folder AS system, s.name AS system_name,
               g.title, g.region, g.release_date,
               g.publisher, g.developer, g.genre
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    old_path = game['rom_path']
    if not old_path:
        return error(_('No ROM path set'), 404)

    is_virtual = old_path.startswith(('clz_import/', 'steam_import/', 'xbox_import/', 'psn_import/'))

    if not is_virtual and not os.path.exists(old_path):
        return error(_('ROM file not found'), 404)

    title = game['title']
    if not title:
        return error(_('No scraped title available'), 400)

    system = game['system'] or ''
    region = game['region'] or 'USA'
    release_date = game['release_date'] or ''
    publisher = game['publisher'] or ''
    developer = game['developer'] or ''
    genre = game['genre'] or ''
    system_name_val = game['system_name'] or ''
    system_type = get_system_type(system)

    # Clean title for filename
    clean_title = title
    for char, repl in [(':', ' -'), ('?', ''), ('*', ''), ('/', '-'), ('\\', '-'), ('"', "'"), ('<', ''), ('>', ''), ('|', '-')]:
        clean_title = clean_title.replace(char, repl)
    clean_title = clean_title.strip()

    if not clean_title:
        return error(_('Title is empty after sanitization'), 400)

    ext = os.path.splitext(old_path)[1].lower()
    is_m3u = ext == '.m3u'

    # Load user's naming convention for this system type
    naming_settings = settings_manager.get_setting('naming_convention', {})
    tags = naming_settings.get(system_type, ['region'])

    game_data = {
        'region': region,
        'release_date': release_date,
        'publisher': publisher,
        'developer': developer,
        'genre': genre,
        'system_type': system_type,
        'system_name': system_name_val,
    }
    new_base_name = build_filename(clean_title, '', tags, game_data)

    new_name = new_base_name + ext

    if not safe_filename(new_name):
        return error(_('Generated filename contains invalid characters'), 400)

    # CLZ imports have virtual paths — just update the database
    if is_virtual:
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))
        return success(
            old_name=os.path.basename(old_path),
            new_name=new_name,
            new_path=new_path,
            is_m3u=False,
        )

    # Build new path
    dir_path = os.path.dirname(old_path)
    new_path = os.path.join(dir_path, new_name)

    # Check if new name already exists
    if os.path.exists(new_path) and new_path != old_path:
        return error(_('A file with that name already exists'), 400)

    # Handle M3U files specially - need to rename folder and update M3U contents
    if is_m3u:
        old_base_name = os.path.splitext(os.path.basename(old_path))[0]
        old_folder = os.path.join(dir_path, old_base_name)
        new_folder = os.path.join(dir_path, new_base_name)
        
        # Check if associated folder exists
        if os.path.isdir(old_folder):
            # Check if new folder name already exists
            if os.path.exists(new_folder) and new_folder != old_folder:
                return error(_('A folder with the new name already exists'), 400)
            
            # Rename the folder first
            if new_folder != old_folder:
                os.rename(old_folder, new_folder)
                logger.info(f"Renamed M3U folder: {old_folder} -> {new_folder}")
            
            # Update M3U contents to reference new folder name
            if os.path.exists(old_path):
                try:
                    with open(old_path, 'r', encoding='utf-8') as f:
                        m3u_contents = f.read()
                    
                    # Replace old folder name with new folder name in paths
                    updated_contents = m3u_contents.replace(f"{old_base_name}/", f"{new_base_name}/")
                    
                    # Write to new location (or same if just updating contents)
                    with open(old_path, 'w', encoding='utf-8') as f:
                        f.write(updated_contents)
                    
                    logger.info(f"Updated M3U contents: {old_base_name}/ -> {new_base_name}/")
                except Exception as e:
                    logger.warning(f"Failed to update M3U contents: {e}")
    
    # Rename the main file (ROM or M3U)
    if new_path != old_path:
        os.rename(old_path, new_path)
        
        # Update database
        execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))
        
        logger.info(f"Renamed ROM to scraped title: {old_path} -> {new_path}")
    
    return success(
        old_name=os.path.basename(old_path),
        new_name=new_name,
        new_path=new_path,
        is_m3u=is_m3u,
    )
    
