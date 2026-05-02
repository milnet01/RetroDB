#!/usr/bin/env python3
"""
RetroDB Distribution Builder
Creates platform-specific distributable ZIP files for Patreon release.

Two distribution shapes:

  Source     — small ZIP, end user must install Python + run requirements.txt
               (default; works on all 3 platforms from any host)
  Standalone — self-contained PyInstaller bundle (Python runtime + deps + assets
               baked in; user just unzips and runs the launcher). Built via
               retrodb.spec; can ONLY produce the host platform's binary
               (PyInstaller has no cross-compile).

Outputs to: /mnt/Storage/Scripts/Linux/Staging_Area/RetroDB/
Filenames:  RetroDB-vX.Y.Z-Linux.zip            (source)
            RetroDB-vX.Y.Z-Linux-Standalone.zip (standalone)

Usage:
    python build_dist.py                          # All 3 source ZIPs
    python build_dist.py linux                    # Linux source only
    python build_dist.py --standalone             # Standalone for host platform
    python build_dist.py --standalone linux       # Standalone Linux (host=Linux)
"""

import os
import platform
import shutil
import subprocess
import sys
import zipfile


# ── Staging area (outside project dir) ──────────────────────────────────────
# RETRODB_STAGING_DIR overrides the hardcoded path — used by release.yml
# to redirect output to /tmp/staging on CI runners that don't have the
# host's /mnt/Storage/ tree. Default mirrors the maintainer's local layout.
STAGING_DIR = os.environ.get(
    'RETRODB_STAGING_DIR',
    '/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB',
)

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


def _host_platform():
    """Map platform.system() to one of {'Linux', 'macOS', 'Windows'}."""
    sysname = platform.system()
    if sysname == 'Darwin':
        return 'macOS'
    if sysname in ('Linux', 'Windows'):
        return sysname
    return None


def build_standalone(base_dir, version, host_name):
    """Run PyInstaller against retrodb.spec and zip dist/retrodb/ into a
    Standalone bundle for the host platform.

    PyInstaller cannot cross-compile — the produced zip is valid only for
    the OS that built it. Linux→Linux, macOS→macOS, Windows→Windows.
    """
    spec_path = os.path.join(base_dir, 'retrodb.spec')
    if not os.path.exists(spec_path):
        print(f"ERROR: retrodb.spec not found at {spec_path}")
        sys.exit(1)

    print(f"\n  Building standalone {host_name} bundle via PyInstaller…")
    print("  (this takes 3–6 min and uses ~5 GB temp during the build)")

    # Wipe any prior PyInstaller output so we don't ship leftover files
    # from an aborted earlier run.
    for tmp_dir in ('build', 'dist'):
        tmp_path = os.path.join(base_dir, tmp_dir)
        if os.path.isdir(tmp_path):
            shutil.rmtree(tmp_path)

    # PyInstaller writes to ./build and ./dist; cwd must be project root.
    result = subprocess.run(
        ['pyinstaller', spec_path, '--noconfirm', '--log-level', 'WARN'],
        cwd=base_dir,
    )
    if result.returncode != 0:
        print(f"ERROR: PyInstaller exited {result.returncode}")
        sys.exit(result.returncode)

    bundle_dir = os.path.join(base_dir, 'dist', 'retrodb')
    if not os.path.isdir(bundle_dir):
        print(f"ERROR: PyInstaller produced no output at {bundle_dir}")
        sys.exit(1)

    zip_name = f"RetroDB-v{version}-{host_name}-Standalone.zip"
    zip_path = os.path.join(STAGING_DIR, zip_name)
    folder_name = f"RetroDB-v{version}-Standalone"
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print(f"  Packaging {zip_name}…")
    file_count = 0
    total_size = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # compresslevel=6 — bundle is already mostly compressed binaries
        # (libMIOpen.so etc). Level 9 saves <1 % at 3× the CPU cost.
        for root, _dirs, files in os.walk(bundle_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, bundle_dir)
                arc_name = os.path.join(folder_name, rel_path)
                zf.write(full_path, arc_name)
                file_count += 1
                total_size += os.path.getsize(full_path)

    zip_size = os.path.getsize(zip_path)
    ratio = (1 - zip_size / total_size) * 100 if total_size else 0
    print(f"    Files: {file_count}  |  "
          f"Size: {total_size / (1024*1024):.0f} MB → {zip_size / (1024*1024):.0f} MB  |  "
          f"Compression: {ratio:.0f}%")
    return zip_path


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    version = get_version(base_dir)

    # Parse args: optional --standalone flag + optional platform name
    standalone = False
    args = list(sys.argv[1:])
    if '--standalone' in args:
        standalone = True
        args.remove('--standalone')

    requested = None
    if args:
        arg = args[0].lower()
        platform_map = {'linux': 'Linux', 'macos': 'macOS', 'windows': 'Windows'}
        if arg in platform_map:
            requested = platform_map[arg]
        else:
            print(f"Unknown platform: {args[0]}")
            print("Usage: python build_dist.py [--standalone] [linux|macos|windows]")
            sys.exit(1)

    # Ensure staging directory exists
    os.makedirs(STAGING_DIR, exist_ok=True)

    mode = 'Standalone (PyInstaller bundle)' if standalone else 'Source (Python required)'
    print(f"\n{'='*60}")
    print(f"  RetroDB v{version} — Distribution Builder")
    print(f"  Mode:   {mode}")
    print(f"  Output: {STAGING_DIR}")
    print(f"{'='*60}")

    if standalone:
        host = _host_platform()
        if host is None:
            print(f"ERROR: unrecognised host OS '{platform.system()}' for --standalone")
            sys.exit(1)
        if requested and requested != host:
            print(f"ERROR: PyInstaller cannot cross-compile. Host is '{host}', "
                  f"but you asked for '{requested}'. Run on a {requested} host instead.")
            sys.exit(1)
        path = build_standalone(base_dir, version, host)
        built = [path]
    else:
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
