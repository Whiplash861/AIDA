from __future__ import annotations

from PySide6.QtWidgets import QApplication


AIDA_STYLESHEET = """
QMainWindow {
    background-color: #0b1016;
}

QWidget {
    color: #e6edf3;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QWidget#appRoot {
    background-color: #0b1016;
}

/* ---------------------------------------------------------
   APPLICATION HEADER
   --------------------------------------------------------- */

QFrame#appHeader {
    background-color: #111923;
    border: 1px solid #26384a;
    border-radius: 10px;
}

QLabel#appTitle {
    color: #f2f7fb;
    font-size: 20pt;
    font-weight: 700;
    letter-spacing: 3px;
}

QLabel#appSubtitle {
    color: #55c7ff;
    font-size: 8pt;
    font-weight: 600;
    letter-spacing: 1px;
}

QLabel#statusLabel {
    color: #a9b7c4;
    background-color: #1b2229;
    border: 1px solid #303b45;
    border-radius: 12px;
    padding: 6px 14px;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}

/* ---------------------------------------------------------
   STATUS TONES
   --------------------------------------------------------- */

QLabel#statusLabel[tone="ready"],
QLabel#statusValue[tone="ready"] {
    color: #54e0a4;
    background-color: #10271f;
    border-color: #245c48;
}

QLabel#statusLabel[tone="active"],
QLabel#statusValue[tone="active"] {
    color: #59caff;
    background-color: #102431;
    border-color: #27566c;
}

QLabel#statusLabel[tone="warning"],
QLabel#statusValue[tone="warning"] {
    color: #ffd166;
    background-color: #2c2412;
    border-color: #6b5420;
}

QLabel#statusLabel[tone="error"],
QLabel#statusValue[tone="error"] {
    color: #ff7474;
    background-color: #2b1719;
    border-color: #713139;
}

QLabel#statusLabel[tone="idle"],
QLabel#statusValue[tone="idle"] {
    color: #a9b7c4;
    background-color: #1b2229;
    border-color: #303b45;
}

/* ---------------------------------------------------------
   WORKSPACE
   --------------------------------------------------------- */

QFrame#workspace {
    background-color: transparent;
    border: none;
}

QTextBrowser#transcript {
    color: #e6edf3;
    background-color: #0b131c;
    border: 1px solid #26384a;
    border-radius: 10px;
    padding: 6px;
    font-size: 10pt;
    selection-background-color: #285f82;
}

QSplitter#workspaceSplitter {
    background-color: transparent;
}

QSplitter#workspaceSplitter::handle {
    background-color: transparent;
    margin: 0 2px;
}

QSplitter#workspaceSplitter::handle:hover {
    background-color: #2d5068;
    border-radius: 2px;
}

/* ---------------------------------------------------------
   COMMAND COMPOSER
   --------------------------------------------------------- */

QFrame#composer {
    background-color: #111923;
    border: 1px solid #26384a;
    border-radius: 10px;
}

QLabel#composerTitle {
    color: #55c7ff;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#composerHint {
    color: #687987;
    font-size: 7pt;
    font-weight: 600;
    letter-spacing: 1px;
}

QLineEdit#commandInput {
    background-color: #0d151e;
    border: 1px solid #34495c;
    border-radius: 7px;
    padding: 10px 12px;
    font-size: 10pt;
}

QLineEdit#commandInput:focus {
    border: 1px solid #55c7ff;
    background-color: #101b26;
}

QLineEdit#commandInput:disabled {
    color: #69747f;
    background-color: #11161c;
    border-color: #242f38;
}

QLineEdit#commandInput {
    min-height: 20px;
}

QPushButton#sendButton {
    color: #eef8ff;
    background-color: #125f96;
    border: 1px solid #318bc6;
    border-radius: 7px;
    padding: 10px 22px;
    min-width: 78px;
    font-weight: 600;
}

QPushButton#sendButton:hover {
    background-color: #1775b7;
    border-color: #59caff;
}

QPushButton#sendButton:pressed {
    background-color: #0e4c78;
}

QPushButton#sendButton:disabled {
    color: #687783;
    background-color: #1a242d;
    border-color: #2a3640;
}

QPushButton#sendButton {
    min-height: 20px;
}

/* ---------------------------------------------------------
   STATUS DASHBOARD
   --------------------------------------------------------- */

QFrame#statusDashboard {
    background-color: #111923;
    border: 1px solid #26384a;
    border-radius: 10px;
}

QLabel#dashboardTitle {
    color: #55c7ff;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#statusName {
    color: #8f9da9;
    font-size: 8pt;
    font-weight: 600;
}

QLabel#statusValue {
    color: #a9b7c4;
    background-color: #1b2229;
    border: 1px solid #303b45;
    border-radius: 7px;
    padding: 2px 6px;
    font-size: 8pt;
    font-weight: 700;
}

QListWidget#activityList {
    color: #b7c4ce;
    background-color: #0d151e;
    border: 1px solid #263541;
    border-radius: 7px;
    padding: 4px;
    outline: none;
    font-size: 8pt;
}

QListWidget#activityList::item {
    padding: 6px 4px;
    border-bottom: 1px solid #1e2b35;
}

QListWidget#activityList::item:selected {
    color: #b7c4ce;
    background-color: transparent;
}

/* ---------------------------------------------------------
   SCROLLBARS
   --------------------------------------------------------- */

QScrollBar:vertical {
    background: #0d141c;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #334655;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #476276;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""


def apply_theme(
    app: QApplication,
) -> None:
    """
    Applies AIDA's application-wide visual theme.
    """

    app.setStyle("Fusion")
    app.setStyleSheet(AIDA_STYLESHEET)