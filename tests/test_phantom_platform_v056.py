"""Synthetic offline platform-packaging and post-upload diagnostics; no platform API calls."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.phantom_tank import create_phantom
from veilpng.phantom_platform import (PRESETS, audit_platform_return,
                                      prepare_platform_package)


def fake_pair(size=(260,190)):
    a=Image.new('RGB',size,'white')
    da=ImageDraw.Draw(a)
    da.rectangle((25,15,130,100),fill='black')
    b=Image.new('RGB',size,'black')
    ImageDraw.Draw(b).ellipse((80,45,195,165),fill='white')
    return a,b


@pytest.fixture
def phantom_file(tmp_path):
    a,b=fake_pair()
    f=tmp_path/'original_alpha.png'
    create_phantom(a,b).image.save(f)
    return f


@pytest.mark.parametrize('platform',list(PRESETS))
def test_offline_bundles_are_actual_png_alpha_and_fallback(tmp_path, phantom_file, platform):
    output=tmp_path/f'export_{platform}'
    report=prepare_platform_package(phantom_file,output,platform)
    assert report['status']=='LOCAL_CANDIDATE_NOT_PLATFORM_VERIFIED'
    assert report['platform']==platform
    assert report['alpha_max']<255
    for p in ['upload_alpha.png','original_unmodified.png','white_background_reference.jpg',
              'black_background_reference.jpg','fallback_side_by_side.jpg','view_offline.html','platform_report.json']:
        assert (output/p).is_file()
    with Image.open(output/'upload_alpha.png') as png:
        assert png.format=='PNG' and png.mode=='RGBA'
        assert np.count_nonzero(np.asarray(png.getchannel('A'))<255)>0
    assert audit_platform_return(output/'upload_alpha.png',output/'upload_alpha.png')['verdict']=='PRESERVED'
    assert '不能证明' in (output/'view_offline.html').read_text(encoding='utf-8')


def test_platform_jpeg_flattened_detected(tmp_path,phantom_file):
    out=tmp_path/'out'
    prepare_platform_package(phantom_file,out,'wechat')
    source=Image.open(out/'upload_alpha.png').convert('RGBA')
    flat=Image.new('RGBA',source.size,'white')
    flat.alpha_composite(source)
    flat.convert('RGB').save(tmp_path/'wechat_returned.jpg',quality=95)
    report=audit_platform_return(out/'upload_alpha.png',tmp_path/'wechat_returned.jpg')
    assert report['verdict']=='ALPHA_LOST'
    assert report['returned_has_alpha'] is False
    assert report['app_native_preview_verified'] is False


def test_platform_png_opaque_detected(tmp_path,phantom_file):
    opaque=Image.open(phantom_file).convert('RGB').convert('RGBA')
    f=tmp_path/'opaque.png';opaque.save(f)
    assert audit_platform_return(phantom_file,f)['verdict']=='ALPHA_LOST'


def test_platform_same_rgba_resized_detected(tmp_path,phantom_file):
    source=Image.open(phantom_file)
    smaller=source.resize((130,95),Image.Resampling.LANCZOS)
    f=tmp_path/'smaller.png';smaller.save(f)
    report=audit_platform_return(phantom_file,f)
    assert report['verdict']=='PRESERVED_RESIZED'
    assert report['returned_nonopaque_pixels']>0


def test_platform_alpha_modified_detected(tmp_path,phantom_file):
    arr=np.asarray(Image.open(phantom_file).convert('RGBA')).copy()
    arr[...,3]=np.clip(np.round(arr[...,3].astype(np.float32)*0.5),0,255).astype('uint8')
    f=tmp_path/'modified.png';Image.fromarray(arr,'RGBA').save(f)
    assert audit_platform_return(phantom_file,f)['verdict']=='DEGRADED'


def test_platform_geometry_mismatch_detected(tmp_path,phantom_file):
    im=Image.open(phantom_file)
    altered=im.crop((0,0,im.width,im.height-45))
    f=tmp_path/'cropped.png'; altered.save(f)
    assert audit_platform_return(phantom_file,f)['verdict']=='GEOMETRY_CHANGED'


def test_bad_input_and_output_paths(tmp_path,phantom_file):
    with pytest.raises(ValueError,match='platform'):
        prepare_platform_package(phantom_file,tmp_path/'bad','unknown')
    with pytest.raises(ValueError,match='separate'):
        prepare_platform_package(phantom_file,tmp_path,'qq')
    with pytest.raises(ValueError,match='128..8192'):
        prepare_platform_package(phantom_file,tmp_path/'bad', 'qq',max_long_side=64)
    opaque=tmp_path/'opaque.png';Image.new('RGB',(50,50),'white').save(opaque)
    with pytest.raises(ValueError,match='alpha'):
        prepare_platform_package(opaque,tmp_path/'bad','qq')


def test_cli_round_trip(tmp_path,phantom_file):
    root=Path(__file__).resolve().parents[1]
    out=tmp_path/'qq_bundle'
    cmd=[sys.executable,'-m','veilpng','phantom-platform-prepare','-i',str(phantom_file),
         '--platform','qq','-o',str(out)]
    env=os.environ.copy();env['PYTHONPATH']=str(root)
    r=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True)
    assert r.returncode==0, r.stderr
    assert json.loads(r.stdout)['status']=='LOCAL_CANDIDATE_NOT_PLATFORM_VERIFIED'
    report=tmp_path/'audit.json'
    r=subprocess.run([sys.executable,'-m','veilpng','phantom-platform-audit',
                     '--original',str(out/'upload_alpha.png'),'--returned',str(out/'upload_alpha.png'),
                     '--report',str(report)],cwd=root,env=env,capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    assert json.loads(report.read_text())['verdict']=='PRESERVED'


def test_userscript_opt_in_and_safe_code():
    root=Path(__file__).resolve().parents[1]
    src=(root/'userscripts'/'VeilPNG-Alpha-Preview.user.js').read_text(encoding='utf-8')
    assert '@match        https://*.qq.com/*' in src
    assert '@match        https://*.weixin.qq.com/*' in src
    assert '@match        https://*.xiaohongshu.com/*' in src
    assert 'event.altKey' in src and 'type="file"' in src
    assert 'URL.createObjectURL' in src
    for forbidden in ('fetch(', 'XMLHttpRequest', 'GM_xmlhttpRequest', 'localStorage.setItem', 'eval('):
        assert forbidden not in src
