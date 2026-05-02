#!/usr/bin/env python3
"""
RetroDB Installer
Cross-platform setup script that installs dependencies and prepares the application.

Usage:
    python3 install.py              # Full interactive install
    python3 install.py --no-pillow  # Skip optional Pillow install
"""

import os
import shutil
import subprocess
import sys

import installer_core

# ── Colours ──────────────────────────────────────────────────────────────────

_NO_COLOR = os.environ.get('NO_COLOR')

def _c(code, text):
    if _NO_COLOR or not sys.stdout.isatty():
        return text
    return f'\033[{code}m{text}\033[0m'

def _green(t):  return _c('0;32', t)
def _red(t):    return _c('0;31', t)
def _cyan(t):   return _c('0;36', t)
def _yellow(t): return _c('1;33', t)
def _bold(t):   return _c('1', t)


# ── Banner ───────────────────────────────────────────────────────────────────

def _print_banner():
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║  ██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗ ██████╗   ║
║  ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗  ║
║  ██████╔╝█████╗     ██║   ██████╔╝██║   ██║██║  ██║██████╔╝  ║
║  ██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║██║  ██║██╔══██╗  ║
║  ██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██████╔╝  ║
║  ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═════╝   ║
║                                                              ║
║              Retro Gaming ROM Library Manager                ║
║                        INSTALLER                             ║
╚══════════════════════════════════════════════════════════════╝"""
    print(_cyan(banner))
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    skip_pillow = '--no-pillow' in sys.argv
    distro = installer_core.detect_distro()
    errors = []
    warnings = []

    _print_banner()

    print(f"  Platform:  {_bold(installer_core.distro_label(distro))}")
    print(f"  Python:    {_bold(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')}")
    print(f"  Directory: {_bold(base_dir)}")
    print()

    total_steps = 8
    step = 0

    # ── Step 1: Python version ───────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Checking Python version...")
    major, minor = sys.version_info[:2]
    if not installer_core.python_version_ok():
        req_major, req_minor = installer_core.MIN_PYTHON
        print(f"  {_red('ERROR')}: Python {req_major}.{req_minor}+ required, found {major}.{minor}")
        sys.exit(1)
    print(f"  {_green('OK')}: Python {major}.{minor}.{sys.version_info.micro}")

    # ── Step 2: pip ──────────────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Checking pip...")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', '--version'],
            capture_output=True, text=True, check=True
        )
        pip_version = result.stdout.strip().split()[1] if result.stdout else '?'
        print(f"  {_green('OK')}: pip {pip_version}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        hint = installer_core.pip_install_hint(distro)
        print(f"  {_red('ERROR')}: pip is not available")
        print(f"  Install it with:  {_yellow(hint)}")
        sys.exit(1)

    # ── Step 3: Core Python dependencies ─────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Installing core Python dependencies...")
    pip_args, source = installer_core.select_pip_args(base_dir)
    if pip_args is None:
        print(f"  {_red('ERROR')}: neither requirements.lock nor requirements.txt found")
        sys.exit(1)
    if source == 'fallback':
        print(f"  {_yellow('WARN')}: requirements.lock missing — falling back to "
              f"requirements.txt (no hash verification)")
    result = installer_core.pip_install(pip_args, base_dir)
    if result.returncode != 0:
        print(f"  {_red('ERROR')}: pip install failed")
        # Show meaningful error lines (skip pip warnings about PATH)
        for line in result.stderr.splitlines():
            if line.strip() and 'WARNING' not in line:
                print(f"    {line.strip()}")
        errors.append('Core dependencies failed to install')
    else:
        # Verify critical modules
        ok_count = 0
        names = [name for _, name in installer_core.CORE_MODULES]
        for mod, name in installer_core.CORE_MODULES:
            if installer_core.check_module(mod):
                ok_count += 1
            else:
                print(f"  {_red('MISSING')}: {name}")
                errors.append(f'{name} not importable after install')
        print(f"  {_green('OK')}: {ok_count}/{len(names)} core packages verified ({', '.join(names)})")

    # ── Step 4: Optional Pillow ──────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Checking optional dependencies...")
    if skip_pillow:
        print(f"  {_yellow('SKIP')}: Pillow (--no-pillow flag)")
    elif installer_core.check_module('PIL'):
        print(f"  {_green('OK')}: Pillow already installed")
    else:
        print(f"  Installing Pillow (image processing for avatars & image standardization)...")
        result = installer_core.pip_install(['Pillow'], base_dir)
        if result.returncode == 0 and installer_core.check_module('PIL'):
            print(f"  {_green('OK')}: Pillow installed")
        else:
            print(f"  {_yellow('WARN')}: Pillow install failed (optional — avatars/image resize won't work)")
            warnings.append('Pillow not installed (optional)')

    # ── Step 5: Config files ─────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Setting up configuration files...")
    for src_name, dst_name in installer_core.CONFIG_COPIES:
        src = os.path.join(base_dir, src_name)
        dst = os.path.join(base_dir, dst_name)
        if os.path.exists(dst):
            print(f"  {_green('SKIP')}: {dst_name} (already exists)")
        elif os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  {_green('CREATED')}: {dst_name}")
        else:
            print(f"  {_yellow('WARN')}: Template {src_name} not found")

    # ── Step 6: Directories ──────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Creating required directories...")
    created = 0
    for d in installer_core.DIRECTORIES:
        path = os.path.join(base_dir, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            created += 1
    print(f"  {_green('OK')}: {len(installer_core.DIRECTORIES)} directories ready ({created} created)")

    # ── Step 7: Build CSS ────────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Building CSS bundle...")
    css_ok, _ = installer_core.run_build_script(base_dir, 'build_css.py')
    if css_ok is None:
        print(f"  {_yellow('SKIP')}: build_css.py not found")
    elif css_ok:
        print(f"  {_green('OK')}: main.min.css built")
    else:
        css_path = os.path.join(base_dir, 'static', 'css', 'main.min.css')
        if os.path.exists(css_path):
            print(f"  {_yellow('WARN')}: CSS build failed, using existing bundle")
        else:
            print(f"  {_red('ERROR')}: CSS build failed and no existing bundle found")
            errors.append('CSS bundle missing')

    # ── Step 8: Build JS ─────────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Building JS bundle...")
    js_ok, _ = installer_core.run_build_script(base_dir, 'build_js.py')
    if js_ok is None:
        print(f"  {_yellow('SKIP')}: build_js.py not found")
    elif js_ok:
        print(f"  {_green('OK')}: core.bundle.js + games.bundle.js built")
    else:
        # Pass 38.5 — Pass 13 split the single app.bundle.js into core +
        # games. The "use existing bundle" fallback now checks both.
        js_dir = os.path.join(base_dir, 'static', 'js')
        if os.path.exists(os.path.join(js_dir, 'core.bundle.js')) and \
           os.path.exists(os.path.join(js_dir, 'games.bundle.js')):
            print(f"  {_yellow('WARN')}: JS build failed, using existing bundles")
        else:
            print(f"  {_red('ERROR')}: JS build failed and no existing bundles found")
            errors.append('JS bundle missing')

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    if errors:
        print(_red("=" * 58))
        print(_red("  Installation completed with errors"))
        print(_red("=" * 58))
        print()
        for e in errors:
            print(f"  {_red('ERROR')}: {e}")
        print()
        print("  Please fix the errors above and run install.py again.")
        print()
        sys.exit(1)
    else:
        print(_green("=" * 58))
        print(_green("  Installation Complete!"))
        print(_green("=" * 58))

    if warnings:
        print()
        for w in warnings:
            print(f"  {_yellow('NOTE')}: {w}")

    print()
    print(f"  {_bold('Next steps:')}")
    print()
    if sys.platform == 'win32':
        print(f"  1. Start RetroDB:  {_cyan('start.bat')}")
    elif sys.platform == 'darwin':
        print(f"  1. Start RetroDB:  {_cyan('./start.command')}")
    else:
        print(f"  1. Start RetroDB:  {_cyan('./start.sh')}")
    print(f"  2. Open in browser: {_cyan('http://localhost:5000')}")
    print(f"  3. Follow the setup wizard to configure paths and API keys")
    print()
    print(f"  Default login:  {_bold('admin')} / {_bold('admin')}")
    print(f"  (You'll be prompted to change the password on first login)")
    print()


if __name__ == '__main__':
    main()
