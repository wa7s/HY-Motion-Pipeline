"""Blender-style dark theme for HY Motion Studio.

Colours follow Blender 4's default theme: a near-black frame between areas,
#303030 editor regions, slightly lighter collapsible panels, dark input
fields, lighter operator buttons and the #4772b3 selection blue.
"""

FRAME   = "#161616"    # gaps between areas, menus
TOPBAR  = "#232323"
AREA    = "#303030"    # editor / region background
PANEL   = "#3a3a3a"    # collapsible panel body
PANELH  = "#3f3f3f"    # panel header
FIELD   = "#282828"    # text / number / dropdown fields
FIELDH  = "#2f2f2f"
BUTTON  = "#545454"    # operator buttons
BUTTONH = "#646464"
OUTLINE = "#1f1f1f"
TEXT    = "#e6e6e6"
LABEL   = "#bdbdbd"
MUTED   = "#8f8f8f"
ACCENT  = "#4772b3"    # Blender selection blue
ACCENTH = "#5680c2"
GOOD    = "#6cc644"
BAD     = "#e0555f"
WARN    = "#e0a040"

STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 9pt; }}
QMainWindow {{ background: {FRAME}; }}
QWidget {{ color: {TEXT}; }}
QWidget#area, QWidget#region {{ background: {AREA}; }}
QScrollArea, QScrollArea > QWidget > QWidget#region {{ background: {AREA}; border: none; }}

/* ---- top bar: menus + workspace tabs ---- */
QWidget#topbar {{ background: {TOPBAR}; border-bottom: 1px solid {FRAME}; }}
QMenuBar {{ background: transparent; color: {TEXT}; padding: 2px 4px; }}
QMenuBar::item {{ background: transparent; padding: 4px 9px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {BUTTON}; }}
QMenu {{ background: {FRAME}; border: 1px solid #2a2a2a; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 16px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #fff; }}
QMenu::separator {{ height: 1px; background: #2e2e2e; margin: 4px 6px; }}
QLabel#appname {{ color: {LABEL}; font-weight: 600; padding: 0 6px 0 10px; }}

QTabBar#workspaces {{ background: transparent; }}
QTabBar#workspaces::tab {{
    background: transparent; color: {MUTED};
    padding: 6px 16px; margin: 3px 1px 0 1px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
}}
QTabBar#workspaces::tab:selected {{ background: {AREA}; color: {TEXT}; }}
QTabBar#workspaces::tab:hover:!selected {{ color: {TEXT}; background: #2b2b2b; }}

/* ---- area headers (viewport header, timeline, info) ---- */
QWidget#header {{ background: {AREA}; border-bottom: 1px solid {FRAME}; }}
QWidget#timeline {{ background: {AREA}; border-top: 1px solid {FRAME}; }}
QLabel#areatitle {{ color: {LABEL}; font-weight: 600; }}

/* ---- collapsible panels ---- */
QFrame#panel {{ background: {PANEL}; border-radius: 5px; }}
QPushButton#panelhead {{
    background: {PANELH}; color: {TEXT}; text-align: left;
    border: none; border-radius: 5px; padding: 6px 8px; font-weight: 600;
}}
QPushButton#panelhead:hover {{ background: #464646; }}
QPushButton#panelhead:checked {{ border-bottom-left-radius: 0; border-bottom-right-radius: 0; }}
QWidget#panelbody {{ background: {PANEL}; border-bottom-left-radius: 5px;
                     border-bottom-right-radius: 5px; }}

QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#flabel {{ color: {LABEL}; }}
QLabel#hint {{ color: {MUTED}; }}
QLabel#mono {{ color: {LABEL}; font-family: Consolas, "Cascadia Mono", monospace; }}
QLabel#frame {{
    background: {ACCENT}; color: #fff; border-radius: 4px;
    padding: 3px 10px; font-family: Consolas, monospace;
}}
QLabel#badge_ok {{ color: {GOOD}; }}
QLabel#badge_bad {{ color: {BAD}; }}
QLabel#badge_warn {{ color: {WARN}; }}
QLabel#badge_off {{ color: {MUTED}; }}
QLabel#banner {{
    background: #2d3a4f; color: {TEXT}; border: 1px solid {ACCENT};
    border-radius: 5px; padding: 10px;
}}

