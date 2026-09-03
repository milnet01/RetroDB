"""Regression pins for Pass 59.19-59.29 — the scraper + ratings group.

Each test names the finding it locks. The group's theme is that a wrong or
lost value in one field propagates: a mis-parsed ESRB code seeds all nine
rating boards, and one explicit JSON null used to discard a whole record.
"""

import os
import re

import pytest


# --------------------------------------------------------------------------
# 59.19 — TheGamesDB ESRB parsing mis-assigned four of six real strings
# --------------------------------------------------------------------------

# The exact strings TGDB sends, and the code each must produce. Substring
# matching returned E for TEEN/MATURE/PENDING (all contain an 'E') and T for
# ADULTS, so four of these six were wrong.
TGDB_ESRB_STRINGS = [
    ('E - Everyone', 'E'),
    ('E10+ - Everyone 10+', 'E10+'),
    ('T - Teen', 'T'),
    ('M - Mature 17+', 'M'),
    ('AO - Adults Only 18+', 'AO'),
    ('RP - Rating Pending', 'RP'),
]


@pytest.mark.parametrize('raw,expected', TGDB_ESRB_STRINGS)
def test_parse_esrb_code_uses_whole_tokens(raw, expected):
    from services.game_utils import parse_esrb_code
    assert parse_esrb_code(raw) == expected


@pytest.mark.parametrize('raw', ['PEGI 12', 'USK 16', 'Not Rated', '', None])
def test_parse_esrb_code_rejects_non_esrb(raw):
    """A non-ESRB string must not be stored as an ESRB rating — it would seed
    the other eight boards through cross_map_ratings."""
    from services.game_utils import parse_esrb_code
    assert parse_esrb_code(raw) == ''


def test_tgdb_rating_parse_has_one_home():
    """Both TGDB paths must call the shared parser, so they cannot diverge
    again — the hybrid copy had been fixed and the single-source one had not."""
    from scraper import scrape_thegamesdb, metadata_merger
    for mod in (scrape_thegamesdb, metadata_merger):
        src = open(mod.__file__).read()
        assert 'parse_esrb_code' in src, mod.__name__
        assert "for esrb in ['E10+'" not in src, mod.__name__


# --------------------------------------------------------------------------
# 59.20 — cross_map_ratings read the dict it was filling
# --------------------------------------------------------------------------

def test_cross_map_does_not_read_its_own_output():
    """A slot filled earlier in the pass must not become a source for a later
    one: CERO 'D' derived GRAC '15' / ClassInd '14', both a tier low."""
    from services.game_metadata_service import cross_map_ratings
    result = cross_map_ratings({'cero': 'D'})
    assert result['grac'] == '18'
    assert result['classind'] == '16'


def test_cross_map_direct_mapping_from_classind():
    from services.game_metadata_service import cross_map_ratings
    assert cross_map_ratings({'classind': '16'})['cero'] == 'D'


def test_cross_map_leaves_given_ratings_alone():
    from services.game_metadata_service import cross_map_ratings
    given = {'esrb': 'M', 'pegi': 'PEGI 18'}
    result = cross_map_ratings(given)
    assert result['esrb'] == 'M'
    assert result['pegi'] == 'PEGI 18'


# --------------------------------------------------------------------------
# 59.21 — a single ScreenScraper result bypassed the 80-point score floor
# --------------------------------------------------------------------------

def test_screenscraper_single_result_is_scored():
    """`_pick_best_fallback` must be called unconditionally; the length test
    accepted a lone result with no score at all (scrapers.md §6)."""
    src = open('scraper/hybrid_scraper.py').read()
    assert 'if len(ss_results) > 1 else ss_results[0]' not in src
    assert '_pick_best_fallback(ss_results, game_title)' in src


def test_pick_best_fallback_rejects_a_lone_low_scorer():
    from scraper.hybrid_scraper import _pick_best_fallback
    assert _pick_best_fallback([{'name': 'Something Entirely Else'}],
                               'Alan Wake Remastered') is None


def test_pick_best_fallback_accepts_a_lone_good_match():
    from scraper.hybrid_scraper import _pick_best_fallback
    assert _pick_best_fallback([{'name': 'Alan Wake Remastered'}],
                               'Alan Wake Remastered') is not None


# --------------------------------------------------------------------------
# 59.22 — Full Re-scrape blanked curated region / save_type
# --------------------------------------------------------------------------

def test_force_rescrape_seeds_derived_fields_from_the_row():
    """region and save_type are DERIVED, not source-supplied, so force mode
    must not let a default ('USA') and a folder guess overwrite curated
    values through COALESCE."""
    src = open('scraper/hybrid_scraper.py').read()
    block = src[src.index('if force_overwrite:'):]
    assert "metadata['region'] = game.get('region')" in block
    assert "metadata['save_type'] = game.get('save_type')" in block


