#!/usr/bin/env python3
"""
RetroDB Graphical Installer
Tkinter-based setup wizard that installs all dependencies and prepares the app.

Launched by setup.sh (which handles system-level deps like Python and tkinter).
Can also be run directly if Python + tkinter are already installed:
    python3 install_gui.py
"""

import tkinter as tk
from tkinter import ttk
import threading
import queue
import os
import sys
import subprocess
import shutil


# =============================================================================
# THEME COLOURS (matches RetroDB cyberpunk palette)
# =============================================================================

BG          = '#0d1117'
BG_CARD     = '#151b24'
BG_LIGHT    = '#1a222d'
BG_INPUT    = '#0a0e17'
TEXT        = '#e8eaed'
TEXT_SEC    = '#9aa0a6'
TEXT_MUTED  = '#6e7378'
CYAN        = '#4cc9f0'
GREEN       = '#22c55e'
RED         = '#ef4444'
YELLOW      = '#f59e0b'
MAGENTA     = '#f72585'


# =============================================================================
# STEP DEFINITIONS
# =============================================================================

STEPS = [
    'Verify Python version',
    'Check pip availability',
    'Install core dependencies',
    'Install Pillow (optional)',
    'Setup configuration files',
    'Create directories',
    'Build CSS bundle',
    'Build JS bundle',
]


# =============================================================================
# HELPERS
# =============================================================================

def detect_distro():
    """Detect Linux distro family."""
    if sys.platform != 'linux':
        return sys.platform
    try:
        with open('/etc/os-release') as f:
            content = f.read().lower()
        for line in content.splitlines():
            if line.startswith('id_like=') or line.startswith('id='):
                val = line.split('=', 1)[1].strip('"\'')
                if any(d in val for d in ('fedora', 'rhel', 'nobara')):
                    return 'Fedora / Nobara'
                if any(d in val for d in ('debian', 'ubuntu', 'mint', 'pop')):
                    return 'Debian / Ubuntu'
                if 'arch' in val:
                    return 'Arch Linux'
    except FileNotFoundError:
        pass
    if sys.platform == 'darwin':
        return 'macOS'
    return 'Linux'


def pip_install(args, cwd=None):
    """Run pip install with --break-system-packages fallback."""
    cmd = [sys.executable, '-m', 'pip', 'install', '-q'] + args
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0 and 'externally-managed-environment' in result.stderr:
        cmd.append('--break-system-packages')
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result


def check_module(name):
    """Check if a Python module is importable."""
    try:
        subprocess.run(
            [sys.executable, '-c', f'import {name}'],
            capture_output=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_build_script(base_dir, script_name):
    """Run a build script, return (success, stdout)."""
    script = os.path.join(base_dir, script_name)
    if not os.path.exists(script):
        return None, f'{script_name} not found'
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, cwd=base_dir
    )
    return result.returncode == 0, result.stdout or result.stderr


# =============================================================================
# INSTALLER APPLICATION
# =============================================================================

