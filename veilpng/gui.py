"""Cross-platform VeilPNG PySide6 desktop UI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QGroupBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QStatusBar, QVBoxLayout, QWidget, QLineEdit,
)

from .canvas import MaskCanvas
from .gui_theme import STYLESHEET
from .core import (
    audit_exported_preview, inspect_container, merge_ai_preview, preview_only, repack_preview,
    seal_bytes, unseal_bytes,
)
from .imaging import DEFAULT_SOLID_COLOR, normalize_solid_color, image_to_png_bytes, load_image, render_preview
from .png_container import extract_private_chunk


STYLES = {
    "纯色遮盖（可选颜色，推荐）": "solid",
    "随机噪声（推荐）": "noise",
    "像素马赛克（非强隐私）": "mosaic",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VeilPNG 0.4.0 · 双层加密图像工作站")
        self.resize(1360, 880)
        self.original_bytes: bytes | None = None
        self.filename: str = ""
        self.container_path: Path | None = None
        self.modified = False
        self.roi_active = False
        self.ai_roi_mask: Image.Image | None = None
        self.saved_conceal_mask: Image.Image | None = None
        self.solid_color = DEFAULT_SOLID_COLOR
        self._loading = False
        self.canvas = MaskCanvas()
        self.canvas.changed.connect(self._mask_changed)
        self.canvas.mouse_info.connect(self._show_mouse_info)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._build_ui()
        self._shortcuts()
        self.status.showMessage("打开图片后，用画笔、矩形、套索或多边形选择需要加密遮挡的区域")

    def _btn(self, text: str, callback, *, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("primary", primary)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(callback)
        b.setMinimumHeight(36)
        return b

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(305)
        sidebar.setMaximumWidth(375)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(17, 18, 17, 16)
        left.setSpacing(10)

        title = QLabel("VeilPNG")
        title.setObjectName("title")
        subtitle = QLabel("局部防窥 · 加密复原 · AI 安全编辑")
        subtitle.setObjectName("muted")
        left.addWidget(title)
        left.addWidget(subtitle)
        left.addWidget(self._btn("打开原图 / 双层 PNG", self.open_image, primary=True))
        left.addWidget(self._btn("保存为加密双层 PNG", self.save_sealed))
        left.addWidget(self._btn("解密并无损恢复原文件", self.restore_original))

        edit_group = QGroupBox("手动选择加密区域")
        edit_layout = QVBoxLayout(edit_group)
        edit_layout.setSpacing(8)
        tools_grid = QGridLayout()
        tools_grid.setHorizontalSpacing(6)
        tools_grid.setVerticalSpacing(6)
        tool_buttons = [
            ("画笔涂抹", "brush"),
            ("橡皮擦", "erase"),
            ("矩形框选", "rect"),
            ("自由套索", "lasso"),
            ("多边形选区", "polygon"),
            ("平移画布", "pan"),
        ]
        self.tool_buttons = {}
        for i, (label, tool) in enumerate(tool_buttons):
            b = self._btn(label, lambda checked=False, t=tool: self._set_tool(t))
            b.setCheckable(True)
            self.tool_buttons[tool] = b
            tools_grid.addWidget(b, i // 2, i % 2)
        edit_layout.addLayout(tools_grid)
        self.tool_buttons["brush"].setChecked(True)
        self.brush_label = QLabel("画笔宽度：32 px")
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(2, 250)
        self.brush_slider.setValue(32)
        self.brush_slider.valueChanged.connect(self._change_brush)
        edit_layout.addWidget(self.brush_label)
        edit_layout.addWidget(self.brush_slider)
        edit_layout.addWidget(QLabel("多边形：逐点单击，双击/Enter 完成；Esc 取消"))
        buttons = QHBoxLayout()
        buttons.addWidget(self._btn("撤销", self.canvas.undo))
        buttons.addWidget(self._btn("重做", self.canvas.redo))
        edit_layout.addLayout(buttons)
        buttons2 = QHBoxLayout()
        buttons2.addWidget(self._btn("反选", self.canvas.invert_mask))
        buttons2.addWidget(self._btn("清空", self.canvas.clear_mask))
        edit_layout.addLayout(buttons2)
        edit_layout.addWidget(self._btn("全图选中", self.canvas.select_all))
        edit_layout.addWidget(self._btn("配对映射：复制选区到日/中文对应图", self.transfer_to_pair))
        edit_layout.addWidget(QLabel("使用 Folirina 的真实 pairs.csv 配准矩阵，不进行简单缩放。"))
        left.addWidget(edit_group)

        preview_group = QGroupBox("表层遮挡设置")
        pv = QVBoxLayout(preview_group)
        self.style_combo = QComboBox()
        self.style_combo.addItems(STYLES)
        self.style_combo.currentTextChanged.connect(self._style_changed)
        pv.addWidget(self.style_combo)
        color_row = QHBoxLayout()
        self.color_entry = QLineEdit(self.solid_color)
        self.color_entry.setMaxLength(7)
        self.color_entry.setToolTip("纯色填充必须为 #RRGGBB，不支持半透明")
        self.color_entry.editingFinished.connect(self._color_entry_changed)
        self.color_pick_btn = self._btn("选颜色", self._pick_color)
        color_row.addWidget(QLabel("纯色颜色"))
        color_row.addWidget(self.color_entry)
        color_row.addWidget(self.color_pick_btn)
        pv.addLayout(color_row)
        block_row = QHBoxLayout()
        block_row.addWidget(QLabel("马赛克块尺寸"))
        self.block_spin = QSpinBox()
        self.block_spin.setRange(2, 128)
        self.block_spin.setValue(18)
        self.block_spin.valueChanged.connect(self._style_changed)
        block_row.addWidget(self.block_spin)
        pv.addLayout(block_row)
        self.toggle_preview = QCheckBox("显示公开预览（隐藏红色蒙版）")
        self.toggle_preview.toggled.connect(self.canvas.set_preview)
        pv.addWidget(self.toggle_preview)
        self.mask_stat = QLabel("加密面积：0%")
        pv.addWidget(self.mask_stat)
        pv.addWidget(QLabel("纯色不包含原像素；马赛克仍会暴露轮廓。"))
        left.addWidget(preview_group)
        self._refresh_color_controls()

        ai_group = QGroupBox("AI 往返处理")
        ai = QVBoxLayout(ai_group)
        ai.addWidget(self._btn("1 · 导出可上传给 AI 的预览", self.export_ai_preview))
        ai.addWidget(self._btn("2A · 回封装表层（原图不变）", self.ai_repack))
        ai.addWidget(self._btn("2B · 合并 AI 改动并重新加密（旧版整页）", self.ai_merge))
        self.roi_button = self._btn("3 · 编辑 GPT 可写入区域（绿色）", self.toggle_ai_roi)
        ai.addWidget(self.roi_button)
        self.extraction_combo = QComboBox()
        self.extraction_combo.addItems(["彩色标记提取（黑白漫画推荐）", "像素差异提取（需人工复核）"])
        ai.addWidget(self.extraction_combo)
        ai.addWidget(self._btn("4A · 智能 A1：只改表层，原密文不变", lambda:self.ai_smart_edit("A1")))
        ai.addWidget(self._btn("4B · 智能 A2：只写回绿色区域", lambda:self.ai_smart_edit("A2")))
        tip = QLabel("只上传上方导出的普通预览 PNG；不要上传带有密文的双层 PNG。\n2B 只合并未遮挡区域，选中区域保持原像素。")
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        ai.addWidget(tip)
        left.addWidget(ai_group)
        left.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(sidebar)
        splitter.addWidget(scroll)
        workspace = QWidget()
        workspace.setObjectName("workspaceRoot")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 10, 12, 9)
        workspace_layout.setSpacing(8)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 14, 8)
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        workspace_title = QLabel("图像画布")
        workspace_title.setObjectName("workspaceTitle")
        self.workspace_info = QLabel("导入图片以开始 · 选择的遮盖区仅公开为替换像素")
        self.workspace_info.setObjectName("workspaceInfo")
        header_text.addWidget(workspace_title)
        header_text.addWidget(self.workspace_info)
        header_layout.addLayout(header_text)
        header_layout.addStretch()
        fit_btn = self._btn("适应窗口", self.canvas.zoom_fit)
        fit_btn.setObjectName("toolbarBtn")
        actual_btn = self._btn("100%", self.canvas.zoom_one)
        actual_btn.setObjectName("toolbarBtn")
        header_layout.addWidget(fit_btn)
        header_layout.addWidget(actual_btn)
        workspace_layout.addWidget(header)
        self.canvas.setObjectName("imageCanvas")
        workspace_layout.addWidget(self.canvas, 1)
        footer = QLabel("红色：加密遮挡选区     绿色：允许 AI 编辑区     Ctrl+滚轮 / 滚轮：缩放     Ctrl+Z：撤销")
        footer.setObjectName("workspaceInfo")
        footer.setWordWrap(True)
        workspace_layout.addWidget(footer)
        splitter.addWidget(workspace)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([355, 1005])
        self.setCentralWidget(splitter)
        self.setStyleSheet(STYLESHEET)

    def _shortcuts(self):
        for key, call in (("Ctrl+Z", self.canvas.undo), ("Ctrl+Shift+Z", self.canvas.redo),
                          ("Ctrl+O", self.open_image), ("Ctrl+S", self.save_sealed),
                          ("Ctrl+0", self.canvas.zoom_fit), ("Ctrl+1", self.canvas.zoom_one)):
            sh = QShortcut(QKeySequence(key), self)
            sh.activated.connect(call)

    def _set_tool(self, tool: str):
        self.canvas.set_tool(tool)
        for key, b in self.tool_buttons.items():
            b.setChecked(tool == key)
        self.status.showMessage(f"工具：{tool}")

    def _change_brush(self, value: int):
        self.canvas.brush_size = value
        self.brush_label.setText(f"画笔宽度：{value} px")

    def _style_changed(self, *_):
        self.canvas.set_conceal_style(self._style(), self.block_spin.value(), self.solid_color)
        self._refresh_color_controls()
        if self.original_bytes is not None and not self._loading:
            self.modified = True

    def _refresh_color_controls(self):
        enabled = self._style() == "solid"
        self.color_pick_btn.setEnabled(enabled)
        self.color_entry.setEnabled(enabled)
        self.color_entry.setText(self.solid_color)
        self.color_pick_btn.setStyleSheet(
            f"background-color: {self.solid_color}; color: "
            f"{'#000000' if int(self.solid_color[1:3], 16) + int(self.solid_color[3:5], 16) + int(self.solid_color[5:7], 16) > 420 else '#FFFFFF'};"
        )

    def _set_solid_color(self, color: str):
        new = normalize_solid_color(color)
        if new != self.solid_color:
            self.solid_color = new
            self._style_changed()
        self._refresh_color_controls()

    def _color_entry_changed(self):
        try:
            self._set_solid_color(self.color_entry.text())
        except ValueError as exc:
            self.color_entry.setText(self.solid_color)
            QMessageBox.warning(self, "颜色格式错误", str(exc))

    def _pick_color(self):
        chosen = QColorDialog.getColor(QColor(self.solid_color), self, "选择纯色遮盖颜色")
        if chosen.isValid():
            self._set_solid_color(chosen.name().upper())

    def _style(self) -> str:
        return STYLES[self.style_combo.currentText()]

    def _mask_changed(self):
        if not self._loading and self.original_bytes is not None and not self.roi_active:
            self.modified = True
        if self.canvas.mask is not None:
            n = self.canvas.mask.histogram()[255]
            total = self.canvas.mask.width * self.canvas.mask.height
            self.mask_stat.setText(f"加密面积：{n / total * 100:.2f}%（{n:,} / {total:,} 像素）")
            if hasattr(self, "workspace_info"):
                mode = "AI 编辑许可" if self.roi_active else "受保护遮挡"
                self.workspace_info.setText(f"{self.filename or '未载入文件'}  |  {self.canvas.mask.width} × {self.canvas.mask.height}  |  {mode} {n / total * 100:.2f}%")

    def _show_mouse_info(self, s: str):
        self.status.showMessage(s)

    def _error(self, action: str, exception: Exception):
        QMessageBox.critical(self, f"{action}失败", f"{type(exception).__name__}: {exception}")

    def _get_password(self, confirm: bool = False) -> str | None:
        text, ok = QInputDialog.getText(self, "加密密码", "输入密码（至少8字符，建议12字符以上）：", QLineEdit.EchoMode.Password)
        if not ok:
            return None
        if confirm:
            other, ok = QInputDialog.getText(self, "确认加密密码", "再次输入相同密码：", QLineEdit.EchoMode.Password)
            if not ok:
                return None
            if text != other:
                QMessageBox.warning(self, "密码不一致", "两次输入的密码不同")
                return None
        return text

    def _need_doc(self) -> bool:
        if self.original_bytes is None or self.canvas.mask is None or self.canvas.original is None:
            QMessageBox.information(self, "尚未打开图片", "请先打开原图或已有双层 PNG")
            return False
        return True

    def _load_document(self, data: bytes, name: str, mask: Image.Image | None, container: Path | None):
        original = load_image(data)
        self._loading = True
        try:
            self.roi_active = False
            self.ai_roi_mask = None
            self.saved_conceal_mask = None
            if hasattr(self, "roi_button"):
                self.roi_button.setText("3 · 编辑 GPT 可写入区域（绿色）")
            self.canvas.set_selection_tint((245, 68, 88, 135))
            self.original_bytes = data
            self.filename = name
            self.container_path = container
            self.canvas.set_document(original, mask)
            if container is not None:
                info = inspect_container(container.read_bytes())
                selected_style = info.get("preview_style", "solid")
                name_of_style = next((name for name, value in STYLES.items() if value == selected_style), "纯色遮盖（可选颜色，推荐）")
                self.style_combo.blockSignals(True)
                self.block_spin.blockSignals(True)
                self.style_combo.setCurrentText(name_of_style)
                self.block_spin.setValue(int(info.get("preview_block", 18)))
                self.solid_color = normalize_solid_color(info.get("preview_solid_color", DEFAULT_SOLID_COLOR))
                self.style_combo.blockSignals(False)
                self.block_spin.blockSignals(False)
                self.canvas.set_conceal_style(self._style(), self.block_spin.value(), self.solid_color)
            else:
                self.canvas.set_conceal_style(self._style(), self.block_spin.value(), self.solid_color)
            self._refresh_color_controls()
            self.toggle_preview.setChecked(False)
        finally:
            self._loading = False
        self.modified = False
        self.setWindowTitle(f"VeilPNG · {name}")
        self.status.showMessage(f"已打开 {name}，尺寸 {original.width} × {original.height}")

    def open_image(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "打开原图或加密双层 PNG", "", "图像 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;全部文件 (*)"
        )
        if not path_str:
            return
        try:
            path = Path(path_str)
            data = path.read_bytes()
            if data.startswith(b"\x89PNG\r\n\x1a\n") and extract_private_chunk(data) is not None:
                pw = self._get_password()
                if pw is None:
                    return
                asset = unseal_bytes(data, pw)
                self._load_document(asset.original_bytes, asset.filename, asset.mask, path)
                self.status.showMessage("已成功认证解密双层 PNG；选择区域可继续修改，保存会重新加密")
            else:
                self._load_document(data, path.name, None, None)
        except Exception as e:
            self._error("打开图片", e)

    def save_sealed(self):
        if self.roi_active:
            QMessageBox.warning(self,"处于 GPT 区域模式","请先点击绿色选区按钮保存编辑范围，再操作原始加密选区。")
            return
        if not self._need_doc():
            return
        path_str, _ = QFileDialog.getSaveFileName(self, "保存双层 PNG", "sealed_" + Path(self.filename).stem + ".png", "PNG (*.png)")
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        pw = self._get_password(confirm=True)
        if pw is None:
            return
        try:
            assert self.original_bytes is not None and self.canvas.mask is not None
            if not self.canvas.mask.getbbox():
                if QMessageBox.question(self, "没有遮挡区域", "当前未选择加密区域，公开预览将显示完整图片。是否仍继续？") != QMessageBox.StandardButton.Yes:
                    return
            sealed = seal_bytes(self.original_bytes, self.filename, self.canvas.mask, pw, self._style(), self.block_spin.value(), solid_color=self.solid_color)
            path.write_bytes(sealed)
            # Verify both encrypted payload and exact source file before reporting success.
            assert unseal_bytes(sealed, pw).original_bytes == self.original_bytes
            self.container_path = path
            self.modified = False
            QMessageBox.information(self, "成功", f"双层 PNG 已保存并成功校验：\n{path}\n\n上传给 AI 前请使用“导出可上传的预览”。")
        except Exception as e:
            self._error("加密保存", e)

    def transfer_to_pair(self):
        """Open a registered source/target scan with safely projected current mask."""
        if self.roi_active:
            QMessageBox.warning(self, "请先退出绿色选区模式", "当前只有红色加密遮挡蒙版可被映射。")
            return
        if not self._need_doc():
            return
        manifest, _ = QFileDialog.getOpenFileName(self, "选择 Folirina 配准 pairs.csv", "", "配准表 (*.csv)")
        if not manifest:
            return
        pair_id, ok = QInputDialog.getText(self, "配对编号", "输入 pairs.csv 中的 pair_id（如 0050）：")
        if not ok or not pair_id.strip():
            return
        try:
            from .mask_transfer import load_pair, transfer_mask
            pair = load_pair(manifest, pair_id.strip())
            current = Path(self.filename).name.casefold()
            if current == Path(pair.target_image).name.casefold():
                from_space, other_name = "target", Path(pair.source_image).name
            elif current == Path(pair.source_image).name.casefold():
                from_space, other_name = "source", Path(pair.target_image).name
            else:
                raise ValueError("当前图像的文件名不属于该配对。请使用正确的 pair_id。")
            assert self.canvas.mask is not None
            mapped = transfer_mask(self.canvas.mask, pair, from_space=from_space, expand_px=1)
            other, _ = QFileDialog.getOpenFileName(self, f"选择对应图片 {other_name}", "", "图像 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
            if not other:
                return
            if Path(other).name.casefold() != other_name.casefold():
                raise ValueError(f"选择的文件名必须为 {other_name}，避免映射到错误图片")
            raw = Path(other).read_bytes()
            image = load_image(raw)
            if image.size != mapped.size:
                raise ValueError(f"目标文件尺寸 {image.size} 与配准目标 {mapped.size} 不符")
            covered = mapped.histogram()[255]
            # This switches documents by design. Original is never overwritten.
            self._load_document(raw, Path(other).name, mapped, None)
            QMessageBox.information(self, "配对遮盖已映射",
                f"{pair.pair_id}：{from_space} → {'source' if from_space=='target' else 'target'}\n"
                f"遮盖 {covered:,} 像素。已切换至 {other_name}；请检查遮盖边界，然后另存为双层 PNG。")
        except Exception as exc:
            self._error("配对映射", exc)

    def restore_original(self):
        source = self._pick_sealed_file()
        if source is None:
            return
        pw = self._get_password()
        if pw is None:
            return
        try:
            asset = unseal_bytes(source.read_bytes(), pw)
            out, _ = QFileDialog.getSaveFileName(self, "原始文件无损恢复", asset.filename, "所有文件 (*)")
            if out:
                out_path = Path(out)
                if out_path.resolve() == source.resolve():
                    raise ValueError("不能覆盖加密容器文件")
                out_path.write_bytes(asset.original_bytes)
                QMessageBox.information(self, "已恢复", f"原图原始字节已恢复：\n{out_path}\nSHA-256：{asset.source_sha256}")
        except Exception as e:
            self._error("无损解密", e)

    def _pick_sealed_file(self) -> Path | None:
        if self.container_path and self.container_path.exists() and not self.modified:
            return self.container_path
        p, _ = QFileDialog.getOpenFileName(self, "选择已有双层加密 PNG", "", "PNG (*.png)")
        return Path(p) if p else None

    def export_ai_preview(self):
        if self.roi_active:
            QMessageBox.warning(self,"编辑区域未保存","请先退出绿色 GPT 选区模式。")
            return
        if not self._need_doc():
            return
        if self.container_path is None or self.modified:
            QMessageBox.information(self, "先封装双层文件", "请先保存当前选择为双层 PNG，以保证 AI 回封装时使用的是同一版选区蒙版。")
            return
        name = Path(self.filename).stem + "_AI_公开预览.png"
        p, _ = QFileDialog.getSaveFileName(self, "导出不含密文的 AI 预览", name, "PNG (*.png)")
        if not p:
            return
        try:
            pw = self._get_password()
            if pw is None:
                return
            container_bytes = self.container_path.read_bytes()
            preview_bytes = preview_only(container_bytes)
            audit = audit_exported_preview(container_bytes, preview_bytes, pw)
            if not audit["mechanical_audit_pass"]:
                raise ValueError("预览机械隐私审计失败，已取消导出")
            Path(p).write_bytes(preview_bytes)
            QMessageBox.information(self, "预览已导出并校验",
                f"已剥离加密底层，遮盖比例：{audit['coverage_percent']:.2f}%。\n"
                f"纯色像素检查：{audit['covered_area_uniform_color']}；被遮盖区域不透明：{audit['covered_area_opaque']}。\n"
                "可见上下文仍可能暴露信息，不能保证 AI 一定接受处理。")
        except Exception as e:
            self._error("导出 AI 预览", e)

    def _pick_ai(self) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 AI 返回的 PNG", "", "PNG / 图片 (*.png *.jpg *.jpeg *.webp)")
        return Path(path) if path else None

    def _ai_inputs(self):
        if self.roi_active:
            QMessageBox.warning(self, "GPT 选区编辑中", "请先保存绿色 GPT 选区并返回保护蒙版。")
            return None
        if self.modified:
            QMessageBox.warning(self, "选区已修改", "请先重新保存双层 PNG，或取消修改后操作。")
            return None
        container = self._pick_sealed_file()
        if container is None:
            return None
        ai_img = self._pick_ai()
        if ai_img is None:
            return None
        output, _ = QFileDialog.getSaveFileName(self, "保存 AI 处理后的双层 PNG", "AI_" + container.stem + ".png", "PNG (*.png)")
        if not output:
            return None
        out = Path(output)
        if out.resolve() == container.resolve():
            QMessageBox.warning(self, "不能覆盖源文件", "请选择与原双层 PNG 不同的输出文件名")
            return None
        return container, ai_img, out

    def toggle_ai_roi(self):
        """Edit a distinct permission mask without modifying the encrypted protection mask."""
        if not self._need_doc():
            return
        if not self.roi_active:
            if self.modified or self.container_path is None:
                QMessageBox.warning(self,"请先保存加密文件","保存双层 PNG 后才能另设 GPT 可编辑区域。")
                return
            assert self.canvas.mask is not None
            self.saved_conceal_mask = self.canvas.mask.copy()
            self.canvas.mask = (self.ai_roi_mask.copy() if self.ai_roi_mask is not None
                                else Image.new("L",self.canvas.mask.size,0))
            self.canvas.undo_stack.clear()
            self.canvas.redo_stack.clear()
            self.roi_active = True
            self.canvas.set_preview(False)
            self.toggle_preview.setChecked(False)
            self.canvas.set_selection_tint((40, 226, 169, 140))
            self.roi_button.setText("3 · 保存绿色 GPT 区域并返回遮挡选区")
            self.status.showMessage("绿色=允许 GPT 修改的独立选区；其余所有区域保持原图，不影响红色加密遮挡区")
        else:
            self.ai_roi_mask = self.canvas.mask.copy()
            self.canvas.mask = self.saved_conceal_mask
            self.saved_conceal_mask = None
            self.canvas.undo_stack.clear()
            self.canvas.redo_stack.clear()
            self.roi_active = False
            self.canvas.set_selection_tint((245, 68, 88, 135))
            self.roi_button.setText("3 · 编辑 GPT 可写入区域（绿色）")
            self.status.showMessage("GPT 可编辑区域已保存，红色为原始加密遮挡选区")
        self.canvas._refresh_overlay()
        # Switching the editor target does not modify the encrypted mask.
        self._loading = True
        try:
            self.canvas.changed.emit()
        finally:
            self._loading = False

    def ai_smart_edit(self, mode: str):
        if self.roi_active:
            QMessageBox.warning(self,"先退出编辑模式","请先保存绿色 GPT 区域。")
            return
        if self.ai_roi_mask is None or not self.ai_roi_mask.getbbox():
            QMessageBox.warning(self,"缺少绿色选区","请先点击「编辑 GPT 可写入区域」，用矩形、涂抹或套索明确指定修改范围，再返回。")
            return
        paths = self._ai_inputs()
        if paths is None:
            return
        src, ai, dst = paths
        pw = self._get_password()
        if pw is None:
            return
        try:
            from .smart_edit import smart_edit
            extraction = "color" if self.extraction_combo.currentIndex()==0 else "difference"
            result = smart_edit(src.read_bytes(), ai.read_bytes(), pw, self.ai_roi_mask,
                     mode=mode, extraction=extraction, alignment="auto")
            assert unseal_bytes(result.container_png,pw).mask.size == self.ai_roi_mask.size
            dst.write_bytes(result.container_png)
            restored = unseal_bytes(result.container_png, pw)
            # A1 returns original file bytes, A2 returns merged editable plaintext.
            restored_path = dst.with_name(dst.stem + ("_原始解密" if mode=="A1" else "_AI合成解密") +
                                          Path(restored.filename).suffix)
            if restored_path.resolve() == src.resolve() or restored_path.resolve() == dst.resolve():
                raise ValueError("解密输出路径不能覆盖加密原件")
            restored_path.write_bytes(restored.original_bytes)
            # Save a mask/report alongside result. Exports do not contain encrypted source.
            dst.with_name(dst.stem+"_GPT修改像素蒙版.png").write_bytes(result.delta_mask_png)
            dst.with_name(dst.stem+"_GPT验收.json").write_text(__import__('json').dumps(result.report,ensure_ascii=False,indent=2), encoding='utf-8')
            QMessageBox.information(self,"GPT 精确回封装完成",
               f"{mode}：已写入 {result.report['changed_pixels']:,} 像素（整图 {result.report['changed_percent_of_whole']}%）。\n"
               f"遮挡区和非绿色区域写入量均为 0；原始文件：{dst}\n"
               f"同时已输出真正去除遮盖的解密图：{restored_path}\n"
               "已保存逐像素蒙版与验证报告，请检查边缘与文字是否符合预期。")
        except Exception as e:
            self._error("GPT 智能回封装",e)

    def ai_repack(self):
        paths = self._ai_inputs()
        if paths is None:
            return
        src, ai, dst = paths
        pw = self._get_password()
        if pw is None:
            return
        try:
            container = src.read_bytes()
            original = unseal_bytes(container, pw).original_bytes
            result = repack_preview(container, ai.read_bytes(), password=pw)
            if unseal_bytes(result, pw).original_bytes != original:
                raise RuntimeError("回封装校验失败")
            dst.write_bytes(result)
            QMessageBox.information(self, "安全回封装完成（A1）",
                "原始密文保持不变；遮挡区继续沿用原有遮盖像素。\n解密后仍然是最初的原图。")
        except Exception as e:
            self._error("AI 表层回封装", e)

    def ai_merge(self):
        paths = self._ai_inputs()
        if paths is None:
            return
        src, ai, dst = paths
        pw = self._get_password()
        if pw is None:
            return
        try:
            result = merge_ai_preview(src.read_bytes(), ai.read_bytes(), pw, self._style(), self.block_spin.value(), solid_color=self.solid_color)
            dst.write_bytes(result)
            asset = unseal_bytes(result, pw)
            QMessageBox.information(self, "合成并重新加密（A2）", f"AI 修改已合成到未选中的区域，原选区内的像素保持不变。\n新加密文件已验证可解密：\n{dst}\n新原图：{asset.filename}")
        except Exception as e:
            self._error("AI 局部合成", e)


def main():
    # CI-only offscreen construction smoke test. No dialogs, files or network.
    smoke = "--smoke-test" in sys.argv
    argv = [arg for arg in sys.argv if arg != "--smoke-test"]
    app = QApplication(argv)
    app.setApplicationName("VeilPNG")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    if smoke:
        QTimer.singleShot(150, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
