"""v0.2.0 tests: selectable opaque RGB color + export auditing + safe A1."""
from io import BytesIO
from PIL import Image, ImageDraw
import pytest

from veilpng.core import (
    audit_exported_preview, inspect_container, merge_ai_preview, preview_only,
    repack_preview, seal_bytes, unseal_bytes,
)
from veilpng.crypto import KDFParams
from veilpng.imaging import image_to_png_bytes, normalize_solid_color, render_preview
from veilpng.png_container import extract_private_chunk

PASSWORD = 'v02-test-password'
FAST = KDFParams(memory_kib=8192, time_cost=1, parallelism=1)

@pytest.fixture
def drawing():
    img = Image.new('RGBA', (32, 24), (240, 180, 60, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((5, 3, 29, 21), fill=(20, 220, 160, 255))
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).rectangle((8, 5, 22, 18), fill=255)
    return image_to_png_bytes(img), mask

@pytest.mark.parametrize('color', ['#000000', '#FFFFFF', '#1648B7', '#f2a4bd'])
def test_color_opaque_exact_and_bit_exact(drawing, color):
    original, mask = drawing
    sealed = seal_bytes(original, 'source.png', mask, PASSWORD, 'solid', kdf=FAST, solid_color=color)
    preview = preview_only(sealed)
    asset = unseal_bytes(sealed, PASSWORD)
    assert asset.original_bytes == original
    assert inspect_container(sealed)['preview_solid_color'] == color.upper()
    with Image.open(BytesIO(preview)) as im:
        assert im.getpixel((15, 10)) == tuple(bytes.fromhex(color[1:])) + (255,)
        assert im.getpixel((0, 0)) == (240, 180, 60, 0)
    audit = audit_exported_preview(sealed, preview, PASSWORD)
    assert audit['mechanical_audit_pass']
    assert audit['covered_area_uniform_color'] is True
    assert audit['covered_area_opaque'] is True
    assert audit['encrypted_payload_absent'] is True
    assert audit['coverage_pixels'] == 15 * 14

@pytest.mark.parametrize('color', ['#aaa', '#1FFFFFFF', 'white', '', '#12GG77', '#11223F\n', '#11223300'])
def test_bad_color_rejected(drawing, color):
    orig, mask = drawing
    with pytest.raises(ValueError, match='#RRGGBB'):
        normalize_solid_color(color)
    with pytest.raises(ValueError, match='#RRGGBB'):
        seal_bytes(orig, 'a.png', mask, PASSWORD, kdf=FAST, solid_color=color)

def test_preview_tamper_fails_audit(drawing):
    original, mask = drawing
    sealed = seal_bytes(original, 'a.png', mask, PASSWORD, kdf=FAST, solid_color='#FFFDFC')
    public = Image.open(BytesIO(preview_only(sealed))).convert('RGBA')
    public.putpixel((10, 10), (99, 25, 100, 255))
    audit = audit_exported_preview(sealed, image_to_png_bytes(public), PASSWORD)
    assert not audit['covered_area_uniform_color']
    assert not audit['matches_container_public_preview']
    assert not audit['mechanical_audit_pass']

def test_mask_export_without_secret_and_opaque(drawing):
    original, mask = drawing
    sealed = seal_bytes(original, 'a.png', mask, PASSWORD, kdf=FAST, solid_color='#000000')
    public = preview_only(sealed)
    assert extract_private_chunk(public) is None
    assert extract_private_chunk(sealed) is not None
    assert audit_exported_preview(sealed, public, PASSWORD)['mechanical_audit_pass'] is True


def test_a1_password_restricts_ai_changes_to_visible_area(drawing):
    original, mask = drawing
    sealed = seal_bytes(original, 'a.png', mask, PASSWORD, kdf=FAST, solid_color='#DA1436')
    ai = image_to_png_bytes(Image.new('RGBA', (32, 24), (3, 5, 15, 255)))
    safe = repack_preview(sealed, ai, PASSWORD)
    assert extract_private_chunk(safe) == extract_private_chunk(sealed)
    assert unseal_bytes(safe, PASSWORD).original_bytes == original
    with Image.open(BytesIO(safe)) as im:
        assert im.getpixel((13, 9)) == (218, 20, 54, 255)
        assert im.getpixel((1, 9)) == (3, 5, 15, 255)
    assert inspect_container(safe)['original_preview_unchanged'] is False


def test_safe_a1_bad_password_and_dimension_error(drawing):
    original, mask = drawing
    sealed = seal_bytes(original, 'a.png', mask, PASSWORD, kdf=FAST)
    ai = image_to_png_bytes(Image.new('RGBA', (32, 24), 'blue'))
    with pytest.raises(ValueError, match='Wrong password'):
        repack_preview(sealed, ai, 'wrongpassword')
    with pytest.raises(ValueError, match='must be'):
        repack_preview(sealed, image_to_png_bytes(Image.new('RGBA', (30, 24))), PASSWORD)


def test_a2_preserves_secret_region_and_custom_color(drawing):
    original, mask = drawing
    sealed = seal_bytes(original, 'a.png', mask, PASSWORD, kdf=FAST, solid_color='#000000')
    ai = image_to_png_bytes(Image.new('RGBA', (32, 24), (35, 18, 80, 255)))
    a2 = merge_ai_preview(sealed, ai, PASSWORD, kdf=FAST, solid_color='#F1F4FA')
    asset = unseal_bytes(a2, PASSWORD)
    before = Image.open(BytesIO(original)).convert('RGBA')
    after = Image.open(BytesIO(asset.original_bytes)).convert('RGBA')
    assert after.getpixel((15, 10)) == before.getpixel((15, 10))
    assert after.getpixel((2, 2)) == (35, 18, 80, 255)
    assert asset.mask.tobytes() == mask.tobytes()
    assert inspect_container(a2)['preview_solid_color'] == '#F1F4FA'
    with Image.open(BytesIO(preview_only(a2))) as view:
        assert view.getpixel((15, 10)) == (241, 244, 250, 255)
