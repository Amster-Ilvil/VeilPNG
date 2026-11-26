"""Synthetic-only post-upload evidence tests. No platform APIs or private user assets."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw
from veilpng.phantom_tank import create_phantom, reveal_on_background
from veilpng.phantom_platform import prepare_platform_package, write_platform_audit_evidence


@pytest.fixture
def pair(tmp_path):
    w=Image.new('RGB',(180,140),'white')
    h=Image.new('RGB',(180,140),'black')
    ImageDraw.Draw(w).ellipse((15,10,140,120),fill='black')
    ImageDraw.Draw(h).rectangle((55,10,165,125),fill='white')
    original=tmp_path/'phantom.png'
    create_phantom(w,h).image.save(original)
    opaque=tmp_path/'returned.jpg'
    reveal_on_background(Image.open(original),(255,255,255)).save(opaque,quality=93)
    return original,opaque


def test_platform_bundle_contains_safari_offline_return_verifier(tmp_path,pair):
    original,_=pair
    bundle=tmp_path/'qq'
    report=prepare_platform_package(original,bundle,'qq')
    f=bundle/'verify_return_offline.html'
    html=f.read_text(encoding='utf-8')
    assert f.exists()
    assert 'id="after"' in html and 'id="before"' in html
    assert 'ALPHA_LOST' in html and 'PRESERVED_RESIZED' in html
    assert 'URL.createObjectURL' in html
    assert 'fetch(' not in html and 'XMLHttpRequest' not in html
    assert report['files']['local_return_verifier']=='verify_return_offline.html'


def test_visual_evidence_simulated_alpha_lost_and_no_private_source_copy(tmp_path,pair):
    original,opaque=pair
    evidence=tmp_path/'evidence'
    rep=write_platform_audit_evidence(original,opaque,evidence)
    assert rep['verdict']=='ALPHA_LOST'
    assert (evidence/'white_black_before_after.jpg').exists()
    heat=np.asarray(Image.open(evidence/'alpha_change_heatmap.png').convert('RGB'))
    assert heat.shape[:2]==(140,180)
    assert int(heat[...,0].max())>0
    assert (evidence/'verify_return_offline.html').exists()
    meta=json.loads((evidence/'audit.json').read_text())
    assert meta['app_native_preview_verified'] is False
    assert set(p.name for p in evidence.iterdir())==set(rep['files'])
    # Do not ever copy the input PNG or the returned image to evidence.
    assert not (evidence/original.name).exists()
    assert not (evidence/opaque.name).exists()
    with pytest.raises(ValueError,match='empty'):
        write_platform_audit_evidence(original,opaque,evidence)


def test_visual_evidence_preserved_image_is_zero_alpha_heatmap(tmp_path,pair):
    original,_=pair
    rep=write_platform_audit_evidence(original,original,tmp_path/'clean')
    assert rep['verdict']=='PRESERVED'
    heat=np.asarray(Image.open(tmp_path/'clean'/'alpha_change_heatmap.png'))
    assert not np.any(heat)


def test_cli_evidence_dir(tmp_path,pair):
    original,opaque=pair
    root=Path(__file__).resolve().parents[1]
    env=os.environ.copy();env['PYTHONPATH']=str(root)
    evidence=tmp_path/'cli_evidence'
    proc=subprocess.run([sys.executable,'-m','veilpng','phantom-platform-audit',
                         '--original',str(original),'--returned',str(opaque),
                         '--evidence-dir',str(evidence)],cwd=root,env=env,
                        capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    rep=json.loads(proc.stdout)
    assert rep['verdict']=='ALPHA_LOST'
    assert len(rep['evidence_files'])==5
    assert (evidence/'white_black_before_after.jpg').exists()


def test_userscript_alpha_button_and_no_cross_origin_bypass():
    path=Path(__file__).resolve().parents[1]/'userscripts'/'VeilPNG-Alpha-Preview.user.js'
    script=path.read_text(encoding='utf-8')
    from veilpng import __version__
    assert f'@version      {__version__}' in script
    assert 'data-action="inspect"' in script
    assert 'getImageData' in script
    assert '跨域保护' in script
    for bad in ('fetch(', 'XMLHttpRequest','GM_xmlhttpRequest','localStorage.setItem','eval('):
        assert bad not in script
