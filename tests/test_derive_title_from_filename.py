"""PASS-59-126: derive_title_from_filename strips every tag a ROM filename
carries, so a bulk scrape searches with the bare game title."""
import pytest

from services.game_utils import derive_title_from_filename


@pytest.mark.parametrize('filename, is_computer, expected', [
    # Every tag from the year onward goes on a computer system.
    ("Chuckie Egg 2 (UK) (1985) (A'n'F Software) (tzx).zip", True, 'Chuckie Egg 2'),
    # A combined region tag is a region tag.
    ('Pokemon - Gold Version (USA, Europe).zip', False, 'Pokemon: Gold Version'),
    ('Tetris (Europe) (En,Fr,De,Es).zip', False, 'Tetris'),
    # A double-dot extension leaves no trailing dot.
    ('International Karate+ (1987) (System 3)..zip', True, 'International Karate+'),
    # A name part before the year stays.
    ('F-19 Stealth Fighter (Simulation Mode) (1990) (MicroProse).zip', True,
     'F-19 Stealth Fighter (Simulation Mode)'),
    # Unchanged cases.
    ('Lemmings (1991) (Psygnosis).adf', True, 'Lemmings'),
    ('The Legend of Zelda - Ocarina of Time (USA).n64', False,
     'The Legend of Zelda: Ocarina of Time'),
    ('Super Mario Bros. (World).nes', False, 'Super Mario Bros.'),
])
def test_derive_title_from_filename(filename, is_computer, expected):
    assert derive_title_from_filename(filename, is_computer) == expected
