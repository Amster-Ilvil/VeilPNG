"""Synthetic-only QA: no user scans, passwords, or private file fixtures."""
from io import BytesIO
import numpy as np
import pytest
from PIL import Image, ImageDraw
from veilpng.core import seal_bytes, unseal_bytes, preview_only
from veilpng.crypto import KDFParams
from veilpng.imaging import image_to_png_bytes
from veilpng.smart_edit import smart_edit

PASS = 'synthetic-unit-password'
FAST = KDFParams(memory_kib=8192,time_cost=1,parallelism=1)

@pytest.fixture(scope='module')
def fixture():
    rng = np.random.default_rng(418)
    h,w = 560,410
    canvas=np.full((h,w,3),247,np.uint8)
    for _ in range(240):
        x,y=int(rng.integers(0,w)),int(rng.integers(0,h))
        if y < 90 or y > 245:
            canvas[y,x] = (42,42,42)
    image=Image.fromarray(canvas,'RGB').convert('RGBA')
    d=ImageDraw.Draw(image)
    d.rectangle((40,110,368,270),outline=(12,12,12),width=2)
    d.text((84,146),'ORIGINAL WORDS',fill=(0,0,0))
    protect=Image.new('L',(w,h),0)
    ImageDraw.Draw(protect).ellipse((70,355,340,520), fill=255)
    roi=Image.new('L',(w,h),0)
    ImageDraw.Draw(roi).rectangle((70,125,325,245), fill=255)
    sealed=seal_bytes(image_to_png_bytes(image),'synthetic-only.png',protect,PASS,kdf=FAST,style='solid')
    pub=Image.open(BytesIO(preview_only(sealed))).convert('RGBA')
    return image, protect, roi, sealed, pub


def test_monochrome_text_restores_grayscale_changes_but_not_others(fixture):
    orig,prot,roi,sealed,public=fixture
    edited=public.copy()
    d=ImageDraw.Draw(edited)
    d.rectangle((80,137,270,181),fill=(255,255,255),outline=None)
    d.text((90,153),'REVISED TEXT',fill=(0,0,0))
    d.rectangle((20,299,110,339),fill='black') # should never merge
    r=smart_edit(sealed,image_to_png_bytes(edited),PASS,roi,mode='A2',
                 extraction='monochrome',alignment='resize',edge_guard_px=3,
                 min_component_pixels=3)
    after=np.asarray(unseal_bytes(r.container_png,PASS).image())
    before=np.asarray(orig)
    ro=np.asarray(roi)>0; secure=np.asarray(prot)>0
    assert np.array_equal(after[~ro],before[~ro])
    assert np.array_equal(after[secure],before[secure])
    assert r.report['actual_decrypted_changed_pixels']>50
    assert r.report['written_pixels_outside_roi']==0
    assert r.report['written_pixels_in_protected_area']==0
    assert np.any(after[ro]!=before[ro])


def test_monochrome_rejects_colored_gpt_overlay(fixture):
    orig,prot,roi,sealed,public=fixture
    edited=public.copy()
    ImageDraw.Draw(edited).rectangle((90,150,230,220), fill='red')
    with pytest.raises(ValueError,match='mostly grayscale'):
        smart_edit(sealed,image_to_png_bytes(edited),PASS,roi,mode='A1',
                   extraction='monochrome',alignment='resize')


def test_patch_replaces_old_text_background_but_stays_inside_interior(fixture):
    orig,prot,roi,sealed,public=fixture
    edited=public.copy()
    ImageDraw.Draw(edited).rectangle((70,125,325,245),fill=(255,255,255))
    ImageDraw.Draw(edited).text((95,165),'NEW TEXT',fill=(0,0,0))
    r=smart_edit(sealed,image_to_png_bytes(edited),PASS,roi,mode='A2',
                 extraction='patch',alignment='resize',edge_guard_px=5)
    before=np.asarray(orig)
    after=np.asarray(unseal_bytes(r.container_png,PASS).image())
    assert r.report['changed_pixels']>10000 # patch deliberately copies whole ROI
    assert np.array_equal(after[~(np.asarray(roi)>0)],before[~(np.asarray(roi)>0)])
    # Explicit 5px border remains exactly original, no forced discontinuity.
    assert np.array_equal(after[125:130,85:300],before[125:130,85:300])
    assert np.all(after[180:200,275:295,:3]==255)


def test_monochrome_filters_small_luminance_noise(fixture):
    orig,prot,roi,sealed,public=fixture
    data=np.asarray(public).astype(np.int16).copy()
    data[...,:3] = np.minimum(data[...,:3]+2,255)
    edited=Image.fromarray(data.astype(np.uint8),'RGBA')
    with pytest.raises(ValueError,match='No eligible GPT changes'):
        smart_edit(sealed,image_to_png_bytes(edited),PASS,roi,
                   extraction='monochrome',alignment='resize')


def test_invalid_edge_guard_rejected(fixture):
    orig,prot,roi,sealed,public=fixture
    with pytest.raises(ValueError,match='edge_guard'):
        smart_edit(sealed,image_to_png_bytes(public),PASS,roi,edge_guard_px=25)
