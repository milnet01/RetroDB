# PASS-59-81 player cores and settings — cold-eyes loop log

## Cold-eyes loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| impl | 2026-10-22 | none (no reviewer dispatched) | - | - | - | - | Build fold-back, not a review. The build found §4.1's `superfamicom` is a folder no library uses (config.SYSTEM_NAME_MAP has `sfc`, as PASS-59-122 found for the seeds); renamed, and a test now pins every table folder. Recorded what the build settled: §4.3 falls back to an installed core when the index cannot be fetched; a launch maps a `same_as` folder that shares an installed core; test pointers name the files that exist. Rule 14 gate cancelled by RetroDB CLAUDE.md. |
| amend | 2026-11-16 | none: amendment for PASS-59-318, no reviewer dispatched | - | - | - | - | §4.1 gains `achievements_only` and the arcade row (mame, fbneo, arcade, neogeo → fbneo): the player takes an arcade game only when RetroAchievements links it and it has no emulator of its own, ahead of the system default, and never stands in for a game without achievements. Origin: roadmap PASS-59-318 (user, 2026-11-16). |
