# =============================================================================
# RETRODB - MAME names (PASS-59-227)
# =============================================================================
# A MAME game's file name is its identity, so it never changes. Its real name,
# year and maker come from a list MAME publishes (`mame -listxml`, or a DAT),
# and its category from a catver.ini. Both are files the user points at.
# =============================================================================

import json
import os
import re
import zipfile
from datetime import datetime

import defusedxml.ElementTree as ET

from scraper.metadata_normalizer import alt_title_entry, merge_alt_titles
from scraper.scan_roms import clean_title
from services.game_utils import ARCADE_SET_FOLDERS, generate_sort_title

BIOS = 'BIOS'
SOURCE = 'mame_list'
_MACHINE_TAGS = ('machine', 'game')
_FOUR_DIGIT_YEAR = re.compile(r'^\d{4}$')


def _open_list(path):
    """A binary stream of the XML: the file, or the first XML inside a zip."""
    if not zipfile.is_zipfile(path):
        return open(path, 'rb')
    archive = zipfile.ZipFile(path)
    name = next((n for n in archive.namelist() if n.lower().endswith(('.xml', '.dat'))), None)
    if name is None:
        archive.close()
        raise ValueError(f'{os.path.basename(path)} holds no XML list')
    return archive.open(name)


def read_machines(path, wanted, machines=None, should_stop=lambda: False):
    """Add each wanted set from one list to `machines`, set name -> details.

    An earlier list wins for a detail it has; a later one only fills gaps, so
    the list matching the user's ROMs goes first. The lists are large, so each
    machine is dropped from memory as soon as it is read.
    """
    machines = {} if machines is None else machines
    with _open_list(path) as stream:
        parser = ET.iterparse(stream, events=('start', 'end'))
        root = None
        for event, element in parser:
            if root is None:
                root = element
            if event != 'end' or element.tag not in _MACHINE_TAGS:
                continue
            name = element.get('name')
            if name in wanted:
                found = {
                    'description': (element.findtext('description') or '').strip(),
                    'year': (element.findtext('year') or '').strip(),
                    'manufacturer': (element.findtext('manufacturer') or '').strip(),
                    'bios': element.get('isbios') == 'yes' or element.get('isdevice') == 'yes',
                }
                held = machines.setdefault(name, {})
                for key, value in found.items():
                    held[key] = held.get(key) or value
            root.clear()
            if should_stop():
                break
    return machines


def read_categories(path, wanted):
    """Set name -> top-level category, from a catver.ini's [Category] section.

    The same file's [VerAdded] section uses the same keys for version numbers,
    so it must not be read.
    """
    categories = {}
    section = None
    with open(path, encoding='utf-8', errors='replace') as ini:
        for line in ini:
            line = line.strip()
            if line.startswith('['):
                section = line
            elif section == '[Category]' and '=' in line:
                name, value = line.split('=', 1)
                if name in wanted:
                    top = value.replace('* Mature *', '').split('/')[0].strip()
                    if top:
                        categories[name] = top.replace(',', '')
    return categories


def _usable_maker(manufacturer):
    return manufacturer if manufacturer and '<unknown>' not in manufacturer else None


def _history_with(history_json, filled):
    try:
        history = json.loads(history_json) if history_json else []
    except (ValueError, TypeError):
        history = []
    if not isinstance(history, list):
        history = []
    history.append({
        'timestamp': datetime.now().isoformat(),
        'primary_source': SOURCE,
        'sources_used': ['MAME list'],
        'fields_filled': filled,
        'fields_missing': [],
    })
    return json.dumps(history)


def changes_for(row, machine, category):
    """The column changes one game takes, or {}.

    Only a title still equal to the file name is replaced, and a locked one
    never. The new title is locked, because the AI and the scrapers would
    otherwise rename it. Year and maker only fill empty fields.
    """
    changes = {}
    filename = os.path.basename(row['rom_path'] or '')
    stem = os.path.splitext(filename)[0]
    title = row['title'] or ''
    description = machine.get('description')
    if (description and not row['title_locked'] and description != title
            and title.lower() in (stem.lower(), clean_title(filename).lower())):
        alts = merge_alt_titles(row['alternate_titles'],
                                [alt_title_entry(stem, source='mame')],
                                primary_title=description)
        changes.update(title=description, sort_title=generate_sort_title(description),
                       title_locked=1, alternate_titles=json.dumps(alts) if alts else None)
    year = machine.get('year') or ''
    if not row['release_date'] and _FOUR_DIGIT_YEAR.match(year):
        changes['release_date'] = year
    maker = _usable_maker(machine.get('manufacturer'))
    if not row['publisher'] and maker:
        changes['publisher'] = maker

    wanted_category = BIOS if machine.get('bios') else category
    if wanted_category and wanted_category != row['arcade_category']:
        changes['arcade_category'] = wanted_category
    if changes:
        changes['scrape_history'] = _history_with(row['scrape_history'], sorted(changes))
    return changes


def arcade_rows(conn):
    """Every game in a folder of arcade sets, with what changes_for reads."""
    marks = ','.join('?' * len(ARCADE_SET_FOLDERS))
    return conn.execute(f"""
        SELECT g.id, g.title, g.rom_path, g.release_date, g.publisher, g.title_locked,
               g.alternate_titles, g.arcade_category, g.scrape_history
        FROM games g JOIN systems s ON s.id = g.system_id
        WHERE s.folder IN ({marks}) AND g.rom_path IS NOT NULL
    """, ARCADE_SET_FOLDERS).fetchall()


def set_name(row):
    return os.path.splitext(os.path.basename(row['rom_path'] or ''))[0]


# The fixed columns changes_for can return, so none is taken from outside.
_COLUMNS = ('title', 'sort_title', 'title_locked', 'alternate_titles', 'release_date',
            'publisher', 'arcade_category', 'scrape_history')


def apply_changes(conn, game_id, changes):
    columns = [c for c in _COLUMNS if c in changes]
    assignments = ', '.join(f'{c} = ?' for c in columns)
    conn.execute(f"UPDATE games SET {assignments} WHERE id = ?",  # noqa: S608 — fixed names
                 [changes[c] for c in columns] + [game_id])
