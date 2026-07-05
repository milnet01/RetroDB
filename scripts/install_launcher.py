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
    exec_line = f'{sys.executable} {launcher}'

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
