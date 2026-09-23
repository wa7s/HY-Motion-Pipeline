"""Preferences - where everything lives on *this* machine.

Laid out like Blender's Preferences window: categories on the left, the page
on the right. Every path can be left blank to auto-detect; the dot beside it
says whether the app can actually find the thing.
"""

import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton,
                               QSpinBox, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget,
                               QScrollArea)

from . import config as C
from .widgets import Panel, badge, flabel, hint, set_badge, tool


class PathRow(QWidget):
    """Line edit + browse button + a dot that says whether it resolves."""
    changed = Signal()

    def __init__(self, kind, value, detect, required=True, pattern="", check=None):
        super().__init__()
        self.kind, self.detect, self.required = kind, detect, required
        self.pattern = pattern
        self.check = check or (lambda p: p.is_dir() if kind == "dir" else p.is_file())
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.dot = badge("off")
        self.dot.setFixedWidth(14)
        self.ed = QLineEdit(str(value or ""))
        self.ed.setClearButtonEnabled(True)
        self.btn = tool("…", "Browse", width=32)
        h.addWidget(self.dot)
        h.addWidget(self.ed, 1)
        h.addWidget(self.btn)
        self.ed.textChanged.connect(self.refresh)
        self.btn.clicked.connect(self._browse)

    def text(self):
        return self.ed.text().strip().strip('"')

    def resolved(self):
        t = self.text()
        if t:
            p = Path(t)
            return p if self.check(p) else None
        try:
            d = self.detect()
        except Exception:
            d = None
        return Path(d) if d else None

    def refresh(self, *_):
        t = self.text()
        if not t:
            d = None
            try:
                d = self.detect()
            except Exception:
                pass
            self.ed.setPlaceholderText(("Auto-detected:  %s" % d) if d else
                                       "Not found - click … to choose")
        r = self.resolved()
        set_badge(self.dot, "ok" if r else ("fail" if self.required else "off"))
        self.changed.emit()

    def _browse(self):
        start = self.text() or str(self.resolved() or Path.home())
        if self.kind == "dir":
            f = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Choose file", start, self.pattern)
        if f:
            self.ed.setText(str(Path(f)))


