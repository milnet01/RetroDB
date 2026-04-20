# =============================================================================
# ROM SCANNER
# =============================================================================
# Scans ES-DE formatted ROM directories and adds games to database
# =============================================================================

import os
import logging
import sys
from datetime import datetime, timezone

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ROM_PATH, SYSTEM_NAME_MAP
from scraper.base_scraper import get_scraper_conn

logger = logging.getLogger(__name__)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_systeminfo(system_path):
    """Parse ES-DE systeminfo.txt for supported extensions"""
    info_file = os.path.join(system_path, 'systeminfo.txt')
    extensions = set()
    
    if not os.path.exists(info_file):
        return extensions
    
    current_key = None
    
    try:
        with open(info_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                
                if not line:
                    current_key = None
                    continue
                
                if line.endswith(':'):
                    current_key = line[:-1].strip().lower()
                    continue
                
                if current_key == 'supported file extensions':
                    for ext in line.split():
                        if ext.startswith('.'):
                            extensions.add(ext.lower())
    except Exception as e:
        logger.error(f"Error parsing systeminfo.txt: {e}")
    
    return extensions


def clean_title(filename):
    """Convert ROM filename into a clean title"""
    name = os.path.splitext(filename)[0]
    
    # Remove common tags
    tags = [
        '(USA)', '(Europe)', '(Japan)', '(World)', '(En)', '(Fr)', '(De)', '(Es)', '(It)',
        '(U)', '(E)', '(J)', '(W)',
        '[!]', '(Rev', '(v', '[b', '[h', '[a', '[o', '[p', '[t', '[f',
        '(Demo)', '(Proto)', '(Beta)', '(Sample)', '(Unl)',
        '(Hack)', '(PD)', '(Pirate)'
    ]
    
    for tag in tags:
        if tag in name:
            name = name.split(tag)[0]
    
    # Clean up remaining artifacts
    name = name.replace('_', ' ')
    name = name.replace('  ', ' ')
    
    # Normalize colon formatting: " : " -> ": " and " :" -> ":"
    name = name.replace(' : ', ': ')
    name = name.replace(' :', ':')
    
    # Convert ' - ' to ': ' for subtitle separation (common ROM naming convention)
    # Only convert if followed by uppercase letter (indicates subtitle)
    import re
    name = re.sub(r' - (?=[A-Z])', ': ', name)
    
    name = name.strip()
    
    return name


# =============================================================================
# MAIN SCANNER
# =============================================================================

def scan_roms():
    """Scan ROM directories and add games to database"""
    logger.info("=" * 60)
    logger.info("Starting ROM scan")
    logger.info(f"ROM Path: {ROM_PATH}")
    logger.info("=" * 60)
    
    if not os.path.exists(ROM_PATH):
        logger.error(f"ROM path does not exist: {ROM_PATH}")
        return 0
    
    conn = get_scraper_conn()
    c = conn.cursor()

    new_games = 0
    systems_processed = 0
    
    # Sort system folders alphabetically
    try:
        folders = sorted(os.listdir(ROM_PATH), key=str.lower)
    except Exception as e:
        logger.error(f"Error listing ROM directory: {e}")
        conn.close()
        return 0
    
    for folder in folders:
        system_path = os.path.join(ROM_PATH, folder)
        
        if not os.path.isdir(system_path):
            continue
        
        # Skip hidden folders and special directories
        if folder.startswith('.') or folder in ['downloads', 'themes', 'roms']:
            continue
        
        # Get system name from mapping or generate from folder name
        system_name = SYSTEM_NAME_MAP.get(folder, folder.replace('_', ' ').title())
        
        # Check for system logo (folder.png in static/images/systems/)
        logo_filename = f"{folder}.png"
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                  'static', 'images', 'systems', logo_filename)
        system_logo = logo_filename if os.path.exists(logo_path) else None
        
        # Insert or update system
        c.execute("INSERT OR IGNORE INTO systems (name, folder, logo) VALUES (?, ?, ?)", 
                  (system_name, folder, system_logo))
        c.execute("SELECT id FROM systems WHERE folder = ?", (folder,))
        result = c.fetchone()
        
        if not result:
            logger.warning(f"Could not get system ID for: {folder}")
            continue
        
        system_id = result[0]
        
        # Update system name and logo
        c.execute("UPDATE systems SET name = ?, logo = ? WHERE folder = ?", 
                  (system_name, system_logo, folder))
        
        # Get supported extensions from systeminfo.txt
        extensions = parse_systeminfo(system_path)
        
        # Special handling for PS3 - scan for .PS3 folders AND .iso files
        is_ps3 = folder.lower() == 'ps3'
        
        if not extensions and not is_ps3:
            logger.warning(f"[SKIP] No extensions found for {folder}")
            continue
        
        systems_processed += 1
        rom_count = 0
        
        # Scan for ROM files (and PS3 folders)
        try:
            # For PS3, we scan for .PS3 folders and .iso files (non-recursive)
            if is_ps3:
                # Scan top-level directory only (no recursion)
                try:
                    entries = os.listdir(system_path)
                except OSError as e:
                    logger.error(f"Cannot read PS3 directory: {e}")
                    entries = []
                
                for entry in entries:
                    entry_path = os.path.join(system_path, entry)
                    
                    # Skip hidden files
                    if entry.startswith('.'):
                        continue
                    
                    # Check for .PS3 game folders
                    if os.path.isdir(entry_path) and entry.upper().endswith('.PS3'):
                        # Check if game already exists
                        c.execute("SELECT id FROM games WHERE rom_path = ?", (entry_path,))
                        if c.fetchone():
                            continue
                        
                        # Clean up the title (remove .PS3 extension from folder name)
                        title = clean_title(entry[:-4])
                        
                        # Insert new game
                        c.execute("""
                            INSERT INTO games (system_id, title, rom_path, scraped, created_at)
                            VALUES (?, ?, ?, 0, ?)
                        """, (system_id, title, entry_path, datetime.now(timezone.utc).isoformat()))

                        rom_count += 1
                        new_games += 1
                        logger.debug(f"Added PS3 game (folder): {title}")
                    
                    # Check for .iso files (RPCS3 now supports ISO)
                    elif os.path.isfile(entry_path) and entry.lower().endswith('.iso'):
                        # Check if game already exists
                        c.execute("SELECT id FROM games WHERE rom_path = ?", (entry_path,))
                        if c.fetchone():
                            continue
                        
                        # Clean up the title (remove .iso extension)
                        title = clean_title(entry)
                        
                        # Insert new game
                        c.execute("""
                            INSERT INTO games (system_id, title, rom_path, scraped, created_at)
                            VALUES (?, ?, ?, 0, ?)
                        """, (system_id, title, entry_path, datetime.now(timezone.utc).isoformat()))

                        rom_count += 1
                        new_games += 1
                        logger.debug(f"Added PS3 game (ISO): {title}")
            else:
                # Regular ROM scanning for non-PS3 systems
                for file in os.listdir(system_path):
                    file_path = os.path.join(system_path, file)
                    
                    # Skip special files
                    if file.startswith('.') or file == 'systeminfo.txt':
                        continue
                    
                    # Skip directories for non-PS3 systems
                    if not os.path.isfile(file_path):
                        continue
                    
                    # Check extension
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in extensions:
                        continue
                    
                    # Check if game already exists
                    c.execute("SELECT id FROM games WHERE rom_path = ?", (file_path,))
                    if c.fetchone():
                        continue
                    
                    # Clean up the title
                    title = clean_title(file)
                    
                    # Insert new game
                    c.execute("""
                        INSERT INTO games (system_id, title, rom_path, scraped, created_at)
                        VALUES (?, ?, ?, 0, ?)
                    """, (system_id, title, file_path, datetime.now(timezone.utc).isoformat()))

                    rom_count += 1
                    new_games += 1
                
        except Exception as e:
            logger.error(f"Error scanning {folder}: {e}")
            continue
        
        if rom_count > 0:
            logger.info(f"[OK] {system_name}: {rom_count} new ROMs")
    
    conn.commit()
    conn.close()
    
    logger.info("=" * 60)
    logger.info(f"ROM scan complete")
    logger.info(f"Systems processed: {systems_processed}")
    logger.info(f"New games added: {new_games}")
    logger.info("=" * 60)
    
    return new_games


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    new_games = scan_roms()
    print(f"\nScan complete. Added {new_games} new games.")
