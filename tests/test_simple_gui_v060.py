import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import Qt
from PIL import Image,ImageDraw
from veilpng.simple_gui import SimpleWindow

@pytest.fixture
def win():
    app=QApplication.instance() or QApplication([])
    w=SimpleWindow();w.show();app.processEvents();yield w
    w.dirty=False;w.close();app.processEvents()

def test_single_batch_and_mode_switch(win,tmp_path,monkeypatch):
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    paths=[]
    for i in range(2):
        p=tmp_path/f'{i}.png';Image.new('RGB',(150,200),'white').save(p);paths.append(p)
    win.load_images(paths[:1]);assert win.index==0;assert not win.panes[1].isVisible()
    ImageDraw.Draw(win.canvases[0].mask).rectangle((20,30,50,70),fill=255);win.canvases[0].changed.emit();assert win.export_current.isEnabled()
    win.switch_mode(1);win.load_images(paths);win.list.setCurrentRow(1);assert win.index==1
    ImageDraw.Draw(win.canvases[0].mask).rectangle((20,30,50,70),fill=255);win.canvases[0].changed.emit();win.list.setCurrentRow(0);win.list.setCurrentRow(1);assert win.canvases[0].mask.getbbox()
    win.search.setText('1.png');win.load_images(paths);assert win.list.count()==2

def test_minimum_window_layout(win):
    win.resize(760,520);QApplication.processEvents();assert win.import_btn.isVisible();assert win.export_current.isVisible()

def test_pair_workbench_sync(win,tmp_path):
    from test_simple_project_v060 import bundle
    win.load_pairs(bundle(tmp_path/'paired'))
    QApplication.processEvents()
    assert win.mode==2 and win.index==0 and win.panes[1].isVisible()
    ImageDraw.Draw(win.canvases[0].mask).rectangle((20,30,45,60),fill=255)
    win.canvases[0].changed.emit()
    assert win.canvases[1].mask.getpixel((50,80))==255
    assert win.pages[0].ready and win.export_current.isEnabled()
    win.preview.setChecked(True)
    assert win.canvases[0].show_cover and win.canvases[1].show_cover
