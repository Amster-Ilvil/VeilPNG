"""A3 Qt GUI actions with synthetic-only images and no network calls."""
from __future__ import annotations
import os
import json
from pathlib import Path

import pytest

if os.name!='nt' and not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QMessageBox
from veilpng.gui import MainWindow
from test_cross_pair_edit_v053 import mock_pair


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_GUI_A3_rejects_risky_patch_without_confirmation(app,mock_pair,monkeypatch):
    project,ai,_,_=mock_pair
    w=MainWindow();w.show();app.processEvents()
    try:
        w.manga_project_dir.setText(str(project))
        w.manga_source_ai_path.setText(str(ai))
        w.manga_a3_strategy.setCurrentIndex(1)
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
        monkeypatch.setattr(w,'_get_password',lambda:pytest.fail('Should not ask password if declined'))
        w.manga_transfer_gemini_to_japanese()
        assert not (project/'resolved_outputs'/'A3_JP_base').exists()
    finally:
        w.close();app.processEvents()


def test_GUI_A3_transfers_approved_patch_and_generates_decrypted_JP(app,mock_pair,monkeypatch):
    project,ai,_,_=mock_pair
    w=MainWindow();w.show();app.processEvents()
    try:
        w.manga_project_dir.setText(str(project))
        w.manga_source_ai_path.setText(str(ai))
        w.manga_a3_strategy.setCurrentIndex(1)
        w.manga_a3_feather.setValue(6)
        w.manga_alignment_combo.setCurrentIndex(1)
        monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(w,'_get_password',lambda:'strongtest123')
        monkeypatch.setattr(w,'_error',lambda *a:pytest.fail(f'GUI A3 error: {a}'))
        w.manga_transfer_gemini_to_japanese();app.processEvents()
        out=project/'resolved_outputs'/'A3_JP_base'
        assert (out/'A3_JP_based_decrypted.png').exists()
        assert (out/'A3_JP_based_sealed.png').exists()
        report=json.loads((out/'A3_transfer_report.json').read_text())
        assert report['actual_japanese_image_changed_pixels']>0
        assert report['outside_green_roi_changed']==0
        assert report['protected_pixels_changed']==0
        assert 'A3' in w.manga_info.text()
    finally:
        w.close();app.processEvents()
