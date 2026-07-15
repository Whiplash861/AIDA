from __future__ import annotations

from PySide6.QtWidgets import QApplication


AIDA_STYLESHEET = """
/* =========================================================
   AIDA — PRECISION GLASS THEME
   ========================================================= */

QMainWindow {
    background-color: #05090f;
}

QWidget {
    color: #eaf6ff;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10pt;
}

QWidget#appRoot {
    background:
        qradialgradient(
            cx: 0.12,
            cy: 0.06,
            radius: 1.15,
            fx: 0.12,
            fy: 0.06,
            stop: 0 rgba(27, 89, 119, 185),
            stop: 0.28 rgba(11, 33, 49, 240),
            stop: 0.68 rgba(6, 16, 26, 250),
            stop: 1 rgba(4, 9, 15, 255)
        );
}


/* =========================================================
   APPLICATION HEADER
   ========================================================= */

QFrame#appHeader {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(27, 52, 70, 238),
            stop: 0.38 rgba(14, 31, 45, 232),
            stop: 1 rgba(8, 19, 30, 242)
        );

    border: 1px solid rgba(112, 210, 255, 82);
    border-radius: 18px;
}

QLabel#appTitle {
    color: #f5fbff;
    font-family: "Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI";
    font-size: 23pt;
    font-weight: 600;
    letter-spacing: 5px;
}

QLabel#appSubtitle {
    color: #64d8ff;
    font-family: "Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI";
    font-size: 8pt;
    font-weight: 500;
    letter-spacing: 3px;
}

QLabel#statusLabel {
    color: #afc2d1;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(51, 69, 82, 205),
            stop: 1 rgba(24, 35, 45, 220)
        );

    border: 1px solid rgba(147, 194, 221, 70);
    border-radius: 15px;

    padding: 7px 16px;

    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}


/* =========================================================
   STATUS TONES
   ========================================================= */

QLabel#statusLabel[tone="ready"],
QLabel#statusValue[tone="ready"] {
    color: #59f0b3;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(24, 83, 66, 210),
            stop: 1 rgba(9, 42, 34, 225)
        );

    border-color: rgba(77, 236, 171, 105);
}

QLabel#statusLabel[tone="active"],
QLabel#statusValue[tone="active"] {
    color: #68d8ff;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(22, 75, 105, 220),
            stop: 1 rgba(8, 39, 59, 230)
        );

    border-color: rgba(88, 207, 255, 120);
}

QLabel#statusLabel[tone="warning"],
QLabel#statusValue[tone="warning"] {
    color: #ffd875;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(103, 77, 24, 210),
            stop: 1 rgba(48, 36, 12, 230)
        );

    border-color: rgba(255, 205, 91, 120);
}

QLabel#statusLabel[tone="error"],
QLabel#statusValue[tone="error"] {
    color: #ff7d8d;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(104, 38, 49, 215),
            stop: 1 rgba(49, 18, 25, 230)
        );

    border-color: rgba(255, 105, 126, 125);
}

QLabel#statusLabel[tone="idle"],
QLabel#statusValue[tone="idle"] {
    color: #a9bbc8;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(53, 68, 79, 190),
            stop: 1 rgba(25, 35, 43, 215)
        );

    border-color: rgba(136, 166, 187, 65);
}

QLabel#statusLabel,
QLabel#statusValue,
QLabel#composerHint {
    font-family: "Cascadia Mono", "Consolas";
}


/* =========================================================
   WORKSPACE
   ========================================================= */

QFrame#workspace {
    background-color: transparent;
    border: none;
}

QSplitter#workspaceSplitter {
    background-color: transparent;
}

QSplitter#workspaceSplitter::handle {
    background-color: transparent;
    margin: 6px 2px;
}

QSplitter#workspaceSplitter::handle:hover {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(85, 205, 255, 25),
            stop: 0.5 rgba(85, 205, 255, 150),
            stop: 1 rgba(85, 205, 255, 25)
        );

    border-radius: 3px;
}


/* =========================================================
   COMMAND COMPOSER
   ========================================================= */

QFrame#composer {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(22, 42, 58, 235),
            stop: 0.45 rgba(12, 27, 40, 232),
            stop: 1 rgba(7, 18, 28, 242)
        );

    border: 1px solid rgba(104, 204, 250, 78);
    border-radius: 18px;
}

QLabel#composerTitle {
    color: #66d9ff;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#composerHint {
    color: #768c9c;
    font-size: 7pt;
    font-weight: 650;
    letter-spacing: 1px;
}

QLineEdit#commandInput {
    color: #edf9ff;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(5, 17, 27, 225),
            stop: 1 rgba(10, 26, 38, 220)
        );

    border: 1px solid rgba(107, 181, 218, 82);
    border-radius: 12px;

    padding: 10px 14px;
    min-height: 20px;

    font-size: 10pt;

    selection-color: #ffffff;
    selection-background-color: rgba(61, 162, 214, 190);
}

QLineEdit#commandInput:hover {
    border-color: rgba(102, 211, 255, 125);
}

QLineEdit#commandInput:focus {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(7, 25, 38, 235),
            stop: 1 rgba(12, 37, 52, 225)
        );

    border: 1px solid rgba(102, 217, 255, 205);
}

QLineEdit#commandInput:disabled {
    color: #657684;
    background-color: rgba(11, 20, 29, 210);
    border-color: rgba(78, 100, 115, 55);
}

QPushButton#sendButton {
    color: #f4fbff;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 #1487c5,
            stop: 0.52 #116da7,
            stop: 1 #264d9c
        );

    border: 1px solid rgba(109, 218, 255, 180);
    border-radius: 12px;

    padding: 10px 24px;

    min-width: 82px;
    min-height: 20px;

    font-weight: 700;
}

QPushButton#sendButton:hover {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 #22a5e7,
            stop: 0.55 #1684c5,
            stop: 1 #4a5ec4
        );

    border-color: rgba(144, 231, 255, 235);
}

QPushButton#sendButton:pressed {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 #0c5f8f,
            stop: 1 #293f82
        );

    border-color: rgba(76, 178, 224, 170);
}

QPushButton#sendButton:disabled {
    color: #657684;
    background-color: rgba(30, 43, 54, 190);
    border-color: rgba(88, 109, 122, 55);
}

/* =========================================================
   ANIMATED MESSAGE FEED
   ========================================================= */

QScrollArea#messageFeed {
    background-color: transparent;
    border: 1px solid rgba(105, 196, 239, 68);
    border-radius: 18px;
}

QWidget#messageFeedViewport {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(9, 25, 37, 238),
            stop: 0.55 rgba(6, 18, 28, 245),
            stop: 1 rgba(5, 14, 23, 250)
        );

    border-radius: 17px;
}

QWidget#messageFeedContent {
    background-color: transparent;
}

QFrame#messageCard {
    border-radius: 14px;
}

QFrame#messageCard[sender="aida"] {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(14, 49, 59, 230),
            stop: 1 rgba(8, 30, 39, 238)
        );

    border: 1px solid rgba(92, 218, 232, 92);
}

QFrame#messageCard[sender="user"] {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(46, 31, 72, 230),
            stop: 1 rgba(27, 22, 51, 238)
        );

    border: 1px solid rgba(177, 118, 244, 92);
}

QFrame#messageCard[sender="system"] {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(18, 42, 61, 230),
            stop: 1 rgba(10, 28, 43, 238)
        );

    border: 1px solid rgba(85, 176, 224, 82);
}

QLabel#messageSender {
    font-family:
        "Bahnschrift SemiCondensed",
        "Bahnschrift",
        "Segoe UI";

    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 1px;
}

QFrame#messageCard[sender="aida"]
QLabel#messageSender {
    color: #65e6ef;
}

QFrame#messageCard[sender="user"]
QLabel#messageSender {
    color: #c58aff;
}

QFrame#messageCard[sender="system"]
QLabel#messageSender {
    color: #62cfff;
}

QLabel#messageTimestamp {
    color: #748b9b;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 7pt;
}

QLabel#messageBody {
    color: #ebf7ff;
    font-family:
        "Segoe UI Variable Text",
        "Segoe UI";

    font-size: 10pt;
    line-height: 1.2;
}

/* =========================================================
   STATUS DASHBOARD
   ========================================================= */

QFrame#statusDashboard {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 1,
            stop: 0 rgba(23, 43, 59, 235),
            stop: 0.42 rgba(12, 28, 41, 235),
            stop: 1 rgba(7, 18, 28, 243)
        );

    border: 1px solid rgba(105, 202, 247, 74);
    border-radius: 18px;
}

QLabel#dashboardTitle,
QLabel#composerTitle {
    font-family: "Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI";
    font-weight: 600;
    letter-spacing: 2px;
}

QLabel#statusName {
    color: #8da3b3;
    font-size: 8pt;
    font-weight: 650;
}

QLabel#statusValue {
    color: #afc0cc;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(52, 69, 81, 190),
            stop: 1 rgba(23, 34, 43, 220)
        );

    border: 1px solid rgba(129, 164, 186, 60);
    border-radius: 9px;

    padding: 3px 7px;

    font-size: 8pt;
    font-weight: 700;
}

QListWidget#activityList {
    color: #b9cbd7;

    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1,
            stop: 0 rgba(5, 17, 27, 220),
            stop: 1 rgba(8, 22, 33, 225)
        );

    border: 1px solid rgba(99, 167, 202, 55);
    border-radius: 12px;

    padding: 5px;

    outline: none;
    font-size: 8pt;
}

QListWidget#activityList::item {
    padding: 7px 5px;
    border-bottom: 1px solid rgba(90, 145, 173, 38);
}

QListWidget#activityList::item:hover {
    color: #d9f4ff;
    background-color: rgba(53, 128, 162, 42);
    border-radius: 6px;
}

QListWidget#activityList::item:selected {
    color: #d9f4ff;
    background-color: rgba(53, 128, 162, 58);
}


/* =========================================================
   SCROLLBARS
   ========================================================= */

QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 5px 2px;
}

QScrollBar::handle:vertical {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 0,
            stop: 0 rgba(55, 107, 132, 150),
            stop: 1 rgba(77, 143, 173, 180)
        );

    border-radius: 4px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background:
        qlineargradient(
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 0,
            stop: 0 rgba(78, 161, 197, 190),
            stop: 1 rgba(103, 204, 238, 215)
        );
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}


/* =========================================================
   TOOLTIP
   ========================================================= */

QToolTip {
    color: #eaf7ff;
    background-color: rgba(10, 24, 35, 245);
    border: 1px solid rgba(101, 207, 255, 110);
    border-radius: 8px;
    padding: 6px 9px;
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