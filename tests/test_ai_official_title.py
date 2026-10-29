"""AI Fill names each game's official title during every scrape (user,
2026-10-27), and the ROM Tools Official Names run reads the replies the
providers actually send.

Route tests use the throwaway schema conftest points RETRODB_DB_PATH at.
"""
import json

from tests.test_official_names import _game, _row, db  # noqa: F401 — fixture


# ---------------------------------------------------------------------------
# Official Names run: replies that were read as "no answer" before
# ---------------------------------------------------------------------------

def test_parse_reads_object_reply():
    """OpenAI's JSON mode returns an object only, so the answers came
    wrapped and every one was dropped: the run suggested nothing."""
    from scraper.scrape_ai import _parse_official_names
    reply = json.dumps({'games': [{'i': 0, 'official_title': 'Rockman',
                                   'old_title_region': 'USA'}]})
    assert _parse_official_names(reply, 1) == [
        {'official_title': 'Rockman', 'old_title_region': 'US'}]
    other_key = json.dumps({'results': [{'i': 0, 'official_title': 'Rockman'}]})
    assert _parse_official_names(other_key, 1)[0]['official_title'] == 'Rockman'


def test_parse_reads_reply_inside_prose():
    """Gemini's search grounding can put text and citations around the JSON."""
    from scraper.scrape_ai import _parse_official_names
    reply = ('Here are the titles [1]:\n'
             '[{"i": 1, "official_title": "Rockman 2"}]\nSources: [2]')
    assert [a['official_title'] for a in _parse_official_names(reply, 2)] == [None, 'Rockman 2']


def test_prompt_asks_for_an_object():
    from scraper.scrape_ai import _build_official_names_prompt
    prompt = _build_official_names_prompt('NES', [{'title': 'Mega Man', 'rom_file': 'x.nes'}])
    assert '{"games": [' in prompt


# ---------------------------------------------------------------------------
# AI Fill asks for, and applies, the official title
# ---------------------------------------------------------------------------

def test_prompt_asks_official_title_only_when_given():
    from scraper.scrape_ai import _build_prompt
    asked = _build_prompt('Mega Man', 'NES', ['genre'],
                          official_title_for={'rom_file': '/r/Rockman (Japan).nes'})
    assert '"official_title"' in asked and 'Rockman (Japan).nes' in asked
    assert '"official_title"' not in _build_prompt('Mega Man', 'NES', ['genre'])


def test_reply_keeps_official_title():
    from scraper.scrape_ai import _parse_ai_response
    data = _parse_ai_response(json.dumps({'genre': 'Platformer', 'official_title': 'Rockman',
                                          'old_title_region': 'USA'}))
    assert (data['official_title'], data['old_title_region']) == ('Rockman', 'US')
    assert 'official_title' not in _parse_ai_response(json.dumps({'official_title': 'Bad\x07'}))


def test_locked_or_romless_game_not_asked(db):
    from scraper.scrape_ai import _official_title_context
    gid = _game(db, 'Mega Man')
    assert _official_title_context(gid)['rom_file'].endswith('Rockman 2 (Japan).nes')
    assert _official_title_context(_game(db, 'Locked', rom='L.nes', title_locked=1)) is None
    assert _official_title_context(_game(db, 'No ROM', rom_path='')) is None
    assert _official_title_context(_game(db, 'CLZ', rom_path='clz_import/1')) is None


def test_scrape_applies_official_title():
    """The hybrid scrape (manual and bulk) takes the AI's name; the
    replaced one stays as an alternate title."""
    from scraper.metadata_merger import apply_ai_to_metadata
    metadata = {'title': 'Mega Man', 'alternate_titles': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'official_title': 'Rockman', 'old_title_region': 'US'},
                         1, result)
    assert metadata['title'] == 'Rockman'
    assert metadata['alternate_titles'] == [{'title': 'Mega Man', 'region': 'US', 'source': 'ai'}]
    assert 'title (AI official name)' in result['filled_fields']


def test_scrape_same_title_unchanged():
    from scraper.metadata_merger import apply_ai_to_metadata
    metadata = {'title': 'Rockman', 'alternate_titles': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'official_title': 'Rockman'}, 1, result)
    assert metadata == {'title': 'Rockman', 'alternate_titles': None}
    assert result['filled_fields'] == []


def _ai_fill(client, csrf, gid):
    resp = client.post(f'/api/game/{gid}/ai-fill', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


def test_ai_fill_button_updates_title(db, admin_test_client, monkeypatch):
    import scraper.scrape_ai as scrape_ai
    from scraper.scrape_ai import _official_title_context
    gid = _game(db, 'Mega Man')
    monkeypatch.setattr(scrape_ai, 'get_game_details', lambda game_id, *a, **k: (
        {'official_title': 'Rockman', 'old_title_region': 'US'}
        if _official_title_context(game_id) else {'genre': 'Platformer'}))
    client, csrf = admin_test_client()
    body = _ai_fill(client, csrf, gid)
    assert body['game']['title'] == 'Rockman' and 'title' in body['filled_fields']
    row = _row(db, gid)
    assert (row['title'], row['sort_title']) == ('Rockman', 'Rockman')
    assert json.loads(row['alternate_titles']) == [
        {'title': 'Mega Man', 'region': 'US', 'source': 'ai'}]


def test_ai_fill_button_keeps_locked_title(db, admin_test_client, monkeypatch):
    import scraper.scrape_ai as scrape_ai
    gid = _game(db, 'My Name', title_locked=1)
    monkeypatch.setattr(scrape_ai, 'get_game_details',
                        lambda *a, **k: {'official_title': 'Rockman'})
    client, csrf = admin_test_client()
    _ai_fill(client, csrf, gid)
    assert _row(db, gid)['title'] == 'My Name'
