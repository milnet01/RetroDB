"""Progress tracking for a single-game metadata apply (PASS-59-108).

The game page's Apply Metadata runs `apply_hybrid_metadata_to_game` in a
background thread and polls this module for a percentage. The apply reports
its own progress through the module-level helpers below; each is a no-op when
no tracker is active, so the bulk-scrape jobs that share the same code pay
nothing.

Progress is steps done over steps planned. The plan grows as work is
discovered (each media download adds a step), so `percent` is clamped never to
move backwards. A download in flight counts as the fraction of its bytes
received.

The tracker lives in a ContextVar, which a new thread does not inherit: code
that fans work out to a pool must submit through `contextvars.copy_context()`
(see `_download_screenshots_parallel` in scraper/metadata_merger.py).

The same marks drive a per-game step timer (PASS-59-129) that runs with or
without a tracker: `timing_start` / `timing_end` log one line per game saying
how many seconds each step took. See `StepTimer`.

Tasks are in-memory only. A server restart mid-apply loses the task and the
poll answers 404, which the page reports as a failure; this is a one-game
action the user is watching, not a job that needs crash recovery.
"""

import contextvars
import logging
import os
import threading
import time
import uuid

logger = logging.getLogger(__name__)

_current = contextvars.ContextVar('apply_progress', default=None)
_timer = contextvars.ContextVar('apply_timer', default=None)

# Media folder name -> the media kind the page labels ("Downloading video…").
_MEDIA_KINDS = {
    'boxart': 'boxart',
    'boxart_3d': 'boxart_3d',
    'fanart': 'fanart',
    'screenshots': 'screenshot',
    'videos': 'video',
    'manuals': 'manual',
}

# Finished tasks are kept this long for the page's last poll, then dropped.
_KEEP_FINISHED_SECONDS = 600

_tasks = {}
_tasks_lock = threading.Lock()


class ApplyTask:
    """One apply's progress. Every counter is read and written under `_lock`."""

    def __init__(self, game_id):
        self.id = uuid.uuid4().hex
        self.game_id = game_id
        self._lock = threading.Lock()
        self._planned = 0
        self._done = 0
        self._downloads = {}   # key -> [bytes received, bytes expected or 0]
        self._step = {'kind': 'start'}
        self._percent = 0
        self.finished = False
        self.result = None
        self.error = None
        self.finished_at = None
        self.flashed = False

    def plan(self, n):
        with self._lock:
            self._planned += n

    def unplan(self, n):
        """Drop planned steps that will not run (a loop that stopped early)."""
        with self._lock:
            self._planned = max(self._done, self._planned - n)

    def begin(self, kind, **params):
        with self._lock:
            self._step = {'kind': kind, **params}

    def step_done(self):
        with self._lock:
            self._done += 1

    def download_start(self, key, media, total):
        with self._lock:
            self._planned += 1
            self._downloads[key] = [0, total or 0]
            self._step = {'kind': 'download', 'media': media}

    def download_bytes(self, key, received):
        with self._lock:
            if key in self._downloads:
                self._downloads[key][0] = received

    def download_end(self, key):
        with self._lock:
            if self._downloads.pop(key, None) is not None:
                self._done += 1

    def finish(self, result=None, error=None):
        with self._lock:
            self.finished = True
            self.result = result
            self.error = error
            self.finished_at = time.monotonic()
            self._percent = 100

    def snapshot(self):
        with self._lock:
            if not self.finished and self._planned:
                partial = sum(min(got / want, 1.0)
                              for got, want in self._downloads.values() if want)
                pct = int(100 * (self._done + partial) / self._planned)
                # Held at 99 until finish(): the page reloads at 100.
                self._percent = max(self._percent, min(pct, 99))
            return {
                'percent': self._percent,
                'step': dict(self._step),
                'finished': self.finished,
                'applied': bool(self.finished and self.error is None
                                and self.result and self.result.get('success')),
            }


class StepTimer:
    """Seconds per step of one game's scrape.

    Each second counts once, in the innermost step running: a download inside
    the IGDB fallback is media download time, not IGDB time. Pool workers
    (parallel screenshots) overlap the step that waits for them, so their
    downloads and processing are totalled apart.
    """

    def __init__(self, label):
        self.label = label
        self._thread = threading.get_ident()
        self._seconds = {}
        self._stack = ['prepare']   # [top-level step, nested steps...]
        self._workers = {}          # pool-thread seconds, by step
        self._workers_lock = threading.Lock()
        self._start = self._since = time.monotonic()

    def _charge(self):
        now = time.monotonic()
        key = self._stack[-1]
        self._seconds[key] = self._seconds.get(key, 0.0) + now - self._since
        self._since = now

    def _mine(self):
        return threading.get_ident() == self._thread

    def switch(self, name):
        if self._mine():
            self._charge()
            self._stack[0] = name

    def push(self, name):
        if self._mine():
            self._charge()
            self._stack.append(name)

    def pop(self, name, began):
        """End a nested step pushed at `began` (time.monotonic())."""
        if not self._mine():
            with self._workers_lock:
                self._workers[name] = self._workers.get(name, 0.0) + time.monotonic() - began
        elif len(self._stack) > 1:
            self._charge()
            self._stack.pop()

    def line(self):
        self._charge()
        line = (f"Scrape timing, {self.label}: "
                f"{time.monotonic() - self._start:.1f}s total; {_seconds_list(self._seconds)}")
        with self._workers_lock:
            workers = _seconds_list(self._workers)
        return f"{line}; worker threads, overlapping: {workers}" if workers else line