class InstallerApp:

    def __init__(self):
        self.root = tk.Tk()
        self.msg_queue = queue.Queue()
        self.step_icons = []
        self.step_labels = []
        self.installing = False
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self._setup_window()
        self._setup_styles()
        self._build_ui()

    # ── Window setup ─────────────────────────────────────────────────────

    def _setup_window(self):
        self.root.title('RetroDB Installer')
        self.root.configure(bg=BG)
        self.root.geometry('700x660')
        self.root.resizable(False, False)

        # Centre on screen
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'+{x}+{y}')

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            'Cyan.Horizontal.TProgressbar',
            background=CYAN,
            troughcolor=BG_LIGHT,
            borderwidth=0,
            lightcolor=CYAN,
            darkcolor=CYAN,
        )

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        root = self.root
        pad = 28

        # Main container
        main = tk.Frame(root, bg=BG, padx=pad, pady=20)
        main.pack(fill='both', expand=True)

        # ── Title ────────────────────────────────────────────────────────
        tk.Label(
            main, text='RETRODB', font=('Helvetica', 26, 'bold'),
            fg=CYAN, bg=BG
        ).pack(anchor='w')

        tk.Label(
            main, text='Retro Gaming ROM Library Manager',
            font=('Helvetica', 11), fg=TEXT_SEC, bg=BG
        ).pack(anchor='w', pady=(0, 6))

        # ── System info ─────────────────────────────────────────────────
        distro = detect_distro()
        py_ver = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
        info_text = f'Platform: {distro}    |    Python: {py_ver}    |    Path: {self.base_dir}'

        tk.Label(
            main, text=info_text, font=('Helvetica', 9),
            fg=TEXT_MUTED, bg=BG, wraplength=640, justify='left'
        ).pack(anchor='w', pady=(0, 14))

        # ── Separator ───────────────────────────────────────────────────
        tk.Frame(main, bg=BG_LIGHT, height=1).pack(fill='x', pady=(0, 14))

        # ── Steps panel ─────────────────────────────────────────────────
        steps_outer = tk.Frame(main, bg=BG_CARD, bd=0, highlightthickness=1,
                               highlightbackground=BG_LIGHT)
        steps_outer.pack(fill='x', pady=(0, 14))

        tk.Label(
            steps_outer, text='  INSTALLATION STEPS',
            font=('Helvetica', 9, 'bold'), fg=TEXT_MUTED, bg=BG_CARD,
            anchor='w'
        ).pack(fill='x', padx=12, pady=(10, 4))

        steps_inner = tk.Frame(steps_outer, bg=BG_CARD, padx=16, pady=6)
        steps_inner.pack(fill='x')

        for i, step_text in enumerate(STEPS):
            row = tk.Frame(steps_inner, bg=BG_CARD)
            row.pack(fill='x', pady=2)

            icon = tk.Label(
                row, text='\u25cb', font=('Helvetica', 11),
                fg=TEXT_MUTED, bg=BG_CARD, width=2, anchor='center'
            )
            icon.pack(side='left')

            label = tk.Label(
                row, text=step_text, font=('Helvetica', 10),
                fg=TEXT, bg=BG_CARD, anchor='w'
            )
            label.pack(side='left', padx=(4, 0))

            self.step_icons.append(icon)
            self.step_labels.append(label)

        # Bottom padding in steps
        tk.Frame(steps_outer, bg=BG_CARD, height=6).pack()

        # ── Log panel ───────────────────────────────────────────────────
        log_outer = tk.Frame(main, bg=BG_CARD, bd=0, highlightthickness=1,
                             highlightbackground=BG_LIGHT)
        log_outer.pack(fill='both', expand=True, pady=(0, 14))

        tk.Label(
            log_outer, text='  LOG', font=('Helvetica', 9, 'bold'),
            fg=TEXT_MUTED, bg=BG_CARD, anchor='w'
        ).pack(fill='x', padx=12, pady=(10, 4))

        # Text widget with scrollbar
        log_frame = tk.Frame(log_outer, bg=BG_INPUT)
        log_frame.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        scrollbar = tk.Scrollbar(log_frame, bg=BG_LIGHT, troughcolor=BG_INPUT,
                                 activebackground=TEXT_MUTED, bd=0,
                                 highlightthickness=0)
        scrollbar.pack(side='right', fill='y')

        self.log_text = tk.Text(
            log_frame, height=8, font=('Courier', 9),
            bg=BG_INPUT, fg=TEXT, insertbackground=TEXT,
            bd=0, padx=10, pady=8, wrap='word',
            yscrollcommand=scrollbar.set, state='disabled',
            highlightthickness=0, selectbackground=CYAN,
            selectforeground=BG
        )
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.log_text.yview)

        # Log text colour tags
        self.log_text.tag_configure('success', foreground=GREEN)
        self.log_text.tag_configure('error', foreground=RED)
        self.log_text.tag_configure('warning', foreground=YELLOW)
        self.log_text.tag_configure('info', foreground=CYAN)
        self.log_text.tag_configure('muted', foreground=TEXT_MUTED)

        # ── Progress bar ────────────────────────────────────────────────
        self.progress = ttk.Progressbar(
            main, style='Cyan.Horizontal.TProgressbar',
            length=400, mode='determinate', maximum=len(STEPS)
        )
        self.progress.pack(fill='x', pady=(0, 18))

        # ── Buttons ─────────────────────────────────────────────────────
        btn_frame = tk.Frame(main, bg=BG)
        btn_frame.pack()

        self.install_btn = tk.Button(
            btn_frame, text='   Install   ', font=('Helvetica', 12, 'bold'),
            fg=BG, bg=CYAN, activebackground='#3ab8e0', activeforeground=BG,
            bd=0, padx=28, pady=10, cursor='hand2',
            command=self.start_install
        )
        self.install_btn.pack(side='left', padx=8)

        self.exit_btn = tk.Button(
            btn_frame, text='   Exit   ', font=('Helvetica', 12),
            fg=TEXT, bg=BG_LIGHT, activebackground=BG_CARD,
            activeforeground=TEXT, bd=0, padx=28, pady=10, cursor='hand2',
            command=self.root.quit
        )
        self.exit_btn.pack(side='left', padx=8)

    # ── Queue messaging ──────────────────────────────────────────────────

    def _enqueue(self, msg_type, *args):
        self.msg_queue.put((msg_type, *args))

    def _log(self, text, tag=None):
        self._enqueue('log', text, tag)

    def _set_step(self, index, status):
        self._enqueue('step', index, status)

    def _set_progress(self, value):
        self._enqueue('progress', value)

    def _finish(self, success):
        self._enqueue('done', success)

    # ── Queue polling (runs on main thread) ──────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == 'log':
                    _, text, tag = msg
                    self.log_text.configure(state='normal')
                    if tag:
                        self.log_text.insert('end', text + '\n', tag)
                    else:
                        self.log_text.insert('end', text + '\n')
                    self.log_text.see('end')
                    self.log_text.configure(state='disabled')

                elif msg_type == 'step':
                    _, index, status = msg
                    icon_map = {
                        'pending':  ('\u25cb', TEXT_MUTED),   # ○
                        'running':  ('\u25cf', CYAN),          # ●
                        'done':     ('\u2713', GREEN),         # ✓
                        'failed':   ('\u2717', RED),           # ✗
                        'warning':  ('\u26a0', YELLOW),        # ⚠
                    }
                    char, color = icon_map.get(status, ('\u25cb', TEXT_MUTED))
                    self.step_icons[index].configure(text=char, fg=color)

                elif msg_type == 'progress':
                    _, value = msg
                    self.progress['value'] = value

                elif msg_type == 'done':
                    _, success = msg
                    self._on_complete(success)
                    return

        except queue.Empty:
            pass

        self.root.after(80, self._poll_queue)

    # ── Start install ────────────────────────────────────────────────────

    def start_install(self):
        if self.installing:
            return
        self.installing = True

        # Reset UI
        for idx in range(len(STEPS)):
            self._set_step(idx, 'pending')
        self.progress['value'] = 0
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

        self.install_btn.configure(state='disabled', bg=TEXT_MUTED, cursor='arrow')

        thread = threading.Thread(target=self._install_worker, daemon=True)
        thread.start()
        self._poll_queue()

    # ── Install worker (background thread) ───────────────────────────────

    def _install_worker(self):
        base_dir = self.base_dir
        errors = []
        step = 0

        # ── Step 0: Python version ───────────────────────────────────────
        self._set_step(step, 'running')
        major, minor, micro = sys.version_info[:3]
        self._log(f'Python {major}.{minor}.{micro}')

        if major < 3 or (major == 3 and minor < 8):
            self._set_step(step, 'failed')
            self._log(f'Python 3.8+ required, found {major}.{minor}', 'error')
            self._finish(False)
            return

        self._set_step(step, 'done')
        self._log(f'  Version OK', 'success')
        step += 1
        self._set_progress(step)

        # ── Step 1: pip ──────────────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Checking pip...')

        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', '--version'],
                capture_output=True, text=True, check=True
            )
            version_line = result.stdout.strip().split('\n')[0]
            self._log(f'  {version_line}', 'muted')
            self._set_step(step, 'done')
        except (subprocess.CalledProcessError, FileNotFoundError):
            self._set_step(step, 'failed')
            self._log('  pip is not available — cannot install dependencies', 'error')
            self._log('  Run setup.sh to install system packages first', 'error')
            self._finish(False)
            return

        step += 1
        self._set_progress(step)

        # ── Step 2: Core dependencies ────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Installing core dependencies...')

        req_path = os.path.join(base_dir, 'requirements.txt')
        if not os.path.exists(req_path):
            self._set_step(step, 'failed')
            self._log('  requirements.txt not found', 'error')
            errors.append('Missing requirements.txt')
        else:
            result = pip_install(['-r', req_path], base_dir)
            if result.returncode != 0:
                self._set_step(step, 'failed')
                self._log('  pip install failed', 'error')
                for line in result.stderr.splitlines()[-5:]:
                    if line.strip():
                        self._log(f'    {line.strip()}', 'error')
                errors.append('Core dependencies')
            else:
                # Verify each module
                modules = [
                    ('flask', 'Flask'),
                    ('requests', 'Requests'),
                    ('yaml', 'PyYAML'),
                    ('waitress', 'Waitress'),
                ]
                ok = 0
                for mod, name in modules:
                    if check_module(mod):
                        ok += 1
                        self._log(f'  \u2713 {name}', 'success')
                    else:
                        self._log(f'  \u2717 {name} — not importable', 'error')
                        errors.append(f'{name} missing')

                if ok == len(modules):
                    self._set_step(step, 'done')
                else:
                    self._set_step(step, 'failed')

        step += 1
        self._set_progress(step)

        # ── Step 3: Pillow (optional) ────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Checking Pillow (image processing)...')

        if check_module('PIL'):
            self._log('  Already installed', 'success')
            self._set_step(step, 'done')
        else:
            self._log('  Installing Pillow...')
            result = pip_install(['Pillow'], base_dir)
            if result.returncode == 0 and check_module('PIL'):
                self._log('  \u2713 Pillow installed', 'success')
                self._set_step(step, 'done')
            else:
                self._log('  Pillow not available (optional — avatar/image features limited)', 'warning')
                self._set_step(step, 'warning')

        step += 1
        self._set_progress(step)

        # ── Step 4: Config files ─────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Setting up configuration files...')

        config_copies = [
            ('config.example.py', 'config.py'),
            ('data/scraper_settings.example.json', 'data/scraper_settings.json'),
            ('docs/psn-npsso.env.example', 'docs/psn-npsso.env'),
        ]
        for src_name, dst_name in config_copies:
            src = os.path.join(base_dir, src_name)
            dst = os.path.join(base_dir, dst_name)
            if os.path.exists(dst):
                self._log(f'  {dst_name} (exists)', 'muted')
            elif os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                self._log(f'  \u2713 Created {dst_name}', 'success')
            else:
                self._log(f'  Template {src_name} not found', 'warning')

        self._set_step(step, 'done')
        step += 1
        self._set_progress(step)

        # ── Step 5: Directories ──────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Creating directories...')

        directories = [
            'database', 'logs', 'data',
            'static/images/boxart', 'static/images/boxart_3d',
            'static/images/screenshots', 'static/images/systems',
            'static/images/ratings', 'static/images/fanart',
            'static/videos', 'static/images/manuals',
            'static/images/trophies', 'static/images/avatars',
            'static/images/hardware',
        ]
        created = 0
        for d in directories:
            path = os.path.join(base_dir, d)
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
                created += 1

        self._log(f'  {len(directories)} directories ready ({created} created)', 'success')
        self._set_step(step, 'done')
        step += 1
        self._set_progress(step)

        # ── Step 6: CSS bundle ───────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Building CSS bundle...')

        css_ok, _css_msg = run_build_script(base_dir, 'build_css.py')
        if css_ok is None:
            self._log('  build_css.py not found', 'warning')
            self._set_step(step, 'warning')
        elif css_ok:
            self._log('  \u2713 main.min.css built', 'success')
            self._set_step(step, 'done')
        else:
            css_path = os.path.join(base_dir, 'static', 'css', 'main.min.css')
            if os.path.exists(css_path):
                self._log('  Build failed, using existing bundle', 'warning')
                self._set_step(step, 'warning')
            else:
                self._log('  CSS build failed — no bundle available', 'error')
                self._set_step(step, 'failed')
                errors.append('CSS bundle')

        step += 1
        self._set_progress(step)

        # ── Step 7: JS bundle ────────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Building JS bundle...')

        js_ok, _js_msg = run_build_script(base_dir, 'build_js.py')
        if js_ok is None:
            self._log('  build_js.py not found', 'warning')
            self._set_step(step, 'warning')
        elif js_ok:
            self._log('  \u2713 core.bundle.js + games.bundle.js built', 'success')
            self._set_step(step, 'done')
        else:
            # Pass 38.5 — Pass 13 split the single app.bundle.js into core +
            # games. The "use existing bundle" fallback now checks both.
            js_dir = os.path.join(base_dir, 'static', 'js')
            if os.path.exists(os.path.join(js_dir, 'core.bundle.js')) and \
               os.path.exists(os.path.join(js_dir, 'games.bundle.js')):
                self._log('  Build failed, using existing bundles', 'warning')
                self._set_step(step, 'warning')
            else:
                self._log('  JS build failed — no bundles available', 'error')
                self._set_step(step, 'failed')
                errors.append('JS bundle')

        step += 1
        self._set_progress(step)

        # ── Done ─────────────────────────────────────────────────────────
        self._log('')
        if errors:
            self._log(f'Finished with {len(errors)} error(s):', 'error')
            for e in errors:
                self._log(f'  \u2717 {e}', 'error')
        else:
            self._log('All steps completed successfully!', 'success')
            self._log('')
            self._log('Default login:  admin / admin', 'info')
            self._log('(You\'ll be prompted to change the password on first login)', 'muted')

        self._finish(len(errors) == 0)

    # ── Completion callback (main thread) ────────────────────────────────

    def _on_complete(self, success):
        self.installing = False

        if success:
            self.install_btn.configure(
                text='   Launch RetroDB   ',
                state='normal', bg=GREEN, fg=BG,
                activebackground='#1db84e', activeforeground=BG,
                cursor='hand2', command=self._launch
            )
        else:
            self.install_btn.configure(
                text='   Retry   ',
                state='normal', bg=YELLOW, fg=BG,
                activebackground='#e08d0a', activeforeground=BG,
                cursor='hand2', command=self.start_install
            )

    def _launch(self):
        """Start the RetroDB server and open the browser."""
        base_dir = self.base_dir
        app_py = os.path.join(base_dir, 'app.py')

        self._log('')
        self._log('Starting RetroDB server...', 'info')

        # Launch server in background process
        subprocess.Popen(
            [sys.executable, app_py],
            cwd=base_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Open browser after a short delay
        def open_browser():
            import webbrowser
            webbrowser.open('http://localhost:5000')
            self.root.after(1000, self.root.quit)

        self.root.after(2500, open_browser)

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    app = InstallerApp()
    app.run()
