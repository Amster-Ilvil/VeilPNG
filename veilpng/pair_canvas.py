"""Side-by-side manga editor with matrix-synchronized CN/source and JP/target masks.

The red concealment mask and green AI edit permission mask are separate. A
completed mouse gesture in either QGraphicsView projects its binary selection
onto the opposite registered page using the actual homography.
"""
from __future__ import annotations

from PIL import Image, ImageChops
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QSplitter, QFrame, QGridLayout, QSizePolicy,
)

from .canvas import MaskCanvas
from .mask_transfer import RegistrationPair, transfer_mask


class MangaPairCanvas(QWidget):
    side_changed = Signal(str)
    mask_changed = Signal(str, str)  # side, mode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pair: RegistrationPair | None = None
        self.mode = 'conceal'
        self.last_side = 'source'
        self._synchronizing = False
        self._masks: dict[str, dict[str, Image.Image]] = {'conceal': {}, 'roi': {}}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        outer.setSpacing(7)

        header = QFrame(); header.setObjectName('workspaceHeader')
        top = QGridLayout(header)
        top.setContentsMargins(12, 7, 12, 7)
        title = QLabel('漫画双画布 · 中日配准同步'); title.setWordWrap(True)
        top.addWidget(title, 0, 0, 1, 4)
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(['红色：加密遮挡', '绿色：AI 编辑许可'])
        self.layer_combo.currentIndexChanged.connect(self.set_layer)
        top.addWidget(self.layer_combo, 1, 0, 1, 2)
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(['画笔', '橡皮擦', '矩形', '套索', '多边形', '平移'])
        self.tool_combo.currentIndexChanged.connect(self._change_tool)
        top.addWidget(self.tool_combo, 1, 2, 1, 2)
        top.addWidget(QLabel('笔刷'), 2, 0)
        self.brush_spin = QSpinBox(); self.brush_spin.setRange(2, 250); self.brush_spin.setValue(32)
        self.brush_spin.valueChanged.connect(self.set_brush_size)
        top.addWidget(self.brush_spin, 2, 1)
        self.preview_check = QCheckBox('遮盖预览')
        self.preview_check.toggled.connect(self.set_preview)
        top.addWidget(self.preview_check, 2, 2)
        fit = QPushButton('双图适应'); fit.clicked.connect(self.zoom_fit_both)
        top.addWidget(fit, 2, 3)
        for combo in (self.layer_combo, self.tool_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(5)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        top.setColumnStretch(2, 1)
        outer.addWidget(header)
        self.pair_note = QLabel('选择已配准的图片组后，在任意一侧绘制；松开鼠标后同步到另一侧。')
        self.pair_note.setObjectName('workspaceInfo')
        self.pair_note.setWordWrap(True)
        outer.addWidget(self.pair_note)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_canvas, self.source_title, source_widget = self._make_pane('source', '中文 · source')
        self.target_canvas, self.target_title, target_widget = self._make_pane('target', '日文 · target')
        self.splitter.addWidget(source_widget)
        self.splitter.addWidget(target_widget)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([520, 520])
        outer.addWidget(self.splitter, 1)
        footer = QLabel('左/右两侧都可使用画笔、矩形、套索、橡皮擦和撤销；只在鼠标操作完成后同步。红色加密区与绿色许可区互不覆盖。')
        footer.setObjectName('workspaceInfo')
        footer.setWordWrap(True)
        outer.addWidget(footer)
        self.source_canvas.changed.connect(lambda: self._after_changed('source'))
        self.target_canvas.changed.connect(lambda: self._after_changed('target'))
        self.set_tool('brush')
        self.set_brush_size(32)

    def _make_pane(self, side: str, label: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(4)
        caption = QLabel(label + ' · 未载入')
        caption.setObjectName('previewCaption')
        caption.setWordWrap(True)
        layout.addWidget(caption)
        canvas = MaskCanvas()
        canvas.setObjectName('manga_' + side + '_canvas')
        layout.addWidget(canvas, 1)
        return canvas, caption, widget

    @property
    def loaded(self) -> bool:
        return self.pair is not None and self.source_canvas.original is not None and self.target_canvas.original is not None

    def _canvas(self, side: str) -> MaskCanvas:
        if side not in ('source', 'target'):
            raise ValueError(side)
        return self.source_canvas if side == 'source' else self.target_canvas

    def set_pair(self, pair: RegistrationPair, source: Image.Image, target: Image.Image,
                 *, state: dict | None = None):
        if source.size != pair.source_size or target.size != pair.target_size:
            raise ValueError('Page dimensions do not match the chosen pair registration')
        self._synchronizing = True
        try:
            self.pair = pair
            self.mode = 'conceal'
            self.layer_combo.blockSignals(True)
            self.layer_combo.setCurrentIndex(0)
            self.layer_combo.blockSignals(False)
            self._masks = {
                layer: {side: Image.new('L', size, 0)
                        for side, size in (('source', pair.source_size), ('target', pair.target_size))}
                for layer in ('conceal', 'roi')
            }
            if state is not None:
                for layer in ('conceal', 'roi'):
                    for side in ('source', 'target'):
                        stored = state.get(layer, {}).get(side)
                        if stored is not None:
                            if stored.size != self._masks[layer][side].size:
                                raise ValueError('Saved mask size does not match selected pair')
                            self._masks[layer][side] = stored.copy()
            self.source_canvas.set_document(source, self._masks['conceal']['source'])
            self.target_canvas.set_document(target, self._masks['conceal']['target'])
            for canvas in (self.source_canvas, self.target_canvas):
                canvas.set_selection_tint((245, 68, 88, 135))
                canvas.set_preview(False)
            self.preview_check.blockSignals(True)
            self.preview_check.setChecked(False)
            self.preview_check.setEnabled(True)
            self.preview_check.blockSignals(False)
            self.source_title.setText(f'中文 · {pair.source_image}  {source.width}×{source.height}')
            self.target_title.setText(f'日文 · {pair.target_image}  {target.width}×{target.height}')
            self.last_side = 'source'
            self._note()
        finally:
            self._synchronizing = False

    def _note(self):
        if self.pair is None:
            return
        name = '红色加密遮挡' if self.mode == 'conceal' else '绿色 AI 许可区'
        counts = []
        for side in ('source', 'target'):
            mask = self._masks[self.mode][side]
            counts.append(f'{side} {mask.histogram()[255]:,} 像素')
        self.pair_note.setText(f'配对 {self.pair.pair_id} · {name} · 最近绘制：{self.last_side} · ' + ' / '.join(counts))

    def export_state(self) -> dict:
        if not self.loaded:
            return {}
        for side in ('source', 'target'):
            self._masks[self.mode][side] = self._canvas(side).mask.copy()
        return {layer: {side: mask.copy() for side, mask in group.items()}
                for layer, group in self._masks.items()}

    def mask_for(self, side: str, layer: str) -> Image.Image:
        if not self.loaded:
            raise ValueError('No registered manga pair is open')
        if layer not in ('conceal', 'roi'):
            raise ValueError(layer)
        if layer == self.mode:
            return self._canvas(side).mask.copy()
        return self._masks[layer][side].copy()

    def set_layer(self, index: int):
        if not self.loaded:
            return
        new_mode = 'roi' if index == 1 else 'conceal'
        if new_mode == self.mode:
            return
        self.export_state()
        self._synchronizing = True
        try:
            self.mode = new_mode
            self.preview_check.blockSignals(True)
            self.preview_check.setChecked(False)
            self.preview_check.setEnabled(new_mode == 'conceal')
            self.preview_check.blockSignals(False)
            for side in ('source', 'target'):
                canvas = self._canvas(side)
                canvas.mask = self._masks[new_mode][side].copy()
                canvas.set_preview(False)
                canvas.set_selection_tint((40, 226, 169, 140) if new_mode == 'roi'
                                          else (245, 68, 88, 135))
                canvas._refresh_overlay()
            self._note()
        finally:
            self._synchronizing = False

    def set_style(self, style: str, block: int, color: str):
        for canvas in (self.source_canvas, self.target_canvas):
            canvas.set_conceal_style(style, block, color)

    def set_preview(self, enabled: bool):
        if self.mode == 'roi':
            self.preview_check.blockSignals(True)
            self.preview_check.setChecked(False)
            self.preview_check.blockSignals(False)
            return
        for canvas in (self.source_canvas, self.target_canvas):
            canvas.set_preview(enabled)

    def _change_tool(self, index: int):
        tool = ('brush', 'erase', 'rect', 'lasso', 'polygon', 'pan')[index]
        self.set_tool(tool)

    def set_tool(self, tool: str):
        for canvas in (self.source_canvas, self.target_canvas):
            canvas.set_tool(tool)

    def set_brush_size(self, size: int):
        for canvas in (self.source_canvas, self.target_canvas):
            canvas.brush_size = size

    def zoom_fit_both(self):
        for canvas in (self.source_canvas, self.target_canvas):
            canvas.zoom_fit()

    def _after_changed(self, side: str):
        if self._synchronizing or not self.loaded:
            return
        self.last_side = side
        other = 'target' if side == 'source' else 'source'
        self._synchronizing = True
        try:
            current = self._canvas(side).mask.copy()
            # Keep the ROI strictly outside protected pixels even when edited by hand.
            if self.mode == 'roi':
                current = ImageChops.subtract(current, self._masks['conceal'][side])
                self._canvas(side).mask = current.copy()
                self._canvas(side)._refresh_overlay()
            mapped = transfer_mask(current, self.pair, from_space=side,
                                   expand_px=1 if self.mode == 'conceal' else 0)
            if self.mode == 'roi':
                mapped = ImageChops.subtract(mapped, self._masks['conceal'][other])
            self._masks[self.mode][side] = current
            self._masks[self.mode][other] = mapped
            second = self._canvas(other)
            second.mask = mapped.copy()
            second.undo_stack.clear()
            second.redo_stack.clear()
            second._refresh_overlay()
            if self.mode == 'conceal':
                for which in ('source', 'target'):
                    self._masks['roi'][which] = ImageChops.subtract(self._masks['roi'][which],
                                                                    self._masks['conceal'][which])
            self._note()
            self.side_changed.emit(side)
            self.mask_changed.emit(side, self.mode)
        finally:
            self._synchronizing = False
