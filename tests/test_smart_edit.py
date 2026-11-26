"""v0.3: fail-closed alignment and independently selected AI-edit permission mask."""
from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.core import seal_bytes, unseal_bytes, preview_only
from veilpng.crypto import KDFParams
from veilpng.imaging import image_to_png_bytes
from veilpng.smart_edit import smart_edit

PASS = 'smart-test-password'
FAST = KDFParams(memory_kib=8192, time_cost=1, parallelism=1)


@pytest.fixture(scope='module')
def sample():
    # Feature rich, deterministic monochrome document. No real/mature manga.
    import cv2
    rng = np.random.default_rng(31)
    h,w=900,660
    a=np.full((h,w,3),248,np.uint8)
    for _ in range(650):
        x=int(rng.integers(0,w));y=int(rng.integers(0,h))
        xx=int(rng.integers(0,w));yy=int(rng.integers(0,h))
        color=int(rng.integers(0,190))
        cv2.line(a,(x,y),(xx,yy),(color,color,color),1)
    orig=Image.fromarray(a).convert('RGBA')
    protected=Image.new('L',(w,h),0)
    ImageDraw.Draw(protected).ellipse((230,565,510,855),fill=255)
    sealed=seal_bytes(image_to_png_bytes(orig),'doc.png',protected,PASS,kdf=FAST,solid_color='#000000')
    public=Image.open(BytesIO(preview_only(sealed))).convert('RGBA')
    ai=public.copy()
    painter=ImageDraw.Draw(ai)
    painter.rounded_rectangle((25,25,180,145),radius=8,fill=(90,210,250,255))
    painter.rectangle((400,380,525,470),fill=(244,40,38,255))
    # Also simulate unrelated black-and-white redraw in a noneditable region.
    painter.rectangle((70,700,165,785),fill='white')
    # resize to provoke the same GPT dimension mismatch as in the real case
    ai=ai.resize((490,668),Image.Resampling.LANCZOS)
    roi=Image.new('L',(w,h),0)
    d=ImageDraw.Draw(roi)
    d.rectangle((15,15,195,160),fill=255)
    d.rectangle((380,360,550,490),fill=255)
    return orig,protected,sealed,roi,image_to_png_bytes(ai)


def _images_match_outside_region(before,after,allow):
    a=np.asarray(before.convert('RGBA'))
    b=np.asarray(after.convert('RGBA'))
    ma=np.asarray(allow.convert('L'))>0
    assert np.array_equal(a[~ma],b[~ma])


def test_a1_keeps_original_bit_exact_and_encrypted_payload(sample):
    orig, mask, sealed, roi, gpt = sample
    result=smart_edit(sealed,gpt,PASS,roi,mode='A1',extraction='color')
    assert unseal_bytes(result.container_png,PASS).original_bytes == unseal_bytes(sealed,PASS).original_bytes
    assert result.report['geometry']['inlier_ratio'] > .5
    assert result.report['changed_pixels'] > 1000
    base=Image.open(BytesIO(preview_only(sealed)))
    new=Image.open(BytesIO(preview_only(result.container_png)))
    _images_match_outside_region(base,new,roi)
    assert result.report['written_pixels_in_protected_area'] == 0
    assert result.report['written_pixels_outside_roi'] == 0
    assert np.asarray(new)[80,80,1] > 160


def test_a2_does_not_change_hidden_pixels_or_anything_outside_roi(sample):
    orig, protected, sealed, roi, gpt=sample
    result=smart_edit(sealed,gpt,PASS,roi,mode='A2')
    plain=unseal_bytes(result.container_png,PASS)
    decrypted=plain.image()
    _images_match_outside_region(orig,decrypted,roi)
    _images_match_outside_region(orig,decrypted,Image.fromarray(
        np.where(np.asarray(roi)==255,255,0).astype('uint8'))) # repeat for strictness
    before=np.asarray(orig)
    after=np.asarray(decrypted)
    assert np.array_equal(before[np.asarray(protected)>0],after[np.asarray(protected)>0])
    assert not np.array_equal(before[80,80],after[80,80])
    assert np.array_equal(before[740,100],after[740,100])
    assert result.report['changed_percent_of_whole'] < 10


