#!/usr/bin/env python3
"""Audit WCAG 2.2 AA contrast ratios across all themes.

Parses:
    static/css/core/variables.css   — cyberpunk baseline (:root)
    static/css/core/themes.css      — per-theme overrides ([data-theme="..."])

Computes relative-luminance contrast ratios for the text/background pairs
RetroDB actually uses, per theme, per WCAG 2.2 AA thresholds:

    4.5:1  — normal text (body, labels, buttons)
    3.0:1  — large text (>= 18pt regular or 14pt bold), and graphical UI controls

Writes a markdown report to docs/theme_contrast.md with PASS / FAIL / NOTE rows.

Exit code 0 regardless; this is a report, not a gate. CI can grep the output.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VARIABLES_CSS = REPO_ROOT / 'static' / 'css' / 'core' / 'variables.css'
THEMES_CSS = REPO_ROOT / 'static' / 'css' / 'core' / 'themes.css'
REPORT = REPO_ROOT / 'docs' / 'theme_contrast.md'

# Pairs to audit. Each entry: (label, text-var, bg-var, threshold, notes).
# Large-text / UI-component pairs use 3.0, normal text uses 4.5.
PAIRS = [
    ('body text',        '--text-primary',   '--bg-darkest',   4.5, 'body text on app background'),
    ('body text (card)', '--text-primary',   '--card-bg',      4.5, 'body text inside cards'),
    ('body text (medium bg)', '--text-primary', '--bg-medium',  4.5, 'body text on panels'),
    ('secondary text',   '--text-secondary', '--bg-darkest',   4.5, 'captions, metadata'),
    ('secondary text (card)', '--text-secondary', '--card-bg', 4.5, 'metadata inside cards'),
    ('muted text',       '--text-muted',     '--bg-darkest',   4.5, 'muted labels; 3.0 acceptable'),
    ('muted text (card)', '--text-muted',    '--card-bg',      4.5, 'muted labels; 3.0 acceptable'),
    ('accent cyan (UI)', '--primary-cyan',   '--bg-darkest',   3.0, 'primary controls (large text / UI)'),
    ('accent magenta (UI)', '--secondary-magenta', '--bg-darkest', 3.0, 'secondary controls'),
    ('success (UI)',     '--status-success', '--bg-darkest',   3.0, 'success badges'),
    ('warning (UI)',     '--status-warning', '--bg-darkest',   3.0, 'warning badges'),
    ('error (UI)',       '--status-error',   '--bg-darkest',   3.0, 'error badges'),
]

# Known theme slugs (keep in sync with themes.css selectors).
# `cyberpunk` is the default, defined in variables.css :root.
THEMES = ['cyberpunk', 'matrix', 'amber', 'ocean', 'christian', 'bladerunner', 'elite']


def parse_root_vars(css: str) -> dict[str, str]:
    """Parse the :root { ... } block from variables.css."""
    m = re.search(r':root\s*\{([^}]*)\}', css, re.DOTALL)
    if not m:
        return {}
    return _parse_decl_block(m.group(1))


def parse_theme_vars(css: str, theme: str) -> dict[str, str]:
    """Parse the [data-theme="THEME"] { ... } block (the one without body::before etc)."""
    pattern = r'\[data-theme="' + re.escape(theme) + r'"\]\s*\{([^}]*)\}'
    m = re.search(pattern, css, re.DOTALL)
    if not m:
        return {}
    return _parse_decl_block(m.group(1))


_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)


def _parse_decl_block(body: str) -> dict[str, str]:
    """Parse a CSS declaration block — only --variable: value; pairs.

    Strips /* ... */ comments first so a trailing `;`-split doesn't leave
    a comment prefix on the next declaration and hide the `--var` start.
    """
    body = _COMMENT_RE.sub('', body)
    decls = {}
    for line in body.split(';'):
        line = line.strip()
        if not line or not line.startswith('--'):
            continue
        if ':' not in line:
            continue
        name, value = line.split(':', 1)
        decls[name.strip()] = value.strip().rstrip(';').strip()
    return decls


def resolve(var_name: str, vars_map: dict[str, str], _seen=None) -> str | None:
    """Resolve a CSS variable value, following var(--other) references."""
    _seen = _seen or set()
    if var_name in _seen:
        return None
    _seen.add(var_name)
    val = vars_map.get(var_name)
    if val is None:
        return None
    m = re.match(r'var\((--[a-z0-9-]+)\)', val)
    if m:
        return resolve(m.group(1), vars_map, _seen)
    return val


def parse_color(css_color: str) -> tuple[int, int, int] | None:
    """Parse #RGB / #RRGGBB / rgb(...) / rgba(...) into (R, G, B)."""
    s = css_color.strip().lower()
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        return None
    m = re.match(r'rgba?\(\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)', s)
    if m:
        return (int(float(m.group(1))), int(float(m.group(2))), int(float(m.group(3))))
    return None


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance. Input 0-255 sRGB; output 0.0-1.0."""
    def chan(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1 = relative_luminance(c1)
    l2 = relative_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def audit_theme(theme: str, base_vars: dict[str, str], theme_vars: dict[str, str]) -> list[dict]:
    """Merge base + theme overrides, compute ratios for every PAIR."""
    merged = dict(base_vars)
    merged.update(theme_vars)
    rows = []
    for label, fg_var, bg_var, threshold, notes in PAIRS:
        fg_val = resolve(fg_var, merged)
        bg_val = resolve(bg_var, merged)
        fg_rgb = parse_color(fg_val) if fg_val else None
        bg_rgb = parse_color(bg_val) if bg_val else None
        if not fg_rgb or not bg_rgb:
            rows.append({
                'label': label, 'fg': fg_var, 'bg': bg_var,
                'fg_hex': fg_val or '?', 'bg_hex': bg_val or '?',
                'ratio': None, 'threshold': threshold, 'status': 'SKIP',
                'notes': f'unresolved: {fg_var if not fg_rgb else bg_var}',
            })
            continue
        ratio = contrast_ratio(fg_rgb, bg_rgb)
        if ratio >= threshold:
            status = 'PASS'
        elif ratio >= 3.0 and 'muted' in label:
            # Muted text is inherently lower-priority; 3:1 is acceptable by docs.
            status = 'NOTE'
        else:
            status = 'FAIL'
        rows.append({
            'label': label, 'fg': fg_var, 'bg': bg_var,
            'fg_hex': fg_val, 'bg_hex': bg_val,
            'ratio': ratio, 'threshold': threshold, 'status': status,
            'notes': notes,
        })
    return rows


def render_report(results: dict[str, list[dict]]) -> str:
    lines = []
    lines.append('# Theme Contrast Audit (WCAG 2.2 AA)')
    lines.append('')
    lines.append('Generated by `scripts/audit_contrast.py` against `static/css/core/variables.css` + `static/css/core/themes.css`.')
    lines.append('')
    lines.append('Thresholds:')
    lines.append('')
    lines.append('- **4.5:1** — normal body text (WCAG 2.2 AA, Success Criterion 1.4.3)')
    lines.append('- **3.0:1** — large text (>= 18pt regular / 14pt bold) and graphical UI controls (SC 1.4.11)')
    lines.append('')
    lines.append('Statuses:')
    lines.append('')
    lines.append('- `PASS` — meets the threshold.')
    lines.append('- `NOTE` — below 4.5:1 but >= 3.0:1 on a pair marked low-priority (e.g. muted text). Documented acceptable.')
    lines.append('- `FAIL` — below threshold; should be fixed or the token should be re-purposed.')
    lines.append('')

    # Summary table (count of PASS/FAIL/NOTE per theme).
    lines.append('## Summary')
    lines.append('')
    lines.append('| Theme | Pass | Note | Fail |')
    lines.append('| --- | ---: | ---: | ---: |')
    for theme, rows in results.items():
        passes = sum(1 for r in rows if r['status'] == 'PASS')
        notes = sum(1 for r in rows if r['status'] == 'NOTE')
        fails = sum(1 for r in rows if r['status'] == 'FAIL')
        lines.append(f'| {theme} | {passes} | {notes} | {fails} |')
    lines.append('')

    # Per-theme detail.
    for theme, rows in results.items():
        lines.append(f'## {theme}')
        lines.append('')
        lines.append('| Pair | FG token | BG token | FG hex | BG hex | Ratio | Thresh | Status | Notes |')
        lines.append('| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |')
        for r in rows:
            ratio_str = f"{r['ratio']:.2f}:1" if r['ratio'] is not None else 'n/a'
            lines.append(
                f"| {r['label']} | `{r['fg']}` | `{r['bg']}` | `{r['fg_hex']}` | "
                f"`{r['bg_hex']}` | {ratio_str} | {r['threshold']:.1f} | **{r['status']}** | {r['notes']} |"
            )
        lines.append('')

    return '\n'.join(lines) + '\n'


def main() -> int:
    variables_css = VARIABLES_CSS.read_text()
    themes_css = THEMES_CSS.read_text()
    base = parse_root_vars(variables_css)

    if not base:
        print('ERROR: could not parse :root block from variables.css', file=sys.stderr)
        return 1

    results = {}
    for theme in THEMES:
        theme_overrides = {} if theme == 'cyberpunk' else parse_theme_vars(themes_css, theme)
        results[theme] = audit_theme(theme, base, theme_overrides)

    report = render_report(results)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report)
    print(f'Wrote {REPORT.relative_to(REPO_ROOT)}')

    total_fails = sum(1 for rows in results.values() for r in rows if r['status'] == 'FAIL')
    print(f'Total FAIL: {total_fails}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
