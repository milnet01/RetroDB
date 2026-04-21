#!/usr/bin/env python3
"""
RetroDB JS Build Script
Concatenates and conservatively minifies deferred JS files into a single bundle.

Usage:
    python build_js.py              # Build app.bundle.js (minified)
    python build_js.py --dev        # Just verify all files exist
    python build_js.py --no-minify  # Concatenate without minifying

Notes:
    - theme.js is NOT included (loaded separately for FOUC prevention)
    - Page-specific JS files are NOT included (loaded per-page)
    - Each source file is wrapped in an IIFE to prevent variable leaking
    - Minification is conservative: no variable renaming, no structural changes
"""

import re
import sys
from pathlib import Path

# Deferred JS files in load order (must match base.html script tag order)
JS_ORDER = [
    'utils.js',
    'page-lifecycle.js',
    'filters.js',
    'bulk-scrape.js',
    'bulk-edit.js',
    'toast-controller.js',
    'game-list.js',
    'game-modals.js',
    'main.js',
]

# Files NOT included in bundle (loaded separately)
EXCLUDED = [
    'theme.js',              # FOUC prevention - loaded non-deferred
    'all-games-controller.js',  # Page-specific
    'achievements.js',          # Page-specific
    'trophies.js',              # Page-specific
    'settings-page.js',         # Page-specific
    'log-viewer.js',            # Page-specific
    'rom-tools.js',             # Page-specific
    'museum.js',                # Page-specific
]

OUTPUT_FILENAME = 'app.bundle.js'


def get_js_dir():
    """Get the JS directory path."""
    script_dir = Path(__file__).parent
    return script_dir / 'static' / 'js'


def verify_files():
    """Verify all JS files exist."""
    js_dir = get_js_dir()
    missing = []

    for js_file in JS_ORDER:
        path = js_dir / js_file
        if not path.exists():
            missing.append(js_file)

    return missing


def is_output_fresh():
    """Return True if app.bundle.js is newer than every source file.

    Skips the rebuild when no source has changed since the last build — makes
    the mandatory "rebuild JS after edits" step a no-op when nothing touched
    the bundled JS, instead of re-reading and re-concatenating 9 files.
    """
    js_dir = get_js_dir()
    output_path = js_dir / OUTPUT_FILENAME
    if not output_path.exists():
        return False

    output_mtime = output_path.stat().st_mtime
    for js_file in JS_ORDER:
        path = js_dir / js_file
        if not path.exists():
            continue
        if path.stat().st_mtime > output_mtime:
            return False

    # Also consider the build script itself — if we changed the minifier,
    # re-run regardless of source mtimes.
    script_path = Path(__file__).resolve()
    if script_path.stat().st_mtime > output_mtime:
        return False

    return True


def minify_js(js_text):
    """Conservative JS minification.

    Only performs safe transformations:
    - Remove lines that are purely whitespace
    - Remove lines that only contain a single-line // comment
    - Collapse 3+ consecutive newlines into 2
    - Trim trailing whitespace from lines

    Does NOT:
    - Remove multi-line comments (may contain important data)
    - Rename variables
    - Remove whitespace between tokens
    - Insert or remove semicolons
    """
    lines = js_text.split('\n')
    result = []

    for line in lines:
        stripped = line.strip()

        # Remove lines that are only whitespace
        if stripped == '':
            result.append('')
            continue

        # Remove lines that only contain a single-line // comment
        # (line starts with optional whitespace then //)
        if stripped.startswith('//'):
            continue

        # Trim trailing whitespace from lines
        result.append(line.rstrip())

    text = '\n'.join(result)

    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text


def build(do_minify=True):
    """Concatenate all JS files into app.bundle.js, optionally minifying."""
    js_dir = get_js_dir()
    output = []
    total_lines = 0
    file_count = 0

    print(f"Building JS bundle{' (minified)' if do_minify else ''}...")
    print("-" * 50)

    for js_file in JS_ORDER:
        path = js_dir / js_file
        if not path.exists():
            print(f"  MISSING: {js_file}")
            continue

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.count('\n') + 1
            total_lines += lines

        # Wrap each file in an IIFE to prevent variable leaking
        wrapped = f'// === {js_file} ===\n(function(){{\n{content}\n}})();\n'
        output.append(wrapped)
        file_count += 1

        size_kb = len(content.encode('utf-8')) / 1024
        print(f"  + {js_file} ({lines} lines, {size_kb:.1f} KB)")

    combined = '\n'.join(output)
    original_size = len(combined.encode('utf-8'))

    if do_minify:
        combined = minify_js(combined)

    final_size = len(combined.encode('utf-8'))

    # Write combined output
    output_path = js_dir / OUTPUT_FILENAME
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(combined)

    print("-" * 50)
    print(f"Source: {total_lines:,} lines across {file_count} files")
    if do_minify:
        reduction = (1 - final_size / original_size) * 100 if original_size else 0
        print(f"Size: {original_size:,} -> {final_size:,} bytes ({reduction:.1f}% reduction)")
    else:
        print(f"Size: {final_size:,} bytes")
    print(f"Output: {output_path}")
    print()
    print(f"Excluded (loaded separately):")
    for f in EXCLUDED:
        print(f"  - {f}")
    print()
    print("Build complete!")


def main():
    """Main entry point."""
    dev_mode = '--dev' in sys.argv
    no_minify = '--no-minify' in sys.argv
    force = '--force' in sys.argv

    # Verify all files exist
    missing = verify_files()

    if missing:
        print("Missing JS files:")
        for f in missing:
            print(f"  - {f}")
        if not dev_mode:
            print("\nBuild aborted. Create missing files first.")
            sys.exit(1)
        return

    if dev_mode:
        print(f"All {len(JS_ORDER)} JS files verified!")
        return

    if not force and is_output_fresh():
        print(f"{OUTPUT_FILENAME} is up-to-date — no source changes detected. (use --force to rebuild)")
        return

    # Build concatenated (and optionally minified) file
    build(do_minify=not no_minify)


if __name__ == '__main__':
    main()
