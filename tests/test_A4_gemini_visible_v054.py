"""Synthetic-only regression for A4: full Gemini-visible image with JP protected restore."""
from __future__ import annotations
import csv
from io import BytesIO
import json

import pytest
from PIL import Image, ImageDraw

from veilpng.manga_mode import create_manga_project
from veilpng.cross_pair_edit import transfer_gemini_visible_to_japanese, save_gemini_visible_result
from veilpng.png_container import extract_private_chunk


def test_A4_full_visible_with_restored_cover(tmp_path):
    w,h=160,120
    src=Image.new('RGB',(w,h),(240,240,240))
    d=ImageDraw.Draw(src)
    d.rectangle((6,8,50,42),fill=(180,180,180))
    d.text((12,62),'CN',fill=(5,5,5))
    tgt=src.resize((w*2,h*2),Image.Resampling.NEAREST)
    ds=ImageDraw.Draw(tgt)
    # The encrypted Japanese base contains different colors in the cover.
    ds.ellipse((100,100,230,210),fill=(170,175,185))
    src_path=tmp_path/'CN.png';tgt_path=tmp_path/'JP.png'
    src.save(src_path);tgt.save(tgt_path)
    csv_path=tmp_path/'pairs.csv'
    with csv_path.open('w',newline='',encoding='utf-8') as f:
        c=csv.DictWriter(f,fieldnames=['pair_id','source_image','target_image','source_width','source_height',
           'target_width','target_height','matrix_3x3_json','registration_confidence'])
        c.writeheader();c.writerow(dict(pair_id='TEST',source_image='CN.png',target_image='JP.png',
         source_width=w,source_height=h,target_width=w*2,target_height=h*2,
         matrix_3x3_json='[[2,0,0],[0,2,0],[0,0,1]]',registration_confidence=1.0))
    # Conceal mask covers interior of the circle in JP (source half-resolution).
    mask=Image.new('L',src.size,0)
    ImageDraw.Draw(mask).ellipse((58,52,108,100),fill=255)
    mask_path=tmp_path/'mask.png';mask.save(mask_path)
    manifest=create_manga_project(output_dir=tmp_path/'project',pairs_csv=csv_path,pair_id='TEST',
         source_image=src_path,target_image=tgt_path,mask=mask_path,mask_space='source',
         password='synthetic_password_for_test',expand_px=0,style='solid',solid_color='#000000')
    # Gemini output is the source picture with all-visible edits + solid black cover.
    gem=src.copy()
    d=ImageDraw.Draw(gem)
    d.rectangle((10,8,42,28),fill=(20,100,230))
    d.rectangle((14,72,55,95),fill=(245,20,50))
    d.ellipse((58,52,108,100),fill=(0,0,0))
    buf=BytesIO();gem.save(buf,format='PNG')
    result=transfer_gemini_visible_to_japanese(project_dir=tmp_path/'project',
             gemini_result=buf.getvalue(),password='synthetic_password_for_test',
             alignment='matrix', recover_expand_px=0,feather_px=0)
    out=Image.open(BytesIO(result.final_png)).convert('RGB')
    jp=tgt.convert('RGB')
    assert out.size==tgt.size
    # Gemini-visible colors outside cover must be present in JP resolution.
    assert out.getpixel((30,24))==(20,100,230)
    assert out.getpixel((45,163))==(245,20,50)
    # Fully concealed original pixel is recovered from the Japanese base.
    assert out.getpixel((170,155))==jp.getpixel((170,155))
    # This is a plain PNG with no encryption metadata.
    assert extract_private_chunk(result.final_png) is None
    assert result.report['protected_pixels_changed']==0
    assert result.report['output_type']=='ordinary_png_no_encrypted_layer'

    with pytest.raises(Exception):
        transfer_gemini_visible_to_japanese(project_dir=tmp_path/'project',
             gemini_result=buf.getvalue(),password='wrong_password',alignment='matrix')

    gem_path=tmp_path/'gemini.png';gem.save(gem_path)
    info=save_gemini_visible_result(project_dir=tmp_path/'project',gemini_image_path=gem_path,
             password='synthetic_password_for_test',alignment='matrix',
             recover_expand_px=0,feather_px=0)
    assert info['final_image'].endswith('FINAL.png')
    assert Image.open(info['final_image']).size==(w*2,h*2)


def test_A4_rejects_invalid_mode_and_negative_recovery(tmp_path):
    from veilpng.cross_pair_edit import transfer_gemini_visible_to_japanese as a4
    with pytest.raises(ValueError,match='alignment'):
        a4(project_dir=tmp_path,gemini_result=b'',password='none',alignment='untrusted')
    with pytest.raises(ValueError,match='recover_expand_px'):
        a4(project_dir=tmp_path,gemini_result=b'',password='none',recover_expand_px=-1)
