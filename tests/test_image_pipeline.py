# Tests for the Pass 18 image pipeline — pins the WebP-on-ingest + format
# normalization + responsive variant contract so future refactors don't
# silently drop WebP conversion or break srcset emission.

import io

import pytest
from PIL import Image

import config
from services import image_utils
from services.image_utils import (
    _ensure_format_matches_extension,
    _make_responsive_variants,
    boxart_srcset,
    finalize_downloaded_image,
)


@pytest.fixture(scope='module')
def jpeg_bytes():
    """Raw JPEG payload for a trivial test image.

    Module-scoped — these payloads are read-only and consumed by ~4 tests;
    function scope re-encoded the 800x1120 image 4× (5-15 ms each) per
    pytest invocation (test-audit c-003 LOW performance)."""
    buf = io.BytesIO()
    Image.new('RGB', (800, 1120), color=(200, 100, 50)).save(buf, format='JPEG', quality=85)
    return buf.getvalue()


@pytest.fixture(scope='module')
def png_bytes():
    """Same module-scope rationale as `jpeg_bytes` above."""
    buf = io.BytesIO()
    Image.new('RGBA', (800, 1120), color=(0, 0, 255, 255)).save(buf, format='PNG')
    return buf.getvalue()


class TestPreferredImageExtension:
    """`preferred_image_extension` drives the on-ingest format decision."""

    # Six near-identical test methods collapsed into one parametrize
    # block (test-audit c-003 MED). The `test_gif_always_preserved`
    # case stays standalone because it warrants a dedicated docstring
    # explaining the multi-frame-loss risk on Pillow's WebP save path.
    @pytest.mark.parametrize("img_format,img_type,ext_in,ext_out", [
        ('webp', 'boxart', '.jpg', '.webp'),
        ('webp', 'screenshots', '.png', '.webp'),
        ('jpeg', 'boxart', '.jpg', '.jpg'),
        ('jpeg', 'boxart', '.png', '.jpg'),
        ('webp', 'video', '.mp4', '.mp4'),
        ('webp', 'manual', '.pdf', '.pdf'),
        ('webp', 'boxart', 'jpg', '.webp'),  # no-leading-dot input
    ])
    def test_format_decision(self, monkeypatch, img_format, img_type, ext_in, ext_out):
        monkeypatch.setattr(config, 'IMAGE_FORMAT', img_format, raising=False)
        assert image_utils.preferred_image_extension(img_type, ext_in) == ext_out

    def test_gif_always_preserved(self, monkeypatch):
        """Animated GIFs must survive the pipeline unchanged — re-encoding as
        WebP here would silently drop all frames beyond the first on Pillow
        versions that default to single-frame WebP save."""
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        assert image_utils.preferred_image_extension('boxart', '.gif') == '.gif'


class TestFormatNormalize:
    """Re-encoding when on-disk bytes don't match filename extension."""

    def test_jpeg_written_to_webp_path_is_reencoded(self, tmp_path, jpeg_bytes):
        # JPEG payload under a .webp filename (simulating the on-ingest flow
        # where the caller chose the target format via the path alone).
        path = tmp_path / 'foo.webp'
        path.write_bytes(jpeg_bytes)

        _ensure_format_matches_extension(str(path))

        with Image.open(path) as img:
            assert img.format == 'WEBP'

    def test_matching_format_is_noop(self, tmp_path):
        path = tmp_path / 'foo.webp'
        Image.new('RGB', (10, 10)).save(path, format='WEBP')
        before = path.read_bytes()

        _ensure_format_matches_extension(str(path))

        # Bytes must be untouched — avoids a write/mtime bump on every finalize.
        assert path.read_bytes() == before

    def test_unknown_extension_is_skipped(self, tmp_path, jpeg_bytes):
        path = tmp_path / 'foo.bmp'
        path.write_bytes(jpeg_bytes)
        _ensure_format_matches_extension(str(path))
        # File should be left untouched (no PIL re-save attempted).
        assert path.read_bytes() == jpeg_bytes

    def test_unidentified_image_error_handled(self, tmp_path):
        """COV-3: PIL.UnidentifiedImageError on corrupt bytes must be
        swallowed — the function logs and returns without raising. A
        regression that lets the exception escape would crash every
        finalize call for a malformed download."""
        path = tmp_path / 'bad.webp'
        path.write_bytes(b'not a real image, just garbage')

        # Must not raise. The corrupt file is left on disk untouched —
        # the caller's later logic will handle the missing valid image.
        _ensure_format_matches_extension(str(path))

        assert path.exists()
        assert path.read_bytes() == b'not a real image, just garbage'


