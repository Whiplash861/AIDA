from __future__ import annotations

from PySide6.QtWidgets import QApplication


AIDA_STYLESHEET = """
QMainWindow {
    background-color: #101317;
}

QWidget {
    color: #e8edf2;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QLabel#statusLabel {
    color: #76c7ff;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 4px 2px;
}

QTextBrowser {
    background-color: #171b20;
    border: 1px solid #2c343d;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: #285f82;
}

QLineEdit {
    background-color: #171b20;
    border: 1px solid #34404b;
    border-radius: 5px;
    padding: 8px 10px;
}

QLineEdit:focus {
    border: 1px solid #76c7ff;
}

QLineEdit:disabled {
    color: #6f7881;
    background-color: #14171b;
    border-color: #252b31;
}

QPushButton {
    background-color: #26313a;
    border: 1px solid #3a4854;
    border-radius: 5px;
    padding: 8px 18px;
    min-width: 72px;
}

QPushButton:hover {
    background-color: #303e49;
    border-color: #76c7ff;
}

QPushButton:pressed {
    background-color: #1d262d;
}

QPushButton:disabled {
    color: #69737c;
    background-color: #1a1f24;
    border-color: #292f35;
}

QScrollBar:vertical {
    background: #15191d;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #3b4650;
    border-radius: 5px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background: #52616d;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QFrame#statusDashboard {
    background-color: #151a20;
    border: 1px solid #2c343d;
    border-radius: 7px;
}

QLabel#dashboardTitle {
    color: #76c7ff;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#statusName {
    color: #8f9aa5;
    font-size: 8pt;
    font-weight: 600;
}

QLabel#statusValue {
    color: #dce6ee;
    font-size: 8pt;
    font-weight: 600;
}

QListWidget#activityList {
    background-color: #11161b;
    border: 1px solid #273039;
    border-radius: 5px;
    padding: 4px;
    outline: none;
    color: #aebbc6;
    font-size: 8pt;
}

QListWidget#activityList::item {
    padding: 4px 3px;
    border-bottom: 1px solid #202830;
}

QListWidget#activityList::item:selected {
    background-color: transparent;
    color: #aebbc6;
}
"""


def apply_theme(app: QApplication) -> None:
    """
    Applies AIDA's application-wide visual theme.
    """

    app.setStyle("Fusion")
    app.setStyleSheet(AIDA_STYLESHEET)