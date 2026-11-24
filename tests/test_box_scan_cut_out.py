"""A disc or cartridge scan is taken off its plain backdrop: the backdrop goes
see-through and the picture is trimmed to the object (services/box_scans.cut_out)."""
from PIL import Image, ImageDraw

from services import box_scans


def _disc(path, backdrop=(255, 255, 255), label=(200, 30, 30)):
    image = Image.new('RGB', (400, 380), backdrop)
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 40, 350, 340), fill=label)        # a 300 px disc
    draw.ellipse((185, 175, 215, 205), fill=backdrop)   # its hole
    image.save(path, 'WEBP', quality=95)


def test_a_disc_on_white_is_cut_to_a_circle_and_trimmed(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    _disc(path)
    assert box_scans.cut_out(path) is True
    with Image.open(path) as image:
        assert image.mode == 'RGBA'
        assert abs(image.width - 300) <= 3 and abs(image.height - 300) <= 3
        assert image.getpixel((2, 2))[3] == 0                      # corner gone
        assert image.getpixel((image.width // 2, 20))[3] == 255     # label kept
        assert image.getpixel((image.width // 2, image.height // 2))[3] == 255  # hole is the hub's


def test_a_white_rim_on_the_disc_stays(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    image = Image.new('RGB', (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 50, 350, 350), fill=(120, 120, 120))
    draw.ellipse((60, 60, 340, 340), fill=(255, 255, 255))   # white label to the rim
    draw.ellipse((150, 150, 250, 250), fill=(0, 0, 200))
    image.save(path, 'WEBP', quality=95)
    assert box_scans.cut_out(path) is True
    with Image.open(path) as cut:
        assert cut.getpixel((cut.width // 2, 30))[3] == 255


def test_a_black_backdrop_goes_too(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    _disc(path, backdrop=(10, 10, 10))
    assert box_scans.cut_out(path) is True
    with Image.open(path) as image:
        assert image.getpixel((2, 2))[3] == 0


def test_a_cartridge_keeps_its_shape_and_its_white_label(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    image = Image.new('RGB', (500, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 50, 400, 350), fill=(60, 60, 60))
    draw.rectangle((140, 90, 360, 250), fill=(255, 255, 255))   # white label, enclosed
    image.save(path, 'WEBP', quality=95)
    assert box_scans.cut_out(path) is True
    with Image.open(path) as image:
        cut = image.convert('RGBA')
        assert abs(cut.width - 301) <= 3 and abs(cut.height - 301) <= 3
        assert cut.getpixel((2, 2))[3] == 255                       # square corner kept
        assert cut.getpixel((cut.width // 2, 100))[3] == 255        # label kept


def test_a_disc_whose_label_matches_its_backdrop_stays_whole(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    image = Image.new('RGB', (400, 400), (90, 90, 90))
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 50, 350, 350), fill=(30, 30, 30))      # a dark rim
    draw.ellipse((56, 56, 344, 344), fill=(95, 95, 95))      # grey like the backdrop
    draw.rectangle((180, 60, 220, 340), fill=(200, 20, 20))
    image.save(path, 'WEBP', quality=95)
    assert box_scans.cut_out(path) is True
    with Image.open(path) as cut:
        assert cut.getpixel((80, cut.height // 2))[3] == 255
        assert cut.getpixel((2, 2))[3] == 0


def test_a_cartridge_on_black_is_left_alone(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    image = Image.new('RGB', (500, 400), (5, 5, 5))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 50, 400, 350), fill=(10, 10, 10))   # a black shell
    draw.rectangle((140, 90, 360, 250), fill=(240, 240, 240))
    image.save(path, 'WEBP', quality=95)
    before = open(path, 'rb').read()
    assert box_scans.cut_out(path) is False
    assert open(path, 'rb').read() == before


def test_a_second_cut_changes_nothing(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    _disc(path)
    assert box_scans.cut_out(path) is True
    assert box_scans.cut_out(path) is False


def test_a_photo_with_no_plain_backdrop_is_left_alone(tmp_path):
    path = str(tmp_path / '1_media_0_ab.webp')
    image = Image.linear_gradient('L').convert('RGB').resize((300, 300))
    image.save(path, 'WEBP')
    before = open(path, 'rb').read()
    assert box_scans.cut_out(path) is False
    assert open(path, 'rb').read() == before


def test_only_media_names_are_disc_pictures():
    assert box_scans.is_media_name('4_media_0_ab.webp')
    assert not box_scans.is_media_name('4_front_0_ab.webp')


def test_stored_discs_are_cut_once_and_other_scans_left(tmp_path, monkeypatch):
    monkeypatch.setattr(box_scans, 'scans_dir', lambda: str(tmp_path))
    _disc(str(tmp_path / '1_media_0_ab.webp'))
    _disc(str(tmp_path / '1_front_0_ab.webp'))
    record = ('{"version": 1, "mobygames": {"items": ['
              '{"kind": "media", "file": "1_media_0_ab.webp"},'
              '{"kind": "front", "file": "1_front_0_ab.webp"}]}}')
    front = (tmp_path / '1_front_0_ab.webp').read_bytes()
    assert box_scans.cut_out_stored(record) == 1
    assert (tmp_path / '1_front_0_ab.webp').read_bytes() == front
    assert box_scans.cut_out_stored(record) == 0
