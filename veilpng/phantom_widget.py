"""Qt-only preview workspace for the non-encrypted phantom tank feature."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PySide6.QtGui import QPixmap

from .canvas import _pixmap


class PhantomTankWorkspace(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("phantomWorkspace")
        self.result = None
        self._source_pixmaps = []
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)
        header = QFrame()
        header.setObjectName("workspaceHeader")
        hv = QVBoxLayout(header)
        title = QLabel("幻影坦克 · 白底与黑底双视图")
        title.setObjectName("workspaceTitle")
        subtitle = QLabel("同一张透明 PNG 由背景变化显现不同内容；不含加密底层，不需要密码。")
        subtitle.setObjectName("workspaceInfo")
        subtitle.setWordWrap(True)
        hv.addWidget(title); hv.addWidget(subtitle)
        root.addWidget(header)
        previews = QHBoxLayout()
        previews.setSpacing(12)
        self.preview_labels = []
        for caption, background in [("白色背景 · 表图", "#ffffff"),
                                    ("黑色背景 · 里图", "#000000")]:
            panel = QFrame()
            panel.setFrameShape(QFrame.Shape.StyledPanel)
            panel.setStyleSheet(f"QFrame{{background-color:{background};border-radius:10px}}")
            layout = QVBoxLayout(panel)
            title = QLabel(caption)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-weight:600;color:" + ("#26364e" if background=="#ffffff" else "#ffffff"))
            layout.addWidget(title)
            view = QLabel("请在左侧导入两张图片后生成。")
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            view.setStyleSheet("border:0;color:" + ("#52606d" if background=="#ffffff" else "#ffffff"))
            view.setMinimumSize(100,120)
            view.setWordWrap(True)
            layout.addWidget(view, 1)
            self.preview_labels.append(view)
            previews.addWidget(panel, 1)
        root.addLayout(previews, 1)
        self.info_label = QLabel("输出为标准 RGBA PNG；截图、JPG 转换或压平会丢失背景切换效果。")
        self.info_label.setObjectName("workspaceInfo")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

    def set_result(self, result):
        self.result = result
        self._source_pixmaps = [_pixmap(result.white_preview), _pixmap(result.black_preview)]
        self.info_label.setText(
            f"尺寸 {result.image.width} × {result.image.height} · "
            f"Alpha {result.report.get('alpha_min', '-')}/{result.report.get('alpha_max', '-')} · "
            f"白黑底平均差异 {result.report.get('mean_white_black_difference', 0):.1f}"
        )
        self.update_previews()

    def update_previews(self):
        if self.result is None:
            return
        for view, pixmap in zip(self.preview_labels, self._source_pixmaps):
            size = view.size()
            if size.width() < 20 or size.height() < 20:
                continue
            pixmap = pixmap.scaled(size.width()-8,size.height()-8,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            view.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_previews()