# --------------------------------------------------------------------------
# 59.23 — download_image committed a filename whose bytes may be broken
# --------------------------------------------------------------------------

def test_download_image_deletes_and_fails_on_finalize_error(tmp_path, monkeypatch):
    """scrapers.md §9: when finalize raises, delete the file and return False
    so the caller does NOT set metadata[field]."""
    from scraper import base_scraper
    import services.image_utils as image_utils

    dest_dir = tmp_path / 'boxart'
    dest_dir.mkdir()
    dest = dest_dir / 'x.webp'

    class _Resp:
        status_code = 200
        headers = {'Content-Type': 'image/webp'}
        url = 'https://example.com/x.webp'

        def iter_content(self, chunk_size=8192):
            yield b'not-an-image'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(base_scraper, 'validate_and_pin_url',
                        lambda *a, **kw: ('https://example.com/x.webp', None),
                        raising=False)
    monkeypatch.setattr(base_scraper._http_session, 'get',
                        lambda *a, **kw: _Resp())

    def _boom(*a, **kw):
        raise ValueError('cannot decode')

    monkeypatch.setattr(image_utils, 'finalize_downloaded_image', _boom)

    result = base_scraper.download_image('https://example.com/x.webp', str(dest))
    assert result is False, 'a broken image must not report success'
    assert not os.path.exists(str(dest)), 'the broken file must be deleted'


def test_download_image_no_longer_swallows_finalize_failure():
    src = open('scraper/base_scraper.py').read()
    assert "pass  # Non-critical — don't fail the download" not in src


# --------------------------------------------------------------------------
# 59.24 — FIELD_SOURCES had zero readers while the spec called it canonical
# --------------------------------------------------------------------------

def test_field_sources_is_gone_from_code_and_spec():
    from scraper import hybrid_scraper
    assert not hasattr(hybrid_scraper, 'FIELD_SOURCES')
    assert 'FIELD_SOURCES' not in open('docs/specs/scrapers.md').read()


def test_spec_states_the_priority_the_code_uses():
    spec = open('docs/specs/scrapers.md').read()
    assert "fallback_settings['priority']" in spec


# --------------------------------------------------------------------------
# 59.25 — two ScreenScraper zombies, one returning a credential-bearing URL
# --------------------------------------------------------------------------

def test_screenscraper_zombies_are_deleted():
    from scraper import scrape_screenscraper
    assert not hasattr(scrape_screenscraper, 'fetch_system_media')
    assert not hasattr(scrape_screenscraper, 'download_media')


def test_no_screenscraper_response_url_is_returned():
    """fetch_system_media returned response.url, which carries sspassword=
    and devpassword= — handing a credential to whatever wired it up."""
    src = open('scraper/scrape_screenscraper.py').read()
    assert 'return response.url' not in src


# --------------------------------------------------------------------------
# 59.26 — Xbox bypassed the sanctioned HTTP layer
# --------------------------------------------------------------------------

def test_xbox_uses_the_sanctioned_http_layer():
    """scrapers.md §10/§14: every API call goes through http_get/http_post,
    which is what supplies the shared session, 429/Retry-After backoff and
    the response-size cap."""
    src = open('scraper/scrape_xbox.py').read()
    code = '\n'.join(l for l in src.split('\n') if not l.lstrip().startswith('#'))
    assert not re.search(r'\brequests\.(get|post)\s*\(', code)
    assert 'from scraper.base_scraper import http_get, http_post' in src


def test_xbox_title_history_caps_the_paginated_body():
    src = open('scraper/scrape_xbox.py').read()
    body = src[src.index('def get_title_history'):src.index('def get_achievements')]
    assert 'max_bytes=' in body


# --------------------------------------------------------------------------
# 59.27 — IGDB lost an entire apply on any unexpanded reference
# --------------------------------------------------------------------------

def test_igdb_unexpanded_references_do_not_abort_the_apply():
    """An unexpanded IGDB reference arrives as a bare int. Each of these
    shapes used to raise, and the outer except discarded every field."""
    src = open('scraper/scrape_igdb.py').read()
    assert "g['name'] for g in genres)" not in src
    assert "g['name'] for g in igdb_data.get('game_modes', []))" not in src
    assert "m.get('offlinemax', 0)" not in src
    assert "'cover' in igdb_data and 'url' in igdb_data['cover']" not in src


