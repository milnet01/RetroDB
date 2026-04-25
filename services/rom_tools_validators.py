# =============================================================================
# RETRODB — Per-key validators for rom_tools_config.json
# =============================================================================
# Pass 40.1 — the previous /api/rom-tools/settings POST handler wrote the
# attacker-supplied JSON body verbatim via atomic_write_json().  Downstream
# CHD conversion and verification used the persisted `chdman_path` as
# argv[0] in subprocess.run([chdman_path, ...]), so a logged-in user could
# substitute /usr/bin/python3 or /tmp/evil and gain arbitrary code
# execution under the Flask UID (CWE-78).
#
# This module mirrors services.settings_validators: every persisted key
# has an explicit validator; unknown keys are rejected by the caller.
# =============================================================================

import os


_ALLOWED_DUPLICATE_METHODS = {'hash', 'name', 'size'}

# Linux + macOS system binary directories considered safe to invoke from.
# Windows installs typically rely on PATH lookup of the bare name `chdman.exe`,
# so absolute Windows paths are rejected — symlink chdman.exe into PATH instead.
_SAFE_BIN_PREFIXES = (
    '/usr/bin/',
    '/usr/local/bin/',
    '/opt/homebrew/bin/',  # macOS Apple-Silicon Homebrew
    '/opt/local/bin/',     # MacPorts
    '/bin/',
)

_CHDMAN_BASENAMES = {'chdman', 'chdman.exe'}

_SCANNER_TYPE_KEYS = {'zip', '7z', 'rar'}
_SCANNER_MODE_KEYS = {'corrupted', 'multiFile', 'unwanted'}


def _bool_validator(value):
    if not isinstance(value, bool):
        return False, 'must be true or false', None
    return True, None, value


def _string_list_validator(max_items=128, max_len=255):
    def _inner(value):
        if not isinstance(value, list):
            return False, 'must be a list of strings', None
        if len(value) > max_items:
            return False, f'must contain at most {max_items} entries', None
        cleaned = []
        for item in value:
            if not isinstance(item, str):
                return False, 'every entry must be a string', None
            stripped = item.strip()
            if len(stripped) > max_len:
                return False, f'entry too long (>{max_len} chars)', None
            cleaned.append(stripped)
        return True, None, cleaned
    return _inner


def _path_string_validator(allow_empty=True, max_len=4096):
    def _inner(value):
        if not isinstance(value, str):
            return False, 'must be a string path', None
        stripped = value.strip()
        if not stripped:
            if allow_empty:
                return True, None, ''
            return False, 'must not be empty', None
        if len(stripped) > max_len:
            return False, 'path too long', None
        # No NUL bytes; no control characters.
        if '\x00' in stripped or any(ord(c) < 0x20 for c in stripped):
            return False, 'path contains invalid characters', None
        return True, None, stripped
    return _inner


def _bool_dict_validator(allowed_keys):
    """Fixed-shape dict of {known_key: bool}.  Unknown keys rejected."""
    def _inner(value):
        if not isinstance(value, dict):
            return False, 'must be an object', None
        cleaned = {}
        for key, flag in value.items():
            if key not in allowed_keys:
                return False, f'unknown key: {key}', None
            if not isinstance(flag, bool):
                return False, f'{key} must be a boolean', None
            cleaned[key] = flag
        return True, None, cleaned
    return _inner


def _enum_validator(allowed):
    def _inner(value):
        if not isinstance(value, str) or value not in allowed:
            return False, f'must be one of {sorted(allowed)}', None
        return True, None, value
    return _inner


def _chdman_path_validator(value):
    """Allow the bare name `chdman` (let PATH resolve) or an absolute path
    under a known-safe system binary directory ending in /chdman.

    Reject:
      - non-strings
      - relative paths other than the bare name
      - absolute paths to writable dirs (/tmp, /home, /var, etc.)
      - traversal sequences
      - any basename other than chdman / chdman.exe
    """
    if not isinstance(value, str):
        return False, 'must be a string', None
    stripped = value.strip()
    # Empty / bare name → normalize to 'chdman'.
    if stripped == '' or stripped == 'chdman':
        return True, None, 'chdman'
    if stripped == 'chdman.exe':
        return True, None, 'chdman.exe'
    if not os.path.isabs(stripped):
        return False, 'must be "chdman" or absolute path to chdman binary', None
    # Reject traversal sequences (defence in depth — normalize would resolve
    # them but the prefix check would still match).
    if '..' in stripped.split('/'):
        return False, 'path must not contain traversal segments', None
    basename = os.path.basename(stripped)
    if basename not in _CHDMAN_BASENAMES:
        return False, 'binary name must be chdman', None
    for prefix in _SAFE_BIN_PREFIXES:
        if stripped.startswith(prefix):
            # Anchor: nothing between prefix and basename (so /usr/bin/foo/chdman
            # is rejected — only /usr/bin/chdman directly).
            if stripped == prefix + basename:
                return True, None, stripped
    return False, 'must be in a system binary directory (/usr/bin, /usr/local/bin, etc.)', None


_VALIDATORS = {
    'roms_path':                _path_string_validator(allow_empty=True),
    'output_path':              _path_string_validator(allow_empty=True),
    'temp_path':                _path_string_validator(allow_empty=True),
    'archive_types':            _string_list_validator(max_items=32, max_len=16),
    'recursive_scan':           _bool_validator,
    'verify_integrity':         _bool_validator,
    'generate_m3u':             _bool_validator,
    'remove_unwanted':          _bool_validator,
    'unwanted_patterns':        _string_list_validator(max_items=64, max_len=64),
    'excluded_paths':           _string_list_validator(max_items=128, max_len=4096),
    'chdman_path':              _chdman_path_validator,
    'chd_verify_after_convert': _bool_validator,
    'chd_delete_originals':     _bool_validator,
    'chd_skip_existing':        _bool_validator,
    'duplicate_method':         _enum_validator(_ALLOWED_DUPLICATE_METHODS),
    'ignore_region_tags':       _bool_validator,
    'include_archives':         _bool_validator,
    'scanner_types':            _bool_dict_validator(_SCANNER_TYPE_KEYS),
    'scanner_modes':            _bool_dict_validator(_SCANNER_MODE_KEYS),
}


def known_rom_tools_keys():
    """Return the set of valid rom_tools_config.json keys."""
    return set(_VALIDATORS.keys())


def validate_rom_tools_value(key, value):
    """Validate one (key, value) against the per-key validator table.

    Returns (ok, reason, cleaned):
        ok=True, reason=None, cleaned=<normalized value>   on success
        ok=False, reason=<string>, cleaned=None             on failure
    Unknown keys fail with ok=False, reason='unknown setting key'.
    """
    validator = _VALIDATORS.get(key)
    if validator is None:
        return False, 'unknown setting key', None
    return validator(value)
