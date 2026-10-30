"""PASS-59-194 — RetroDB signs DuckStation and PCSX2 in to RetroAchievements at
Play. Files live under tmp_path; no test reaches the network or a real emulator.
"""
import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from services import platform_tokens, ra_sign_in, ra_standalone
from services.database import execute, query

TOKEN = 'connect-token-abc'
# From `openssl enc -aes-128-cbc -nopad -a` with a key made as
# GetLoginEncryptionKey does, machine key b'abcdef0123456789\n', username Ants.
DUCKSTATION_VECTOR = 'hcyZFmFHD+HLtoV8H7nkPno0oydpiOf+1DqIPHfBAQ4='
REC = {'username': 'Ants', 'token': TOKEN, 'hardcore': False}


@pytest.fixture
def emu(setup_complete):
    made = []

    def make(kind):
        eid = execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, enabled) "
                      "VALUES (?, ?, '', 0, 1)", (f'RAProbe {kind} {len(made)}', kind))
        made.append(eid)
        return {'id': eid, 'binary_name': kind}
    yield make
    for eid in made:
        execute("DELETE FROM emulator_written_settings WHERE emulator_id = ?", (eid,))
        execute("DELETE FROM emulators WHERE id = ?", (eid,))


@pytest.fixture
def duckstation(emu, tmp_path, monkeypatch):
    monkeypatch.setattr(ra_standalone, '_machine_key', lambda: b'abcdef0123456789\n')
    (tmp_path / 'settings.ini').write_text('[Main]\nSettingsVersion = 3\n\n[Cheevos]\nEnabled = false\n')
    return emu('duckstation-qt'), tmp_path / 'emu', tmp_path, tmp_path / 'settings.ini'


@pytest.fixture
def pcsx2(emu, tmp_path):
    (tmp_path / 'inis').mkdir()
    (tmp_path / 'inis' / 'PCSX2.ini').write_text('[EmuCore]\nCheats = false\n')
    return emu('pcsx2-qt'), tmp_path / 'emu', tmp_path, tmp_path / 'inis' / 'PCSX2.ini'


def _play(target, rec):
    emulator, binary, data_dir, _path = target
    ra_standalone._hand_over(emulator, binary, data_dir, rec)


def _section(path, name):
    out, on = {}, False
    for line in Path(path).read_text().splitlines():
        if line.startswith('['):
            on = line == f'[{name}]'
        elif on and '=' in line:
            key, value = line.split('=', 1)
            out[key.strip()] = value.strip()
    return out


def test_duckstation_token_matches_an_independent_aes_run(monkeypatch):
    monkeypatch.setattr(ra_standalone, '_machine_key', lambda: b'abcdef0123456789\n')
    assert ra_standalone._duckstation_token('Ants', TOKEN, portable=False) == DUCKSTATION_VECTOR


def test_a_portable_duckstation_uses_no_machine_key(monkeypatch):
    monkeypatch.setattr(ra_standalone, '_machine_key', lambda: b'abcdef0123456789\n')
    portable = ra_standalone._duckstation_token('Ants', TOKEN, portable=True)
    assert portable != DUCKSTATION_VECTOR
    monkeypatch.setattr(ra_standalone, '_machine_key', lambda: pytest.fail('read the machine key'))
    assert ra_standalone._duckstation_token('Ants', TOKEN, portable=True) == portable


def test_duckstation_gets_an_encrypted_token_it_can_read_back(duckstation):
    _play(duckstation, REC)
    keys = _section(duckstation[3], 'Cheevos')
    assert keys['Username'] == 'Ants' and keys['Enabled'] == 'true' and keys['ChallengeMode'] == 'false'
    assert TOKEN not in duckstation[3].read_text()
    assert keys['Token'] == DUCKSTATION_VECTOR
    assert int(keys['LoginTimestamp']) > 0
    assert _section(duckstation[3], 'Main') == {'SettingsVersion': '3'}


def test_no_machine_key_leaves_duckstation_alone(duckstation, monkeypatch):
    monkeypatch.setattr(ra_standalone, '_machine_key', lambda: None)
    before = duckstation[3].read_text()
    _play(duckstation, REC)
    assert duckstation[3].read_text() == before


