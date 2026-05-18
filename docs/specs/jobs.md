# Background Jobs Subsystem

> **TL;DR.** Eleven singleton job classes share one `services/jobs/base.py` toolkit:
> a `job_queue` table for crash recovery, an `fcntl.flock`-based cross-process
> singleton, a `self.cancelled` cooperative-cancel flag, and a module-level
> `shutdown_requested` Event for SIGTERM drain. New jobs subclass nothing —
> they reuse the helpers, follow the seven invariants in §13, and add a test
> using the `tests/test_bulk_scrape_job.py` patching stanza.

Cross-references: [`CLAUDE.md`](../../CLAUDE.md) (project-level rules),
[`roadmap.md`](../../roadmap.md) Pass 40.9 / 40.10 / 41.6 / 41.6.D / FU.3,
[`docs/RETRODB_DESIGN_STANDARDS.md`](../RETRODB_DESIGN_STANDARDS.md) §13
(toasts) and §14 (bulk-operation progress UI).

---

## 1. Purpose

RetroDB ships several long-running tasks that don't fit inside a single HTTP
request: bulk metadata scraping for a 700-game system can run for an hour,
PSN trophy refresh has a 2.5 s per-game rate limit, image standardisation
walks 10 000+ files. Each runs in a daemon `threading.Thread` owned by a
process-singleton job object, the object exposes `start / get_status / cancel
/ (pause / resume)`, and an HTTP route layer (`routes/bulk_scrape.py`,
`routes/maintenance.py`, etc.) thin-wraps those methods. The dashboard polls
`get_status()` over JSON; the toast controller renders the response. Crash
recovery is via a `job_queue` row updated every ~10 items so a SIGTERM mid-run
can be resumed (or surfaced) on the next start.

## 2. Inventory

Ten files, eleven singleton classes (`platform_sync.py` hosts two — Steam + Xbox). All live in `services/jobs/`. The singleton instances are at the bottom of [`services/jobs/__init__.py`](../../services/jobs/__init__.py).

| File | Class | Singleton name | What it does |
|------|-------|----------------|--------------|
| `bulk_scrape.py` | `BulkScrapeJob` | `bulk_scrape_job` | Bulk metadata fill / full re-scrape across a system or selection; has a per-process **queue** of follow-on jobs and pause/resume/promote/demote operations. |
| `ra_sync.py` | `RASyncJob` | `ra_sync_job` | Per-user RetroAchievements progress sync — pulls per-game earned/total achievements + points. |
| `ra_refresh.py` | `RARefreshJob` | `ra_refresh_job` | Walks games to discover whether each has a RetroAchievements entry (populates `games.ra_game_id`). |
| `psn_refresh.py` | `PSNRefreshJob` | `psn_refresh_job` | Bulk pull of PSN trophy detail with a 2.5 s rate-limit between games. |
| `museum.py` | `MuseumGenerateJob` | `museum_generate_job` | AI generation of per-system museum content (history / summary / top games). |
| `image_resize.py` | `ImageResizeJob` | `image_resize_job` | Standardises boxart/screenshots/etc. via Real-ESRGAN upscale + Lanczos downscale. |
| `platform_sync.py` | `SteamSyncJob`, `XboxSyncJob` | `steam_sync_job`, `xbox_sync_job` | Per-user Steam / Xbox achievement-progress sync (one file, two classes). |
| `alt_titles_backfill.py` | `AltTitlesBackfillJob` | `alt_titles_backfill_job` | Walks scraped games to refresh `games.alternate_titles` without re-pulling other metadata. |
| `hltb_bulk.py` | `HLTBBulkLookupJob` | `hltb_bulk_job` | Bulk HowLongToBeat lookup — auto-applies high-confidence primary matches, queues the rest into `hltb_pending_matches` for review. |
| `webp_migrate.py` | `WebPMigrateJob` | `webp_migrate_job` | Bulk JPEG/PNG → WebP format migration for boxart / boxart_3d / fanart / screenshots (FU.3, v3.6.19). |

