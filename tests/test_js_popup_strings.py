"""PASS-52-1: pop-up text built in JavaScript must be translatable.

Templates translate on the server: ``{{ _('Saved')|tojson }}``, and
``t({{ _('{count} saved')|tojson }}, {count: n})`` where a value is filled
in. Files in static/js use ``t('Saved')``, which build_js.py collects.
A ``t('...')`` written inside a template is never collected, so it always
shows English. See docs/specs/i18n.md §6.
"""
import re
from pathlib import Path

import pytest

from tests._util import REPO_ROOT as _ROOT

REPO_ROOT = Path(_ROOT)
TEMPLATES = REPO_ROOT / 'templates'
JS_DIR = REPO_ROOT / 'static' / 'js'

POPUPS = (r'(?:showNotification|showConfirm|showConfirmModal|showModal|showInfoModal'
          r'|showBatchProgressModal|showToast|alert|confirm)')
# A pop-up whose first argument is quoted text with a letter in it. An
# emoji-only title such as showModal('⚠️', ...) has nothing to translate.
_BARE_POPUP = re.compile(
    r"(?<![\w.$])" + POPUPS + r"""\(\s*(['"`])((?:\\.|(?!\1).)*?[A-Za-z](?:\\.|(?!\1).)*?)\1""",
    re.DOTALL)
_T_LITERAL = re.compile(r"""(?<![\w.$])t\(\s*['"]""")
_SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_LINE_COMMENT = re.compile(r'(?<![:\'"])//[^\n]*')


# A line marked `i18n-skip: <reason>` is left out, e.g. the PSN bookmarklet,
# which runs on Sony's page where RetroDB's translations do not exist.
_SKIPPED_LINE = re.compile(r'^.*i18n-skip:.*$', re.MULTILINE)


def _strip_comments(js):
    js = _SKIPPED_LINE.sub('', js)
    return _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', js))


def _template_scripts():
    for path in sorted(TEMPLATES.rglob('*.html')):
        html = path.read_text(encoding='utf-8')
        for m in _SCRIPT.finditer(html):
            yield path, _strip_comments(m.group(1))


def _js_sources():
    for path in sorted(JS_DIR.glob('*.js')):
        if not path.name.endswith('.bundle.js'):
            yield path, _strip_comments(path.read_text(encoding='utf-8'))


def _rel(path):
    return str(path.relative_to(REPO_ROOT))


# Code inside a template literal's ${...} is not text: `${_ti('error')} ${t('Error')}`.
_INTERPOLATION = re.compile(r'\$\{[^}]*\}')


def _is_text(m):
    body = m.group(2)
    if m.group(1) == '`':
        body = _INTERPOLATION.sub('', body)
    return bool(re.search('[A-Za-z]', body))


def _bare_popups(sources):
    found = []
    for path, js in sources:
        for m in _BARE_POPUP.finditer(js):
            if _is_text(m):
                found.append(f'{_rel(path)}: {m.group(0)[:90]}')
    return found


def test_template_popups_are_translated():
    found = _bare_popups(_template_scripts())
    assert not found, 'English pop-up text in a template:\n' + '\n'.join(found)


def test_js_file_popups_are_translated():
    found = _bare_popups(_js_sources())
    assert not found, 'English pop-up text in static/js:\n' + '\n'.join(found)


def test_templates_do_not_call_t_with_plain_text():
    """build_js.py reads static/js only, so t('...') in a template stays English."""
    found = [_rel(path) for path, js in _template_scripts() if _T_LITERAL.search(js)]
    assert not found, ("t('...') in a template script; use {{ _('...')|tojson }}: "
                       + ', '.join(sorted(set(found))))


@pytest.mark.parametrize('js, bare', [
    ("showNotification('Saved', 'success');", True),
    ("showNotification(`Added ${n} games`, 'info');", True),
    ("showModal('⚠️', msg);", False),
    ("showNotification(t('Saved'), 'success');", False),
    ("showNotification({{ _('Saved')|tojson }}, 'success');", False),
    ("RetroDB.confirm(x)", False),
    ("showInfoModal('Error', msg);", True),
    ("showModal(`${_ti('error')} ${t('Error')}`, msg);", False),
    ("showModal(`${icon} Failed`, msg);", True),
    ("alert('Not found'); // i18n-skip: runs on another site", False),
])
def test_bare_popup_matcher(js, bare):
    m = _BARE_POPUP.search(_strip_comments(js))
    assert bool(m and _is_text(m)) is bare
