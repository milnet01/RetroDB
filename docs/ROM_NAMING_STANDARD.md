# RetroDB ROM Naming Standard

> **Version**: 1.1  
> **Last Updated**: 2026-01-20

This document defines the official ROM file naming conventions for RetroDB. Following these standards ensures consistency, proper sorting, and accurate matching between filenames and scraped metadata.

---

## Core Principles

1. **Natural article placement** - Keep articles (A, An, The) at the beginning
   - ✅ `The Legend of Zelda`
   - ❌ `Legend of Zelda, The`

2. **Spaces over underscores** - Use natural spacing
   - ✅ `Super Mario Bros`
   - ❌ `Super_Mario_Bros`

3. **Parentheses for metadata** - All metadata tags use `()`
   - ✅ `Game Name (USA).nes`
   - ❌ `Game Name [USA].nes`

4. **Natural sorting** - Files sort as they appear; database `sort_title` handles alphabetical ordering

---

## Special Character Handling

Certain characters are unsafe or problematic for filesystems. Replace them as follows:

| Original | Replacement | Example |
|----------|-------------|---------|
| `:` | ` - ` | `Zelda: Ocarina of Time` → `Zelda - Ocarina of Time` |
| `?` | *(remove)* | `Who Framed Roger Rabbit?` → `Who Framed Roger Rabbit` |
| `*` | *(remove)* | |
| `/` | `-` | `AC/DC` → `AC-DC` |
| `\` | `-` | |
| `"` | `'` | `"Quota"` → `'Quota'` |
| `<` | *(remove)* | |
| `>` | *(remove)* | |
| `\|` | `-` | |

**Note**: Apostrophes (`'`) and ampersands (`&`) are safe and should be preserved.

---

## Console Games

### Standard Format

```
Game Name (Region).extension
```

### With Optional Tags

```
Game Name (Region) (Edition).extension
```

### Multi-Disc Games

```
Game Name (Disc X of Y) (Region) (Edition).extension
```

### Examples

| Filename | Notes |
|----------|-------|
| `Super Mario Bros (USA).nes` | Standard single-region game |
| `Sonic the Hedgehog (Europe).md` | European release |
| `The Legend of Zelda - Ocarina of Time (USA).n64` | Colon replaced with dash |
| `Final Fantasy VII (Disc 1 of 3) (USA).bin` | Multi-disc with disc indicator |
| `Final Fantasy VII (Disc 2 of 3) (USA).bin` | |
| `Final Fantasy VII (Disc 3 of 3) (USA).bin` | |
| `Metal Gear Solid (Disc 1 of 2) (USA) (Greatest Hits).bin` | Multi-disc with edition |
| `Crash Bandicoot (USA) (Collector's Edition).bin` | Special edition |

### Region Codes

When a ROM works for multiple regions, use **USA** as the default for consoles.

| Code | Region |
|------|--------|
| `USA` | United States (default for consoles) |
| `Europe` | European release |
| `Japan` | Japanese release |
| `World` | Multi-region/worldwide |
| `Germany` | German-specific |
| `France` | French-specific |
| `Spain` | Spanish-specific |
| `Italy` | Italian-specific |
| `Australia` | Australian release |
| `Brazil` | Brazilian release |
| `Korea` | Korean release |

### Optional Tags (Console)

Only include when applicable:

| Tag | Usage |
|-----|-------|
| `(Disc X of Y)` | Multi-disc games - position before region |
| `(Rev N)` | Revision number (Rev 1, Rev 2, Rev A) |
| `(Beta)` | Beta version |
| `(Proto)` | Prototype |
| `(Demo)` | Demo/trial version |
| `(Unl)` | Unlicensed |
| Edition names | `(Greatest Hits)`, `(Player's Choice)`, `(Platinum)`, `(Collector's Edition)`, etc. |

---

## Computer Games

### Standard Format

```
Game Name (Year) (Publisher).extension
```

### With Optional Tags

```
Game Name (Year) (Publisher) (Edition).extension
```

### Examples

| Filename | Notes |
|----------|-------|
| `Lemmings (1991) (Psygnosis).adf` | Standard Amiga game |
| `The Secret of Monkey Island (1990) (LucasArts).d64` | Article preserved |
| `Elite (1984) (Acornsoft).ssd` | BBC Micro game |
| `Maniac Mansion (1987) (LucasFilm Games).d64` | C64 game |
| `Prince of Persia (1989) (Broderbund) (Collector's Edition).adf` | With edition |
| `Jet Set Willy (1984) (Software Projects).tzx` | ZX Spectrum game |

### Region Default

When a game was released in multiple regions, use **Europe** as the default for computer systems.

**Rationale**: Home computers (C64, Amiga, ZX Spectrum, Amstrad CPC, etc.) were predominantly European platforms in the 1980s.

### Year Format

- Always use 4-digit year: `(1984)`, `(1991)`
- Use original release year for that platform
- For ports, use the year of that specific port

### Publisher Guidelines

- Use the publisher name as it appeared at release
- Common variations:
  - `LucasArts` (not `LucasArts Entertainment`)
  - `Ocean` (not `Ocean Software`)
  - `U.S. Gold` (with periods)
  - `Microprose` (not `MicroProse Software`)

---

## Systems Classification

### Console Systems (use Region, default USA)

