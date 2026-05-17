# =============================================================================
# Pass 38.1 (partial 4/4) — _normalize_ratings helper
# =============================================================================
# The "NORMALIZE VALUES BEFORE SAVE" block inside apply_hybrid_metadata had
# 26 lines doing three rating-related things in sequence: ESRB letter
# normalization, cross-map empty rating fields from any available rating,
# and content-based rating inference as a final fallback. Pass 38.1
# (partial 4/4) extracted the trio into a single helper.
# =============================================================================

from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401


class TestNormalizeRatings:
    def test_esrb_normalized_before_cross_map(self):
        """KA → E (deprecated ESRB tag → modern equivalent). Cross-map then
        propagates the normalized 'E' to other systems."""
        from scraper import hybrid_scraper

        metadata = {
            'esrb_rating': 'KA',
            'pegi_rating': '', 'cero_rating': '', 'usk_rating': '',
            'acb_rating': '', 'fpb_rating': '', 'grac_rating': '',
            'classind_rating': '',
        }
        result = {'filled_fields': []}
        hybrid_scraper._normalize_ratings(metadata, result)
        assert metadata['esrb_rating'] == 'E', \
            f"KA should normalize to E, got {metadata['esrb_rating']!r}"

    def test_cross_map_fills_empty_rating_systems(self):
        """One filled rating + 7 empty ones → cross_map_ratings fills the
        empties from the filled one. Each filled column must add a
        descriptive entry to result['filled_fields']."""
        from scraper import hybrid_scraper

        metadata = {
            'esrb_rating': 'T',  # Teen — well-known cross-map source
            'pegi_rating': '', 'cero_rating': '', 'usk_rating': '',
            'acb_rating': '', 'fpb_rating': '', 'grac_rating': '',
            'classind_rating': '',
        }
        result = {'filled_fields': []}
        hybrid_scraper._normalize_ratings(metadata, result)
        # ESRB stays the source; at least some other systems get filled.
        assert metadata['esrb_rating'] == 'T'
        filled_logs = [f for f in result['filled_fields']
                       if 'cross-map' in f]
        assert filled_logs, (
            "cross_map_ratings should have filled at least one empty "
            "rating column from ESRB:T; result['filled_fields'] was: "
            f"{result['filled_fields']}"
        )

    def test_no_cross_map_when_all_systems_already_filled(self):
        """When every system has a value, cross-map is a no-op — no
        result['filled_fields'] entries should be added."""
        from scraper import hybrid_scraper

        metadata = {
            'esrb_rating': 'E', 'pegi_rating': 'PEGI 3', 'cero_rating': 'A',
            'usk_rating': '0', 'acb_rating': 'G', 'fpb_rating': 'A',
            'grac_rating': 'ALL', 'classind_rating': 'L',
        }
        result = {'filled_fields': []}
        hybrid_scraper._normalize_ratings(metadata, result)
        # No new filled_fields entries — every system already had a value.
        assert result['filled_fields'] == []

    def test_inference_fires_only_when_no_rating_present(self, monkeypatch):
        """If all rating columns are empty/None/'RP', `infer_rating_from_
        content` is called; if any have a real value, inference is skipped."""
        from scraper import hybrid_scraper

        # Stub the inference function so we control its return.
        called = []
        def _stub_infer(meta):
            called.append(dict(meta))
            return {'esrb_rating': 'E', 'pegi_rating': 'PEGI 3'}
        monkeypatch.setattr(hybrid_scraper, 'infer_rating_from_content',
                            _stub_infer)

        metadata = {
            'esrb_rating': '', 'pegi_rating': '', 'cero_rating': '',
            'usk_rating': '', 'acb_rating': '', 'fpb_rating': '',
            'grac_rating': '', 'classind_rating': '',
            'title': 'Sonic',
        }
        result = {'filled_fields': []}
        hybrid_scraper._normalize_ratings(metadata, result)
        assert len(called) == 1, "inference should fire once for empty ratings"
        assert metadata['esrb_rating'] == 'E'
        assert metadata['pegi_rating'] == 'PEGI 3'
        assert 'ratings (inferred from content)' in result['filled_fields']

    def test_rp_treated_as_empty_for_inference_check(self, monkeypatch):
        """'RP' (Rating Pending) is treated as no-rating for the
        inference-fires-when-empty gate. The inline version had this
        explicit; the helper preserves it."""
        from scraper import hybrid_scraper

        called = []
        monkeypatch.setattr(hybrid_scraper, 'infer_rating_from_content',
                            lambda m: called.append(1) or {})

        metadata = {
            'esrb_rating': 'RP', 'pegi_rating': 'rp', 'cero_rating': '',
            'usk_rating': '', 'acb_rating': '', 'fpb_rating': '',
            'grac_rating': '', 'classind_rating': '',
        }
        result = {'filled_fields': []}
        hybrid_scraper._normalize_ratings(metadata, result)
        assert called, ("'RP' / 'rp' should be treated as empty so "
                        "inference still fires")

    def test_esrb_missing_does_not_crash(self):
        """If `esrb_rating` is missing entirely (helper called from a
        partial metadata dict), `metadata.get('esrb_rating')` returns
        None and the normalize call is skipped — no AttributeError."""
        from scraper import hybrid_scraper

        metadata = {}  # no esrb_rating key at all
        result = {'filled_fields': []}
        # Should not raise:
        hybrid_scraper._normalize_ratings(metadata, result)
