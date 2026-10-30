"""PASS-59-195 — the once-per-release translation script. Claude is replaced by
a fake; catalogs and changelogs live under tmp_path, and no test reaches the network.
"""
import json
import os
import sys

import pytest
import yaml
from babel.messages.pofile import read_po

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
import translate_release as tr  # noqa: E402

PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgid "Done"
msgstr "Fertig"

msgid "Saved %(n)s games"
msgstr ""

#, fuzzy
#| msgid "Old words"
msgid "New <b>words</b>"
msgstr "Alt"

msgid "%(n)s game"
msgid_plural "%(n)s games"
msgstr[0] ""
msgstr[1] ""
'''

LOCALE_LOG = """# kept comment
- version: 1.0.0
  date: '2026-01-01'
  tags:
  - type: fix
    label: 'Alt'
"""


def _english(*versions):
    return [{'version': v, 'date': '2026-10-30',
             'tags': [{'type': 'fix', 'label': f'Label {v}'}]} for v in versions]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    po_dir = tmp_path / 'translations' / 'de' / 'LC_MESSAGES'
    po_dir.mkdir(parents=True)
    (po_dir / 'messages.po').write_text(PO, encoding='utf-8')
    (tmp_path / 'translations' / 'eo').mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'changelog.yaml').write_text(yaml.safe_dump(_english('2.0.0', '1.0.0')), encoding='utf-8')
    (data / 'changelog.de.yaml').write_text(LOCALE_LOG, encoding='utf-8')
    monkeypatch.setattr(tr, 'TRANSLATIONS', str(tmp_path / 'translations'))
    monkeypatch.setattr(tr, 'DATA', str(data))
    monkeypatch.setattr(tr, 'TERMS_DIR', str(tmp_path / 'terms'))
    monkeypatch.setattr(tr, 'CHUNK', 40)
    return tmp_path


def _echo(system, payload, key):
    """Stands in for Claude: marks each string, so it keeps every placeholder."""
    return {n: ([f'DE {item["plural"]}'] * item['forms'] if isinstance(item, dict) else f'DE {item}')
            for n, item in payload.items()}


def _messages(repo):
    with open(repo / 'translations' / 'de' / 'LC_MESSAGES' / 'messages.po', 'rb') as f:
        return {m.id if isinstance(m.id, str) else m.id[0]: m for m in read_po(f) if m.id}


def test_only_what_is_still_english_is_sent(repo, monkeypatch):
    sent = []
    monkeypatch.setattr(tr, '_ask_claude', lambda s, p, k: sent.extend(p.values()) or _echo(s, p, k))
    tr.translate_catalog('de', 'k', dry_run=False)
    assert 'Done' not in sent and 'Saved %(n)s games' in sent and 'New <b>words</b>' in sent


def test_translations_reach_the_catalog_and_clear_fuzzy(repo, monkeypatch):
    monkeypatch.setattr(tr, '_ask_claude', _echo)
    assert tr.translate_catalog('de', 'k', dry_run=False) == (3, 0)
    msgs = _messages(repo)
    assert msgs['Done'].string == 'Fertig'
    assert msgs['Saved %(n)s games'].string == 'DE Saved %(n)s games'
    assert msgs['%(n)s game'].string == ('DE %(n)s games', 'DE %(n)s games')
    assert msgs['New <b>words</b>'].string == 'DE New <b>words</b>' and not msgs['New <b>words</b>'].fuzzy


@pytest.mark.parametrize('bad', ['Ohne Platzhalter', '%(m)s Spiele', '', None, 5])
def test_a_broken_string_is_asked_again_then_left_out(repo, monkeypatch, bad):
    asked = []

    def fake(system, payload, key):
        asked.append(1)
        reply = _echo(system, payload, key)
        for n, item in payload.items():
            if item == 'Saved %(n)s games':
                reply[n] = bad
        return reply
    monkeypatch.setattr(tr, '_ask_claude', fake)
    assert tr.translate_catalog('de', 'k', dry_run=False) == (3, 1)
    assert len(asked) == tr.ROUNDS
    assert _messages(repo)['Saved %(n)s games'].string == ''


def test_a_lost_html_tag_is_refused():
    assert not tr._good('New <b>words</b>', 'Neue Wörter')
    assert tr._good('New <b>words</b>', 'Neue <b>Wörter</b>')


def test_a_wrong_number_of_plural_forms_is_refused():
    source = ('%(n)s game', '%(n)s games', 3)
    assert not tr._good(source, ['%(n)s a', '%(n)s b'])
    assert tr._good(source, ['%(n)s a', '%(n)s b', '%(n)s c'])


def test_no_answer_from_claude_changes_nothing(repo, monkeypatch):
    monkeypatch.setattr(tr, '_ask_claude', lambda s, p, k: {})
    assert tr.translate_catalog('de', 'k', dry_run=False) == (3, 3)
    assert (repo / 'translations' / 'de' / 'LC_MESSAGES' / 'messages.po').read_text(encoding='utf-8') == PO
    assert tr.translate_changelog('de', 'k', dry_run=False) == (1, 1)
    assert (repo / 'data' / 'changelog.de.yaml').read_text(encoding='utf-8') == LOCALE_LOG


def test_dry_run_counts_and_never_asks(repo, monkeypatch):
    monkeypatch.setattr(tr, '_ask_claude', lambda *a: pytest.fail('asked Claude'))
    assert tr.translate_catalog('de', 'k', dry_run=True) == (3, 0)
    assert tr.translate_changelog('de', 'k', dry_run=True) == (1, 0)


def test_a_new_entry_goes_on_top_and_the_rest_is_untouched(repo, monkeypatch):
    monkeypatch.setattr(tr, '_ask_claude', _echo)
    assert tr.translate_changelog('de', 'k', dry_run=False) == (1, 0)
    text = (repo / 'data' / 'changelog.de.yaml').read_text(encoding='utf-8')
    assert text.startswith('# kept comment\n- version: 2.0.0') and text.endswith(LOCALE_LOG.split('\n', 1)[1])
    entry = yaml.safe_load(text)[0]
    assert entry == {'version': '2.0.0', 'date': '2026-10-30',
                     'tags': [{'type': 'fix', 'label': 'DE Label 2.0.0'}]}


def test_an_entry_that_gained_items_is_replaced_whole(repo, monkeypatch):
    english = _english('1.0.0')
    english[0]['tags'].append({'type': 'feature', 'label': 'More'})
    (repo / 'data' / 'changelog.yaml').write_text(yaml.safe_dump(english), encoding='utf-8')
    monkeypatch.setattr(tr, '_ask_claude', _echo)
    assert tr.translate_changelog('de', 'k', dry_run=False) == (1, 0)
    rows = yaml.safe_load((repo / 'data' / 'changelog.de.yaml').read_text(encoding='utf-8'))
    assert [r['version'] for r in rows] == ['1.0.0'] and len(rows[0]['tags']) == 2


def test_a_locale_with_no_file_gets_only_the_newest_entry(repo, monkeypatch):
    (repo / 'data' / 'changelog.de.yaml').unlink()
    monkeypatch.setattr(tr, '_ask_claude', _echo)
    assert tr.translate_changelog('de', 'k', dry_run=False) == (1, 0)
    rows = yaml.safe_load((repo / 'data' / 'changelog.de.yaml').read_text(encoding='utf-8'))
    assert [r['version'] for r in rows] == ['2.0.0']


def test_the_body_is_translated_too(repo, monkeypatch):
    english = _english('2.0.0')
    english[0]['body'] = '<p>Hello</p>'
    (repo / 'data' / 'changelog.yaml').write_text(yaml.safe_dump(english), encoding='utf-8')
    monkeypatch.setattr(tr, '_ask_claude', _echo)
    tr.translate_changelog('de', 'k', dry_run=False)
    rows = yaml.safe_load((repo / 'data' / 'changelog.de.yaml').read_text(encoding='utf-8'))
    assert rows[0]['body'] == 'DE <p>Hello</p>'


def test_the_word_list_is_filled_from_the_catalog_and_keeps_a_corrected_word(repo, monkeypatch):
    po = repo / 'translations' / 'de' / 'LC_MESSAGES' / 'messages.po'
    po.write_text(PO + '\nmsgid "Library"\nmsgstr "Bibliothek"\n\nmsgid "Game"\nmsgstr "Spiel"\n', encoding='utf-8')
    (repo / 'terms').mkdir()
    (repo / 'terms' / 'de.json').write_text(json.dumps({'Game': 'Game-Titel'}), encoding='utf-8')
    tr.seed_terms('de')
    assert json.loads((repo / 'terms' / 'de.json').read_text(encoding='utf-8')) == {
        'Game': 'Game-Titel', 'Library': 'Bibliothek'}


def test_claude_sees_only_the_words_this_chunk_uses(repo, monkeypatch):
    (repo / 'terms').mkdir()
    (repo / 'terms' / 'de.json').write_text(json.dumps({'Games': 'Spiele', 'Theme': 'Design'}), encoding='utf-8')
    systems = []
    monkeypatch.setattr(tr, '_ask_claude', lambda s, p, k: systems.append(s) or _echo(s, p, k))
    tr.translate_catalog('de', 'k', dry_run=False)
    assert 'Games = Spiele' in systems[0] and 'Design' not in systems[0]
    assert 'German' in systems[0]


def test_the_pseudolocale_is_never_translated(repo):
    assert tr._locales() == ['de']


def test_no_key_stops_before_any_call(repo, monkeypatch, capsys):
    monkeypatch.setattr(tr, '_api_key', lambda: '')
    monkeypatch.setattr(tr, '_ask_claude', lambda *a: pytest.fail('asked Claude'))
    monkeypatch.setattr(sys, 'argv', ['translate_release.py'])
    assert tr.main() == 2
    assert 'No Claude key' in capsys.readouterr().out


def test_the_key_never_appears_in_output(repo, monkeypatch, capsys):
    class Reply:
        status_code = 401
    monkeypatch.setattr(tr.requests, 'post', lambda *a, **k: Reply())
    assert tr._ask_claude('s', {'0': 'x'}, 'secret-key') == {}
    assert 'secret-key' not in capsys.readouterr().out


def test_claudes_reply_is_read_past_thinking_and_code_fences(monkeypatch):
    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {'usage': {'input_tokens': 7, 'output_tokens': 3},
                    'content': [{'type': 'thinking', 'thinking': '{"0": "no"}'},
                                {'type': 'text', 'text': '```json\n{"0": "Fertig"}\n```'}]}
    sent = {}
    monkeypatch.setattr(tr.requests, 'post', lambda url, headers, json, timeout: sent.update(json) or Reply())
    monkeypatch.setattr(tr, 'tokens', tr.Counter())
    assert tr._ask_claude('s', {'0': 'Done'}, 'k') == {'0': 'Fertig'}
    assert sent['model'] == tr.MODEL and tr.tokens == {'in': 7, 'out': 3}


def test_an_entity_may_become_a_word():
    assert tr._good('Developers &amp; Publishers', 'Deweloperzy i wydawcy')


def test_a_real_catalogue_has_a_word_list_for_every_locale():
    assert sorted(f[:-5] for f in os.listdir(tr.TERMS_DIR)) == tr._locales()
