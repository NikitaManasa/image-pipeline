from io import BytesIO

import pytest
from PIL import Image

from conftest import make_image
from pipeline.images import InvalidImage, process_image


def open_webp(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    assert image.format == "WEBP"
    return image


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_supported_formats_produce_both_renditions(fmt):
    result = process_image(make_image(fmt, size=(1600, 900)))

    assert (result.width, result.height, result.format) == (1600, 900, fmt)
    assert open_webp(result.renditions[256]).size == (256, 144)  # aspect ratio kept
    assert open_webp(result.renditions[1024]).size == (1024, 576)


def test_small_images_are_not_upscaled():
    result = process_image(make_image("PNG", size=(100, 50)))

    assert open_webp(result.renditions[1024]).size == (100, 50)


def test_transparency_is_kept():
    result = process_image(make_image("PNG", size=(300, 300), mode="RGBA"))

    assert open_webp(result.renditions[256]).mode == "RGBA"


def test_exif_metadata_is_stripped():
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make; real photos carry GPS coordinates here too
    result = process_image(make_image("JPEG", exif=exif.tobytes()))

    for blob in result.renditions.values():
        assert b"SecretCameraMaker" not in blob
        assert not open_webp(blob).getexif()


def test_exif_orientation_is_applied_before_stripping():
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90° clockwise", as phones save portrait photos
    result = process_image(make_image("JPEG", size=(400, 200), exif=exif.tobytes()))

    assert open_webp(result.renditions[1024]).size == (200, 400)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"definitely not an image", "not a valid image"),
        (b"%PDF-1.7 pretending to be a jpeg", "not a valid image"),
        (make_image("GIF", size=(10, 10), mode="P"), "unsupported format GIF"),
        (make_image("JPEG")[:500], "corrupt image"),
    ],
)
def test_rejects_bad_files(data, message):
    with pytest.raises(InvalidImage, match=message):
        process_image(data)


def test_rejects_decompression_bomb():
    # 7000x7000 1-bit PNG: a few KB on disk, 49 megapixels when decoded.
    bomb = make_image("PNG", size=(7000, 7000), mode="1")
    assert len(bomb) < 100_000

    with pytest.raises(InvalidImage, match="too large"):
        process_image(bomb)
