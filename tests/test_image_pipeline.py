# Tests for the Pass 18 image pipeline — pins the WebP-on-ingest + format
# normalization + responsive variant contract so future refactors don't
# silently drop WebP conversion or break srcset emission.

import io

import pytest
from PIL import Image


@pytest.fixture
def jpeg_bytes():
    """Raw JPEG payload for a trivial test image."""
    buf = io.BytesIO()
    Image.new('RGB', (800, 1120), color=(200, 100, 50)).save(buf, format='JPEG', quality=85)
    return buf.getvalue()


@pytest.fixture
def png_bytes():
    buf = io.BytesIO()
    Image.new('RGBA', (800, 1120), color=(0, 0, 255, 255)).save(buf, format='PNG')
    return buf.getvalue()


class TestPreferredImageExtension:
    """`preferred_image_extension` drives the on-ingest format decision."""

    def test_webp_mode_boxart(self, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('boxart', '.jpg') == '.webp'

    def test_webp_mode_screenshots(self, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('screenshots', '.png') == '.webp'

    def test_jpeg_mode_keeps_jpg(self, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'jpeg', raising=False)
        assert image_utils.preferred_image_extension('boxart', '.jpg') == '.jpg'

    def test_jpeg_mode_downgrades_png(self, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'jpeg', raising=False)
        assert image_utils.preferred_image_extension('boxart', '.png') == '.jpg'

    def test_gif_always_preserved(self, monkeypatch):
        """Animated GIFs must survive the pipeline unchanged — re-encoding as
        WebP here would silently drop all frames beyond the first on Pillow
        versions that default to single-frame WebP save."""
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('boxart', '.gif') == '.gif'

    def test_video_type_passthrough(self, monkeypatch):
        """Videos and manuals aren't convertible image types."""
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('video', '.mp4') == '.mp4'
        assert image_utils.preferred_image_extension('manual', '.pdf') == '.pdf'

    def test_accepts_ext_without_dot(self, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('boxart', 'jpg') == '.webp'


class TestFormatNormalize:
    """Re-encoding when on-disk bytes don't match filename extension."""

    def test_jpeg_written_to_webp_path_is_reencoded(self, tmp_path, jpeg_bytes):
        from services.image_utils import _ensure_format_matches_extension
        # JPEG payload under a .webp filename (simulating the on-ingest flow
        # where the caller chose the target format via the path alone).
        path = tmp_path / 'foo.webp'
        path.write_bytes(jpeg_bytes)

        _ensure_format_matches_extension(str(path))

        with Image.open(path) as img:
            assert img.format == 'WEBP'

    def test_matching_format_is_noop(self, tmp_path):
        from services.image_utils import _ensure_format_matches_extension
        path = tmp_path / 'foo.webp'
        Image.new('RGB', (10, 10)).save(path, format='WEBP')
        before = path.read_bytes()

        _ensure_format_matches_extension(str(path))

        # Bytes must be untouched — avoids a write/mtime bump on every finalize.
        assert path.read_bytes() == before

    def test_unknown_extension_is_skipped(self, tmp_path, jpeg_bytes):
        from services.image_utils import _ensure_format_matches_extension
        path = tmp_path / 'foo.bmp'
        path.write_bytes(jpeg_bytes)
        _ensure_format_matches_extension(str(path))
        # File should be left untouched (no PIL re-save attempted).
        assert path.read_bytes() == jpeg_bytes


class TestResponsiveVariants:
    """`-sm` and `-md` sibling generation for boxart."""

    def test_variants_written_for_boxart(self, tmp_path):
        from services.image_utils import _make_responsive_variants

        path = tmp_path / 'game.webp'
        Image.new('RGB', (800, 1120), color='blue').save(path, format='WEBP')
        _make_responsive_variants(str(path), 'boxart')

        sm = tmp_path / 'game-sm.webp'
        md = tmp_path / 'game-md.webp'
        assert sm.exists(), '-sm variant must be written'
        assert md.exists(), '-md variant must be written'

        with Image.open(sm) as img:
            assert img.width == 160
        with Image.open(md) as img:
            assert img.width == 320

    def test_variants_skipped_for_small_source(self, tmp_path):
        """Source narrower than a variant target must NOT be upscaled."""
        from services.image_utils import _make_responsive_variants

        path = tmp_path / 'small.webp'
        Image.new('RGB', (120, 160)).save(path, format='WEBP')
        _make_responsive_variants(str(path), 'boxart')

        # -sm (160w) and -md (320w) both >= source width → both skipped.
        assert not (tmp_path / 'small-sm.webp').exists()
        assert not (tmp_path / 'small-md.webp').exists()

    def test_screenshots_skip_variants(self, tmp_path):
        """Only boxart-family types get variants; screenshots don't."""
        from services.image_utils import _make_responsive_variants

        path = tmp_path / 'shot.webp'
        Image.new('RGB', (1920, 1080)).save(path, format='WEBP')
        _make_responsive_variants(str(path), 'screenshots')
        assert not (tmp_path / 'shot-sm.webp').exists()
        assert not (tmp_path / 'shot-md.webp').exists()


class TestBoxartSrcset:
    """Server-side srcset builder used by the detail-page hero `<img>`."""

    def test_emits_candidates_when_variants_exist(self, tmp_path, monkeypatch):
        import config
        from services import image_utils
        # Redirect IMAGE_PATH at the module that `boxart_srcset` reads it from.
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)

        boxart_dir = tmp_path / 'boxart'
        boxart_dir.mkdir()
        Image.new('RGB', (800, 1120)).save(boxart_dir / 'g.webp', format='WEBP')
        Image.new('RGB', (160, 224)).save(boxart_dir / 'g-sm.webp', format='WEBP')
        Image.new('RGB', (320, 448)).save(boxart_dir / 'g-md.webp', format='WEBP')

        srcset = image_utils.boxart_srcset('g.webp')
        assert 'g-sm.webp 160w' in srcset
        assert 'g-md.webp 320w' in srcset
        # Original always included so a too-large viewport still has a choice.
        assert 'g.webp' in srcset

    def test_empty_for_missing_boxart(self, tmp_path, monkeypatch):
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)
        (tmp_path / 'boxart').mkdir()
        assert image_utils.boxart_srcset('does-not-exist.webp') == ''

    def test_empty_for_none_or_empty_string(self):
        from services.image_utils import boxart_srcset
        assert boxart_srcset(None) == ''
        assert boxart_srcset('') == ''

    def test_skips_missing_variant_siblings(self, tmp_path, monkeypatch):
        """If `-sm` is missing but `-md` exists, srcset must include only `-md`
        plus the original — never emit a candidate URL that would 404."""
        import config
        from services import image_utils
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)

        boxart_dir = tmp_path / 'boxart'
        boxart_dir.mkdir()
        Image.new('RGB', (800, 1120)).save(boxart_dir / 'g.webp', format='WEBP')
        Image.new('RGB', (320, 448)).save(boxart_dir / 'g-md.webp', format='WEBP')

        srcset = image_utils.boxart_srcset('g.webp')
        assert 'g-sm.webp' not in srcset
        assert 'g-md.webp 320w' in srcset


class TestFinalizePipeline:
    """Full post-download pipeline: normalize + standardize + variants."""

    def test_jpeg_bytes_to_webp_path_full_pipeline(self, tmp_path, monkeypatch, jpeg_bytes):
        """End-to-end: bytes arrive as JPEG but path is `.webp` → ingest writes
        WebP, standardizes size, generates `-sm` / `-md` siblings."""
        from services.image_utils import finalize_downloaded_image

        boxart_dir = tmp_path / 'boxart'
        boxart_dir.mkdir()
        path = boxart_dir / 'game.webp'
        path.write_bytes(jpeg_bytes)

        # Keep standardize from trying to load Real-ESRGAN in CI — our 800x1120
        # source is within the 80%-120% band of the 1080 target, so standardize
        # is a no-op anyway.  Just in case, block the upscaler.
        monkeypatch.setattr('services.image_utils._get_upscaler', lambda: None)

        finalize_downloaded_image(str(path), 'boxart')

        with Image.open(path) as img:
            assert img.format == 'WEBP'

        assert (boxart_dir / 'game-sm.webp').exists()
        assert (boxart_dir / 'game-md.webp').exists()
