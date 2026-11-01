"""PASS-59-206: every source's genres, perspectives and modes reach one set of names.

The words below were counted in a real library, so each is a word a source
really sends. No test here reaches a scraper's service.
"""
import json
import sqlite3

import pytest

import config
from scraper.metadata_merger import apply_igdb_to_metadata, apply_rawg_to_metadata
from scraper.scrape_ai import FIELD_SCHEMAS
from services import game_cleanup, migrations, normalization
from services.normalization import modes_from_player_count, normalize_genre, normalize_modes

SEEN_GENRES = """Role Playing Game|Arcade|Beat 'em Up|Shoot 'em Up|FPV|Shooter Scrolling|Versus
Third-Person Shooter|Football (American)|Football (Soccer)|Side-Scroller|Vertical-Scroller|Baseball
Compilation|Basketball|Boxing|Indie|Golf|Lightgun Shooter|Pinball|Fighter Scrolling|Multisports|Fall
Run and Gun|Quiz|Tennis|Plane|Hockey|Pool|Various|Music|Racing TPV|3D|Hunting and Fishing
Music and Dancing|RealTime 3D|Run & Jump|Cycling|Breakout games|Board Games|2D|Fishing
Motorcycle race TPV|Vehicle|Japanese RPG|Run & Jump Scrolling|Space Invaders Like|Bowling|Skiing
Wrestling|Sandbox|Unofficial|Casino|Dungeon Crawler RPG|Point and Click|Throw|Motorcycle|Life|Extreme
Rugby|Water|Construction and Management Simulation|Family|Virtual Console|Interactive Movie
Build And Management|Motorcycle race FPV|Party-Based RPG|Racing FPV|Boat|Real Time Strategy (RTS)
Rhythm|Diagonal|Tactical|Shougi|Asiatic board game|Darts|Skateboard|Volleyball
Turn-based strategy (TBS)|Thinking|Role-playing (RPG)|MOBA|Card & Board Game|Massively Multiplayer
Hack and slash/Beat 'em up|Quiz/Trivia|Shoot'em Up / Vertical|Education|MMO"""


def _words(text):
    return [w for line in text.splitlines() for w in line.split('|')]


def _is_canonical(field, value):
    return all(word in FIELD_SCHEMAS[field] for word in value.split(', ') if word)


@pytest.fixture(autouse=True)
def fresh_maps():
    normalization.invalidate_normalization_cache()
    yield
    normalization.invalidate_normalization_cache()


@pytest.mark.parametrize('word', _words(SEEN_GENRES))
def test_every_genre_word_seen_ends_canonical(word):
    assert _is_canonical('genre', normalize_genre(word)), normalize_genre(word)


@pytest.mark.parametrize('word,expected', [
    ('Role Playing Game', 'RPG'),
    ('Role-playing (RPG)', 'RPG'),
    ('Real Time Strategy (RTS)', 'Real-Time Strategy'),
    ('Turn-based strategy (TBS)', 'Turn-Based Strategy'),
    ('Music', 'Music-Rhythm'),
    ('Football (Soccer)', 'Sports'),
    ('Quiz', 'Trivia'),
    ('Tactical', 'Strategy'),
    ('Board Games', 'Board-Card'),
    ("Beat 'em Up", 'Beat-em-up'),
    ('Arcade', ''),
    ('Indie', ''),
    ('Unofficial', ''),
    ('Word no source has sent', ''),
    ('Racing, Arcade', 'Racing'),
    ('Adventure, RPG, Unofficial', 'Adventure, RPG'),
])
def test_genre_names(word, expected):
    assert normalize_genre(word) == expected


@pytest.mark.parametrize('field,word,value,moved', [
    ('genre', 'Racing TPV', 'Racing', {'perspective': 'Third-Person'}),
    ('genre', 'FPV', '', {'perspective': 'First-Person'}),
    ('genre', 'Side-Scroller', '', {'perspective': 'Side-Scroller'}),
    ('genre', 'RealTime 3D', '', {'dimension': '3D'}),
    ('genre', 'Action, Sandbox', 'Action', {'game_structure': 'Sandbox'}),
    ('genre', "Shoot'em Up / Vertical", 'Shoot-em-up', {'perspective': 'Vertical-Scroller'}),
    ('perspective', 'Third person', 'Third-Person', {}),
    ('perspective', 'First person', 'First-Person', {}),
    ('perspective', 'Side view', 'Side-Scroller', {}),
    ('perspective', 'Bird view / Isometric', 'Isometric', {}),
    ('perspective', 'Text', '', {}),
    ('perspective', 'Auditory', '', {}),
    ('perspective', 'Virtual Reality', '', {'dimension': 'VR'}),
    ('game_structure', 'Open World', 'Open-World', {}),
    ('game_structure', 'Level-based', 'Level-Based', {}),
])
def test_split_labels(field, word, value, moved):
    assert normalization.split_labels(field, word) == (value, moved)


