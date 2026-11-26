---
paths:
  - "services/cheats.py"
  - "routes/cheats.py"
  - "static/js/game-cheats.js"
  - "services/ra_*.py"
  - "services/launcher/**"
  - "services/player*.py"
  - "services/launch_resolver.py"
  - "services/retroarch_command.py"
  - "services/standalone_settings.py"
  - "services/emulator_adapters.py"
  - "routes/launch*.py"
  - "routes/emulators.py"
  - "routes/achievements.py"
  - "routes/ra_sync.py"
  - "data/player_cores.json"
---

# Cheats and RetroAchievements sign-in

### Cheats (PASS-59-155)
- `services/cheats.py` owns the store (`data/cheats/`, gitignored): `packs/` is replaced whole by a download, `own/` holds imports and wins on a name clash. Routes in `routes/cheats.py`; pack downloads ride the player downloads job as `_cheats_<pack>`.
- The emulator's files are the record of which cheats are on; RetroDB keeps no table. Never overwrite a cheat file already in DuckStation's or PCSX2's cheats folder (INV-4).
- The game page's Cheats panel (`static/js/game-cheats.js`) sits full width under the card row; Settings > Emulators has the Cheats section. Spec: `docs/specs/PASS-59-155-cheats.md`.
- Standalone MAME (PASS-59-313, spec §4.8): no pack, since mamecheat.co.uk refuses automated requests; an imported `cheat.7z` stays packed in `own/mame/` (MAME reads it so), and its arcade sets' cheat names go to `own/mame/names.sqlite3`. MAME records no on/off state, so `own/mame/on/<set>.txt` does (PASS-59-314): the panel writes it, and the launch's `-autoboot_script` (`retrodb.lua`) switches its names on at start and writes MAME's switches back as the game stops. Only run/off cheats without a value get a switch.
- Arcade games with RetroAchievements (PASS-59-318): `achievements_only` in `data/player_cores.json` sends a linked game with no override of its own to the player's FBNeo core; the rest stay in MAME. The panel lists FBNeo's names with no switches (FBNeo turns cheats off at every boot). A launch copies the set's `.ini` into the user's `<RetroArch system>/fbneo/cheats/` only where none is, and the session's end removes it. Spec §4.9.

### RetroAchievements sign-in
- `services/ra_sign_in.py` owns it: the password is sent once and dropped, and the token lives in `user_platform_tokens` under `retroachievements`, per user. The web API key cannot sign RetroArch in.
- A token reaches RetroArch only in a launch's run layer (`session_keys`), never the base cfg or a game's cfg; `_PROTECTED_KEYS` holds the `cheevos_*` keys so a menu save cannot copy one.
- DuckStation and PCSX2 take no sign-in for one launch, so `services/ra_standalone.py` writes it to their main settings files at Play and takes it back when that user signs out or a signed-out user plays. A sign-in from an emulator's own menu is never overwritten. `emulator_written_settings` holds a hash of the token, never the token. DuckStation's token is encrypted as its `EncryptLoginToken` does; if DuckStation changes that, it asks the user to sign in again.
