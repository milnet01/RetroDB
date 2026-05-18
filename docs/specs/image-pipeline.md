# Image Pipeline

> Standardization, upscaling, dedup, and cleanup for every image RetroDB
> stores on disk — boxart, 3D boxart, screenshots, fanart, controllers,
> hardware shots, and manuals. Audience: maintainers and Claude Code
> sessions about to touch image handling, debug ESRGAN, or chase a
> WebP / srcset regression.

Cross-references:

- [`scrapers.md`](scrapers.md) — owns the upstream hand-off
  (`base_scraper.download_image` and
  `metadata_merger._download_and_finalize` call into this pipeline once
  the bytes have landed on disk).
- [`jobs.md`](jobs.md) — owns the `ImageResizeJob` background worker
  lifecycle (persistence, cancel, status). This spec describes what the
  per-image work *does*; `jobs.md` describes how the long-running job
  *runs*.

---

## 1. Purpose

The image pipeline takes every byte that lands in `static/images/` and
puts it into a predictable shape: WebP encoding (by default), a target
height of 1080 px for boxart / screenshots / 3D boxart, longest-edge of
1280 px for controllers / hardware shots, and sibling `-sm` / `-md`
variants for boxart that browser `srcset` can pick from. Every write is
atomic, every external URL is run through the SSRF gate, decompression
bombs are rejected before they OOM-kill a worker, and the ESRGAN
upscaler is a lazy GPU-or-CPU singleton that funnels every GPU
inference through one dedicated thread to keep the MIOpen invoker cache
warm.

The pipeline is fill-only in the same sense scrapers are: per-image
work is idempotent, format normalization is a no-op when bytes already
match, variants are regenerated unconditionally so they stay in sync
with the primary, and standardized images that already sit in the
80%–120% target band are skipped.

---

## 2. Data flow

```
    scraper (TGDB / IGDB / RAWG / ScreenScraper / ESDE)
              │
              ▼
   base_scraper.download_image(url, dest_path)
   metadata_merger._download_and_finalize(url, local_path, type)
              │
              │  validate_outbound_url  (SSRF gate, http(s) only)
              │  validate_and_pin_url   (walk redirects through gate,
              │                          capture IP for pinning)
              │
              ▼
   pin_host_ip(host, ip)  ──► requests.get(stream=True,
                                           allow_redirects=False)
              │
              │   iter_content(8192) → mkstemp(prefix='.dl-',
              │                                suffix='.part', dir=dest_dir)
              │   fsync(tempfd)
              │
              ▼
   os.replace(tmp, dest_path)              # atomic finalize
              │
              ▼
   finalize_downloaded_image(dest_path, image_type)
       1. _ensure_format_matches_extension       # WebP ⇄ JPEG ⇄ PNG
       2. standardize_downloaded_image            # ESRGAN ↑ / Lanczos ↓
       3. _make_responsive_variants               # boxart -sm / -md
              │
              ▼
   apply_*_to_game(...) UPDATE games SET <field> = COALESCE(?, <field>)
              │
              ▼
   later: find_orphaned_media + clean_orphaned_files
          (admin-triggered via /api/orphaned-media/{preview,clean})
```

Stale-DB-reference clearing happens *before* this flow on each scrape —
see §9.

---

## 3. Image formats

**Accepted input formats** (`save_upload` / scraper download): JPEG,
PNG, GIF, WebP. Extension allow-list lives in
`services/game_media_service.py` (`ALLOWED_IMAGE_EXT`). Magic bytes are
validated with Pillow's `Image.verify()` so a `.exe` renamed to `.jpg`
fails at intake.

**On-disk default**: WebP, controlled by
`config.IMAGE_FORMAT` (env override `RETRODB_IMAGE_FORMAT=webp|jpeg`,
default `webp`). `preferred_image_extension()` decides the target ext
on ingest:

| input ext | image_type        | IMAGE_FORMAT=webp | IMAGE_FORMAT=jpeg |
|-----------|-------------------|-------------------|-------------------|
| `.jpg`    | boxart            | `.webp`           | `.jpg`            |
| `.png`    | boxart            | `.webp`           | `.jpg`            |
| `.gif`    | boxart            | `.gif` (preserve) | `.gif` (preserve) |

