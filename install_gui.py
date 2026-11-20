#!/usr/bin/env python3
"""
RetroDB Graphical Installer
Tkinter-based setup wizard that installs all dependencies and prepares the app.

Launched by setup.sh (which handles system-level deps like Python and tkinter).
Can also be run directly if Python + tkinter are already installed:
    python3 install_gui.py
"""

import tkinter as tk
from tkinter import messagebox, ttk
import threading
import queue
import os
import sys
import subprocess

import installer_core


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
    'Check image support',
    'Setup configuration files',
    'Create directories',
    'Build CSS bundle',
    'Build JS bundle',
]


# =============================================================================
# HELPERS
# =============================================================================
# Pass 38.3 — distro detection, RetroDB's own Python folder, pip install,
# module probe, and build-script runner live in `installer_core` (shared with
# the CLI install.py). The GUI's `pip_install` always runs in quiet mode.

def pip_install(args, cwd=None, python=None):
    """GUI shim: quiet pip install via the shared installer_core helper."""
    return installer_core.pip_install(args, cwd, quiet=True, python=python)


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
        self.current_step = None
        self.python = sys.executable
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
        distro = installer_core.distro_label(installer_core.detect_distro())
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
            command=self._exit
        )
        self.exit_btn.pack(side='left', padx=8)

    # ── Queue messaging ──────────────────────────────────────────────────

    def _enqueue(self, msg_type, *args):
        self.msg_queue.put((msg_type, *args))

    def _log(self, text, tag=None):
        self._enqueue('log', text, tag)

    def _set_step(self, index, status):
        if status == 'running':
            self.current_step = index
        self._enqueue('step', index, status)

    def _set_progress(self, value):
        self._enqueue('progress', value)

    def _finish(self, success):
        self._enqueue('done', success)

    def _exit(self):
        """Leaving halfway stops pip mid-install, so ask first."""
        if self.installing and not messagebox.askyesno(
                'RetroDB Installer',
                'The install is not finished. Stop it and close the installer?'):
            return
        self.root.quit()

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

        thread = threading.Thread(target=self._run_install_worker, daemon=True)
        thread.start()
        self._poll_queue()

    # ── Install worker (background thread) ───────────────────────────────

    def _run_install_worker(self):
        """Run the worker so an unexpected error (an unwritable config copy or
        directory, say) still reaches the UI. Uncaught, it ended the thread
        before 'done' was queued, and the window sat with Install disabled."""
        try:
            self._install_worker()
        except Exception as e:
            if self.current_step is not None:
                self._set_step(self.current_step, 'failed')
            self._log(f'Installer error: {e}', 'error')
            self._finish(False)

    def _install_worker(self):
        base_dir = self.base_dir
        errors = []
        step = 0

        # ── Step 0: Python version ───────────────────────────────────────
        self._set_step(step, 'running')
        major, minor, micro = sys.version_info[:3]
        self._log(f'Python {major}.{minor}.{micro}')

        if not installer_core.python_version_ok():
            req_major, req_minor = installer_core.MIN_PYTHON
            self._set_step(step, 'failed')
            self._log(f'Python {req_major}.{req_minor}+ required, found {major}.{minor}', 'error')
            self._finish(False)
            return

        self._set_step(step, 'done')
        self._log('  Version OK', 'success')
        step += 1
        self._set_progress(step)

        # ── Step 1: pip ──────────────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Checking pip...')

        python, how, output = installer_core.choose_python(base_dir)
        if how == 'failed':
            self._set_step(step, 'failed')
            self._log("  This system's Python does not allow installing packages,", 'error')
            self._log("  and RetroDB could not make its own Python folder (.venv):", 'error')
            for line in output.splitlines()[-3:]:
                self._log(f'    {line.strip()}', 'error')
            hint = installer_core.venv_install_hint(installer_core.detect_distro())
            self._log(f'  Install it with:  {hint}', 'error')
            self._finish(False)
            return
        self.python = python
        if how == 'venv-created':
            self._log("  Made RetroDB's own Python folder (.venv); the system's Python is left alone", 'success')
        elif how == 'venv':
            self._log("  Using RetroDB's own Python folder (.venv)", 'muted')

        try:
            result = subprocess.run(
                [python, '-m', 'pip', '--version'],
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

        pip_args, source = installer_core.select_pip_args(base_dir)
        if source == 'fallback':
            self._log('  requirements.lock missing — falling back to '
                      'requirements.txt (no hash verification)', 'warning')
        if pip_args is None:
            self._set_step(step, 'failed')
            self._log('  neither requirements.lock nor requirements.txt found', 'error')
            errors.append('Missing requirements file')
        else:
            result = pip_install(pip_args, base_dir, python)
            if result.returncode != 0:
                self._set_step(step, 'failed')
                self._log('  pip install failed', 'error')
                for line in result.stderr.splitlines()[-5:]:
                    if line.strip():
                        self._log(f'    {line.strip()}', 'error')
                errors.append('Core dependencies')
            else:
                ok = 0
                for mod, name in installer_core.CORE_MODULES:
                    if installer_core.check_module(mod, python):
                        ok += 1
                        self._log(f'  \u2713 {name}', 'success')
                    else:
                        self._log(f'  \u2717 {name} — not importable', 'error')
                        errors.append(f'{name} missing')

                if ok == len(installer_core.CORE_MODULES):
                    self._set_step(step, 'done')
                else:
                    self._set_step(step, 'failed')

        step += 1
        self._set_progress(step)

        # ── Step 3: Pillow ───────────────────────────────────────────────
        # Pillow comes with the locked packages above; it is only checked
        # here, never installed on its own, so it is always the checked one.
        self._set_step(step, 'running')
        self._log('Checking Pillow (image processing)...')

        if installer_core.check_module('PIL', python):
            self._log('  \u2713 Pillow installed', 'success')
            self._set_step(step, 'done')
        else:
            self._log('  Pillow is missing (avatars and image resizing limited)', 'warning')
            self._set_step(step, 'warning')

        step += 1
        self._set_progress(step)

        # ── Step 4: Config files ─────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Setting up configuration files...')

        for src_name, dst_name in installer_core.CONFIG_COPIES:
            src = os.path.join(base_dir, src_name)
            dst = os.path.join(base_dir, dst_name)
            if not os.path.exists(src):
                self._log(f'  Template {src_name} not found', 'warning')
            elif installer_core.copy_private(src, dst):
                self._log(f'  \u2713 Created {dst_name}', 'success')
            else:
                self._log(f'  {dst_name} (exists)', 'muted')

        self._set_step(step, 'done')
        step += 1
        self._set_progress(step)

        # ── Step 5: Directories ──────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Creating directories...')

        created = 0
        for d in installer_core.DIRECTORIES:
            path = os.path.join(base_dir, d)
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
                created += 1

        self._log(f'  {len(installer_core.DIRECTORIES)} directories ready ({created} created)', 'success')
        self._set_step(step, 'done')
        step += 1
        self._set_progress(step)

        # ── Step 6: CSS bundle ───────────────────────────────────────────
        self._set_step(step, 'running')
        self._log('Building CSS bundle...')

        css_ok, _css_msg = installer_core.run_build_script(base_dir, 'build_css.py', python)
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

        js_ok, _js_msg = installer_core.run_build_script(base_dir, 'build_js.py', python)
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
        """Start the RetroDB server; it opens the browser itself once it is
        listening, on whatever port it was given."""
        base_dir = self.base_dir
        self.install_btn.configure(state='disabled', bg=TEXT_MUTED, cursor='arrow')
        self._log('')
        self._log('Starting RetroDB server...', 'info')

        os.makedirs(os.path.join(base_dir, 'logs'), exist_ok=True)
        log_path = os.path.join(base_dir, 'logs', 'launch.log')
        env = dict(os.environ, RETRODB_OPEN_BROWSER='1')
        with open(log_path, 'ab') as log:
            proc = subprocess.Popen(
                [self.python, os.path.join(base_dir, 'app.py')],
                cwd=base_dir, env=env, stdout=log, stderr=subprocess.STDOUT)

        def check_started():
            if proc.poll() is None:
                self.root.quit()
                return
            self._log(f'RetroDB stopped while starting. See {log_path}', 'error')
            self._poll_queue()
            self._on_complete(True)

        self.root.after(5000, check_started)

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    app = InstallerApp()
    app.run()
