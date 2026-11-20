"""Masks, preview rendering, and protected-region-constrained AI composites."""
from __future__ import annotations

from io import BytesIO
import re
from PIL import Image, ImageDraw, ImageOps

STYLES = ("solid", "noise", "mosaic")
DEFAULT_SOLID_COLOR = "#222838"


def normalize_solid_color(color: str) -> str:
    """Return opaque six-digit RGB hex; never allow transparency in concealment."""
    if not isinstance(color, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
        raise ValueError("纯色遮盖颜色必须是 #RRGGBB 格式，不支持透明度")
    return color.upper()


def solid_rgba(color: str) -> tuple[int, int, int, int]:
    c = normalize_solid_color(color)
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), 255)



def load_image(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as src:
        if getattr(src, "n_frames", 1) != 1:
            raise ValueError("Animated / multi-page inputs are not supported")
        img = ImageOps.exif_transpose(src)
        img.load()
        return img.convert("RGBA")


def binary_mask(mask: Image.Image, image_size: tuple[int, int]) -> Image.Image:
    if mask.size != image_size:
        raise ValueError(f"Selection mask must be {image_size}; got {mask.size}")
    return mask.convert("L").point(lambda v: 255 if v >= 128 else 0)


def image_to_png_bytes(img: Image.Image) -> bytes:
    bio = BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def render_preview(
    original: Image.Image, mask: Image.Image, style: str = "solid", block: int = 18,
    solid_color: str = DEFAULT_SOLID_COLOR,
) -> Image.Image:
    """Opaque concealment on selected pixels. Noise/solid do not leak source detail."""
    if style not in STYLES:
        raise ValueError(f"Unsupported concealment: {style}")
    original = original.convert("RGBA")
    mask = binary_mask(mask, original.size)
    color = solid_rgba(solid_color)  # even unused styles reject invalid configuration
    if style == "solid":
        conceal = Image.new("RGBA", original.size, color)
    elif style == "noise":
        # Independent noise, not derived from the protected image pixels.
        import os
        conceal = Image.frombytes("L", original.size, os.urandom(original.width * original.height)).convert("RGBA")
    else:
        # Pixelation is a LOW-PRIVACY visual effect: rough scene information remains.
        block = max(2, int(block))
        small = (max(1, (original.width + block - 1) // block), max(1, (original.height + block - 1) // block))
        conceal = original.resize(small, Image.Resampling.BOX).resize(original.size, Image.Resampling.NEAREST)
    return Image.composite(conceal, original, mask)


def protected_merge(original: Image.Image, ai_image: Image.Image, mask: Image.Image) -> Image.Image:
    """Write AI image ONLY to unprotected pixels. Protected pixels remain exact."""
    if original.size != ai_image.size:
        raise ValueError("AI image dimensions must match original; register externally first")
    original = original.convert("RGBA")
    ai_image = ai_image.convert("RGBA")
    mask = binary_mask(mask, original.size)
    # Mask=255 uses original, Mask=0 uses edited AI result.
    return Image.composite(original, ai_image, mask)


def rectangle_mask(size: tuple[int, int], rects: list[tuple[int, int, int, int]]) -> Image.Image:
    result = Image.new("L", size, 0)
    draw = ImageDraw.Draw(result)
    for x0, y0, x1, y1 in rects:
        draw.rectangle((x0, y0, x1, y1), fill=255)
    return result
