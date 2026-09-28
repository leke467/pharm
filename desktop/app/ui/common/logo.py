from PySide6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen, QPolygonF, QIcon
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout


def create_logo_pixmap(size: int = 48, on_dark: bool = False) -> QPixmap:
    """
    Renders the Apex-nexus geometric 3D isometric prism logo at any given size.
    Colors match the authoritative SVG specification:
      - Top face: #1A82FC (Electric Blue)
      - Left face: #5BC0BE (Teal/Cyan)
      - Right face: #0B132B (Deep Navy)
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    scale = size / 32.0

    def pt(x: float, y: float) -> QPointF:
        return QPointF(x * scale, y * scale)

    # Face 1: Top facet (#1A82FC)
    top_poly = QPolygonF([pt(16, 2), pt(2, 9), pt(16, 16), pt(30, 9)])
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#1A82FC")))
    painter.drawPolygon(top_poly)

    # Face 2: Left facet (#5BC0BE)
    left_poly = QPolygonF([pt(2, 9), pt(2, 23), pt(16, 30), pt(16, 16)])
    painter.setBrush(QBrush(QColor("#5BC0BE")))
    painter.drawPolygon(left_poly)

    # Face 3: Right facet (#0B132B)
    right_poly = QPolygonF([pt(30, 9), pt(30, 23), pt(16, 30), pt(16, 16)])
    if on_dark:
        # Subtle contrast elevation on dark themes so the deep navy facet remains clear
        painter.setBrush(QBrush(QColor("#1B2A4A")))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
    else:
        painter.setBrush(QBrush(QColor("#0B132B")))
        painter.setPen(Qt.NoPen)
    painter.drawPolygon(right_poly)

    painter.end()
    return pixmap


def create_logo_icon(size: int = 32) -> QIcon:
    """Returns a QIcon containing the geometric prism logo for window titlebars and taskbars."""
    return QIcon(create_logo_pixmap(size))


class LogoWidget(QLabel):
    """Convenience QLabel widget displaying the logo at a fixed size."""

    def __init__(self, size: int = 36, on_dark: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setPixmap(create_logo_pixmap(size, on_dark=on_dark))
        self.setStyleSheet("background: transparent;")
