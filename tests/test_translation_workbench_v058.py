"""Synthetic, non-private tests for Japanese-base Chinese translation transfer."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from veilpng.translation_core import align_translation_images, render_translation, mask_array


def synthetic_pair(size=(240,180)):
    jp=Image.new('RGB',size,'white')
    gem=Image.new('RGB',size,'white')
    j=ImageDraw.Draw(jp);g=ImageDraw.Draw(gem)
    # constant comic panel art, unchanged between both images
    for d in [j,g]:
        d.rectangle((8,8,size[0]-10,size[1]-10),outline='black',width=3)
        d.ellipse((120,80,198,155),outline='#555555',width=5)
    j.rectangle((38,45,48,95),fill='black')  # old JP vertical mark
    g.rectangle((59,45,69,95),fill='black')  # new Chinese mark
    # Gemini replaces protected chest area with an object, must never transfer.
    g.rectangle((137,94,191,149),fill='black')
    tr=Image.new('L',size,0);ImageDraw.Draw(tr).rectangle((30,30,85,110),fill=255)
    erase=Image.new('L',size,0);ImageDraw.Draw(erase).rectangle((32,38,53,106),fill=255)
    protect=Image.new('L',size,0);ImageDraw.Draw(protect).rectangle((134,90,193,152),fill=255)
    return jp,gem,tr,erase,protect


def identity_aligned():
    jp,gem,tr,erase,protect=synthetic_pair()
    aligned=align_translation_images(japanese=jp,gemini=gem,matrix_jp_to_gemini=np.eye(3))
    return aligned,tr,erase,protect


def test_patch_mode_restores_protected_artwork_and_replaces_approved_area():
    a,tr,erase,protect=identity_aligned()
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,protect_mask=protect,
                         transfer='patch',feather_px=0)
    assert r.image.getpixel((41,61))==(255,255,255) # original lettering erased
    assert r.image.getpixel((62,61))==(0,0,0) # Gemini Chinese ink transferred
    assert r.image.getpixel((160,120))==a.japanese.getpixel((160,120))
    assert r.report['protected_pixels_changed']==0
    assert r.report['outside_edit_scope_changed']==0
    assert r.report['encrypted_output'] is False


def test_ink_only_does_not_replace_white_gemini_background():
    a,tr,erase,prot=identity_aligned()
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,protect_mask=prot,
                         transfer='ink',feather_px=0)
    assert r.image.getpixel((62,70))==(0,0,0)
    assert r.image.getpixel((42,70))==(255,255,255)
    assert r.report['effective_transferred_pixels']<r.report['paste_mask_pixels']


def test_protection_priority_even_with_overlapping_paste_and_erase():
    a,tr,erase,prot=identity_aligned()
    ImageDraw.Draw(tr).rectangle((130,90,198,155),fill=255)
    ImageDraw.Draw(erase).rectangle((140,96,170,145),fill=255)
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,protect_mask=prot,feather_px=2)
    original=np.asarray(a.japanese)
    result=np.asarray(r.image)
    p=np.asarray(prot)>127
    assert np.array_equal(original[p],result[p])
    assert r.report['protected_pixels_changed']==0
    assert r.report['paste_mask_protected_overlap_pixels'] > 0


def test_precleaned_base_is_used_only_in_manual_erase_mask():
    a,tr,erase,prot=identity_aligned()
    fake=Image.new('RGB',a.japanese.size,'#dadada')
    # Leave the old JP glyph clear of the Gemini paste mask, so only the
    # manually-selected delettered base can replace those pixels.
    ImageDraw.Draw(tr).rectangle((33,42,53,100),fill=0)
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,
                         cleaned_japanese_base=fake,protect_mask=prot,feather_px=0)
    # Outside union of selected areas, the original JP image must survive.
    assert r.image.getpixel((93,58))==a.japanese.getpixel((93,58))
    assert r.image.getpixel((41,61))==(218,218,218)


def test_cv2_inpaint_dilation_does_not_escape_user_erase_selection():
    a,tr,erase,protect=identity_aligned()
    # The two manual regions are intentionally distinct, and no saved clean
    # base is supplied. This exercises the real OpenCV INPAINT_TELEA path.
    ImageDraw.Draw(tr).rectangle((33,42,53,100),fill=0)
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,
                         protect_mask=protect,cleaned_japanese_base=None,
                         transfer='patch',feather_px=0)
    assert r.report['outside_edit_scope_changed']==0
    original=np.asarray(a.japanese)
    result=np.asarray(r.image)
    allowed=(np.asarray(tr)>127) | (np.asarray(erase)>127)
    assert np.array_equal(original[~allowed],result[~allowed])


def test_size_mismatch_and_empty_selection_are_rejected():
    a,tr,erase,protect=identity_aligned()
    with pytest.raises(ValueError,match='size'):
        render_translation(aligned=a,translation_mask=Image.new('L',(32,32),255))
    with pytest.raises(ValueError,match='No approved'):
        render_translation(aligned=a,translation_mask=Image.new('L',a.japanese.size,0))


def test_global_edit_budget_prevents_accidental_whole_image_copy():
    a,tr,erase,protect=identity_aligned()
    with pytest.raises(ValueError,match='exceeds configured'):
        render_translation(aligned=a,translation_mask=Image.new('L',a.japanese.size,255),max_area_fraction=.55)


def test_invalid_homography_is_rejected():
    jp,gem,*_=synthetic_pair()
    with pytest.raises(ValueError,match='Invalid'):
        align_translation_images(japanese=jp,gemini=gem,matrix_jp_to_gemini=np.zeros((3,3)))


def test_output_is_normal_png_without_custom_encrypted_chunk(tmp_path):
    a,tr,erase,prot=identity_aligned()
    r=render_translation(aligned=a,translation_mask=tr,erase_japanese_mask=erase,protect_mask=prot)
    p=tmp_path/'final.png';r.image.save(p,'PNG')
    data=p.read_bytes()
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    assert b'vpNg' not in data and b'veilpng' not in data.lower()


def test_cli_translation_transfer_uses_new_library(tmp_path):
    jp,gem,tr,erase,protect=synthetic_pair()
    for name,im in [('jp.png',jp),('gem.png',gem),('tr.png',tr),('erase.png',erase),('protect.png',protect)]:
        im.save(tmp_path/name,'PNG')
    np.save(tmp_path/'H.npy',np.eye(3))
    command=[sys.executable,'-m','veilpng','translation-transfer',
             '--japanese',str(tmp_path/'jp.png'),'--gemini',str(tmp_path/'gem.png'),
             '--translation-mask',str(tmp_path/'tr.png'),
             '--erase-mask',str(tmp_path/'erase.png'),'--protect-mask',str(tmp_path/'protect.png'),
             '--matrix',str(tmp_path/'H.npy'),
             '--output',str(tmp_path/'final.png'),'--report',str(tmp_path/'report.json'),
             '--feather-px','0']
    result=subprocess.run(command,capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'final.png').exists()
    assert json.loads((tmp_path/'report.json').read_text())['protected_pixels_changed']==0


def test_qt_edit_layers_preview_save_reopen_and_export(tmp_path, monkeypatch):
    if os.name!='nt' and not os.getenv('DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from veilpng.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    jp,gem,tr,erase,prot=synthetic_pair(size=(300,230))
    paths=[]
    for name,im in [('jp.png',jp),('gem.png',gem),('tr.png',tr),('erase.png',erase),('protect.png',prot)]:
        p=tmp_path/name;im.save(p);paths.append(p)
    w=MainWindow();w.resize(1600,980);w.show();app.processEvents()
    try:
        w.side_tabs.setCurrentIndex(4);app.processEvents()
        work=w.translation_workbench
        work.jp_path.setText(str(paths[0]));work.gem_path.setText(str(paths[1]))
        assert work.prepare(saved_matrix=np.eye(3))
        assert w.workspace_stack.currentIndex()==3
        # Import the pre-defined ROI masks through *GUI state*, then use an actual
        # Qt mouse drag to extend the translation selection on the canvas.
        work.masks['translation']=tr
        work.canvas.set_document(work.aligned.japanese,tr)
        work.canvas.set_selection_tint(work.TINTS[0])
        work.canvas.set_tool('rect')
        def screen_pt(x,y):return work.canvas.mapFromScene(QPointF(x,y))
        p1=screen_pt(205,155);p2=screen_pt(225,175)
        QTest.mousePress(work.canvas.viewport(),Qt.MouseButton.LeftButton,pos=p1)
        QTest.mouseMove(work.canvas.viewport(),pos=p2)
        QTest.mouseRelease(work.canvas.viewport(),Qt.MouseButton.LeftButton,pos=p2)
        app.processEvents()
        assert work.canvas.mask.getpixel((215,165))==255
        work.layer_combo.setCurrentIndex(1)
        assert work.masks['translation'].getpixel((215,165))==255
        work.layer_combo.setCurrentIndex(0)
        work.canvas.undo()
        assert work.canvas.mask.getpixel((215,165)) == 0
        work.canvas.redo()
        assert work.canvas.mask.getpixel((215,165)) == 255
        work.layer_combo.setCurrentIndex(1)
        work.masks['erase']=erase.copy()
        work.canvas.set_document(work.aligned.japanese,erase)
        work.layer_combo.setCurrentIndex(2)
        work.masks['protect']=prot.copy()
        work.canvas.set_document(work.aligned.japanese,prot)
        res=work.generate_preview()
        assert res and res.report['protected_pixels_changed']==0
        # Local export invokes the new module; file is ordinary PNG.
        output=tmp_path/'export_final.png'
        monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',lambda *a,**k:(str(output),'PNG (*.png)'))
        work.export_final();app.processEvents()
        assert output.exists() and output.read_bytes().startswith(b'\x89PNG')
        folder=tmp_path/'saved_project';folder.mkdir()
        monkeypatch.setattr(QtWidgets.QFileDialog,'getExistingDirectory',lambda *a,**k:str(folder))
        work.save_project()
        assert (folder/'translation_project.json').exists()
        work.masks['translation']=Image.new('L',jp.size,0)
        work.open_project()
        assert work.masks['translation'].getpixel((215,165))==255
        assert work.generate_preview() is not None
    finally:
        w.close();app.processEvents()