class TestResponsiveVariants:
    """`-sm` and `-md` sibling generation for boxart."""

    def test_variants_written_for_boxart(self, tmp_path):
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
        path = tmp_path / 'small.webp'
        Image.new('RGB', (120, 160)).save(path, format='WEBP')
        _make_responsive_variants(str(path), 'boxart')

        # -sm (160w) and -md (320w) both >= source width → both skipped.
        assert not (tmp_path / 'small-sm.webp').exists()
        assert not (tmp_path / 'small-md.webp').exists()

    def test_screenshots_skip_variants(self, tmp_path):
        """Only boxart-family types get variants; screenshots don't."""
        path = tmp_path / 'shot.webp'
        Image.new('RGB', (1920, 1080)).save(path, format='WEBP')
        _make_responsive_variants(str(path), 'screenshots')
        assert not (tmp_path / 'shot-sm.webp').exists()
        assert not (tmp_path / 'shot-md.webp').exists()


@pytest.fixture
def boxart_with_files(tmp_path, monkeypatch):
    """Shared setup for srcset tests: redirect IMAGE_PATH at tmp_path,
    make a boxart/ dir, and let the caller drop variant files into it.
    Returns (boxart_dir, write_variant) where write_variant(name, w, h)
    writes a WebP at `boxart_dir/name` of the given dimensions.
    """
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)
    boxart_dir = tmp_path / 'boxart'
    boxart_dir.mkdir()

    def write_variant(name, width, height):
        Image.new('RGB', (width, height)).save(boxart_dir / name, format='WEBP')

    return boxart_dir, write_variant


