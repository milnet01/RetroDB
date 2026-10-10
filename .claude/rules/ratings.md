---
paths:
  - "services/game_utils.py"
  - "services/settings_validators.py"
  - "templates/_modals/edit_modal.html"
  - "templates/base.html"
  - "scraper/**"
---

# Multi-rating system

ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd, CADPA/China — DB columns
`{system}_rating` (China's is `china_rating`; key `china`, values `8+/12+/16+`).
Cross-mapping via maturity tiers in `services/game_utils.py` (`map_rating()`,
`get_preferred_rating()`). Empty ratings auto-fill from any available rating
during scrape / AI Fill / manual edit. User preference: `preferred_rating_system`.
`RATING_SYSTEM_KEYS` order is cross-map source priority — China is appended last
so Western boards win as the source. No Western scraper supplies a China rating
(inference / AI-fill / manual only). Adding a board = extend the tables in
`game_utils.py` + a migration + both edit modals (`_modals/edit_modal.html`
`edit_*`, `base.html` `gem*`) + settings dropdown + compare table + the scraper /
AI-fill / save paths + JS rating maps + `settings_validators._ALLOWED_RATING_SYSTEMS`.

Rating images live in `static/images/ratings/{SYSTEM}/`. `RATING_IMAGE_MAP` in
`game_utils.py` maps `(system, value)` → path. JS helpers expose
`window.RATING_IMAGE_MAP`, `window.RATING_TO_TIER`, `window.TIER_TO_RATING` via
`base.html`.
