# RetroDB

**Retro Gaming ROM Library Manager** - A web-based application for organizing, scraping metadata, and managing your retro game ROM collection.

> **Status:** Solo-developed; releases on a best-effort cadence. See [`SECURITY.md`](SECURITY.md) for the security disclosure policy and [`CONTRIBUTING.md`](CONTRIBUTING.md) for the developer setup.

## Features

### Library & Metadata
- **Multi-System Library** - Consoles and computers from the Atari 2600 to the PS5, with one card per game across regional versions
- **Hybrid Metadata Scraping** - Combines data from TheGamesDB, IGDB, RAWG, ScreenScraper, and ES-DE gamelists; Steam imports also fill from the Steam store *(requires your own login/API key per source — see [API Keys](#api-keys))*
- **AI Fill** - Intelligent metadata gap-filling using Gemini, OpenAI, or Claude *(requires your own AI provider API key, which is paid/usage-billed — see [API Keys](#api-keys))*
- **Multi-Rating System** - 9 international age rating systems (ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd, CADPA) with cross-mapping
- **Bulk Operations** - Bulk scraping, bulk editing, bulk AI Fill, compare games, and queue management with job recovery
- **Rich Game Pages** - Game logos, a turnable 3D box (with Slipcase box import), manuals that turn like a book, release dates per region, and RPCS3 compatibility for PS3 games

### Achievements & Trophies
- **RetroAchievements Integration** - Track achievement progress across retro games
- **Steam Achievements** - Import Steam library and track achievement progress
- **Xbox Achievements** - Import Xbox library and track gamerscore
- **PS3/PSN Trophy Tracking** - RPCS3 local trophies and PSN API trophy sync

### Playing
- **Play Button** - Start a game from RetroDB with RetroArch or a standalone emulator (DuckStation, PCSX2, RPCS3 and others)
- **Built-in Player** - Download RetroDB's own RetroArch from inside the app; cores download when a game needs them
- **Emulator Setup** - Point RetroDB at your emulators and choose one per system
- **Cheats** - Download cheat packs or import your own for RetroArch, DuckStation and PCSX2

### Organization
- **Collections** - Tags, named lists with drag-and-drop ordering, and a wishlist that scrapes itself
- **Bonus Discs and Multi-Disc Games** - Link bonus discs to their game; build `.m3u` playlists for multi-disc games
- **Collector Trophies** - Gamification system with milestone-based trophy unlocks
- **Game Imports** - Import from CLZ Games (PDF), Steam, Xbox, and PlayStation Network

### Tools & Analytics
- **ROM Tools** - Archive scanner, CHD converter/verifier, duplicate finder, multi-disc organizer, MAME Names
- **ROM Reports** - Naming validation and standards compliance checking
- **Analytics Dashboard** - Charts, export (PNG/CSV), and leaderboards
- **Image Standardization** - AI upscaling (Real-ESRGAN) and Lanczos downscaling; Screenshot Review and duplicate screenshot finder
- **Museum** - Interactive gaming system encyclopedia with AI-generated content

### UI & System
- **Themes** - Cyberpunk, Matrix, Amber, Ocean, Cathedral (`christian` internal key), Blade Runner, and Elite (vector starfield) with animated canvas effects
- **Languages** - The interface, help manual and changelog are translated; pick your language in Settings
- **Multi-User Support** - Role-based access control (admin, editor, player, viewer); a player can view and launch games
- **How Long to Beat** - Playtime estimates for your games, beside your own Steam play time
- **Search Anywhere** - Find any game or console from every page
- **Self-Updater** - An admin installs a new version from Settings; RetroDB backs up the database first and rolls back if the update fails
- **Phone and Tablet Layout** - The pages fit a small screen
- **Log Viewer** - Unified log browser across all categories
- **Genre Normalization** - Automatic normalization with custom rules

> **Heads up:** The metadata scrapers, AI Fill, Museum AI content, and the
> achievement/trophy integrations (RetroAchievements, Steam, Xbox, PSN) each
> need the relevant account login or API key before they'll work. RetroDB runs
> fine without them, but those specific features stay inactive until you supply
> credentials — see [API Keys](#api-keys) below for where to get each one. Most
> are free; the AI providers are paid (billed by usage).

## Quick Start

> **End users:** each release offers two downloads per platform (Linux, macOS, Windows). A **Standalone** zip needs no Python: unzip it and run `start.sh`, `start.command` or `start.bat`. The plain zip runs from source and needs the steps below. **Developers:** `git clone` the repo and see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup instead.

### 1. Extract

Extract the RetroDB ZIP to a directory of your choice.

### 2. Install

```bash
python install.py
```

This installs Python dependencies, creates config files from templates, and sets up required directories. On Linux, `./setup.sh` runs the same install in a graphical installer.

### 3. Launch

```bash
# Linux/macOS
./start.sh

# Windows
start.bat

# Or directly
python app.py
```

Open your browser to `http://localhost:5000` and follow the setup wizard.

## Requirements

- **Python** 3.10 or higher (CI tests on 3.12 and 3.13)
- **pip** (Python package manager)
- **Web Browser** (Chrome, Firefox, Safari, Edge)

### Optional Tools (for ROM Tools features)

- **unzip** - ZIP archive extraction
- **7-Zip** (`p7zip-full`) - 7z archive extraction
- **unrar** - RAR archive support
- **chdman** (`mame-tools`) - CHD conversion and verification

## Configuration

RetroDB keeps its settings in three places:

- **`data/settings.json`** - Paths and preferences changed via the web UI.
- **`data/scraper_settings.json`** - The install-wide scraper and AI keys entered under **Settings**.
- **The database** - Each user's own sign-ins (PlayStation, Xbox, RetroAchievements).

**`config.py`** holds server defaults and is created from `config.example.py` during install. You rarely need to edit it.

Most settings can be configured through the web interface at **Settings** or during the first-run **Setup Wizard**.

### API Keys

The metadata scrapers and AI services do **not** work out of the box — each one
needs its own account login or API key, which you create on that provider's
site. RetroDB itself is free and runs without any of them; the related feature
simply stays inactive until you add the credential. Most keys below are free to
obtain, but a few are **paid / usage-billed** — the AI providers (OpenAI,
Anthropic Claude, and Gemini beyond its free tier) charge per request, so you
pay them directly for what you use. Check each provider's current pricing before
enabling it.

| Service | Signup URL | Used For | Cost |
|---|---|---|---|
| TheGamesDB | https://api.thegamesdb.net/key.php | Metadata & boxart | Free |
| IGDB (Twitch) | https://dev.twitch.tv/console | Metadata | Free |
| RAWG.io | https://rawg.io/apidocs | Metadata | Free |
| ScreenScraper | https://www.screenscraper.fr | Metadata, 3D boxart, videos | Free account |
| RetroAchievements | https://retroachievements.org/controlpanel.php | Achievement tracking | Free account |
| Steam Web API | https://steamcommunity.com/dev/apikey | Steam import & achievements | Free |
| PlayStation | https://ca.account.sony.com/api/v1/ssocookie | Trophy sync (an NPSSO sign-in token, per user) | Free account |
| Xbox | https://portal.azure.com | Xbox import & achievements (a Microsoft app client ID and secret, then a Microsoft sign-in) | Needs an Azure account |
| Google Gemini | https://aistudio.google.com/apikey | AI Fill & Museum | Free tier + paid |
| OpenAI | https://platform.openai.com/api-keys | AI Fill & Museum | Paid (usage-billed) |
| Anthropic Claude | https://console.anthropic.com/ | AI Fill & Museum | Paid (usage-billed) |

## Platform Support

RetroDB runs on **Linux**, **Windows**, and **macOS**. Platform-specific launchers are included:

| Platform | Launcher | Notes |
|---|---|---|
| Linux | `start.sh` | Tested on Ubuntu, Fedora, Arch |
| Windows | `start.bat` | Windows 10/11 |
| macOS | `start.command` | Double-clickable from Finder |

## Deployment

RetroDB is built for a trusted home network. The server listens on every
network interface, so other devices in your home can open the Network address
the start script prints. Do not expose it to the internet directly; if you
need access from outside your home, put it behind a reverse proxy as described
in [`docs/PROXY-DEPLOY.md`](docs/PROXY-DEPLOY.md). The full threat model is
[`docs/decisions/0001-threat-model.md`](docs/decisions/0001-threat-model.md).

## Updating

An admin can update from **Settings**: RetroDB downloads the new version, checks it, backs up the database, installs it, restarts, and rolls back if anything fails.

To update by hand instead:

1. Back up your install. Three things to copy:
   - `database/` — the live SQLite DB lives here (`database/roms.db`).
   - `data/` — settings and your own files (`settings.json`, `scraper_settings.json`, `rom_tools_config.json`, `standalone_settings.json`, `.secret_key`, `cheats/`, `player/`).
   - `config.py` — at the project root; copy it separately.
2. Extract the new version over the existing installation
3. Run `python install.py` to install any new dependencies
4. Your database and settings will be preserved

## Support development

[![Sponsor on GitHub](https://img.shields.io/github/sponsors/milnet01?label=Sponsor&logo=github&color=ea4aaa)](https://github.com/sponsors/milnet01)
[![Support on Patreon](https://img.shields.io/badge/Patreon-Support-f96854?logo=patreon&logoColor=white)](https://www.patreon.com/c/AntsProjectsHub)

RetroDB is free and open source, and every release is free to download.
If it saves you time, you can support its development. Donations fund
RetroDB itself: they buy no features, no early access and no downloads.
They do not pay for the emulators or cores RetroDB can launch. Those
belong to their own authors and are covered by their own licences.

- **GitHub Sponsors:** [github.com/sponsors/milnet01](https://github.com/sponsors/milnet01)
- **Patreon:** [patreon.com/c/AntsProjectsHub](https://www.patreon.com/c/AntsProjectsHub)

## License

RetroDB is released under the [MIT License](LICENSE).

## Legal

System logos and platform names are trademarks of their respective owners. RetroDB is not affiliated with any console manufacturer or game publisher. See [LEGAL.md](LEGAL.md) for full details.

RetroDB does not distribute or host ROM files.

## Credits

- Built with [Flask](https://flask.palletsprojects.com/) and [Waitress](https://docs.pylonsproject.org/projects/waitress/)
- Metadata from [TheGamesDB](https://thegamesdb.net/), [IGDB](https://www.igdb.com/), [RAWG](https://rawg.io/), [ScreenScraper](https://www.screenscraper.fr/)
- Achievement data from [RetroAchievements](https://retroachievements.org/), [Steam](https://store.steampowered.com/), [Xbox](https://www.xbox.com/)
- Trophy data from [PlayStation Network](https://www.playstation.com/) and [RPCS3](https://rpcs3.net/)
- AI metadata via [Google Gemini](https://ai.google.dev/), [OpenAI](https://openai.com/), [Anthropic Claude](https://www.anthropic.com/)
- Playtime data from [HowLongToBeat](https://howlongtobeat.com/)
- Image upscaling via [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (ONNX Runtime)
