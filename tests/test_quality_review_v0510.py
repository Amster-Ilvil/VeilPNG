"""Non-private quality detection and GUI regression tests."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.translation_core import align_translation_images, render_translation
from veilpng.quality_review import review_translation


def _build(size=(320, 240), *, residual=False, hard_seam=False):
    jp = Image.new('RGB', size, 'white')
    gem = jp.copy()
    orig = ImageDraw.Draw(jp)
    new = ImageDraw.Draw(gem)
    # original dark Japanese stroke on a clean white bubble
    orig.rectangle((40, 40, 60, 105), fill='black')
    new.rectangle((95, 42, 118, 108), fill='black')
    tr = Image.new('L', size, 0)
    d = ImageDraw.Draw(tr)
    d.rectangle((80, 26, 139, 125), fill=255)
    if hard_seam:
        # Gray Gemini patch reaches manual ROI boundary; should be flagged.
        new.rectangle((80, 26, 139, 125), fill=(145,145,145))
    er = Image.new('L', size, 0)
    if not residual:
        ImageDraw.Draw(er).rectangle((36, 36, 65, 111), fill=255)
    else:
        ImageDraw.Draw(er).rectangle((52, 37, 69, 112), fill=255)
    pr = Image.new('L', size, 0)
    ImageDraw.Draw(pr).rectangle((220, 120, 290, 194), fill=255)
    aligned = align_translation_images(japanese=jp, gemini=gem, matrix_jp_to_gemini=np.eye(3))
    result = render_translation(aligned=aligned, translation_mask=tr,
                                erase_japanese_mask=er, protect_mask=pr,
                                transfer='patch', feather_px=0)
    if residual:
        # Simulate an imperfect delettering result that left a thin JP stroke.
        bad = np.asarray(result.image).copy()
        original = np.asarray(aligned.japanese)
        bad[44:95,55:59] = original[44:95,55:59]
        result.image = Image.fromarray(bad, 'RGB')
    return aligned, result, tr, er, pr


def test_review_flags_dark_original_ink_in_erasure_region():
    a, r, tr, er, pr = _build(residual=True)
    report = review_translation(aligned=a, result=r, translation_mask=tr,
                                erase_japanese_mask=er, protect_mask=pr,
                                min_pixels=4)
    assert report.report['candidate_counts']['possible_original_ink'] >= 1
    assert any(x['kind'] == 'possible_original_ink' for x in report.report['issues'])
    assert report.overlay.size == r.image.size
    assert report.issue_mask.mode == 'RGB'


def test_review_flags_abrupt_patch_boundary():
    a, r, tr, er, pr = _build(hard_seam=True)
    q = review_translation(aligned=a, result=r, translation_mask=tr,
                           erase_japanese_mask=er, protect_mask=pr)
    assert q.report['candidate_counts']['possible_patch_seam'] >= 1


def test_review_does_not_change_original_or_final():
    a,r,tr,er,pr=_build()
    before=r.image.tobytes(); base=a.japanese.tobytes()
    q=review_translation(aligned=a,result=r,translation_mask=tr,
                         erase_japanese_mask=er,protect_mask=pr)
    assert r.image.tobytes()==before
    assert a.japanese.tobytes()==base
    assert q.report['status'] in ('no_candidates_found','manual_review_needed')


def test_review_rejects_wrong_mask_size():
    a,r,tr,er,pr=_build()
    with pytest.raises(ValueError,match='size'):
        review_translation(aligned=a,result=r,translation_mask=Image.new('L',(2,3)))


def test_review_protected_translation_overlap_reported():
    a,r,tr,er,pr=_build()
    ImageDraw.Draw(pr).rectangle((90,45,105,60),fill=255)
    q=review_translation(aligned=a,result=r,translation_mask=tr,protect_mask=pr)
    assert q.report['protected_translation_overlap_pixels']>0


def test_cli_quality_evidence_is_written(tmp_path):
    a,r,tr,er,pr=_build(residual=True)
    for name, img in [('jp.png',a.japanese),('gem.png',a.gemini),('tr.png',tr),('er.png',er),('pr.png',pr)]:
        img.save(tmp_path/name)
    np.save(tmp_path/'H.npy',np.eye(3))
    cmd=[sys.executable,'-m','veilpng','translation-transfer',
         '--japanese',str(tmp_path/'jp.png'), '--gemini',str(tmp_path/'gem.png'),
         '--translation-mask',str(tmp_path/'tr.png'), '--erase-mask',str(tmp_path/'er.png'),
         '--protect-mask',str(tmp_path/'pr.png'),'--matrix',str(tmp_path/'H.npy'),
         '--output',str(tmp_path/'out.png'),'--quality-dir',str(tmp_path/'quality')]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
    assert p.returncode==0,p.stderr
    report=json.loads((tmp_path/'quality'/'translation_quality_report.json').read_text())
    assert 'possible_original_ink' in report['candidate_counts']
    assert (tmp_path/'quality'/'translation_quality_overlay.png').exists()
    assert (tmp_path/'quality'/'translation_quality_flags.png').exists()


def test_cli_rejects_nonempty_quality_directory(tmp_path):
    a,r,tr,er,pr=_build()
    for name, img in [('jp.png',a.japanese),('gem.png',a.gemini),('tr.png',tr)]:
        img.save(tmp_path/name)
    np.save(tmp_path/'H.npy',np.eye(3))
    target=tmp_path/'quality'; target.mkdir(); (target/'private.txt').write_text('DO NOT OVERWRITE')
    cmd=[sys.executable,'-m','veilpng','translation-transfer',
         '--japanese',str(tmp_path/'jp.png'),'--gemini',str(tmp_path/'gem.png'),
         '--translation-mask',str(tmp_path/'tr.png'),'--matrix',str(tmp_path/'H.npy'),
         '--output',str(tmp_path/'out.png'),'--quality-dir',str(target)]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
    assert p.returncode!=0
    assert (target/'private.txt').read_text()=='DO NOT OVERWRITE'
    assert not (tmp_path/'out.png').exists()  # preflight must not create partial final output


def test_gui_quality_overlay_and_export(tmp_path, monkeypatch):
    if os.name!='nt' and not os.getenv('DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    QtWidgets=pytest.importorskip('PySide6.QtWidgets')
    from veilpng.gui import MainWindow
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    a,r,tr,er,pr=_build(residual=True)
    for name, img in [('jp.png',a.japanese),('gem.png',a.gemini)]:
        img.save(tmp_path/name)
    w=MainWindow();w.resize(1550,950);w.show();app.processEvents()
    try:
        work=w.translation_workbench
        work.jp_path.setText(str(tmp_path/'jp.png'));work.gem_path.setText(str(tmp_path/'gem.png'))
        assert work.prepare(saved_matrix=np.eye(3))
        work.masks['translation']=tr.copy();work.masks['erase']=er.copy();work.masks['protect']=pr.copy()
        work.canvas.set_document(work.aligned.japanese,tr)
        assert work.generate_preview() is not None
        q=work.run_quality_review()
        assert q is not None
        assert work.preview_combo.currentIndex()==3
        assert q.report['candidate_counts']['possible_original_ink']>=1
        assert work.issue_combo.count()==1+len(q.report['issues'])
        work.issue_combo.setCurrentIndex(1)
        assert work.issue_combo.currentIndex()==1
        monkeypatch.setattr(QtWidgets.QFileDialog,'getExistingDirectory',lambda *a,**kw:str(tmp_path/'evidence'))
        work.export_quality_review()
        assert (tmp_path/'evidence'/'translation_quality_overlay.png').exists()
        # Edited source must invalidate preview AND QA overlay.
        work.clean_path.setText(str(tmp_path/'jp.png'))
        assert work.review is None
    finally:
        w.close(); app.processEvents()