## 3. Lifecycle / states

Two state planes, with distinct vocabularies:

1. **In-memory flags** on the job object: `running`, `paused`, `cancelled`,
   `completed` — all `bool`, all touched only under `self._lock`.
2. **`job_queue.status`** in the DB: one of
   `queued / running / paused / completed / failed / cancelled / interrupted / dismissed`.
   This is the **persistent** view used by the dashboard recovery banner.

> Note: `paused` is an in-memory-only state. There is no `paused` value
> persisted to `job_queue.status` — only `BulkScrapeJob` / `PSNRefreshJob`
> implement pause/resume and they keep the persisted status at `running`
> while paused.

State machine (one job's lifetime):

```
                +-------------+
                |   (idle)    |
                +------+------+
                       |
              start() / persist_queued / persist_start
                       v
              +-----------------+         demote_running
              | queued (in DB)  |<------------------+
              +--------+--------+                   |
                       |                            |
              _start_next_queued / start            |
                       v                            |
                +-------------+        cancel()     |
                |   running   |--------------+      |
                +-+----+----+-+              |      |
        pause()   |    |    |  Exception     |      |
         |        |    |    |     |          |      |
         v        |    |    |     v          |      |
     +--------+   |    |    | +--------+     |      |
     | paused |---+    |    | | failed |     |      |
     +--------+        |    | +--------+     |      |
       resume()        |    |                |      |
                       |    |                v      |
                       |    |          +-----------+|
                       |    |          | cancelled ||
                       |    |          +-----------+|
                       |    |                       |
                       |    +-> normal exit         |
                       v                            |
                 +-----------+    SIGTERM mid-run   |
                 | completed |<----- shutdown ------+
                 +-----------+         |
                                       v
                                 +-------------+
                                 | interrupted |
                                 |  (recoverable)
                                 +------+------+
                                        |
                              dismiss_job() / resume_from_params
                                        v
                                 +-------------+
                                 |  dismissed  |
                                 +-------------+
```

Terminal-state mapping is centralised in
[`services/jobs/base.py:768 resolve_terminal_status`](../../services/jobs/base.py):

- `shutdown_requested.is_set()` → `interrupted` (recoverable next start)
- `self.cancelled` → `cancelled` (final, user-driven, not recoverable)
- otherwise → `completed`

`mark_jobs_interrupted` (called at startup, [`app.py:1589`](../../app.py))
forcibly converts every `running` or `queued` row left over from a previous
process to `interrupted` so the dashboard never shows stale ghosts.

## 4. Persistence model

| State | Lives in | Survives restart? |
|-------|----------|-------------------|
| `self.running` / `self.cancelled` / `self.paused` / counters | Job object in memory | No |
| Queue chain (`BulkScrapeJob._queue`) | In-memory list | No (each queued entry also gets a `job_queue` row with `status='queued'` — those are auto-promoted to `interrupted` at startup) |
| Per-tick progress | `job_queue.progress` (JSON) | Yes — updated every 10 items or 30 s |
| Run history (started/finished, params, error) | `job_queue` row | Yes — until `sweep_old_job_history` prunes it (§10) |
| Cross-process lock | `database/job_locks/<name>.lock` (open FD) | No — released on process exit by the kernel |

The `job_queue` schema (see
[`services/migrations/scripts/001_baseline.py:295`](../../services/migrations/scripts/001_baseline.py)):

```sql
CREATE TABLE job_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type      TEXT NOT NULL,         -- 'bulk_scrape', 'ra_sync', ...
    status        TEXT DEFAULT 'running',
    progress      TEXT,                  -- JSON {current, total, success, failed, skipped, current_item}
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    completed_at  TEXT,
    error_message TEXT,
    params        TEXT                   -- JSON; job-type-specific; MUST include game_ids for resume
);
CREATE INDEX idx_job_queue_status ON job_queue(status);
```

**Why every persist call uses `_retry_on_locked`:** the long-lived
progress connection in a worker can race with the queue-table writes from
HTTP-handler threads. The `_retry_on_locked` helper retries **3×** by
default (4 total attempts) with exponential backoff before raising; the
high-traffic helpers `persist_job_progress` and `_commit_with_retry`
override `max_retries=5`.

## 5. Singleton-lock contract

Two layers guard against two distinct concurrent-start scenarios:

1. **Same-process duplicate** — guarded by `self.running` + the in-job lock
   `self._lock`. `start()` returns `{'success': False}` if already running.
2. **Different-process duplicate** — guarded by an `fcntl.flock(LOCK_EX |
   LOCK_NB)` on `database/job_locks/<job_name>.lock`. This is what stops
   `gunicorn --workers 2` from running the same bulk scrape twice against
   the same DB.

Acquisition lives in
[`services/jobs/base.py:302 acquire_job_singleton_lock`](../../services/jobs/base.py).
The pattern in every job is:

```python
singleton_fd = acquire_job_singleton_lock('bulk_scrape')
if singleton_fd is None:
    return {'success': False, 'error': '... another worker process ...'}
self._singleton_fd = singleton_fd
# ... start the worker thread ...
# In worker's terminal-cleanup branch (success / failure / cancel):
release_singleton_fd(self)          # idempotent
```

Lock-name → DB column-name mapping (used in routes / `request_shutdown`):

| Lock file | Job singleton |
|-----------|---------------|
| `bulk_scrape.lock` | `bulk_scrape_job` |
| `ra_sync.lock` | `ra_sync_job` |
| `ra_refresh.lock` | `ra_refresh_job` |
| `psn_refresh.lock` | `psn_refresh_job` |
| `museum_generate.lock` | `museum_generate_job` |
| `image_resize.lock` | `image_resize_job` |
| `steam_sync.lock` | `steam_sync_job` |
| `xbox_sync.lock` | `xbox_sync_job` |
| `alt_titles_backfill.lock` | `alt_titles_backfill_job` |
| `hltb_bulk.lock` | `hltb_bulk_job` |
| `webp_migrate.lock` | `webp_migrate_job` |

**Degradation notes** (`base.py:316-341`):

- **Windows** — `fcntl` import fails; `acquire_job_singleton_lock` returns
  the sentinel `0` ("acquired, no real lock"). Same-process `self.running`
  becomes the only guard. RetroDB's deployment target is Linux, so this is
  a development-only mode.
- **NFS / flock-unsupported filesystems** — `flock()` raises `OSError`;
  the helper logs a warning and again returns `0`. The `data/` directory
  must be on a local filesystem for the cross-process guard to be real.
- **Sentinel `0`** is intentionally falsy-but-not-None so a caller can
  distinguish "lock denied" (`None`) from "lock unavailable, proceed
  anyway" (`0`). `release_job_singleton_lock` is a no-op on both.

The `release_singleton_fd(self)` helper
([`base.py:361`](../../services/jobs/base.py)) is idempotent — safe to call
from multiple branches of a terminal cleanup without re-releasing.

History: Pass 41.6 landed the helper + `BulkScrapeJob` reference
implementation; Pass 41.6.D rolled it out to nine more job classes. When
`WebPMigrateJob` landed later (FU.3, v3.6.19) it followed the same pattern
from the start, bringing the total to eleven.

## 6. Cancellation semantics

There is **no `cancel_event`**. Cancellation is a `bool` flag on each job
object, read and written only under `self._lock`. The contract a worker
loop must honour:

```python
for i, item in enumerate(items):
    with self._lock:
        if self.cancelled:
            break
        self.current_index = i
    # ... do work ...
    shutdown_requested.wait(rate_limit_seconds)   # NOT time.sleep
```

Three properties this gives you:

1. **Cooperative.** A worker that doesn't check the flag won't be cancelled
   until its current item finishes. Long HTTP calls (RA / PSN APIs use
   `timeout=30`) block cancellation for up to that long.
2. **Shutdown-aware sleeps.** Every per-iteration delay uses
   `shutdown_requested.wait(d)` instead of `time.sleep(d)`. When a SIGTERM
   arrives, the wait returns immediately (Pass 40.10).
3. **Partial work is committed.** A cancel mid-batch keeps everything
   already written. The terminal `resolve_terminal_status` decides the
   final `job_queue.status`:
   - User cancel → `cancelled` (not auto-resumed)
   - SIGTERM during run → `interrupted` (offered on dashboard for resume)

Pause is a separate flag (`self.paused`); the worker's wait loop polls it
under the lock and `time.sleep(0.2)` between polls. `cancel()` clears
`self.paused` so a paused job can exit immediately.

PSNRefreshJob has an extra inner thread (`_fetch_titles`) with its own
`threading.Event` cancel signal — that pattern is the exception, not the
rule, and exists because the outer `fetch_thread.join(timeout=FETCH_TIMEOUT)`
(`FETCH_TIMEOUT = 300` seconds, defined inside the relevant method in
`services/jobs/psn_refresh.py`) can time out — see Pass 41.6 in
`roadmap.md`, sub-item (3) of the original plan ("`_fetch_titles` inner
thread cancel event").

## 7. `processing` field contract

`get_status()` returns **both** `processed` and `processing`:

- `processed = success_count + failed_count + skipped_count` — past tense,
  the count rendered below the progress bar.
- `processing = min(processed + 1, total)` — present tense, 1-indexed,
  capped at total, rendered above the progress bar as the "N / Total"
  counter.

Centralising the `+1`-and-clamp in the backend means the JS doesn't
duplicate it across the toast and modal renderers. See
[`design standards §14`](../RETRODB_DESIGN_STANDARDS.md) for the
two-zone progress layout and the toast detail-line table.

`current_index` is **internal** and not the same as `processing` —
`current_index` is the loop index (used to compute resume offsets),
`processing` is the human "which one am I doing" number.

## 8. Shutdown / recovery

**Graceful shutdown** (`SIGTERM` / `SIGINT`, see
[`base.py:31 request_shutdown`](../../services/jobs/base.py) and
[`app.py:1604`](../../app.py)):

1. Sets the module-level `shutdown_requested` Event — collapses every
   `shutdown_requested.wait(d)` in every worker to ~0 ms.
2. Calls `.cancel()` on each running singleton. The candidate list in
   `services/jobs/base.py::request_shutdown` enumerates:
   `bulk_scrape_job`, `ra_sync_job`, `ra_refresh_job`, `psn_refresh_job`,
   `museum_generate_job`, `image_resize_job`, `steam_sync_job`,
   `xbox_sync_job`, `alt_titles_backfill_job`, `hltb_bulk_job`. **Note:**
   `webp_migrate_job` is intentionally absent today — SIGTERM mid-WebP
   migration leaves the row `running` until `mark_jobs_interrupted` flips
   it on next start, then the user re-runs the job from the top
   (WebPMigrateJob is idempotent; it adopts existing `.webp` siblings on
   restart). If you want SIGTERM to cancel `webp_migrate_job` actively,
   add it to the candidate list.
3. `join(timeout=)` on each worker thread until the total budget
   (default 5 s) expires.

Workers that don't drain in time are killed when the process exits.
Anything not persisted in the last progress-tick window (≤ 10 items or
≤ 30 s) is lost; the `job_queue` row for an in-flight job stays
`running` until the next start.

**Startup recovery** (`app.py:1589`):

1. `mark_jobs_interrupted()` — flips every leftover `running` / `queued`
   row to `interrupted`. Idempotent; safe to run on every start.
2. `sweep_old_job_history()` — deletes terminal rows older than retention
   (§10).
3. The dashboard reads `get_recoverable_jobs()` and offers a banner.
   `BulkScrapeJob` deduplicates by `(system_id, scrape_mode)` and
   auto-dismisses losers (`base.py:606`).
4. User clicks "Resume" → route calls `<job>.resume_from_params(params,
   progress)` which restarts the worker at `progress['current']`. **Seven
   classes implement resume**: `BulkScrapeJob`, `RASyncJob`, `RARefreshJob`,
   `PSNRefreshJob`, `SteamSyncJob`, `XboxSyncJob`, `MuseumGenerateJob`.
   Use the shared `pad_resume_game_ids` / `restore_progress_counts` /
   `try_acquire_singleton_or_warn` helpers in `services/jobs/base.py`
   (search the symbol names; line numbers drift). The remaining four
   singletons (`ImageResizeJob`, `AltTitlesBackfillJob`,
   `HLTBBulkLookupJob`, `WebPMigrateJob`) have no `resume_from_params`
   — they're idempotent and re-run from the top after `interrupted`.

**`params` must include enough to resume.** Most jobs persist the full
`game_ids` list in `params` so resume doesn't have to re-query — this
matters because the underlying query result can change between runs (new
games imported, others deleted) and a partial resume needs to keep the
original ordering for `progress['current']` to be meaningful.

## 9. Toast / progress UI contract

`get_status()` returns a JSON dict. The toast-controller polls and renders
it. The fields and their consumers
([`static/js/toast-controller.js`](../../static/js/toast-controller.js)):

| Field | Type | Producer | Toast consumer |
|-------|------|----------|----------------|
| `running` / `paused` / `completed` / `cancelled` | bool | all jobs | state machine — drives polling cadence + cancel-button visibility |
| `current` / `total` / `percent` | int | all jobs | progress bar fill |
| `processed` / `processing` | int | all jobs (§7) | counter strings above + below the bar |
| `success` / `failed` / `skipped` | int | scrape / sync jobs | result-breakdown line (icons + counts) |
| `current_game` | string | bulk_scrape, ra_*, psn_refresh, hltb_bulk | "currently being processed" line on most job types |
| `current_file` | string | image_resize | same line, file-rather-than-game wording |
| `current_system` | string | ra_refresh, alt_titles_backfill | shown as subtitle on ra-refresh / appended to single-line on image-resize fallback |
| `system_name` | string | bulk_scrape, ra_sync | subtitle / queue-card title; **load-bearing for XSS** (Pass 40.12 — must be escaped at the controller, never trusted) |
| `current_type` | string | image_resize | subtitle line ("boxart" / "screenshots" / ...) |
| `current_npwr` | string | psn_refresh | secondary subtitle showing the NPWR ID being processed |
| `queue` / `queue_count` | list / int | bulk_scrape only | per-card queue rendering with cancel/promote/demote buttons |
| `return_url` | string | bulk_scrape | "Return to library" link when the modal closes |
| `error` / `error_message` | string | all jobs | red toast on failure |

Toast-type detection switches on `data.current_file` (image-resize),
`data.current_npwr` (psn-refresh), `data.system_name` (bulk_scrape /
ra_sync), `data.current_system` (ra-refresh). New jobs should populate at
least one of these so the toast can pick the right detail-line wording —
or extend the dispatch in `toast-controller.js` around lines 1125-1290.

See design standards §14 for the full progress-bar layout and the per-job
detail-line table.

## 10. History sweep

[`base.py:728 sweep_old_job_history`](../../services/jobs/base.py).

- **Setting:** `config.JOB_HISTORY_RETENTION_DAYS` (default 30; environment
  variable `RETRODB_JOB_HISTORY_RETENTION_DAYS`).
- **Disabled:** `<= 0` is a no-op.
- **Run at:** every server start (`app.py:1593`).
- **Sweeps:** `completed`, `failed`, `dismissed`, `cancelled` rows whose
  `completed_at` is older than the retention window.
- **Never sweeps:** `running`, `queued`, `interrupted` — those are active
  states; deleting them would mask a real bug.
- **Doesn't sweep rows with `completed_at IS NULL`** — those predate the
  column being populated; their age can't be inferred safely.

## 11. Authoring a new job

Skeleton — assumes the new job is called `WidgetFooJob` with singleton name
`widget_foo` (lock file `database/job_locks/widget_foo.lock`):

```python
# services/jobs/widget_foo.py
import threading, time, logging
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn,
    persist_job_start, persist_job_progress, persist_job_complete,
    resolve_terminal_status, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)


class WidgetFooJob:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.current_index = 0
        self.total = 0
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.error_message = None

    def get_status(self):
        with self._lock:
            processed = self.success_count + self.failed_count + self.skipped_count
            total = self.total
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'current': self.current_index,
                'processed': processed,
                'processing': min(processed + 1, total) if total else 0,
                'total': total,
                'percent': int(processed / total * 100) if total else 0,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'error': self.error_message,
            }

    def start(self, **params):
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Already running'}
            fd = acquire_job_singleton_lock('widget_foo')
            if fd is None:
                return {'success': False, 'error': 'Already running on another worker process.'}
            self.reset()
            self._singleton_fd = fd
            self.job_id = f"widget_foo_{int(time.time())}"
            self.running = True
        self._thread = threading.Thread(target=self._worker, args=(params,), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running job to cancel'}

    def _worker(self, params):
        persist_id = None
        last_persist = time.time()
        try:
            items = self._load_items(params)
            with self._lock:
                self.total = len(items)
            persist_id = persist_job_start('widget_foo', {**params, 'item_ids': items})

            for i, item in enumerate(items):
                with self._lock:
                    if self.cancelled:
                        break
                    self.current_index = i

                now = time.time()
                if (i % 10 == 0 or now - last_persist >= 30) and i > 0:
                    with self._lock:
                        snapshot = {
                            'current': i, 'total': self.total,
                            'success': self.success_count,
                            'failed': self.failed_count,
                            'skipped': self.skipped_count,
                        }
                    persist_job_progress(persist_id, snapshot)
                    last_persist = now

                try:
                    self._process_one(item)
                    with self._lock:
                        self.success_count += 1
                except Exception as e:
                    logger.warning(f"widget_foo: {item} failed: {e}")
                    with self._lock:
                        self.failed_count += 1

                shutdown_requested.wait(0.0)   # use a non-zero delay if rate-limited

            with self._lock:
                self.completed = True
                self.running = False
                status = resolve_terminal_status(self.cancelled)
            if persist_id:
                persist_job_complete(persist_id, status=status)
        except Exception as e:
            logger.error(f"widget_foo worker error: {e}")
            with self._lock:
                self.completed = True
                self.running = False
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
        finally:
            release_singleton_fd(self)
```

Wire-up checklist:

1. **Register the singleton** in
   [`services/jobs/__init__.py`](../../services/jobs/__init__.py) — import
   the class, instantiate `widget_foo_job = WidgetFooJob()`, add to
   `__all__`.
2. **Add a shutdown candidate** in `base.py:50 request_shutdown` so SIGTERM
   drains it.
3. **Add a route module** under `routes/` exposing `start / status / cancel`
   (look at `routes/maintenance.py` for the simplest pattern, or
   `routes/bulk_scrape.py` for full queue handling).
4. **Add the toast-type wiring** in
   `static/js/toast-controller.js` — extend the `getTypeConfig(type)` switch
   (around line 1063; grep the symbol name to find it) and the detail-line
   dispatch that follows.
5. **(Optional) resume support** — implement `resume_from_params(params,
   progress)`; use `pad_resume_game_ids` + `restore_progress_counts` +
   `try_acquire_singleton_or_warn` from `base.py:382-415` to keep the
   pattern uniform.
6. **Tests** — copy the `tests/test_bulk_scrape_job.py` fixture pattern
   (§12) and pin the state-machine transitions.

Then version-bump + changelog per the workflow in CLAUDE.md.

## 12. Testability

The canonical fixture is in
[`tests/test_bulk_scrape_job.py`](../../tests/test_bulk_scrape_job.py).
The pattern stubs the four things that would otherwise touch live state:

1. `_get_conn` → returns an in-memory sqlite DB seeded with the minimal
   tables the job's `start()` reads.
2. `persist_job_*` and `remove_queued_job` / `persist_job_queued` →
   `return_value=None` (or a sentinel int) so no `job_queue` writes happen.
3. `acquire_job_singleton_lock` → `return_value=0`. Without this, tests
   contend with the running dev server's flock and start() returns
   "already running on another worker". The sentinel `0` makes
   `release_job_singleton_lock(0)` a documented no-op.
4. `_run_scrape` / `_worker` → patched to a no-op `lambda self: None`. The
   state machine can then be exercised without a thread.

Teardown **must** release any `_singleton_fd` the test acquired
(`tests/test_bulk_scrape_job.py:80-88`) — otherwise the file-lock survives
into the next test and breaks it.

Race / shutdown / sweep tests use slightly different shapes:

- [`tests/test_bulk_scrape_race.py`](../../tests/test_bulk_scrape_race.py) —
  real worker thread + controllable stub for testing the cancel→swap race.
- [`tests/test_graceful_shutdown.py`](../../tests/test_graceful_shutdown.py)
  — `_FakeJob` substitute swapped into every singleton slot to test the
  `request_shutdown` fan-out and drain budget.
- [`tests/test_job_history_sweep.py`](../../tests/test_job_history_sweep.py)
  — real file-backed sqlite (the sweep closes its connection in `finally`,
  so `:memory:` would be discarded between assertions).

## 13. Known invariants

These are the contract; new jobs and refactors must keep them all true.

1. **Every read/write of a shared counter is under `self._lock`.** Reading
   without the lock can return torn writes; writing without it loses
   updates. `get_status()` may compute derived fields (e.g. `percent`,
   `processing`) inside the same `with self._lock:` block — the rule is that
   the counters themselves are never read outside the lock, not that the
   computation has to happen after lock release.
2. **Every status persist call (`persist_job_start` / `_progress` /
   `_complete`) happens outside `self._lock`.** Persistence opens its own
   sqlite connection and can take 10-50 ms under WAL contention; holding
   the in-job lock across that blocks status polls — see Pass 41.6 in
   `roadmap.md`, sub-item (2) of the original plan ("move persist_job_progress
   outside the lock block").
3. **Every per-iteration delay uses `shutdown_requested.wait(d)`, not
   `time.sleep(d)`.** Bare sleeps block SIGTERM drain (Pass 40.10).
4. **The terminal status comes from `resolve_terminal_status(self.cancelled)`,
   not a hand-rolled if-else.** This is what distinguishes user-cancel from
   SIGTERM-interrupt for the dashboard recovery banner.
5. **`start()` acquires the cross-process lock; the worker's terminal
   cleanup releases it via `release_singleton_fd(self)`.** Idempotent —
   safe to call from multiple cleanup branches.
6. **The singleton FD is also released on every `start()`-side validation
   failure path** (no API credentials, no items to process, etc.). A
   forgotten release means the next start fails with "already running on
   another worker."
7. **`persist_job_start` is called once per worker run; `persist_job_complete`
   is called once per worker run; both `persist_id` references go through
   the `if persist_id:` guard so an early-exit failure-path doesn't double-
   write.** Pattern: set `persist_id = None` after a failure-path
   `persist_job_complete` so the `finally` block short-circuits (Pass 40.8).
8. **`params` passed to `persist_job_start` must include enough state for
   `resume_from_params` to reconstruct the work.** For game-walking jobs
   that means the full `game_ids` list, not just the system_id — the query
   result can change between runs.
9. **Job-class state-machine transitions are reachable from `start()` and
   `cancel()` only.** Promote / demote / swap reuse `start()`-equivalent
   code paths; ad-hoc state mutation from outside the class is a layering
   violation and will race with the worker.
