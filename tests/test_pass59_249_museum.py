"""PASS-59-249: controller pictures are saved where an update keeps them.

In the standalone build STATIC_PATH is inside the bundle an update replaces;
IMAGE_PATH sits beside the launcher. A source install has one folder for both."""
import io
import os

import pytest
from PIL import Image


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    import config
    user, bundle = tmp_path / 'user_images', tmp_path / 'bundle_static'
    (user / 'controllers').mkdir(parents=True)
    (bundle / 'images' / 'controllers').mkdir(parents=True)
    monkeypatch.setattr(config, 'IMAGE_PATH', str(user))
    monkeypatch.setattr(config, 'STATIC_PATH', str(bundle))
    return user / 'controllers', bundle / 'images' / 'controllers'


def _png():
    buf = io.BytesIO()
    Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(buf, 'PNG')
    return buf.getvalue()


def test_a_saved_controller_picture_goes_to_the_user_folder(two_roots, monkeypatch):
    from routes import museum
    from services import image_utils
    # The tidy step starts the GPU upscaler, which aborts the process under ROCm.
    monkeypatch.setattr(image_utils, 'standardize_downloaded_image', lambda *a, **k: None)
    user_dir, bundle_dir = two_roots
    assert museum._persist_controller_image(77, _png()) == '77.webp'
    assert (user_dir / '77.webp').is_file()
    assert not (bundle_dir / '77.webp').exists()


def test_a_shipped_picture_is_still_found(two_roots):
    from routes import museum
    user_dir, bundle_dir = two_roots
    (bundle_dir / 'pad.webp').write_bytes(b'x')
    (user_dir / 'mine.webp').write_bytes(b'x')
    assert museum._controller_image_file('pad.webp') == os.path.join(bundle_dir, 'pad.webp')
    assert museum._controller_image_file('mine.webp') == os.path.join(user_dir, 'mine.webp')
    assert museum._controller_image_file('gone.webp') is None