/* ---- fields ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {FIELD}; color: {TEXT};
    border: 1px solid {OUTLINE}; border-radius: 4px;
    padding: 4px 7px; min-height: 18px;
    selection-background-color: {ACCENT};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ background: {FIELDH}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:read-only {{ color: {LABEL}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: url(@ARROW@); width: 9px; height: 6px; margin-right: 7px; }}
QComboBox::down-arrow:on {{ top: 1px; }}
QComboBox QAbstractItemView {{
    background: {FRAME}; border: 1px solid #2a2a2a; color: {TEXT};
    selection-background-color: {ACCENT}; outline: none; padding: 2px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QPlainTextEdit#log {{
    background: #242424; color: {LABEL}; border: none; border-radius: 0;
    font-family: Consolas, "Cascadia Mono", monospace; font-size: 8.5pt;
}}

/* ---- buttons ---- */
QPushButton, QToolButton {{
    background: {BUTTON}; color: {TEXT};
    border: 1px solid {OUTLINE}; border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover, QToolButton:hover {{ background: {BUTTONH}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {ACCENT}; }}
QPushButton:disabled {{ background: #3a3a3a; color: #6a6a6a; }}
QToolButton:checked, QPushButton#toggle:checked {{ background: {ACCENT}; color: #fff; }}
QToolButton#flat, QPushButton#flat {{ background: transparent; border: none; padding: 4px 8px; }}
QToolButton#flat:hover, QPushButton#flat:hover {{ background: {BUTTON}; }}
QToolButton#flat:checked {{ background: {ACCENT}; }}
QPushButton#go {{
    background: {ACCENT}; border: 1px solid #365a91; color: #ffffff;
    font-size: 10.5pt; font-weight: 600; padding: 10px; border-radius: 5px;
}}
QPushButton#go:hover {{ background: {ACCENTH}; }}
QPushButton#go:disabled {{ background: #3b4a63; color: #9aa7bb; }}
QPushButton#danger {{ background: #7a3b40; }}
QPushButton#danger:hover {{ background: #8d454b; }}

QCheckBox {{ color: {TEXT}; spacing: 7px; background: transparent; }}
QCheckBox::indicator {{
    width: 13px; height: 13px; border-radius: 3px;
    border: 1px solid {OUTLINE}; background: {FIELD};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: #365a91; }}

/* ---- lists ---- */
QTreeWidget, QListWidget, QTableWidget {{
    background: {FIELD}; border: 1px solid {OUTLINE}; border-radius: 4px;
    color: {TEXT}; outline: none; alternate-background-color: #2c2c2c;
}}
QTreeWidget::item, QListWidget::item {{ padding: 4px 4px; border-radius: 3px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #333; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT}; color: #fff; }}
QHeaderView::section {{ background: {PANELH}; color: {LABEL}; border: none; padding: 5px; }}

/* ---- inner tabs (character 1 / 2) ---- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: {FIELD}; color: {MUTED}; padding: 5px 14px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {BUTTON}; color: {TEXT}; }}

/* ---- timeline slider ---- */
QSlider::groove:horizontal {{ height: 6px; background: {FIELD}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: #36527f; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 4px; margin: -7px 0; border-radius: 2px;
    border: 1px solid #8fb0e6;
}}

QProgressBar {{
    background: {FIELD}; border: none; border-radius: 3px;
    max-height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QStatusBar {{ background: {TOPBAR}; color: {LABEL}; border-top: 1px solid {FRAME}; }}
QStatusBar::item {{ border: none; }}

QSplitter::handle {{ background: {FRAME}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #555; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #666; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #555; border-radius: 3px; min-width: 30px; }}

QDialog {{ background: {AREA}; }}
QListWidget#categories {{
    background: {TOPBAR}; border: none; border-radius: 0; padding: 6px;
}}
QListWidget#categories::item {{ padding: 8px 10px; }}
QMessageBox {{ background: {AREA}; }}
QToolTip {{ background: {FRAME}; color: {TEXT}; border: 1px solid #3a3a3a; padding: 5px; }}
"""


def stylesheet():
    """The stylesheet, with its small arrow image drawn on first use.

    Qt stylesheets cannot draw a triangle reliably, and shipping an image file
    means one more thing to bundle, so the chevron is painted here (needs a
    running QApplication) and cached in the temp folder.
    """
    import tempfile
    from pathlib import Path
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    path = Path(tempfile.gettempdir()) / "hymstudio_arrow_v1.png"
    if not path.is_file():
        pm = QPixmap(18, 12)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(LABEL), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(3, 3), QPointF(9, 9), QPointF(15, 3)])
        p.end()
        pm.save(str(path))
    return STYLESHEET.replace("@ARROW@", path.as_posix())