The table above lists the **convertible image types** only. Non-convertible
types — anything whose `image_type` is not in `_CONVERTIBLE_TYPES = {boxart,
boxart_3d, screenshots, fanart, controllers, hardware}` — bypass
`preferred_image_extension()` entirely and keep their original extension
regardless of `IMAGE_FORMAT`. That covers videos (`.mp4`), manuals (`.pdf`),
and anything else the function isn't asked to decide about. Don't add new
extension rows to the table for non-image types — wire the new `image_type`
into `_CONVERTIBLE_TYPES` if it should be re-encoded, otherwise leave it out.

GIFs are never re-encoded — `img.save(path, 'GIF')` without `save_all`
flattens animated GIFs to the first frame, so the only safe path is
passthrough.

**Pass 45.6 — `MAX_IMAGE_PIXELS` cap.** Pillow's
`Image.MAX_IMAGE_PIXELS` is set at module import in both
`services/image_utils.py` and `services/game_media_service.py` (default
64 MP, override via `config.IMAGE_MAX_PIXELS`). A 1 MB malicious PNG
can advertise dimensions that decode to 4 GB+ of pixel data; without
the cap, that OOM-kills the worker before any of the post-download
logic runs. Above the cap, Pillow raises `Image.DecompressionBombError`
and every `Image.open(...)` call site catches it explicitly so the file
is rejected with a distinct warning line (admin sees the bomb attempt
in the security log rather than a generic "format normalize failed").

**Pass 41.14.A** added the same cap to `compute_dhash` in
`scraper/image_dedup.py` — without it, one bomb image inside a
screenshot batch aborted the whole dedup loop for the game being
scraped.

`app.py:22` sets a stricter 25 MP cap before any other Pillow call sites.
`Image.MAX_IMAGE_PIXELS` is a process-global singleton (the last assignment
wins), so the effective cap at any moment depends on import order: once
`services/image_utils.py` has been imported anywhere in the process, the 64 MP
cap is live everywhere. In practice the pipeline modules load lazily inside
`scraper/` and `services/jobs/`, so the 25 MP cap holds for the first few
requests and the 64 MP cap holds once the image pipeline is warm. If you need
a single source of truth, set `config.IMAGE_MAX_PIXELS` and reference it from
both modules instead of relying on import-order convergence.

---

## 4. Atomic finalize

Two paths write images, and both go through tempfile + fsync +
`os.replace`:

**`base_scraper.download_image`** (Pass 40.15) — streams the HTTP body
to `mkstemp(prefix='.dl-', suffix='.part', dir=dest_dir)`, calls
`os.fsync` on the file descriptor, then `os.replace(tmp, dest_path)`.
The previous version streamed `open(dest_path, 'wb')` directly: any
mid-stream exception (connection reset, OOM, SIGKILL) left a partial
file at `dest_path`, and the `if os.path.exists(dest_path): return
True` short-circuit at the top of the function then treated those
corrupt bytes as "already downloaded" forever.

