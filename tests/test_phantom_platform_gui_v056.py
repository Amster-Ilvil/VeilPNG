"""Qt offscreen widget-level tests for platform export and returned-image audit."""
from __future__ import annotations
import os
import pytest
from PIL import Image, ImageDraw
if os.name != 'nt' and not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from veilpng.gui import MainWindow
from veilpng.phantom_tank import create_phantom

@pytest.fixture(scope='module')
def app():
    a=QApplication.instance() or QApplication([])
    yield a

@pytest.fixture
def window(app,tmp_path):
    w=MainWindow()
    w.show();app.processEvents()
    white=Image.new('RGB',(240,180),'white')
    black=Image.new('RGB',(240,180),'black')
    ImageDraw.Draw(white).rectangle((30,30,120,120),fill='black')
    ImageDraw.Draw(black).ellipse((60,20,220,150),fill='white')
    w.phantom_result=create_phantom(white,black)
    w.phantom_saved_path=tmp_path/'phantom.png'
    w.phantom_result.image.save(w.phantom_saved_path)
    w.phantom_workspace.set_result(w.phantom_result)
    yield w
    w.close();app.processEvents()

@pytest.mark.parametrize('profile',range(3))
def test_platform_gui_exports_selected_profile(window,app,tmp_path,monkeypatch,profile):
    out=tmp_path/f'platform_{profile}'
    window.phantom_platform_combo.setCurrentIndex(profile)
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a,**k:str(out))
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(window,'_error',lambda *a:pytest.fail(f'GUI error {a}'))
    window.phantom_export_platform_package()
    app.processEvents()
    assert (out/'upload_alpha.png').exists()
    assert '候选已生成' in window.phantom_platform_status.text()


def test_platform_gui_downloaded_jpeg_detects_alpha_lost(window,app,tmp_path,monkeypatch):
    source=window.phantom_saved_path
    fl=Image.new('RGB',(240,180),'white')
    fl.save(tmp_path/'returned.jpg')
    files=iter([(str(source),'PNG'),(str(tmp_path/'returned.jpg'),'Image')])
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:next(files))
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(window,'_error',lambda *a:pytest.fail(f'GUI error {a}'))
    window.phantom_audit_platform_return()
    app.processEvents()
    assert 'ALPHA_LOST' in window.phantom_platform_status.text()


def test_platform_gui_visual_evidence_export(window, app, tmp_path, monkeypatch):
    from veilpng.phantom_tank import reveal_on_background
    original=window.phantom_saved_path
    returned=tmp_path/'received_simulated.jpg'
    reveal_on_background(Image.open(original),(255,255,255)).save(returned)
    files=iter([(str(original),'PNG'),(str(returned),'Image')])
    directory=tmp_path/'evidence_gui'
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:next(files))
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a,**k:str(directory))
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(window,'_error',lambda *a:pytest.fail(f'Unexpected GUI error: {a}'))
    window.phantom_export_platform_audit_evidence()
    app.processEvents()
    assert (directory/'alpha_change_heatmap.png').exists()
    assert 'ALPHA_LOST' in window.phantom_platform_status.text()
