"""Synthetic fixtures only. Never check in private JP/CN manga or model output."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.cross_pair_edit import transfer_ai_changes_to_japanese, transfer_and_save
from veilpng.core import unseal_bytes
from veilpng.manga_mode import create_manga_project


@pytest.fixture()
def mock_pair(tmp_path):
    source = Image.new('RGB', (200, 150), '#dddddd')
    pen = ImageDraw.Draw(source)
    pen.rectangle((10, 12, 190, 141), outline='#111111', width=2)
    pen.rectangle((16, 17, 62, 64), fill='#c4c4c4')
    pen.ellipse((82, 30, 140, 90), fill='#777777')
    pen.text((100, 60), 'SOURCE', fill='black')
    target = source.resize((400, 300), Image.Resampling.NEAREST)
    ImageDraw.Draw(target).text((205, 125), 'JP ORIGINAL', fill=(22,22,22))
    sp = tmp_path/'CN0001.png';tp=tmp_path/'JP0001.png'
    source.save(sp);target.save(tp)
    pairs=tmp_path/'pairs.csv'
    with pairs.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['pair_id','source_image','target_image','source_width','source_height',
            'target_width','target_height','matrix_3x3_json','registration_confidence'])
        w.writeheader();w.writerow({'pair_id':'test005','source_image':sp.name,'target_image':tp.name,
            'source_width':200,'source_height':150,'target_width':400,'target_height':300,
            'matrix_3x3_json':'[[2,0,0],[0,2,0],[0,0,1]]','registration_confidence':0.99})
    mask=Image.new('L',source.size)
    ImageDraw.Draw(mask).ellipse((45,101,95,149),fill=255)
    mp=tmp_path/'mask.png';mask.save(mp)
    roi=Image.new('L',source.size)
    ImageDraw.Draw(roi).rectangle((88,38,163,100),fill=255)
    rp=tmp_path/'roi.png';roi.save(rp)
    proj=tmp_path/'manga'
    m=create_manga_project(output_dir=proj,pairs_csv=pairs,pair_id='test005',
        source_image=sp,target_image=tp,mask=mp,mask_space='source',password='strongtest123',
        roi_mask=rp,style='solid',solid_color='#000000')
    source_pub=Image.open(m['source']['public_preview']).convert('RGB')
    altered=source_pub.copy()
    pen=ImageDraw.Draw(altered)
    pen.rounded_rectangle((104,57,149,86),radius=2,fill='white',outline='black',width=3)
    pen.text((110,63),'NEW',fill='black')
    # Deliberate "watermark" edit OUTSIDE the green ROI must not propagate.
    pen.text((8,130),'UNAPPROVED',fill='black')
    buf=io.BytesIO();altered.save(buf,'PNG')
    ai=tmp_path/'model.png';ai.write_bytes(buf.getvalue())
    return proj, ai, target, m


def test_A3_patch_uses_original_JP_as_base_and_recovers_cover(mock_pair):
    project, ai, target, m=mock_pair
    r=transfer_ai_changes_to_japanese(project_dir=project, gemini_result=ai.read_bytes(),
          password='strongtest123',extraction='patch',allow_entire_roi=True,alignment='resize',
          feather_px=0, edge_guard_px=2)
    decoded=unseal_bytes(r.sealed_png,'strongtest123')
    assert decoded.original_bytes==r.decrypted_png
    new=np.asarray(Image.open(io.BytesIO(decoded.original_bytes)).convert('RGB'))
    old=np.asarray(target.convert('RGB'))
    delta=np.any(new!=old,axis=2)
    red=np.asarray(Image.open(m['target']['conceal_mask']).convert('L'))>0
    green=np.asarray(Image.open(m['target']['roi_mask']).convert('L'))>0
    assert delta.any()
    assert int(np.count_nonzero(delta & red))==0
    assert int(np.count_nonzero(delta & ~green))==0
    assert r.report['protected_pixels_changed']==0
    assert r.report['outside_green_roi_changed']==0
    # True Japanese base: source modifications outside ROI are ignored and JP pixels remain byte-for-byte identical.
    assert np.array_equal(new[~green],old[~green])
    # Covered lower-left area is restored from original JP source, not blanked black.
    assert new[260,130].tolist()==old[260,130].tolist()


def test_A3_refuses_unconfirmed_full_ROI(mock_pair):
    project,ai,*_=mock_pair
    with pytest.raises(ValueError,match='entire ROI|allow_entire_roi'):
        transfer_ai_changes_to_japanese(project_dir=project,gemini_result=ai.read_bytes(),
              password='strongtest123',extraction='patch',alignment='resize')


def test_A3_wrong_password_does_not_decrypt(mock_pair):
    project,ai,*_=mock_pair
    with pytest.raises(ValueError,match='password|authentication|Invalid'):
        transfer_ai_changes_to_japanese(project_dir=project,gemini_result=ai.read_bytes(),
              password='wrongwrong',extraction='patch',allow_entire_roi=True,alignment='resize')


def test_A3_saves_outputs_separate_from_originals(mock_pair,tmp_path):
    project,ai,_,m=mock_pair
    before=Path(m['target']['container']).read_bytes()
    report=transfer_and_save(project_dir=project,gemini_image_path=ai,password='strongtest123',
          output_dir=tmp_path/'results',extraction='patch',allow_entire_roi=True,alignment='resize',
          feather_px=6,edge_guard_px=2)
    assert report['actual_japanese_image_changed_pixels']>0
    assert report['outside_mapped_edit_pixels_changed']==0
    assert Path(report['artifacts']['decrypted_japanese_image']).exists()
    assert Path(m['target']['container']).read_bytes()==before


def test_A3_rejects_if_required_ROI_missing(mock_pair):
    project,ai,_,m=mock_pair
    p=Path(m['target']['roi_mask']);p.unlink()
    with pytest.raises(FileNotFoundError):
        transfer_ai_changes_to_japanese(project_dir=project,gemini_result=ai.read_bytes(),
              password='strongtest123',extraction='patch',allow_entire_roi=True,alignment='resize')
