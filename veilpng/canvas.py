"""PySide6 manual image-mask editor: rectangle, freehand, polygon, brush, eraser."""
from __future__ import annotations

import math
import zlib

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView,
)

from .imaging import DEFAULT_SOLID_COLOR, binary_mask, render_preview


def _pixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    # .copy() ensures the QImage owns pixel data after Python bytes are collected.
    bits = rgba.tobytes()
    qimg = QImage(bits, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


class MaskCanvas(QGraphicsView):
    changed = Signal()
    mouse_info = Signal(str)
    zoom_changed = Signal(float)
    TOOLS = ("brush", "erase", "rect", "lasso", "polygon", "pan")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.original: Image.Image | None = None
        self.mask: Image.Image | None = None
        self.base_item = QGraphicsPixmapItem()
        self.overlay_item = QGraphicsPixmapItem()
        self.base_item.setZValue(0)
        self.overlay_item.setZValue(1)
        self.scene_obj.addItem(self.base_item)
        self.scene_obj.addItem(self.overlay_item)
        self.temp_item = None
        self.tool = "brush"
        self.brush_size = 32
        self.show_cover = False
        self.conceal_style = "solid"
        self.conceal_color = DEFAULT_SOLID_COLOR
        self.selection_tint = (245, 68, 88, 135)
        self.block_size = 18
        self.start_point: tuple[int, int] | None = None
        self.previous_point: tuple[int, int] | None = None
        self.points: list[tuple[int, int]] = []
        self.drawing = False
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#EDF2F9")))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self._paint_redraw_timer = QTimer(self)
        self._paint_redraw_timer.setSingleShot(True)
        self._paint_redraw_timer.timeout.connect(self._refresh_overlay)

    def set_document(self, image: Image.Image, mask: Image.Image | None = None):
        self.original = image.convert("RGBA")
        self.mask = binary_mask(mask, self.original.size) if mask is not None else Image.new("L", image.size, 0)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.points.clear()
        self._clear_temp()
        self.base_item.setPixmap(_pixmap(self.original))
        self._refresh_overlay()
        self.scene_obj.setSceneRect(0, 0, image.width, image.height)
        self.resetTransform()
        self.fitInView(self.scene_obj.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_changed.emit(self.transform().m11())
        self.changed.emit()

    def set_tool(self, tool: str):
        if tool not in self.TOOLS:
            raise ValueError(tool)
        self.cancel_polygon()
        self.tool = tool
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == "pan" else QGraphicsView.DragMode.NoDrag)
        if tool in ("brush", "erase"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif tool == "pan":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def set_preview(self, enabled: bool):
        self.show_cover = enabled
        self._refresh_overlay()

    def set_conceal_style(self, style: str, block: int, solid_color: str = DEFAULT_SOLID_COLOR):
        self.conceal_style = style
        self.block_size = block
        self.conceal_color = solid_color
        if self.show_cover:
            self._refresh_overlay()

    def set_selection_tint(self, rgba: tuple[int,int,int,int]):
        self.selection_tint = rgba
        self._refresh_overlay()

    def _refresh_overlay(self):
        if self.original is None or self.mask is None:
            return
        if self.show_cover:
            self.base_item.setPixmap(_pixmap(render_preview(self.original, self.mask, self.conceal_style, self.block_size, self.conceal_color)))
            self.overlay_item.setVisible(False)
        else:
            self.base_item.setPixmap(_pixmap(self.original))
            tint = Image.new("RGBA", self.mask.size, (*self.selection_tint[:3], 0))
            tint.putalpha(self.mask.point(lambda a: self.selection_tint[3] if a else 0))
            self.overlay_item.setPixmap(_pixmap(tint))
            self.overlay_item.setVisible(True)
        self.viewport().update()

    def _cursor_xy(self, event) -> tuple[int, int]:
        assert self.original is not None
        p = self.mapToScene(event.position().toPoint())
        return (
            max(0, min(self.original.width - 1, int(p.x()))),
            max(0, min(self.original.height - 1, int(p.y()))),
        )

    def _cursor_is_inside(self, event) -> bool:
        if self.original is None:
            return False
        p = self.mapToScene(event.position().toPoint())
        return 0 <= p.x() < self.original.width and 0 <= p.y() < self.original.height

    def _snapshot(self):
        assert self.mask is not None
        self.undo_stack.append(zlib.compress(self.mask.tobytes(), level=1))
        self.undo_stack = self.undo_stack[-20:]
        self.redo_stack.clear()

    def _restore_snapshot(self, compressed: bytes):
        assert self.mask is not None
        self.mask = Image.frombytes("L", self.mask.size, zlib.decompress(compressed))
        self._refresh_overlay()
        self.changed.emit()

    def undo(self):
        if self.mask is not None and self.undo_stack:
            self.redo_stack.append(zlib.compress(self.mask.tobytes(), level=1))
            self._restore_snapshot(self.undo_stack.pop())

    def redo(self):
        if self.mask is not None and self.redo_stack:
            self.undo_stack.append(zlib.compress(self.mask.tobytes(), level=1))
            self._restore_snapshot(self.redo_stack.pop())

    def clear_mask(self):
        if self.mask is None:
            return
        self._snapshot()
        self.mask.paste(0, (0, 0, self.mask.width, self.mask.height))
        self._refresh_overlay()
        self.changed.emit()

    def invert_mask(self):
        if self.mask is None:
            return
        self._snapshot()
        self.mask = self.mask.point(lambda v: 255 - v)
        self._refresh_overlay()
        self.changed.emit()

    def select_all(self):
        if self.mask is None:
            return
        self._snapshot()
        self.mask.paste(255, (0, 0, self.mask.width, self.mask.height))
        self._refresh_overlay()
        self.changed.emit()

    def _paint_stroke(self, previous: tuple[int, int], current: tuple[int, int]):
        if self.mask is None:
            return
        d = ImageDraw.Draw(self.mask)
        r = max(1, self.brush_size // 2)
        color = 0 if self.tool == "erase" else 255
        d.line((previous[0], previous[1], current[0], current[1]), fill=color, width=max(1, self.brush_size))
        for x, y in (previous, current):
            d.ellipse((x-r, y-r, x+r, y+r), fill=color)
        # Full bitmap conversion is expensive on multi-megapixel pages.
        # Coalesce pointer moves; the final stroke is rendered immediately on release.
        if not self._paint_redraw_timer.isActive():
            self._paint_redraw_timer.start(35)

    def _clear_temp(self):
        if self.temp_item is not None:
            self.scene_obj.removeItem(self.temp_item)
            self.temp_item = None

    def _draw_outline(self, points: list[tuple[int, int]], closed: bool = False):
        self._clear_temp()
        if not points:
            return
        path = QPainterPath(QPointF(*points[0]))
        for x, y in points[1:]:
            path.lineTo(x, y)
        if closed:
            path.closeSubpath()
        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor("#ffd166"), 2, Qt.PenStyle.DashLine))
        item.setZValue(5)
        self.scene_obj.addItem(item)
        self.temp_item = item

    def _draw_rectangle(self, a: tuple[int, int], b: tuple[int, int]):
        self._clear_temp()
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        item = QGraphicsRectItem(QRectF(x0, y0, x1-x0, y1-y0))
        item.setPen(QPen(QColor("#ffd166"), 2, Qt.PenStyle.DashLine))
        item.setZValue(5)
        self.scene_obj.addItem(item)
        self.temp_item = item

    def _finish_polygon(self):
        if self.mask is None:
            return
        points = self.points.copy()
        self.points.clear()
        self._clear_temp()
        if len(set(points)) < 3:
            return
        self._snapshot()
        ImageDraw.Draw(self.mask).polygon(points, fill=255)
        self._refresh_overlay()
        self.changed.emit()

    def cancel_polygon(self):
        self.points.clear()
        self._clear_temp()

    def mousePressEvent(self, event):
        if self.original is None or self.tool == "pan" or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        if not self._cursor_is_inside(event):
            return
        p = self._cursor_xy(event)
        if self.tool == "polygon":
            self.points.append(p)
            self._draw_outline(self.points)
            return
        self.start_point = p
        self.previous_point = p
        self.drawing = True
        if self.tool in ("brush", "erase"):
            self._snapshot()
            self._paint_stroke(p, p)
        elif self.tool == "lasso":
            self.points = [p]
        event.accept()

    def mouseMoveEvent(self, event):
        if self.original is None:
            return super().mouseMoveEvent(event)
        p = self._cursor_xy(event)
        self.mouse_info.emit(f"X: {p[0]}   Y: {p[1]}   缩放: {self.transform().m11()*100:.0f}%")
        if self.tool == "polygon" and self.points:
            self._draw_outline(self.points + [p])
        elif self.drawing and (event.buttons() & Qt.MouseButton.LeftButton):
            if self.tool in ("brush", "erase") and self.previous_point:
                self._paint_stroke(self.previous_point, p)
                self.previous_point = p
            elif self.tool == "rect" and self.start_point:
                self._draw_rectangle(self.start_point, p)
            elif self.tool == "lasso":
                if not self.points or math.dist(p, self.points[-1]) > 1.4:
                    self.points.append(p)
                    self._draw_outline(self.points)
        else:
            return super().mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event):
        if not self.drawing or event.button() != Qt.MouseButton.LeftButton or self.original is None or self.mask is None:
            return super().mouseReleaseEvent(event)
        p = self._cursor_xy(event)
        if self.tool == "rect" and self.start_point:
            self._snapshot()
            x0, x1 = sorted((self.start_point[0], p[0]))
            y0, y1 = sorted((self.start_point[1], p[1]))
            ImageDraw.Draw(self.mask).rectangle((x0, y0, x1, y1), fill=255)
        elif self.tool == "lasso":
            if len(set(self.points)) >= 3:
                self._snapshot()
                ImageDraw.Draw(self.mask).polygon(self.points, fill=255)
        self.start_point = None
        self.previous_point = None
        self.drawing = False
        self.points = []
        self._clear_temp()
        self._paint_redraw_timer.stop()
        self._refresh_overlay()
        self.changed.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.tool == "polygon" and self.original is not None:
            if self._cursor_is_inside(event):
                p = self._cursor_xy(event)
                if not self.points or self.points[-1] != p:
                    self.points.append(p)
            self._finish_polygon()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tool == "polygon":
            self._finish_polygon()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_polygon()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.original is None:
            return super().wheelEvent(event)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        zoom = self.transform().m11() * factor
        if 0.03 <= zoom <= 16:
            self.scale(factor, factor)
            self.zoom_changed.emit(self.transform().m11())
        event.accept()

    def zoom_fit(self):
        if self.original is not None:
            self.fitInView(self.scene_obj.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoom_changed.emit(self.transform().m11())

    def zoom_one(self):
        self.resetTransform()
        self.zoom_changed.emit(self.transform().m11())
