# 0002 — Scrapers fill gaps; they do not overwrite

**Status:** accepted. **Recorded:** 2026-10-17 (roadmap PASS-59-65).

## Context

RetroDB pulls metadata from several online sources. A source often answers
with a partial record: no publisher, no players count, no boxart. Users also
correct fields by hand. A re-scrape that wrote whatever came back would
erase both earlier scraped values and hand-curated ones.

Origins:

- The media, screenshot and controller rules were in `CLAUDE.md` when the
  repository began (commit `f2e7335`, 2026-04-20).
- Full Re-scrape mode, the `force_overwrite` parameter, shipped in v1.13.7
  (`data/changelog.yaml`).
- Pass 30.4 found IGDB and TGDB wiping filled fields on an empty answer, and
  wrapped every write in `COALESCE` (v2.98.1, `data/changelog.yaml`). The
  rule entered `CLAUDE.md` § Scraper fill-only invariant in commit
  `1e8f7c6` (2026-04-24).
- Pass 40.6 and Pass 45.3 fixed later breaches of the same rule
  ([`../specs/scrapers.md`](../specs/scrapers.md) § 5).

## Decision

- A scraper fills an empty field and never overwrites a filled one.
- Full Re-scrape mode is the one exception. The user asks for it, and it
  overwrites only the fields a source actually provides.
- Media fields are only filled when empty. To replace one, the user clears
  it first.
- Screenshots are appended, never replaced.
- A system's curated default controllers always override scraped or AI
  values.

The contract, its audit-column carve-out and AI Fill's separate path are
[`../specs/scrapers.md`](../specs/scrapers.md) § 5.

## Consequences

- Every scraper `UPDATE` wraps each value in `COALESCE(?, column)`.
  `scraper/scrape_esde.py::apply_esde_metadata` is the model.
- `tests/test_scrape_fill_only.py` pins the rule for IGDB and TGDB. The
  other sources are not yet covered by it
  ([`../specs/scrapers.md`](../specs/scrapers.md) § 5, *Test pin*).
- A re-scrape cannot repair a wrong value. The user clears the field, or
  runs Full Re-scrape.
