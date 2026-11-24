"""PASS-59-255: page styles use the theme's colour, never the Cyberpunk cyan by value."""
import glob
import re

from tests._util import read_source

# rgba(76, 201, 240, …) or #4cc9f0, except as a var() fallback or inside a
# data: URL (an SVG arrow cannot read a CSS variable).
FIXED = re.compile(r'rgba\(\s*(76\s*,\s*201\s*,\s*240|20\s*,\s*26\s*,\s*35)'
                   r'|(?<!%23)(?<!--primary-cyan, )#4cc9f0', re.I)
# The swatches show one theme's or one tag's own colour, whatever theme is on.
SWATCH = re.compile(r'class="(theme-swatch|tag-color-swatch|tag-pill)')


def _hits(text):
    return [line.strip() for line in text.splitlines() if FIXED.search(line) and not SWATCH.search(line)]


def test_stylesheets_name_no_fixed_cyan():
    skip = {'static/css/core/variables.css', 'static/css/core/themes.css'}
    bad = {f: _hits(open(f).read()) for f in glob.glob('static/css/*/*.css') if f not in skip}
    assert {f: h for f, h in bad.items() if h} == {}


def test_page_styles_name_no_fixed_cyan():
    bad = {}
    for f in glob.glob('templates/**/*.html', recursive=True):
        html = open(f).read()
        styles = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)
        styles += re.findall(r'<[^>]*style="[^"]*"[^>]*>', html)
        hits = [h for s in styles for h in _hits(s)]
        if hits:
            bad[f] = hits
    assert bad == {}


def test_the_analytics_charts_take_the_theme_colours():
    # Chart.js cannot read CSS variables; the page reads them as it builds the charts.
    html = read_source('templates/analytics.html')
    assert "themeColor('--primary-cyan'" in html
    assert _hits(html) == []


def test_wishlist_badges_mix_a_valid_colour():
    # `${color}20` on a var() colour is not CSS, so the badge lost its background.
    html = read_source('templates/wishlist.html')
    assert '${color}20' not in html and '${color}40' not in html


def test_the_cyan_background_tokens_follow_the_theme():
    css = read_source('static/css/core/variables.css')
    for token in ('--cyan-bg', '--cyan-bg-light', '--cyan-bg-strong'):
        value = re.search(rf'{token}:\s*([^;]+);', css).group(1)
        assert 'var(--primary-cyan)' in value, token