class PreferencesDialog(QDialog):
    PAGES = ("File Paths", "Engine", "Setup Check")

    def __init__(self, settings, parent=None, first_run=False, page=0):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("HY Motion Studio Preferences")
        self.resize(920, 640)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.cats = QListWidget()
        self.cats.setObjectName("categories")
        self.cats.setFixedWidth(180)
        self.cats.addItems(self.PAGES)
        root.addWidget(self.cats)

        right = QWidget()
        right.setObjectName("area")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(18, 16, 18, 14)
        rv.setSpacing(12)
        if first_run:
            b = QLabel("<b>Welcome to HY Motion Studio.</b><br>"
                       "Tell it where your tools are. Anything left blank is found "
                       "automatically - a <span style='color:#6cc644'>green</span> dot "
                       "means it was found, <span style='color:#e0555f'>red</span> means "
                       "you need to point to it. You can come back here any time from "
                       "<b>Edit › Preferences</b>.")
            b.setObjectName("banner")
            b.setWordWrap(True)
            rv.addWidget(b)
        self.stack = QStackedWidget()
        rv.addWidget(self.stack, 1)

        row = QHBoxLayout()
        b_fill = QPushButton("Fill in detected paths")
        b_fill.setToolTip("Write every auto-detected location into its field.")
        b_fill.clicked.connect(self._fill_detected)
        row.addWidget(b_fill)
        row.addStretch(1)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        b_save = QPushButton("Save Preferences")
        b_save.setObjectName("go")
        b_save.setMinimumWidth(170)
        b_save.clicked.connect(self._save)
        row.addWidget(b_cancel)
        row.addWidget(b_save)
        rv.addLayout(row)
        root.addWidget(right, 1)

        self.stack.addWidget(self._page_paths())
        self.stack.addWidget(self._page_engine())
        self.stack.addWidget(self._page_check())
        self.cats.currentRowChanged.connect(self._page_changed)
        self.cats.setCurrentRow(page)
        for r in self.rows.values():
            r.refresh()

    # -- pages -------------------------------------------------------------
    def _scroll(self, inner):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        inner.setObjectName("region")
        sa.setWidget(inner)
        return sa

    def _page_paths(self):
        s = self.settings
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)
        self.rows = {}

        def comfy_now():
            return self.rows["comfy_dir"].resolved() if "comfy_dir" in self.rows \
                else C.find_comfy_dir()

        p = Panel("ComfyUI")
        f = p.form()
        self.rows["comfy_dir"] = PathRow(
            "dir", s.get("comfy_dir"), C.find_comfy_dir,
            check=lambda q: C.normalise_comfy_dir(q) is not None)
        f.addRow(flabel("ComfyUI folder"), self.rows["comfy_dir"])
        f.addRow("", hint("The ComfyUI folder itself, or a portable install's root "
                          "(the folder holding run_nvidia_gpu.bat)."))
        self.rows["comfy_python"] = PathRow(
            "file", s.get("comfy_python"), lambda: C.find_comfy_python(
                C.normalise_comfy_dir(comfy_now()) if comfy_now() else None),
            pattern="python.exe (python.exe);;All files (*.*)")
        f.addRow(flabel("ComfyUI Python"), self.rows["comfy_python"])
        f.addRow("", hint("The python.exe ComfyUI runs on: python_embeded\\python.exe "
                          "in the portable build, or your venv's Scripts\\python.exe."))
        self.rows["comfy_dir"].changed.connect(lambda: self.rows["comfy_python"].refresh())
        v.addWidget(p)

        p = Panel("Applications")
        f = p.form()
        self.rows["blender"] = PathRow("file", s.get("blender"), C.find_blender,
                                       pattern="blender.exe (blender.exe);;All files (*.*)")
        f.addRow(flabel("Blender"), self.rows["blender"])
        f.addRow("", hint("blender.exe - version 4.2 or newer. Used in the background "
                          "to put the motion on your character."))
        self.rows["cascadeur"] = PathRow("file", s.get("cascadeur"), C.find_cascadeur,
                                         required=False,
                                         pattern="cascadeur.exe (cascadeur.exe);;All files (*.*)")
        f.addRow(flabel("Cascadeur"), self.rows["cascadeur"])
        f.addRow("", hint("Optional - for the Send to Cascadeur button."))
        v.addWidget(p)

        p = Panel("Character and projects")
        f = p.form()
        self.rows["target_rig"] = PathRow("file", s.get("target_rig"), C.default_character,
                                          pattern="FBX files (*.fbx)")
        f.addRow(flabel("Character FBX"), self.rows["target_rig"])
        f.addRow("", hint("The rigged character the motion is put on. Supported "
                          "skeletons: Mixamo, Unreal (UE4 / UE5 Manny & Quinn), "
                          "3ds Max Biped and Unity-Humanoid names. Tip: drop an FBX "
                          "into the app's Mannequin folder and it is picked up "
                          "automatically."))
        self.rows["projects_dir"] = PathRow("dir", s.get("projects_dir"),
                                            lambda: C.PIPELINE_DIR / "Projects",
                                            check=lambda q: True)
        f.addRow(flabel("Projects folder"), self.rows["projects_dir"])
        f.addRow("", hint("Where generated clips are saved. Created if it does not exist."))
        v.addWidget(p)
        v.addStretch(1)
        return self._scroll(w)

    def _page_engine(self):
        s = self.settings
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)
        p = Panel("ComfyUI engine")
        f = p.form()
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(int(s.get("engine_port") or 8189))
        self.sp_port.setFixedWidth(110)
        f.addRow(flabel("Port"), self.sp_port)
        self.ck_auto = QCheckBox("Start ComfyUI automatically, hidden in the background")
        self.ck_auto.setChecked(bool(s.get("engine_autostart", True)))
        f.addRow("", self.ck_auto)
        self.ed_args = QLineEdit(str(s.get("engine_args") or ""))
        self.ed_args.setPlaceholderText("e.g.  --lowvram")
        f.addRow(flabel("Extra launch options"), self.ed_args)
        v.addWidget(p)
        v.addWidget(hint(
            "By default the app starts its own hidden ComfyUI on port 8189, so it "
            "never collides with a ComfyUI you run yourself on 8188, and closes it "
            "when you quit.\n\n"
            "Already running ComfyUI and want the app to use it? Set the port to "
            "yours (8188 for ComfyUI, 8000 for ComfyUI Desktop) and untick "
            "'Start ComfyUI automatically'. It must be on this computer.\n\n"
            "Changing the port restarts the app's engine when you save."))
        v.addStretch(1)
        return self._scroll(w)

    def _page_check(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)
        v.addWidget(hint("What HY Motion Studio can find with the settings on the "
                         "other pages (unsaved changes included)."))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Check", "Found"])
        self.tree.setRootIsDecorated(True)
        self.tree.setColumnWidth(0, 270)
        self.tree.setColumnWidth(1, 330)
        self.tree.setTextElideMode(Qt.ElideMiddle)   # long paths keep both ends
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        v.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b = QPushButton("Check again")
        b.clicked.connect(self._run_check)
        row.addWidget(b)
        if C.README_FILE.is_file():
            b2 = QPushButton("Open the README")
            b2.clicked.connect(lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(C.README_FILE))))
            row.addWidget(b2)
        row.addStretch(1)
        v.addLayout(row)
        return self._scroll(w)

    # -- behaviour ---------------------------------------------------------
    def values(self):
        out = {k: r.text() for k, r in self.rows.items()}
        out.update({"engine_port": self.sp_port.value(),
                    "engine_autostart": self.ck_auto.isChecked(),
                    "engine_args": self.ed_args.text().strip()})
        return out

    def _page_changed(self, i):
        self.stack.setCurrentIndex(i)
        if i == 2:
            self._run_check()

    def _run_check(self):
        tmp = C.Settings()
        tmp.update(self.values())
        rows = C.setup_checks(tmp)
        rows += self._engine_rows(tmp)
        C.apply(self.settings)                  # checks must not leak unsaved paths
        self.tree.clear()
        groups = {}
        colour = {"ok": "#6cc644", "fail": "#e0555f", "warn": "#e0a040", "optional": "#8f8f8f"}
        glyph = {"ok": "●", "fail": "●", "warn": "●", "optional": "○"}
        for area, name, state, detail, fix in rows:
            top = groups.get(area)
            if top is None:
                top = QTreeWidgetItem([area])
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
                self.tree.addTopLevelItem(top)
                groups[area] = top
            it = QTreeWidgetItem(["%s  %s" % (glyph[state], name), detail])
            it.setForeground(0, QColor(colour[state]))
            it.setToolTip(1, detail)
            top.addChild(it)
            if fix and state != "ok":
                # the advice gets a full-width line of its own - it is the
                # part a new user most needs to read
                tip = QTreeWidgetItem(["→  " + fix])
                tip.setForeground(0, QColor("#bdbdbd"))
                tip.setToolTip(0, fix)
                it.addChild(tip)
                tip.setFirstColumnSpanned(True)      # only works once in the tree
        self.tree.expandAll()

    def _engine_rows(self, tmp):
        """If an engine answers on the chosen port, ask it which nodes it has."""
        port = int(tmp.get("engine_port") or 8189)
        base = "http://127.0.0.1:%d" % port
        try:
            urllib.request.urlopen(base + "/system_stats", timeout=1.0).read()
        except Exception:
            return [("Engine", "ComfyUI on port %d" % port, "optional",
                     "not running right now", "Fine - the app starts it when needed.")]
        out = [("Engine", "ComfyUI on port %d" % port, "ok", "running", "")]
        for node, feature in (("HYMotionGenerate", "text to motion"),
                              ("GVHMRInference", "video to motion")):
            try:
                import json
                d = json.loads(urllib.request.urlopen(
                    base + "/object_info/" + node, timeout=3).read())
                ok = node in d
            except Exception:
                ok = False
            out.append(("Engine", "%s node (%s)" % (node, feature),
                        "ok" if ok else ("fail" if node == "HYMotionGenerate" else "optional"),
                        "loaded" if ok else "not loaded",
                        "" if ok else "Check ComfyUI's console for an import error."))
        return out

    def _fill_detected(self):
        for r in self.rows.values():
            if not r.text():
                d = r.resolved()
                if d:
                    r.ed.setText(str(d))

    def _save(self):
        self.settings.update(self.values())
        self.settings["setup_done"] = True
        self.settings.save()
        C.apply(self.settings)
        self.accept()

    def reject(self):
        C.apply(self.settings)
        super().reject()
