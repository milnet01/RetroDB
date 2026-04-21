#!/usr/bin/env python3
"""
RPCS3 Trophy Parser - Based on RPCS3 source code

File format from RPCS3:
- rpcs3/Loader/TROPUSR.h
- rpcs3/Loader/TROPUSR.cpp
- rpcs3/Emu/Cell/Modules/cellRtc.cpp

TROPUSR.DAT Structure:
- Header (48 bytes): magic, unk1, tables_count, unk2, reserved[32]
- Table Headers start at offset 0x30 (32 bytes each)
- Entry4 (96 bytes): trophy info (id, grade, pid)
- Entry6 (112 bytes): unlock state and timestamps

All values are big-endian.
Timestamps are microseconds since year 0001.
"""

import struct
import defusedxml.ElementTree as ET
# Element is only used for type annotations — defusedxml doesn't re-export
# node classes (only parser functions), and annotating with a data-container
# class has no security impact. Actual XML parsing still goes through
# defusedxml.ElementTree.fromstring() below.
from xml.etree.ElementTree import Element
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path


# Constants from RPCS3
TROPUSR_MAGIC = 0x818F54AD
RTC_MAGIC_OFFSET = 62135596800000000  # Microseconds from year 0001 to 1970-01-01


@dataclass
class Trophy:
    """Represents a single trophy"""
    trophy_id: int
    name: str
    description: str
    trophy_type: str  # 'P', 'G', 'S', 'B'
    hidden: bool
    platinum_relevant: bool
    group_id: Optional[str] = None
    unlocked: bool = False
    unlock_timestamp: Optional[datetime] = None
    icon_path: Optional[str] = None
    
    @property
    def trophy_type_name(self) -> str:
        return {'P': 'Platinum', 'G': 'Gold', 'S': 'Silver', 'B': 'Bronze'}.get(self.trophy_type, 'Unknown')


@dataclass
class TrophySet:
    """Represents a complete trophy set for a game"""
    npcomm_id: str
    title: str
    description: str
    version: str = "1.0"
    parental_level: int = 0
    trophies: List[Trophy] = field(default_factory=list)
    icon_path: Optional[str] = None
    
    @property
    def base_game_trophies(self) -> List[Trophy]:
        return [t for t in self.trophies if t.group_id is None]
    
    def get_trophy_counts(self, include_dlc: bool = False) -> Dict[str, Tuple[int, int]]:
        trophies = self.trophies if include_dlc else self.base_game_trophies
        counts = {'P': [0, 0], 'G': [0, 0], 'S': [0, 0], 'B': [0, 0]}
        for trophy in trophies:
            if trophy.trophy_type in counts:
                counts[trophy.trophy_type][1] += 1
                if trophy.unlocked:
                    counts[trophy.trophy_type][0] += 1
        return {k: tuple(v) for k, v in counts.items()}
    
    @property
    def completion_percentage(self) -> float:
        base = self.base_game_trophies
        if not base:
            return 0.0
        unlocked = sum(1 for t in base if t.unlocked)
        return (unlocked / len(base)) * 100


