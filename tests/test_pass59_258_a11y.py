"""PASS-59-258: the running-games popover and the library cards work with a
screen reader and a keyboard. Walked in headless Chrome on 2026-11-06."""
import re

from tests._util import read_source


def test_the_indicator_announces_changes_through_a_status_not_on_every_refresh():
    html = read_source('templates/base.html')
    button = re.search(r'<button type="button" id="launch-indicator"[^>]*>', html).group(0)
    assert 'aria-live' not in button
    assert 'aria-haspopup="dialog"' in button and 'aria-controls="launch-popover"' in button
    assert '<span id="launch-status" class="visually-hidden" role="status"></span>' in html
    js = read_source('static/js/launch-indicator.js')
    assert "shownCount !== null && n !== shownCount" in js


def test_the_popover_is_a_named_dialog_whose_buttons_name_the_game():
    js = read_source('static/js/launch-indicator.js')
    assert "popover.setAttribute('role', 'dialog')" in js
    assert "t('Kill {game}', {game: name})" in js
    assert "t('Next disk: {game}', {game: name})" in js
    assert "popover.querySelector('button').focus()" in js


def test_a_library_card_opens_from_a_button_in_its_title():
    js = read_source('static/js/all-games-controller.js')
    assert js.count('<h3 class="game-card-title"><button type="button" class="game-card-open">') == 2
    assert js.count("aria-label=\"${esc(t('Filter by {field}: {value}'") == 4
