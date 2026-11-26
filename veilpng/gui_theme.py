"""VeilPNG independent blue-and-white studio theme inspired by Folirina's workflow aesthetics.

No source code from Folirina is copied. The color system is intentionally familiar;
layout and styles are maintained independently for this project.
"""

STYLESHEET = """
QMainWindow, QWidget#workspaceRoot { background: #F5F7FB; }
QWidget { color: #263448; font-size: 13px; }
QWidget#sidebar { background: #F8FAFD; }
QLabel#title { font-size: 28px; font-weight: 800; color: #1D4ED8; }
QLabel#muted { color: #64748B; font-size: 12px; }
QFrame#workspaceHeader {
    background: #FFFFFF; border: 1px solid #DFE6F1; border-radius: 12px;
}
QLabel#workspaceTitle { color:#1E293B; font-weight: 800; font-size: 16px; }
QLabel#workspaceInfo { color:#64748B; font-size: 11px; }
QGroupBox {
    border: 1px solid #E2E8F0; border-radius: 10px;
    margin-top: 12px; padding-top: 13px; font-weight: 700; background: #FFFFFF;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 11px; top: 0px; padding: 0 5px;
    color: #3B526D; background: #FFFFFF;
}
QPushButton {
    min-height: 27px; border: 1px solid #CCD7E5;
    border-radius: 8px; background: #FFFFFF;
    padding: 4px 8px; font-weight: 600; color: #334155;
}
QPushButton:hover { background: #F0F5FD; border-color:#99B5DC; }
QPushButton:pressed { background: #E5EDFA; }
QPushButton:checked {
    background: #E7F0FF; border-color: #6199DD;
    color: #1D4ED8; font-weight: 750;
}
QPushButton#primary {
    background:#2563EB; border-color:#2563EB; color:#FFFFFF; font-weight:750;
    min-height: 32px;
}
QPushButton#primary:hover { background:#1D4ED8; }
QPushButton#modeNav { min-height:24px; padding:4px 5px; }
QPushButton#modeNav:checked { background:#2563EB; color:white; border-color:#2563EB; }
QPushButton#toolbarBtn { min-height:24px; font-size:11px; padding:3px 10px; }
QPushButton:disabled { background:#F3F5F9; color:#94A3B8; border-color:#E2E8F0; }
QComboBox, QSpinBox, QLineEdit {
    border:1px solid #CBD5E1; border-radius: 6px;
    padding:4px 6px; background: #FFFFFF; color:#334155;
    min-height: 23px;
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus { border-color:#60A5FA; }
QScrollArea { border:none; background:#F8FAFD; }
QSlider::groove:horizontal { height:5px; border-radius:2px; background:#D7E4F2; }
QSlider::handle:horizontal { width:14px; margin:-5px 0; border-radius:7px; background:#2563EB; }
QTabWidget#sideTabs::pane { background:#F7F9FD; border:1px solid #DCE5F1; border-radius: 10px; }
QTabWidget#sideTabs QTabBar::tab {
    background:#EDF2FA; border:1px solid #DCE5F1; border-bottom:none;
    min-width:80px; padding:8px 6px; border-top-left-radius:8px; border-top-right-radius:8px;
    color:#54708E; font-weight:700;
}
QTabWidget#sideTabs QTabBar::tab:selected { background:white; color:#1D4ED8; }
QWidget#comparePanel { background:#FFFFFF; border:1px solid #DCE5F1; border-radius:9px; }
QLabel#previewCaption { font-size:12px; color:#2563EB; font-weight:700; }
QLabel#modeLabel { background:#F0F4FB; border-radius:6px; color:#4B6584; padding:5px 7px; font-weight:700; }
QLabel#zoomLabel { min-width:43px; color:#375A82; font-weight:700; }
QGraphicsView#compareView { border:1px solid #E3EAF3; background:#E9EFF7; }
QStatusBar { color:#64748B; background:#FFFFFF; border-top:1px solid #E2E8F0; }
QGraphicsView#imageCanvas { border:1px solid #DEE5EF; border-radius: 8px; }
"""
