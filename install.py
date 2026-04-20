#!/usr/bin/env python3
"""
RetroDB Installer
Cross-platform setup script that installs dependencies and prepares the application.

Usage:
    python3 install.py              # Full interactive install
    python3 install.py --no-pillow  # Skip optional Pillow install
"""

import os
import sys
import shutil
import subprocess

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


# ── Distro detection ────────────────────────────────────────────────────────

def _detect_distro():
    """Detect Linux distro family. Returns 'fedora', 'debian', 'arch', or 'unknown'."""
    if sys.platform != 'linux':
        return None
    try:
        with open('/etc/os-release') as f:
            content = f.read().lower()
        # Check ID_LIKE first, then ID
        for line in content.splitlines():
            if line.startswith('id_like=') or line.startswith('id='):
                val = line.split('=', 1)[1].strip('"\'')
                if any(d in val for d in ('fedora', 'rhel', 'centos', 'nobara')):
                    return 'fedora'
                if any(d in val for d in ('debian', 'ubuntu', 'mint', 'pop')):
                    return 'debian'
                if 'arch' in val:
                    return 'arch'
    except FileNotFoundError:
        pass
    return 'unknown'


def _pip_install_hint(distro):
    """Return the right pip install command for the distro."""
    if distro == 'fedora':
        return 'sudo dnf install python3-pip'
    elif distro == 'debian':
        return 'sudo apt install python3-pip'
    elif distro == 'arch':
        return 'sudo pacman -S python-pip'
    elif sys.platform == 'darwin':
        return 'python3 -m ensurepip'
    elif sys.platform == 'win32':
        return 'python -m ensurepip'
    return 'Install pip for your distribution'


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run_pip(args, base_dir=None):
    """Run pip with --break-system-packages fallback."""
    cmd = [sys.executable, '-m', 'pip', 'install'] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    if result.returncode != 0 and 'externally-managed-environment' in result.stderr:
        cmd.append('--break-system-packages')
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    return result


def _check_module(module_name):
    """Check if a Python module is importable."""
    try:
        subprocess.run(
            [sys.executable, '-c', f'import {module_name}'],
            capture_output=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _build_script(base_dir, script_name):
    """Run a build script and return success/failure."""
    script = os.path.join(base_dir, script_name)
    if not os.path.exists(script):
        return None  # not found
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, cwd=base_dir
    )
    return result.returncode == 0


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
    distro = _detect_distro()
    errors = []
    warnings = []

    _print_banner()

    # Platform info
    distro_label = distro or sys.platform
    if distro == 'fedora':
        distro_label = 'Fedora/Nobara/RHEL'
    elif distro == 'debian':
        distro_label = 'Debian/Ubuntu/Mint'
    elif distro == 'arch':
        distro_label = 'Arch Linux'
    elif sys.platform == 'darwin':
        distro_label = 'macOS'
    elif sys.platform == 'win32':
        distro_label = 'Windows'

    print(f"  Platform:  {_bold(distro_label)}")
    print(f"  Python:    {_bold(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')}")
    print(f"  Directory: {_bold(base_dir)}")
    print()

    total_steps = 8
    step = 0

    # ── Step 1: Python version ───────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Checking Python version...")
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 8):
        print(f"  {_red('ERROR')}: Python 3.8+ required, found {major}.{minor}")
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
        hint = _pip_install_hint(distro)
        print(f"  {_red('ERROR')}: pip is not available")
        print(f"  Install it with:  {_yellow(hint)}")
        sys.exit(1)

    # ── Step 3: Core Python dependencies ─────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Installing core Python dependencies...")
    req_path = os.path.join(base_dir, 'requirements.txt')
    if not os.path.exists(req_path):
        print(f"  {_red('ERROR')}: requirements.txt not found")
        sys.exit(1)

    result = _run_pip(['-r', req_path], base_dir)
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
        for mod, name in [('flask', 'Flask'), ('requests', 'Requests'), ('yaml', 'PyYAML'), ('waitress', 'Waitress')]:
            if _check_module(mod):
                ok_count += 1
            else:
                print(f"  {_red('MISSING')}: {name}")
                errors.append(f'{name} not importable after install')
        print(f"  {_green('OK')}: {ok_count}/4 core packages verified (Flask, Requests, PyYAML, Waitress)")

    # ── Step 4: Optional Pillow ──────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Checking optional dependencies...")
    if skip_pillow:
        print(f"  {_yellow('SKIP')}: Pillow (--no-pillow flag)")
    elif _check_module('PIL'):
        print(f"  {_green('OK')}: Pillow already installed")
    else:
        print(f"  Installing Pillow (image processing for avatars & image standardization)...")
        result = _run_pip(['Pillow'], base_dir)
        if result.returncode == 0 and _check_module('PIL'):
            print(f"  {_green('OK')}: Pillow installed")
        else:
            print(f"  {_yellow('WARN')}: Pillow install failed (optional — avatars/image resize won't work)")
            warnings.append('Pillow not installed (optional)')

    # ── Step 5: Config files ─────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Setting up configuration files...")
    config_copies = [
        ('config.example.py', 'config.py'),
        ('data/scraper_settings.example.json', 'data/scraper_settings.json'),
        ('docs/psn-npsso.env.example', 'docs/psn-npsso.env'),
    ]
    for src_name, dst_name in config_copies:
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
    directories = [
        'database',
        'logs',
        'data',
        'static/images/boxart',
        'static/images/boxart_3d',
        'static/images/screenshots',
        'static/images/systems',
        'static/images/ratings',
        'static/images/fanart',
        'static/videos',
        'static/images/manuals',
        'static/images/trophies',
        'static/images/avatars',
        'static/images/hardware',
    ]
    created = 0
    for d in directories:
        path = os.path.join(base_dir, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            created += 1
        else:
            pass  # already exists
    print(f"  {_green('OK')}: {len(directories)} directories ready ({created} created)")

    # ── Step 7: Build CSS ────────────────────────────────────────────────
    step += 1
    print(f"{_bold(f'[{step}/{total_steps}]')} Building CSS bundle...")
    css_ok = _build_script(base_dir, 'build_css.py')
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
    js_ok = _build_script(base_dir, 'build_js.py')
    if js_ok is None:
        print(f"  {_yellow('SKIP')}: build_js.py not found")
    elif js_ok:
        print(f"  {_green('OK')}: app.bundle.js built")
    else:
        js_path = os.path.join(base_dir, 'static', 'js', 'app.bundle.js')
        if os.path.exists(js_path):
            print(f"  {_yellow('WARN')}: JS build failed, using existing bundle")
        else:
            print(f"  {_red('ERROR')}: JS build failed and no existing bundle found")
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
