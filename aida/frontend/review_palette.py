"""Use AIDA's existing dark colors for native review dialog surfaces."""
from PySide6.QtGui import QColor, QPalette


def apply_review_palette(widget) -> None:
    # The application stylesheet supplies light text, while native Fusion
    # dialogs can otherwise retain a white Window/Base palette. Keep the main
    # window stylesheet intact and make these review surfaces readable.
    palette = widget.palette()
    for role, color in {
        QPalette.ColorRole.Window: "#05090f",
        QPalette.ColorRole.Base: "#06101a",
        QPalette.ColorRole.AlternateBase: "#0b212f",
        QPalette.ColorRole.Button: "#102536",
        QPalette.ColorRole.WindowText: "#eaf6ff",
        QPalette.ColorRole.Text: "#eaf6ff",
        QPalette.ColorRole.ButtonText: "#eaf6ff",
        QPalette.ColorRole.Highlight: "#1b5977",
        QPalette.ColorRole.HighlightedText: "#eaf6ff",
    }.items():
        palette.setColor(role, QColor(color))
    widget.setPalette(palette)
    widget.setStyleSheet("""
        QWidget { background-color: #05090f; color: #eaf6ff; }
        QTextEdit, QListWidget, QLineEdit, QComboBox {
            background-color: #06101a; border: 1px solid #1c3445;
            selection-background-color: #1b5977; selection-color: #eaf6ff;
        }
        QTabWidget::pane { border: 1px solid #1c3445; background-color: #06101a; }
        QTabBar::tab { background-color: #102536; border: 1px solid #1c3445; padding: 5px 8px; }
        QTabBar::tab:selected { background-color: #1b5977; }
        QPushButton { background-color: #102536; border: 1px solid #1c3445; border-radius: 5px; padding: 5px 8px; }
        QPushButton:hover { background-color: #1b5977; }
        QPushButton:disabled { color: #637586; background-color: #06101a; }
    """)
