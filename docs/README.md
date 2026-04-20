# RetroDB - Retro Gaming ROM Library Manager

A web-based application for organizing, scraping metadata, and managing your retro game ROM collection with a cyberpunk-themed UI.

## Features

### Library & Metadata
- **277 Gaming Platforms** - From Atari 2600 to PS5, handhelds, arcade, and computers
- **Hybrid Metadata Scraping** - Combines data from TheGamesDB, IGDB, RAWG, ScreenScraper, and ES-DE gamelists
- **AI Fill** - Intelligent metadata gap-filling using Gemini, OpenAI, or Claude
- **Multi-Rating System** - 8 age rating systems (ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd) with cross-mapping
- **Bulk Operations** - Bulk scraping, bulk editing, compare games, and queue management with job recovery
- **Genre Normalization** - Automatic standardization with custom rules

### Achievements & Trophies
- **RetroAchievements** - Track achievement progress across retro games
- **Steam Achievements** - Import Steam library and track achievements
- **Xbox Achievements** - Import Xbox library and track gamerscore
- **PS3/PSN Trophies** - RPCS3 local trophies and PSN API trophy sync

### Organization
- **Collections** - Tags, named lists with ordering, and wishlist
- **Collector Trophies** - Milestone-based gamification system
- **Game Imports** - Import from CLZ Games (PDF), Steam, Xbox, and PSN

### Tools & Analytics
- **ROM Tools** - Archive scanner, CHD converter/verifier, duplicate finder, multi-disc organizer
- **ROM Reports** - Naming validation and standards compliance
- **Analytics Dashboard** - 12 tabs with charts, export (PNG/CSV), and leaderboards
- **Image Standardization** - Real-ESRGAN upscaling and Lanczos downscaling
- **Museum** - Interactive gaming system encyclopedia with AI content
- **Log Viewer** - Unified log browser across all categories

### UI & System
- **6 Themes** - Cyberpunk, Matrix, Amber, Ocean, Cathedral, Blade Runner (each with animated canvas effects)
- **Multi-User Support** - Role-based access (admin, editor, viewer)
- **How Long to Beat** - Playtime estimates integration
- **Keyboard Shortcuts** - Navigate with `g+d`, `g+s`, `g+l`, etc.

## Requirements

- Python 3.8+
- pip (Python package manager)
- Web browser (Chrome, Firefox, Safari, Edge)
- Linux, Windows 10/11, or macOS

### Optional Tools
- **7-Zip** (`p7zip-full`) - Archive extraction
- **unrar** - RAR archive support
- **chdman** (`mame-tools`) - CHD conversion and verification

## Installation

1. **Extract** the RetroDB ZIP to a directory of your choice
2. **Install** dependencies:
   ```bash
   python install.py
   ```
3. **Start** the server:
   ```bash
   # Linux
   ./start.sh

   # Windows
   start.bat

   # macOS
   start.command
   ```
4. **Open** `http://localhost:5000` and follow the setup wizard

## Directory Structure

```
retrodb/
├── app.py                    # Main Flask application & database setup
├── config.py                 # Configuration and system mappings (277 systems)
├── build_css.py              # CSS bundle builder
├── build_js.py               # JS bundle builder
├── requirements.txt          # Python dependencies
├── data/
│   ├── settings.json         # User settings (via web UI)
│   ├── scraper_settings.json # Scraper priority & toggles
│   └── changelog.yaml        # Version changelog
├── database/
│   └── roms.db               # SQLite database
├── routes/                   # Flask blueprints (20+ route files)
├── services/
│   ├── database.py           # SQLite helpers, WAL mode
│   ├── auth.py               # Authentication & roles
│   ├── security.py           # Path validation, rate limiting
│   ├── game_utils.py         # Title parsing, ratings, system constants
│   ├── normalization.py      # Genre/modes normalization
│   ├── image_utils.py        # Real-ESRGAN upscaling, Lanczos downscaling
│   └── jobs/                 # Background job classes
├── scraper/
│   ├── hybrid_scraper.py     # Multi-source orchestration
│   ├── metadata_merger.py    # Per-source merge logic
│   ├── scrape_ai.py          # AI metadata (Gemini, OpenAI, Claude)
│   └── ...                   # Individual scraper modules
├── static/
│   ├── css/                  # Modular CSS (core/layout/components/features/pages)
│   │   └── main.min.css      # Generated bundle
│   ├── js/                   # Modular JS
│   │   └── app.bundle.js     # Generated bundle
│   └── images/               # Media (boxart, screenshots, fanart, ratings, hardware)
└── templates/                # 44 Jinja2 templates
```

## API Keys (Optional)

| Service | Signup URL | Used For |
|---|---|---|
| TheGamesDB | https://api.thegamesdb.net/key.php | Metadata & boxart |
| IGDB (Twitch) | https://dev.twitch.tv/console | Metadata |
| RAWG.io | https://rawg.io/apidocs | Metadata |
| ScreenScraper | https://www.screenscraper.fr | Metadata, 3D boxart, videos |
| RetroAchievements | https://retroachievements.org/controlpanel.php | Achievement tracking |
| Steam Web API | https://steamcommunity.com/dev/apikey | Steam import & achievements |
| Google Gemini | https://aistudio.google.com/apikey | AI Fill & Museum |
| OpenAI | https://platform.openai.com/api-keys | AI Fill & Museum |
| Anthropic Claude | https://console.anthropic.com/ | AI Fill & Museum |

## ES-DE Compatibility

RetroDB works with ES-DE's ROM folder structure:
- Each system has its own folder (e.g., `nes/`, `snes/`, `psx/`)
- Each folder contains a `systeminfo.txt` with supported file extensions
- Gamelists and media can be imported automatically

## Credits

- Built with [Flask](https://flask.palletsprojects.com/) and [Waitress](https://docs.pylonsproject.org/projects/waitress/)
- Metadata from [TheGamesDB](https://thegamesdb.net/), [IGDB](https://www.igdb.com/), [RAWG](https://rawg.io/), [ScreenScraper](https://www.screenscraper.fr/)
- Achievement data from [RetroAchievements](https://retroachievements.org/), [Steam](https://store.steampowered.com/), [Xbox](https://www.xbox.com/)
- Trophy data from [PlayStation Network](https://www.playstation.com/) and [RPCS3](https://rpcs3.net/)
- AI metadata via [Google Gemini](https://ai.google.dev/), [OpenAI](https://openai.com/), [Anthropic Claude](https://www.anthropic.com/)
- Playtime data from [HowLongToBeat](https://howlongtobeat.com/)
- Image upscaling via [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (ONNX Runtime)

## License

RetroDB is released under the [MIT License](../LICENSE).
