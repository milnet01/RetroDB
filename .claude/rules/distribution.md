---
paths:
  - "build_dist.py"
  - "retrodb.spec"
  - "packaging/**"
  - "scripts/render_icons.py"
  - "scripts/retrodb_launcher.py"
  - "scripts/install_launcher.py"
  - "release-standalone.sh"
  - ".github/workflows/release.yml"
---

## Distribution (Patreon Releases)

Two shapes:
- **Source** — small zip; user installs Python + runs `pip install -r requirements.txt`. Cross-platform from one host.
- **Standalone** — PyInstaller bundle (Python runtime + deps + assets baked in). User unzips and double-clicks the platform's launcher (`start.sh` / `start.command` / `start.bat`) — the PyInstaller `retrodb` binary sits next to it. PyInstaller has no cross-compile — must build on the target OS. `build_dist.build_standalone` ships those launchers from **`packaging/standalone/`**, never the repo root: the root scripts are the *source*-install launchers and run `python3 app.py`, which a bundle has no `.py` files for (Pass 59.10). A standalone launcher must only `exec ./retrodb` — the binary opens the browser itself (`app.py`'s `sys.frozen` branch), since only the server knows the resolved port. The source-install launchers ask `app.py` to do the same with `RETRODB_OPEN_BROWSER=1`; it opens once the port is bound, and never under LocalWebServerManager (`LWSM_MANAGED=1`). On Linux the zip also carries `packaging/RetroDB.desktop` + `retrodb-256.png` and `install-launcher.sh`, which substitutes the template's `__EXEC__` / `__ICON__` against the extraction path (Pass 59.11); `scripts/install_launcher.py` is the source-install equivalent and needs Python, so it cannot run inside a bundle.

### App icon assets
- Master SVG: `packaging/icon.svg` (neon gamepad). `python3 scripts/render_icons.py` rasterizes it into `static/favicon.svg`/`-16`/`-32`/`apple-touch-icon.png` (wired in `base.html`) + `packaging/icons/retrodb-{256,512}.png`/`.ico`/`.icns`. Needs **`cairosvg`** — a BUILD-TIME-ONLY dep, deliberately NOT in `requirements.txt`; the raster outputs are committed so end users never import it. `retrodb.spec` sets `icon=` (`.ico`/`.icns`) and bundles `packaging/icons`.
- **One-click launch (local install):** `scripts/retrodb_launcher.py` probes the unauthenticated `/health` (port from `server_port.resolve_server_port(use_saved=True)` — the same chain `app.py` binds with: `PORT` → `RETRODB_PORT` → saved `server_port` → 5000; see `docs/specs/settings.md` §Precedence), starts `app.py` if down, opens the browser. `scripts/install_launcher.py` pins a `.desktop` (absolute `Exec`/`Icon` paths) into `~/.local/share/applications/`. Run the installer once.

```bash
python3 build_dist.py                       # all 3 source ZIPs
python3 build_dist.py linux|macos|windows   # one source ZIP
python3 build_dist.py --standalone          # standalone for host platform
python3 build_dist.py --standalone --cpu-only  # CPU-only standalone (~600 MB, -CPU suffix)
```

- Output: `STAGING_DIR` constant in `build_dist.py` — defaults to `/mnt/Games/Scripts/Linux/Staging_Area/RetroDB`; override with the `RETRODB_STAGING_DIR` env var (`release.yml` does, to `/tmp/staging`). The default must name a mounted, writable drive: `build_standalone` calls `os.makedirs(STAGING_DIR)`, so a retired drive fails the documented build command with `PermissionError`.
- Filename: `RetroDB-v{VERSION}-{Platform}.zip` (source) or `RetroDB-v{VERSION}-{Platform}-Standalone.zip`. The self-updater (PASS-59-169, `services/updater.py::asset_names`) finds a release's download by these names, its checksum in `SHA256SUMS.txt` / `<zip>.sha256`, and only sees a release once it is **published** — so publishing the draft is what offers the update to users.
- What ships in a source ZIP: `collect_files` enumerates **`git ls-files`** — the allow-list `.gitignore` already maintains — and only then applies the deny-lists (Pass 59.13). Every generated artifact the ZIP needs (`main.min.css`, both bundles, `translations/**/*.mo`) is committed, so nothing shipped depends on the walk. Without git (a tarball, not a checkout) it falls back to the filesystem walk, which is why the deny-lists stay. They are `EXCLUDE_FILES`, `EXCLUDE_DIRS`, `EXCLUDE_EXTENSIONS` and the `INCLUDE_IMAGE_DIRS` whitelist in `build_dist.py`, and they remove the tracked-but-maintainer-only files. Between them this excludes user config (`config.py`, `data/{settings,scraper_settings,rom_tools_config,psn_tokens,xbox_tokens}.json`, `data/.secret_key`), the runtime DB (the whole `database/` dir — covers `database/roms.db`; `data/retrodb.db` is also listed as a legacy path, and all `.db*` / `.log` files are excluded by extension), and scraped media (`static/videos/`, plus every `static/images/<dir>/` that is not in `INCLUDE_IMAGE_DIRS = {'hardware','ratings','systems','avatars'}`). The one exception is `INCLUDE_IMAGE_FILES`: the app's trophy and platform icons, which share `static/images/trophies/` with each user's downloaded PSN trophy art. They are named file by file in `build_dist.py`, `.gitignore` and `retrodb.spec`. `tests/test_pass59_packaging.py::TestReferencedImagesShip` fails if an image the templates or scripts name stops shipping. Per-platform: only that platform's start script (`start.sh` / `start.command` / `start.bat`).
- Standalone build is driven by `retrodb.spec` (PyInstaller onedir mode). Spec whitelists static subdirs explicitly to avoid sweeping in scraped media; new pip deps that PyInstaller's static analyser can't follow (string-imported via `importlib`) must be added to `HIDDEN_IMPORTS` in the spec.
- `--cpu-only` (Pass 46.3 Part 3) builds the standalone inside an isolated venv under `STAGING_DIR/.cpu-build-venv` (vanilla CPU `onnxruntime` from `requirements.txt` + PyInstaller), so it produces the ~600 MB CPU bundle even on the maintainer's AMD box where `onnxruntime-rocm` is installed system-wide (the two flavours share the `onnxruntime` import name and can't coexist). Artifacts get a `-CPU` filename suffix. Plain `--standalone` inherits whatever onnxruntime is in the current env (GPU/ROCm locally; CPU on a clean checkout, since `requirements.txt` pins vanilla).
- CI standalone build (Pass 46.3 Part 4): `.github/workflows/release.yml` has a `build-standalone` job — a `[ubuntu, macos, windows]-latest` matrix gated behind `workflow_dispatch` + `build_standalone: true` (never fires on an automatic tag push; triples CI minutes). Each runner builds `--standalone --cpu-only` and attaches the zip + SHA-256 to the draft release.
- `./release-standalone.sh` (repo root) automates that standalone CI release: detects the version from `config.example.py`, pushes the `vX.Y.Z` tag (cancelling the redundant push-triggered source run), dispatches `release.yml` with `build_standalone=true`, watches the matrix, and fixes the draft's release notes from `data/changelog.yaml` (the dispatch path leaves a placeholder body). Leaves the release as a **draft** — review and publish manually. Windows/macOS standalones can only come from this CI path (PyInstaller has no cross-compile).

Pre-release checklist: bump version + changelog → ensure `config.example.py` matches any new settings → `python3 build_dist.py` (source) and/or `python3 build_dist.py --standalone` (host platform) → upload from staging.
