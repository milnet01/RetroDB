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


def step_done():
    task = _current.get()
    if task:
        task.step_done()


class step:
    """Context manager for one step found mid-run: planned on entry, done on
    exit. Used for each downloaded image's post-processing, which can take
    longer than the download (Real-ESRGAN upscaling)."""

    def __init__(self, kind, **params):
        self._task = _current.get()
        self._kind = kind
        self._params = params

    def __enter__(self):
        if self._task:
            self._task.plan(1)
            self._task.begin(self._kind, **self._params)
        return self

    def __exit__(self, *exc):
        if self._task:
            self._task.step_done()
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
        self._key = object()
        self._dest = dest_path
        self._total = total

    def __enter__(self):
        if self._task:
            self._task.download_start(self._key, media_kind(self._dest), self._total)
        return self

    def received(self, n):
        if self._task:
            self._task.download_bytes(self._key, n)

    def __exit__(self, *exc):
        if self._task:
            self._task.download_end(self._key)
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
