# Tests for services/formatters.py

import pytest

from services.formatters import format_size, get_manufacturer, MANUFACTURER_MAP


class TestFormatSize:
    def test_none_returns_unknown(self):
        assert format_size(None) == "Unknown"

    def test_zero_bytes(self):
        assert format_size(0) == "0.0 B"

    def test_bytes_under_kb(self):
        assert format_size(512) == "512.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(100 * 1024 * 1024) == "100.0 MB"

    def test_gigabytes(self):
        assert format_size(1024 ** 3) == "1.0 GB"
        assert format_size(50 * (1024 ** 3)) == "50.0 GB"

    def test_terabytes(self):
        assert format_size(1024 ** 4) == "1.0 TB"

    def test_petabytes_fallthrough(self):
        # Anything >= 1 PB falls through to the final PB formatting.
        result = format_size(1024 ** 5)
        assert result.endswith(" PB")


class TestGetManufacturer:
    @pytest.mark.parametrize("folder, expected", [
        ('nes', 'Nintendo'),
        ('snes', 'Nintendo'),
        ('switch', 'Nintendo'),
        ('gba', 'Nintendo'),
        ('psx', 'Sony'),
        ('ps5', 'Sony'),
        ('psvita', 'Sony'),
        ('genesis', 'Sega'),
        ('saturn', 'Sega'),
        ('dreamcast', 'Sega'),
        ('xbox', 'Microsoft'),
        ('xbox360', 'Microsoft'),
    ])
    def test_known_console_folders(self, folder, expected):
        assert get_manufacturer(folder) == expected

    def test_case_insensitive(self):
        assert get_manufacturer('NES') == 'Nintendo'
        assert get_manufacturer('Xbox360') == 'Microsoft'

    def test_unknown_folder_returns_other(self):
        assert get_manufacturer('not_a_real_system') == 'Other'

    def test_empty_folder_returns_other(self):
        assert get_manufacturer('') == 'Other'
        assert get_manufacturer(None) == 'Other'

    def test_no_duplicate_keys(self):
        """Regression for F601 duplicate-key bugs. Reparse source to catch
        the 'last wins' silent override that ruff flagged in earlier audits."""
        import ast
        # Use REPO_ROOT-anchored read_source so the test runs from any CWD —
        # the previous `Path('services/formatters.py')` would FileNotFoundError
        # when pytest was invoked from outside the repo root (test-audit
        # c-002 MED hardcoded_data).
        from tests._util import read_source
        src = read_source('services/formatters.py')
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'MANUFACTURER_MAP' for t in node.targets
            ):
                assert isinstance(node.value, ast.Dict)
                keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                assert len(keys) == len(set(keys)), \
                    f"Duplicate keys in MANUFACTURER_MAP: {[k for k in keys if keys.count(k) > 1]}"
                return
        raise AssertionError("MANUFACTURER_MAP assignment not found in formatters.py")

    def test_map_has_expected_size(self):
        """Sanity check that MANUFACTURER_MAP hasn't shrunk unexpectedly."""
        assert len(MANUFACTURER_MAP) >= 40
