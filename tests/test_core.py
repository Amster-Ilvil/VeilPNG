from io import BytesIO
import json
import struct

import pytest
from cryptography.exceptions import InvalidTag
from PIL import Image, ImageDraw

from veilpng.core import (
    inspect_container, merge_ai_preview, preview_only, repack_preview,
    seal_bytes, unseal_bytes,
)
from veilpng.crypto import KDFParams
from veilpng.imaging import image_to_png_bytes, load_image, rectangle_mask, render_preview
from veilpng.png_container import ContainerError, extract_private_chunk, strip_private_chunk

FAST_KDF = KDFParams(memory_kib=8192, time_cost=1, parallelism=1)
PASSWORD = "test-password-strong-123!"


@pytest.fixture
def original():
    im = Image.new("RGBA", (96, 64), (20, 70, 120, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((18, 12, 62, 44), fill=(239, 35, 60, 255))
    d.ellipse((42, 12, 76, 50), fill=(200, 240, 20, 210))
    return image_to_png_bytes(im)


@pytest.fixture
def mask():
    return rectangle_mask((96, 64), [(17, 11, 62, 45)])


@pytest.fixture
def sealed(original, mask):
    return seal_bytes(original, "原始测试.png", mask, PASSWORD, "solid", kdf=FAST_KDF)


def test_normal_png_preview_is_viewable_and_private_chunk_exists(sealed):
    with Image.open(BytesIO(sealed)) as img:
        img.load()
        assert img.size == (96, 64)
        assert img.getpixel((25, 25)) == (34, 40, 56, 255)
        assert img.getpixel((4, 4)) == (20, 70, 120, 255)
    assert extract_private_chunk(sealed) is not None
    assert inspect_container(sealed)["original_preview_unchanged"] is True


def test_bit_exact_original_recovery(sealed, original, mask):
    asset = unseal_bytes(sealed, PASSWORD)
    assert asset.original_bytes == original
    assert asset.filename == "原始测试.png"
    assert asset.mask.tobytes() == mask.tobytes()


def test_wrong_password_rejected(sealed):
    with pytest.raises(ValueError, match="Wrong password"):
        unseal_bytes(sealed, "incorrect-password")


def test_ciphertext_tamper_detected(sealed):
    payload = bytearray(extract_private_chunk(sealed))
    payload[-22] ^= 0x20
    from veilpng.png_container import attach_private_chunk
    tampered = attach_private_chunk(sealed, bytes(payload))
    with pytest.raises(ValueError, match="failed authentication"):
        unseal_bytes(tampered, PASSWORD)


def test_chunk_crc_tamper_detected(sealed):
    from veilpng.png_container import PRIVATE_CHUNK
    damaged = bytearray(sealed)
    idx = damaged.index(PRIVATE_CHUNK)
    damaged[idx + 30] ^= 0xAA
    with pytest.raises(ContainerError, match="CRC"):
        inspect_container(bytes(damaged))


def test_preview_export_contains_no_secret(sealed):
    flat = preview_only(sealed)
    assert extract_private_chunk(flat) is None
    assert len(flat) < len(sealed)
    with Image.open(BytesIO(flat)) as img:
        img.load()
        assert img.getpixel((25, 25)) == (34, 40, 56, 255)


def test_repack_preview_leaves_encrypted_data_unchanged(sealed, original):
    ai = Image.new("RGBA", (96, 64), (255, 0, 255, 255))
    out = repack_preview(sealed, image_to_png_bytes(ai))
    assert extract_private_chunk(out) == extract_private_chunk(sealed)
    assert unseal_bytes(out, PASSWORD).original_bytes == original
    assert inspect_container(out)["original_preview_unchanged"] is False
    with Image.open(BytesIO(out)) as im:
        assert im.getpixel((25, 25)) == (255, 0, 255, 255)


def test_merge_writes_only_unprotected_pixels(sealed, mask, original):
    ai = Image.new("RGBA", (96, 64), (255, 0, 255, 255))
    result = merge_ai_preview(sealed, image_to_png_bytes(ai), PASSWORD, "noise", kdf=FAST_KDF)
    asset = unseal_bytes(result, PASSWORD)
    patched = load_image(asset.original_bytes)
    before = load_image(original)
    assert patched.getpixel((25, 25)) == before.getpixel((25, 25))
    assert patched.getpixel((4, 4)) == (255, 0, 255, 255)
    assert asset.mask.tobytes() == mask.tobytes()
    assert asset.filename == "原始测试_AI.png"


def test_ai_dimension_mismatch_rejected(sealed):
    wrong_size = image_to_png_bytes(Image.new("RGBA", (95, 64), "red"))
    with pytest.raises(ValueError, match="must be"):
        repack_preview(sealed, wrong_size)
    with pytest.raises(ValueError, match="dimensions"):
        merge_ai_preview(sealed, wrong_size, PASSWORD, kdf=FAST_KDF)


def test_password_minimum(original, mask):
    with pytest.raises(ValueError, match="at least 8"):
        seal_bytes(original, "a.png", mask, "short", kdf=FAST_KDF)


def test_full_cover_then_holes(original):
    im = load_image(original)
    mask = Image.new("L", im.size, 255)
    ImageDraw.Draw(mask).rectangle((22, 22, 33, 33), fill=0)
    cover = render_preview(im, mask, "solid")
    assert cover.getpixel((2, 2)) == (34, 40, 56, 255)
    assert cover.getpixel((25, 25)) == im.getpixel((25, 25))


def test_no_source_transparency_leak_inside_mask():
    im = Image.new("RGBA", (8, 8), (200, 100, 30, 0))
    mask = Image.new("L", im.size, 255)
    cover = render_preview(im, mask, "solid")
    assert cover.getpixel((4, 4))[3] == 255
