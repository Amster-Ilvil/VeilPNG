"""Qt GUI tests of actual phantom tab controls (headless virtual display)."""
from __future__ import annotations
import os
import json
import pytest
from pathlib import Path
from PIL import Image,ImageDraw
if os.name!='nt' and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from veilpng.gui import MainWindow

@pytest.fixture(scope='module')
def app():
    a=QApplication.instance() or QApplication([])
    yield a

@pytest.fixture
def window(app):
    w=MainWindow()
    w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def test_gui_phantom_build_and_switch_tab(window,app,tmp_path):
    assert window.side_tabs.count()==5
    window.side_tabs.setCurrentIndex(3)
    app.processEvents()
    assert window.workspace_stack.currentIndex()==2
    white=Image.new('RGB',(190,240),'white')
    ImageDraw.Draw(white).rectangle((20,30,150,180),fill='black')
    black=Image.new('RGB',(190,240),'black')
    ImageDraw.Draw(black).ellipse((30,20,175,210),fill='white')
    w=tmp_path/'white.png';b=tmp_path/'black.png';white.save(w);black.save(b)
    window.phantom_surface_path.setText(str(w))
    window.phantom_hidden_path.setText(str(b))
    window.phantom_create_btn.click();app.processEvents()
    assert window.phantom_result is not None
    assert window.phantom_workspace.result is window.phantom_result
    assert all(not label.pixmap().isNull() for label in window.phantom_workspace.preview_labels)
    assert window.phantom_result.report['alpha_min']<255
    window.side_tabs.setCurrentIndex(2);app.processEvents()
    assert window.workspace_stack.currentIndex()==1
    window.side_tabs.setCurrentIndex(0);app.processEvents()
    assert window.workspace_stack.currentIndex()==0


def test_gui_phantom_save_and_preview_export(window,app,tmp_path,monkeypatch):
    white=Image.new('RGB',(165,200),'white')
    ImageDraw.Draw(white).ellipse((10,20,150,180),fill='black')
    black=Image.new('RGB',(165,200),'black')
    ImageDraw.Draw(black).rectangle((30,30,120,160),fill='white')
    w=tmp_path/'white.png';b=tmp_path/'black.png';white.save(w);black.save(b)
    window.phantom_surface_path.setText(str(w));window.phantom_hidden_path.setText(str(b))
    window.phantom_mode_combo.setCurrentIndex(1) # colour
    window.phantom_create_from_gui()
    out=tmp_path/'phantom.png';preview_dir=tmp_path/'preview'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(out),'PNG'))
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a,**k:str(preview_dir))
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(window,'_error',lambda *args: pytest.fail(f'Unexpected Qt GUI error: {args}'))
    window.phantom_save_from_gui();app.processEvents()
    assert out.exists()
    with Image.open(out) as img: assert img.mode=='RGBA'
    window.phantom_export_previews_from_gui()
    assert (preview_dir/'preview_black.png').exists()
    assert (preview_dir/'preview.html').exists()
    # Existing transparent PNG can be reopened in visual mode.
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(out),'PNG'))
    window.phantom_inspect_from_gui()
    assert window.phantom_result.report['type']=='phantom_tank_inspection'
