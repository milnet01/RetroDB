# PASS-59-155 cheats — cold-eyes loop log

## Cold-eyes loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| impl | 2026-10-29 | none: implementation fold-back, no reviewer dispatched | — | — | — | — | Building it proved clauses false. §4.4: three cores' .info corename is not their library name (cap32, freeintv, same_cdi); names now come from source; `cheats` read without same_as; the helper is disc_ids. §4.2: both GitHub packs redirect; redirects followed to libretro/GitHub hosts only. §4.3: DuckStation pack names 3-letter serials. §4.5/INV-5: enabled names the panel does not list stay. §4.6: panel full width with a search box (a PS2 game had 486 cheats). §4.7: source alone keeps the list's switches. |
| answer | 2026-11-04 | none: open question answered from RetroArch's source, no reviewer dispatched | — | — | — | — | §14 Q1 answered: RetroArch's rewrite at unload keeps every loaded cheat, so INV-2 holds. It drops comments, unknown keys and cheats past the `cheats = N` count, in the game's copy only. |
| amend | 2026-11-15 | none: amendment for PASS-59-313, no reviewer dispatched | — | — | — | — | §4.8 and INV-12 added: standalone MAME lists a set's cheats from an imported cheat.7z (no pack: mamecheat.co.uk refuses automated requests) and launches with -plugin cheat. No switches: MAME's plugin keeps no record of which cheats are on. Origin: roadmap PASS-59-313. |
| amend | 2026-11-16 | none: amendment for PASS-59-314, no reviewer dispatched | — | — | — | — | §4.8 gains switches and INV-13: choices in own/mame/on/<set>.txt, switched on by an -autoboot_script MAME runs at each start and written back as it stops; only run/off cheats without a parameter get one. MAME 0.289 on Galaga: Infinite Lives switched on at start held the lives byte at 6; the script re-runs after a hard reset. Origin: roadmap PASS-59-314. |