@pytest.mark.parametrize('bad_field,payload', [
    ('genres', {'genres': [17, {'name': 'Shooter'}]}),
    ('game_modes', {'game_modes': [3, {'name': 'Single player'}]}),
    # `.get('offlinemax', 0)` returns None — not the default — on an explicit
    # JSON null, and max() then raises comparing None with int.
    ('multiplayer_modes', {'multiplayer_modes': [{'offlinemax': None}, 9]}),
    ('cover', {'cover': 4242}),
])
def test_igdb_apply_survives_an_unexpanded_reference(bad_field, payload, monkeypatch):
    """One unexpanded reference used to raise, and the outer except swallowed
    it and returned False — discarding the ENTIRE IGDB apply, not one field."""
    from scraper import scrape_igdb
    from tests.test_scrape_fill_only import _make_conn_with_existing_row

    conn = _make_conn_with_existing_row(id=1, title='Existing')
    monkeypatch.setattr(scrape_igdb, 'get_scraper_conn', lambda: conn)
    monkeypatch.setattr(scrape_igdb, 'download_image', lambda *a, **kw: None)

    igdb_data = {'name': 'Test Game', 'summary': 'A summary.'}
    igdb_data.update(payload)

    assert scrape_igdb.apply_metadata_to_game(1, igdb_data) is True, \
        f'a malformed {bad_field} discarded the whole apply'
    row = conn.execute("SELECT description FROM games WHERE id=1").fetchone()
    assert row['description'] == 'A summary.', 'unrelated fields must still be written'


# --------------------------------------------------------------------------
# 59.28 — ScreenScraper lost a whole record on an explicit null
# --------------------------------------------------------------------------

def test_screenscraper_null_field_keeps_the_record():
    """`jeu.get("developpeur", {})` does not fire its default when the key is
    present with JSON null, so this was None.get -> AttributeError, aborting
    parse_game_data and losing the entire record."""
    from scraper import scrape_screenscraper
    jeu = {
        'noms': [{'region': 'us', 'text': 'Test Game'}],
        'developpeur': None,
        'editeur': None,
        'joueurs': None,
        'note': None,
        'dates': None,
        'genres': [],
        'classifications': [{'type': None, 'text': None}],
        'medias': [],
    }
    result = scrape_screenscraper.parse_game_data(jeu)
    assert result is not None
    assert result.get('developer') in ('', None)


def test_screenscraper_has_no_remaining_null_unsafe_defaults():
    src = open('scraper/scrape_screenscraper.py').read()
    assert not re.search(r'\.get\([^)]*,\s*\{\}\)\s*\.', src)
    assert not re.search(r'\.get\([^)]*,\s*""\)\.(lower|upper)\(\)', src)


# --------------------------------------------------------------------------
# 59.29 — three diverged copies of "derive modes from player count"
# --------------------------------------------------------------------------

CANONICAL_MODES = {
    'Single-Player', 'Local Multiplayer', 'Online Multiplayer',
    'Asynchronous Multiplayer', 'Local Co-op', 'Online Co-op', 'Co-op',
    'Split-Screen', 'Versus', 'MMO', 'LAN-System Link', 'Cross-Platform Play',
}


@pytest.mark.parametrize('players,expected', [
    (None, ''),
    ('', ''),
    (1, 'Single-Player'),
    (2, 'Single-Player, Local Multiplayer'),
    ('1-4', 'Single-Player, Local Multiplayer'),
    ('4+', 'Single-Player, Local Multiplayer'),
])
def test_modes_from_player_count(players, expected):
    from services.normalization import modes_from_player_count
    assert modes_from_player_count(players) == expected


def test_derived_modes_are_all_canonical():
    """A non-canonical token cannot be translated by display_field_value()
    and the modes filter chip cannot match it."""
    from services.normalization import modes_from_player_count
    for players in (1, 2, 8, '1-4'):
        for token in modes_from_player_count(players).split(', '):
            assert token in CANONICAL_MODES, token


def test_esde_delegates_and_keeps_its_contract():
    from scraper.scrape_esde import derive_game_modes
    assert derive_game_modes(None) == 'Single-Player'
    assert derive_game_modes('1-4') == 'Single-Player, Local Multiplayer'
    assert derive_game_modes('4+') == 'Single-Player, Local Multiplayer'


def test_no_lowercase_single_player_is_emitted():
    """TGDB wrote 'Single-player' (lowercase p), which matches no canonical
    label."""
    for path in ('scraper/scrape_thegamesdb.py', 'scraper/scrape_esde.py',
                 'scraper/metadata_merger.py'):
        assert 'Single-player' not in open(path).read(), path


def test_bare_multiplayer_normalizes_to_the_canonical_token():
    from services.normalization import normalize_modes
    assert normalize_modes('Single-player, Multiplayer') == \
        'Single-Player, Local Multiplayer'


def test_player_count_plus_form_is_parsed():
    """ES-DE sends "4+"; only its own copy of the parse handled it."""
    from services.game_utils import normalize_players_value
    assert normalize_players_value('4+') == 4
    assert normalize_players_value('1-4+') == 4