def test_wrong_password_rejects(sample):
    *_, sealed,roi,gpt = sample
    with pytest.raises((ValueError,RuntimeError)):
        smart_edit(sealed,gpt,'bad-password',roi)


def test_empty_and_excessive_roi_rejected(sample):
    orig,protected,sealed,roi,gpt=sample
    with pytest.raises(ValueError,match='Empty editable'):
        smart_edit(sealed,gpt,PASS,Image.new('L',roi.size,0))
    with pytest.raises(ValueError,match='65%'):
        smart_edit(sealed,gpt,PASS,Image.new('L',roi.size,255))


def test_wrong_roi_size_rejected(sample):
    orig, protected, sealed, roi, gpt=sample
    with pytest.raises(ValueError,match='must be'):
        smart_edit(sealed,gpt,PASS,Image.new('L',(10,10)))


def test_nonmatching_gpt_rejected(sample):
    orig, protected, sealed, roi, gpt=sample
    x=np.random.default_rng(92).integers(0,256,(668,490,3),dtype=np.uint8)
    with pytest.raises(ValueError, match='registration rejected'):
        smart_edit(sealed,image_to_png_bytes(Image.fromarray(x)),PASS,roi)


def test_no_eligible_changed_pixels_rejected(sample):
    orig, protected, sealed, roi, gpt=sample
    # Original public preview has no colored pixels.
    with pytest.raises(ValueError,match='No eligible GPT'):
        smart_edit(sealed,preview_only(sealed),PASS,roi)


def test_different_alignment_mode_requires_explicit_opt_in(sample):
    orig, protected, sealed, roi, gpt=sample
    result=smart_edit(sealed,gpt,PASS,roi,alignment='resize')
    assert result.report['geometry']['warning'].startswith('Resize only')


def test_change_budget_rejects(sample):
    orig, protected, sealed, roi, gpt=sample
    with pytest.raises(ValueError,match='Too many modified'):
        smart_edit(sealed,gpt,PASS,roi,max_global_fraction=0.00001)


def test_grayscale_difference_mode(sample):
    orig,prot,sealed,roi,gpt=sample
    # Source is identical (no colored GPT mark); non-monochrome changes happen
    # only in the selected rectangular area.
    base=Image.open(BytesIO(preview_only(sealed))).convert('RGBA')
    ImageDraw.Draw(base).rectangle((38,36,130,115),fill=(10,10,10,255))
    result=smart_edit(sealed,image_to_png_bytes(base),PASS,roi,extraction='difference',threshold=60)
    assert result.report['changed_pixels']>300
    assert np.array_equal(np.asarray(unseal_bytes(result.container_png,PASS).image())[700,70],np.asarray(orig)[700,70])


def test_colored_reference_guard():
    # Intentional color extraction guard for already-colorful source photos.
    src=Image.new('RGBA',(400,300),(130,40,210,255))
    protect=Image.new('L',src.size,0)
    roi=Image.new('L',src.size,0)
    ImageDraw.Draw(roi).rectangle((10,10,180,100),fill=255)
    sealed=seal_bytes(image_to_png_bytes(src),'colored.png',protect,PASS,kdf=FAST)
    edited=src.copy();ImageDraw.Draw(edited).rectangle((30,30,100,75),fill='red')
    with pytest.raises(ValueError, match='mostly grayscale'):
        smart_edit(sealed,image_to_png_bytes(edited),PASS,roi,alignment='resize')


def test_transparent_gpt_output_rejected(sample):
    orig,prot,sealed,roi,gpt=sample
    image=Image.open(BytesIO(gpt)).convert("RGBA")
    image.putpixel((0,0),(10,20,30,0))
    with pytest.raises(ValueError,match='fully opaque'):
        smart_edit(sealed,image_to_png_bytes(image),PASS,roi)