@pytest.mark.parametrize('word,expected', [
    ('Co-op', 'Local Co-op'),
    ('Split-screen Multiplayer', 'Split-Screen'),
    ('Competitive Multiplayer', 'Versus'),
    ('Co-Op Multiplayer', 'Local Co-op'),
    ('Single-player with 2 controllers', ''),
    ('Massively Multiplayer Online (MMO)', 'MMO'),
    ('Multiplayer', 'Local Multiplayer'),
])
def test_mode_names(word, expected):
    assert normalize_modes(word) == expected


def test_a_library_rule_to_an_unknown_name_gives_way_to_the_canonical_one(monkeypatch):
    """This library's own rule `beat'em up -> Beat 'em Up` split the genre in two."""
    monkeypatch.setattr(normalization, 'query', lambda sql, args=(): (
        [{'from_value': "beat'em up", 'to_value': "Beat 'em Up"},
         {'from_value': 'role-playing (rpg)', 'to_value': 'Adventure'}]
        if 'normalization_rules' in sql else [{'value': 'My Own Genre'}]))
    assert normalize_genre("Beat'em Up") == 'Beat-em-up'
    assert normalize_genre('Role-playing (RPG)') == 'Adventure'


def test_a_value_added_to_a_dropdown_is_kept(monkeypatch):
    monkeypatch.setattr(normalization, 'query', lambda sql, args=(): (
        [] if 'normalization_rules' in sql else [{'value': 'My Own Genre'}]))
    assert normalize_genre('my own genre, Arcade') == 'My Own Genre'


@pytest.mark.parametrize('names,multi,expected', [
    (['Multiplayer'], [{'onlinemax': 24, 'offlinemax': 0}], 'Online Multiplayer'),
    (['Single player', 'Multiplayer'], [{'offlinemax': 4}], 'Single-Player, Local Multiplayer'),
    (['Multiplayer'], [{'onlinemax': 8, 'offlinemax': 2, 'splitscreen': True}],
     'Local Multiplayer, Online Multiplayer, Split-Screen'),
    (['Multiplayer'], [{'onlinecoop': True}], 'Online Co-op'),
    (['Multiplayer'], [{'offlinecoop': True}], 'Local Co-op'),
    (['Multiplayer'], [{'offlinemax': None}], 'Local Multiplayer'),
    (['Multiplayer'], [], 'Local Multiplayer'),
    (['Single player'], [{'onlinemax': 8}], 'Single-Player'),
])
def test_igdb_multiplayer_comes_from_its_details(names, multi, expected):
    assert normalization.modes_from_igdb(names, multi) == expected


@pytest.mark.parametrize('players,expected', [
    ('2-4', 'Local Multiplayer'),
    ('2-24', 'Local Multiplayer'),
    ('1-4', 'Single-Player, Local Multiplayer'),
    (2, 'Single-Player, Local Multiplayer'),
])
def test_a_range_starting_above_one_is_not_single_player(players, expected):
    assert modes_from_player_count(players) == expected


@pytest.mark.parametrize('before,after', [
    ({'players': 1, 'modes': 'Local Multiplayer'}, {'players': 2}),
    ({'players': 1, 'modes': 'Single-Player, Versus'}, {'players': 2}),
    ({'players': 4, 'modes': 'Single-Player'}, {'modes': 'Single-Player, Local Multiplayer'}),
    ({'players': 1, 'modes': 'Single-Player'}, {}),
    ({'players': 4, 'modes': 'Single-Player, Online Multiplayer'}, {}),
    ({'players': None, 'modes': 'Local Multiplayer'}, {}),
])
def test_player_count_and_modes_agree(before, after):
    metadata = dict(before)
    normalization.canonicalize_metadata(metadata)
    assert metadata == {**before, **after}


def test_a_moved_word_never_replaces_a_stored_value():
    metadata = {'genre': 'Racing TPV', 'perspective': 'First-Person', 'dimension': None}
    normalization.canonicalize_metadata(metadata)
    assert metadata['genre'] == 'Racing'
    assert metadata['perspective'] == 'First-Person'


def _blank():
    return {'genre': None, 'modes': None, 'players': None, 'perspective': None,
            'dimension': None, 'game_structure': None, 'title': None, 'description': None,
            'developer': None, 'publisher': None, 'release_date': None, 'esrb_rating': None,
            'pegi_rating': None, 'critic_score': None, 'critic_score_count': None,
            'user_score': None, 'user_score_count': None, 'franchise': None,
            'playtime_estimate': None, 'boxart': None, 'fanart': None, 'screenshots': None,
            'video': None, 'manual': None, 'boxart_3d': None, 'region': None,
            'similar_games': None, 'alternate_titles': None, 'other_platforms': None}