def _seconds_list(seconds):
    return ', '.join(f"{name} {secs:.1f}s" for name, secs in seconds.items() if secs >= 0.05)


def _step_name(kind, params):
    source = params.get('source')
    if kind == 'fetch' and source:
        return f"lead {source}"
    if kind == 'search' and source:
        return f"fallback {source}"
    return 'AI' if kind == 'ai' else kind


def timing_start(label):
    """Start timing one game. Returns False, changing nothing, when a timer
    is already running: the bulk job's timer, which includes the search,
    wins over the apply's own."""
    if _timer.get() is not None:
        return False
    _timer.set(StepTimer(label))
    return True


def timing_end():
    """Log the running timer's line and stop it; a no-op when none runs."""
    timer = _timer.get()
    if timer is not None:
        _timer.set(None)
        logger.info(timer.line())


class timed:
    """Context manager timing a step that makes no progress mark (the bulk
    job's search)."""

    def __init__(self, name):
        self._timer = _timer.get()
        self._name = name

    def __enter__(self):
        if self._timer:
            self._began = time.monotonic()
            self._timer.push(self._name)
        return self

    def __exit__(self, *exc):
        if self._timer:
            self._timer.pop(self._name, self._began)
        return False


def plan(n):
    task = _current.get()
    if task:
        task.plan(n)


def unplan(n):
    task = _current.get()
    if task:
        task.unplan(n)


def begin(kind, **params):
    task = _current.get()
    if task:
        task.begin(kind, **params)
    timer = _timer.get()
    if timer:
        timer.switch(_step_name(kind, params))


def step_done():
    task = _current.get()
    if task:
        task.step_done()
    timer = _timer.get()
    if timer:
        timer.switch('other')


class step:
    """Context manager for one step found mid-run: planned on entry, done on
    exit. Used for each downloaded image's post-processing, which can take
    longer than the download (Real-ESRGAN upscaling)."""

    def __init__(self, kind, **params):
        self._task = _current.get()
        self._timer = _timer.get()
        self._kind = kind
        self._params = params

    def __enter__(self):
        if self._task:
            self._task.plan(1)
            self._task.begin(self._kind, **self._params)
        if self._timer:
            self._name = 'image processing' if self._kind == 'process' else self._kind
            self._began = time.monotonic()
            self._timer.push(self._name)
        return self

    def __exit__(self, *exc):
        if self._task:
            self._task.step_done()
        if self._timer:
            self._timer.pop(self._name, self._began)
        return False


def media_kind(dest_path):
    """Media kind of a download, from the folder it lands in."""
    folder = os.path.basename(os.path.dirname(dest_path or ''))
    return _MEDIA_KINDS.get(folder, 'media')


class download:
    """Context manager around one media download's byte loop.

        with apply_progress.download(dest_path, declared) as dl:
            for chunk in ...:
                written += len(chunk)
                dl.received(written)
    """

    def __init__(self, dest_path, total):
        self._task = _current.get()
        self._timer = _timer.get()
        self._key = object()
        self._dest = dest_path
        self._total = total

    def __enter__(self):
        if self._task:
            self._task.download_start(self._key, media_kind(self._dest), self._total)
        if self._timer:
            self._began = time.monotonic()
            self._timer.push('media download')
        return self

    def received(self, n):
        if self._task:
            self._task.download_bytes(self._key, n)

    def __exit__(self, *exc):
        if self._task:
            self._task.download_end(self._key)
        if self._timer:
            self._timer.pop('media download', self._began)
        return False


def _prune():
    now = time.monotonic()
    with _tasks_lock:
        for tid in [tid for tid, t in _tasks.items()
                    if t.finished and now - t.finished_at > _KEEP_FINISHED_SECONDS]:
            del _tasks[tid]


def start(game_id, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) in a daemon thread under a new tracker.

    Returns the task. fn's return value becomes `task.result`; an exception
    becomes `task.error`.
    """
    _prune()
    task = ApplyTask(game_id)
    with _tasks_lock:
        _tasks[task.id] = task

    def _run():
        _current.set(task)
        try:
            task.finish(result=fn(*args, **kwargs))
        except Exception as e:
            logger.error(f"Apply task {task.id} for game {game_id} failed: {e}",
                         exc_info=True)
            task.finish(error=str(e))

    threading.Thread(target=_run, daemon=True, name=f'apply-{game_id}').start()
    return task


def get(task_id):
    with _tasks_lock:
        return _tasks.get(task_id)