**`_atomic_save` in `services/image_utils.py`** (Pass 32.9 / 45.5) —
wraps Pillow's `img.save(...)` with the same scaffold:
`mkstemp(prefix='.save_', dir=dirname)` → `img.save(tmp, fmt, **kw)` →
explicit `os.fsync` on the temp file (Pillow's `img.save` closes the
fd but doesn't fsync) → `os.replace(tmp, path)` → fsync the parent
directory via `services.atomic_io.fsync_path` so the rename is durable
on XFS or `nobarrier` mounts. Any exception unlinks the tempfile so the
directory doesn't accumulate `.save_*` debris.

**`_atomic_write_bytes`** (uploads) delegates to
`services.atomic_io.atomic_write_bytes` for the shared atomic-write
sequence (fsync + chmod-before-replace + parent fsync).

Every external download finishes with `finalize_downloaded_image(path,
image_type)` which is best-effort: each of its three steps catches and
logs its own errors so a finalize failure never fails the download
(Pass 32.10).

---

## 5. ESRGAN upscaling

**Model**: Real-ESRGAN x4plus (4× upscale), ONNX format, served by
`onnxruntime`.

**Path**:
`~/.cache/realesrgan/<REALESRGAN_MODEL_NAME>.onnx` (default
`RealESRGAN_x4plus.onnx`). First-run download via `_download_model`.

**Download source**: `REALESRGAN_MODEL_URL` (default
`https://huggingface.co/Xenova/realesrgan-x4plus/resolve/main/model.onnx`).
`_MODEL_URLS` carries a hardcoded fallback list (HuggingFace mirrors).
Pass 41.14.B routes every URL through
`services.ssrf.validate_outbound_url(require_https=True)`; Pass 45.2
also pins the IP via `validate_and_pin_url` + `pin_host_ip` so DNS
rebinding between validate and GET can't redirect the connect.

**Dispatch**:

| EP                    | Hardware         | Notes                                            |
|-----------------------|------------------|--------------------------------------------------|
| CUDAExecutionProvider | NVIDIA           | preferred when present                           |
| ROCMExecutionProvider | AMD (gfx10xx)    | gated on `/dev/kfd` being R/W (`render` group)   |
| CPUExecutionProvider  | any              | unconditional fallback                           |

`onnxruntime-rocm` will `abort()` the process if it can't open
`/dev/kfd`, so the upscaler pre-checks `os.access('/dev/kfd', R|W)`
before adding `ROCMExecutionProvider` to the provider list. ROCm env
vars (`HSA_OVERRIDE_GFX_VERSION`, `MIOPEN_FIND_MODE`,
`MIOPEN_USER_DB_PATH`, `MIOPEN_CUSTOM_CACHE_DIR`) are set in `app.py`
**before** any ROCm library loads — they cannot move into the upscaler
module without breaking dispatch (Python import order matters here).

**MIOpen dedicated-thread trick**: MIOpen's compiled-kernel invoker
cache is per-handle, ORT allocates a handle per thread, and a different
thread running inference gets an empty cache → *"No invoker was
registered for convolution forward"*. The upscaler funnels every GPU
`session.run()` through a single `_gpu_inference_worker` thread fed by
`_gpu_queue`. Warm-up (a dummy inference at init) populates the
invoker cache on the same thread that serves all future requests.

**Tile budget**: CPU caps at 100 tiles (~40 s); GPU caps at 1024 tiles
(~51 s). Above the cap, `enhance()` returns `(None, None)` and the
caller falls back to Lanczos so a bulk job of 10 000 boxart can't stall
for hours on a single 8k screenshot.

**Tile size** auto-detects from the model's expected input shape — some
ONNX variants have fixed 64×64 input dims, others accept dynamic
shapes. Default `REALESRGAN_TILE_SIZE=256`; padding mode reflect-pads
the source so dimensions divide evenly.

**Singleton lifecycle**: `_get_upscaler()` is lazy, double-checked
under `_upscaler_lock`. A GPU inference failure trips a one-way circuit
breaker (`_gpu_failed = True`), tears down the GPU thread, and rebuilds
the session as CPU-only — every subsequent upscale stays on CPU for the
process lifetime. This is intentional: a wedged ROCm session can fail
in obscure ways and CPU is the known-good baseline.

---

## 6. Lanczos downscaling

`_downscale_image()` is the do-the-resize-now helper. Used for:

- Downscale path of `standardize_image` (image is above 120% of target).
- Final exact-size resize after ESRGAN (ESRGAN always upscales 4×;
  Lanczos brings the result to the exact target height).
- Generating `-sm` / `-md` variants for boxart (§7).
- Fallback when ESRGAN is unavailable or above the tile budget.

Aspect ratio is preserved: for height-based types (boxart, screenshots,
boxart_3d) the target is the desired *height* and width scales
proportionally; for longest-edge types (controllers, hardware) the
target is the desired longest edge and the other dimension scales.

Quality settings (`_save_image`):

| ext       | Pillow format | params                                |
|-----------|---------------|---------------------------------------|
| `.webp`   | `WEBP`        | `quality=85`, `lossless=False`        |
| `.jpg/.jpeg` | `JPEG`     | `quality=90`; RGBA flattened to RGB   |
| `.png`    | `PNG`         | default                               |
| `.gif`    | (no-op)       | passthrough — see §3                  |
| unknown   | `PNG`         | conservative fallback                 |

---

## 7. WebP variant generation (`-md` srcset)

`_make_responsive_variants(path, image_type)` writes sibling files at
fixed widths so browsers can `srcset`-pick the smallest variant that
satisfies the rendered width:

| image_type   | variants                          |
|--------------|-----------------------------------|
| `boxart`     | `<base>-sm.webp` (160w), `-md.webp` (320w) |
| `boxart_3d`  | `<base>-sm.webp` (160w), `-md.webp` (320w) |
| anything else | (no variants — Lanczos+srcset wins are smallest on boxart) |

Filename convention: `_variant_path(original, 'sm')` for `12_tgdb.webp`
yields `12_tgdb-sm.webp` (same dir, same ext). Variants are skipped
when the source is already narrower than the target (no upscaling the
variant unnecessarily).

**Template wiring**: `boxart_srcset(filename)` builds the `srcset=`
string for the detail-page hero `<img>`. It probes each variant on disk
and emits only those that exist, then appends the original with a
conservative width descriptor (PIL-read width if cheap, else 760 px as
a 7:10 ratio upper bound for a 1080-tall standardized boxart). Missing
original → empty string, so templates can `{% if srcset %}` cleanly.

Pass 18.3 wired this into the detail-page hero. **FU.2 (v3.6.18)
extended it to the card grid.** The grid path uses a request-scoped batch
existence cache to avoid 500-cards × per-card `stat`:
`services/image_utils.py::boxart_dir_listing()` memoizes a single
`os.scandir()` per request against `flask.g`, and
`boxart_srcset(filename, existing=…)` skips the PIL width-read in batch
mode (falls back to a 760 px width descriptor).
`services/game_metadata_service.py::build_game_card()` emits
`boxart_srcset` + `boxart_3d_srcset` on every card payload, and the
front-end's `renderGameCard()` consumes them — clearing `srcset` and
`sizes` in the 3D → 2D `onerror` fallback so the swap renders cleanly.

Variants are regenerated unconditionally on each finalize call (and
after every `ImageResizeJob` write) so they never drift from the
primary. **FU.3 (v3.6.19)** landed the bulk JPEG/PNG → WebP migration
endpoint — see §12.1 below for the contract.

---

## 8. Perceptual dedup (`compute_dhash`)

`scraper/image_dedup.py::compute_dhash(path, hash_size=8)` returns a
64-bit difference hash: open image, convert to greyscale, resize to
`(hash_size+1, hash_size)` with Lanczos, compare adjacent pixels along
each row to produce a bit per pair.

**Hamming distance bands** (empirically observed across TGDB / IGDB /
RAWG / ScreenScraper):

- 0–3: identical (re-encode / resize only)
- 10–20: similar but different
- 25+: unrelated

`is_visual_duplicate(new_path, existing_hashes, threshold=10)` flags
matches at distance ≤ 10. Used by every scraper screenshot path
(`keep_screenshot_if_unique` deletes the file and returns False on
match) so the same screenshot scraped from multiple sources isn't
appended twice.

The exception catch is `(OSError, ValueError,
Image.DecompressionBombError)` (Pass 41.14.A —
`DecompressionBombError` is a sibling of OSError/ValueError, not a
subclass, and was leaking through to abort the whole-game dedup loop on
a single bomb image).

---

## 9. Stale DB-reference cleanup (pre-populate)

`hybrid_scraper.py:765-823` runs before every scrape to harmonise the
DB with disk. For each media field (`boxart`, `boxart_3d`, `fanart`,
`manual`, `video`, `screenshots`):

1. Stat the file under its expected directory.
2. If missing, clear the value in the local `metadata` dict.
3. Record `(field, stale_filename)` in `stale_media`.

After the per-field loop, issue one `UPDATE games SET <field> = NULL
WHERE id = ? AND <field> = ?` per stale row — Pass 40.15's conditional
WHERE guards against a concurrent upload that may have replaced the
value between the stat and the UPDATE (without it, the new reference
gets NULL'd and the just-uploaded file becomes an orphan that the
media-cleanup sweep then deletes).

This is the contract behind CLAUDE.md "Media handling — during pre-
population, media files are validated on disk … stale DB references
… are auto-cleared so scrapers can re-download." The scraper-side
fill-only invariant (`apply_*_to_game` wraps every `?` in
`COALESCE(?, column_name)`) preserves the cleared `NULL`s by letting
the new scrape value land instead of restoring the stale string.

---

## 10. Orphan cleanup (admin-triggered)

`services/media_cleanup.py` does *not* run on a schedule. It runs only
from the maintenance routes (`routes/maintenance.py`):

- `GET /api/orphaned-media/preview` → `find_orphaned_media(games)`
  returns the candidate list + total size for the admin UI to confirm.
- `POST /api/orphaned-media/clean` → re-scans (defence against the
  preview being stale) and calls `clean_orphaned_files(candidates)`.

A file is "orphaned" when both: (a) its `<game_id>_` filename prefix
doesn't match any live game ID, and (b) the bare filename isn't
referenced by any games-row media column.

**Pass 45.7 race fix**: each candidate carries `mtime` and
`scan_started_at`. At delete time, `clean_orphaned_files` re-checks:

1. File still exists (a peer cleaner / user delete may have removed it).
2. Still not a symlink (defence in depth).
3. `stat.st_mtime <= scan_started_at` — a scraper that wrote to
   `42_boxart.webp` between scan and clean bumps the mtime; the file
   may now belong to a game-row inserted after the scan started, so we
   skip it.

Skipped files are logged at info so admins see the cleaner deferred
work rather than silently doing nothing.

---

## 11. `rglob` symlink risk (Pass 41.14.C)

`Path.rglob()` follows symlinks on Python 3.12 (default changed in
3.13). A symlink to `/` placed inside `ROM_PATH` would enumerate the
entire filesystem — same shape of bug applies to media directories,
though the orphan cleaner takes the `os.listdir` route (one level) so
the rglob risk is concentrated in `scraper/rom_tools.py`.

**Safe pattern** (used at every ROM_PATH-walk site in
`scraper/rom_tools.py` — `grep -n "rglob" scraper/rom_tools.py` to enumerate;
each is guarded by `_safe_under_root(p, root_resolved)`, defined near the
top of the module):

```python
root = pathlib.Path(ROM_PATH).resolve()

def _safe_under_root(p, root_resolved):
    try:
        return p.resolve().is_relative_to(root_resolved)
    except (OSError, ValueError):
        return False

for path in root.rglob(f"*{ext}"):
    if not _safe_under_root(path, root):
        continue
    ...
```

Apply this same guard to any new code that walks media directories
recursively — `os.listdir` over a single level is symlink-safe in the
sense that `os.path.islink` filters cleanly, but `rglob` is not.

`find_orphaned_media` also skips symlinks at scan time
(`os.path.islink` check) and `clean_orphaned_files` re-checks at delete
time so a symlink that appears between scan and clean can never have
its target unlinked.

---

## 12. Image-resize job

`services/jobs/image_resize.py::ImageResizeJob` is the bulk standardize
endpoint — admin trigger walks every file under
`static/images/{boxart,screenshots,boxart_3d,controllers,hardware}` and
runs `_standardize_with_tracking` on each.

Per-job behaviour and persistence contract live in [`jobs.md`](jobs.md)
— `ImageResizeJob` follows the `services/jobs/base.py` convention as of
Pass 40.9: `persist_job_start` before the loop,
`persist_job_progress` every 10 items or 30 s, `persist_job_complete`
in `finally`, every shared-counter read/write under `self._lock`,
`acquire_job_singleton_lock` so two workers can't race the same files.

For the *image* side: `_standardize_with_tracking` mirrors the
single-shot `standardize_image` flow (decode in context manager → copy
pixels → close source → upscale/downscale/skip → atomic save) and adds
result tracking (`'skipped'` / `'upscaled'` / `'downscaled'`). After
each save it regenerates the responsive variants so cards pick up the
new primary on the next page load.

The job does **not** convert `.jpg` / `.png` to `.webp` — extensions
are preserved. For format migration, use `WebPMigrateJob` (§12.1).

**Failure handling.** Per-file exceptions raised inside
`_standardize_with_tracking` are caught, logged at WARNING (with the
filename), and the loop continues; the offending file is bucketed as
`'failed'` and surfaces in the job-status snapshot via `failed_count`
alongside `skipped` / `upscaled` / `downscaled`. The job only aborts
early on cancel, pause, or shutdown — never on a single bad file.

### 12.1 `WebPMigrateJob` (FU.3, v3.6.19)

`services/jobs/webp_migrate.py::WebPMigrateJob` (singleton
`webp_migrate_job`). REST surface:
`POST /api/maintenance/convert-to-webp/{start,status,cancel}` in
`routes/maintenance.py`.

- **Worklist:** the `_SOURCES` tuple at `services/jobs/webp_migrate.py:34-39`
  enumerates four columns — `boxart`, `boxart_3d`, `fanart`, `screenshots`
  (with `is_csv=True` for the last one). Manuals are out of scope by
  omission, not by skip-branch (the `manual` column is simply not in
  `_SOURCES`). The per-file filter is the allowlist
  `_CONVERTIBLE_EXTS = {'.jpg', '.jpeg', '.png'}`
  (`webp_migrate.py:44`); anything else — `.gif`, `.webp`, `.bmp`, etc. —
  is left untouched (`.gif` because Pillow's animated-WebP output is lossy;
  others because they're too rare to handle without per-format edge-case
  coverage).
- **Per-file order:** PIL save to a `.webp` sibling → integrity-verify
  the new file (open + `verify()`) → DB `UPDATE` to the new filename →
  unlink the original. If verify fails the partial `.webp` is removed
  and the original is left untouched; the file is bucketed as failed.
- **Disk-space precheck:** runs inside `_run()` after the worker thread
  has spun (so `start()` itself returns immediately with `success: True`).
  The precheck sums the byte size of every in-scope file
  (`in_scope_bytes`). If `free < 2 × in_scope_bytes` the job logs a
  human-readable error, transitions to `failed`, and surfaces the reason
  via `get_status()` — WebP is usually smaller, but the 2× floor covers
  the transient "old + new both on disk" window per file.
- **Resume:** the job adopts an existing `.webp` sibling if it appears
  intact (open + `verify()`); the original is unlinked, the DB row
  updated, and the file counted as already-migrated.
- **Responsive variants:** after each successful conversion, the legacy
  `-sm.jpg` / `-md.png` siblings are wiped and `_make_responsive_variants`
  re-runs against the new primary so srcset stays consistent.
- **Lock:** `database/job_locks/webp_migrate.lock` (singleton, same
  pattern as Pass 41.6.A).

---

## 13. AMD ROCm / onnxruntime trap

Per-machine pitfall on AMD GPU dev boxes that lands ESRGAN in CPU mode
when it should be on GPU. Two stacked upstream bugs.

**Symptom**: server startup log shows
`Real-ESRGAN ONNX loaded (CPU mode, ...)` when ROCm was expected.

**Cause 1 — CPU-wheel shadow**: `requirements.txt` carries
`onnxruntime>=1.25.1,<2.0`. Pip resolves that against the
PyPI default (CPU-only `onnxruntime`), installs it alongside
`onnxruntime-rocm` into the *same* `onnxruntime/` package directory,
and last-installer-wins overwrites the ROCm `.so` files. Result:
`onnxruntime.get_available_providers()` no longer lists
`ROCMExecutionProvider`.

**Cause 2 — exec-stack flag**: AMD's `onnxruntime-rocm 1.22.2.post1`
wheel ships `onnxruntime_pybind11_state.so` and
`libonnxruntime.so.1.22.2` with `PT_GNU_STACK = RWE` — the binary was
linked without `-z noexecstack`. glibc 2.41+ refuses to honour
`RWE` and aborts `import onnxruntime` with
`cannot enable executable stack as shared object requires: Invalid
argument`. The flag is purely declarative — onnxruntime never actually
needs an executable stack at runtime — but the loader doesn't know
that.

**Fix sequence** (worked example, AMD RX 6600-series dev box):

```bash
# 1. Drop the CPU shadow that overwrote ROCm files
pip uninstall -y onnxruntime --break-system-packages

# 2. Force-reinstall the ROCm wheel without pulling deps that would
#    re-shadow it
pip install --force-reinstall --no-deps onnxruntime-rocm \
    --break-system-packages

# 3. Clear PF_X from PT_GNU_STACK in the two affected .so files
python3 scripts/fix_onnxruntime_rocm_execstack.py

# 4. Verify
python3 -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Expected: includes 'ROCMExecutionProvider'

# 5. Restart server; look for:
#    Real-ESRGAN ONNX loaded (ROCm (AMD GPU) mode, tile=N, max_tiles=1024)
```

**Re-run trigger**: any `pip install` that touches `onnxruntime` —
`pip install -r requirements.txt`,
`pip install --require-hashes -r requirements.lock`, an explicit
`--force-reinstall onnxruntime-rocm`, or a pre-commit hook that
rewrites the lockfile and then runs pip. The fix-script is idempotent
(it only writes when `PF_X` is set) and prints `already clean` when
it's a no-op, so re-running on a healthy install is safe.

CPU-only users and standalone-zip users are unaffected; the trap is
purely an AMD-GPU dev-host concern.

---

## 14. Testability

`tests/test_image_pipeline.py` pins the user-visible contract:

| class                       | what it pins                                           |
|-----------------------------|--------------------------------------------------------|
| `TestPreferredImageExtension` | format-decision matrix (webp/jpeg mode, gif preserve, video/manual passthrough) |
| `TestFormatNormalize`       | `_ensure_format_matches_extension` re-encodes JPEG-in-`.webp`, no-ops on matching format, swallows corrupt bytes |
| `TestResponsiveVariants`    | `-sm`/`-md` written for boxart, skipped when source narrower than target, never written for screenshots |
| `TestBoxartSrcset`          | srcset emits existing variants, empty for missing original, skips missing variant siblings |
| `TestFinalizePipeline`      | end-to-end: JPEG bytes at `.webp` path → WebP on disk + variants written |

Tests stub `_get_upscaler` to `None` so CI doesn't try to load Real-
ESRGAN — the 800×1120 fixture sits inside the 80%–120% target band
anyway, so standardize is a no-op for the size dimension.

**ROCm path is not tested in CI** — `/dev/kfd` doesn't exist in CI
containers, and even if it did, the GitHub runner doesn't have an AMD
GPU. The provider-selection branch is exercised manually via the trap
fix sequence in §13. `services/image_utils._init_upscaler` falls
through to `CPUExecutionProvider` on CI, which is what every other test
expects.

`tests/test_pass45_security.py::TestPass45_6*` pins the
decompression-bomb cap (5 cases). `TestPass45_7*` pins the orphan-
cleanup race (5 cases — reverting the cleanup change fails 4 of 5).

`tests/test_image_pipeline.py` does not currently have a dedicated dedup
test — `compute_dhash` is exercised indirectly through scraper
integration tests. New work on dedup should add direct unit tests for
the Hamming distance bands.

---

## 15. Known invariants

These hold across the whole pipeline. A change that breaks any of them
is a regression — flag it in code review.

1. **Every image write is atomic.** Either via
   `base_scraper.download_image`'s `.dl-*.part` + `os.replace` or via
   `_atomic_save`'s `.save_*` + `os.replace`. No call site writes
   directly to a final path — even on the upload branch
   (`save_upload`) — without going through `_atomic_write_bytes`.
2. **Every external URL fetch goes through the SSRF gate.** Both
   `validate_outbound_url` and `validate_and_pin_url` + `pin_host_ip`
   on the GET so redirects walk the gate hop-by-hop and DNS rebinding
   between validate and connect can't redirect the connection. Applies
   equally to scraper images, screenshots, fanart, manuals, *and* the
   ESRGAN model download (Pass 41.14.B / 45.2).
3. **`Image.MAX_IMAGE_PIXELS` is set at module import** in
   `services/image_utils.py`, `services/game_media_service.py`, and
   `app.py`. Every `Image.open(...)` call site has an explicit
   `Image.DecompressionBombError` catch with a distinct log line.
4. **ESRGAN model load is lazy and singleton.** `_get_upscaler()`
   double-checks under `_upscaler_lock`; the GPU inference worker is a
   single daemon thread; the GPU-fail circuit breaker is one-way for
   the process lifetime.
5. **Every `Path.rglob` over a configurable root has a symlink-escape
   guard.** Use the `_safe_under_root` pattern (§11) — `Path.is_
   symlink()` alone is insufficient because Python 3.12's `rglob`
   already followed the link by the time you inspect the result.
6. **Variants are sibling files**, same dir, same ext, suffix in the
   filename stem (`<base>-sm.webp`). Never a sibling directory, never a
   different format — `boxart_srcset` and the template `<img srcset>`
   builder assume the sibling-file layout.
7. **Format normalization is no-op when bytes already match the
   extension.** `_ensure_format_matches_extension` reads the source
   format and returns early when equal — avoids a write/mtime bump on
   every finalize call (and avoids tripping `clean_orphaned_files`'s
   mtime-based race guard).
8. **Orphan cleanup never follows symlinks.** Skip at scan time
   (`find_orphaned_media`), re-check at delete time
   (`clean_orphaned_files`). A symlinked entry inside a media dir from
   manual admin work can never be unlinked by the cleaner.
9. **GIFs pass through untouched.** Never re-encoded, never resized,
   never converted to WebP — `img.save(path, 'GIF')` without
   `save_all=True` flattens animation to the first frame.
10. **The fill-only invariant extends to media columns.** Scraper
    `apply_*_to_game` UPDATEs wrap every `?` in
    `COALESCE(?, column_name)` (see CLAUDE.md "Scraper fill-only
    invariant"); the pre-populate stale-clear step is the only place
    that ever NULLs a media column outside of Full Re-scrape mode.
