"""Tests for alt_title_entry and merge_alt_titles in scraper/metadata_normalizer.py."""

import json

from scraper.metadata_normalizer import alt_title_entry, merge_alt_titles


class TestAltTitleEntry:
    def test_empty_title_returns_none(self):
        assert alt_title_entry("") is None
        assert alt_title_entry(None) is None
        assert alt_title_entry("   ") is None

    def test_plain_title(self):
        assert alt_title_entry("Rockman") == {"title": "Rockman"}

    def test_strips_whitespace(self):
        assert alt_title_entry("  Mega Man  ") == {"title": "Mega Man"}

    def test_with_region_and_source(self):
        entry = alt_title_entry("Rockman", region="JP", source="igdb")
        assert entry == {"title": "Rockman", "region": "JP", "source": "igdb"}

    def test_blank_region_dropped(self):
        entry = alt_title_entry("Rockman", region="   ", source="igdb")
        assert "region" not in entry
        assert entry["source"] == "igdb"


class TestMergeAltTitles:
    def test_empty_existing(self):
        new = [{"title": "Rockman", "region": "JP"}]
        merged = merge_alt_titles(None, new)
        assert merged == [{"title": "Rockman", "region": "JP"}]

    def test_accepts_json_string(self):
        existing = json.dumps([{"title": "Rockman", "region": "JP"}])
        new = [{"title": "Mega Man EU"}]
        merged = merge_alt_titles(existing, new)
        assert len(merged) == 2

    def test_dedupes_case_insensitive(self):
        existing = [{"title": "Rockman"}]
        new = [{"title": "rockman"}, {"title": "ROCKMAN"}, {"title": "Rockman X"}]
        merged = merge_alt_titles(existing, new)
        assert len(merged) == 2
        assert merged[0]["title"] == "Rockman"
        assert merged[1]["title"] == "Rockman X"

    def test_skips_primary_title(self):
        new = [{"title": "Mega Man"}, {"title": "Rockman"}]
        merged = merge_alt_titles(None, new, primary_title="Mega Man")
        assert merged == [{"title": "Rockman"}]

    def test_skips_primary_title_case_insensitive(self):
        new = [{"title": "mega man"}, {"title": "Rockman"}]
        merged = merge_alt_titles(None, new, primary_title="Mega Man")
        assert len(merged) == 1
        assert merged[0]["title"] == "Rockman"

    def test_malformed_existing_recovers(self):
        merged = merge_alt_titles("not json at all", [{"title": "Rockman"}])
        assert merged == [{"title": "Rockman"}]

    def test_none_new_entries(self):
        existing = [{"title": "Rockman"}]
        merged = merge_alt_titles(existing, None)
        assert merged == [{"title": "Rockman"}]

    def test_drops_entries_without_title(self):
        new = [{"region": "JP"}, {"title": ""}, None, {"title": "Rockman"}]
        merged = merge_alt_titles(None, new)
        assert merged == [{"title": "Rockman"}]

    def test_drops_existing_entries_without_title(self):
        """COV-1: the `existing` list also gets filtered for malformed
        dicts (e.g. corrupt DB rows with `region` but no `title`). The
        new-entries path was already covered; this pins the existing-
        list path too."""
        existing = [{"region": "JP"}, {"title": "Rockman"}]
        merged = merge_alt_titles(existing, [])
        assert merged == [{"title": "Rockman"}]

    def test_preserves_region_and_source(self):
        new = [
            alt_title_entry("Rockman X", region="JP", source="igdb"),
            alt_title_entry("Mega Man X", region="US", source="screenscraper"),
        ]
        merged = merge_alt_titles(None, new)
        assert merged[0]["region"] == "JP"
        assert merged[0]["source"] == "igdb"
        assert merged[1]["region"] == "US"
        assert merged[1]["source"] == "screenscraper"
