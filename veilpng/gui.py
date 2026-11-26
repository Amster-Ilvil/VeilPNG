"""Cross-platform VeilPNG PySide6 desktop UI."""
from __future__ import annotations

import os
import sys
import tempfile
import csv
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QGroupBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QStatusBar, QVBoxLayout, QWidget, QLineEdit, QTabWidget, QSizePolicy,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QListWidget, QListWidgetItem, QStackedWidget,
)

from .canvas import MaskCanvas, _pixmap
from .pair_canvas import MangaPairCanvas
from .phantom_widget import PhantomTankWorkspace
from .translation_widget import TranslationWorkbench
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
        from . import __version__
        self.setWindowTitle(f"VeilPNG {__version__} · 漫画翻译移植与幻影坦克工作站")
        self.resize(1360, 880)
        self.setMinimumSize(900, 620)
        self.original_bytes: bytes | None = None
        self.filename: str = ""
        self.source_path: Path | None = None
        self.container_path: Path | None = None
        self.modified = False
        self.roi_active = False
        self.ai_roi_mask: Image.Image | None = None
        self.saved_conceal_mask: Image.Image | None = None
        self.manga_pair_state: dict[tuple, dict] = {}
        self._loaded_pair_key = None
        self.phantom_result = None
        self.phantom_saved_path: Path | None = None
        self.solid_color = DEFAULT_SOLID_COLOR
        self._loading = False
        self._compare_pending = False
        self._compare_timer = QTimer(self)
        self._compare_timer.setSingleShot(True)
        self._compare_timer.timeout.connect(self._update_compare)
        self.canvas = MaskCanvas()
        self.canvas.changed.connect(self._mask_changed)
        self.canvas.zoom_changed.connect(self._zoom_changed)
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
        b.setMinimumWidth(0)
        b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        b.setToolTip(text)
        return b

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(330)
        # The splitter, rather than a hard width cap, controls the sidebar.
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(9, 9, 9, 8)
        left.setSpacing(6)

        title = QLabel("VeilPNG")
        title.setObjectName("title")
        subtitle = QLabel("局部防窥 · 加密复原 · AI 安全编辑")
        subtitle.setObjectName("muted")
        left.addWidget(title)
        left.addWidget(subtitle)
        self.single_actions = QWidget()
        action_grid = QGridLayout(self.single_actions)
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setSpacing(5)
        action_grid.addWidget(self._btn("打开原图 / 双层 PNG", self.open_image, primary=True), 0, 0, 1, 2)
        action_grid.addWidget(self._btn("保存双层 PNG", self.save_sealed), 1, 0)
        action_grid.addWidget(self._btn("解密恢复原图", self.restore_original), 1, 1)
        left.addWidget(self.single_actions)

        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sideTabs")
        # Keep the tab API for existing callbacks, but present a two-row mode selector.
        self.side_tabs.tabBar().hide()
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        nav = QGridLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        for i, name in enumerate(("遮挡", "AI 配准", "漫画项目", "幻影坦克", "中文移植")):
            button = self._btn(name, lambda checked=False, index=i: self.side_tabs.setCurrentIndex(index))
            button.setCheckable(True)
            button.setObjectName("modeNav")
            self.mode_buttons.addButton(button, i)
            if i < 3:
                nav.addWidget(button, 0, i * 2, 1, 2)
            else:
                nav.addWidget(button, 1, (i - 3) * 3, 1, 3)
        for column in range(6):
            nav.setColumnStretch(column, 1)
        self.mode_buttons.button(0).setChecked(True)
        left.addLayout(nav)
        edit_page = QWidget()
        edit_page.setObjectName("tabPane")
        tab_layout = QVBoxLayout(edit_page)
        tab_layout.setContentsMargins(7, 10, 7, 9)
        tab_layout.setSpacing(10)
        ai_page = QWidget()
        ai_page.setObjectName("tabPane")
        ai_page_layout = QVBoxLayout(ai_page)
        ai_page_layout.setContentsMargins(7, 10, 7, 9)
        ai_page_layout.setSpacing(10)
        manga_page = QWidget()
        manga_page.setObjectName('tabPane')
        manga_page_layout = QVBoxLayout(manga_page)
        manga_page_layout.setContentsMargins(7, 10, 7, 9)
        manga_page_layout.setSpacing(10)
        phantom_page = QWidget()
        phantom_page.setObjectName("tabPane")
        phantom_layout = QVBoxLayout(phantom_page)
        phantom_layout.setContentsMargins(7, 10, 7, 9)
        phantom_layout.setSpacing(10)

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
        edit_layout.addWidget(QLabel("多边形：单击加点，双击/Enter 完成；Esc 取消"))
        buttons = QHBoxLayout()
        buttons.addWidget(self._btn("撤销", self.canvas.undo))
        buttons.addWidget(self._btn("重做", self.canvas.redo))
        edit_layout.addLayout(buttons)
        buttons2 = QHBoxLayout()
        buttons2.addWidget(self._btn("反选", self.canvas.invert_mask))
        buttons2.addWidget(self._btn("清空", self.canvas.clear_mask))
        edit_layout.addLayout(buttons2)
        edit_layout.addWidget(self._btn("全图选中", self.canvas.select_all))
        self.finish_roi_btn = self._btn("保存绿色选区并返回", self.toggle_ai_roi, primary=True)
        self.finish_roi_btn.setVisible(False)
        edit_layout.addWidget(self.finish_roi_btn)
        tab_layout.addWidget(edit_group)

        preview_group = QGroupBox("表层遮挡设置")
        pv = QVBoxLayout(preview_group)
        self.style_combo = QComboBox()
        self.style_combo.addItems(STYLES)
        self.style_combo.currentTextChanged.connect(self._style_changed)
        pv.addWidget(self.style_combo)
        color_row = QHBoxLayout()
        self.color_entry = QLineEdit(self.solid_color)
        self.color_entry.setMaxLength(7)
        self.color_entry.setMinimumWidth(70)
        self.color_entry.setMaximumWidth(130)
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
        self.toggle_preview = QCheckBox("显示公开预览")
        self.toggle_preview.setToolTip("显示公开预览（隐藏红色蒙版）")
        self.toggle_preview.toggled.connect(self.canvas.set_preview)
        self.toggle_preview.toggled.connect(lambda _v: self._request_compare())
        pv.addWidget(self.toggle_preview)
        self.mask_stat = QLabel("加密面积：0%")
        pv.addWidget(self.mask_stat)
        pv.addWidget(QLabel("纯色不包含原像素；马赛克仍会暴露轮廓。"))
        tab_layout.addWidget(preview_group)
        tab_layout.addStretch()
        self._refresh_color_controls()

        ai_group = QGroupBox("AI 往返处理")
        ai = QVBoxLayout(ai_group)
        ai.addWidget(self._btn("1 · 导出 AI 公开预览", self.export_ai_preview))
        ai.addWidget(self._btn("2A · 回封装表层", self.ai_repack))
        ai.addWidget(self._btn("2B · 整页覆盖（高风险）", self.ai_merge))
        self.roi_button = self._btn("3 · 编辑绿色许可区", self.toggle_ai_roi)
        ai.addWidget(self.roi_button)
        self.extraction_combo = QComboBox()
        self.extraction_combo.addItems(["彩色标记提取（低误改）", "黑白文字笔画提取（实验性）", "像素差异提取（需复核）", "整块替换绿色区域（适合擦除旧文字）"])
        ai.addWidget(self.extraction_combo)
        ai.addWidget(QLabel("ROI 边缘保护：0=无，2–4px 可减少拼接边缘突变"))
        self.edge_guard_spin = QSpinBox()
        self.edge_guard_spin.setRange(0,24)
        self.edge_guard_spin.setValue(2)
        ai.addWidget(self.edge_guard_spin)
        ai.addWidget(self._btn("4A · A1 表层回封装", lambda:self.ai_smart_edit("A1")))
        ai.addWidget(self._btn("4B · A2 绿色区回写", lambda:self.ai_smart_edit("A2")))
        tip = QLabel("只上传上方导出的普通预览 PNG；不要上传带有密文的双层 PNG。\n2B 只合并未遮挡区域，选中区域保持原像素。")
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        ai.addWidget(tip)
        ai_page_layout.addWidget(ai_group)
        pair_group = QGroupBox("日中配对遮挡映射")
        pair_layout = QVBoxLayout(pair_group)
        pair_layout.addWidget(self._btn("映射选区至对应页面", self.transfer_to_pair))
        pair_tip = QLabel("读取 Folirina 的 pairs.csv 几何矩阵；不使用简单比例缩放。映射后请检查边界。")
        pair_tip.setWordWrap(True)
        pair_tip.setObjectName("muted")
        pair_layout.addWidget(pair_tip)
        ai_page_layout.addWidget(pair_group)

        manga_list_group = QGroupBox('已配准漫画页面 · 项目列表')
        manga_list_layout = QVBoxLayout(manga_list_group)
        self.manga_pairs_csv = QLineEdit()
        choose_csv = QHBoxLayout()
        choose_csv.addWidget(self.manga_pairs_csv, 1)
        choose_csv.addWidget(self._btn('浏览', self._choose_manga_pairs_csv))
        manga_list_layout.addWidget(self._btn('一键导入配准目录', self._choose_manga_bundle, primary=True))
        manga_list_layout.addWidget(QLabel('Folirina 配准清单'))
        manga_list_layout.addLayout(choose_csv)
        self.manga_source_root = QLineEdit()
        self.manga_target_root = QLineEdit()
        for caption, field, title in (('中文图片目录', self.manga_source_root, '选择中文图片目录'),
                                      ('日文图片目录', self.manga_target_root, '选择日文图片目录')):
            line = QHBoxLayout()
            manga_list_layout.addWidget(QLabel(caption))
            line.addWidget(field, 1)
            line.addWidget(self._btn('浏览', lambda checked=False, edit=field, label=title: self._choose_manga_root(edit, label)))
            manga_list_layout.addLayout(line)
        manga_list_layout.addWidget(self._btn('读取清单／刷新列表', self.manga_refresh_list, primary=True))
        self.manga_pair_search = QLineEdit()
        self.manga_pair_search.setPlaceholderText('筛选编号 / 中文或日文文件名')
        self.manga_pair_search.textChanged.connect(self._manga_filter_list)
        manga_list_layout.addWidget(self.manga_pair_search)
        self.manga_pair_list = QListWidget()
        self.manga_pair_list.setObjectName('mangaPairList')
        self.manga_pair_list.setWordWrap(True)
        self.manga_pair_list.setMinimumHeight(72)
        self.manga_pair_list.setMaximumHeight(200)
        self.manga_pair_list.currentItemChanged.connect(self._manga_select_item)
        manga_list_layout.addWidget(self.manga_pair_list)
        manga_list_layout.addWidget(self._btn('载入配对／双画布', self.manga_load_selected))
        self.manga_pair_status = QLabel('选择配准清单和图片目录后，可点击配对编号同时打开两张图。')
        self.manga_pair_status.setWordWrap(True)
        self.manga_pair_status.setObjectName('muted')
        manga_list_layout.addWidget(self.manga_pair_status)
        manga_page_layout.addWidget(manga_list_group)

        manga_group = QGroupBox("漫画模式（成组配准）")
        manga_layout = QVBoxLayout(manga_group)
        manga_layout.setSpacing(8)

        self.manga_project_dir = QLineEdit()
        self.manga_pair_id = QLineEdit()
        self.manga_source_path = QLineEdit()
        self.manga_target_path = QLineEdit()
        self.manga_source_ai_path = QLineEdit()
        self.manga_target_ai_path = QLineEdit()
        self.manga_mask_space = QComboBox(); self.manga_mask_space.addItems(["source（中文侧绘制）", "target（日文侧绘制）"])
        self.manga_mode_combo = QComboBox(); self.manga_mode_combo.addItems(["A2 · 只写回绿色区域", "A1 · 只改表层，原密文不变"])

        def _path_row(label_text, line_edit, button_text, callback):
            roww = QVBoxLayout()
            roww.setSpacing(3)
            roww.addWidget(QLabel(label_text))
            inputs = QHBoxLayout()
            inputs.addWidget(line_edit, 1)
            inputs.addWidget(self._btn(button_text, callback))
            roww.addLayout(inputs)
            return roww

        manga_layout.addLayout(_path_row("项目目录", self.manga_project_dir, "选择目录", self._choose_manga_project_dir))
        row_pair = QGridLayout()
        row_pair.addWidget(QLabel("pair_id"), 0, 0)
        row_pair.addWidget(self.manga_pair_id, 0, 1)
        row_pair.addWidget(QLabel("蒙版空间"), 1, 0)
        row_pair.addWidget(self.manga_mask_space, 1, 1)
        manga_layout.addLayout(row_pair)
        manga_layout.addLayout(_path_row("中文图/source", self.manga_source_path, "浏览", lambda: self._choose_manga_file(self.manga_source_path, "选择 source/中文图片")))
        manga_layout.addLayout(_path_row("日文图/target", self.manga_target_path, "浏览", lambda: self._choose_manga_file(self.manga_target_path, "选择 target/日文图片")))
        manga_layout.addWidget(self._btn("创建成组加密项目", self.manga_init_from_current, primary=True))
        manga_layout.addWidget(QLabel("AI 返回图可只填写一侧，也可两侧都填。若当前页面已保存绿色 ROI，则会同步映射到另一侧。"))
        manga_layout.addLayout(_path_row("中文 AI 返回图", self.manga_source_ai_path, "浏览", lambda: self._choose_manga_file(self.manga_source_ai_path, "选择中文 AI 返回图")))
        manga_layout.addLayout(_path_row("日文 AI 返回图", self.manga_target_ai_path, "浏览", lambda: self._choose_manga_file(self.manga_target_ai_path, "选择日文 AI 返回图")))
        row_mode = QVBoxLayout()
        row_mode.addWidget(QLabel("回写模式"))
        row_mode.addWidget(self.manga_mode_combo)
        manga_layout.addLayout(row_mode)
        self.manga_alignment_combo = QComboBox()
        self.manga_alignment_combo.addItems(['自动特征配准（推荐）', '只按尺寸缩放（风险较高）'])
        manga_layout.addWidget(self.manga_alignment_combo)
        manga_layout.addWidget(self._btn("解析 AI 返回图并解密", self.manga_resolve_project))
        self.manga_a3_strategy = QComboBox()
        self.manga_a3_strategy.addItems([
            'A3 · 严格差异提取（只复制确实不同的笔画）',
            'A3 · 明确绿色区域整体替换（会替换该区域日文文字）',
        ])
        manga_layout.addWidget(QLabel('日文底图优先：Gemini 的中文修改映射到日文高清图'))
        manga_layout.addWidget(self.manga_a3_strategy)
        self.manga_a3_feather = QSpinBox()
        self.manga_a3_feather.setRange(0,24)
        self.manga_a3_feather.setValue(6)
        fr = QHBoxLayout()
        fr.addWidget(QLabel('A3 补丁边缘融合(px)'))
        fr.addWidget(self.manga_a3_feather)
        manga_layout.addLayout(fr)
        manga_layout.addWidget(self._btn('A3 · 日文底图优先', self.manga_transfer_gemini_to_japanese, primary=True))
        manga_layout.addWidget(self._btn('A4 · AI 画面优先／恢复遮盖', self.manga_visible_gemini_to_japanese, primary=True))
        self.manga_info = QLabel("漫画模式：一组 source/target 图片共享同一配准工程。先在当前页画红色遮挡和可选绿色 ROI，再创建项目。")
        self.manga_info.setWordWrap(True)
        self.manga_info.setObjectName("muted")
        manga_layout.addWidget(self.manga_info)
        manga_page_layout.addWidget(manga_group)
        manga_page_layout.addStretch()
        ai_page_layout.addStretch()

        ph_files = QGroupBox("两张图片合成一个透明 PNG")
        phfv = QVBoxLayout(ph_files)
        self.phantom_surface_path = QLineEdit()
        self.phantom_surface_path.setPlaceholderText("白底展示的表图，推荐浅色图")
        self.phantom_hidden_path = QLineEdit()
        self.phantom_hidden_path.setPlaceholderText("黑底展示的里图，推荐深色图")
        for caption, entry in (("白底表图", self.phantom_surface_path), ("黑底里图", self.phantom_hidden_path)):
            phfv.addWidget(QLabel(caption))
            h = QHBoxLayout(); h.addWidget(entry, 1)
            h.addWidget(self._btn("选择", lambda checked=False, e=entry: self._choose_phantom_image(e)))
            phfv.addLayout(h)
        phantom_layout.addWidget(ph_files)

        ph_options = QGroupBox("Alpha 合成设置")
        phv = QVBoxLayout(ph_options)
        self.phantom_mode_combo = QComboBox()
        self.phantom_mode_combo.addItems(["灰度双图（准确度较高）", "彩色双图（近似拟合）"])
        phv.addWidget(self.phantom_mode_combo)
        self.phantom_fit_combo = QComboBox()
        self.phantom_fit_combo.addItems(["居中裁剪对齐", "完整保留并填充", "拉伸至表图尺寸"])
        phv.addWidget(self.phantom_fit_combo)
        self.phantom_white_base = QSpinBox()
        self.phantom_white_base.setRange(150,235)
        self.phantom_white_base.setValue(190)
        self.phantom_white_gain = QSpinBox()
        self.phantom_white_gain.setRange(5,40)
        self.phantom_white_gain.setValue(22)
        self.phantom_black_gain = QSpinBox()
        self.phantom_black_gain.setRange(5,45)
        self.phantom_black_gain.setValue(24)
        for caption, widget in (("白底亮度基准", self.phantom_white_base),
                                ("表图对比度（%）", self.phantom_white_gain),
                                ("里图对比度（%）", self.phantom_black_gain)):
            r=QHBoxLayout(); r.addWidget(QLabel(caption)); r.addStretch(); r.addWidget(widget); phv.addLayout(r)
        self.phantom_create_btn = self._btn("生成并双背景预览", self.phantom_create_from_gui, primary=True)
        phv.addWidget(self.phantom_create_btn)
        phv.addWidget(self._btn("保存透明幻影坦克 PNG", self.phantom_save_from_gui))
        phv.addWidget(self._btn("打开并解析透明 PNG", self.phantom_inspect_from_gui))
        phv.addWidget(self._btn("导出双背景预览与 HTML", self.phantom_export_previews_from_gui))
        phantom_layout.addWidget(ph_options)
        platform_group = QGroupBox("平台适配与回传验收")
        platform_layout = QVBoxLayout(platform_group)
        self.phantom_platform_combo = QComboBox()
        self.phantom_platform_combo.addItems(["QQ 聊天（实验性）", "微信聊天（实验性）", "小红书图文（建议备用对比图）"])
        platform_layout.addWidget(self.phantom_platform_combo)
        platform_layout.addWidget(self._btn("导出平台兼容包", self.phantom_export_platform_package))
        platform_layout.addWidget(self._btn("检查平台回传图 Alpha", self.phantom_audit_platform_return))
        platform_layout.addWidget(self._btn("导出回传差异热力图", self.phantom_export_platform_audit_evidence))
        self.phantom_platform_status = QLabel("不联网提交：上传前生成候选文件；上传后将实际下载的图片交给本机检验。油猴仅支持网页版，不能修改手机 App。")
        self.phantom_platform_status.setWordWrap(True)
        self.phantom_platform_status.setObjectName('muted')
        platform_layout.addWidget(self.phantom_platform_status)
        phantom_layout.addWidget(platform_group)
        caution = QLabel("注意：幻影坦克是视觉效果，不具备 AES 加密或隐私防护能力。只能通过支持透明通道的查看器切换背景显示；不要上传隐私明文。")
        caution.setObjectName("muted")
        caution.setWordWrap(True)
        phantom_layout.addWidget(caution)
        phantom_layout.addStretch()
        translation_page=QWidget()
        translation_layout=QVBoxLayout(translation_page)
        translation_tip=QLabel('新版中文翻译移植工作台：日文原图作为底图，Gemini 中文内容只写入蓝色许可区域。'
                               '橙色去字和红色原图保护区独立编辑；最终导出不带加密层的普通 PNG。')
        translation_tip.setWordWrap(True)
        translation_layout.addWidget(translation_tip)
        translation_layout.addWidget(self._btn('进入翻译移植工作台',lambda: self.workspace_stack.setCurrentIndex(3)))
        translation_layout.addStretch()
        for name, widget in (("遮挡", edit_page), ("AI 配准", ai_page),
                             ("漫画项目", manga_page), ("幻影坦克", phantom_page),
                             ("中文移植", translation_page)):
            inner = QScrollArea()
            inner.setWidgetResizable(True)
            inner.setFrameShape(QFrame.Shape.NoFrame)
            # Width-adaptive controls first; horizontal scrolling is a last-resort
            # accessibility fallback on unusual fonts / high-DPI configurations.
            self._compact_sidebar_page(widget)
            inner.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            inner.setWidget(widget)
            self.side_tabs.addTab(inner, name)
        left.addWidget(self.side_tabs, 1)

        splitter.addWidget(sidebar)
        workspace = QWidget()
        workspace.setMinimumWidth(300)
        workspace.setObjectName("workspaceRoot")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 10, 12, 9)
        workspace_layout.setSpacing(8)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        header_layout = QVBoxLayout(header)
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
        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        header_layout.addLayout(toolbar)
        self.workspace_info.setWordWrap(True)
        self.mode_label = QLabel("保护区 · 红色")
        self.mode_label.setObjectName("modeLabel")
        toolbar.addWidget(self.mode_label)
        self.compare_toggle = QCheckBox("并排对比")
        self.compare_toggle.setToolTip("同时查看原始画布与公开遮挡预览，方便检查边缘")
        self.compare_toggle.toggled.connect(self._toggle_compare)
        toolbar.addWidget(self.compare_toggle)
        fit_btn = self._btn("适应窗口", self.canvas.zoom_fit)
        fit_btn.setObjectName("toolbarBtn")
        actual_btn = self._btn("100%", self.canvas.zoom_one)
        actual_btn.setObjectName("toolbarBtn")
        toolbar.addWidget(fit_btn)
        toolbar.addWidget(actual_btn)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        toolbar.addWidget(self.zoom_label)
        workspace_layout.addWidget(header)
        self.canvas.setObjectName("imageCanvas")
        self.view_split = QSplitter(Qt.Orientation.Horizontal)
        self.view_split.setObjectName("viewSplit")
        self.view_split.addWidget(self.canvas)
        self.compare_panel = QWidget()
        self.compare_panel.setObjectName("comparePanel")
        compare_layout = QVBoxLayout(self.compare_panel)
        compare_layout.setContentsMargins(7, 7, 7, 7)
        compare_layout.setSpacing(5)
        compare_label = QLabel("公开预览 · 仅可见像素（不能解密）")
        compare_label.setObjectName("previewCaption")
        compare_label.setWordWrap(True)
        compare_layout.addWidget(compare_label)
        self.compare_view = QGraphicsView()
        self.compare_view.setObjectName("compareView")
        self.compare_view.setRenderHints(self.canvas.renderHints())
        self.compare_scene = QGraphicsScene(self.compare_view)
        self.compare_item = QGraphicsPixmapItem()
        self.compare_scene.addItem(self.compare_item)
        self.compare_view.setScene(self.compare_scene)
        compare_layout.addWidget(self.compare_view, 1)
        self.view_split.addWidget(self.compare_panel)
        self.view_split.setStretchFactor(0, 1)
        self.view_split.setStretchFactor(1, 1)
        self.compare_panel.hide()
        workspace_layout.addWidget(self.view_split, 1)
        footer = QLabel("红色：加密遮挡区 · 绿色：AI 编辑许可区 · B 画笔 / E 橡皮 / R 矩形 / L 套索 / P 多边形 / H 平移（画布聚焦时） · 滚轮缩放")
        footer.setObjectName("workspaceInfo")
        footer.setWordWrap(True)
        workspace_layout.addWidget(footer)
        self.manga_dual = MangaPairCanvas()
        self.manga_dual.setObjectName('mangaDualWorkspace')
        self.manga_dual.mask_changed.connect(self._manga_modified)
        self.manga_dual.side_changed.connect(self._manga_active_side_changed)
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(workspace)
        self.workspace_stack.addWidget(self.manga_dual)
        self.phantom_workspace = PhantomTankWorkspace()
        self.workspace_stack.addWidget(self.phantom_workspace)
        self.translation_workbench=TranslationWorkbench()
        self.workspace_stack.addWidget(self.translation_workbench)
        self.workspace_stack.setCurrentIndex(0)
        self.side_tabs.tabBar().hide()
        self.side_tabs.currentChanged.connect(self._on_side_tab_changed)
        splitter.addWidget(self.workspace_stack)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 970])
        self.main_splitter = splitter
        self.setCentralWidget(splitter)
        self.sidebar_toggle = QAction("显示侧栏", self)
        self.sidebar_toggle.setCheckable(True)
        self.sidebar_toggle.setChecked(True)
        self.sidebar_toggle.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.sidebar_toggle.toggled.connect(sidebar.setVisible)
        self.menuBar().addMenu("视图").addAction(self.sidebar_toggle)
        self.setStyleSheet(STYLESHEET)
        self._on_side_tab_changed(0)

    @staticmethod
    def _compact_sidebar_page(page):
        for label in page.findChildren(QLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
        for entry in page.findChildren(QLineEdit):
            entry.setMinimumWidth(0)
            entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setMinimumWidth(0)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            for index in range(combo.count()):
                combo.setItemData(index, combo.itemText(index), Qt.ItemDataRole.ToolTipRole)
        # A single short checkbox is enough; a long explanatory label belongs in a tooltip.
        for check in page.findChildren(QCheckBox):
            if not check.toolTip():
                check.setToolTip(check.text())
        for button in page.findChildren(QPushButton):
            # Preserve action text while giving the control a bounded size hint.
            button.setMinimumWidth(0)

    def _zoom_changed(self, factor: float):
        if hasattr(self, "zoom_label"):
            self.zoom_label.setText(f"{factor * 100:.0f}%")

    def _toggle_compare(self, on: bool):
        self.compare_panel.setVisible(on)
        if on:
            self.view_split.setSizes([600, 560])
            self.toggle_preview.setChecked(False)
            self.toggle_preview.setEnabled(False)
            self._update_compare()
        else:
            self.toggle_preview.setEnabled(True)
            self.canvas.zoom_fit()

    def _request_compare(self):
        if not getattr(self, "compare_toggle", None) or not self.compare_toggle.isChecked():
            return
        if self._compare_pending:
            return
        self._compare_pending = True
        self._compare_timer.start(110)

    def _update_compare(self):
        self._compare_pending = False
        if not getattr(self, "compare_toggle", None) or not self.compare_toggle.isChecked():
            return
        if self.canvas.original is None:
            return
        protection_mask = self.saved_conceal_mask if self.roi_active else self.canvas.mask
        if protection_mask is None:
            return
        public = render_preview(self.canvas.original, protection_mask,
                                self._style(), self.block_spin.value(), self.solid_color)
        self.compare_item.setPixmap(_pixmap(public))
        self.compare_scene.setSceneRect(0, 0, public.width, public.height)
        self.compare_view.fitInView(self.compare_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _shortcuts(self):
        for key, call in (("Ctrl+Z", self.canvas.undo), ("Ctrl+Shift+Z", self.canvas.redo),
                          ("Ctrl+O", self.open_image), ("Ctrl+S", self.save_sealed),
                          ("Ctrl+0", self.canvas.zoom_fit), ("Ctrl+1", self.canvas.zoom_one)):
            sh = QShortcut(QKeySequence(key), self)
            sh.activated.connect(call)
        # Single-letter shortcuts only work while the image canvas has focus;
        # entering hex colors, filenames or passwords stays unaffected.
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for key, tool in (("B", "brush"), ("E", "erase"), ("R", "rect"),
                          ("L", "lasso"), ("P", "polygon"), ("H", "pan")):
            sh = QShortcut(QKeySequence(key), self.canvas)
            sh.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sh.activated.connect(lambda t=tool: self._set_tool(t))

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
        self._request_compare()
        if hasattr(self, 'manga_dual'):
            self.manga_dual.set_style(self._style(), self.block_spin.value(), self.solid_color)
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
        self._request_compare()
        if self.canvas.mask is not None:
            n = self.canvas.mask.histogram()[255]
            total = self.canvas.mask.width * self.canvas.mask.height
            kind = "AI 许可区域" if self.roi_active else "加密遮盖面积"
            self.mask_stat.setText(f"{kind}：{n / total * 100:.2f}%（{n:,} / {total:,} 像素）")
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
            if hasattr(self, "mode_label"):
                self.mode_label.setText("保护区 · 红色")
                self.finish_roi_btn.hide()
            self.original_bytes = data
            self.filename = name
            self.source_path = None
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
        self._request_compare()
        self.setWindowTitle(f"VeilPNG · {name}")
        self.status.showMessage(f"已打开 {name}，尺寸 {original.width} × {original.height}")
        self._prefill_manga_fields_from_current()

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
                self.source_path = path
                self.status.showMessage("已成功认证解密双层 PNG；选择区域可继续修改，保存会重新加密")
            else:
                self._load_document(data, path.name, None, None)
                self.source_path = path
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
        if self.source_path and path.resolve() == self.source_path.resolve():
            QMessageBox.warning(self,'禁止覆盖原始输入','双层 PNG 必须另存，不能覆盖原始图像或已打开的加密原件。')
            return
        pw = self._get_password(confirm=True)
        if pw is None:
            return
        try:
            assert self.original_bytes is not None and self.canvas.mask is not None
            if not self.canvas.mask.getbbox():
                if QMessageBox.question(self, "没有遮挡区域", "当前未选择加密区域，公开预览将显示完整图片。是否仍继续？") != QMessageBox.StandardButton.Yes:
                    return
            sealed = seal_bytes(self.original_bytes, self.filename, self.canvas.mask, pw, self._style(), self.block_spin.value(), solid_color=self.solid_color)
            # Verify both encrypted payload and exact source file before reporting success.
            assert unseal_bytes(sealed, pw).original_bytes == self.original_bytes
            from .cli import _atomic_write
            _atomic_write(path,sealed)
            self.container_path = path
            self.modified = False
            QMessageBox.information(self, "成功", f"双层 PNG 已保存并成功校验：\n{path}\n\n上传给 AI 前请使用“导出可上传的预览”。")
        except Exception as e:
            self._error("加密保存", e)

    def _on_side_tab_changed(self, index: int):
        if self.mode_buttons.button(index) is not None:
            self.mode_buttons.button(index).setChecked(True)
        self.single_actions.setVisible(index in (0, 1))
        if hasattr(self, 'workspace_stack'):
            self.workspace_stack.setCurrentIndex({2:1,3:2,4:3}.get(index,0))
        if index == 2 and hasattr(self, 'manga_dual'):
            QTimer.singleShot(0, self.manga_dual.zoom_fit_both)

    def _choose_phantom_image(self, entry: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "选择幻影坦克素材", "", "图片 (*.png *.webp *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if path:
            entry.setText(path)

    def phantom_create_from_gui(self):
        try:
            from .phantom_tank import PhantomOptions, create_phantom
            surface_path = Path(self.phantom_surface_path.text().strip())
            hidden_path = Path(self.phantom_hidden_path.text().strip())
            if not surface_path.is_file() or not hidden_path.is_file():
                raise ValueError("请先选择真实存在的表图与里图")
            self.phantom_result = None
            self.phantom_saved_path = None
            options = PhantomOptions(mode=("grayscale", "color")[self.phantom_mode_combo.currentIndex()],
                                     fit=("cover", "contain", "stretch")[self.phantom_fit_combo.currentIndex()],
                                     white_base=self.phantom_white_base.value(),
                                     white_gain=self.phantom_white_gain.value()/100,
                                     black_gain=self.phantom_black_gain.value()/100)
            with Image.open(surface_path) as surface, Image.open(hidden_path) as hidden:
                self.phantom_result = create_phantom(surface, hidden, options)
            self.phantom_workspace.set_result(self.phantom_result)
            self.status.showMessage("幻影坦克已生成；请在两种背景下检查，保存时只能选择透明 PNG。")
        except Exception as exc:
            self._error("幻影坦克生成", exc)

    def phantom_save_from_gui(self):
        if self.phantom_result is None:
            QMessageBox.warning(self, "尚无合成结果", "请先生成幻影坦克或打开已有透明 PNG")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存带 Alpha 的幻影坦克 PNG", "phantom_tank.png", "PNG (*.png)")
        if not path:
            return
        try:
            from .phantom_tank import to_png_bytes, inspect_phantom
            dst=Path(path)
            if dst.suffix.casefold() != ".png":
                raise ValueError("只能保存为 PNG")
            sources=[self.phantom_surface_path.text().strip(),self.phantom_hidden_path.text().strip()]
            if any(p and dst.resolve()==Path(p).resolve() for p in sources):
                raise ValueError("不允许覆盖导入的素材")
            dst.write_bytes(to_png_bytes(self.phantom_result.image))
            with Image.open(dst) as check:
                inspect_phantom(check)
            self.phantom_saved_path = dst
            QMessageBox.information(self, "幻影坦克保存成功", f"真实透明 PNG：{dst}\n切换白底、黑底才能查看效果；不是加密文件。")
        except Exception as exc:
            self._error("保存幻影坦克", exc)

    def phantom_inspect_from_gui(self):
        path, _ = QFileDialog.getOpenFileName(self,"打开已有幻影坦克", "", "PNG (*.png)")
        if not path:
            return
        try:
            from .phantom_tank import inspect_phantom
            with Image.open(path) as image:
                self.phantom_result = inspect_phantom(image)
            self.phantom_saved_path = Path(path)
            self.phantom_workspace.set_result(self.phantom_result)
        except Exception as exc:
            self._error("解析幻影坦克", exc)

    def phantom_export_previews_from_gui(self):
        if self.phantom_result is None or self.phantom_saved_path is None:
            QMessageBox.warning(self,"请先保存透明 PNG", "需要先保存幻影坦克 PNG 后才能导出配套预览。")
            return
        directory=QFileDialog.getExistingDirectory(self,"选择离线预览的导出目录")
        if not directory:
            return
        try:
            from .phantom_tank import write_preview_assets
            write_preview_assets(self.phantom_result, self.phantom_saved_path, directory)
            QMessageBox.information(self,"幻影坦克预览已导出", f"黑白/灰底 PNG、对比图、检查报告和 preview.html：\n{directory}")
        except Exception as exc:
            self._error("幻影坦克预览导出", exc)

    def phantom_export_platform_package(self):
        if self.phantom_result is None or self.phantom_saved_path is None:
            QMessageBox.warning(self, '请先保存幻影坦克', '先生成/打开并保存透明 PNG，再导出平台候选文件。')
            return
        path = QFileDialog.getExistingDirectory(self, '平台候选导出目录（建议新建单独文件夹）')
        if not path:
            return
        try:
            from .phantom_platform import prepare_platform_package
            platform = ('qq','wechat','xhs')[self.phantom_platform_combo.currentIndex()]
            report = prepare_platform_package(self.phantom_saved_path, path, platform)
            self.phantom_platform_status.setText(
                f"{report['profile']['label']} 候选已生成：{path}\n"
                f"{report['prepared_size'][0]}×{report['prepared_size'][1]}，Alpha: "
                f"{report['alpha_min']}–{report['alpha_max']}。"
                "此操作仅在本地导出，不能证明 App 会显示幻影效果。"
            )
            QMessageBox.information(self, '平台候选文件已导出',
                f"目录：{path}\n"
                '优先上传 upload_alpha.png；失败时用 fallback_side_by_side.jpg。'
                '上传后请把下载回的图片再交给“检查 Alpha”按钮。')
        except Exception as exc:
            self._error('平台候选导出',exc)

    def phantom_export_platform_audit_evidence(self):
        original, _ = QFileDialog.getOpenFileName(self, '选择上传前的 upload_alpha.png', '', 'PNG (*.png)')
        if not original:
            return
        returned, _ = QFileDialog.getOpenFileName(self, '选择平台返回图片', '', '图片 (*.png *.webp *.jpg *.jpeg *.bmp)')
        if not returned:
            return
        directory = QFileDialog.getExistingDirectory(self, '选择新的空文件夹，保存差异热力图和离线检查页')
        if not directory:
            return
        try:
            from .phantom_platform import write_platform_audit_evidence
            result = write_platform_audit_evidence(original, returned, directory)
            self.phantom_platform_status.setText(
                f"回传图片：{result['verdict']}；可视化证据：{directory}。\n"
                "白/黑底对比和 Alpha 热力图均为本地结果；不代表原生 App 已验收。"
            )
            QMessageBox.information(self, '平台回传图差异报告',
                f"诊断结果：{result['verdict']}\n报告目录：{directory}\n"
                "已生成白/黑底前后对比、Alpha 变化热力图与 Mac 浏览器离线检查器。")
        except Exception as exc:
            self._error('回传图片可视化验收',exc)

    def phantom_audit_platform_return(self):
        original, _=QFileDialog.getOpenFileName(self,'选择上传前的 upload_alpha.png', '', 'PNG (*.png)')
        if not original:
            return
        returned, _=QFileDialog.getOpenFileName(self,'选择平台下载/保存回来的图片', '', '图片 (*.png *.webp *.jpg *.jpeg *.bmp)')
        if not returned:
            return
        try:
            from .phantom_platform import audit_platform_return
            report=audit_platform_return(original,returned)
            self.phantom_platform_status.setText(
                f"回传诊断：{report['verdict']}\n"
                f"Alpha MAE={report['alpha_mae']}；白底误差={report['white_render_mae']}；"
                f"黑底误差={report['black_render_mae']}。此结果不验证客户端缩略图背景。"
            )
            QMessageBox.information(self,'平台回收图诊断',
                f"结果：{report['verdict']}\n{report['reason']}\n"
                '无法从被压平的文件中恢复丢失的透明图层。')
        except Exception as exc:
            self._error('平台回传诊断',exc)

    def _choose_manga_bundle(self):
        path = QFileDialog.getExistingDirectory(self, "选择解压后的配准项目目录")
        if path:
            try:
                self.import_manga_bundle(path)
            except Exception as exc:
                self._error("导入配准目录", exc)

    def import_manga_bundle(self, path):
        from .pair_import import discover_bundle
        manifest, source, target = discover_bundle(path)
        self.manga_pairs_csv.setText(str(manifest))
        self.manga_source_root.setText(str(source))
        self.manga_target_root.setText(str(target))
        self.manga_source_path.clear()
        self.manga_target_path.clear()
        self.manga_pair_id.clear()
        self.manga_pair_search.clear()
        if self.manga_refresh_list() and self.manga_pair_list.count() == 1:
            self.manga_pair_list.setCurrentRow(0)

    def _choose_manga_root(self, line_edit: QLineEdit, title: str):
        path = QFileDialog.getExistingDirectory(self, title)
        if path:
            line_edit.setText(path)
            if line_edit is self.manga_source_root:
                self.manga_source_path.clear()
            else:
                self.manga_target_path.clear()

    def manga_refresh_list(self):
        path = Path(self.manga_pairs_csv.text().strip())
        if not path.is_file():
            QMessageBox.warning(self, '缺少配准清单', '请先选择存在的配准 CSV。')
            return False
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            ids = set()
            items = []
            for row in rows:
                pid = row.get('pair_id', '').strip()
                if not pid or pid in ids:
                    raise ValueError('配对编号存在空值或重复，请先检查 pairs.csv')
                ids.add(pid)
                items.append((pid, Path(row.get('source_image', '')).name,
                              Path(row.get('target_image', '')).name))
            self.manga_pair_list.blockSignals(True)
            try:
                self.manga_pair_list.clear()
                for pid, cn, jp in items:
                    item = QListWidgetItem(f'{pid}   {cn}  ↔  {jp}')
                    item.setData(Qt.ItemDataRole.UserRole, pid)
                    self.manga_pair_list.addItem(item)
            finally:
                self.manga_pair_list.blockSignals(False)
            self._manga_filter_list(self.manga_pair_search.text())
            self.manga_pair_status.setText(f'已载入 {len(items)} 组配对。点击编号自动显示双画布；所有隐私图片只从本地读取。')
            return True
        except Exception as exc:
            self._error('读取漫画配准清单', exc)
            return False

    def _manga_filter_list(self, query: str):
        keyword = query.strip().casefold()
        visible = 0
        for i in range(self.manga_pair_list.count()):
            item = self.manga_pair_list.item(i)
            hidden = bool(keyword) and keyword not in item.text().casefold()
            item.setHidden(hidden)
            if not hidden:
                visible += 1
        # Compact the list when a filter leaves only a few entries; expose the
        # actual manga project actions below instead of leaving empty space.
        self.manga_pair_list.setFixedHeight(min(170, max(72, 22 + visible * 24)))

    def _manga_select_item(self, current, previous):
        if current is not None:
            self.manga_pair_id.setText(str(current.data(Qt.ItemDataRole.UserRole)))
            self.manga_load_selected()

    def _manga_image_path(self, side: str, expected: str) -> Path:
        field = self.manga_source_path if side == 'source' else self.manga_target_path
        manual = Path(field.text().strip()) if field.text().strip() else None
        root_field = self.manga_source_root if side == 'source' else self.manga_target_root
        root_text = root_field.text().strip()
        if not root_text:
            if manual is not None and manual.name.casefold() == Path(expected).name.casefold() and manual.is_file():
                return manual
            raise FileNotFoundError('请先填写中文/日文图片目录，或分别浏览选择两张图片')
        root = Path(root_text).resolve()
        # Never follow paths from a CSV outside the user-selected image directory.
        name = Path(str(expected).replace('\\', '/')).name
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError('配准文件中的路径越过了所选图片目录')
        if not candidate.is_file():
            raise FileNotFoundError(f'找不到已配对图片：{candidate}')
        return candidate

    def manga_load_selected(self):
        pair_id = self.manga_pair_id.text().strip()
        if not pair_id:
            QMessageBox.warning(self, '请选择配对', '先从列表选择 pair_id。')
            return
        try:
            from .mask_transfer import load_pair
            pair = load_pair(self.manga_pairs_csv.text().strip(), pair_id)
            src = self._manga_image_path('source', pair.source_image)
            tgt = self._manga_image_path('target', pair.target_image)
            from .imaging import load_image
            src_img, tgt_img = load_image(src.read_bytes()), load_image(tgt.read_bytes())
            old = self.manga_dual.pair
            if old is not None and self._loaded_pair_key is not None:
                self.manga_pair_state[self._loaded_pair_key] = self.manga_dual.export_state()
            key = (str(Path(self.manga_pairs_csv.text()).resolve()), pair_id, str(src.resolve()), str(tgt.resolve()), pair.matrix_source_to_target)
            self.manga_dual.set_pair(pair, src_img, tgt_img, state=self.manga_pair_state.get(key))
            self._loaded_pair_key = key
            self.manga_dual.set_style(self._style(), self.block_spin.value(), self.solid_color)
            self.manga_source_path.setText(str(src))
            self.manga_target_path.setText(str(tgt))
            self.manga_pair_status.setText(f'配对 {pair_id} 已载入：中文 {src_img.width}×{src_img.height} · 日文 {tgt_img.width}×{tgt_img.height}。')
            self.side_tabs.setCurrentIndex(2)
            QTimer.singleShot(0, self.manga_dual.zoom_fit_both)
        except Exception as exc:
            self._error('载入日中双画布', exc)

    def _manga_modified(self, side: str, mode: str):
        self.manga_pair_status.setText(f'当前配对 {self.manga_dual.pair.pair_id} · 最新编辑 {side} / {mode}；另一侧已按配准矩阵同步。')

    def _manga_active_side_changed(self, side: str):
        self.manga_mask_space.setCurrentIndex(0 if side == 'source' else 1)

    def _choose_manga_project_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择漫画模式项目目录")
        if path:
            self.manga_project_dir.setText(path)

    def _choose_manga_pairs_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Folirina pairs.csv", "", "CSV (*.csv)")
        if path:
            self.manga_pairs_csv.setText(path)

    def _choose_manga_file(self, line_edit: QLineEdit, title: str):
        path, _ = QFileDialog.getOpenFileName(self, title, "", "图像 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            line_edit.setText(path)

    def _manga_mask_space_value(self) -> str:
        return 'source' if self.manga_mask_space.currentIndex() == 0 else 'target'

    def _manga_current_paths(self):
        project_dir = self.manga_project_dir.text().strip()
        pairs_csv = self.manga_pairs_csv.text().strip()
        pair_id = self.manga_pair_id.text().strip()
        source_path = self.manga_source_path.text().strip()
        target_path = self.manga_target_path.text().strip()
        if not all([project_dir, pairs_csv, pair_id, source_path, target_path]):
            raise ValueError("请先填写项目目录、pairs.csv、pair_id、source 图片和 target 图片")
        return Path(project_dir), Path(pairs_csv), pair_id, Path(source_path), Path(target_path)

    def _prefill_manga_fields_from_current(self):
        if not self.filename:
            return
        try:
            current = Path(self.filename).name
            if current.casefold().startswith('cn') and not self.manga_source_path.text().strip():
                self.manga_source_path.setText(self.filename)
            elif current.casefold().startswith('jp') and not self.manga_target_path.text().strip():
                self.manga_target_path.setText(self.filename)
        except Exception:
            pass

    def _manga_create_from_dual(self):
        from .manga_mode import create_manga_project
        try:
            project_dir, pairs_csv, pair_id, source_path, target_path = self._manga_current_paths()
            if self.manga_dual.pair is None or self.manga_dual.pair.pair_id != pair_id:
                raise ValueError('当前双画布尚未载入指定 pair_id')
            side = self.manga_dual.last_side
            conceal = self.manga_dual.mask_for(side, 'conceal')
            roi = self.manga_dual.mask_for(side, 'roi')
            if not conceal.getbbox():
                raise ValueError('红色加密遮挡区为空，请先在任意一侧绘制')
            if (project_dir / 'manga_project.json').exists():
                reply = QMessageBox.question(self, '项目已存在',
                    '该项目目录已经包含一个漫画工程。重新创建会覆盖该工程文件，继续吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return
            pw = self._get_password(confirm=True)
            if pw is None:
                return
            with tempfile.TemporaryDirectory(prefix='veilpng-manga-') as tmp:
                mask_path = Path(tmp) / 'mask.png'
                conceal.save(mask_path)
                roi_path = None
                if roi.getbbox():
                    roi_path = Path(tmp) / 'roi.png'
                    roi.save(roi_path)
                manifest = create_manga_project(
                    output_dir=project_dir, pairs_csv=pairs_csv, pair_id=pair_id,
                    source_image=source_path, target_image=target_path,
                    mask=mask_path, mask_space=side, password=pw,
                    roi_mask=roi_path, style=self._style(),
                    block=self.block_spin.value(), solid_color=self.solid_color)
            self.manga_info.setText(
                f'已创建配对 {pair_id}：CN {manifest["coverage"]["source"]["covered_pixels"]:,} 像素；'
                f'JP {manifest["coverage"]["target"]["covered_pixels"]:,} 像素。')
            self.manga_pair_status.setText(f'已将配对 {pair_id} 同时加密；公开预览位于 {project_dir / "public_previews"}')
            QMessageBox.information(self, '漫画双图项目完成',
                f'已同时输出中文与日文双层 PNG、两张可上传 AI 的公开预览，以及配准蒙版。\n{project_dir}')
        except Exception as exc:
            self._error('双图漫画项目创建', exc)

    def manga_init_from_current(self):
        if self.side_tabs.currentIndex() == 2 and self.manga_dual.loaded:
            return self._manga_create_from_dual()
        if self.roi_active:
            QMessageBox.warning(self, "请先退出绿色选区模式", "请先保存绿色 GPT 选区，再创建漫画模式项目。")
            return
        if not self._need_doc():
            return
        if self.canvas.mask is None or not self.canvas.mask.getbbox():
            QMessageBox.warning(self, "缺少红色遮挡选区", "请先在当前页面画出需要加密遮挡的红色区域。")
            return
        try:
            from .manga_mode import create_manga_project
            project_dir, pairs_csv, pair_id, source_path, target_path = self._manga_current_paths()
            current_name = Path(self.filename).name.casefold()
            source_name = source_path.name.casefold()
            target_name = target_path.name.casefold()
            if current_name == source_name:
                mask_space = 'source'
            elif current_name == target_name:
                mask_space = 'target'
            else:
                mask_space = self._manga_mask_space_value()
            pw = self._get_password(confirm=True)
            if pw is None:
                return
            project_dir.mkdir(parents=True, exist_ok=True)
            tmpdir = Path(tempfile.mkdtemp(prefix='veilpng-manga-', dir=project_dir))
            mask_path = tmpdir / f'{Path(self.filename).stem}_conceal_mask.png'
            self.canvas.mask.save(mask_path)
            roi_path = None
            if self.ai_roi_mask is not None and self.ai_roi_mask.getbbox():
                roi_path = tmpdir / f'{Path(self.filename).stem}_roi_mask.png'
                self.ai_roi_mask.save(roi_path)
            manifest = create_manga_project(output_dir=project_dir, pairs_csv=pairs_csv, pair_id=pair_id,
                                           source_image=source_path, target_image=target_path,
                                           mask=mask_path, mask_space=mask_space, password=pw,
                                           roi_mask=roi_path, style=self._style(),
                                           block=self.block_spin.value(), solid_color=self.solid_color)
            self.manga_info.setText(
                f"已创建漫画模式项目：{project_dir}\n"
                f"source 遮挡 {manifest['coverage']['source']['covered_pixels']:,} 像素；"
                f"target 遮挡 {manifest['coverage']['target']['covered_pixels']:,} 像素。"
            )
            QMessageBox.information(self, "漫画模式项目已创建",
                                    f"pair_id={pair_id}\n项目目录：{project_dir}\n"
                                    "已生成 source/target 双层 PNG、公开预览和配准后的蒙版。")
        except Exception as exc:
            self._error("漫画模式项目创建", exc)

    def manga_resolve_project(self):
        try:
            from .manga_mode import resolve_manga_project
            project_dir = self.manga_project_dir.text().strip()
            if not project_dir:
                raise ValueError("请先选择漫画模式项目目录")
            source_ai = self.manga_source_ai_path.text().strip() or None
            target_ai = self.manga_target_ai_path.text().strip() or None
            if not source_ai and not target_ai:
                raise ValueError("请至少提供一侧的 AI 返回图")
            pw = self._get_password()
            if pw is None:
                return
            mode = 'A2' if self.manga_mode_combo.currentIndex() == 0 else 'A1'
            extraction = ('color', 'monochrome', 'difference', 'patch')[self.extraction_combo.currentIndex()]
            alignment = 'auto' if self.manga_alignment_combo.currentIndex() == 0 else 'resize'
            if alignment == 'resize':
                decision = QMessageBox.question(self, '按尺寸缩放存在风险',
                    '不进行特征配准可能导致局部错位。仅建议几何一致的图片使用。确认继续吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if decision != QMessageBox.StandardButton.Yes:
                    return
            summary = resolve_manga_project(project_dir=project_dir, password=pw,
                                            source_ai_preview=source_ai, target_ai_preview=target_ai,
                                            mode=mode, extraction=extraction, alignment=alignment,
                                            edge_guard_px=self.edge_guard_spin.value(),
                                            style=self._style(), block=self.block_spin.value(),
                                            solid_color=self.solid_color)
            self.manga_info.setText(
                f"漫画模式已解析完成：{project_dir}\n"
                f"source：{summary['results']['source']['status']} · "
                f"target：{summary['results']['target']['status']}"
            )
            QMessageBox.information(self, "漫画模式解析完成",
                                    f"结果目录：{Path(project_dir) / 'resolved_outputs'}\n"
                                    "已生成新的双层 PNG、公开预览，以及真正解密后的无遮挡结果。")
        except Exception as exc:
            self._error("漫画模式解析", exc)

    def manga_transfer_gemini_to_japanese(self):
        """A3: use JP as the base, replacing ONLY approved mapped Gemini regions."""
        from .cross_pair_edit import transfer_and_save
        project_dir = self.manga_project_dir.text().strip()
        source_ai = self.manga_source_ai_path.text().strip()
        if not project_dir:
            QMessageBox.warning(self, '缺少漫画项目', '请先选择已生成的日中漫画项目目录。')
            return
        if not source_ai:
            QMessageBox.warning(self, '缺少 Gemini 图片', '请在「中文 AI 返回图」中选择 Gemini 的 PNG。')
            return
        full_roi = self.manga_a3_strategy.currentIndex() == 1
        if full_roi:
            confirmation = QMessageBox.question(
                self, '确认将 Gemini 文字区域替换到日文原图',
                '此模式以 JP 日文高清原图为底，仅将已授权绿色区域内的 Gemini/CN 像素复制过去。\n'
                '该区域原来的日文文字及部分底纹会被替换，其他 JP 像素不变。\n'
                '生成的日文高清结果需要逐页检查文字与接缝。是否继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmation != QMessageBox.StandardButton.Yes:
                return
        pw = self._get_password()
        if pw is None:
            return
        try:
            result = transfer_and_save(
                project_dir=project_dir, gemini_image_path=source_ai,
                password=pw, extraction='patch' if full_roi else 'monochrome',
                allow_entire_roi=full_roi, feather_px=self.manga_a3_feather.value(),
                edge_guard_px=self.edge_guard_spin.value(),
                alignment='auto' if self.manga_alignment_combo.currentIndex()==0 else 'resize',
            )
            out = Path(project_dir) / 'resolved_outputs' / 'A3_JP_base'
            self.manga_info.setText(f'A3 已完成：以日文版为底图，修改 {result["actual_japanese_image_changed_pixels"]:,} 像素；\n'
                                    f'遮挡区及绿色区外改动均为 0。结果：{out}')
            QMessageBox.information(self,'A3 日文高清原图回写完成',
                    f'日文高清结果已生成并经 AES 解密验收。\n'
                    f'真正去黑色遮盖的日文底图合成：{result["artifacts"]["decrypted_japanese_image"]}\n'
                    f'新双层 PNG：{result["artifacts"]["new_double_layer_png"]}\n'
                    f'请检查文字内容和拼接边缘。')
        except Exception as e:
            self._error('A3 · Gemini 修改映射到日文高清图', e)

    def manga_visible_gemini_to_japanese(self):
        """A4 deliberately transfers the entire visible Gemini image (not A3 ROI)."""
        from .cross_pair_edit import save_gemini_visible_result
        project_dir = self.manga_project_dir.text().strip()
        source_ai = self.manga_source_ai_path.text().strip()
        if not project_dir or not source_ai:
            QMessageBox.warning(self, '缺少项目或 Gemini 返回图',
                                '请先选择漫画项目，以及「中文 AI 返回图」。')
            return
        confirmation = QMessageBox.question(
            self, 'A4 · 确认移植完整 Gemini 可见画面',
            '此操作不同于 A3：会把 Gemini 返回图的全部可见区域（包括人物与网点重绘）映射到日文画布。\n'
            '日文原图仅用于恢复遮挡区域，其他区域的高清线稿不能保证保留。\n'
            '最终输出普通 PNG，不再生成双层加密图片。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        pw = self._get_password()
        if pw is None:
            return
        try:
            report = save_gemini_visible_result(
                project_dir=project_dir, gemini_image_path=source_ai,
                password=pw,
                alignment='auto' if self.manga_alignment_combo.currentIndex() == 0 else 'matrix',
            )
            self.manga_info.setText('A4 已完成：Gemini 全部可见内容已移植；'
                                    f'遮盖恢复像素 {report["restored_exact_japanese_pixels"]:,}；'
                                    f'最终普通 PNG：{report["final_image"]}')
            QMessageBox.information(self, 'A4 已输出最终普通 PNG',
                                    f'文件：{report["final_image"]}\n'
                                    'A4 不会重新加密，也不会生成双层文件。')
        except Exception as e:
            self._error('A4 · Gemini 完整可见图移植', e)

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
            self.source_path = Path(other)
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
            output_path=Path(p)
            if output_path.suffix.lower()!='.png':
                raise ValueError('AI 公开预览必须使用 PNG')
            forbidden = [self.container_path, self.source_path]
            if any(v and output_path.resolve()==v.resolve() for v in forbidden):
                raise ValueError('公开预览不能覆盖原始图像或加密双层容器')
            pw = self._get_password()
            if pw is None:
                return
            container_bytes = self.container_path.read_bytes()
            preview_bytes = preview_only(container_bytes)
            audit = audit_exported_preview(container_bytes, preview_bytes, pw)
            if not audit["mechanical_audit_pass"]:
                raise ValueError("预览机械隐私审计失败，已取消导出")
            from .cli import _atomic_write
            _atomic_write(output_path,preview_bytes)
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
        if out.resolve() in {container.resolve(),ai_img.resolve()}:
            QMessageBox.warning(self, "不能覆盖源文件", "请选择与原双层 PNG 及 AI 返回图均不同的输出文件名")
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
            self.mode_label.setText("AI 许可区 · 绿色")
            self.finish_roi_btn.show()
            self.side_tabs.setCurrentIndex(0)
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
            self.mode_label.setText("保护区 · 红色")
            self.finish_roi_btn.hide()
            self.side_tabs.setCurrentIndex(1)
            self.canvas.set_selection_tint((245, 68, 88, 135))
            self.roi_button.setText("3 · 编辑 GPT 可写入区域（绿色）")
            self.status.showMessage("GPT 可编辑区域已保存，红色为原始加密遮挡选区")
        self.canvas._refresh_overlay()
        self._request_compare()
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
            extraction = ("color", "monochrome", "difference", "patch")[self.extraction_combo.currentIndex()]
            result = smart_edit(src.read_bytes(), ai.read_bytes(), pw, self.ai_roi_mask,
                     mode=mode, extraction=extraction, alignment="auto",
                     edge_guard_px=self.edge_guard_spin.value())
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
        # Legacy whole-page merge can copy AI redraw artifacts into every
        # unprotected pixel. Require an explicit yes (not the default button).
        response = QMessageBox.question(
            self, "确认高风险整页覆盖",
            "此功能会把 AI 返回图的所有可见区域写入解密图，可能改变非目标文字、线稿和网点。\n"
            "建议改用下方绿色编辑区和智能 A2。仍然继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
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
    legacy = "--classic" in sys.argv
    argv = [arg for arg in sys.argv if arg not in ("--smoke-test", "--classic")]
    app = QApplication(argv)
    app.setApplicationName("VeilPNG")
    app.setStyle("Fusion")
    from .simple_gui import SimpleWindow
    window = MainWindow() if legacy else SimpleWindow()
    window.show()
    if smoke:
        QTimer.singleShot(150, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