class TROPCONFParser:
    """Parser for TROPCONF.SFM XML files"""
    
    def parse(self, filepath: str) -> TrophySet:
        with open(filepath, 'rb') as f:
            content = f.read()
        
        # Find XML start (may have binary header)
        xml_start = content.find(b'<?xml')
        if xml_start == -1:
            xml_start = content.find(b'<trophyconf')
        if xml_start == -1:
            xml_start = 0
        
        content = content[xml_start:]
        
        try:
            xml_content = content.decode('utf-8')
        except UnicodeDecodeError:
            xml_content = content.decode('utf-8', errors='ignore')
        
        root = ET.fromstring(xml_content)
        
        # Handle nested trophyconf (some files have it wrapped)
        if root.tag != 'trophyconf':
            trophyconf = root.find('trophyconf')
            if trophyconf is not None:
                root = trophyconf
        
        npcomm_id = self._get_text(root, 'npcommid', '')
        title = self._get_text(root, 'title-name', 'Unknown Game')
        description = self._get_text(root, 'title-detail', '')
        version = root.get('version', '1.0')
        
        trophy_set = TrophySet(
            npcomm_id=npcomm_id,
            title=title,
            description=description,
            version=version
        )
        
        # Parse trophies
        for trophy_elem in root.findall('trophy'):
            trophy = self._parse_trophy(trophy_elem)
            trophy_set.trophies.append(trophy)
        
        return trophy_set
    
    def _parse_trophy(self, elem: Element) -> Trophy:
        trophy_id = int(elem.get('id', '0'))
        trophy_type = elem.get('ttype', 'B')
        hidden = elem.get('hidden', 'no').lower() == 'yes'
        pid = elem.get('pid', '-1')
        group_id = elem.get('gid')
        
        # Platinum relevance: has a valid pid (not -1) and no group (not DLC)
        platinum_relevant = group_id is None and pid != '-1' and trophy_type != 'P'
        
        return Trophy(
            trophy_id=trophy_id,
            name=self._get_text(elem, 'name', f'Trophy {trophy_id}'),
            description=self._get_text(elem, 'detail', ''),
            trophy_type=trophy_type,
            hidden=hidden,
            platinum_relevant=platinum_relevant,
            group_id=group_id
        )
    
    def _get_text(self, elem: Element, tag: str, default: str = '') -> str:
        child = elem.find(tag)
        return child.text if child is not None and child.text else default


class TROPUSRParser:
    """
    Parser for TROPUSR.DAT binary files - matches RPCS3 implementation exactly
    
    Based on rpcs3/Loader/TROPUSR.h and TROPUSR.cpp
    """
    
    def __init__(self):
        self.entries = {}  # trophy_id -> (unlocked, timestamp)
    
    def parse(self, filepath: str) -> Dict[int, Tuple[bool, Optional[datetime]]]:
        """Parse TROPUSR.DAT and return {trophy_id: (unlocked, timestamp)}"""
        self.entries = {}
        
        with open(filepath, 'rb') as f:
            data = f.read()
        
        if len(data) < 48:
            return self.entries
        
        # Parse header
        magic = struct.unpack('>I', data[0:4])[0]
        if magic != TROPUSR_MAGIC:
            return self.entries
        
        tables_count = struct.unpack('>I', data[8:12])[0]
        
        # Parse table headers (start at 0x30, 32 bytes each)
        table_headers = []
        for i in range(tables_count):
            header_offset = 0x30 + (i * 32)
            if header_offset + 32 > len(data):
                break
            
            hdr = data[header_offset:header_offset + 32]
            table_type = struct.unpack('>I', hdr[0:4])[0]
            entries_size = struct.unpack('>I', hdr[4:8])[0]
            entries_count = struct.unpack('>I', hdr[12:16])[0]
            offset = struct.unpack('>Q', hdr[16:24])[0]
            
            table_headers.append({
                'type': table_type,
                'entries_size': entries_size,
                'entries_count': entries_count,
                'offset': offset
            })
        
        # Parse Table 6 (unlock state and timestamps)
        for header in table_headers:
            if header['type'] == 6:
                self._parse_table6(data, header)
        
        return self.entries
    
    def _parse_table6(self, data: bytes, header: dict):
        """Parse Table 6 entries (unlock state and timestamps)"""
        # Entry size = entries_size + 0x10 (16-byte entry header)
        entry_size = header['entries_size'] + 0x10
        offset = header['offset']
        
        for i in range(header['entries_count']):
            entry_offset = offset + (i * entry_size)
            
            if entry_offset + entry_size > len(data):
                break
            
            entry = data[entry_offset:entry_offset + entry_size]
            
            # Verify entry type
            entry_type = struct.unpack('>I', entry[0:4])[0]
            if entry_type != 6:
                continue
            
            # Parse entry contents (after 16-byte header)
            trophy_id = struct.unpack('>I', entry[16:20])[0]
            trophy_state = struct.unpack('>I', entry[20:24])[0]
            timestamp2 = struct.unpack('>Q', entry[40:48])[0]
            
            # Convert timestamp to datetime
            timestamp = None
            if trophy_state != 0 and timestamp2 > 0:
                timestamp = self._tick_to_datetime(timestamp2)
            
            self.entries[trophy_id] = (trophy_state != 0, timestamp)
    
    def _tick_to_datetime(self, tick: int) -> Optional[datetime]:
        """Convert PS3 tick (microseconds since year 0001) to Python datetime"""
        try:
            if tick <= RTC_MAGIC_OFFSET:
                return None
            
            unix_microseconds = tick - RTC_MAGIC_OFFSET
            unix_seconds = unix_microseconds / 1_000_000
            
            if unix_seconds < 0 or unix_seconds > 4102444800:
                return None
            
            return datetime.fromtimestamp(unix_seconds)
        except (OSError, OverflowError, ValueError):
            return None