def test_pcsx2_gets_the_token_in_its_base_file(pcsx2):
    _play(pcsx2, dict(REC, hardcore=True))
    keys = _section(pcsx2[3], 'Achievements')
    assert keys['Token'] == TOKEN and keys['ChallengeMode'] == 'true'
    assert _section(pcsx2[3], 'EmuCore') == {'Cheats': 'false'}


def test_the_database_never_holds_the_token(pcsx2):
    _play(pcsx2, REC)
    rows = query("SELECT setting, written FROM emulator_written_settings WHERE file_path = ?",
                 (str(pcsx2[3]),))
    assert rows and all(TOKEN not in r['written'] for r in rows)


def test_a_token_pcsx2_moved_to_secrets_is_not_written_again(pcsx2):
    _play(pcsx2, REC)
    text = pcsx2[3].read_text().replace(f'Token = {TOKEN}\n', '')
    pcsx2[3].write_text(text)
    _play(pcsx2, REC)
    assert 'Token' not in _section(pcsx2[3], 'Achievements')


def test_a_new_token_is_written_over_the_old(pcsx2):
    _play(pcsx2, REC)
    _play(pcsx2, dict(REC, token='a-newer-token'))
    assert _section(pcsx2[3], 'Achievements')['Token'] == 'a-newer-token'


def test_a_sign_in_from_the_emulators_menu_is_left_alone(pcsx2):
    original = '[Achievements]\nEnabled = false\nUsername = Someone\n'
    pcsx2[3].write_text(original)
    _play(pcsx2, REC)
    assert pcsx2[3].read_text() == original
    _play(pcsx2, None)
    assert pcsx2[3].read_text() == original


def test_a_signed_out_user_playing_takes_the_sign_in_back_out(pcsx2):
    pcsx2[3].write_text('[Achievements]\nEnabled = false\n')
    secrets = pcsx2[2] / 'inis' / 'secrets.ini'
    _play(pcsx2, REC)
    secrets.write_text(f'[Achievements]\nToken = {TOKEN}\n')
    _play(pcsx2, None)
    assert _section(pcsx2[3], 'Achievements') == {'Enabled': 'false'}
    assert TOKEN not in secrets.read_text()
    assert query("SELECT 1 FROM emulator_written_settings WHERE file_path = ?", (str(pcsx2[3]),)) == []


def test_another_signed_in_user_replaces_the_first(pcsx2):
    _play(pcsx2, REC)
    _play(pcsx2, {'username': 'Other', 'token': 'other-token', 'hardcore': False})
    keys = _section(pcsx2[3], 'Achievements')
    assert keys['Username'] == 'Other' and keys['Token'] == 'other-token'


@pytest.fixture
def user(setup_complete):
    uid = execute("INSERT INTO users (username, password_hash, role) VALUES ('ra-standalone', 'x', 'viewer')")
    yield uid
    execute("DELETE FROM user_platform_tokens WHERE user_id = ?", (uid,))
    execute("DELETE FROM users WHERE id = ?", (uid,))


def test_signing_out_of_retrodb_clears_the_emulator(pcsx2, user):
    platform_tokens.save_tokens(user, ra_sign_in.PLATFORM, REC)
    _play(pcsx2, REC)
    ra_sign_in.sign_out(user)
    assert 'Username' not in _section(pcsx2[3], 'Achievements')
    assert TOKEN not in pcsx2[3].read_text()


def test_signing_out_does_not_touch_another_accounts_sign_in(pcsx2, user):
    platform_tokens.save_tokens(user, ra_sign_in.PLATFORM, REC)
    _play(pcsx2, {'username': 'Other', 'token': 'other-token', 'hardcore': False})
    ra_sign_in.sign_out(user)
    assert _section(pcsx2[3], 'Achievements')['Username'] == 'Other'


def test_a_broken_settings_file_does_not_stop_a_launch(monkeypatch):
    monkeypatch.setattr('services.standalone_settings._context', lambda _gid: 1 / 0)
    ra_standalone.apply_for_launch(1)


def test_the_vector_decrypts_to_the_token():
    import hashlib
    digest = hashlib.sha256(b'abcdef0123456789\nAnts').digest()
    for _round in range(100):
        digest = hashlib.sha256(digest).digest()
    dec = Cipher(algorithms.AES(digest[:16]), modes.CBC(digest[16:])).decryptor()
    plain = dec.update(base64.b64decode(DUCKSTATION_VECTOR)) + dec.finalize()
    assert plain.rstrip(b'\0').decode() == TOKEN
