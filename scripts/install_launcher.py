#!/usr/bin/env python3
"""Install the RetroDB taskbar launcher (Linux, XDG desktops).

Copies the icon into ~/.local/share/icons and writes a .desktop file into
~/.local/share/applications with absolute Exec/Icon paths, then refreshes the
desktop database. Run once: `python3 scripts/install_launcher.py`.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Characters that make an Exec argument need quoting (Desktop Entry spec,
# "The Exec key").
_EXEC_RESERVED = set(' \t\n"\'\\><~|&;$*?#()`')


def exec_arg(arg: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec, so an install
    path with a space (~/My Games/RetroDB) is not split into two arguments.
    Inside quotes, `"`, `` ` ``, `$` and `\\` are backslash-escaped; the key
    file's own string escaping then doubles every backslash; `%` is a field
    code prefix and is written `%%`."""
    arg = arg.replace('%', '%%')
    if not any(c in _EXEC_RESERVED for c in arg):
        return arg
    for ch in ('\\', '"', '`', '$'):
        arg = arg.replace(ch, '\\' + ch)
    return '"' + arg.replace('\\', '\\\\') + '"'


def main() -> None:
    if sys.platform != 'linux':
        print('install_launcher.py targets Linux XDG desktops only.', file=sys.stderr)
        sys.exit(1)

    apps = Path.home() / '.local' / 'share' / 'applications'
    icons = Path.home() / '.local' / 'share' / 'icons'
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)

    src_icon = ROOT / 'packaging' / 'icons' / 'retrodb-256.png'
    dst_icon = icons / 'retrodb.png'
    shutil.copyfile(src_icon, dst_icon)

    launcher = ROOT / 'scripts' / 'retrodb_launcher.py'
    exec_line = f'{exec_arg(sys.executable)} {exec_arg(str(launcher))}'

    template = (ROOT / 'packaging' / 'RetroDB.desktop').read_text()
    desktop = template.replace('__EXEC__', exec_line).replace('__ICON__', str(dst_icon))
    dst_desktop = apps / 'RetroDB.desktop'
    dst_desktop.write_text(desktop)
    # No exec bit needed: menu entries under ~/.local/share/applications/ are
    # launched by the menu, not run as files (the +x requirement is only for
    # file-manager / Desktop double-clicks).

    # Best-effort refresh so the entry appears without a re-login.
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(apps)], check=False)

    print(f'Installed launcher: {dst_desktop}')
    print('Find "RetroDB" in your app menu and pin it to the taskbar.')


if __name__ == '__main__':
    main()