class TrophyManager:
    """Main class for managing trophy data from RPCS3"""
    
    def __init__(self, trophy_base_path: str):
        self.trophy_base_path = Path(trophy_base_path)
        self.trophy_sets: Dict[str, TrophySet] = {}
    
    def discover_trophy_sets(self) -> List[str]:
        """Discover all trophy sets in the trophy folder"""
        npwr_ids = []
        
        if not self.trophy_base_path.exists():
            return npwr_ids
        
        for item in self.trophy_base_path.iterdir():
            if item.is_dir() and item.name.startswith('NPWR'):
                if '_BU_' not in item.name:
                    npwr_ids.append(item.name)
        
        return sorted(npwr_ids)
    
    def load_trophy_set(self, npwr_id: str) -> Optional[TrophySet]:
        """Load a complete trophy set by its NPWR ID"""
        trophy_path = self.trophy_base_path / npwr_id
        
        if not trophy_path.exists():
            return None
        
        # Parse TROPCONF.SFM
        tropconf_path = trophy_path / 'TROPCONF.SFM'
        if not tropconf_path.exists():
            return None
        
        conf_parser = TROPCONFParser()
        trophy_set = conf_parser.parse(str(tropconf_path))
        
        # Parse TROPUSR.DAT
        tropusr_path = trophy_path / 'TROPUSR.DAT'
        if tropusr_path.exists():
            usr_parser = TROPUSRParser()
            unlock_data = usr_parser.parse(str(tropusr_path))
            
            # Apply unlock data to trophies
            for trophy in trophy_set.trophies:
                if trophy.trophy_id in unlock_data:
                    unlocked, timestamp = unlock_data[trophy.trophy_id]
                    trophy.unlocked = unlocked
                    trophy.unlock_timestamp = timestamp
        
        # Set icon paths
        icon0_path = trophy_path / 'ICON0.PNG'
        if icon0_path.exists():
            trophy_set.icon_path = str(icon0_path)
        
        for trophy in trophy_set.trophies:
            icon_path = trophy_path / f'TROP{trophy.trophy_id:03d}.PNG'
            if icon_path.exists():
                trophy.icon_path = str(icon_path)
        
        self.trophy_sets[npwr_id] = trophy_set
        return trophy_set
    
    def load_all_trophy_sets(self) -> Dict[str, TrophySet]:
        """Load all discovered trophy sets"""
        for npwr_id in self.discover_trophy_sets():
            self.load_trophy_set(npwr_id)
        return self.trophy_sets
    
    def get_total_trophy_counts(self) -> Dict[str, Tuple[int, int]]:
        """Get total trophy counts across all games"""
        totals = {'P': [0, 0], 'G': [0, 0], 'S': [0, 0], 'B': [0, 0]}
        
        for trophy_set in self.trophy_sets.values():
            counts = trophy_set.get_trophy_counts(include_dlc=True)
            for trophy_type, (unlocked, total) in counts.items():
                totals[trophy_type][0] += unlocked
                totals[trophy_type][1] += total
        
        return {k: tuple(v) for k, v in totals.items()}


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        trophy_path = sys.argv[1]
        manager = TrophyManager(trophy_path)
        
        npwr_ids = manager.discover_trophy_sets()
        print(f"Found {len(npwr_ids)} trophy sets:")
        
        for npwr_id in npwr_ids:
            trophy_set = manager.load_trophy_set(npwr_id)
            if trophy_set:
                unlocked = sum(1 for t in trophy_set.trophies if t.unlocked)
                print(f"  {trophy_set.title} ({npwr_id}): {unlocked}/{len(trophy_set.trophies)}")
    else:
        print("Usage: python trophy_parser.py <trophy_folder_path>")
