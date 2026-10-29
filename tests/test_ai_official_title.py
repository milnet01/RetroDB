"""AI Fill names each game's official title during every scrape (user,
2026-10-27), and the ROM Tools Official Names run reads the replies the
providers actually send.

Route tests use the throwaway schema conftest points RETRODB_DB_PATH at.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_official_names import _game, _row, db  # noqa: F401 — fixture

ROOT = Path(__file__).resolve().parent.parent


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


@pytest.mark.parametrize('prefix', ['steam_import/', 'xbox_import/', 'psn_import/'])
def test_store_imports_not_asked(db, prefix):
    """Steam, Xbox and PSN imports have no ROM file either: their rom_path
    is a made-up key, so there is no file name to read a region from."""
    from scraper.scrape_ai import _official_title_context
    assert _official_title_context(_game(db, 'Store', rom_path=prefix + '123')) is None


def test_scrape_applies_official_title(db):
    """The hybrid scrape (manual and bulk) takes the AI's name; the
    replaced one stays as an alternate title."""
    from scraper.metadata_merger import apply_ai_to_metadata
    gid = _game(db, 'Mega Man')
    metadata = {'title': 'Mega Man', 'alternate_titles': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'official_title': 'Rockman', 'old_title_region': 'US'},
                         gid, result)
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


def test_ai_fill_button_keeps_title_locked_during_the_call(db, admin_test_client, monkeypatch):
    """The lock is read before the slow AI call; a title locked while the
    AI answers must still be kept, with its sort title and alternates."""
    import scraper.scrape_ai as scrape_ai
    gid = _game(db, 'Mega Man', sort_title='Mega Man')

    def answer(game_id, *a, **k):
        db.conn.execute("UPDATE games SET title = 'My Name', sort_title = 'My Name', "
                        "title_locked = 1 WHERE id = ?", (game_id,))
        db.conn.commit()
        return {'official_title': 'Rockman', 'old_title_region': 'US'}
    monkeypatch.setattr(scrape_ai, 'get_game_details', answer)
    client, csrf = admin_test_client()
    _ai_fill(client, csrf, gid)
    row = _row(db, gid)
    assert (row['title'], row['sort_title'], row['alternate_titles']) == (
        'My Name', 'My Name', None)


# ---------------------------------------------------------------------------
# get_game_details keeps an official title only when it may be applied
# ---------------------------------------------------------------------------

def _stub_provider(monkeypatch, reply):
    import scraper.scrape_ai as scrape_ai
    monkeypatch.setattr(scrape_ai, '_get_active_provider',
                        lambda: {'provider': 'claude', 'api_key': 'k', 'model': 'm'})
    monkeypatch.setattr(scrape_ai, 'rate_limit', lambda **k: None)
    monkeypatch.setattr(scrape_ai, '_call_claude', lambda *a, **k: json.dumps(reply))


def test_rejected_name_not_applied_by_ai_fill(db, monkeypatch):
    """INV-6: a name the user rejected in Official Names is not proposed
    again, so AI Fill and Bulk Scrape must not apply it either."""
    from scraper.scrape_ai import get_game_details
    gid = _game(db, 'Mega Man')
    db.conn.execute("INSERT INTO title_proposals (game_id, old_title, proposed_title, status) "
                    "VALUES (?, 'Mega Man', 'Rockman', 'rejected')", (gid,))
    db.conn.commit()
    _stub_provider(monkeypatch, {'genre': 'Platformer', 'official_title': 'Rockman',
                                 'old_title_region': 'USA'})
    data = get_game_details(gid, 'Mega Man', 'NES', existing_metadata={'genre': ''})
    assert data.get('genre') and 'official_title' not in data
    _stub_provider(monkeypatch, {'official_title': 'Rockman World'})
    assert get_game_details(gid, 'Mega Man', 'NES')['official_title'] == 'Rockman World'


def test_unasked_official_title_dropped(db, monkeypatch):
    """A locked game is not asked for its official name; a reply that sends
    one anyway must not reach the merger."""
    from scraper.scrape_ai import get_game_details
    gid = _game(db, 'My Name', title_locked=1)
    _stub_provider(monkeypatch, {'genre': 'Platformer', 'official_title': 'Rockman'})
    data = get_game_details(gid, 'My Name', 'NES', existing_metadata={'genre': ''})
    assert 'official_title' not in data and 'old_title_region' not in data


def test_scrape_locked_title_changes_nothing(db):
    """A title locked after the AI was asked: the save keeps the title, so
    nothing else of the rename (alternates, history) may land either."""
    from scraper.metadata_merger import apply_ai_to_metadata
    gid = _game(db, 'My Name', title_locked=1)
    metadata = {'title': 'My Name', 'alternate_titles': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'official_title': 'Rockman', 'old_title_region': 'US'},
                         gid, result)
    assert metadata == {'title': 'My Name', 'alternate_titles': None}
    assert result['filled_fields'] == []


# ---------------------------------------------------------------------------
# Live Bulk Scrape cards: each finished game re-renders once
# ---------------------------------------------------------------------------

NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='node not available')
def test_live_cards_refresh_each_game_once():
    """The server reports the last 20 finished ids on every poll. Clearing
    the seen-set when it grew past its cap made the 19 ids still in that
    list look new, so their cards re-rendered again."""
    src = (ROOT / 'static/js/all-games-controller.js').read_text(encoding='utf-8')
    start = src.index('const _liveRefreshed')
    end = src.index('});', src.index("addEventListener('retrodb:job-status'", start)) + 3
    script = (
        "let handler; const document = {addEventListener: (n, f) => { handler = f; }};\n"
        "const counts = {}; function refreshCards(ids) {"
        " ids.forEach(i => { counts[i] = (counts[i] || 0) + 1; }); }\n"
        + src[start:end] + "\n"
        "for (let n = 1; n <= 1200; n++) {"
        " const ids = []; for (let i = Math.max(1, n - 19); i <= n; i++) ids.push(i);"
        " handler({detail: {type: 'bulk-scrape', data: {job_id: 'j', recently_scraped_ids: ids}}}); }\n"
        "console.log(JSON.stringify(Object.keys(counts).filter(k => counts[k] !== 1).length));\n")
    res = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-1500:]
    assert json.loads(res.stdout) == 0
