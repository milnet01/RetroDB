# =============================================================================
# Pass 40 — Tier-1 indie-review security findings, 40.9–40.16
# =============================================================================
# Regression pins for the 2026-04-24 multi-agent independent review. 40.1–40.8
# live in test_pass40_1_8_security.py, whose header also explains which tests
# are functional and which are kept on purpose as source-pattern invariants.
# =============================================================================

import re

# c-006 DU-1: collapse ~15 inlined `open(mod.__file__).read()` + index-slice
# patterns onto shared helpers so a file rename fails one place, not 15.
from tests._util import REPO_ROOT as _REPO_ROOT, read_module_source, read_source, slice_function  # noqa: E402, F401


# -----------------------------------------------------------------------------
# 40.9 — ImageResizeJob persistence + lock + shutdown recovery
# -----------------------------------------------------------------------------
class TestPass40_9ImageResizeJobBaseConvention:
    """Pin that ImageResizeJob now uses persist_job_start/progress/complete
    and locks every shared-counter access."""

    def test_imports_persist_helpers(self):
        from services.jobs import image_resize as mod
        assert hasattr(mod, 'persist_job_start')
        assert hasattr(mod, 'persist_job_progress')
        assert hasattr(mod, 'persist_job_complete')
        assert hasattr(mod, 'resolve_terminal_status')

    def test_worker_invokes_full_persist_lifecycle(self, tmp_path, monkeypatch):
        """Functional: running the worker against an empty image set (no
        files in IMAGE_PATH) must invoke persist_job_start AND, in the
        finally block, persist_job_complete + resolve_terminal_status.
        Consolidates 4 prior source-grep tests (one per persist call) into
        one behavior pin.

        c-006 F-2 fix: previously polled `job.get_status()` with sleep(0.05)
        × 40.  We now signal a threading.Event from inside the
        `persist_job_complete` stub — the worker's finally calls it AFTER
        `resolve_terminal_status`, so by the time we wake up both lifecycle
        helpers have already fired."""
        import threading
        import config
        from services.jobs import image_resize as mod

        # Point IMAGE_PATH at an empty tmpdir so the worker's file-walk
        # finds nothing and exits early (but the finally block still runs).
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))

        called = {'start': 0, 'progress': 0, 'complete': 0, 'resolve': 0}
        done = threading.Event()

        def _record(name, retval=None):
            def _fn(*a, **kw):
                called[name] += 1
                return retval
            return _fn

        def _record_and_signal(name, retval=None):
            """persist_job_complete runs LAST in the worker's finally (after
            resolve_terminal_status). Signal on it so the test wakes up
            with the full lifecycle already recorded."""
            def _fn(*a, **kw):
                called[name] += 1
                done.set()
                return retval
            return _fn

        monkeypatch.setattr(mod, 'persist_job_start', _record('start', 'fake-id-99'))
        monkeypatch.setattr(mod, 'persist_job_progress', _record('progress'))
        monkeypatch.setattr(mod, 'persist_job_complete',
                            _record_and_signal('complete'))
        monkeypatch.setattr(mod, 'resolve_terminal_status',
                            _record('resolve', 'completed'))

        job = mod.ImageResizeJob()
        job.start(image_types=['boxart'])
        # wait() returns the moment the worker signals, normally within a few
        # ms (the image set is empty). The ceiling only bounds a genuinely
        # stuck worker, so it is generous: a short one failed falsely on a
        # loaded runner. The thread cannot be run synchronously instead —
        # start() holds the job's non-reentrant lock while starting it, and
        # the worker takes the same lock.
        assert done.wait(timeout=30.0), (
            f"worker did not signal completion within 30 s; counts: {called!r}"
        )
        # Join the worker so it cannot outlive this test's monkeypatches.
        job._thread.join(timeout=30.0)
        assert not job._thread.is_alive()
        assert called['start'] >= 1, (
            f"persist_job_start must fire on worker entry (Pass 40.9); "
            f"counts: {called!r}"
        )
        assert called['complete'] >= 1, (
            f"persist_job_complete must fire in finally (Pass 40.9); "
            f"counts: {called!r}"
        )
        assert called['resolve'] >= 1, (
            f"resolve_terminal_status must fire in finally (Pass 40.9); "
            f"counts: {called!r}"
        )

    def test_get_status_takes_lock(self):
        from services.jobs import image_resize as mod
        src = read_module_source(mod)
        idx = src.index('def get_status')
        end = src.index('def _worker', idx)
        body = src[idx:end]
        assert 'with self._lock' in body, \
            'get_status must take self._lock (Pass 40.9)'

    def test_worker_locks_counter_writes(self):
        """Counter writes (self.processed_count += 1, etc.) must be inside
        a `with self._lock:` block."""
        from services.jobs import image_resize as mod
        src = read_module_source(mod)
        idx = src.index('def _worker')
        body = src[idx:]
        # The naked `self.processed_count += 1` shape from before the fix
        # must NOT exist outside a lock block — sample one of them.
        # Easier: verify multiple `with self._lock:` appear in the loop.
        loop_section = body[body.index('for i, item in enumerate'):]
        assert loop_section.count('with self._lock:') >= 2, \
            'worker loop must lock counter accesses (Pass 40.9)'


