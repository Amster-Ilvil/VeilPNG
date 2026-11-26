"""Synthetic-only Qt tests; never requires private manga or credentials."""
from __future__ import annotations
import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
if os.name != 'nt' and not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from veilpng.gui import MainWindow
from veilpng.core import seal_bytes

@pytest.fixture(scope='module')
def app():
    a = QApplication.instance() or QApplication([])
    yield a

@pytest.fixture
def work(app):
    w = MainWindow()
    w.resize(1440, 920)
    w.show()
    app.processEvents()
    im=Image.new('RGB',(540,720),'#eeeef2')
    ImageDraw.Draw(im).rectangle((30,30,490,690),outline='#40404e',width=5)
    ImageDraw.Draw(im).ellipse((120,140,410,420),fill='#bad1df')
    b=io.BytesIO(); im.save(b,format='PNG')
    w._load_document(b.getvalue(),'synthetic-page.png',None,None)
    app.processEvents()
    yield w
    w.close()
    app.processEvents()

def test_tab_layout_and_side_by_side_black_mask(work, app):
    assert work.side_tabs.count()==5
    assert "漫画" in work.side_tabs.tabText(2)
    assert '遮挡' in work.side_tabs.tabText(0)
    assert 'AI' in work.side_tabs.tabText(1)
    assert work.view_split.count()==2
    from PySide6.QtWidgets import QScrollArea
    edit_scroll=work.side_tabs.widget(0)
    assert edit_scroll.horizontalScrollBarPolicy()==Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    ImageDraw.Draw(work.canvas.mask).rectangle((160,240,300,360),fill=255)
    work.canvas.changed.emit()
    work._set_solid_color('#000000')
    work.compare_toggle.setChecked(True)
    app.processEvents()
    assert work.compare_panel.isVisible()
    assert not work.toggle_preview.isEnabled()
    assert work.compare_item.pixmap().size().width()==540
    px=work.compare_item.pixmap().toImage().pixelColor(200,300)
    assert (px.red(),px.green(),px.blue())==(0,0,0)
    assert '加密遮盖面积' in work.mask_stat.text()
    work.compare_toggle.setChecked(False)
    app.processEvents()
    assert not work.compare_panel.isVisible()
    assert work.toggle_preview.isEnabled()

def test_roi_mode_routing_preserves_mask_and_compare(work, tmp_path, app, monkeypatch):
    mask=work.canvas.mask
    ImageDraw.Draw(mask).rectangle((100,100,190,190),fill=255)
    work.canvas.changed.emit()
    sealed=tmp_path/'synthetic_container.png'
    sealed.write_bytes(seal_bytes(work.original_bytes,'synthetic-page.png',mask,'OnlySyntheticPassword2026','solid',solid_color='#000000'))
    work.container_path=sealed
    before=mask.tobytes()
    work._set_solid_color('#000000')
    work.modified=False
    work.side_tabs.setCurrentIndex(1)
    work.compare_toggle.setChecked(True)
    work.toggle_ai_roi()
    app.processEvents()
    assert work.side_tabs.currentIndex()==0
    assert work.roi_active
    assert work.finish_roi_btn.isVisible()
    assert '绿色' in work.mode_label.text()
    assert work.compare_item.pixmap().toImage().pixelColor(140,140).red()==0
    ImageDraw.Draw(work.canvas.mask).rectangle((380,450,470,580),fill=255)
    work.canvas.changed.emit()
    assert 'AI 许可区域' in work.mask_stat.text()
    work.toggle_ai_roi()
    app.processEvents()
    assert not work.roi_active
    assert work.canvas.mask.tobytes()==before
    assert work.side_tabs.currentIndex()==1
    assert not work.finish_roi_btn.isVisible()
    assert '红色' in work.mode_label.text()

def test_brush_refresh_coalescing_retains_exact_pixels(work, app):
    view=work.canvas
    view.set_tool('brush')
    view.brush_size=19
    a=(90,520)
    for i in range(100):
        b=(90+i*2,520)
        view._paint_stroke(a,b)
        a=b
    assert view._paint_redraw_timer.isActive()
    assert view.mask.getpixel((250,520))==255
    view._paint_redraw_timer.stop()
    view._refresh_overlay()
    assert not view.overlay_item.pixmap().isNull()

def test_zoom_label_tracks_canvas_zoom(work, app):
    work.canvas.zoom_one()
    app.processEvents()
    assert work.zoom_label.text()=='100%'
    work.canvas.zoom_fit()
    app.processEvents()
    assert '%' in work.zoom_label.text()
    assert work.canvas.transform().m11()>0


def test_grayscale_selection_and_legacy_merge_warning(work, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    work.side_tabs.setCurrentIndex(1)
    assert work.extraction_combo.count() == 4
    work.extraction_combo.setCurrentIndex(1)
    assert "黑白" in work.extraction_combo.currentText()
    work.extraction_combo.setCurrentIndex(3)
    assert "整块" in work.extraction_combo.currentText()
    work.edge_guard_spin.setValue(4)
    assert work.edge_guard_spin.value() == 4
    warnings=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:(warnings.append(a[1]),QMessageBox.StandardButton.No)[1])
    monkeypatch.setattr(work,'_ai_inputs',lambda:pytest.fail('Legacy merge should not open file dialogs unless user explicitly confirms'))
    work.ai_merge()
    assert warnings and '高风险' in warnings[0]
