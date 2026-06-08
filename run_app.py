import sys
from src.main import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

def _apply_dark_theme(app: QApplication):
    app.setStyle('Fusion')
    pal = QPalette()
    # 기본 배경/전경
    pal.setColor(QPalette.ColorRole.Window,          QColor(30, 30, 30))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Base,            QColor(22, 22, 22))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(40, 40, 40))
    pal.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.BrightText,      QColor(255, 255, 255))
    # 버튼
    pal.setColor(QPalette.ColorRole.Button,          QColor(50, 50, 50))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
    # 선택 / 강조
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(41, 121, 255))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    # 툴팁
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(50, 50, 50))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(220, 220, 220))
    # 비활성화 상태
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(100, 100, 100))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(100, 100, 100))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(100, 100, 100))
    app.setPalette(pal)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    _apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