def test_a_source_with_only_a_dropped_genre_leaves_it_open_for_the_next():
    metadata, result = _blank(), {'filled_fields': []}
    apply_rawg_to_metadata(metadata, {'genre': 'Arcade, Indie'}, 1, result, fill_only=True)
    assert not metadata['genre']
    assert 'genre (RAWG)' not in result['filled_fields']
    apply_rawg_to_metadata(metadata, {'genre': 'Racing'}, 1, result, fill_only=True)
    assert metadata['genre'] == 'Racing'


def test_igdb_merge_uses_multiplayer_details():
    metadata, result = _blank(), {'filled_fields': []}
    apply_igdb_to_metadata(metadata, {
        'game_modes': [{'name': 'Multiplayer'}],
        'multiplayer_modes': [{'onlinemax': 24}],
    }, 1, result, fill_only=True)
    assert metadata['modes'] == 'Online Multiplayer'


def _history(*fields):
    return json.dumps([{'fields_filled': list(fields)}])


@pytest.fixture
def library(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Sega Saturn', 'saturn')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, 'DB_PATH', path)

    def add(game_id, **cols):
        c = sqlite3.connect(path)
        names = ['id', 'system_id', 'title', 'rom_path', *cols]
        values = [game_id, 1, f'Game {game_id}', f'/roms/saturn/{game_id}.zip', *cols.values()]
        c.execute(f"INSERT INTO games ({', '.join(names)}) "
                  f"VALUES ({', '.join('?' * len(names))})", values)
        c.commit()
        c.close()

    def row(game_id):
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        found = dict(c.execute('SELECT * FROM games WHERE id = ?', (game_id,)).fetchone())
        c.close()
        return found

    return add, row


def test_cleanup_counts_then_converts_stored_rows(library):
    add, row = library
    add(1, genre='Racing, Arcade', perspective='Third person', modes='Co-op')
    add(2, genre='Role Playing Game', perspective='Side view, Text')
    add(3, genre='Racing TPV')
    add(4, genre='Action', perspective='Top-Down', modes='Single-Player', players=1)

    assert game_cleanup.count_label_changes() == 3
    assert row(1)['genre'] == 'Racing, Arcade', 'the count must change nothing'

    assert game_cleanup.fix_labels() == 3
    assert (row(1)['genre'], row(1)['perspective'], row(1)['modes']) == \
        ('Racing', 'Third-Person', 'Local Co-op')
    assert (row(2)['genre'], row(2)['perspective']) == ('RPG', 'Side-Scroller')
    assert (row(3)['genre'], row(3)['perspective']) == ('Racing', 'Third-Person')
    assert game_cleanup.count_label_changes() == 0


def test_cleanup_leaves_a_genre_empty_not_blank(library):
    add, row = library
    add(1, genre='Arcade')
    game_cleanup.fix_labels()
    assert row(1)['genre'] is None


def test_cleanup_clears_a_stale_rawg_player_count(library):
    """RAWG no longer sends a default of 1, but its old ones block a real count."""
    add, row = library
    add(1, players=1, scrape_history=_history('players (RAWG)'))
    add(2, players=1, scrape_history=_history('players (ScreenScraper)'))
    add(3, players=4, scrape_history=_history('players (RAWG)'))
    add(4, players=1, scrape_history=json.dumps([
        {'fields_filled': ['players (RAWG)']}, {'fields_filled': ['players (IGDB)']}]))

    assert game_cleanup.fix_labels() == 1
    assert row(1)['players'] is None
    assert row(2)['players'] == 1
    assert row(3)['players'] == 4
    assert row(4)['players'] == 1


def test_cleanup_reconciles_players_and_modes(library):
    add, row = library
    add(1, players=1, modes='Local Multiplayer')
    add(2, players=4, modes='Single-Player')
    game_cleanup.fix_labels()
    assert row(1)['players'] == 2
    assert row(2)['modes'] == 'Single-Player, Local Multiplayer'


def test_cleanup_skips_a_row_changed_since_it_was_read(library, monkeypatch):
    """A scrape can be running while the button is pressed."""
    add, row = library
    add(1, genre='Arcade, Racing')
    real = game_cleanup._label_changes

    def then_a_scrape_writes():
        found = real()
        conn = sqlite3.connect(config.DB_PATH)
        conn.execute("UPDATE games SET genre = 'Puzzle' WHERE id = 1")
        conn.commit()
        conn.close()
        return found

    monkeypatch.setattr(game_cleanup, '_label_changes', then_a_scrape_writes)
    assert game_cleanup.fix_labels() == 0
    assert row(1)['genre'] == 'Puzzle'