# -----------------------------------------------------------------------------
# 40.10 — Rate-limit time.sleep blocks shutdown drain
# -----------------------------------------------------------------------------
class TestPass40_10ShutdownAwareSleep:
    """Per-iteration time.sleep(d) in long-running jobs must be replaced
    with shutdown_requested.wait(d) so SIGTERM short-circuits the sleep
    instead of expiring the drain budget."""

    def test_no_bare_time_sleep_in_jobs(self):
        """No services/jobs/{psn_refresh,platform_sync,ra_sync,ra_refresh,
        museum}.py file should call time.sleep — every wait must go through
        the shutdown event so the drain budget is honoured."""
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ('psn_refresh', 'platform_sync', 'ra_sync',
                     'ra_refresh', 'museum'):
            path = os.path.join(repo, 'services', 'jobs', f'{name}.py')
            with open(path, encoding='utf-8') as f:
                src = f.read()
            for i, line in enumerate(src.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if 'time.sleep(' in line:
                    offenders.append(f'{name}.py:{i}: {stripped}')
        assert not offenders, \
            'Pass 40.10: replace with shutdown_requested.wait()\n' + \
            '\n'.join(offenders)

    def test_each_job_imports_shutdown_event(self):
        for name in ('psn_refresh', 'platform_sync', 'ra_sync',
                     'ra_refresh', 'museum'):
            mod = __import__(f'services.jobs.{name}', fromlist=['*'])
            assert hasattr(mod, 'shutdown_requested'), \
                f'{name}.py must import shutdown_requested (Pass 40.10)'


# -----------------------------------------------------------------------------
# 40.11 — CHD conversion non-atomic + dead chd_verify_after_convert
# -----------------------------------------------------------------------------
class TestPass40_11ChdAtomicConversion:
    """chdman output must be written to a tempfile, optionally verified,
    and only os.replace'd to the final path on success.  Otherwise a
    mid-run kill leaves a truncated .chd that chd_skip_existing treats
    as good on the next pass.

    Pass 42.5 — the per-file atomic-write contract moved into the shared
    ``scraper.rom_tools.convert_one_to_chd`` helper; both call sites
    (``CHDConverter._convert_file`` and ``api_chd_converter_convert``)
    delegate to it. The pins below assert (a) the helper itself carries
    the contract and (b) both call sites delegate, instead of grepping
    `_convert_file` / `api_chd_converter_convert` for the literal
    `.chd.part` string."""

    def _convert_one_to_chd_body(self):
        from scraper import rom_tools as mod
        src = read_module_source(mod)
        idx = src.index('def convert_one_to_chd')
        end = src.index('\ndef ', idx + 1)
        return src[idx:end]

    def test_helper_uses_tempfile(self):
        body = self._convert_one_to_chd_body()
        assert '.chd.part' in body, \
            'convert_one_to_chd must write to .chd.part tempfile (Pass 40.11)'
        assert 'os.replace(' in body, \
            'convert_one_to_chd must os.replace tmp → dst (Pass 40.11)'

    def test_helper_runs_verify(self):
        body = self._convert_one_to_chd_body()
        assert 'do_verify' in body, \
            'convert_one_to_chd must accept a do_verify flag (Pass 40.11)'
        assert "'verify'" in body or '"verify"' in body, \
            'convert_one_to_chd must call chdman verify when configured (Pass 40.11)'

    def test_rom_tools_converter_delegates(self):
        from scraper import rom_tools as mod
        src = read_module_source(mod)
        idx = src.index('def _convert_file')
        end = src.index('def _timestamp', idx)
        body = src[idx:end]
        assert 'convert_one_to_chd(' in body, \
            'CHDConverter._convert_file must delegate to convert_one_to_chd (Pass 42.5)'
        assert 'chd_verify_after_convert' in body, \
            'CHDConverter must read chd_verify_after_convert (Pass 40.11 / 42.5)'

    def test_routes_inline_worker_delegates(self):
        from routes import tools as mod
        src = read_module_source(mod)
        idx = src.index('def api_chd_converter_convert')
        end = src.index('def api_chd_verify_scan', idx)
        body = src[idx:end]
        assert 'convert_one_to_chd(' in body, \
            'api_chd_converter_convert must delegate to convert_one_to_chd (Pass 42.5)'
        assert 'chd_verify_after_convert' in body, \
            'inline CHD converter must honor chd_verify_after_convert (Pass 40.11 / 42.5)'


# -----------------------------------------------------------------------------
# 40.12 — Toast-controller XSS on job.system_name
# -----------------------------------------------------------------------------
class TestPass40_12ToastControllerXss:
    """job.system_name was interpolated into toast.innerHTML without
    escape; the inline onclick was migrated to addEventListener.

    The "no inline onclick" half of this contract is now subsumed by
    Pass 45.4's `test_toast_controller_has_no_inline_onclicks` (asserts the
    strictly stronger property: NO inline onclick anywhere in the file).
    Only the system_name escape pin lives here — no other test covers it."""

    def test_system_name_escaped(self):
        src = read_source('static/js/toast-controller.js')
        # The Queued-toast block: subtitle should not raw-interpolate
        # job.system_name — it must go through escapeHtml.
        assert '${job.system_name || \'Multi-System\'}' not in src, \
            'job.system_name must not be raw-interpolated into innerHTML (Pass 40.12)'


# -----------------------------------------------------------------------------
# 40.13 — showModal HTML auto-detect blocklist XSS sink
# -----------------------------------------------------------------------------
class TestPass40_13ShowModalOptInHtml:
    """showModal must default to textContent; opt-in via {allowHtml: true}.
    The old heuristic `message.includes('<') && message.includes('>')`
    was a blocklist that <script>-stripped only — missing <img onerror=>,
    <svg onload=>, etc."""

    def test_no_includes_lt_gt_heuristic(self):
        """The live `if (message.includes('<') && message.includes('>'))`
        branch must be gone.  We strip `// ...` comments before scanning so
        a Pass 40.13 doc-block referencing the old heuristic is allowed."""
        src = read_source('templates/base.html')
        idx = src.index('function showModal(')
        end = src.index('function modalKeyHandler', idx)
        body = src[idx:end]
        # Strip single-line `//` comments so the test sees only live code.
        live = re.sub(r'//[^\n]*', '', body)
        assert "if (message.includes('<') && message.includes('>'))" not in live, \
            'showModal must not auto-detect HTML via the includes() heuristic (Pass 40.13)'

    def test_options_param_with_allowhtml(self):
        src = read_source('templates/base.html')
        idx = src.index('function showModal(')
        end = src.index('function modalKeyHandler', idx)
        body = src[idx:end]
        assert 'allowHtml' in body, \
            'showModal must accept opt-in {allowHtml: true} (Pass 40.13)'


# -----------------------------------------------------------------------------
# 40.14 — PSN trophy-detail game-link search XSS
# -----------------------------------------------------------------------------
class TestPass40_14PsnTrophyDetailXss:
    """Game search results in psn_trophy_detail.html interpolate
    user-authored game.title / game.boxart / game.system into innerHTML
    text + attribute contexts; the old version used a single-quote
    .replace() that didn't protect HTML attribute decoding."""

    def test_inline_onclick_linkgame_removed(self):
        src = read_source('templates/psn_trophy_detail.html')
        # The dangerous inline onclick was:
        #   onclick="linkGame(${game.id}, '${game.title.replace...}', ...)"
        assert "onclick=\"linkGame(${game.id}" not in src, \
            'inline onclick="linkGame(...)" must use addEventListener (Pass 40.14)'

    def test_search_results_use_escape(self):
        src = read_source('templates/psn_trophy_detail.html')
        # The search-results loop must call esc() / escAttr().
        idx = src.index('for (const game of data.results)')
        # bound to the next async function
        end = src.index('async function linkGame', idx)
        body = src[idx:end]
        assert 'esc(game.title)' in body or 'escapeHtml(game.title)' in body, \
            'game.title must be escaped in HTML-text context (Pass 40.14)'
        assert 'escAttr(game.boxart)' in body or 'escapeAttr(game.boxart)' in body, \
            'game.boxart must be escaped in HTML-attribute context (Pass 40.14)'


# -----------------------------------------------------------------------------
# 40.15 — base_scraper.download_image non-atomic + stale-clear race
# -----------------------------------------------------------------------------
class TestPass40_15DownloadImageAtomic:
    """download_image must stream into a tempfile and os.replace; the stale
    media auto-clear must condition the UPDATE on the observed filename."""

    def test_download_image_uses_tempfile_and_replace(self):
        """Check the live-code shape — strip `# ...` comments so a doc
        block referencing the old pattern is allowed."""
        import re
        from scraper import base_scraper as mod
        src = read_module_source(mod)
        idx = src.index('def download_image(')
        end = src.index('def rate_limit', idx)
        body = src[idx:end]
        live = re.sub(r'#[^\n]*', '', body)
        assert 'mkstemp' in live, \
            'download_image must allocate a tempfile (Pass 40.15)'
        assert 'os.replace(' in live, \
            'download_image must os.replace tmp → dest_path (Pass 40.15)'
        assert "open(dest_path, 'wb')" not in live, \
            'download_image must not stream directly to dest_path (Pass 40.15)'

    def test_download_image_atomic_smoke(self, tmp_path, monkeypatch):
        """Functional smoke: a successful download produces a complete
        file at dest_path; no .dl-*.part file is left behind."""
        from scraper import base_scraper as mod
        from services import ssrf as ssrf_mod

        # Bypass the SSRF gate + redirect-walk for the test (these are
        # imported lazily inside the function — patch on the source module).
        # Pass 45.2: validate_and_pin_url calls validate_outbound_url(...,
        # require_https=...) and consumes the third tuple element (resolved
        # IPs) to pin against rebinding, so the stub must accept kwargs and
        # return at least one IP.
        monkeypatch.setattr(ssrf_mod, 'validate_outbound_url',
                            lambda url, **kw: (True, url, ['203.0.113.1']))
        monkeypatch.setattr(ssrf_mod, 'validate_redirect_chain',
                            lambda *a, **kw: ('http://example.test/img.png', None))

        # Stub _http_session.get to return a fake streaming response.
        class _Resp:
            status_code = 200
            headers = {'Content-Length': '12'}

            def iter_content(self, chunk_size):
                yield b'\x89PNG\r\n\x1a\n0123'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Session:
            def get(self, *a, **kw):
                return _Resp()

        monkeypatch.setattr(mod, '_http_session', _Session())

        dest = tmp_path / 'sub' / 'image.png'
        ok = mod.download_image('http://example.test/img.png', str(dest))
        assert ok is True
        assert dest.exists()
        # No leftover tempfile in the same directory.
        leftover = list((tmp_path / 'sub').glob('.dl-*'))
        assert not leftover, f"tempfile not cleaned up: {leftover}"

    def test_stale_clear_binds_observed_filename(self):
        """The hybrid_scraper stale-media UPDATE must include
        `AND {field} = ?` so a concurrent upload between stat and UPDATE
        doesn't get its new reference wiped."""
        from scraper import hybrid_scraper as mod
        src = read_module_source(mod)
        # Search the stale-clear region.
        idx = src.index('Cleared') if 'Cleared' in src else None
        # Get the surrounding ~600 chars for the UPDATE.
        if idx is not None:
            window = src[max(0, idx - 800):idx + 200]
            assert 'AND ' in window and ' = ?' in window, \
                'stale-clear UPDATE must bind observed filename (Pass 40.15)'
        else:
            assert False, 'stale-media block missing (Pass 40.15)'


# -----------------------------------------------------------------------------
# 40.16 — Missing docs/PROXY-DEPLOY.md referenced in app.py:147
# -----------------------------------------------------------------------------
class TestPass40_16ProxyDeployDocs:
    """app.py:147 references docs/PROXY-DEPLOY.md as the trust contract for
    RETRODB_TRUST_PROXY=1 — the file must exist and document the required
    proxy header configuration."""

    def test_doc_exists(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'docs', 'PROXY-DEPLOY.md')
        assert os.path.exists(path), \
            'docs/PROXY-DEPLOY.md must exist (Pass 40.16)'

    def test_doc_covers_required_sections(self):
        body = read_source('docs/PROXY-DEPLOY.md')
        # Must mention every load-bearing header / config knob.
        for needle in (
            'X-Forwarded-For', 'RETRODB_TRUST_PROXY', 'ProxyFix',
            'nginx', 'one hop',
        ):
            assert needle in body, \
                f'PROXY-DEPLOY.md must mention {needle!r} (Pass 40.16)'
