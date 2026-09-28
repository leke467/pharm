from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt

class StatusBadge(QLabel):
    def __init__(self, text="", color="gray"):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.set_status(text, color)

    def set_status(self, text, color):
        self.setText(text)
        colors = {
            "green": "#4CAF50",
            "red": "#F44336",
            "yellow": "#FFC107",
            "gray": "#9E9E9E"
        }
        hex_color = colors.get(color, colors["gray"])
        self.setStyleSheet(f"background-color: {hex_color}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;")

