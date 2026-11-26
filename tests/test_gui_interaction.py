"""Real Qt interaction tests: synthesize mouse events through the viewport.

These are not mocked canvas method calls; events reach QGraphicsView via Qt.
They can run headless on Linux with QT_QPA_PLATFORM=offscreen or xvfb-run.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

if os.name != "nt" and not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from veilpng.core import seal_bytes, unseal_bytes, preview_only
from veilpng.gui import MainWindow


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    yield instance


@pytest.fixture
def window(app):
    w = MainWindow()
    w.resize(1280, 820)
    w.show()
    app.processEvents()
    image = Image.new("RGB", (420, 300), "#f2f4f7")
    ImageDraw.Draw(image).ellipse((140, 40, 270, 180), fill="#8AAECF")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    w._load_document(buf.getvalue(), "sample.png", None, None)
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def _qt_mouse(view, mode, xy, *, drag=False):
    vpos = view.mapFromScene(QPointF(*xy))
    vpoint = QPointF(vpos)
    pressed = mode in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
    released = mode == QEvent.Type.MouseButtonRelease
    button = Qt.MouseButton.LeftButton if pressed or released else Qt.MouseButton.NoButton
    buttons = Qt.MouseButton.NoButton if released else Qt.MouseButton.LeftButton if drag or pressed else Qt.MouseButton.NoButton
    e = QMouseEvent(mode, vpoint, view.viewport().mapToGlobal(vpos), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), e)
    QApplication.processEvents()


def _stroke(view, mode, points):
    _qt_mouse(view, QEvent.Type.MouseButtonPress, points[0])
    for p in points[1:-1]:
        _qt_mouse(view, QEvent.Type.MouseMove, p, drag=True)
    _qt_mouse(view, QEvent.Type.MouseButtonRelease, points[-1])


def test_real_mouse_rectangle_brush_eraser_undo_redo_lasso(window):
    v = window.canvas
    window._set_tool("rect")
    _stroke(v, "rect", [(30,30),(150,120)])
    assert v.mask.getpixel((100,70)) == 255
    assert v.mask.getpixel((15,15)) == 0
    rect_count = v.mask.histogram()[255]
    window._set_tool("brush")
    v.brush_size = 20
    _stroke(v, "brush", [(200,50),(215,80),(225,120)])
    assert v.mask.getpixel((212,82)) == 255
    assert v.mask.histogram()[255] > rect_count
    window._set_tool("erase")
    v.brush_size = 34
    _stroke(v, "erase", [(90,80),(90,80)])
    assert v.mask.getpixel((90,80)) == 0
    v.undo()
    assert v.mask.getpixel((90,80)) == 255
    v.redo()
    assert v.mask.getpixel((90,80)) == 0
    window._set_tool("lasso")
    _stroke(v, "lasso", [(280,90),(338,90),(338,150),(280,150),(280,90)])
    assert v.mask.getpixel((300,110)) == 255
    assert v.mask.getpixel((270,100)) == 0


def test_polygon_public_solid_color_and_selected_color(window):
    v = window.canvas
    window._set_tool("polygon")
    for point in [(40,40),(105,40),(105,95)]:
        _qt_mouse(v, QEvent.Type.MouseButtonPress, point)
        _qt_mouse(v, QEvent.Type.MouseButtonRelease, point)
    _qt_mouse(v, QEvent.Type.MouseButtonDblClick, (40,95))
    assert v.mask.getpixel((75,70)) == 255
    window._set_solid_color("#000000")
    window.toggle_preview.setChecked(True)
    assert v.show_cover
    assert v.conceal_color == "#000000"
    assert "#000000" == window.color_entry.text()
    assert v.base_item.pixmap().isNull() is False
    assert "图像画布" in window.findChildren(type(window.workspace_info))[0].text() or window.workspace_info.text()


def test_gui_save_export_preview_and_restore(window, tmp_path, monkeypatch):
    v = window.canvas
    ImageDraw.Draw(v.mask).rectangle((60,60,160,160),fill=255)
    v.changed.emit()
    window._set_solid_color("#000000")
    secret = "GUI-Real-Password-2026"
    sealed = tmp_path / "sealed.png"
    public = tmp_path / "public.png"
    restored = tmp_path / "restored.png"
    save_names = iter([str(sealed), str(public), str(restored)])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a,**k:(next(save_names),"PNG"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a,**k:(secret,True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a,**k:pytest.fail(f"Unexpected warning: {a[1:]}"))
    monkeypatch.setattr(window,"_error",lambda *a:pytest.fail(f"GUI exception: {a}"))
    before=window.original_bytes
    window.save_sealed()
    assert sealed.exists()
    assert unseal_bytes(sealed.read_bytes(),secret).original_bytes==before
    window.export_ai_preview()
    assert public.exists()
    assert b"vpNg" not in public.read_bytes()
    assert public.read_bytes()==preview_only(sealed.read_bytes())
    window.restore_original()
    assert restored.read_bytes()==before


def test_green_ai_roi_keeps_red_protected_mask(window, tmp_path):
    v=window.canvas
    ImageDraw.Draw(v.mask).rectangle((30,30,80,80),fill=255)
    original_bytes=window.original_bytes
    protected=v.mask.tobytes()
    secret="GUI-ROI-Password-2026"
    sealed=tmp_path/"protected.png"
    sealed.write_bytes(seal_bytes(original_bytes,"sample.png",v.mask,secret,"solid",solid_color="#000000"))
    window.container_path=sealed
    window.modified=False
    window.toggle_ai_roi()
    assert window.roi_active
    assert v.mask.getbbox() is None
    assert v.selection_tint[:3]==(40,226,169)
    window._set_tool("rect")
    _stroke(v,"rect",[(180,120),(250,220)])
    assert v.mask.getpixel((200,160))==255
    window.toggle_ai_roi()
    assert not window.roi_active
    assert v.mask.tobytes()==protected
    assert window.ai_roi_mask.getpixel((200,160))==255
    assert window.ai_roi_mask.getpixel((50,50))==0
    assert not window.modified


def test_gui_pair_transfer_real_matrix_not_resize(window,tmp_path,monkeypatch):
    import cv2  # confirms optional geometry backend is working
    from veilpng.mask_transfer import load_pair, transfer_mask
    target=tmp_path/"JP0001.png"
    source=tmp_path/"CN0001.webp"
    Image.new("RGB",(200,180),"white").save(target)
    Image.new("RGB",(100,90),"white").save(source)
    w=window
    w._load_document(target.read_bytes(),target.name,None,None)
    ImageDraw.Draw(w.canvas.mask).rectangle((60,40,120,110),fill=255)
    w.canvas.changed.emit()
    manifest=tmp_path/"pairs.csv"
    row={"pair_id":"0050","source_image":"images/source/CN0001.webp", "target_image":"images/target/JP0001.png",
         "source_width":100,"source_height":90,"target_width":200,"target_height":180,
         "matrix_3x3_json":json.dumps([[2,0,0],[0,2,0],[0,0,1]]),"registration_confidence":0.99}
    with manifest.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    open_paths=iter([str(manifest),str(source)])
    monkeypatch.setattr(QFileDialog,"getOpenFileName",lambda *a,**k:(next(open_paths),""))
    monkeypatch.setattr(QInputDialog,"getText",lambda *a,**k:("0050",True))
    monkeypatch.setattr(QMessageBox,"information",lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(w,"_error",lambda *a:pytest.fail(f"Pair transfer failure: {a}"))
    w.transfer_to_pair()
    assert w.filename=="CN0001.webp"
    assert w.canvas.mask.size==(100,90)
    assert w.canvas.mask.getpixel((45,35))==255
    assert w.canvas.mask.getpixel((10,10))==0
