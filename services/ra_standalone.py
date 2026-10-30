# =============================================================================
# RETRODB - RetroAchievements sign-in for DuckStation and PCSX2 (PASS-59-194)
# =============================================================================
# Neither emulator takes a sign-in for one launch, as RetroArch does, so at Play
# RetroDB writes the launching user's sign-in into the emulator's main settings
# file. It stays there until that user signs out of RetroDB or someone else
# plays. A sign-in made in the emulator's own menu is theirs and is left alone.
#
# emulator_written_settings records what RetroDB wrote: the username, and only
# a hash of the token. PCSX2 moves a token from PCSX2.ini to inis/secrets.ini
# when it starts, so the Token line is often gone by the next launch.
#
# Nothing here raises into a launch.
# =============================================================================

import base64
import hashlib
import logging
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from services import ra_sign_in
from services import standalone_settings as ss
from services.database import get_db_with_context, query

logger = logging.getLogger(__name__)

# Main settings file and section, from each emulator's source.
_FILES = {'duckstation-qt': ('settings.ini', 'Cheevos'),
          'pcsx2-qt': ('inis/PCSX2.ini', 'Achievements')}
_SECRETS = 'secrets.ini'                     # PCSX2's, beside its PCSX2.ini
_REMOVE = ('Username', 'Token', 'LoginTimestamp', 'AvatarURL')

_KEY_ROUNDS = 100
_AES_BLOCK = 16


def _machine_key():
    """What DuckStation's GetLoginEncryptionMachineKey returns, or None. The
    bytes go in as they are: Linux keeps the newline, Windows the ending NUL."""
    if sys.platform.startswith('linux'):
        return Path('/etc/machine-id').read_bytes() or None
    if sys.platform == 'win32':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, 'MachineGuid')[0].encode('ascii') + b'\0'
    return None


def _duckstation_token(username, token, portable):
    """Achievements::EncryptLoginToken, or None without a machine key. DuckStation
    cannot read a plain token: it asks the user to sign in again."""
    machine = b'' if portable else _machine_key()
    if machine is None:
        return None
    digest = hashlib.sha256(machine + username.encode('utf-8')).digest()
    for _round in range(_KEY_ROUNDS):
        digest = hashlib.sha256(digest).digest()
    data = token.encode('utf-8')
    data += b'\0' * (-len(data) % _AES_BLOCK)
    # CBC is DuckStation's format, which RetroDB must match; DuckStation is what reads this.
    enc = Cipher(algorithms.AES(digest[:16]), modes.CBC(digest[16:])).encryptor()  # nosemgrep: python.cryptography.security.mode-without-authentication.crypto-mode-without-authentication
    return base64.b64encode(enc.update(data) + enc.finalize()).decode('ascii')


def _token_for_file(binary_name, rec, binary):
    if binary_name == 'duckstation-qt':
        return _duckstation_token(rec['username'], rec['token'],
                                  (binary.parent / 'portable.txt').exists())
    return rec['token']


def _field(section, key) -> dict:
    return {'section': section, 'key': key}


def _hash(token) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _delete_key(lines, section, key) -> list:
    _head, idx, _insert = ss._ini_find(lines, section, key)
    return lines if idx is None else lines[:idx] + lines[idx + 1:]


def _record_written(emulator_id, path, values) -> None:
    with get_db_with_context() as conn:
        conn.executemany("""
            INSERT INTO emulator_written_settings (emulator_id, file_path, setting, written)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (file_path, setting) DO UPDATE SET written = excluded.written,
                                                           emulator_id = excluded.emulator_id
        """, [(emulator_id, str(path), k, v) for k, v in values.items()])
        conn.commit()


