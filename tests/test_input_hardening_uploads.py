# Pass 25 — input hardening / SSRF / size caps regression coverage.
#
# Each class pins one sub-item's invariant. These are narrow unit checks —
# they're not trying to reproduce the full end-to-end flow, only to ensure
# the guard is in place and rejects the value it's supposed to reject.
#
# Split by subsystem so the Flask app import only fires where a test needs it:
#   test_input_hardening_app.py      — 25.2 reports whitelist, 25.9 rate limits
#   test_input_hardening_scrapers.py — 25.1 ES-DE path traversal, 25.7 download caps
#   test_input_hardening_museum.py   — 25.3 SSRF guard, 25.4 upload cap
#   test_input_hardening_uploads.py  — 25.5 CLZ PDF bounds, 25.6 video cap, 25.8 row caps

from unittest.mock import MagicMock

from tests._util import slice_function, read_module_source


# 25.5 — CLZ PDF page-cap + temp cleanup
# --------------------------------------
class TestCLZPDFBounds:
    def test_max_pages_constant_exists(self):
        import config
        assert hasattr(config, 'CLZ_PDF_MAX_PAGES')
        assert config.CLZ_PDF_MAX_PAGES > 0

    def test_try_finally_cleanup(self):
        """The route now wraps pdfplumber.open in try/finally so tmp_path
        is deleted on exception paths, not just success paths.

        Slice the api_clz_parse body so the assertion can't pass on
        unrelated try/finally blocks elsewhere in the file (clz_import
        has at least two `finally:` blocks — lines 412 and 646).
        """
        import routes.clz_import as mod
        src = read_module_source(mod)
        slice_src = slice_function(src, 'api_clz_parse')
        assert slice_src, 'api_clz_parse not found in routes/clz_import.py'
        assert 'finally:' in slice_src
        assert 'os.unlink(tmp_path)' in slice_src


# 25.6 — MAX_VIDEO_SIZE
# ---------------------
class TestVideoUploadCap:
    def test_max_video_size_enforced(self):
        import config
        assert hasattr(config, 'MAX_VIDEO_SIZE')

        # Direct unit test: save_upload with a video-extension file and
        # content_length > MAX_VIDEO_SIZE must return None without writing.
        from services import game_media_service
        fs = MagicMock()
        fs.filename = 'test.mp4'
        fs.content_length = config.MAX_VIDEO_SIZE + 1
        result = game_media_service.save_upload(
            fs, '/tmp/nonexistent', 1, 'custom', game_media_service.ALLOWED_VIDEO_EXT,
        )
        assert result is None


# 25.8 — List-endpoint row caps
# ------------------------------
class TestListRowCaps:
    def test_max_list_rows_constant(self):
        import config
        assert hasattr(config, 'MAX_LIST_ROWS')
        assert config.MAX_LIST_ROWS >= 10
