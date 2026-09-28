from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QCursor, QPainter, QLinearGradient, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from desktop.app.ui.common.logo import create_logo_pixmap


class CustomTitleBar(QFrame):
    """
    Ultra-sleek modern custom window title bar for PharmaCare Pro.
    Replaces the default OS title bar with a polished, executive branded header
    featuring QPainter-guaranteed dark gradient rendering, smooth window controls
    (minimize, maximize/restore, close), and drag support.
    """

    def __init__(
        self,
        parent_window,
        title_text: str = "PharmaCare Pro",
        subtitle_text: str = "Enterprise Edition",
    ):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._drag_pos = None
        self.setObjectName("CustomTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.init_ui(title_text, subtitle_text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Rich executive dark navy-slate gradient (100% immune to QSS overrides)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor("#0B132B"))
        grad.setColorAt(0.5, QColor("#111D4A"))
        grad.setColorAt(1.0, QColor("#0F172A"))
        painter.fillRect(0, 0, w, h, grad)

        # Subtle bottom accent line (emerald to slate)
        line_grad = QLinearGradient(0, h - 1, w, h - 1)
        line_grad.setColorAt(0.0, QColor("#10B981"))
        line_grad.setColorAt(0.35, QColor("#059669"))
        line_grad.setColorAt(1.0, QColor("#1E293B"))
        painter.fillRect(0, h - 2, w, 2, line_grad)
        painter.end()

    def init_ui(self, title_text: str, subtitle_text: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(10)

        # 1. 3D Isometric Brand Icon
        icon_label = QLabel()
        icon_label.setPixmap(create_logo_pixmap(size=22, on_dark=True))
        icon_label.setFixedSize(22, 22)
        icon_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_label)

        # 2. Branded App Title & Tag
        title_box = QHBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(8)

        self.app_name_lbl = QLabel(title_text)
        self.app_name_lbl.setObjectName("TitleBarAppName")
        self.app_name_lbl.setStyleSheet(
            "color: #FFFFFF; font-size: 13px; font-weight: 800; letter-spacing: -0.2px; background: transparent; border: none;"
        )
        title_box.addWidget(self.app_name_lbl)

        if subtitle_text:
            dot = QLabel("•")
            dot.setObjectName("TitleBarDot")
            dot.setStyleSheet(
                "color: #10B981; font-size: 12px; font-weight: 900; background: transparent; border: none;"
            )
            title_box.addWidget(dot)

            self.tag_lbl = QLabel(subtitle_text)
            self.tag_lbl.setObjectName("TitleBarTag")
            self.tag_lbl.setStyleSheet(
                "color: #CBD5E1; font-size: 11px; font-weight: 600; background: transparent; border: none;"
            )
            title_box.addWidget(self.tag_lbl)

        layout.addLayout(title_box)
        layout.addStretch()

        # 3. Window Controls (Minimize, Maximize / Restore, Close)
        btn_box = QHBoxLayout()
        btn_box.setContentsMargins(0, 0, 0, 0)
        btn_box.setSpacing(0)

        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("TitleBarMinBtn")
        self.min_btn.setFixedSize(46, 40)
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.clicked.connect(self.parent_window.showMinimized)
        btn_box.addWidget(self.min_btn)

        self.max_btn = QPushButton("□")
        self.max_btn.setObjectName("TitleBarMaxBtn")
        self.max_btn.setFixedSize(46, 40)
        self.max_btn.setToolTip("Maximize / Restore")
        self.max_btn.setCursor(Qt.PointingHandCursor)
        self.max_btn.clicked.connect(self._toggle_max_restore)
        btn_box.addWidget(self.max_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleBarCloseBtn")
        self.close_btn.setFixedSize(48, 40)
        self.close_btn.setToolTip("Close")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.parent_window.close)
        btn_box.addWidget(self.close_btn)

        layout.addLayout(btn_box)

        self.setStyleSheet("""
            #TitleBarMinBtn, #TitleBarMaxBtn {
                background-color: transparent;
                color: #CBD5E1;
                border: none;
                border-radius: 0px;
                font-size: 13px;
                font-weight: 700;
                padding: 0px;
            }
            #TitleBarMinBtn:hover, #TitleBarMaxBtn:hover {
                background-color: rgba(255, 255, 255, 0.12);
                color: #FFFFFF;
            }
            #TitleBarCloseBtn {
                background-color: transparent;
                color: #CBD5E1;
                border: none;
                border-radius: 0px;
                font-size: 13px;
                font-weight: 700;
                padding: 0px;
            }
            #TitleBarCloseBtn:hover {
                background-color: #EF4444;
                color: #FFFFFF;
            }
            #TitleBarCloseBtn:pressed {
                background-color: #DC2626;
            }
        """)

    def _toggle_max_restore(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.max_btn.setText("□")
        else:
            self.parent_window.showMaximized()
            self.max_btn.setText("❐")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
                self.max_btn.setText("□")
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_max_restore()
            event.accept()


class DialogHeaderBanner(QFrame):
    """
    Executive frameless header banner for modal dialogs (popups).
    Automatically removes the native OS title bar from parent_dialog, enables
    smooth drag-to-move, and renders a dark gradient header with 3D logo & close button.
    """

    def __init__(self, title: str, subtitle: str = "", parent_dialog=None, icon_text: str = "", **kwargs):
        super().__init__(parent_dialog)
        self.parent_dialog = parent_dialog
        self.icon_text = icon_text
        self._drag_pos = None
        self.setObjectName("DialogHeaderBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(66 if subtitle else 52)

        if self.parent_dialog is not None:
            self.parent_dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
            self.parent_dialog.setObjectName("FramelessModalDialog")

        self.init_ui(title, subtitle)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Rich executive dark navy-slate gradient
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor("#0B132B"))
        grad.setColorAt(0.55, QColor("#111D4A"))
        grad.setColorAt(1.0, QColor("#0F172A"))
        painter.fillRect(0, 0, w, h, grad)

        # Bottom emerald accent line
        line_grad = QLinearGradient(0, h - 2, w, h - 2)
        line_grad.setColorAt(0.0, QColor("#10B981"))
        line_grad.setColorAt(0.5, QColor("#059669"))
        line_grad.setColorAt(1.0, QColor("#1E293B"))
        painter.fillRect(0, h - 2, w, 2, line_grad)
        painter.end()

    def init_ui(self, title: str, subtitle: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 14, 10)
        layout.setSpacing(12)

        # 3D Logo Icon
        icon_label = QLabel()
        icon_label.setPixmap(create_logo_pixmap(size=26, on_dark=True))
        icon_label.setFixedSize(26, 26)
        icon_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_label)

        # Text Column
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("DialogBannerTitle")
        self.title_lbl.setStyleSheet(
            "color: #FFFFFF; font-size: 15px; font-weight: 800; letter-spacing: -0.2px; background: transparent; border: none;"
        )
        text_col.addWidget(self.title_lbl)

        if subtitle:
            self.sub_lbl = QLabel(subtitle)
            self.sub_lbl.setObjectName("DialogBannerSub")
            self.sub_lbl.setStyleSheet(
                "color: #CBD5E1; font-size: 11.5px; font-weight: 500; background: transparent; border: none;"
            )
            text_col.addWidget(self.sub_lbl)

        layout.addLayout(text_col)
        layout.addStretch()

        if self.parent_dialog:
            close_btn = QPushButton("✕")
            close_btn.setObjectName("DialogBannerCloseBtn")
            close_btn.setFixedSize(30, 30)
            close_btn.setToolTip("Close Dialog")
            close_btn.setCursor(Qt.PointingHandCursor)
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.12);
                    color: #FFFFFF;
                    border: none;
                    border-radius: 15px;
                    font-size: 12px;
                    font-weight: 800;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #EF4444;
                    color: #FFFFFF;
                }
            """)
            close_btn.clicked.connect(self.parent_dialog.reject)
            layout.addWidget(close_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.parent_dialog is not None:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_dialog.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None and self.parent_dialog is not None:
            self.parent_dialog.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
