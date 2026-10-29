"""showModal / showConfirm show their message as text unless the caller
passes {allowHtml: true} (Pass 40.13), so markup in a plain message showed
as raw tags: "...results. <br><br>No media is downloaded" (user,
2026-10-27). Pins that no caller sends markup without opting in, and that
the game page binds its search-result Apply handler once."""
import glob
import re

_TAG = re.compile(r'<\s*/?\s*(?:br|b|strong|em|i|ul|ol|li|code|p|small|span|div|hr|a)\b'
                  r'|&(?:[a-z]+|#\d+);')


def _calls(text):
    """Each showModal/showConfirm/alert call: (line, message part, full call)."""
    for m in re.finditer(r'\b(?:showConfirm|showModal|alert)\s*\(', text):
        i, depth = m.end(), 1
        while depth and i < len(text):
            depth += {'(': 1, ')': -1}.get(text[i], 0)
            i += 1
        call = text[m.start():i]
        message = re.split(r'function\s*\(|\)\s*=>|async\s*\(', call)[0]
        yield text.count('\n', 0, m.start()) + 1, message, call


def test_no_markup_in_plain_messages():
    files = [f for f in glob.glob('templates/**/*.html', recursive=True)
             + glob.glob('static/js/*.js')
             if 'bundle' not in f and '/help.' not in f and not f.endswith('base.html')]
    found = [f'{f}:{line}' for f in files for line, message, call in _calls(open(f).read())
             if 'allowHtml' not in call and _TAG.search(message)]
    assert not found, found


def test_apply_handler_bound_once():
    """A listener added inside performSearch fired once per search made, so
    one Apply click started several applies and the progress gauge went
    back and forth between them."""
    page = open('templates/game_detail.html').read()
    search = page[page.index('async function performSearch'):page.index('function applyMetadata(')]
    assert "addEventListener('click'" not in search
    assert "resultsDiv.addEventListener('click'" in page


def test_apply_progress_runs_one_at_a_time():
    js = open('static/js/apply-progress.js').read()
    assert 'if (running) return;' in js