- Nintendo: NES, SNES, N64, GameCube, Wii, Wii U, Switch
- Nintendo Handheld: Game Boy, GBC, GBA, DS, 3DS
- Sony: PlayStation, PS2, PS3, PSP, PS Vita
- Sega: Master System, Genesis/Mega Drive, Saturn, Dreamcast, Game Gear
- Microsoft: Xbox, Xbox 360
- Atari: 2600, 5200, 7800, Jaguar, Lynx
- NEC: PC Engine, TurboGrafx-16, PC-FX
- SNK: Neo Geo, Neo Geo Pocket
- Other: 3DO, ColecoVision, Intellivision, Vectrex

### Computer Systems (use Year + Publisher, default Europe)

- Commodore: C64, VIC-20, Amiga, Plus/4
- Sinclair: ZX Spectrum, ZX81
- Amstrad: CPC
- Atari: 800, ST
- BBC: BBC Micro, Acorn Electron
- MSX: MSX, MSX2
- Apple: Apple II, IIGS
- DOS/PC: MS-DOS, Windows 3.x/9x
- Sharp: X68000
- NEC: PC-88, PC-98
- Other: TRS-80, TI-99/4A, Oric

---

## Multi-Disc Game Handling

Multi-disc games require special handling for ES-DE compatibility. RetroDB uses M3U playlists to manage multi-disc games.

### M3U Playlist Structure

An M3U game consists of three components that must share the same base name:

```
roms/psx/
├── Final Fantasy VII.m3u           # M3U playlist file (this is the "ROM" in RetroDB)
└── Final Fantasy VII/              # Game folder (same name as M3U, no extension)
    ├── noload.txt                  # Prevents ES-DE from scanning this folder
    ├── Final Fantasy VII (Disc 1 of 3) (USA).bin
    ├── Final Fantasy VII (Disc 2 of 3) (USA).bin
    └── Final Fantasy VII (Disc 3 of 3) (USA).bin
```

### M3U File Naming

The M3U file follows the same naming convention as regular ROMs, but with `.m3u` extension:

**Console (default):**
```
{Game Name} ({Region}).m3u
```

**Computer:**
```
{Game Name} ({Year}) ({Publisher}).m3u
```

### M3U File Contents

The M3U file contains relative paths to each disc file:

```
Final Fantasy VII/Final Fantasy VII (Disc 1 of 3) (USA).bin
Final Fantasy VII/Final Fantasy VII (Disc 2 of 3) (USA).bin
Final Fantasy VII/Final Fantasy VII (Disc 3 of 3) (USA).bin
```

**Format:** `{FolderName}/{DiscFilename}`

### Disc File Naming

Each disc file inside the folder follows the standard naming with disc indicator:

```
{Game Name} (Disc X of Y) ({Region}).{ext}
```

### Folder Naming

The game folder must match the M3U filename exactly (without the `.m3u` extension):

| M3U File | Folder Name |
|----------|-------------|
| `Final Fantasy VII (USA).m3u` | `Final Fantasy VII (USA)/` |
| `Resident Evil 2 (Europe).m3u` | `Resident Evil 2 (Europe)/` |

### Renaming M3U Games

When renaming an M3U game, three things must be updated:

1. **M3U file** - Rename the `.m3u` file itself
2. **Game folder** - Rename the folder to match the new M3U name
3. **M3U contents** - Update the paths inside the M3U file to reference the new folder name

**Note:** The individual disc files inside the folder do NOT need to be renamed. Only the folder name and M3U contents need updating.

**Example:**
```
Before:                                    After:
├── FF7 (USA).m3u                         ├── Final Fantasy VII (USA).m3u
└── FF7 (USA)/                            └── Final Fantasy VII (USA)/
    ├── noload.txt                            ├── noload.txt
    └── FF7 (Disc 1).bin                      └── FF7 (Disc 1).bin  ← unchanged

M3U contents before:                       M3U contents after:
FF7 (USA)/FF7 (Disc 1).bin                Final Fantasy VII (USA)/FF7 (Disc 1).bin
```

### Creating M3U Games

RetroDB's Archive Scanner can automatically create M3U playlists:

1. **Scan** for multi-file archives
2. **Create M3U** extracts the archive, creates the folder structure, adds `noload.txt`, and generates the M3U playlist
3. **Original archive** is moved to a staging folder for manual deletion after verification

---

## Validation Rules

RetroDB Reports will check for the following:

### Non-Standard Filename Issues

1. **Missing region** (console) - No region tag found
2. **Missing year** (computer) - No year tag found
3. **Missing publisher** (computer) - No publisher tag found
4. **Invalid characters** - Contains `:`, `?`, `*`, etc.
5. **Underscore usage** - Contains underscores instead of spaces
6. **Bracket mismatch** - Uses `[]` instead of `()`
7. **Moved article** - Article at end like "Legend of Zelda, The"

### Name Mismatch Issues

1. **Title differs from scraped** - Filename game name doesn't match database title
2. **Region mismatch** - Filename region differs from scraped region
3. **Year mismatch** (computer) - Filename year differs from scraped release year

---

## Quick Reference

### Console Template
```
{Game Name} ({Region}) ({Edition}).{ext}
{Game Name} (Disc {X} of {Y}) ({Region}) ({Edition}).{ext}
```

### Computer Template
```
{Game Name} ({Year}) ({Publisher}) ({Edition}).{ext}
```

### Character Replacements
```
: → -    ? → (remove)    * → (remove)
/ → -    \ → -           " → '
< → (remove)    > → (remove)    | → -
```
