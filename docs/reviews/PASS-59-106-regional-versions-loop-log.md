# PASS-59-106 regional versions — cold-eyes loop log

## Cold-eyes loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| impl | 2026-10-19 | none: implementation fold-back, no reviewer dispatched | — | — | — | — | Building it proved three clauses false. §4.1: foreign_keys is never on, so the ON DELETE actions do nothing; migration triggers keep the rules on delete, bonus flag and system change. §4.5: the scraper id write was COALESCE(?, igdb_id), which contradicts INV-10; now COALESCE(igdb_id, ?), Full Re-scrape the reverse; the backfill's only-empty run also takes games missing an id. INV-9: the grep matched reads and the triggers; now SET version_group_id = ?. |
