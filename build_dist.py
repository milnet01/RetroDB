#!/usr/bin/env python3
"""
RetroDB Distribution Builder
Creates platform-specific distributable ZIP files for Patreon release.

Outputs to: /mnt/Storage/Scripts/Linux/Staging_Area/RetroDB/
Filenames:  RetroDB-vX.Y.Z-Linux.zip, RetroDB-vX.Y.Z-macOS.zip, RetroDB-vX.Y.Z-Windows.zip

Usage:
    python build_dist.py            # Build all 3 platforms
    python build_dist.py linux      # Build Linux only
    python build_dist.py macos      # Build macOS only
    python build_dist.py windows    # Build Windows only
"""

import os
import sys
import zipfile


# ── Staging area (outside project dir) ──────────────────────────────────────
STAGING_DIR = '/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB'

# ── Platform definitions ────────────────────────────────────────────────────
# Each platform excludes the start scripts for the other two platforms
PLATFORMS = {
    'Linux':   {'exclude_files': {'start.bat', 'start.command'}},
    'macOS':   {'exclude_files': {'start.bat', 'start.sh'}},
    'Windows': {'exclude_files': {'start.sh', 'start.command'}},
}

# ── Global exclusions (same across all platforms) ───────────────────────────
EXCLUDE_FILES = {
    'config.py',
    'data/scraper_settings.json',
    'data/settings.json',
    'data/rom_tools_config.json',
    'data/psn_tokens.json',
    'data/xbox_tokens.json',
    'data/.secret_key',
    'data/retrodb.db',
    'data/hltb_dataset.csv',
    'docs/psn-npsso.env',
    'RetroDB_Directory_Listing.txt',
    '.continueignore',
}

EXCLUDE_DIRS = {
    '__pycache__', '.claude', '.git', '.vscode', '.idea',
    'demo', 'dist', 'venv', '.venv',
    'database', 'logs',  # .gitkeep files added explicitly
}

EXCLUDE_EXTENSIONS = {'.db', '.db-journal', '.db-wal', '.log', '.pyc', '.pyo', '.bak'}

# Scraped/runtime media (excluded from distribution)
# static/videos/ is a top-level directory under static/
# static/images/ uses a whitelist — only hardware, ratings, systems are included
INCLUDE_IMAGE_DIRS = {'hardware', 'ratings', 'systems', 'avatars'}
EXCLUDE_STATIC_DIRS = {'videos'}  # Top-level dirs under static/ to skip entirely


def get_version(base_dir):
    """Read APP_VERSION from config.py (falls back to config.example.py)."""
    for config_name in ('config.py', 'config.example.py'):
        config_path = os.path.join(base_dir, config_name)
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                for line in f:
                    if line.strip().startswith('APP_VERSION'):
                        return line.split('=')[1].strip().strip('"').strip("'")
    return '0.0.0'


def collect_files(base_dir, platform_exclude_files):
    """Walk the project tree and yield (rel_path, full_path) tuples to include."""
    all_exclude_files = EXCLUDE_FILES | {f for f in platform_exclude_files}

    for root, dirs, files in os.walk(base_dir):
        rel_root = os.path.relpath(root, base_dir)
        if rel_root == '.':
            rel_root = ''

        # Skip excluded directories
        dir_name = os.path.basename(root)
        if dir_name in EXCLUDE_DIRS:
            dirs.clear()
            continue

        # Skip hidden directories (except root)
        if rel_root and dir_name.startswith('.'):
            dirs.clear()
            continue

        # Skip excluded top-level dirs under static/ (e.g. static/videos/)
        rel_normalized = rel_root.replace('\\', '/')
        if rel_normalized.startswith('static/'):
            parts = rel_normalized.split('/')
            if len(parts) >= 2 and parts[1] in EXCLUDE_STATIC_DIRS:
                dirs.clear()
                continue

        # Whitelist for static/images/ — only include hardware, ratings, systems
        # Files directly in static/images/ (e.g. placeholder.png) are always included
        if rel_normalized.startswith('static/images/'):
            parts = rel_normalized.split('/')
            if len(parts) >= 3 and parts[2] not in INCLUDE_IMAGE_DIRS:
                dirs.clear()
                continue

        # Filter subdirs so os.walk doesn't recurse into them
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]

        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext in EXCLUDE_EXTENSIONS:
                continue

            if filename.startswith('.') and filename not in ('.gitkeep', '.gitignore'):
                continue

            rel_path = os.path.join(rel_root, filename) if rel_root else filename
            rel_normalized = rel_path.replace('\\', '/')

            if rel_normalized in all_exclude_files:
                continue

            yield rel_path, os.path.join(root, filename)


def build_platform(base_dir, version, platform_name, platform_cfg):
    """Build a single platform ZIP."""
    zip_name = f"RetroDB-v{version}-{platform_name}.zip"
    zip_path = os.path.join(STAGING_DIR, zip_name)
    folder_name = f"RetroDB-v{version}"

    print(f"\n  Building {zip_name}...")

    # Remove old zip if exists
    if os.path.exists(zip_path):
        os.remove(zip_path)

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel_path, full_path in collect_files(base_dir, platform_cfg['exclude_files']):
            file_size = os.path.getsize(full_path)
            arc_name = os.path.join(folder_name, rel_path)
            zf.write(full_path, arc_name)
            file_count += 1
            total_size += file_size

        # Explicitly add .gitkeep for empty directories
        for gitkeep_dir in ['database', 'logs']:
            gitkeep_path = os.path.join(base_dir, gitkeep_dir, '.gitkeep')
            if os.path.exists(gitkeep_path):
                arc_name = os.path.join(folder_name, gitkeep_dir, '.gitkeep')
                zf.write(gitkeep_path, arc_name)
                file_count += 1

    zip_size = os.path.getsize(zip_path)
    ratio = (1 - zip_size / total_size) * 100 if total_size else 0

    print(f"    Files: {file_count}  |  "
          f"Size: {total_size / (1024*1024):.1f} MB → {zip_size / (1024*1024):.1f} MB  |  "
          f"Compression: {ratio:.0f}%")

    return zip_path


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    version = get_version(base_dir)

    # Parse optional platform argument
    requested = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        platform_map = {'linux': 'Linux', 'macos': 'macOS', 'windows': 'Windows'}
        if arg in platform_map:
            requested = platform_map[arg]
        else:
            print(f"Unknown platform: {sys.argv[1]}")
            print("Usage: python build_dist.py [linux|macos|windows]")
            sys.exit(1)

    # Ensure staging directory exists
    os.makedirs(STAGING_DIR, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  RetroDB v{version} — Distribution Builder")
    print(f"  Output: {STAGING_DIR}")
    print(f"{'='*60}")

    platforms_to_build = {requested: PLATFORMS[requested]} if requested else PLATFORMS
    built = []

    for name, cfg in platforms_to_build.items():
        path = build_platform(base_dir, version, name, cfg)
        built.append(path)

    print(f"\n{'='*60}")
    print(f"  Done! {len(built)} ZIP(s) created:")
    for p in built:
        print(f"    → {p}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
