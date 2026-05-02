"""
ROM Tools Backend Module
Provides functionality for archive scanning, CHD conversion/verification, and duplicate finding.
"""

import os
import shutil
import subprocess
import hashlib
import threading
import time
import re
import fnmatch
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Set, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


def convert_one_to_chd(
    src_path: str,
    chdman_path: str,
    *,
    do_verify: bool = True,
    delete_original: bool = False,
    skip_existing: bool = True,
    convert_timeout: int = 3600,
    verify_timeout: int = 600,
) -> Dict[str, Any]:
    """Convert a single disc image to CHD atomically.

    Pass 42.5 — pure per-file helper shared by ``CHDConverter._convert_file``
    and ``routes/tools.py:api_chd_converter_convert``. No task-state
    bookkeeping; the caller owns logs, progress, and registry updates.

    Pass 40.11 atomic-write contract: chdman writes to a sibling
    ``.chd.part`` tempfile, optional ``chdman verify`` runs against the
    tempfile, and only a successful verify promotes via ``os.replace``.
    On any failure or exception the tempfile is unlinked so a SIGKILL
    mid-conversion can never leave a corrupt ``.chd`` that
    ``skip_existing`` would treat as good on the next pass.

    Returns a result dict shaped:
        {
            'source':          str — input path,
            'destination':     str — output .chd path,
            'original_size':   int,
            'compressed_size': int (0 if not success),
            'status':          'success' | 'failed' | 'skipped',
            'error':           str (empty on success/skipped),
        }
    """
    src = Path(src_path)
    dst = src.with_suffix(".chd")
    tmp = dst.with_suffix(".chd.part")

    result: Dict[str, Any] = {
        "source": str(src),
        "destination": str(dst),
        "original_size": src.stat().st_size if src.exists() else 0,
        "compressed_size": 0,
        "status": "pending",
        "error": "",
    }

    if dst.exists() and skip_existing:
        result["status"] = "skipped"
        return result

    try:
        # Pass 40.11 — clean any stale tempfile from a prior failed run.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

        cmd = [chdman_path, "createcd", "-i", str(src), "-o", str(tmp)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=convert_timeout)

        if proc.returncode != 0 or not tmp.exists():
            result["status"] = "failed"
            result["error"] = (proc.stderr[:500] if proc.stderr else "Unknown error")
            return result

        if do_verify:
            verify = subprocess.run(
                [chdman_path, "verify", "-i", str(tmp)],
                capture_output=True, text=True, timeout=verify_timeout,
            )
            if verify.returncode != 0:
                result["status"] = "failed"
                result["error"] = (verify.stderr[:500] or "Verify failed")
                return result

        os.replace(str(tmp), str(dst))
        result["status"] = "success"
        result["compressed_size"] = dst.stat().st_size

        # Delete original only after the verified .chd is in place.
        if delete_original:
            try:
                src.unlink()
            except OSError as e:
                # Conversion succeeded; surface the delete failure but
                # don't flip status — the .chd is good.
                result["error"] = f"original-delete failed: {e}"
        return result

    except subprocess.TimeoutExpired:
        result["status"] = "failed"
        result["error"] = "Conversion timed out"
        return result
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        return result
    finally:
        if result["status"] != "success" and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _safe_under_root(path: Path, root_resolved: Path) -> bool:
    """Pass 41.14.C — guard rglob() against symlinks escaping ROM root.

    `Path.rglob()` follows symlinks on Python 3.12 (default behavior
    changed in 3.13). A symlink to `/` placed inside ROM_PATH would let
    rom_tools' archive/CHD scanners enumerate the entire filesystem.
    Resolve the candidate and confirm it sits under the resolved root
    before processing.
    """
    try:
        return path.resolve().is_relative_to(root_resolved)
    except (OSError, ValueError):
        return False


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ROMToolsConfig:
    """Configuration for ROM Tools"""
    # Paths
    roms_path: str = ""
    output_path: str = ""  # Empty means same as source
    temp_path: str = field(default_factory=lambda: os.path.join(tempfile.gettempdir(), 'retrodb_romtools'))
    
    # Archive Scanner settings
    archive_types: List[str] = field(default_factory=lambda: [".zip", ".7z", ".rar"])
    recursive_scan: bool = True
    verify_integrity: bool = False
    generate_m3u: bool = False
    remove_unwanted: bool = False
    unwanted_patterns: List[str] = field(default_factory=lambda: ["*.txt", "*.nfo", "*.diz", "*.url", "*.html", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.scr"])
    
    # CHD settings
    chdman_path: str = "chdman"  # Assumes in PATH
    chd_verify_after_convert: bool = True
    chd_delete_originals: bool = False
    chd_skip_existing: bool = True
    
    # Duplicate Finder settings
    duplicate_method: str = "hash"  # hash, name, both
    ignore_region_tags: bool = True
    include_archives: bool = False
    
    # Multi-disc systems (for M3U generation)
    multi_disc_systems: List[str] = field(default_factory=lambda: [
        "3do", "dreamcast", "gamecube", "psx", "ps2", "ps3", "psp",
        "saturn", "segacd", "wii", "pcenginecd", "neogeocd"
    ])
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ROMToolsConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# =============================================================================
# TASK STATUS TRACKING
# =============================================================================

@dataclass
class TaskStatus:
    """Status tracking for running tasks"""
    task_id: str
    task_type: str  # scan, convert, verify, duplicates
    status: str = "pending"  # pending, running, paused, completed, error, cancelled
    progress: int = 0
    total: int = 0
    current_file: str = ""
    start_time: float = 0
    end_time: float = 0
    results: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    error: str = ""
    
    def to_dict(self) -> dict:
        result = {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'status': self.status,
            'progress': self.progress,
            'total': self.total,
            'current_file': self.current_file,
            'percent': round((self.progress / self.total * 100) if self.total > 0 else 0, 1),
            'elapsed': round(time.time() - self.start_time, 1) if self.start_time else 0,
            'results': self.results,
            'logs': self.logs[-50:],  # Last 50 log entries
            'error': self.error
        }
        # Include issues for archive scanner
        if 'issues' in self.results:
            result['issues'] = self.results['issues']
        return result


# Global task storage
_tasks: Dict[str, TaskStatus] = {}
_task_lock = threading.Lock()


def get_task(task_id: str) -> Optional[TaskStatus]:
    with _task_lock:
        return _tasks.get(task_id)


def create_task(task_type: str) -> TaskStatus:
    import uuid
    task_id = str(uuid.uuid4())[:8]
    task = TaskStatus(task_id=task_id, task_type=task_type)
    with _task_lock:
        _tasks[task_id] = task
    return task


def update_task(task: TaskStatus):
    with _task_lock:
        _tasks[task.task_id] = task


def cancel_task(task_id: str) -> bool:
    task = get_task(task_id)
    if task and task.status == "running":
        task.status = "cancelled"
        update_task(task)
        return True
    return False


# =============================================================================
# ARCHIVE SCANNER
# =============================================================================

class ArchiveScanner:
    """Scans directories for ROM archives and can extract/process them"""
    
    ARCHIVE_COMMANDS = {
        ".zip": {
            "test": ["unzip", "-tqq"],
            "list": ["unzip", "-Z1"],
            "list_verbose": ["unzip", "-Zl"],
            "extract": ["unzip", "-o", "-d"],
            "delete": ["zip", "-d"]
        },
        ".7z": {
            "test": ["7z", "t"],
            "list": ["7z", "l", "-ba"],
            "list_verbose": ["7z", "l"],
            "extract": ["7z", "x", "-o"],
            "delete": ["7z", "d"]
        },
        ".rar": {
            "test": ["unrar", "t"],
            "list": ["unrar", "lb"],
            "list_verbose": ["unrar", "l"],
            "extract": ["unrar", "x", "-o+"],
            "delete": None  # RAR doesn't support deletion
        }
    }
    
    # Unwanted file patterns
    UNWANTED_PATTERNS = [
        "*.txt", "*.nfo", "*.diz", "*.url", "*.html", "*.htm",
        "*.sfv", "readme*", "release*", "*.md5", "*.sha1",
        "*.png", "*.jpg", "*.jpeg", "*.gif", "*.scr"
    ]
    
    def __init__(self, config: ROMToolsConfig):
        self.config = config
        self.task: Optional[TaskStatus] = None
    
    def scan_for_issues(self, path: str, task: TaskStatus, 
                        excluded_paths: List[str] = None,
                        types: List[str] = None,
                        modes: Dict[str, bool] = None,
                        unwanted_patterns: List[str] = None) -> Dict[str, Any]:
        """Scan directory for archives with issues (corrupted, multi-file, unwanted)"""
        self.task = task
        task.status = "running"
        task.start_time = time.time()
        task.results = {
            "archives_scanned": 0,
            "issues": []
        }
        
        # Default values
        if excluded_paths is None:
            excluded_paths = []
        if types is None:
            types = [".zip", ".7z", ".rar"]
        if modes is None:
            modes = {"corrupted": True, "multiFile": True, "unwanted": True}
        
        # Use custom unwanted patterns if provided, otherwise use class default
        if unwanted_patterns:
            self._custom_unwanted_patterns = unwanted_patterns
            logger.info(f"Using custom unwanted patterns: {unwanted_patterns}")
        else:
            self._custom_unwanted_patterns = None
        
        try:
            root = Path(path)
            if not root.exists():
                raise ValueError(f"Path does not exist: {path}")
            
            # Find all archives, excluding specified paths
            archives = self._find_archives_filtered(root, excluded_paths, types)
            task.total = len(archives)
            task.logs.append(f"[{self._timestamp()}] Found {len(archives)} archives to scan")
            
            for i, archive_path in enumerate(archives):
                if task.status == "cancelled":
                    task.logs.append(f"[{self._timestamp()}] Scan cancelled by user")
                    break
                
                while task.status == "paused":
                    time.sleep(0.5)
                
                task.progress = i + 1
                # Show relative folder being scanned
                rel_folder = archive_path.parent.name
                task.current_file = rel_folder
                update_task(task)
                
                # Check for issues
                issues = self._check_archive_issues(archive_path, root, modes)
                for issue in issues:
                    task.results["issues"].append(issue)
                    # Update task with issues for frontend polling
                    task_dict = task.to_dict()
                    task_dict['issues'] = task.results["issues"]
                    with _task_lock:
                        _tasks[task.task_id] = task
                
                task.results["archives_scanned"] += 1
            
            task.status = "completed" if task.status != "cancelled" else "cancelled"
            task.end_time = time.time()
            task.logs.append(f"[{self._timestamp()}] Scan completed. Found {len(task.results['issues'])} issues in {task.results['archives_scanned']} archives")
            
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.logs.append(f"[{self._timestamp()}] ERROR: {str(e)}")
            logger.error(f"Archive scan error: {e}")
        
        update_task(task)
        return task.results
    
    def _find_archives_filtered(self, root: Path, excluded_paths: List[str], types: List[str]) -> List[Path]:
        """Find all archive files, excluding specified folders"""
        archives = []
        excluded_lower = [p.lower() for p in excluded_paths]
        # Pass 41.14.C — resolve once; then drop any rglob result that
        # leaves the root via a symlink.
        root_resolved = root.resolve()

        for ext in types:
            for archive_path in root.rglob(f"*{ext}"):
                if not _safe_under_root(archive_path, root_resolved):
                    continue
                # Check if any parent folder is in excluded list
                path_parts = [p.lower() for p in archive_path.relative_to(root).parts]
                if not any(excluded in path_parts for excluded in excluded_lower):
                    archives.append(archive_path)

        return sorted(archives)
    
    def _check_archive_issues(self, archive_path: Path, root: Path, modes: Dict[str, bool]) -> List[Dict]:
        """Check an archive for various issues"""
        issues = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rel_path = str(archive_path.relative_to(root))
        
        try:
            # Get archive contents
            contents = self._list_archive_contents(archive_path)
            file_count = len(contents)
            
            # Check for corruption
            if modes.get("corrupted", True):
                if not self._verify_archive(archive_path):
                    issues.append({
                        "type": "corrupted",
                        "path": str(archive_path),
                        "relative_path": rel_path,
                        "file_count": None,
                        "timestamp": timestamp
                    })
                    return issues  # If corrupted, don't check other issues
            
            # Check for multi-file (more than 1 ROM file)
            if modes.get("multiFile", True):
                rom_extensions = {'.bin', '.iso', '.cue', '.gdi', '.chd', '.cso', 
                                 '.nes', '.sfc', '.smc', '.gb', '.gbc', '.gba', 
                                 '.n64', '.z64', '.v64', '.nds', '.3ds', '.cia',
                                 '.md', '.gen', '.smd', '.32x', '.gg', '.sms',
                                 '.pce', '.tg16', '.cdi', '.mds', '.mdf',
                                 '.d64', '.t64', '.tap', '.prg', '.crt',
                                 '.tzx', '.z80', '.sna', '.dsk', '.adf'}
                
                rom_files = [f for f in contents if any(f.lower().endswith(ext) for ext in rom_extensions)]
                
                if len(rom_files) > 1:
                    issues.append({
                        "type": "multi-file",
                        "path": str(archive_path),
                        "relative_path": rel_path,
                        "file_count": len(rom_files),
                        "total_files": len(contents),
                        "timestamp": timestamp
                    })
            
            # Check for unwanted files
            if modes.get("unwanted", True):
                unwanted_files = self._find_unwanted_files(contents)
                if unwanted_files:
                    logger.debug(f"Found {len(unwanted_files)} unwanted files in {rel_path}: {unwanted_files}")
                    issues.append({
                        "type": "unwanted",
                        "path": str(archive_path),
                        "relative_path": rel_path,
                        "file_count": len(unwanted_files),
                        "timestamp": timestamp
                    })
        
        except Exception as e:
            logger.warning(f"Error checking archive {archive_path}: {e}")
        
        return issues
    
    def _find_unwanted_files(self, contents: List[str], custom_patterns: List[str] = None) -> List[str]:
        """Find unwanted files in archive contents
        
        Args:
            contents: List of file paths within the archive
            custom_patterns: Optional list of patterns to use (overrides instance patterns)
        """
        unwanted = []
        
        # Priority: 1. Method parameter, 2. Instance custom patterns, 3. Class default
        if custom_patterns:
            # Convert extension patterns like ".png" to glob patterns like "*.png"
            patterns = []
            for pattern in custom_patterns:
                if pattern.startswith('.') and '*' not in pattern:
                    patterns.append(f"*{pattern}")  # Convert ".png" to "*.png"
                else:
                    patterns.append(pattern)
            logger.debug(f"Using provided custom patterns: {patterns}")
        elif hasattr(self, '_custom_unwanted_patterns') and self._custom_unwanted_patterns:
            # Convert extension patterns like ".png" to glob patterns like "*.png"
            patterns = []
            for pattern in self._custom_unwanted_patterns:
                if pattern.startswith('.') and '*' not in pattern:
                    patterns.append(f"*{pattern}")  # Convert ".png" to "*.png"
                else:
                    patterns.append(pattern)
            logger.debug(f"Using instance custom patterns: {patterns}")
        else:
            patterns = self.UNWANTED_PATTERNS
            logger.debug(f"Using default patterns: {patterns}")
        
        for filepath in contents:
            # Use basename for pattern matching to handle files in subdirectories
            # e.g., "info/readme.nfo" should match "*.nfo" by checking just "readme.nfo"
            basename = os.path.basename(filepath)
            basename_lower = basename.lower()
            for pattern in patterns:
                if fnmatch.fnmatch(basename_lower, pattern.lower()):
                    unwanted.append(filepath)  # Keep full path for deletion
                    logger.debug(f"  Matched '{filepath}' (basename: '{basename}') with pattern '{pattern}'")
                    break
        
        logger.debug(f"Total unwanted files found: {len(unwanted)}")
        return unwanted
    
    def get_archive_contents_detailed(self, archive_path: str) -> Dict[str, Any]:
        """Get detailed contents of an archive with file sizes"""
        path = Path(archive_path)
        ext = self._get_extension(path)
        
        if ext not in self.ARCHIVE_COMMANDS:
            return {"success": False, "error": f"Unsupported archive type: {ext}"}
        
        files = []
        archive_name = path.name  # Get the archive filename to filter it out
        
        try:
            if ext == ".zip":
                # Use zipfile for accurate info
                import zipfile
                with zipfile.ZipFile(path, 'r') as zf:
                    for info in zf.infolist():
                        if not info.is_dir():
                            files.append({
                                "name": info.filename,
                                "size": info.file_size,
                                "compressed": info.compress_size
                            })
            elif ext == ".7z":
                # Use -slt for structured output that's reliable to parse
                cmd = ["7z", "l", "-slt", str(path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    current_file = {}
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Path = "):
                            # Start of new file entry
                            if current_file.get("name"):
                                files.append(current_file)
                            filename = line[7:]
                            # Skip if this is the archive itself (first entry in -slt output)
                            if filename == archive_name or filename == str(path) or filename.endswith(archive_name):
                                current_file = {}  # Reset, don't track this entry
                            else:
                                current_file = {"name": filename, "size": 0}
                        elif line.startswith("Size = ") and current_file.get("name"):
                            try:
                                current_file["size"] = int(line[7:])
                            except ValueError:
                                current_file["size"] = 0
                        elif line.startswith("Packed Size = ") and current_file.get("name"):
                            try:
                                current_file["compressed"] = int(line[14:])
                            except ValueError:
                                pass
                        elif line.startswith("Folder = +"):
                            # This is a folder, skip it
                            current_file = {}
                    # Don't forget the last file
                    if current_file.get("name"):
                        files.append(current_file)
            elif ext == ".rar":
                # Parse unrar list output - use vb for verbose bare listing
                cmd = ["unrar", "lt", str(path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    current_file = {}
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("Name: "):
                            if current_file.get("name"):
                                files.append(current_file)
                            current_file = {"name": line[6:], "size": 0}
                        elif line.startswith("Size: ") and current_file:
                            try:
                                current_file["size"] = int(line[6:])
                            except ValueError:
                                current_file["size"] = 0
                        elif line.startswith("Packed size: ") and current_file:
                            try:
                                current_file["compressed"] = int(line[13:])
                            except ValueError:
                                pass
                    if current_file.get("name"):
                        files.append(current_file)
            
            return {"success": True, "files": files}
            
        except Exception as e:
            logger.error(f"Error getting archive contents: {e}")
            return {"success": False, "error": str(e)}
    
    def remove_files_from_archive(self, archive_path: str, files_to_remove: List[str]) -> Dict[str, Any]:
        """Remove specific files from an archive"""
        path = Path(archive_path)
        ext = self._get_extension(path)
        
        logger.info(f"Attempting to remove {len(files_to_remove)} files from {archive_path}")
        for f in files_to_remove:
            logger.info(f"  File to remove: '{f}'")
        
        if ext not in self.ARCHIVE_COMMANDS:
            return {"success": False, "error": f"Unsupported archive type: {ext}"}
        
        cmd_info = self.ARCHIVE_COMMANDS[ext]
        if not cmd_info.get("delete"):
            return {"success": False, "error": f"Archive type {ext} doesn't support file deletion"}
        
        # Get current contents before deletion for verification
        contents_before = set(self._list_archive_contents(path))
        logger.debug(f"Archive contains {len(contents_before)} files before deletion")
        
        try:
            if ext == ".zip":
                # Use "--" to indicate end of options, preventing filenames starting with "-" from being interpreted as switches
                cmd = ["zip", "-d", str(path), "--"] + files_to_remove
            elif ext == ".7z":
                # For 7z, we need to use a different approach for files starting with "-"
                # Using @ syntax with a list file, or wrap filenames
                # Build command with explicit file list
                # Note: 7z doesn't support "--" the same way, so we use a different approach
                # We can use -i! to specify file patterns explicitly
                cmd = ["7z", "d", str(path)]
                for f in files_to_remove:
                    # Use -i! (include) pattern for each file to avoid option parsing issues
                    # The ! means exact match
                    cmd.extend(["-i!" + f])
            else:
                return {"success": False, "error": "File deletion not supported for this archive type"}
            
            logger.info(f"Executing command: {cmd[0]} {cmd[1]} ... ({len(files_to_remove)} files)")
            logger.debug(f"Full command: {cmd}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            logger.info(f"Command return code: {result.returncode}")
            if result.stdout:
                logger.debug(f"Command stdout: {result.stdout[:500]}")
            if result.stderr:
                logger.debug(f"Command stderr: {result.stderr[:500]}")
            
            # Verify deletion by checking contents after
            contents_after = set(self._list_archive_contents(path))
            actually_removed = contents_before - contents_after
            logger.info(f"Verification: {len(actually_removed)} files were actually removed")
            
            if actually_removed:
                for f in actually_removed:
                    logger.info(f"  Removed: '{f}'")
            
            if result.returncode == 0 and actually_removed:
                logger.info(f"Successfully removed {len(actually_removed)} files from {archive_path}")
                return {"success": True, "removed_count": len(actually_removed)}
            elif result.returncode == 0 and not actually_removed:
                # Command succeeded but no files were removed - likely filename mismatch
                logger.warning(f"Command succeeded but no files were actually removed. Possible filename mismatch.")
                logger.warning(f"Requested files: {files_to_remove}")
                logger.warning(f"Files in archive: {list(contents_before)[:10]}...")
                return {"success": False, "error": "No files were removed. The filenames may not match exactly."}
            else:
                # Check if it's a "file not found" type error which might mean partial success
                error_msg = result.stderr or result.stdout or "Failed to remove files"
                logger.error(f"Failed to remove files: {error_msg}")
                return {"success": False, "error": f"Command Line Error:\n{error_msg}"}
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout removing files from {archive_path}")
            return {"success": False, "error": "Operation timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Exception removing files: {e}")
            return {"success": False, "error": str(e)}
    
    def clean_archive(self, archive_path: str, unwanted_patterns: List[str] = None) -> Dict[str, Any]:
        """Remove unwanted files from an archive
        
        Args:
            archive_path: Path to the archive file
            unwanted_patterns: Optional list of patterns to identify unwanted files
        """
        # Get contents
        contents_result = self.get_archive_contents_detailed(archive_path)
        if not contents_result.get("success"):
            return contents_result
        
        # Find unwanted files using provided patterns or defaults
        file_names = [f["name"] for f in contents_result.get("files", [])]
        unwanted = self._find_unwanted_files(file_names, unwanted_patterns)
        
        if not unwanted:
            return {"success": True, "removed_count": 0, "message": "No unwanted files found"}
        
        logger.info(f"Found {len(unwanted)} unwanted files to remove from {archive_path}")
        for f in unwanted:
            logger.debug(f"  - {f}")
        
        # Remove them
        return self.remove_files_from_archive(archive_path, unwanted)
    
    def create_m3u_playlist(self, archive_path: str, move_to_staging: bool = True,
                              staging_folder: str = None) -> Dict[str, Any]:
        """Create M3U playlist for multi-file archive (ES-DE compatible)
        
        This extracts the archive to a subfolder, adds noload.txt, and creates
        an M3U file in the parent directory pointing to the extracted files.
        
        Args:
            archive_path: Path to the archive file
            move_to_staging: If True, move original archive to staging folder after success
            staging_folder: Folder to move archives to (default: system temp dir)

        ES-DE M3U structure:
        parent_folder/
        ├── GameName.m3u           # M3U file with relative paths
        └── GameName/              # Extracted game folder
            ├── noload.txt         # Prevents ES-DE from scanning this folder
            ├── Game Disc 1.bin
            └── Game Disc 2.bin
        """
        path = Path(archive_path)

        if not path.exists():
            return {"success": False, "error": f"Archive not found: {archive_path}"}

        ext = self._get_extension(path)
        if ext not in self.ARCHIVE_COMMANDS:
            return {"success": False, "error": f"Unsupported archive type: {ext}"}

        # Default staging folder
        if not staging_folder:
            staging_folder = os.path.join(tempfile.gettempdir(), 'retrodb_m3u_staging')
        
        # Get archive contents to verify it's a multi-file archive
        contents = self._list_archive_contents(path)
        
        # Define ROM file extensions for the M3U (these are the files emulators load)
        rom_extensions = {'.bin', '.iso', '.cue', '.gdi', '.chd', '.cso', '.mds', '.mdf',
                         '.nes', '.sfc', '.smc', '.gb', '.gbc', '.gba', 
                         '.n64', '.z64', '.v64', '.nds', '.3ds', '.cia',
                         '.md', '.gen', '.smd', '.32x', '.gg', '.sms',
                         '.pce', '.tg16', '.cdi', '.d64', '.t64', '.tap', 
                         '.prg', '.crt', '.tzx', '.z80', '.sna', '.dsk', '.adf'}
        
        # Find ROM files in the archive
        rom_files = sorted([f for f in contents if any(f.lower().endswith(ext) for ext in rom_extensions)])
        
        if len(rom_files) < 1:
            return {"success": False, "error": "No ROM files found in archive"}
        
        # Create folder name from archive name (without extension)
        folder_name = path.stem
        extract_folder = path.parent / folder_name
        
        # Create M3U file path
        m3u_path = path.parent / f"{folder_name}.m3u"
        
        try:
            # Create extraction folder if it doesn't exist
            extract_folder.mkdir(parents=True, exist_ok=True)
            
            # Extract the archive
            cmd_info = self.ARCHIVE_COMMANDS[ext]
            if ext == ".zip":
                cmd = ["unzip", "-o", str(path), "-d", str(extract_folder)]
            elif ext == ".7z":
                cmd = ["7z", "x", f"-o{extract_folder}", "-y", str(path)]
            elif ext == ".rar":
                cmd = ["unrar", "x", "-o+", str(path), str(extract_folder) + "/"]
            else:
                return {"success": False, "error": f"Extraction not supported for {ext}"}
            
            logger.info(f"Extracting archive to {extract_folder}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown extraction error"
                logger.error(f"Extraction failed: {error_msg}")
                return {"success": False, "error": f"Extraction failed: {error_msg[:200]}"}
            
            # Create noload.txt to prevent ES-DE from scanning this folder
            noload_path = extract_folder / "noload.txt"
            noload_path.touch()
            logger.info(f"Created {noload_path}")
            
            # Build list of extracted ROM files for the M3U
            # Files in the M3U should use relative paths from the M3U's location
            m3u_entries = []
            
            # Check if files are extracted directly to folder or in subdirectories
            for rom_file in rom_files:
                # The rom_file path from archive might include subdirectories
                extracted_file = extract_folder / rom_file
                if extracted_file.exists():
                    # Create relative path: FolderName/filename
                    relative_path = f"{folder_name}/{rom_file}"
                    m3u_entries.append(relative_path)
                    logger.debug(f"  M3U entry: {relative_path}")
            
            if not m3u_entries:
                # Files might be in a nested folder inside the archive
                # Try to find them
                for rom_ext in rom_extensions:
                    for found_file in extract_folder.rglob(f"*{rom_ext}"):
                        relative_path = found_file.relative_to(path.parent)
                        m3u_entries.append(str(relative_path))
                        logger.debug(f"  M3U entry (searched): {relative_path}")
            
            if not m3u_entries:
                return {"success": False, "error": "Extraction succeeded but no ROM files found in extracted folder"}
            
            # Sort entries for consistent ordering (Disc 1, Disc 2, etc.)
            m3u_entries = sorted(m3u_entries)
            
            # Write M3U file
            with open(m3u_path, 'w', encoding='utf-8') as f:
                for entry in m3u_entries:
                    f.write(f"{entry}\n")
            
            logger.info(f"Created M3U: {m3u_path} with {len(m3u_entries)} entries")
            
            # Move original archive to staging folder after successful extraction
            archive_moved = False
            moved_to = None
            if move_to_staging:
                try:
                    staging_path = Path(staging_folder)
                    staging_path.mkdir(parents=True, exist_ok=True)
                    
                    # Create destination path, handling duplicates
                    dest_path = staging_path / path.name
                    counter = 1
                    while dest_path.exists():
                        stem = path.stem
                        dest_path = staging_path / f"{stem}_{counter}{ext}"
                        counter += 1
                    
                    # Move the archive
                    import shutil
                    shutil.move(str(path), str(dest_path))
                    archive_moved = True
                    moved_to = str(dest_path)
                    logger.info(f"Moved original archive to {dest_path}")
                except Exception as move_error:
                    logger.warning(f"Failed to move archive to staging: {move_error}")
            
            return {
                "success": True, 
                "m3u_path": str(m3u_path),
                "folder_path": str(extract_folder),
                "file_count": len(m3u_entries),
                "files": m3u_entries,
                "archive_moved": archive_moved,
                "moved_to": moved_to
            }
            
        except subprocess.TimeoutExpired:
            logger.error(f"Extraction timed out for {archive_path}")
            return {"success": False, "error": "Extraction timed out after 5 minutes"}
        except Exception as e:
            logger.error(f"M3U creation error: {e}")
            return {"success": False, "error": str(e)}
    
    def batch_create_m3u(self, archive_paths: List[str], delete_archives: bool = False, 
                          staging_folder: str = None) -> Dict[str, Any]:
        """Create M3U playlists for multiple multi-file archives
        
        Args:
            archive_paths: List of archive file paths to process
            delete_archives: If True, move original archives to staging folder after successful extraction
            staging_folder: Folder to move archives to instead of deleting (default: system temp dir)

        Returns:
            Dictionary with success/failure counts and details
        """
        results = {
            "success": True,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "moved_archives": 0,
            "details": []
        }

        # Default staging folder
        if delete_archives and not staging_folder:
            staging_folder = os.path.join(tempfile.gettempdir(), 'retrodb_m3u_staging')
        
        # Create staging folder if moving files
        if delete_archives and staging_folder:
            try:
                Path(staging_folder).mkdir(parents=True, exist_ok=True)
                logger.info(f"Using staging folder: {staging_folder}")
            except Exception as e:
                logger.error(f"Failed to create staging folder: {e}")
                return {"success": False, "error": f"Failed to create staging folder: {e}"}
        
        for archive_path in archive_paths:
            results["processed"] += 1
            
            try:
                # Create M3U for this archive
                result = self.create_m3u_playlist(archive_path)
                
                detail = {
                    "path": archive_path,
                    "name": Path(archive_path).name,
                    "success": result.get("success", False),
                    "m3u_path": result.get("m3u_path"),
                    "file_count": result.get("file_count", 0),
                    "error": result.get("error")
                }
                
                if result.get("success"):
                    results["succeeded"] += 1
                    
                    # Move original archive to staging folder instead of deleting
                    if delete_archives and staging_folder:
                        try:
                            archive_file = Path(archive_path)
                            dest_path = Path(staging_folder) / archive_file.name
                            
                            # Handle duplicate names in staging folder
                            if dest_path.exists():
                                base = dest_path.stem
                                ext = dest_path.suffix
                                counter = 1
                                while dest_path.exists():
                                    dest_path = Path(staging_folder) / f"{base}_{counter}{ext}"
                                    counter += 1
                            
                            shutil.move(str(archive_file), str(dest_path))
                            results["moved_archives"] += 1
                            detail["moved"] = True
                            detail["moved_to"] = str(dest_path)
                            logger.info(f"Moved archive to staging: {archive_path} -> {dest_path}")
                        except Exception as e:
                            detail["moved"] = False
                            detail["move_error"] = str(e)
                            logger.warning(f"Failed to move archive {archive_path}: {e}")
                else:
                    results["failed"] += 1
                
                results["details"].append(detail)
                
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "path": archive_path,
                    "name": Path(archive_path).name,
                    "success": False,
                    "error": str(e)
                })
                logger.error(f"Batch M3U error for {archive_path}: {e}")
        
        # Set overall success based on any failures
        results["success"] = results["failed"] == 0
        
        logger.info(f"Batch M3U complete: {results['succeeded']}/{results['processed']} succeeded, {results['moved_archives']} moved to staging")
        return results
    
    # Legacy scan method for backward compatibility
    def scan(self, path: str, task: TaskStatus) -> Dict[str, Any]:
        """Scan directory for archives (legacy method)"""
        self.task = task
        task.status = "running"
        task.start_time = time.time()
        task.results = {
            "archives_found": 0,
            "total_size": 0,
            "by_type": {},
            "multi_disc": [],
            "corrupt": [],
            "files": []
        }
        
        try:
            root = Path(path)
            if not root.exists():
                raise ValueError(f"Path does not exist: {path}")
            
            # Find all archives
            archives = self._find_archives(root)
            task.total = len(archives)
            task.logs.append(f"[{self._timestamp()}] Found {len(archives)} archives to process")
            
            for i, archive_path in enumerate(archives):
                if task.status == "cancelled":
                    task.logs.append(f"[{self._timestamp()}] Scan cancelled by user")
                    break
                
                while task.status == "paused":
                    time.sleep(0.5)
                
                task.progress = i + 1
                task.current_file = archive_path.name
                update_task(task)
                
                self._process_archive(archive_path, task)
            
            task.status = "completed" if task.status != "cancelled" else "cancelled"
            task.end_time = time.time()
            task.logs.append(f"[{self._timestamp()}] Scan completed. Found {task.results['archives_found']} archives ({self._format_size(task.results['total_size'])})")
            
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.logs.append(f"[{self._timestamp()}] ERROR: {str(e)}")
            logger.error(f"Archive scan error: {e}")
        
        update_task(task)
        return task.results
    
    def _find_archives(self, root: Path) -> List[Path]:
        """Find all archive files in directory"""
        archives = []
        extensions = set(self.config.archive_types)
        # Pass 41.14.C — resolve once; symlink-escape filter applied below
        # for every recursive sweep.
        root_resolved = root.resolve()

        if self.config.recursive_scan:
            for ext in extensions:
                archives.extend(
                    p for p in root.rglob(f"*{ext}")
                    if _safe_under_root(p, root_resolved)
                )
        else:
            for ext in extensions:
                archives.extend(root.glob(f"*{ext}"))
        
        return sorted(archives)
    
    def _process_archive(self, archive_path: Path, task: TaskStatus):
        """Process a single archive file"""
        try:
            ext = self._get_extension(archive_path)
            size = archive_path.stat().st_size
            
            task.results["archives_found"] += 1
            task.results["total_size"] += size
            task.results["by_type"][ext] = task.results["by_type"].get(ext, 0) + 1
            
            archive_info = {
                "path": str(archive_path),
                "name": archive_path.name,
                "size": size,
                "type": ext,
                "valid": True,
                "contents": []
            }
            
            # Verify integrity if requested
            if self.config.verify_integrity:
                is_valid = self._verify_archive(archive_path)
                archive_info["valid"] = is_valid
                if not is_valid:
                    task.results["corrupt"].append(str(archive_path))
                    task.logs.append(f"[{self._timestamp()}] ⚠️ CORRUPT: {archive_path.name}")
            
            # List contents
            contents = self._list_archive_contents(archive_path)
            archive_info["contents"] = contents
            
            # Check for multi-disc
            if self._is_multi_disc(contents, archive_path):
                task.results["multi_disc"].append(str(archive_path))
            
            task.results["files"].append(archive_info)
            
        except Exception as e:
            task.logs.append(f"[{self._timestamp()}] Error processing {archive_path.name}: {e}")
    
    def _get_extension(self, path: Path) -> str:
        """Get archive extension"""
        name = path.name.lower()
        for ext in [".tar.gz", ".7z", ".zip", ".rar"]:
            if name.endswith(ext):
                return ext
        return path.suffix.lower()
    
    def _verify_archive(self, archive_path: Path) -> bool:
        """Verify archive integrity"""
        ext = self._get_extension(archive_path)
        if ext not in self.ARCHIVE_COMMANDS:
            return True
        
        cmd_info = self.ARCHIVE_COMMANDS[ext]
        if not cmd_info.get("test"):
            return True
        
        try:
            cmd = cmd_info["test"] + [str(archive_path)]
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            return result.returncode == 0
        except Exception:
            return False
    
    def _list_archive_contents(self, archive_path: Path) -> List[str]:
        """List contents of an archive - returns just filenames"""
        ext = self._get_extension(archive_path)
        if ext not in self.ARCHIVE_COMMANDS:
            return []
        
        archive_name = archive_path.name  # Get the archive filename to filter it out
        
        try:
            if ext == ".7z":
                # Use -slt for structured output that's easier to parse
                cmd = ["7z", "l", "-slt", str(archive_path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    files = []
                    for line in result.stdout.splitlines():
                        # Look for "Path = filename" lines
                        if line.startswith("Path = "):
                            filename = line[7:].strip()  # Remove "Path = " prefix
                            # Skip empty paths and the archive itself (first entry in -slt output)
                            if filename and filename != archive_name and not filename.endswith(archive_name):
                                files.append(filename)
                    return files
            elif ext == ".zip":
                # unzip -Z1 gives just filenames, one per line
                cmd = ["unzip", "-Z1", str(archive_path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
            elif ext == ".rar":
                # unrar lb gives bare listing (just filenames)
                cmd = ["unrar", "lb", str(archive_path)]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception as e:
            logger.debug(f"Error listing archive contents: {e}")
        return []
    
    def _is_multi_disc(self, contents: List[str], archive_path: Path) -> bool:
        """Check if archive contains multi-disc game"""
        disc_patterns = [
            r'disc\s*[0-9]', r'disk\s*[0-9]', r'cd\s*[0-9]',
            r'\(disc\s*[0-9]\)', r'\(disk\s*[0-9]\)', r'\(cd\s*[0-9]\)'
        ]
        
        for content in contents:
            for pattern in disc_patterns:
                if re.search(pattern, content.lower()):
                    return True
        return False
    
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"


# =============================================================================
# CHD CONVERTER
# =============================================================================

class CHDConverter:
    """Convert disc images to CHD format"""
    
    SUPPORTED_FORMATS = {".iso", ".cue", ".gdi", ".mds", ".bin"}
    
    def __init__(self, config: ROMToolsConfig):
        self.config = config
        self.task: Optional[TaskStatus] = None
    
    def find_convertible_files(self, path: str) -> List[Dict[str, Any]]:
        """Find files that can be converted to CHD"""
        root = Path(path)
        files = []
        
        # Pass 41.14.C — symlink-escape guard for the recursive walk.
        root_resolved = root.resolve()
        for ext in self.SUPPORTED_FORMATS:
            for f in root.rglob(f"*{ext}"):
                if not _safe_under_root(f, root_resolved):
                    continue
                # Skip if CHD already exists
                chd_path = f.with_suffix(".chd")
                if self.config.chd_skip_existing and chd_path.exists():
                    continue

                files.append({
                    "path": str(f),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "type": ext.upper()[1:],
                    "chd_exists": chd_path.exists()
                })

        return sorted(files, key=lambda x: x["name"])
    
    def convert(self, files: List[str], task: TaskStatus) -> Dict[str, Any]:
        """Convert files to CHD format"""
        self.task = task
        task.status = "running"
        task.start_time = time.time()
        task.total = len(files)
        task.results = {
            "converted": 0,
            "failed": 0,
            "skipped": 0,
            "original_size": 0,
            "compressed_size": 0,
            "files": []
        }
        
        # Check if chdman is available
        if not self._check_chdman():
            task.status = "error"
            task.error = "chdman not found. Please install MAME tools."
            task.logs.append(f"[{self._timestamp()}] ERROR: chdman not found in PATH")
            update_task(task)
            return task.results
        
        try:
            for i, file_path in enumerate(files):
                if task.status == "cancelled":
                    task.logs.append(f"[{self._timestamp()}] Conversion cancelled by user")
                    break
                
                while task.status == "paused":
                    time.sleep(0.5)
                
                task.progress = i + 1
                task.current_file = Path(file_path).name
                update_task(task)
                
                self._convert_file(file_path, task)
            
            task.status = "completed" if task.status != "cancelled" else "cancelled"
            task.end_time = time.time()
            
            # Calculate space saved
            if task.results["original_size"] > 0:
                saved = task.results["original_size"] - task.results["compressed_size"]
                percent = (saved / task.results["original_size"]) * 100
                task.results["space_saved"] = saved
                task.results["percent_saved"] = round(percent, 1)
            
            task.logs.append(f"[{self._timestamp()}] Conversion completed. {task.results['converted']} files converted.")
            
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.logs.append(f"[{self._timestamp()}] ERROR: {str(e)}")
            logger.error(f"CHD conversion error: {e}")
        
        update_task(task)
        return task.results
    
    def _check_chdman(self) -> bool:
        """Check if chdman is available"""
        return shutil.which(self.config.chdman_path) is not None
    
    def _convert_file(self, file_path: str, task: TaskStatus):
        """Convert a single file to CHD via :func:`convert_one_to_chd`.

        The shared helper carries the Pass 40.11 atomic-write contract;
        this method handles the task-state bookkeeping (logs, counters)
        that the helper deliberately stays out of.
        """
        src_name = Path(file_path).name
        # Pass 42.5 — log the "Converting" line up-front to match prior
        # behaviour. The helper only logs to its return dict.
        task.logs.append(f"[{self._timestamp()}] Converting: {src_name}")

        file_result = convert_one_to_chd(
            file_path,
            self.config.chdman_path,
            do_verify=self.config.chd_verify_after_convert,
            delete_original=self.config.chd_delete_originals,
            skip_existing=self.config.chd_skip_existing,
        )
        status = file_result["status"]

        if status == "skipped":
            task.results["skipped"] += 1
            task.logs.append(f"[{self._timestamp()}] Skipped (CHD exists): {src_name}")
        elif status == "success":
            task.results["converted"] += 1
            task.results["original_size"] += file_result["original_size"]
            task.results["compressed_size"] += file_result["compressed_size"]
            task.logs.append(
                f"[{self._timestamp()}] ✓ Converted: {src_name} "
                f"({self._format_size(file_result['compressed_size'])})"
            )
            if self.config.chd_delete_originals and not file_result["error"]:
                task.logs.append(f"[{self._timestamp()}] Deleted original: {src_name}")
        else:
            task.results["failed"] += 1
            err = file_result.get("error", "")
            if err == "Conversion timed out":
                task.logs.append(f"[{self._timestamp()}] ✗ Timeout: {src_name}")
            elif "Verify failed" in err or err == "Verify failed":
                task.logs.append(f"[{self._timestamp()}] ✗ Verify failed: {src_name}")
            elif err:
                task.logs.append(f"[{self._timestamp()}] ✗ Error: {src_name} - {err}")
            else:
                task.logs.append(f"[{self._timestamp()}] ✗ Failed: {src_name}")

        task.results["files"].append(file_result)
    
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
    
    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"


# =============================================================================
# CHD VERIFIER
# =============================================================================

class CHDVerifier:
    """Verify integrity of CHD files"""
    
    def __init__(self, config: ROMToolsConfig):
        self.config = config
        self.task: Optional[TaskStatus] = None
    
    def find_chd_files(self, path: str) -> List[Dict[str, Any]]:
        """Find all CHD files in path"""
        root = Path(path)
        files = []
        
        pattern = "**/*.chd" if self.config.recursive_scan else "*.chd"
        for f in root.glob(pattern):
            files.append({
                "path": str(f),
                "name": f.name,
                "size": f.stat().st_size
            })
        
        return sorted(files, key=lambda x: x["name"])
    
    def verify(self, files: List[str], task: TaskStatus) -> Dict[str, Any]:
        """Verify CHD files"""
        self.task = task
        task.status = "running"
        task.start_time = time.time()
        task.total = len(files)
        task.results = {
            "total": len(files),
            "valid": 0,
            "invalid": 0,
            "total_size": 0,
            "files": []
        }
        
        # Check if chdman is available
        if not shutil.which(self.config.chdman_path):
            task.status = "error"
            task.error = "chdman not found. Please install MAME tools."
            task.logs.append(f"[{self._timestamp()}] ERROR: chdman not found in PATH")
            update_task(task)
            return task.results
        
        try:
            for i, file_path in enumerate(files):
                if task.status == "cancelled":
                    task.logs.append(f"[{self._timestamp()}] Verification cancelled by user")
                    break
                
                while task.status == "paused":
                    time.sleep(0.5)
                
                task.progress = i + 1
                task.current_file = Path(file_path).name
                update_task(task)
                
                self._verify_file(file_path, task)
            
            task.status = "completed" if task.status != "cancelled" else "cancelled"
            task.end_time = time.time()
            task.logs.append(f"[{self._timestamp()}] Verification completed. {task.results['valid']} valid, {task.results['invalid']} invalid.")
            
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.logs.append(f"[{self._timestamp()}] ERROR: {str(e)}")
            logger.error(f"CHD verify error: {e}")
        
        update_task(task)
        return task.results
    
    def _verify_file(self, file_path: str, task: TaskStatus):
        """Verify a single CHD file"""
        src = Path(file_path)
        
        file_result = {
            "path": str(src),
            "name": src.name,
            "size": src.stat().st_size,
            "status": "checking",
            "error": ""
        }
        
        task.results["total_size"] += file_result["size"]
        
        try:
            task.logs.append(f"[{self._timestamp()}] Verifying: {src.name}")
            
            cmd = [self.config.chdman_path, "verify", "-i", str(src)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                file_result["status"] = "valid"
                task.results["valid"] += 1
                task.logs.append(f"[{self._timestamp()}] ✓ Valid: {src.name}")
            else:
                file_result["status"] = "invalid"
                file_result["error"] = result.stderr[:200] if result.stderr else "Verification failed"
                task.results["invalid"] += 1
                task.logs.append(f"[{self._timestamp()}] ✗ Invalid: {src.name}")
                
        except subprocess.TimeoutExpired:
            file_result["status"] = "invalid"
            file_result["error"] = "Verification timed out"
            task.results["invalid"] += 1
            task.logs.append(f"[{self._timestamp()}] ✗ Timeout: {src.name}")
        except Exception as e:
            file_result["status"] = "invalid"
            file_result["error"] = str(e)
            task.results["invalid"] += 1
            task.logs.append(f"[{self._timestamp()}] ✗ Error: {src.name}")
        
        task.results["files"].append(file_result)
    
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")


# =============================================================================
# DUPLICATE FINDER
# =============================================================================

class DuplicateFinder:
    """Find duplicate ROM files"""
    
    ROM_EXTENSIONS = {
        ".zip", ".7z", ".rar", ".iso", ".cue", ".chd", ".gdi",
        ".nes", ".snes", ".sfc", ".smc", ".gba", ".gbc", ".gb",
        ".nds", ".3ds", ".n64", ".z64", ".v64", ".gcm", ".gcz",
        ".wbfs", ".rvz", ".bin", ".cso", ".pbp", ".vpk"
    }
    
    # Region tags to normalize
    REGION_TAGS = [
        r'\(USA\)', r'\(Europe\)', r'\(Japan\)', r'\(World\)',
        r'\(U\)', r'\(E\)', r'\(J\)', r'\(W\)',
        r'\(En\)', r'\(Fr\)', r'\(De\)', r'\(Es\)', r'\(It\)',
        r'\[!\]', r'\[h\]', r'\[b\]', r'\[a\]', r'\[o\]', r'\[T\]',
        r'\(Rev \d+\)', r'\(V\d+\.\d+\)', r'\(Alt\s*\d*\)'
    ]
    
    def __init__(self, config: ROMToolsConfig):
        self.config = config
        self.task: Optional[TaskStatus] = None
    
    def scan(self, path: str, task: TaskStatus) -> Dict[str, Any]:
        """Scan for duplicate files"""
        self.task = task
        task.status = "running"
        task.start_time = time.time()
        task.results = {
            "files_scanned": 0,
            "duplicate_groups": 0,
            "duplicate_files": 0,
            "wasted_space": 0,
            "groups": []
        }
        
        try:
            root = Path(path)
            if not root.exists():
                raise ValueError(f"Path does not exist: {path}")
            
            # Find all ROM files
            files = self._find_rom_files(root)
            task.total = len(files)
            task.logs.append(f"[{self._timestamp()}] Found {len(files)} ROM files to analyze")
            
            # Group by chosen method
            if self.config.duplicate_method == "hash":
                groups = self._find_by_hash(files, task)
            elif self.config.duplicate_method == "name":
                groups = self._find_by_name(files, task)
            else:  # both
                groups = self._find_by_both(files, task)
            
            # Filter to only groups with duplicates
            duplicate_groups = [g for g in groups if len(g["files"]) > 1]
            
            task.results["groups"] = duplicate_groups
            task.results["duplicate_groups"] = len(duplicate_groups)
            
            for group in duplicate_groups:
                # Count all but the first (kept) file as duplicates
                task.results["duplicate_files"] += len(group["files"]) - 1
                # Sum sizes of duplicate files
                for f in group["files"][1:]:
                    task.results["wasted_space"] += f["size"]
            
            task.status = "completed" if task.status != "cancelled" else "cancelled"
            task.end_time = time.time()
            task.logs.append(f"[{self._timestamp()}] Scan completed. Found {task.results['duplicate_groups']} duplicate groups.")
            
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.logs.append(f"[{self._timestamp()}] ERROR: {str(e)}")
            logger.error(f"Duplicate scan error: {e}")
        
        update_task(task)
        return task.results
    
    def _find_rom_files(self, root: Path) -> List[Path]:
        """Find all ROM files"""
        files = []
        extensions = self.ROM_EXTENSIONS.copy()
        
        if not self.config.include_archives:
            extensions -= {".zip", ".7z", ".rar"}

        # Pass 41.14.C — symlink-escape guard for the recursive walk.
        root_resolved = root.resolve()
        if self.config.recursive_scan:
            for ext in extensions:
                files.extend(
                    p for p in root.rglob(f"*{ext}")
                    if _safe_under_root(p, root_resolved)
                )
        else:
            for ext in extensions:
                files.extend(root.glob(f"*{ext}"))

        return sorted(files)
    
    def _find_by_hash(self, files: List[Path], task: TaskStatus) -> List[Dict]:
        """Find duplicates by file hash"""
        hash_groups: Dict[str, List[Dict]] = {}
        
        for i, f in enumerate(files):
            if task.status == "cancelled":
                break
            
            task.progress = i + 1
            task.current_file = f.name
            task.results["files_scanned"] = i + 1
            update_task(task)
            
            try:
                file_hash = self._hash_file(f)
                file_info = {
                    "path": str(f),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "hash": file_hash
                }
                
                if file_hash not in hash_groups:
                    hash_groups[file_hash] = []
                hash_groups[file_hash].append(file_info)
                
            except Exception as e:
                task.logs.append(f"[{self._timestamp()}] Error hashing {f.name}: {e}")
        
        # Convert to list format
        groups = []
        for hash_val, group_files in hash_groups.items():
            if len(group_files) > 1:
                # Sort by modified date, newest first
                group_files.sort(key=lambda x: x["modified"], reverse=True)
                groups.append({
                    "key": hash_val[:16],
                    "name": self._get_common_name(group_files),
                    "count": len(group_files),
                    "wasted": sum(f["size"] for f in group_files[1:]),
                    "files": group_files
                })
        
        return groups
    
    def _find_by_name(self, files: List[Path], task: TaskStatus) -> List[Dict]:
        """Find duplicates by normalized filename"""
        name_groups: Dict[str, List[Dict]] = {}
        
        for i, f in enumerate(files):
            if task.status == "cancelled":
                break
            
            task.progress = i + 1
            task.current_file = f.name
            task.results["files_scanned"] = i + 1
            update_task(task)
            
            try:
                normalized = self._normalize_name(f.stem)
                file_info = {
                    "path": str(f),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "normalized": normalized
                }
                
                if normalized not in name_groups:
                    name_groups[normalized] = []
                name_groups[normalized].append(file_info)
                
            except Exception as e:
                task.logs.append(f"[{self._timestamp()}] Error processing {f.name}: {e}")
        
        # Convert to list format
        groups = []
        for norm_name, group_files in name_groups.items():
            if len(group_files) > 1:
                group_files.sort(key=lambda x: x["modified"], reverse=True)
                groups.append({
                    "key": norm_name[:32],
                    "name": self._get_common_name(group_files),
                    "count": len(group_files),
                    "wasted": sum(f["size"] for f in group_files[1:]),
                    "files": group_files
                })
        
        return groups
    
    def _find_by_both(self, files: List[Path], task: TaskStatus) -> List[Dict]:
        """Find duplicates by both hash and name"""
        # First find by name, then verify with hash
        name_groups = self._find_by_name(files, task)
        
        verified_groups = []
        for group in name_groups:
            # Sub-group by hash
            hash_subgroups: Dict[str, List[Dict]] = {}
            for f in group["files"]:
                try:
                    file_hash = self._hash_file(Path(f["path"]))
                    f["hash"] = file_hash
                    if file_hash not in hash_subgroups:
                        hash_subgroups[file_hash] = []
                    hash_subgroups[file_hash].append(f)
                except Exception:
                    pass
            
            # Add groups where both name and hash match
            for hash_val, subgroup in hash_subgroups.items():
                if len(subgroup) > 1:
                    verified_groups.append({
                        "key": hash_val[:16],
                        "name": self._get_common_name(subgroup),
                        "count": len(subgroup),
                        "wasted": sum(f["size"] for f in subgroup[1:]),
                        "files": subgroup
                    })
        
        return verified_groups
    
    def _hash_file(self, path: Path, chunk_size: int = 65536) -> str:
        """Calculate SHA-256 hash of file"""
        hasher = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def _normalize_name(self, name: str) -> str:
        """Normalize filename for comparison"""
        normalized = name
        
        if self.config.ignore_region_tags:
            for pattern in self.REGION_TAGS:
                normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
        
        # Remove extra whitespace and lowercase
        normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
        return normalized
    
    def _get_common_name(self, files: List[Dict]) -> str:
        """Get a common display name for a group"""
        if files:
            # Use the shortest filename as the group name
            names = [f["name"] for f in files]
            return min(names, key=len)
        return "Unknown"
    
    def delete_duplicates(self, files_to_delete: List[str]) -> Dict[str, Any]:
        """Delete specified duplicate files"""
        results = {
            "deleted": 0,
            "failed": 0,
            "freed_space": 0,
            "errors": []
        }
        
        for file_path in files_to_delete:
            try:
                p = Path(file_path)
                if p.exists():
                    size = p.stat().st_size
                    p.unlink()
                    results["deleted"] += 1
                    results["freed_space"] += size
                else:
                    results["errors"].append(f"File not found: {file_path}")
                    results["failed"] += 1
            except Exception as e:
                results["errors"].append(f"Error deleting {file_path}: {e}")
                results["failed"] += 1
        
        return results
    
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_size(size: int) -> str:
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def check_tool_availability() -> Dict[str, bool]:
    """Check which tools are available"""
    return {
        "unzip": shutil.which("unzip") is not None,
        "7z": shutil.which("7z") is not None,
        "unrar": shutil.which("unrar") is not None or shutil.which("rar") is not None,
        "chdman": shutil.which("chdman") is not None
    }
