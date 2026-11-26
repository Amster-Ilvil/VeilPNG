"""Non-private regression fixtures for the 0.5.9 reliability audit."""
from __future__ import annotations

import csv
from io import BytesIO
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.translation_core import load_rgb, align_translation_images, render_translation
from veilpng.manga_mode import create_manga_project, resolve_manga_project
from veilpng.core import unseal_bytes
from veilpng.crypto import KDFParams


def make_pair(path: Path, *, same_names: bool = False):
    sdir=path/'source';tdir=path/'target';sdir.mkdir(parents=True);tdir.mkdir(parents=True)
    src_name='page.png' if same_names else 'CN101.png'
    tgt_name='page.png' if same_names else 'JP101.png'
    src=Image.new('RGB',(96,80),'white')
    ImageDraw.Draw(src).rectangle((4,4,20,20),fill='black')
    tgt=src.resize((192,160))
    src.save(sdir/src_name);tgt.save(tdir/tgt_name)
    mask=Image.new('L',src.size,0)
    ImageDraw.Draw(mask).rectangle((33,22,60,50),fill=255)
    mask.save(path/'mask.png')
    with (path/'pairs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['pair_id','source_image','target_image','source_width','source_height','target_width','target_height','matrix_3x3_json','registration_confidence'])
        w.writeheader()
        w.writerow(dict(pair_id='p1',source_image=src_name,target_image=tgt_name,
                        source_width=96,source_height=80,target_width=192,target_height=160,
                        matrix_3x3_json='[[2,0,0],[0,2,0],[0,0,1]]',registration_confidence=.99))
    return sdir/src_name,tdir/tgt_name,path/'mask.png',path/'pairs.csv'


def test_translation_exif_oriented_input_is_transposed(tmp_path):
    img=Image.new('RGB',(80,60),'white')
    exif=Image.Exif();exif[274]=6  # Rotate 90 degrees clockwise
    p=tmp_path/'rotated.jpg';img.save(p,exif=exif)
    corrected=load_rgb(p)
    assert corrected.size==(60,80)
    assert load_rgb(p.read_bytes()).size==(60,80)


def test_translation_rejects_animated_gif(tmp_path):
    p=tmp_path/'animation.gif'
    a=Image.new('RGB',(20,20),'red');b=Image.new('RGB',(20,20),'blue')
    a.save(p,save_all=True,append_images=[b],duration=100,loop=0)
    with pytest.raises(ValueError,match='Animated'):
        load_rgb(p)


def test_invalid_homography_horizon_rejected():
    a=Image.new('RGB',(100,100),'white')
    # third-row denominator changes sign inside the source image.
    matrix=np.array([[1,0,0],[0,1,0],[.04,0,-1]])
    with pytest.raises(ValueError,match='horizon'):
        align_translation_images(japanese=a,gemini=a,matrix_jp_to_gemini=matrix)


def test_pair_same_filenames_keep_source_and_target_separate(tmp_path):
    src,tgt,mask,pairs=make_pair(tmp_path,same_names=True)
    m=create_manga_project(output_dir=tmp_path/'project',pairs_csv=pairs,pair_id='p1',
                           source_image=src,target_image=tgt,mask=mask,mask_space='source',
                           password='long enough password',style='solid')
    assert m['source']['container']!=m['target']['container']
    assert m['source']['public_preview']!=m['target']['public_preview']
    assert m['source']['image']!=m['target']['image']
    assert unseal_bytes(Path(m['source']['container']).read_bytes(),'long enough password').original_bytes==src.read_bytes()
    assert unseal_bytes(Path(m['target']['container']).read_bytes(),'long enough password').original_bytes==tgt.read_bytes()
    with pytest.raises(FileExistsError,match='already exists'):
        create_manga_project(output_dir=tmp_path/'project',pairs_csv=pairs,pair_id='p1',
                             source_image=src,target_image=tgt,mask=mask,mask_space='source',
                             password='long enough password')


def test_moved_manga_project_resolves_private_local_files(tmp_path):
    src,tgt,mask,pairs=make_pair(tmp_path)
    m=create_manga_project(output_dir=tmp_path/'first_project',pairs_csv=pairs,pair_id='p1',
                           source_image=src,target_image=tgt,mask=mask,mask_space='source',
                           password='long enough password')
    assert (tmp_path/'first_project'/'registration_pairs.csv').exists()
    moved=tmp_path/'new_machine'/'moved';moved.parent.mkdir()
    shutil.copytree(tmp_path/'first_project',moved)
    # Simulate a Windows -> Mac transfer: remove the original manifest source.
    shutil.rmtree(tmp_path/'first_project')
    pairs.unlink()
    # The original absolute file references now point to deleted paths.
    src_preview=moved/'public_previews'/'CN101_AI_public.png'
    summary=resolve_manga_project(project_dir=moved,password='long enough password',
                                  source_ai_preview=src_preview,mode='A1')
    assert summary['results']['source']['status']=='processed'
    assert Path(summary['results']['source']['decrypted_output']).exists()


@pytest.fixture
def workbench(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from veilpng.translation_widget import TranslationWorkbench
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    japanese=Image.new('RGB',(128,96),'white');gemini=japanese.copy()
    ImageDraw.Draw(japanese).rectangle((10,10,18,62),fill='black')
    ImageDraw.Draw(gemini).rectangle((32,10,40,62),fill='black')
    j=tmp_path/'jp.png';g=tmp_path/'gemini.png';japanese.save(j);gemini.save(g)
    widget=TranslationWorkbench();widget.jp_path.setText(str(j));widget.gem_path.setText(str(g))
    assert widget.prepare(saved_matrix=np.eye(3))
    m=Image.new('L',(128,96),0);ImageDraw.Draw(m).rectangle((8,8,60,70),fill=255)
    widget.canvas.mask=m;widget._save_layer()
    return app,widget,j,g,tmp_path


def test_workbench_clean_base_change_invalidates_preview(workbench):
    app,w,j,g,root=workbench
    assert w.generate_preview() is not None
    assert w._dirty is False
    clean=Image.new('RGB',(128,96),'white');p=root/'clean.png';clean.save(p)
    w.clean_path.setText(str(p))
    assert w._dirty and w.result is None


def test_workbench_source_change_blocks_stale_generation(workbench,monkeypatch):
    app,w,j,g,root=workbench
    errors=[]
    monkeypatch.setattr(w,'_error',lambda stage,exc:errors.append(str(exc)))
    g2=root/'other.png';Image.new('RGB',(128,96),'blue').save(g2)
    w.gem_path.setText(str(g2))
    assert w.generate_preview() is None
    assert errors and '重新配准' in errors[-1]


def test_workbench_refuses_overwrite_source_on_export(workbench,monkeypatch):
    app,w,j,g,root=workbench
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    original=j.read_bytes()
    errors=[]
    monkeypatch.setattr(w,'_error',lambda stage,exc:errors.append(str(exc)))
    monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',lambda *args,**kwargs:(str(j),'PNG (*.png)'))
    w.export_final()
    assert errors and '覆盖' in errors[-1]
    assert j.read_bytes()==original


def test_workbench_rejects_mask_path_traversal(tmp_path,workbench,monkeypatch):
    app,w,j,g,root=workbench
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    import tempfile
    project=root/'malformed';project.mkdir()
    project_json={'kind':'translation_transfer','japanese':str(j),'gemini':str(g),
                  'clean_base':'','matrix_jp_to_gemini':np.eye(3).tolist(),
                  'mask_files':{'translation':'../secret.png','erase':'erase.png','protect':'protect.png'}}
    (project/'translation_project.json').write_text(json.dumps(project_json),encoding='utf8')
    monkeypatch.setattr(QtWidgets.QFileDialog,'getExistingDirectory',lambda *args,**kwargs:str(project))
    errors=[];monkeypatch.setattr(w,'_error',lambda stage,exc:errors.append(str(exc)))
    w.open_project()
    assert errors and '目录穿越' in errors[-1]


def test_workbench_confirm_before_erasing_manual_masks(workbench,monkeypatch):
    app,w,j,g,root=workbench
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    monkeypatch.setattr(QtWidgets.QMessageBox,'question',lambda *args,**kwargs:QtWidgets.QMessageBox.StandardButton.No)
    assert not w.prepare(saved_matrix=np.eye(3))
    assert w.masks['translation'].getbbox() is not None


def test_main_gui_cannot_overwrite_current_source_with_sealed(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from veilpng.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    original=Image.new('RGB',(80,80),'white')
    source=tmp_path/'input.png';original.save(source)
    previous=source.read_bytes()
    w=MainWindow()
    try:
        w._load_document(previous,'input.png',None,None)
        w.source_path=source
        monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',
                            lambda *a,**k:(str(source),'PNG (*.png)'))
        warnings=[]
        monkeypatch.setattr(QtWidgets.QMessageBox,'warning',
                            lambda *a,**k:warnings.append(a[1]))
        w.save_sealed()
        assert warnings and '禁止覆盖' in warnings[-1]
        assert source.read_bytes()==previous
    finally:
        w.close();app.processEvents()


def test_main_gui_public_preview_cannot_overwrite_encrypted_container(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from veilpng.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    src=Image.new('RGB',(80,80),'white');b=BytesIO();src.save(b,format='PNG')
    w=MainWindow()
    try:
        w._load_document(b.getvalue(),'source.png',None,None)
        sealed=tmp_path/'safe_sealed.png';sealed.write_bytes(b'KEEP_ENCRYPTED_DATA')
        w.container_path=sealed
        w.modified=False
        monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',
                            lambda *a,**k:(str(sealed),'PNG (*.png)'))
        errors=[]
        monkeypatch.setattr(w,'_error',lambda stage,exc:errors.append(str(exc)))
        w.export_ai_preview()
        assert errors and '不能覆盖' in errors[-1]
        assert sealed.read_bytes()==b'KEEP_ENCRYPTED_DATA'
    finally:
        w.close();app.processEvents()


def test_main_gui_ai_return_cannot_be_overwritten_by_a1_output(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from veilpng.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=MainWindow()
    try:
        sealed=tmp_path/'source_sealed.png';sealed.write_bytes(b'fake but not opened')
        ai=tmp_path/'ai.png';ai.write_bytes(b'original AI bytes')
        w.container_path=sealed;w.modified=False;w.roi_active=False
        monkeypatch.setattr(w,'_pick_sealed_file',lambda:sealed)
        monkeypatch.setattr(w,'_pick_ai',lambda:ai)
        monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',
                            lambda *a,**k:(str(ai),'PNG (*.png)'))
        warnings=[]
        monkeypatch.setattr(QtWidgets.QMessageBox,'warning',
                            lambda *a,**k:warnings.append(a[1]))
        assert w._ai_inputs() is None
        assert warnings and ai.read_bytes()==b'original AI bytes'
    finally:
        w.close();app.processEvents()


def test_release_package_version_follows_module_metadata():
    from scripts.build_release import current_version
    from veilpng import __version__
    assert current_version()==__version__
