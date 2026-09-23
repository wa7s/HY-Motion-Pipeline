"""Small Blender-style building blocks shared by the window and Preferences."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFormLayout, QFrame, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)


class Panel(QFrame):
    """A collapsible panel: a header row with an arrow, then its contents.

    Clicking the header folds it away, like the panels in Blender's
    Properties editor. `toggled(key, open)` lets the window remember it.
    """
    toggled = Signal(str, bool)

    def __init__(self, title, key=None, open_=True, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.key = key or title
        self._title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.head = QPushButton()
        self.head.setObjectName("panelhead")
        self.head.setCheckable(True)
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.clicked.connect(self._clicked)
        self.body = QWidget()
        self.body.setObjectName("panelbody")
        self.inner = QVBoxLayout(self.body)
        self.inner.setContentsMargins(10, 8, 10, 11)
        self.inner.setSpacing(8)
        lay.addWidget(self.head)
        lay.addWidget(self.body)
        self.set_open(open_)

    def set_open(self, on):
        self.head.setChecked(bool(on))
        self.body.setVisible(bool(on))
        self.head.setText(("▾   " if on else "▸   ") + self._title)

    def is_open(self):
        return self.head.isChecked()

    def _clicked(self):
        self.set_open(self.head.isChecked())
        self.toggled.emit(self.key, self.head.isChecked())

    def add(self, w, stretch=0):
        self.inner.addWidget(w, stretch)
        return w

    def add_layout(self, layout):
        self.inner.addLayout(layout)
        return layout

    def form(self):
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFormAlignment(Qt.AlignTop)
        f.setHorizontalSpacing(10)
        f.setVerticalSpacing(7)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.inner.addLayout(f)
        return f


def flabel(text):
    """Right-aligned field label in Blender's lighter grey."""
    lb = QLabel(text)
    lb.setObjectName("flabel")
    return lb


def hint(text):
    lb = QLabel(text)
    lb.setObjectName("hint")
    lb.setWordWrap(True)
    return lb


def tool(text, tip="", checkable=False, flat=False, width=None):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    if flat:
        b.setObjectName("flat")
    if width:
        b.setFixedWidth(width)
    return b


def button(text, slot=None, tip="", min_h=28):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setMinimumHeight(min_h)
    if slot:
        b.clicked.connect(slot)
    return b


def badge(state):
    """Coloured dot for ok / fail / warn / optional."""
    lb = QLabel()
    set_badge(lb, state)
    return lb


def set_badge(lb, state):
    glyph, name = {"ok": ("●", "badge_ok"), "fail": ("●", "badge_bad"),
                   "warn": ("●", "badge_warn")}.get(state, ("○", "badge_off"))
    lb.setText(glyph)
    lb.setObjectName(name)
    lb.style().unpolish(lb)
    lb.style().polish(lb)
