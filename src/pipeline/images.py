"""Pure image processing: no AWS here, so it is easy to test.

Treats every upload as hostile: checks the real file format (not the claimed content type),
rejects decompression bombs, and re-encodes the image, which drops EXIF metadata such as
GPS location.
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
RENDITION_SIZES = (256, 1024)
MAX_PIXELS = 40_000_000  # ~ 8000 x 5000; larger is almost certainly an attack or a mistake

Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # make Pillow itself refuse anything bigger, before decoding


class InvalidImage(Exception):
    """Permanent problem with the file; retrying will never help."""


@dataclass(frozen=True)
class ProcessedImage:
    width: int
    height: int
    format: str
    renditions: dict[int, bytes]  # longest side in px -> WebP bytes


def process_image(data: bytes) -> ProcessedImage:
    try:
        with Image.open(BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise InvalidImage(f"unsupported format {fmt}")
            if width * height > MAX_PIXELS:
                raise InvalidImage(f"image too large ({width}x{height})")
            probe.verify()  # detects truncated / corrupt files

        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # honour phone camera orientation before dropping EXIF
            renditions = {size: _rendition(image, size) for size in RENDITION_SIZES}
    except InvalidImage:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise InvalidImage(f"not a valid image: {exc}") from exc
    except (OSError, SyntaxError, ValueError) as exc:  # what Pillow raises for corrupt data
        raise InvalidImage(f"corrupt image: {exc}") from exc

    return ProcessedImage(width=width, height=height, format=fmt, renditions=renditions)


def _rendition(image: Image.Image, size: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((size, size))  # keeps aspect ratio, never upscales
    if copy.mode not in ("RGB", "RGBA"):
        copy = copy.convert("RGBA" if "transparency" in copy.info or copy.mode in ("LA", "PA") else "RGB")
    out = BytesIO()
    copy.save(out, format="WEBP", quality=80, method=4)  # no exif= argument, so metadata is not copied
    return out.getvalue()