class TestBoxartSrcset:
    """Server-side srcset builder used by the detail-page hero `<img>`."""

    def test_emits_candidates_when_variants_exist(self, boxart_with_files):
        _, write_variant = boxart_with_files
        write_variant('g.webp', 800, 1120)
        write_variant('g-sm.webp', 160, 224)
        write_variant('g-md.webp', 320, 448)

        srcset = image_utils.boxart_srcset('g.webp')
        assert 'g-sm.webp 160w' in srcset
        assert 'g-md.webp 320w' in srcset
        # Original always included so a too-large viewport still has a choice.
        assert 'g.webp' in srcset

    def test_empty_for_missing_boxart(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp', raising=False)
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)
        (tmp_path / 'boxart').mkdir()
        assert image_utils.boxart_srcset('does-not-exist.webp') == ''

    def test_empty_for_none_or_empty_string(self):
        assert boxart_srcset(None) == ''
        assert boxart_srcset('') == ''

    def test_skips_missing_variant_siblings(self, boxart_with_files):
        """If `-sm` is missing but `-md` exists, srcset must include only `-md`
        plus the original — never emit a candidate URL that would 404."""
        _, write_variant = boxart_with_files
        write_variant('g.webp', 800, 1120)
        write_variant('g-md.webp', 320, 448)

        srcset = image_utils.boxart_srcset('g.webp')
        assert 'g-sm.webp' not in srcset
        assert 'g-md.webp 320w' in srcset

    def test_batch_mode_uses_existing_set_no_pil(self, boxart_with_files, monkeypatch):
        """Pass FU.2 — batch mode skips per-file os.path.exists + PIL.open
        so a 500-card render does N set-membership checks, not N stat calls."""
        _, write_variant = boxart_with_files
        write_variant('g.webp', 800, 1120)
        write_variant('g-sm.webp', 160, 224)
        # Note: no g-md.webp on disk.

        # Trip-wire: any PIL.Image.open call in batch mode is a perf regression.
        from PIL import Image as _PIL
        opens = []
        original_open = _PIL.open
        monkeypatch.setattr(_PIL, 'open', lambda *a, **kw: opens.append(a) or original_open(*a, **kw))

        existing = {'g.webp', 'g-sm.webp'}
        srcset = image_utils.boxart_srcset('g.webp', existing=existing)

        assert opens == [], "batch mode must not call PIL.Image.open"
        assert 'g-sm.webp 160w' in srcset
        assert 'g-md.webp' not in srcset
        assert 'g.webp 760w' in srcset  # batch mode uses 760 fallback width

    def test_batch_mode_empty_when_filename_absent(self):
        """Filename missing from the existence set → '' (no candidate emitted)."""
        assert image_utils.boxart_srcset('gone.webp', existing={'a.webp', 'b.webp'}) == ''

    def test_boxart_dir_listing_scandir(self, boxart_with_files):
        boxart_dir, write_variant = boxart_with_files
        write_variant('a.webp', 800, 1120)
        write_variant('b.webp', 800, 1120)
        listing = image_utils.boxart_dir_listing('boxart')
        assert 'a.webp' in listing
        assert 'b.webp' in listing
        # Subdir entries are excluded by the is_file() guard.
        (boxart_dir / 'sub').mkdir()
        listing = image_utils.boxart_dir_listing('boxart')
        assert 'sub' not in listing

    def test_boxart_3d_image_type(self, tmp_path, monkeypatch):
        """`image_type='boxart_3d'` resolves the right subdir + URL prefix."""
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path), raising=False)
        boxart_3d_dir = tmp_path / 'boxart_3d'
        boxart_3d_dir.mkdir()
        Image.new('RGB', (800, 1120)).save(boxart_3d_dir / 'g.webp', format='WEBP')
        Image.new('RGB', (160, 224)).save(boxart_3d_dir / 'g-sm.webp', format='WEBP')

        srcset = image_utils.boxart_srcset(
            'g.webp',
            image_type='boxart_3d',
            existing={'g.webp', 'g-sm.webp'},
        )
        assert '/static/images/boxart_3d/g-sm.webp 160w' in srcset
        assert '/static/images/boxart/g.webp' not in srcset


class TestFinalizePipeline:
    """Full post-download pipeline: normalize + standardize + variants."""

    def test_jpeg_bytes_to_webp_path_full_pipeline(self, tmp_path, monkeypatch, jpeg_bytes):
        """End-to-end: bytes arrive as JPEG but path is `.webp` → ingest writes
        WebP, standardizes size, generates `-sm` / `-md` siblings."""
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


class TestGpuFallbackWarning:
    """`_gpu_fallback_warning` turns a silent GPU->CPU fallback (e.g. a missing
    librocsolver.so.0 after a ROCm upgrade) into an actionable pointer at the
    repair script. Pins the detection so the diagnostic doesn't regress."""

    def test_warns_when_rocm_requested_but_not_active(self):
        msg = image_utils._gpu_fallback_warning(
            ['ROCMExecutionProvider', 'CPUExecutionProvider'],
            ['CPUExecutionProvider'],
        )
        assert msg is not None
        assert 'ROCMExecutionProvider' in msg
        # Must name the repair script so recovery is one command.
        assert image_utils._ROCM_REPAIR_SCRIPT in msg

    def test_silent_when_rocm_activated(self):
        assert image_utils._gpu_fallback_warning(
            ['ROCMExecutionProvider', 'CPUExecutionProvider'],
            ['ROCMExecutionProvider', 'CPUExecutionProvider'],
        ) is None

    def test_silent_when_cpu_only_requested(self):
        # No GPU requested (CPU-only host / disabled GPU) — nothing to warn about.
        assert image_utils._gpu_fallback_warning(
            ['CPUExecutionProvider'], ['CPUExecutionProvider'],
        ) is None

    def test_warns_for_cuda_too(self):
        msg = image_utils._gpu_fallback_warning(
            ['CUDAExecutionProvider', 'CPUExecutionProvider'],
            ['CPUExecutionProvider'],
        )
        assert msg is not None and 'CUDAExecutionProvider' in msg
