"""PASS-59-245: keyboard focus is easy to see, and controls work from the keyboard."""
import glob
import re

from tests._util import read_source


def _rules(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return re.findall(r'([^{}]+)\{([^{}]*)\}', css)


def test_one_focus_ring_in_the_themes_colour_that_nothing_can_hide():
    css = read_source('static/css/core/reset.css')
    body = dict((sel.strip(), b) for sel, b in _rules(css)).get(':focus-visible', '')
    assert 'var(--primary-cyan-light) !important' in body
    assert re.search(r'outline:\s*3px', body)


def test_no_focus_rule_names_a_fixed_cyan():
    fixed = re.compile(r'rgba\(76,\s*201,\s*240|#4cc9f0', re.I)
    bad = [f"{f}: {sel.strip()}" for f in glob.glob('static/css/*/*.css')
           for sel, body in _rules(open(f).read()) if 'focus' in sel and fixed.search(body)]
    assert bad == []


def test_card_filter_links_are_buttons():
    js = read_source('static/js/all-games-controller.js')
    assert '<span class="meta-value meta-clickable"' not in js
    assert js.count('<button type="button" class="meta-value meta-clickable"') == 4


def test_the_running_games_indicator_is_a_button_that_says_when_it_is_open():
    html = read_source('templates/base.html')
    assert re.search(r'<button type="button" id="launch-indicator"[^>]*aria-expanded="false"', html)
    js = read_source('static/js/launch-indicator.js')
    assert "e.key === 'Escape'" in js and "aria-expanded', 'true'" in js


def test_tag_colours_have_names_and_say_which_is_chosen():
    html = read_source('templates/tags.html')
    swatches = re.findall(r'<button type="button" class="tag-color-swatch[^>]*>', html)
    assert swatches and all('aria-label=' in s and 'aria-pressed=' in s for s in swatches)


def test_trophy_pictures_are_named_in_full():
    found = [f for f in glob.glob('templates/**/*.html', recursive=True)
             if re.search(r'alt="[PGSB]"', open(f).read())]
    assert found == []


def test_the_play_screen_keeps_tab_on_itself():
    js = read_source('static/js/game-launch.js')
    assert "e.key === 'Tab'" in js
