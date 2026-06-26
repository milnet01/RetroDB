# RetroDB

**Retro Gaming ROM Library Manager** - A web-based application for organizing, scraping metadata, and managing your retro game ROM collection.

> **Status:** Solo-developed; releases on a best-effort cadence. See [`SECURITY.md`](SECURITY.md) for the security disclosure policy and [`CONTRIBUTING.md`](CONTRIBUTING.md) for the developer setup.

## Features

### Library & Metadata
- **Multi-System Library** - Supports 150+ gaming platforms from Atari 2600 to PS5
- **Hybrid Metadata Scraping** - Combines data from TheGamesDB, IGDB, RAWG, ScreenScraper, and ES-DE gamelists *(requires your own login/API key per source — see [API Keys](#api-keys))*
- **AI Fill** - Intelligent metadata gap-filling using Gemini, OpenAI, or Claude *(requires your own AI provider API key, which is paid/usage-billed — see [API Keys](#api-keys))*
- **Multi-Rating System** - 8 international age rating systems (ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd) with cross-mapping
- **Bulk Operations** - Bulk scraping, bulk editing, compare games, and queue management with job recovery

### Achievements & Trophies
- **RetroAchievements Integration** - Track achievement progress across retro games
- **Steam Achievements** - Import Steam library and track achievement progress
- **Xbox Achievements** - Import Xbox library and track gamerscore
- **PS3/PSN Trophy Tracking** - RPCS3 local trophies and PSN API trophy sync

### Organization
- **Collections** - Tags, named lists with drag-and-drop ordering, and wishlist
- **Collector Trophies** - Gamification system with milestone-based trophy unlocks
- **Game Imports** - Import from CLZ Games (PDF), Steam, Xbox, and PlayStation Network

### Tools & Analytics
- **ROM Tools** - Archive scanner, CHD converter/verifier, duplicate finder, multi-disc organizer
- **ROM Reports** - Naming validation and standards compliance checking
- **Analytics Dashboard** - 12-tab analytics with charts, export (PNG/CSV), and leaderboards
- **Image Standardization** - AI upscaling (Real-ESRGAN) and Lanczos downscaling
- **Museum** - Interactive gaming system encyclopedia with AI-generated content

### UI & System
- **7 Themes** - Cyberpunk, Matrix, Amber, Ocean, Cathedral (`christian` internal key), Blade Runner, and Elite (vector starfield) with animated canvas effects
- **Multi-User Support** - Role-based access control (admin, editor, viewer)
- **How Long to Beat** - Playtime estimates for your games
- **Log Viewer** - Unified log browser across all categories
- **Genre Normalization** - Automatic normalization with custom rules

> **Heads up:** The metadata scrapers, AI Fill, Museum AI content, and the
> achievement/trophy integrations (RetroAchievements, Steam, Xbox, PSN) each
> need the relevant account login or API key before they'll work. RetroDB runs
> fine without them, but those specific features stay inactive until you supply
> credentials — see [API Keys](#api-keys) below for where to get each one. Most
> are free; the AI providers are paid (billed by usage).

## Quick Start

> **End users:** download the source ZIP from Releases and follow the steps below. **Developers:** `git clone` the repo and see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup instead.

### 1. Extract

Extract the RetroDB ZIP to a directory of your choice.

### 2. Install

```bash
python install.py
```

This installs Python dependencies, creates config files from templates, and sets up required directories.

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

- **7-Zip** (`p7zip-full`) - Archive extraction
- **unrar** - RAR archive support
- **chdman** (`mame-tools`) - CHD conversion and verification

## Configuration

RetroDB uses two configuration files:

- **`config.py`** - Main settings (paths, API keys, server config). Created from `config.example.py` during install.
- **`data/settings.json`** - User-editable settings changed via the web UI.

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

The default `start.sh` / `start.bat` / `start.command` launchers bind RetroDB to
`localhost` — fine for single-machine use. If you want to access RetroDB from
other devices on your LAN, follow the reverse-proxy guide in
[`docs/PROXY-DEPLOY.md`](docs/PROXY-DEPLOY.md). Putting RetroDB directly on a
non-localhost interface without a proxy in front of it is unsupported.

## Updating

1. Back up your install. Three things to copy:
   - `database/` — the live SQLite DB lives here (`database/roms.db`).
   - `data/` — settings (`settings.json`, `scraper_settings.json`, `rom_tools_config.json`, `psn_tokens.json`, `xbox_tokens.json`, `.secret_key`).
   - `config.py` — at the project root; copy it separately.
2. Extract the new version over the existing installation
3. Run `python install.py` to install any new dependencies
4. Your database and settings will be preserved

## Support development

[![Sponsor on GitHub](https://img.shields.io/github/sponsors/milnet01?label=Sponsor&logo=github&color=ea4aaa)](https://github.com/sponsors/milnet01)

RetroDB is free and open source. If it saves you time, consider tipping —
every bit helps keep solo development sustainable.

- **GitHub Sponsors:** [github.com/sponsors/milnet01](https://github.com/sponsors/milnet01)

(Additional donation surfaces — Patreon, Buy Me A Coffee — are linked from
[`.github/FUNDING.yml`](.github/FUNDING.yml) as they come online.)

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