def _take_back(path: Path, section, written) -> None:
    """Remove RetroDB's sign-in and put Enabled and ChallengeMode back."""
    lines = ss._read_lines(path)
    before = list(lines)
    for key in _REMOVE:
        lines = _delete_key(lines, section, key)
    for key in ('Enabled', 'ChallengeMode'):
        old = written.get(f'ra_before_{key}')
        if old:
            lines = ss.write_value(lines, _field(section, key), old)
        elif old == '':
            lines = _delete_key(lines, section, key)
    if lines != before:
        ss.write_lines(path, lines)
    if section == 'Achievements':
        secrets = path.parent / _SECRETS
        held = ss._read_lines(secrets)
        kept = _delete_key(held, section, 'Token')
        if kept != held:
            ss.write_lines(secrets, kept)
    with get_db_with_context() as conn:
        conn.execute("DELETE FROM emulator_written_settings WHERE file_path = ? AND setting LIKE 'ra\\_%' ESCAPE '\\'",
                     (str(path),))
        conn.commit()


def _hand_over(emu, binary: Path, data_dir: Path, rec) -> None:
    """Bring one emulator's main settings file into line with `rec`, the
    launching user's sign-in, or None."""
    main_file, section = _FILES[emu['binary_name']]
    path = data_dir / main_file
    if not path.is_file():
        return
    lines = ss._read_lines(path)
    written = ss._written(path)
    current = ss.read_value(lines, _field(section, 'Username'))
    ours = bool(current) and written.get('ra_username') == current
    if current and not ours:
        return                               # signed in from the emulator's menu
    if not rec:
        if ours:
            _take_back(path, section, written)
        return
    value = _token_for_file(emu['binary_name'], rec, binary)
    if value is None:
        logger.info("RetroAchievements: no machine key, DuckStation not signed in")
        return

    record = {'ra_username': rec['username'], 'ra_token': _hash(rec['token'])}
    for key in ('Enabled', 'ChallengeMode'):
        record[f'ra_before_{key}'] = written.get(f'ra_before_{key}',
                                                 ss.read_value(lines, _field(section, key)) or '')
    new = list(lines)
    if not ours or written.get('ra_username') != rec['username'] \
            or written.get('ra_token') != record['ra_token']:
        new = ss.write_value(new, _field(section, 'Username'), rec['username'])
        new = ss.write_value(new, _field(section, 'Token'), value)
        new = ss.write_value(new, _field(section, 'LoginTimestamp'), str(int(time.time())))
    new = ss.write_value(new, _field(section, 'Enabled'), 'true')
    new = ss.write_value(new, _field(section, 'ChallengeMode'), 'true' if rec.get('hardcore') else 'false')
    if new != lines:
        ss.write_lines(path, new)
    _record_written(emu['id'], path, record)


def apply_for_launch(game_id) -> None:
    """Sign the emulator for this game in as whoever pressed Play. Never raises."""
    from services.launch_resolver import _launching_user_id
    try:
        ctx = ss._context(game_id)
        emu = ctx.get('emulator')
        if not emu or emu['binary_name'] not in _FILES or not ctx.get('data_dir'):
            return
        _hand_over(emu, ctx['binary'], ctx['data_dir'], ra_sign_in._record(_launching_user_id()))
    except Exception as e:  # noqa: BLE001 — a sign-in problem never stops a launch
        # The type only: a message could quote the token.
        logger.warning("RetroAchievements: emulator not signed in for game %s: %s",
                       game_id, type(e).__name__)


def sign_out(username) -> None:
    """Take this RetroAchievements account back out of every emulator RetroDB
    signed it into. Never raises."""
    rows = query("SELECT file_path FROM emulator_written_settings "
                 "WHERE setting = 'ra_username' AND written = ?", (username,))
    for row in rows:
        path = Path(row['file_path'])
        section = 'Cheevos' if path.name == 'settings.ini' else 'Achievements'
        try:
            written = ss._written(path)
            if ss.read_value(ss._read_lines(path), _field(section, 'Username')) == username:
                _take_back(path, section, written)
        except Exception as e:  # noqa: BLE001 — sign-out in RetroDB still succeeds
            logger.warning("RetroAchievements: %s not cleared: %s", path.name, type(e).__name__)
