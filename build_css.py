#!/usr/bin/env python3
"""
RetroDB CSS Build Script
Concatenates and minifies all modular CSS files into a single production file.

Usage:
    python build_css.py         # Build main.min.css (minified)
    python build_css.py --dev   # Just verify all files exist
    python build_css.py --no-minify  # Concatenate without minifying
"""

import hashlib
import json
import re
import sys
from pathlib import Path

# CSS files in load order (must match main-new.css @import order)
CSS_ORDER = [
    # 1. Core
    'core/variables.css',
    'core/reset.css',
    'core/typography.css',
    'core/themes.css',

    # 2. Layout
    'layout/layout.css',
    'layout/sidebar.css',

    # 3. Base Components
    'components/buttons.css',
    'components/forms.css',
    'components/cards.css',
    'components/badges.css',
    'components/tables.css',
    'components/tabs.css',
    'components/modals.css',
    'components/toasts.css',
    'components/progress.css',
    'components/tags.css',
    'components/queue-manager.css',

    # 4. Features
    'features/game-cards.css',
    'features/game-modals.css',
    'features/trophies.css',
    'features/achievements.css',
    'features/stat-boxes.css',
    'features/filters.css',
    'features/hltb.css',

    # 5. Pages
    'pages/game-list.css',
    'pages/pages.css',

    # 6. Effects
    'effects/backgrounds.css',
    'effects/animations.css',

    # 7. Utilities
    'utilities.css',

    # 8. Responsive (last)
    'layout/responsive.css',
]

def get_css_dir():
    """Get the CSS directory path."""
    script_dir = Path(__file__).parent
    return script_dir / 'static' / 'css'

def verify_files():
    """Verify all CSS files exist."""
    css_dir = get_css_dir()
    missing = []

    for css_file in CSS_ORDER:
        path = css_dir / css_file
        if not path.exists():
            missing.append(css_file)

    return missing


def is_output_fresh():
    """Return True if main.min.css is newer than every source file.

    Skips the rebuild when no source has changed since the last build — makes
    the mandatory "rebuild CSS after edits" step a no-op when nothing touched
    CSS, instead of a 100ms re-read/re-minify every version bump.
    """
    css_dir = get_css_dir()
    output_path = css_dir / 'main.min.css'
    if not output_path.exists():
        return False

    output_mtime = output_path.stat().st_mtime
    for css_file in CSS_ORDER:
        path = css_dir / css_file
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

def _extract_calc_expressions(css_text):
    """Extract calc() expressions and replace with placeholders to protect them.

    calc() needs spaces around + and - operators to be valid CSS,
    so we must protect these from whitespace stripping.
    """
    placeholders = []
    result = []
    i = 0
    while i < len(css_text):
        # Look for calc(
        if css_text[i:i+5] == 'calc(':
            # Find matching closing paren (handle nested parens)
            depth = 0
            start = i
            i += 4  # move to the '('
            while i < len(css_text):
                if css_text[i] == '(':
                    depth += 1
                elif css_text[i] == ')':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            expr = css_text[start:i]
            # Collapse internal whitespace but preserve spaces around + and -
            expr = re.sub(r'\s+', ' ', expr)
            placeholder = f'__CALC_{len(placeholders)}__'
            placeholders.append(expr)
            result.append(placeholder)
        else:
            result.append(css_text[i])
            i += 1
    return ''.join(result), placeholders


def _restore_calc_expressions(css_text, placeholders):
    """Restore calc() expressions from placeholders."""
    for idx, expr in enumerate(placeholders):
        css_text = css_text.replace(f'__CALC_{idx}__', expr)
    return css_text


def minify_css(css_text):
    """Minify CSS by removing comments, excess whitespace, and unnecessary characters.

    Preserves spaces inside calc() expressions (required for valid CSS).
    """
    # Remove multi-line comments (but preserve /*! ... */ license comments)
    css_text = re.sub(r'/\*(?!!)[^*]*\*+(?:[^/*][^*]*\*+)*/', '', css_text)
    # Remove single-line // comments (only at start of line)
    css_text = re.sub(r'(?m)^\s*//.*$', '', css_text)
    # Protect calc() expressions before whitespace stripping
    css_text, calc_placeholders = _extract_calc_expressions(css_text)
    # Collapse multiple whitespace (spaces, tabs) into single space
    css_text = re.sub(r'[ \t]+', ' ', css_text)
    # Remove spaces around braces, colons, semicolons, commas
    css_text = re.sub(r'\s*{\s*', '{', css_text)
    css_text = re.sub(r'\s*}\s*', '}', css_text)
    css_text = re.sub(r'\s*;\s*', ';', css_text)
    css_text = re.sub(r'\s*:\s*', ':', css_text)
    css_text = re.sub(r'\s*,\s*', ',', css_text)
    # Remove trailing semicolons before closing braces
    css_text = css_text.replace(';}', '}')
    # Remove newlines
    css_text = re.sub(r'\n+', '', css_text)
    # Restore calc() expressions
    css_text = _restore_calc_expressions(css_text, calc_placeholders)
    # Remove leading/trailing whitespace
    css_text = css_text.strip()
    return css_text


def build(do_minify=True):
    """Concatenate all CSS files into main.min.css, optionally minifying."""
    css_dir = get_css_dir()
    output = []
    total_lines = 0

    print(f"Building CSS bundle{' (minified)' if do_minify else ''}...")
    print("-" * 50)

    for css_file in CSS_ORDER:
        path = css_dir / css_file
        if not path.exists():
            print(f"  ✗ Missing: {css_file}")
            continue

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.count('\n') + 1
            total_lines += lines

        output.append(content)
        print(f"  ✓ {css_file} ({lines} lines)")

    combined = '\n'.join(output)
    original_size = len(combined.encode('utf-8'))

    if do_minify:
        combined = minify_css(combined)

    final_size = len(combined.encode('utf-8'))

    # Write combined output
    output_path = css_dir / 'main.min.css'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(combined)

    # Record content hash in the shared asset manifest (Pass 13.3).
    _update_manifest({'css/main.min.css': _content_hash(output_path)})

    print("-" * 50)
    print(f"Source: {total_lines} lines across {len(CSS_ORDER)} files")
    if do_minify:
        reduction = (1 - final_size / original_size) * 100 if original_size else 0
        print(f"Size: {original_size:,} → {final_size:,} bytes ({reduction:.1f}% reduction)")
    print(f"Output: {output_path}")
    print("Build complete!")


def _content_hash(path):
    """First 8 hex chars of SHA-256 of file content."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()[:8]


def _update_manifest(entries):
    """Merge entries into static/asset_manifest.json (shared with build_js)."""
    manifest_path = Path(__file__).parent / 'static' / 'asset_manifest.json'
    manifest = {}
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f) or {}
        except (OSError, json.JSONDecodeError):
            manifest = {}
    manifest.update(entries)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

def main():
    """Main entry point."""
    dev_mode = '--dev' in sys.argv
    no_minify = '--no-minify' in sys.argv
    force = '--force' in sys.argv

    # Verify all files exist
    missing = verify_files()

    if missing:
        print("Missing CSS files:")
        for f in missing:
            print(f"  - {f}")
        if not dev_mode:
            print("\nBuild aborted. Create missing files first.")
            sys.exit(1)
        return

    if dev_mode:
        print("All CSS files verified!")
        return

    if not force and is_output_fresh():
        print("main.min.css is up-to-date — no source changes detected. (use --force to rebuild)")
        return

    # Build concatenated (and optionally minified) file
    build(do_minify=not no_minify)

if __name__ == '__main__':
    main()
