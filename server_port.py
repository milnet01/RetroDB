#!/usr/bin/env python3
# server_port.py - RetroDB server-port resolution
# ================================================================================
# Resolves the TCP port the server binds, from the environment.
#
#   PORT  ->  RETRODB_PORT  ->  saved `server_port`  ->  caller's default (5000)
#
# Lives in its own top-level module rather than inside config.py for two
# reasons.  config.py is user-owned and gitignored (installer_core.py copies
# config.example.py into place on first install), so an existing user's copy
# can be older than the code calling into it — keeping the logic here means
# every install resolves the port identically.  And config.py's assignments run
# at *import*, which app.py, scripts/retrodb_launcher.py and the whole test
# suite all do; a malformed value must not turn an import into a traceback.
#
# Absence and invalidity are deliberately NOT the same thing.  An unset or
# empty variable falls through to the next source; a malformed one raises, so
# the caller exits non-zero with a message naming the value.  Silently binding
# 5000 for a tool that asked for 80 is the exact failure this module prevents.
#
# Run as a script (`python3 server_port.py`) it prints the resolved port on
# stdout, or a message on stderr and exits 1 — that is what start.sh /
# start.command / start.bat use to label the banner and the browser-open URL.
# ================================================================================

import os
import sys

DEFAULT_PORT = 5000

# Per-variable valid range.  Insertion order IS the precedence order.
#
# PORT is the machine-facing channel: a supervising tool picks it, never a
# human, and no such tool has a good reason to ask for a privileged port — so
# it gets the strict 1024-65535 range.  RETRODB_PORT is this project's own
# hand-typed override and keeps the full 1-65535 that
# services/settings_validators.py::_port_validator allows the settings UI,
# where a human deliberately choosing port 80 for their own machine is their
# call.  Two channels with different callers — do NOT "unify" these ranges.
_PORT_VARS = {
    'PORT': (1024, 65535),
    'RETRODB_PORT': (1, 65535),
}


def saved_server_port():
    """The `server_port` saved in data/settings.json, or None.

    A fallback tier, never a requirement.  Any failure — no settings file, a
    corrupt one, an unreadable one, a value that no longer validates — returns
    None so the server still boots on the default.  The port the environment
    gave us must never depend on the settings file being loadable.

    Imported lazily on purpose: settings_manager imports config, and config
    imports this module, so a module-scope import would be a cycle.  That
    direction-of-dependency is exactly why config.py could never read the
    setting back, and why the fix lives here in the startup path instead.
    """
    try:
        import settings_manager
        from services.settings_validators import validate_settings_value

        raw = settings_manager.get_setting('server_port')
        if raw is None:
            return None
        # Same validator the settings API uses on the way in — 1-65535, see
        # the range note above.  A settings.json edited by hand can still hold
        # something the API would have rejected.
        ok, reason, cleaned = validate_settings_value('server_port', raw)
        if not ok:
            print(f'WARN: ignoring server_port={raw!r} from settings.json '
                  f'({reason}); falling back to {DEFAULT_PORT}.', file=sys.stderr)
            return None
        return cleaned
    except Exception as exc:
        print(f'WARN: could not read server_port from settings.json ({exc}); '
              f'falling back to {DEFAULT_PORT}.', file=sys.stderr)
        return None


def resolve_server_port(default=DEFAULT_PORT, env=None, use_saved=False):
    """Return the port to bind, or raise ValueError naming the bad value.

    Full chain, highest first:

        PORT  ->  RETRODB_PORT  ->  saved `server_port`  ->  default (5000)

    `use_saved` is opt-in because the saved tier reads settings.json, which
    only the startup path may do — config.py calls this at *import*, long
    before the settings layer is safe to touch.  The environment still wins
    over the saved value, so an external process manager is unaffected by
    whatever the Settings page holds.
    """
    env = os.environ if env is None else env

    for name, (low, high) in _PORT_VARS.items():
        raw = env.get(name)
        if raw is None or raw == '':
            continue  # absent -> next source.  Only absence falls through.
        try:
            port = int(raw)
        except ValueError:
            raise ValueError(
                f'{name}={raw!r} is not a valid port number '
                f'(expected an integer between {low} and {high}).') from None
        if not low <= port <= high:
            raise ValueError(
                f'{name}={raw!r} is out of range '
                f'(expected an integer between {low} and {high}).')
        return port

    if use_saved:
        saved = saved_server_port()
        if saved is not None:
            return saved

    return default


def _config_default():
    """config.SERVER_PORT if config.py is importable, else DEFAULT_PORT.

    Only for the command-line path below, whose job is to print a number for a
    shell banner.  A config.py that is missing or broken is app.py's failure to
    report a second later with a real traceback — not this helper's, and not
    worth turning a banner into an error.
    """
    try:
        import config
        return int(config.SERVER_PORT)
    except Exception:
        return DEFAULT_PORT


if __name__ == '__main__':
    # Note: when run this way the module is `__main__`, so config.py's own
    # `from server_port import ...` loads a second, independent copy.  Both are
    # stateless function definitions, so this costs nothing.
    try:
        print(resolve_server_port(default=_config_default(), use_saved=True))
    except ValueError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
