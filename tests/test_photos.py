import io
from datetime import datetime

import pytest
from PIL import Image

from troupe_bot.photos import (
    ImageRejected,
    make_thumbnail,
    normalize_image,
    photo_paths,
    sanitize_name_part,
)


def png_bytes(size=(40, 30), mode="RGBA", color=(200, 30, 30, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_with_exif(size=(60, 40)) -> bytes:
    img = Image.new("RGB", size, (10, 120, 10))
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


# ------------------------------------------------------------ 圖片驗證與轉檔


def test_png_with_alpha_becomes_rgb_jpeg():
    out = normalize_image(png_bytes())
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.mode == "RGB"


def test_long_edge_is_capped_at_2048():
    out = normalize_image(png_bytes(size=(3000, 1000), mode="RGB", color=(1, 2, 3)))
    assert max(Image.open(io.BytesIO(out)).size) == 2048


def test_exif_is_stripped():
    assert b"SecretCameraMaker" in jpeg_with_exif()
    assert b"SecretCameraMaker" not in normalize_image(jpeg_with_exif())


@pytest.mark.parametrize("bad", [b"", b"hello world", b"%PDF-1.4 fake", b"\x89PNG\r\n\x1a\n broken"])
def test_non_image_bytes_are_rejected(bad):
    with pytest.raises(ImageRejected):
        normalize_image(bad)


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_absurdly_large_dimensions_are_rejected_before_decoding():
    big = png_bytes(size=(9000, 9000), mode="L", color=0)
    with pytest.raises(ImageRejected):
        normalize_image(big)


def test_thumbnail_long_edge_is_at_most_150():
    jpeg = normalize_image(png_bytes(size=(800, 400), mode="RGB", color=(5, 5, 5)))
    thumb = Image.open(io.BytesIO(make_thumbnail(jpeg)))
    assert max(thumb.size) <= 150 and thumb.format == "JPEG"


# ------------------------------------------------------------ 檔名清洗


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("青花瓷瓶", "青花瓷瓶"),
        ("../../evil", "evil"),
        ("..\\..\\evil", "evil"),
        ("a:b*c?d", "abcd"),
        ('say "hi" <x>|y', "say hi xy"),
        ("tab\there\x00", "tabhere"),
        ("花瓶.", "花瓶"),
        ("  .. ", "未命名"),
        ("", "未命名"),
        ("CON", "_CON"),
        ("com1", "_com1"),
    ],
)
def test_sanitize_name_part(raw, expected):
    assert sanitize_name_part(raw) == expected


def test_sanitize_limits_length_and_normalizes_fullwidth():
    assert len(sanitize_name_part("長" * 100)) == 20
    assert sanitize_name_part("ＡＢＣ") == "ABC"


# ------------------------------------------------------------ 照片檔名與路徑

WHEN = datetime(2026, 10, 22, 14, 5, 9)


def test_filename_format(tmp_path):
    [p] = photo_paths(tmp_path, WHEN, "小道具", "青花瓷瓶", 1)
    assert p == tmp_path / "2026-10-22 14-05-09 小道具 青花瓷瓶.jpg"


def test_several_photos_of_one_item_get_dash_numbers(tmp_path):
    names = [p.name for p in photo_paths(tmp_path, WHEN, "服裝", "鳳冠", 3)]
    assert names == [
        "2026-10-22 14-05-09 服裝 鳳冠.jpg",
        "2026-10-22 14-05-09 服裝 鳳冠-2.jpg",
        "2026-10-22 14-05-09 服裝 鳳冠-3.jpg",
    ]


def test_existing_file_in_the_same_second_pushes_to_next_number(tmp_path):
    (tmp_path / "2026-10-22 14-05-09 服裝 鳳冠.jpg").write_bytes(b"x")
    (tmp_path / "2026-10-22 14-05-09 服裝 鳳冠-2.jpg").write_bytes(b"x")
    [p] = photo_paths(tmp_path, WHEN, "服裝", "鳳冠", 1)
    assert p.name == "2026-10-22 14-05-09 服裝 鳳冠-3.jpg"


def test_traversal_in_name_cannot_escape_photo_folder(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    paths = photo_paths(photos, WHEN, "小道具", "..\\..\\..\\evil/../x", 2)
    for p in paths:
        assert p.resolve().parent == photos.resolve()
