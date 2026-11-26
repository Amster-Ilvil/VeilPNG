"""Tests for the alpha-based phantom mode. All inputs are synthetic, never private."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.phantom_tank import (PhantomOptions, create_phantom, inspect_phantom,
                                 make_comparison, reveal_on_background, to_png_bytes,
                                 write_preview_assets)


def sources(size=(160,120)):
    a = Image.new('RGB', size, 'white')
    da = ImageDraw.Draw(a)
    da.rectangle((10,10,70,70),fill='black')
    da.line((0,size[1]-1,size[0]-1,0),fill='black',width=4)
    b = Image.new('RGB', size, 'black')
    db = ImageDraw.Draw(b)
    db.ellipse((30,20,145,110),fill='white')
    db.rectangle((40,40,90,90),fill='black')
    return a,b


def test_two_reveals_are_real_alpha_and_match_compressed_targets():
    white,black=sources()
    res=create_phantom(white,black)
    assert res.image.mode=='RGBA'
    assert res.report['alpha_min'] < res.report['alpha_max'] < 255
    assert res.report['white_target_error']['mae'] < 1.2
    assert res.report['black_target_error']['mae'] < 1.2
    assert np.mean(np.abs(np.asarray(res.white_preview,dtype=np.int16) -
                          np.asarray(res.black_preview,dtype=np.int16))) > 100
    assert not np.array_equal(np.asarray(res.white_preview),np.asarray(res.black_preview))


def test_export_roundtrip_inspection_and_validation_report(tmp_path):
    white,black=sources()
    res=create_phantom(white,black)
    path=tmp_path/'phantom.png'
    path.write_bytes(to_png_bytes(res.image))
    # Standard PNG no custom encrypted chunks.
    with Image.open(path) as img:
        img.load()
        assert img.mode=='RGBA'
        check=inspect_phantom(img)
    assert np.array_equal(np.asarray(check.white_preview),np.asarray(res.white_preview))
    assert np.array_equal(np.asarray(check.black_preview),np.asarray(res.black_preview))
    write_preview_assets(res,path,tmp_path/'previews')
    for name in ('preview_white.png','preview_black.png','preview_gray.png',
                 'comparison.png','phantom.png','report.json','preview.html'):
        assert (tmp_path/'previews'/name).is_file()
    assert 'phantom.png' in (tmp_path/'previews'/'preview.html').read_text()
    meta=json.loads((tmp_path/'previews'/'report.json').read_text())
    assert meta['type']=='phantom_tank_rgba_not_encrypted'
    assert Image.open(tmp_path/'previews'/'comparison.png').size == (320,120)


def test_color_mode_is_approximate_and_not_opaque():
    white,black=sources()
    dw=ImageDraw.Draw(white); dw.rectangle((20,20,60,80),fill=(0,180,250))
    db=ImageDraw.Draw(black); db.ellipse((20,20,130,110),fill=(230,45,45))
    res=create_phantom(white,black,PhantomOptions(mode='color'))
    assert res.report['white_target_error']['mae'] >= 0
    assert res.report['black_target_error']['mae'] >= 0
    assert res.report['alpha_min'] < 255
    assert np.asarray(res.image.convert('RGB'))[...,0].max() != np.asarray(res.image.convert('RGB'))[...,1].max() or (
        not np.array_equal(np.asarray(res.image)[...,0],np.asarray(res.image)[...,1]))
    assert res.white_preview.size==white.size


@pytest.mark.parametrize('fit', ['contain','cover','stretch'])
def test_mismatched_size_fits_without_changing_surface_size(fit):
    white,_=sources((151,117))
    _,black=sources((80,150))
    res=create_phantom(white,black,PhantomOptions(fit=fit))
    assert res.image.size==(151,117)
    assert res.report['type']=='phantom_tank_rgba_not_encrypted'


def test_unsupported_inputs_or_parameters_fail():
    white,black=sources()
    with pytest.raises(ValueError,match='mode'):
        create_phantom(white,black,PhantomOptions(mode='bad'))
    with pytest.raises(ValueError,match='white_base'):
        create_phantom(white,black,PhantomOptions(white_base=20))
    with pytest.raises(ValueError,match='alpha channel'):
        inspect_phantom(white)
    with pytest.raises(ValueError,match='opaque'):
        inspect_phantom(Image.new('RGBA',(10,10),(0,0,0,255)))


def test_cli_generate_and_inspect_without_password(tmp_path):
    white,black=sources()
    wf=tmp_path/'surface.png'; bf=tmp_path/'black.png'
    white.save(wf);black.save(bf)
    out=tmp_path/'out.png'; preview=tmp_path/'preview'
    env=os.environ.copy()
    env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    res=subprocess.run([sys.executable,'-m','veilpng','phantom-create',
                        '--surface',str(wf),'--hidden',str(bf),'-o',str(out),
                        '--preview-dir',str(preview)],cwd=str(Path(__file__).resolve().parents[1]),
                        env=env,capture_output=True,text=True)
    assert res.returncode==0,res.stderr
    assert out.is_file() and (preview/'preview.html').is_file()
    doc=json.loads(res.stdout)
    assert doc['alpha_max'] < 255
    res2=subprocess.run([sys.executable,'-m','veilpng','phantom-inspect','-i',str(out)],
                        cwd=str(Path(__file__).resolve().parents[1]),env=env,capture_output=True,text=True)
    assert res2.returncode==0,res2.stderr
    assert json.loads(res2.stdout)['type']=='phantom_tank_inspection'


def test_output_cannot_overwrite_source(tmp_path):
    white,black=sources()
    wf=tmp_path/'surface.png';bf=tmp_path/'black.png';white.save(wf);black.save(bf)
    before=wf.read_bytes()
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    result=subprocess.run([sys.executable,'-m','veilpng','phantom-create',
                           '--surface',str(wf),'--hidden',str(bf),'-o',str(wf)],
                          cwd=str(Path(__file__).resolve().parents[1]),env=env,capture_output=True,text=True)
    assert result.returncode!=0
    assert wf.read_bytes()==before
