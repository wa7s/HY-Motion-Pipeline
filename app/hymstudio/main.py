"""HY Motion Studio - main window."""

import functools
import json
import os
import shutil
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtWebEngineWidgets import QWebEngineView      # before QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QIcon, QDesktopServices, QFont, QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QSlider, QSplitter, QGroupBox, QFormLayout, QTreeWidget,
    QTreeWidgetItem, QProgressBar, QFileDialog, QMessageBox, QInputDialog,
    QScrollArea, QLineEdit, QListWidget, QListWidgetItem, QTabWidget,
    QMenuBar, QTabBar, QStatusBar, QDialog, QFrame,
)

from . import config as C
from . import pipeline as P
from . import presets as PR
from . import history as H
from .theme import stylesheet
from .widgets import Panel, button, flabel, hint, tool
from .prefs import PreferencesDialog


# ---------------------------------------------------------------------------
# Local static server for the viewport (Chromium blocks ES modules on file://)
# ---------------------------------------------------------------------------
class _Handler(SimpleHTTPRequestHandler):
    # Windows registers .js as text/plain in HKCR, which mimetypes picks up.
    # Chromium then refuses to execute the viewport's ES modules under strict
    # MIME checking, so the types are pinned here rather than trusted.
    TYPES = {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".html": "text/html; charset=utf-8",
        ".css": "text/css",
        ".json": "application/json",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".bin": "application/octet-stream",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }

    def guess_type(self, path):
        ext = os.path.splitext(str(path))[1].lower()
        return self.TYPES.get(ext) or super().guess_type(path)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class LoggingPage(QWebEnginePage):
    """Surfaces viewport JS errors in the app log instead of swallowing them."""

    def __init__(self, sink, parent=None):
        super().__init__(parent)
        self._sink = sink

    def javaScriptConsoleMessage(self, level, message, line, source):
        src = str(source).rsplit("/", 1)[-1]
        self._sink("viewport: %s  (%s:%s)" % (message, src, line))


def start_viewer_server():
    handler = functools.partial(_Handler, directory=str(C.VIEWER_DIR))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ---------------------------------------------------------------------------
# Generation worker
# ---------------------------------------------------------------------------
class GenerateWorker(QThread):
    log = Signal(str)
    status = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine, settings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.s = dict(settings)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # -- one actor: generate, file it, retarget --------------------------
    def _one(self, proj, stem, prompt, duration, seed, place, blender):
        s = dict(self.s)
        s.update({"prompt": prompt, "duration": duration, "seed": seed})

        t0 = time.time()
        pid = P.submit(P.build_workflow(s, stem))

        def tick(el):
            extra = "   (first run loads ~13 GB of models)" if el < 100 else ""
            self.status.emit("Generating %s  %ds%s" % (stem, int(el), extra))

        took = P.wait_for(pid, tick, lambda: self._cancel)
        self.log.emit("  %s generated in %.0fs" % (stem, took))

        raw_fbx = P.newest(C.OUT_FBX_DIR, ".fbx", t0)
        raw_npz = P.newest(C.OUT_NPZ_DIR, ".npz", t0)
        if not raw_fbx:
            raise RuntimeError("The engine finished but wrote no FBX.")

        gen = P.copy_into(raw_fbx, proj / "Generated", stem + "_smplh")
        if raw_npz:
            npz = P.copy_into(raw_npz, proj / "Generated", stem + "_smplh")
            ok, why = P.heading_check(npz)
            if not ok:
                self.log.emit("  WARNING  " + why)

        self.status.emit("Retargeting %s onto the character..." % stem)
        out_fbx = proj / "Blender" / (stem + "_retargeted.fbx")
        out_glb = proj / "Blender" / (stem + "_preview.glb")
        P.retarget(blender, gen, self.s["target_rig"], out_fbx, out_glb,
                   self.s.get("profile", "auto"), 30, self.log.emit,
                   fingers=self.s.get("fingers", "animate"),
                   offset=place[0], yaw=place[1],
                   hands={k: self.s.get(k) for k in
                          ("left_hand", "right_hand", "left_cycle", "right_cycle")})
        return {"source_fbx": str(gen), "retarget_fbx": str(out_fbx),
                "glb": str(out_glb), "seconds": took}

    def run(self):
        try:
            if not self.engine.is_up():
                self.status.emit("Starting engine...")
                if not self.engine.start():
                    raise RuntimeError(
                        "The ComfyUI engine would not start. Check that\n"
                        + str(C.COMFY_MAIN) + "\nstill exists.")

            proj = P.ensure_project(self.s["project"])
            base = P.safe_name(self.s.get("clip_name")
                               or self.s["prompt"][:24])
            blender = C.Settings().blender_exe
            two = int(self.s.get("characters", 1)) >= 2

            # C1 stays at the origin; C2 is placed by the staging controls.
            a = self._one(proj, base + ("_C1" if two else ""),
                          self.s["prompt"], self.s["duration"],
                          self.s["seed"], ((0.0, 0.0, 0.0), 0.0), blender)

            res = {"project": str(proj), "stem": base, "two": two,
                   "c1": a, "seconds": a["seconds"]}

            if two:
                if self._cancel:
                    raise RuntimeError("Cancelled.")
                # Staging is deliberately NOT baked into the clip. Each
                # character is exported standing at the origin, the way
                # animation clips normally are, and the viewport places them
                # live so distance/facing/delay stay adjustable without
                # re-rendering. Blender and Unity position actors in the
                # scene, not in the take.
                b = self._one(proj, base + "_C2",
                              self.s["prompt2"], self.s["duration2"],
                              self.s["seed2"], ((0.0, 0.0, 0.0), 0.0),
                              blender)
                res["c2"] = b
                res["seconds"] += b["seconds"]

            self.finished_ok.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class VideoWorker(QThread):
    """Video -> animation: cut, find the person, capture, rebuild, retarget.

    Every heavy step runs outside this process (the engine, ComfyUI's Python,
    Blender), so the window stays responsive and the exe needs no ML stack.
    """
    log = Signal(str)
    status = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    STEPS = 5

    def __init__(self, engine, settings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.s = dict(settings)
        self._cancel = False

    def cancel(self):
        self._cancel = True
        P.interrupt_engine()

    def _step(self, n, text):
        if self._cancel:
            raise RuntimeError("Cancelled.")
        self.status.emit("Step %d/%d  -  %s" % (n, self.STEPS, text))
        self.log.emit("  [%d/%d] %s" % (n, self.STEPS, text))

    def run(self):
        staged = []
        try:
            s = self.s
            src = Path(s["video_path"])
            t0, t1 = float(s["video_start"]), float(s["video_end"])
            blender = C.Settings().blender_exe
            if not blender:
                raise RuntimeError("Blender was not found. Set its path in Settings.")
            if not self.engine.is_up():
                self.status.emit("Starting engine...")
                if not self.engine.start():
                    raise RuntimeError(
                        "The ComfyUI engine would not start. Check that\n"
                        + str(C.COMFY_MAIN) + "\nstill exists.")

            proj = P.ensure_project(s["project"])
            stem = P.safe_name(s.get("clip_name") or src.stem, "video")
            started = time.time()

            self._step(1, "Cutting %.1f-%.1f s out of %s" % (t0, t1, src.name))
            clip = proj / "Input" / (stem + ".mp4")
            info = P.trim_video(src, clip, t0, t1, self.log.emit)
            fps, frames = float(info["fps"]), int(info["frames"])
            self.log.emit("     %d frames at %.2f fps, %dx%d"
                          % (frames, fps, info["width"], info["height"]))

            # HY-Motion's cached models would leave too little of a 16 GB card
            self._step(2, "Finding the person in every frame")
            if P.free_engine_memory():
                self.log.emit("     freed the engine's cached models for capture")
            mask = proj / "Input" / (stem + "_mask.mp4")
            sheet = proj / "Input" / (stem + "_mask_check.jpg")
            P.person_mask(clip, mask, sheet, self.log.emit)

            self._step(3, "Motion capture - %d frames" % frames)
            # the engine's video loader only lists files directly in input/
            tag = "hymvid_%s_%d" % (stem, int(started))
            for f, name in ((clip, tag + ".mp4"), (mask, tag + "_mask.mp4")):
                dst = C.COMFY_IN / name
                shutil.copy2(f, dst)
                staged.append(dst)
            t_sub = time.time()
            pid = P.submit(P.gvhmr_workflow(tag + ".mp4", tag + "_mask.mp4",
                                            s.get("video_moving", False)))

            def tick(el):
                est = frames * 0.5 + 30
                self.status.emit("Step 3/%d  -  Motion capture  %ds  (about %ds)"
                                 % (self.STEPS, int(el), int(est)))

            took = P.wait_for(pid, tick, lambda: self._cancel,
                              limit=max(1800, int(frames * 4 + 600)))
            npz = P.gvhmr_result(pid, t_sub)
            if not npz:
                raise RuntimeError("Motion capture finished but wrote no result.")
            self.log.emit("     captured in %.0fs" % took)
            npz = P.copy_into(npz, proj / "Generated", stem + "_gvhmr")

            self._step(4, "Building the skeleton from the capture")
            gen = proj / "Generated" / (stem + "_smplh.fbx")
            P.gvhmr_to_fbx(blender, npz, gen, fps, self.log.emit)

            self._step(5, "Putting the motion on the character")
            out_fbx = proj / "Blender" / (stem + "_retargeted.fbx")
            out_glb = proj / "Blender" / (stem + "_preview.glb")
            P.retarget(blender, gen, s["target_rig"], out_fbx, out_glb,
                       s.get("profile", "auto"), 30, self.log.emit,
                       fingers="animate",
                       hands={k: s.get(k) for k in
                              ("left_hand", "right_hand", "left_cycle", "right_cycle")})

            total = time.time() - started
            self.finished_ok.emit({
                "kind": "video", "project": str(proj), "stem": stem, "two": False,
                "c1": {"source_fbx": str(gen), "retarget_fbx": str(out_fbx),
                       "glb": str(out_glb), "seconds": total},
                "seconds": total, "video": str(src), "t0": t0, "t1": t1,
                "moving": bool(s.get("video_moving", False)),
                "mask_check": str(sheet),
            })
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            for f in staged:
                try:
                    f.unlink()
                except Exception:
                    pass


class ProbeWorker(QThread):
    """Reads a video's length and grabs a preview frame off the GUI thread."""
    done = Signal(dict)

    def __init__(self, path, thumb, at, parent=None):
        super().__init__(parent)
        self.path, self.thumb, self.at = path, thumb, at

    def run(self):
        try:
            info = P.probe_video(self.path, self.thumb, self.at)
            info["path"], info["thumb"], info["at"] = self.path, self.thumb, self.at
            self.done.emit(info)
        except Exception as e:
            self.done.emit({"path": self.path, "error": str(e)})


# ---------------------------------------------------------------------------
class Studio(QMainWindow):
    # Worker threads must never touch widgets directly. Everything they want
    # to say goes through these, which Qt queues onto the GUI thread.
    sig_log = Signal(str)
    sig_status = Signal(str, bool)
    sig_engine = Signal(bool)

    HAND_ITEMS = ["From clip", "Relaxed", "Fist", "Open", "Point", "Grip"]
    HAND_VALS = ["source", "relaxed", "fist", "open", "point", "grip"]
    PROFILES = ["auto", "mixamo", "ue5", "ue4", "biped", "unity", "smplh"]

    def __init__(self):
        super().__init__()
        self.sig_log.connect(self._append_log)
        self.sig_status.connect(self._set_status)
        self.sig_engine.connect(self._set_engine_badge)
        self.setWindowTitle("HY Motion Studio")
        self.resize(1720, 1000)
        self.setMinimumSize(1280, 780)
        ico = C.APP_DIR / "MotionStudio.ico"
        if ico.is_file():
            self.setWindowIcon(QIcon(str(ico)))

        self.settings = C.Settings()
        C.apply(self.settings)
        self.engine = P.Engine(self.log)
        self.worker = None
        self.last = {}
        self._slider_lock = False
        self._viewport_live = False
        self._video_info = {}
        self._probe = None
        self._probe_next = None
        self._duration = 0.0
        self._rig = ""

        self.srv, self.port = start_viewer_server()
        self.setStyleSheet(stylesheet())
        self._build()
        self._load_settings_into_ui()
        self._reload_history()

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_viewport)
        self.poll.start(150)
        self.engine_poll = QTimer(self)
        self.engine_poll.timeout.connect(self._check_engine)
        self.engine_poll.start(3000)

        self.log("HY Motion Studio %s" % C.VERSION)
        self._log_setup()
        QTimer.singleShot(400, self._boot_engine)
        if self._needs_setup():
            QTimer.singleShot(700, lambda: self.open_preferences(first_run=True))

    # =====================================================================
    # layout
    # =====================================================================
    def _area(self, name="area"):
        w = QWidget()
        w.setObjectName(name)
        w.setAttribute(Qt.WA_StyledBackground, True)
        return w

    def _panel(self, title, key, collapsed=False):
        coll = self.settings.get("collapsed") or {}
        p = Panel(title, key, open_=not coll.get(key, collapsed))
        p.setAttribute(Qt.WA_StyledBackground, True)
        p.body.setAttribute(Qt.WA_StyledBackground, True)
        p.toggled.connect(self._panel_toggled)
        return p

    def _panel_toggled(self, key, is_open):
        coll = dict(self.settings.get("collapsed") or {})
        coll[key] = not is_open
        self.settings["collapsed"] = coll

    def _build(self):
        self.setMenuWidget(self._topbar())
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self._left_region())
        self.hsplit.addWidget(self._centre_region())
        self.hsplit.addWidget(self._right_region())
        self.hsplit.setStretchFactor(0, 0)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setStretchFactor(2, 0)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.setSizes([400, 960, 340])
        self.setCentralWidget(self.hsplit)
        self._statusbar()
        self._shortcuts()

    # ---------------- top bar: menus + workspaces ----------------
    def _topbar(self):
        bar = self._area("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(2, 0, 10, 0)
        h.setSpacing(2)
        mb = QMenuBar()
        mb.setNativeMenuBar(False)
        self._menus(mb)
        h.addWidget(mb, 0, Qt.AlignVCenter)
        h.addSpacing(20)
        self.ws = QTabBar()
        self.ws.setObjectName("workspaces")
        self.ws.setDrawBase(False)
        self.ws.setExpanding(False)
        self.ws.addTab("Text to Motion")
        self.ws.addTab("Video to Motion")
        self.ws.setToolTip("Workspaces - make a clip from a text prompt, or "
                           "capture it from a video.")
        self.ws.currentChanged.connect(self._source_changed)
        h.addWidget(self.ws, 0, Qt.AlignBottom)
        h.addStretch(1)
        self.lb_top = QLabel("")
        self.lb_top.setObjectName("hint")
        h.addWidget(self.lb_top)
        return bar

    def _act(self, menu, text, slot, shortcut=None, checkable=False):
        a = QAction(text, self)
        a.setCheckable(checkable)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda *_, f=slot: f())
        menu.addAction(a)
        return a

    def _menus(self, mb):
        m = mb.addMenu("File")
        self._act(m, "New Project...", self._new_project)
        self._act(m, "Open Project Folder", self.on_open_folder)
        m.addSeparator()
        self._act(m, "Choose Video...", self._menu_video)
        self._act(m, "Choose Character...", self._pick_rig)
        m.addSeparator()
        self._act(m, "Quit", self.close, "Ctrl+Q")

        m = mb.addMenu("Edit")
        self._act(m, "Preferences...", self.open_preferences, "Ctrl+,")

        m = mb.addMenu("View")
        self.act_info = self._act(m, "Info Log", self._show_info, checkable=True)
        m.addSeparator()
        self._act(m, "Frame Character", lambda: self._js("hym.resetView()"), "Home")
        self._act(m, "Rest Pose", lambda: self._js("hym.restPose()"))
        self._act(m, "Play / Pause    Space", lambda: self._js("hym.toggle()"))

        m = mb.addMenu("Help")
        self._act(m, "Read Me", self._open_readme, "F1")
        self._act(m, "Setup Check...", lambda: self.open_preferences(page=2))
        if C.GITHUB_URL:
            self._act(m, "Project Page on GitHub",
                      lambda: QDesktopServices.openUrl(QUrl(C.GITHUB_URL)))
        m.addSeparator()
        self._act(m, "Licences && Credits...", self._show_licences)
        self._act(m, "About HY Motion Studio", self._about)

    def _shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=lambda: self._js("hym.toggle()"))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.on_generate)

    # ---------------- left: properties ----------------
    def _left_region(self):
        wrap = self._area()
        wrap.setMinimumWidth(350)
        wrap.setMaximumWidth(560)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._region_header("Properties"))

        inner = self._area("region")
        lv = QVBoxLayout(inner)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        # --- output: project + clip name (both workspaces) ---
        p = self._panel("Output", "output")
        f = p.form()
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_project = QComboBox()
        self.cb_project.addItems(P.list_projects())
        self.cb_project.currentTextChanged.connect(self._project_changed)
        row.addWidget(self.cb_project, 1)
        row.addWidget(button("New", self._new_project, "Create a new project folder", 26))
        f.addRow(flabel("Project"), row)
        self.ed_clip = QLineEdit()
        self.ed_clip.setPlaceholderText("optional - named from the prompt")
        f.addRow(flabel("Clip name"), self.ed_clip)
        lv.addWidget(p)

        # ===== Text to Motion =====
        self._text_panels = []

        p = self._panel("Motion", "motion")
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for n in (1, 2):
            page = QWidget()
            pl = QVBoxLayout(page)
            pl.setContentsMargins(0, 8, 0, 0)
            pl.setSpacing(8)
            ed = QPlainTextEdit()
            ed.setPlaceholderText("Describe what the body does, e.g. 'walks forward "
                                  "four steps, stops and waves with the right hand'")
            ed.setFixedHeight(104)
            pl.addWidget(ed)
            fl = QFormLayout()
            fl.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fl.setHorizontalSpacing(10)
            dur = QDoubleSpinBox()
            dur.setRange(0.5, 12.0)
            dur.setSingleStep(0.5)
            dur.setSuffix(" s")
            seed = QSpinBox()
            seed.setRange(0, 2147483647)
            fl.addRow(flabel("Length"), dur)
            fl.addRow(flabel("Seed"), seed)
            pl.addLayout(fl)
            self.tabs.addTab(page, "Character %d" % n)
            if n == 1:
                self.ed_prompt, self.sp_dur, self.sp_seed = ed, dur, seed
            else:
                self.ed_prompt2, self.sp_dur2, self.sp_seed2 = ed, dur, seed
        p.add(self.tabs)
        p.add(hint("Describe body mechanics, not mood. Under about 30 words works best."))
        lv.addWidget(p)
        self._text_panels.append(p)

        p = self._panel("Presets", "presets")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(170)
        self.tree.itemDoubleClicked.connect(self._apply_preset)
        p.add(self.tree)
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, slot in (("Use", lambda: self._apply_preset(self.tree.currentItem())),
                           ("Save Current", self._save_preset),
                           ("Delete", self._delete_preset)):
            row.addWidget(button(text, slot, min_h=26))
        p.add_layout(row)
        lv.addWidget(p)
        self._text_panels.append(p)
        self._reload_presets()

        p = self._panel("Scene", "scene")
        f = p.form()
        self.cb_chars = QComboBox()
        self.cb_chars.addItems(["1 character", "2 characters"])
        self.cb_chars.currentIndexChanged.connect(self._chars_changed)
        f.addRow(flabel("Characters"), self.cb_chars)
        self.stage_box = QWidget()
        sf = QFormLayout(self.stage_box)
        sf.setContentsMargins(0, 4, 0, 0)
        sf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sf.setHorizontalSpacing(10)
        sf.setVerticalSpacing(7)
        self.sp_dist = QDoubleSpinBox()
        self.sp_dist.setRange(0.0, 8.0)
        self.sp_dist.setSingleStep(0.1)
        self.sp_dist.setSuffix(" m")
        self.sp_dist.valueChanged.connect(self._restage)
        sf.addRow(flabel("Distance"), self.sp_dist)
        self.sp_face = QDoubleSpinBox()
        self.sp_face.setRange(-180.0, 180.0)
        self.sp_face.setSingleStep(15.0)
        self.sp_face.setSuffix(" °")
        self.sp_face.valueChanged.connect(self._restage)
        sf.addRow(flabel("Facing"), self.sp_face)
        self.sp_delay = QDoubleSpinBox()
        self.sp_delay.setRange(0.0, 10.0)
        self.sp_delay.setSingleStep(0.1)
        self.sp_delay.setSuffix(" s")
        self.sp_delay.valueChanged.connect(self._restage)
        sf.addRow(flabel("Reacts after"), self.sp_delay)
        sf.addRow("", hint("Staging is live - adjust it while the clip plays."))
        p.add(self.stage_box)
        lv.addWidget(p)
        self._text_panels.append(p)

        p = self._panel("Generation", "generation", collapsed=True)
        f = p.form()
        self.cb_model = QComboBox()
        self.cb_model.addItems(["HY-Motion-1.0", "HY-Motion-1.0-Lite"])
        f.addRow(flabel("Model"), self.cb_model)
        self.ck_rand = QCheckBox("New random seed each run")
        f.addRow("", self.ck_rand)
        self.sp_cfg = QDoubleSpinBox()
        self.sp_cfg.setRange(1.0, 15.0)
        self.sp_cfg.setSingleStep(0.5)
        f.addRow(flabel("Guidance"), self.sp_cfg)
        self.cb_quant = QComboBox()
        self.cb_quant.addItems(["bnb-4bit", "awq", "int4", "int8", "none"])
        f.addRow(flabel("Text encoder"), self.cb_quant)
        self.ck_offload = QCheckBox("Keep the text encoder on the CPU")
        f.addRow("", self.ck_offload)
        f.addRow("", hint("Lite and CPU offload help on cards with less than 16 GB."))
        lv.addWidget(p)
        self._text_panels.append(p)

        # ===== Video to Motion =====
        self._video_panels = []
        p = self._panel("Video", "video")
        p.add(button("Choose Video...", self._pick_video, min_h=30))
        self.lb_video = hint("No video chosen.")
        p.add(self.lb_video)
        self.lb_thumb = QLabel("")
        self.lb_thumb.setAlignment(Qt.AlignCenter)
        self.lb_thumb.setMinimumHeight(40)
        self.lb_thumb.setStyleSheet("background: #232323; border-radius: 4px;")
        p.add(self.lb_thumb)
        lv.addWidget(p)
        self._video_panels.append(p)

        p = self._panel("Clip Range", "range")
        f = p.form()
        self.sp_vstart = QDoubleSpinBox()
        self.sp_vend = QDoubleSpinBox()
        for sp in (self.sp_vstart, self.sp_vend):
            sp.setRange(0.0, 0.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.valueChanged.connect(self._video_range_changed)
        self.sp_vstart.editingFinished.connect(self._refresh_thumb)
        f.addRow(flabel("Start"), self.sp_vstart)
        f.addRow(flabel("End"), self.sp_vend)
        f.addRow("", button("Use Whole Video", self._video_whole, min_h=26))
        self.cb_cam = QComboBox()
        self.cb_cam.addItems(["Fixed (on a tripod)", "Moving (handheld / panning)"])
        f.addRow(flabel("Camera"), self.cb_cam)
        self.lb_vlen = hint("")
        p.add(self.lb_vlen)
        lv.addWidget(p)
        self._video_panels.append(p)

        p = self._panel("Good to Know", "vnote", collapsed=False)
        p.add(hint("Best results: one person, whole body and feet in view, plain "
                   "clothing. Video capture records the body only - set the hands "
                   "below."))
        p.add(hint("Reference / previs only: the video-capture model and body model "
                   "are licensed for non-commercial use. Keyframe over the result "
                   "before anything ships."))
        lv.addWidget(p)
        self._video_panels.append(p)

        # ===== both =====
        p = self._panel("Hands", "hands")
        f = p.form()
        for side, label in (("l", "Left hand"), ("r", "Right hand")):
            row = QHBoxLayout()
            row.setSpacing(6)
            cb = QComboBox()
            cb.addItems(self.HAND_ITEMS)
            cb.setToolTip("Neither HY-Motion nor video capture makes finger "
                          "motion, so the hand pose is set here.")
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 6.0)
            sp.setSingleStep(0.25)
            sp.setSuffix(" Hz")
            sp.setToolTip("Open / close cycles per second. 0 holds the pose.")
            sp.setFixedWidth(80)
            row.addWidget(cb, 1)
            row.addWidget(sp)
            setattr(self, "cb_hand_" + side, cb)
            setattr(self, "sp_cycle_" + side, sp)
            f.addRow(flabel(label), row)
        lv.addWidget(p)

        lv.addStretch(1)
        sa = QScrollArea()
        sa.setWidget(inner)
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.addWidget(sa, 1)

        foot = self._area()
        fv = QVBoxLayout(foot)
        fv.setContentsMargins(8, 8, 8, 10)
        self.btn_go = QPushButton("Generate Animation")
        self.btn_go.setObjectName("go")
        self.btn_go.setToolTip("Ctrl+Enter")
        self.btn_go.clicked.connect(self.on_generate)
        fv.addWidget(self.btn_go)
        v.addWidget(foot)
        return wrap

    def _region_header(self, title):
        w = self._area("header")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 6, 10, 6)
        lb = QLabel(title)
        lb.setObjectName("areatitle")
        h.addWidget(lb)
        h.addStretch(1)
        return w

    # ---------------- centre: viewport, timeline, info ----------------
    def _centre_region(self):
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setChildrenCollapsible(False)
        top = self._area()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)

        head = self._area("header")
        h = QHBoxLayout(head)
        h.setContentsMargins(10, 4, 8, 4)
        h.setSpacing(6)
        lb = QLabel("Viewport")
        lb.setObjectName("areatitle")
        h.addWidget(lb)
        h.addSpacing(8)
        self.cb_view = QComboBox()
        self.cb_view.addItems(["Character + Skeleton", "Character", "Skeleton"])
        self.cb_view.setFixedWidth(180)
        self.cb_view.currentIndexChanged.connect(self._view_mode)
        h.addWidget(self.cb_view)
        h.addStretch(1)
        self.ck_follow = tool("Follow", "Keep a travelling character in shot. "
                              "Your orbit angle is kept.", checkable=True)
        self.ck_follow.toggled.connect(
            lambda b: self._js("hym.setFollow(%s)" % ("true" if b else "false")))
        self.ck_grid = tool("Floor", "Show the floor grid and axes.", checkable=True)
        self.ck_grid.toggled.connect(
            lambda b: self._js("hym.setGrid(%s)" % ("true" if b else "false")))
        b_frame = tool("Frame", "Frame the character (Home)")
        b_frame.clicked.connect(lambda: self._js("hym.resetView()"))
        for b in (self.ck_follow, self.ck_grid, b_frame):
            h.addWidget(b)
        tv.addWidget(head)

        self.view = QWebEngineView()
        self._page = LoggingPage(self.log, self.view)
        self.view.setPage(self._page)
        self.view.setMinimumSize(QSize(480, 340))
        self.view.loadFinished.connect(self._viewport_ready)
        self.view.load(QUrl(f"http://127.0.0.1:{self.port}/viewer.html"))
        tv.addWidget(self.view, 1)
        tv.addWidget(self._timeline())
        self.vsplit.addWidget(top)

        self.info = self._area()
        iv = QVBoxLayout(self.info)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(0)
        ih = self._area("header")
        hh = QHBoxLayout(ih)
        hh.setContentsMargins(12, 4, 8, 4)
        lb = QLabel("Info")
        lb.setObjectName("areatitle")
        hh.addWidget(lb)
        hh.addStretch(1)
        b_clear = tool("Clear", "Clear the log", flat=True)
        b_clear.clicked.connect(lambda: self.log_box.clear())
        hh.addWidget(b_clear)
        iv.addWidget(ih)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setObjectName("log")
        iv.addWidget(self.log_box, 1)
        self.vsplit.addWidget(self.info)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.vsplit.setSizes([780, 170])
        return self.vsplit

    def _timeline(self):
        bar = self._area("timeline")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 6, 12, 6)
        h.setSpacing(6)
        b_start = tool("|◀", "Jump to start", width=34)
        b_start.clicked.connect(lambda: self._jump(0.0))
        self.btn_play = tool("▶", "Play / pause (Space)", width=40)
        self.btn_play.clicked.connect(lambda: self._js("hym.toggle()"))
        b_end = tool("▶|", "Jump to end", width=34)
        b_end.clicked.connect(lambda: self._jump(max(self._duration - 1e-3, 0.0)))
        for b in (b_start, self.btn_play, b_end):
            b.setFixedWidth(44)
            b.setStyleSheet("padding: 4px 2px;")     # room for the symbol
            h.addWidget(b)
        b_rest = tool("Rest Pose", "Stop and show the rig's neutral pose.")
        b_rest.clicked.connect(lambda: self._js("hym.restPose()"))
        h.addWidget(b_rest)
        h.addSpacing(8)
        self.sl_time = QSlider(Qt.Horizontal)
        self.sl_time.setRange(0, 0)
        self.sl_time.sliderMoved.connect(self._scrub)
        self.sl_time.sliderPressed.connect(lambda: setattr(self, "_slider_lock", True))
        self.sl_time.sliderReleased.connect(lambda: setattr(self, "_slider_lock", False))
        h.addWidget(self.sl_time, 1)
        h.addSpacing(8)
        self.lb_frame = QLabel("0 / 0")
        self.lb_frame.setObjectName("frame")
        self.lb_frame.setAlignment(Qt.AlignCenter)
        self.lb_frame.setMinimumWidth(96)
        self.lb_frame.setToolTip("Current frame / total frames")
        h.addWidget(self.lb_frame)
        self.lb_time = QLabel("0.00 s")
        self.lb_time.setObjectName("mono")
        self.lb_time.setFixedWidth(66)
        h.addWidget(self.lb_time)
        self.lb_fps = QLabel("")
        self.lb_fps.setObjectName("mono")
        self.lb_fps.setFixedWidth(58)
        self.lb_fps.setToolTip("Viewport drawing rate")
        h.addWidget(self.lb_fps)
        return bar

    # ---------------- right: clips and output ----------------
    def _right_region(self):
        wrap = self._area()
        wrap.setMinimumWidth(300)
        wrap.setMaximumWidth(480)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._region_header("Clips"))
        inner = self._area("region")
        lv = QVBoxLayout(inner)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        p = self._panel("History", "history")
        self.lst_hist = QListWidget()
        self.lst_hist.setMinimumHeight(230)
        self.lst_hist.setToolTip("Double-click to play a clip again.")
        self.lst_hist.itemDoubleClicked.connect(self._load_history_item)
        p.add(self.lst_hist, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, slot, tip in (
                ("Play", lambda: self._load_history_item(self.lst_hist.currentItem()),
                 "Load the selected clip into the viewport"),
                ("Reuse Settings", self._reuse_history_settings,
                 "Copy the selected clip's prompt or video settings"),
                ("Tidy", self._tidy_history, "Remove clips whose files are gone")):
            row.addWidget(button(text, slot, tip, 26))
        p.add_layout(row)
        lv.addWidget(p)

        p = self._panel("Character", "character")
        self.lb_rig = QLabel("-")
        self.lb_rig.setWordWrap(True)
        p.add(self.lb_rig)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button("Choose...", self._pick_rig, "Choose the character FBX", 26), 1)
        row.addWidget(button("From Mannequin Folder", self._default_rig,
                             "Use the first FBX in the app's Mannequin folder", 26))
        p.add_layout(row)
        f = p.form()
        self.cb_profile = QComboBox()
        self.cb_profile.addItems(self.PROFILES)
        self.cb_profile.setToolTip("Which skeleton naming the character uses. "
                                   "'auto' recognises it by its bone names.")
        f.addRow(flabel("Skeleton"), self.cb_profile)
        lv.addWidget(p)

        p = self._panel("Send To", "send")
        p.add(button("Open in Blender", self.on_open_blender,
                     "Open Blender with the clip already imported", 30))
        p.add(button("Send to Cascadeur", self.on_cascadeur,
                     "Open the clip in Cascadeur for clean-up", 30))
        lv.addWidget(p)

        p = self._panel("Export", "export")
        p.add(button("Save Character FBX...", self.on_export_blender,
                     "Save the animated character wherever you like", 30))
        p.add(button("Export Unity FBX (SMPL-H)", self.on_export_unity,
                     "The raw skeleton renamed for Unity's Humanoid importer", 30))
        self.ck_strip = QCheckBox("Strip finger bones (52 → 22)")
        p.add(self.ck_strip)
        p.add(button("Open Project Folder", self.on_open_folder, min_h=30))
        lv.addWidget(p)

        p = self._panel("Last Result", "result")
        self.lb_result = hint("Nothing made yet.")
        p.add(self.lb_result)
        lv.addWidget(p)

        lv.addStretch(1)
        sa = QScrollArea()
        sa.setWidget(inner)
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.addWidget(sa, 1)
        return wrap

    # ---------------- status bar ----------------
    def _statusbar(self):
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.lb_status = QLabel("Starting...")
        self.lb_status.setContentsMargins(8, 0, 0, 0)
        sb.addWidget(self.lb_status, 1)
        self.pb = QProgressBar()
        self.pb.setRange(0, 0)
        self.pb.setFixedWidth(170)
        self.pb.setVisible(False)
        sb.addPermanentWidget(self.pb)
        self.lb_engine = QLabel("○  Engine")
        self.lb_engine.setObjectName("badge_off")
        self.lb_engine.setContentsMargins(12, 0, 6, 0)
        sb.addPermanentWidget(self.lb_engine)
        ver = QLabel("v" + C.VERSION)
        ver.setObjectName("hint")
        ver.setContentsMargins(6, 0, 10, 0)
        sb.addPermanentWidget(ver)

    # =====================================================================
    # helpers
    # =====================================================================
    def log(self, text):
        """Safe from any thread."""
        self.sig_log.emit(str(text))

    def _append_log(self, text):
        self.log_box.appendPlainText(text)

    def _js(self, code, cb=None):
        # Calls that touch window.hym before the ES modules have executed only
        # raise ReferenceError and spam the log. The readiness probe passes a
        # callback and is written to tolerate hym being absent, so it is the
        # one call allowed through early.
        if not self._viewport_live and cb is None:
            return
        page = self.view.page()
        if cb:
            page.runJavaScript(code, 0, cb)
        else:
            page.runJavaScript(code)

    def status(self, text, busy=False):
        """Safe from any thread."""
        self.sig_status.emit(text, busy)

    def _set_status(self, text, busy):
        self.lb_status.setText(text)
        self.pb.setVisible(busy)

    def _check_engine(self):
        def work():
            self.sig_engine.emit(self.engine.is_up(timeout=1.0))
        threading.Thread(target=work, daemon=True).start()

    def _set_engine_badge(self, up):
        self.lb_engine.setText(("●  Engine running  :%d" % C.PORT) if up
                               else "○  Engine stopped")
        self.lb_engine.setObjectName("badge_ok" if up else "badge_off")
        self.lb_engine.style().unpolish(self.lb_engine)
        self.lb_engine.style().polish(self.lb_engine)

    def _boot_engine(self):
        self.status("Starting engine...", True)

        def work():
            ok = self.engine.start()
            self.status("Ready." if ok else "Engine not running - see the Info log.", False)
            self.sig_engine.emit(ok)
        threading.Thread(target=work, daemon=True).start()

    def _log_setup(self):
        rows = C.setup_checks(self.settings)
        bad = [r for r in rows if r[2] in (C.FAIL, C.WARN)]
        if not bad:
            self.log("Setup: everything found.")
        for area, name, state, detail, fix in bad:
            self.log("  %s  %s - %s" % ("MISSING" if state == C.FAIL else "CHECK  ",
                                         name, fix or detail))
        C.apply(self.settings)

    def _needs_setup(self):
        essential = {"ComfyUI folder", "ComfyUI's Python", "Blender", "Character (FBX)"}
        return any(r[1] in essential and r[2] == C.FAIL
                   for r in C.setup_checks(self.settings))

    # =====================================================================
    # menus / dialogs
    # =====================================================================
    def open_preferences(self, first_run=False, page=0):
        old_port = C.PORT
        dlg = PreferencesDialog(self.settings, self, first_run=first_run, page=page)
        if dlg.exec() != QDialog.Accepted:
            return
        self._set_rig(self.settings.get("target_rig") or "")
        self._refresh_projects()
        self.log("Preferences saved.")
        self._log_setup()
        if C.PORT != old_port:
            self.log("Engine port changed to %d - restarting the engine." % C.PORT)
            self.engine.stop()
            QTimer.singleShot(2500, self._boot_engine)
        elif not self.engine.is_up():
            QTimer.singleShot(300, self._boot_engine)

    def _show_info(self, on):
        self.info.setVisible(bool(on))
        self.settings["show_info"] = bool(on)

    def _menu_video(self):
        self.ws.setCurrentIndex(1)
        self._pick_video()

    def _open_readme(self):
        if C.README_FILE.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(C.README_FILE)))
        elif C.GITHUB_URL:
            QDesktopServices.openUrl(QUrl(C.GITHUB_URL))

    def _about(self):
        QMessageBox.about(
            self, "About HY Motion Studio",
            "<b>HY Motion Studio %s</b><br><br>"
            "A desktop front end for AI character animation: text to motion "
            "with Tencent HY-Motion, video to motion with GVHMR, retargeted onto "
            "your own character, with hand-off to Blender, Cascadeur and Unity."
            "<br><br>A community project - not affiliated with Tencent, Blender "
            "or Nekki." % C.VERSION)

    def _show_licences(self):
        QMessageBox.information(
            self, "Licences & Credits",
            "HY Motion Studio ships no AI models. Each model you download has its "
            "own licence - please read them:\n\n"
            "• HY-Motion 1.0 (Tencent): Tencent Hunyuan Community Licence. "
            "Its territory excludes the EU, UK and South Korea, and larger "
            "products need a separate licence.\n"
            "• GVHMR and the SMPL-X body model (video capture): research / "
            "non-commercial use only.\n"
            "• Your character FBX: whatever licence it came with.\n\n"
            "Built with Qt for Python (LGPL-3.0), three.js (MIT), Blender (GPL) "
            "and ComfyUI (GPL-3.0).")

    # =====================================================================
    # settings <-> UI
    # =====================================================================
    def _load_settings_into_ui(self):
        s = self.settings
        self.ed_prompt.setPlainText(s["prompt"])
        self.sp_dur.setValue(float(s["duration"]))
        self.sp_seed.setValue(int(s["seed"]))
        self.ed_prompt2.setPlainText(s["prompt2"])
        self.sp_dur2.setValue(float(s["duration2"]))
        self.sp_seed2.setValue(int(s["seed2"]))
        self.sp_dist.setValue(float(s["c2_distance"]))
        self.sp_face.setValue(float(s["c2_facing"]))
        self.sp_delay.setValue(float(s["c2_delay"]))
        self.cb_chars.setCurrentIndex(0 if int(s["characters"]) < 2 else 1)
        self.cb_model.setCurrentText(s["model"])
        self.ck_rand.setChecked(bool(s["randomise"]))
        self.sp_cfg.setValue(float(s["cfg_scale"]))
        for side, key, ck in (("l", "left_hand", "left_cycle"),
                              ("r", "right_hand", "right_cycle")):
            val = s.get(key, "source")
            idx = self.HAND_VALS.index(val) if val in self.HAND_VALS else 0
            getattr(self, "cb_hand_" + side).setCurrentIndex(idx)
            getattr(self, "sp_cycle_" + side).setValue(float(s.get(ck, 0.0)))
        self.cb_quant.setCurrentText(s["quantization"])
        self.ck_offload.setChecked(bool(s["offload_llm"]))
        self.cb_profile.setCurrentText(s.get("profile", "auto"))
        if s["project"] in [self.cb_project.itemText(i)
                            for i in range(self.cb_project.count())]:
            self.cb_project.setCurrentText(s["project"])
        self._project_changed(self.cb_project.currentText())
        self._set_rig(s.get("target_rig") or "")
        self._chars_changed()
        self.cb_view.setCurrentIndex(
            {"both": 0, "character": 1, "skeleton": 2}.get(s.get("view_mode"), 0))
        self.ck_follow.setChecked(bool(s.get("follow", True)))
        self.ck_grid.setChecked(bool(s.get("show_grid", True)))
        self.act_info.setChecked(bool(s.get("show_info", True)))
        self.info.setVisible(bool(s.get("show_info", True)))
        self.cb_cam.setCurrentIndex(1 if s.get("video_moving") else 0)
        self.ws.setCurrentIndex(1 if s.get("source_mode") == "video" else 0)
        self._source_changed()
        vp = s.get("video_path") or ""
        if vp and Path(vp).is_file():
            self._open_video(vp, float(s.get("video_start", 0.0)),
                             float(s.get("video_end", 0.0)))

    def _gather(self):
        s = dict(self.settings)
        s.update({
            "prompt": self.ed_prompt.toPlainText().strip(),
            "duration": self.sp_dur.value(),
            "seed": self.sp_seed.value(),
            "prompt2": self.ed_prompt2.toPlainText().strip(),
            "duration2": self.sp_dur2.value(),
            "seed2": self.sp_seed2.value(),
            "c2_distance": self.sp_dist.value(),
            "c2_facing": self.sp_face.value(),
            "c2_delay": self.sp_delay.value(),
            "characters": 2 if self.cb_chars.currentIndex() == 1 else 1,
            "model": self.cb_model.currentText(),
            "randomise": self.ck_rand.isChecked(),
            "cfg_scale": self.sp_cfg.value(),
            "fingers": "animate",
            "left_hand": self.HAND_VALS[self.cb_hand_l.currentIndex()],
            "right_hand": self.HAND_VALS[self.cb_hand_r.currentIndex()],
            "left_cycle": self.sp_cycle_l.value(),
            "right_cycle": self.sp_cycle_r.value(),
            "quantization": self.cb_quant.currentText(),
            "offload_llm": self.ck_offload.isChecked(),
            "project": self.cb_project.currentText(),
            "profile": self.cb_profile.currentText(),
            "target_rig": self._rig,
            "clip_name": self.ed_clip.text().strip(),
            "source_mode": "video" if self.ws.currentIndex() == 1 else "text",
            "video_path": self._video_info.get("path", self.settings.get("video_path", "")),
            "video_start": self.sp_vstart.value(),
            "video_end": self.sp_vend.value(),
            "video_moving": self.cb_cam.currentIndex() == 1,
            "view_mode": ["both", "character", "skeleton"][self.cb_view.currentIndex()],
            "follow": self.ck_follow.isChecked(),
            "show_grid": self.ck_grid.isChecked(),
            "show_info": self.info.isVisible(),
        })
        return s

    def _project_changed(self, name):
        self.lb_top.setText("Project:  %s" % name if name else "")

    def _refresh_projects(self):
        cur = self.cb_project.currentText()
        self.cb_project.blockSignals(True)
        self.cb_project.clear()
        self.cb_project.addItems(P.list_projects())
        if cur in [self.cb_project.itemText(i) for i in range(self.cb_project.count())]:
            self.cb_project.setCurrentText(cur)
        self.cb_project.blockSignals(False)
        self._project_changed(self.cb_project.currentText())

    # -- workspaces --------------------------------------------------------
    def _video_mode(self):
        return self.ws.currentIndex() == 1

    def _go_label(self):
        return "Make Animation from Video" if self._video_mode() else "Generate Animation"

    def _source_changed(self, *_):
        video = self._video_mode()
        for p in self._text_panels:
            p.setVisible(not video)
        for p in self._video_panels:
            p.setVisible(video)
        if not (self.worker and self.worker.isRunning()):
            self.btn_go.setText(self._go_label())
        if video:
            self._js("hym.clearSlot(1)")

    def _pick_video(self):
        start = self._video_info.get("path") or str(Path.home() / "Downloads")
        f, _ = QFileDialog.getOpenFileName(
            self, "Choose a video", start,
            "Videos (*.mp4 *.mov *.webm *.mkv *.avi *.m4v);;All files (*.*)")
        if f:
            self._open_video(f, 0.0, 0.0)

    def _thumb_path(self):
        import tempfile
        return str(Path(tempfile.gettempdir()) / "hymstudio_video_thumb.jpg")

    def _open_video(self, path, start, end):
        """Read length/fps in the background, then fill the range controls."""
        self.lb_video.setText("Reading " + Path(path).name + " ...")
        self._pending_range = (start, end)
        self._run_probe(path, start)

    def _run_probe(self, path, at):
        if self._probe and self._probe.isRunning():
            self._probe_next = (path, at)
            return
        self._probe_next = None
        self._probe = ProbeWorker(path, self._thumb_path(), at, self)
        self._probe.done.connect(self._on_probe)
        self._probe.start()

    def _on_probe(self, info):
        if info.get("error"):
            self.lb_video.setText("Could not read that video.")
            self.log("ERROR: " + info["error"].splitlines()[0])
        else:
            new = info["path"] != self._video_info.get("path")
            self._video_info = info
            dur = float(info.get("duration") or 0.0)
            self.lb_video.setText("%s\n%.1f s   %.2f fps   %dx%d"
                                  % (Path(info["path"]).name, dur, info["fps"],
                                     info["width"], info["height"]))
            if new:
                s0, s1 = getattr(self, "_pending_range", (0.0, 0.0))
                for sp in (self.sp_vstart, self.sp_vend):
                    sp.blockSignals(True)
                    sp.setRange(0.0, max(dur, 0.1))
                self.sp_vstart.setValue(min(s0, dur))
                # default to the first 15 s - long clips take a while
                self.sp_vend.setValue(s1 if s1 > s0 else min(dur, s0 + 15.0))
                for sp in (self.sp_vstart, self.sp_vend):
                    sp.blockSignals(False)
                self._video_range_changed()
            from PySide6.QtGui import QPixmap
            pm = QPixmap(info.get("thumb", ""))
            if not pm.isNull():
                pm = pm.scaled(362, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lb_thumb.setPixmap(pm)
                # a pixmap label gets squeezed inside the scrolling panel
                # unless its height is pinned
                self.lb_thumb.setFixedHeight(pm.height() + 6)
        nxt = getattr(self, "_probe_next", None)
        if nxt:
            self._run_probe(*nxt)

    def _refresh_thumb(self):
        if self._video_info.get("path"):
            self._run_probe(self._video_info["path"], self.sp_vstart.value())

    def _video_whole(self):
        dur = float(self._video_info.get("duration") or 0.0)
        if dur > 0:
            self.sp_vstart.setValue(0.0)
            self.sp_vend.setValue(dur)
            self._refresh_thumb()

    def _video_range_changed(self, *_):
        length = self.sp_vend.value() - self.sp_vstart.value()
        fps = float(self._video_info.get("fps") or 0.0)
        if not self._video_info.get("path"):
            self.lb_vlen.setText("")
            return
        if length <= 0.2:
            self.lb_vlen.setText("End must be after Start.")
            return
        frames = int(length * fps)
        mins = (frames * 0.6 + 60) / 60.0
        self.lb_vlen.setText("Clip length %.1f s  =  %d frames.   Takes about %s."
                             % (length, frames,
                                ("%.0f min" % mins) if mins >= 1.5 else "a minute"))

    def _chars_changed(self, *_):
        two = self.cb_chars.currentIndex() == 1
        self.tabs.setTabEnabled(1, two)
        self.tabs.setTabVisible(1, two)
        self.stage_box.setVisible(two)
        if not two:
            self.tabs.setCurrentIndex(0)
            self._js("hym.clearSlot(1)")

    def _restage(self, *_):
        """Push C2's staging into the live viewport."""
        self._js("hym.setPlacement(1, 0, %f, %f)"
                 % (self.sp_dist.value(), self.sp_face.value()))
        self._js("hym.setDelay(1, %f)" % self.sp_delay.value())

    def _set_rig(self, path):
        self._rig = str(path or "")
        if not self._rig:
            self.lb_rig.setText("<span style='color:#e0555f'>No character chosen.</span> "
                                "Click Choose...")
        else:
            p = Path(self._rig)
            self.lb_rig.setText("<b>%s</b>%s" % (p.name, "" if p.is_file() else
                                "  <span style='color:#e0555f'>(file not found)</span>"))
            self.lb_rig.setToolTip(str(p))
        self.settings["target_rig"] = self._rig

    def _pick_rig(self):
        start = str(Path(self._rig).parent) if self._rig else (
            str(C.MANNEQUIN_DIR) if C.MANNEQUIN_DIR.is_dir() else str(Path.home()))
        f, _ = QFileDialog.getOpenFileName(self, "Choose a character FBX", start,
                                           "FBX files (*.fbx)")
        if f:
            self._set_rig(str(Path(f)))
            self.settings.save()
            self.log("Character: " + f)

    def _default_rig(self):
        d = C.default_character()
        if d:
            self._set_rig(str(d))
            self.log("Character: " + str(d))
        else:
            QMessageBox.information(
                self, "HY Motion Studio",
                "There is no FBX in the Mannequin folder:\n%s\n\nPut one there, "
                "or click Choose..." % C.MANNEQUIN_DIR)

    # -- presets -------------------------------------------------------
    def _reload_presets(self):
        self.tree.clear()
        data = PR.load()
        for cat in sorted(data):
            top = QTreeWidgetItem([cat])
            fnt = top.font(0)
            fnt.setBold(True)
            top.setFont(0, fnt)
            for name in sorted(data[cat]):
                prompt, dur = data[cat][name]
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.UserRole, (cat, name, prompt, dur))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()

    def _apply_preset(self, item, *_):
        if not item:
            return
        d = item.data(0, Qt.UserRole)
        if not d:
            return
        cat, name, prompt, dur = d
        # Apply to whichever character tab is in front.
        if self.tabs.currentIndex() == 1 and self.tabs.isTabVisible(1):
            self.ed_prompt2.setPlainText(prompt)
            self.sp_dur2.setValue(float(dur))
            self.log(f"Preset -> C2: {cat} / {name}")
        else:
            self.ed_prompt.setPlainText(prompt)
            self.sp_dur.setValue(float(dur))
            if not self.ed_clip.text().strip():
                self.ed_clip.setText(P.safe_name(name))
            self.log(f"Preset -> C1: {cat} / {name}")

    def _save_preset(self):
        two = self.tabs.currentIndex() == 1 and self.tabs.isTabVisible(1)
        prompt = (self.ed_prompt2 if two else self.ed_prompt).toPlainText().strip()
        dur = (self.sp_dur2 if two else self.sp_dur).value()
        if not prompt:
            return
        cats = sorted(PR.load().keys())
        cat, ok = QInputDialog.getItem(self, "Save preset", "Category:",
                                       cats, 0, True)
        if not ok or not cat:
            return
        name, ok = QInputDialog.getText(self, "Save preset", "Name:")
        if not ok or not name.strip():
            return
        PR.save_user(cat, name.strip(), prompt, dur)
        self._reload_presets()
        self.log(f"Saved preset: {cat} / {name.strip()}")

    def _delete_preset(self):
        item = self.tree.currentItem()
        d = item.data(0, Qt.UserRole) if item else None
        if not d:
            return
        cat, name, _, _ = d
        if PR.is_builtin(cat, name):
            QMessageBox.information(self, "HY Motion Studio",
                                    "Built-in presets can't be deleted.")
            return
        if PR.delete_user(cat, name):
            self._reload_presets()
            self.log(f"Deleted preset: {cat} / {name}")

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New project", "Project name:")
        if not ok or not name.strip():
            return
        n = P.safe_name(name)
        P.ensure_project(n)
        self.cb_project.clear()
        self.cb_project.addItems(P.list_projects())
        self.cb_project.setCurrentText(n)
        self.log("Created project: " + n)

    # -- history -------------------------------------------------------
    def _reload_history(self):
        self.lst_hist.clear()
        for e in H.load():
            it = QListWidgetItem(H.label(e))
            it.setToolTip(H.tooltip(e))
            it.setData(Qt.UserRole, e)
            if not e.get("_alive", True):
                it.setForeground(Qt.gray)
            self.lst_hist.addItem(it)

    def _load_history_item(self, item, *_):
        if not item:
            return
        e = item.data(Qt.UserRole)
        if not e or not e.get("glb"):
            return
        if not Path(e["glb"]).is_file():
            QMessageBox.information(self, "HY Motion Studio",
                                    "That clip's preview file is gone:\n"
                                    + e["glb"])
            return
        self.last = {
            "project": e.get("project", ""), "stem": e.get("stem", "clip"),
            "two": bool(e.get("glb2")),
            "c1": {"glb": e.get("glb"), "retarget_fbx": e.get("fbx", ""),
                   "source_fbx": e.get("source", ""), "seconds": 0},
        }
        if e.get("glb2"):
            self.last["c2"] = {"glb": e["glb2"],
                               "retarget_fbx": e.get("fbx2", ""),
                               "source_fbx": e.get("source2", ""),
                               "seconds": 0}
        self._show_result_in_viewport(self.last)
        self.log("History: " + H.label(e))

    def _reuse_history_settings(self):
        item = self.lst_hist.currentItem()
        e = item.data(Qt.UserRole) if item else None
        if not e:
            return
        if e.get("kind") == "video":
            self.ws.setCurrentIndex(1)
            self.cb_cam.setCurrentIndex(1 if e.get("moving") else 0)
            if e.get("video") and Path(e["video"]).is_file():
                self._video_info = {}
                self._open_video(e["video"], float(e.get("t0", 0.0)),
                                 float(e.get("t1", 0.0)))
                self.log("Video settings restored from history.")
            else:
                self.log("The original video is no longer at " + str(e.get("video")))
            return
        self.ws.setCurrentIndex(0)
        self.ed_prompt.setPlainText(e.get("prompt", ""))
        self.sp_dur.setValue(float(e.get("duration", 4.0) or 4.0))
        self.sp_seed.setValue(int(e.get("seed", 42) or 42))
        if e.get("prompt2"):
            self.cb_chars.setCurrentIndex(1)
            self.ed_prompt2.setPlainText(e["prompt2"])
            self.sp_dur2.setValue(float(e.get("duration2", 4.0) or 4.0))
            self.sp_seed2.setValue(int(e.get("seed2", 99) or 99))
        else:
            self.cb_chars.setCurrentIndex(0)
        if e.get("fingers"):
            pass
        self.ck_rand.setChecked(False)
        self.log("Settings restored from history (seeds kept).")

    def _tidy_history(self):
        n = H.clear_missing()
        self._reload_history()
        self.log("History tidied - %d entries kept." % n)

    # -- viewport ------------------------------------------------------
    def _viewport_ready(self, ok):
        if not ok:
            self.log("Viewport page failed to load.")

    def _on_viewport_live(self):
        """First poll after the ES modules have executed.

        loadFinished fires before the module graph has run, so anything that
        touches window.hym waits for the API to exist rather than for the page
        load to report done.
        """
        self._js("hym.setMode('%s')" % ["both", "character", "skeleton"][
            self.cb_view.currentIndex()])
        self._js("hym.setGrid(%s)" % ("true" if self.ck_grid.isChecked() else "false"))
        self._js("hym.setFollow(%s)" % ("true" if self.ck_follow.isChecked() else "false"))
        last = C.VIEWER_DIR / "tmp" / "current.glb"
        if last.is_file():
            self._js("hym.load('./tmp/current.glb', 30, 0)")
            self.log("Viewport ready - restored last preview.")
        else:
            self.log("Viewport ready.")

    def _poll_viewport(self):
        self._js("JSON.stringify(window.hym ? window.hym.state() : null)",
                 self._on_state)

    def _on_state(self, raw):
        try:
            st = json.loads(raw) if raw else None
        except Exception:
            return
        if st is None:
            return                      # module graph still executing
        if not self._viewport_live:
            self._viewport_live = True
            self._on_viewport_live()
        if not st.get("ready"):
            return
        frames = int(st.get("frames") or 1)
        fps_clip = float(st.get("clipFps") or 30)
        if self.sl_time.maximum() != frames - 1:
            self.sl_time.setRange(0, max(frames - 1, 0))
        cur = int(round(float(st.get("time", 0)) * fps_clip))
        self._duration = float(st.get("duration") or 0.0)
        if not self._slider_lock:
            self.sl_time.setValue(min(cur, max(frames - 1, 0)))
        self.lb_frame.setText("%d / %d" % (min(cur + 1, frames), frames))
        self.lb_time.setText("%.2f s" % float(st.get("time", 0)))
        self.lb_fps.setText("%d fps" % int(st.get("fps") or 0))
        self.btn_play.setText("❚❚" if st.get("playing") else "▶")

    def _scrub(self, v):
        self._js("hym.setTime(%f)" % (v / 30.0))

    def _jump(self, t):
        self._js("hym.pause()")
        self._js("hym.setTime(%f)" % t)

    def _view_mode(self, idx):
        self._js("hym.setMode('%s')" % ["both", "character", "skeleton"][idx])

    def _publish_glb(self, path, name):
        """Copy a GLB where the viewport's HTTP server can serve it."""
        tmp = C.VIEWER_DIR / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        dst = tmp / name
        shutil.copy2(path, dst)
        return "./tmp/" + name

    def _show_result_in_viewport(self, res):
        url1 = self._publish_glb(res["c1"]["glb"], "current.glb")
        self._js("hym.clearAll()")
        self._js("hym.load('%s', 30, 0)" % url1)
        if res.get("two") and res.get("c2"):
            url2 = self._publish_glb(res["c2"]["glb"], "current2.glb")
            self._js("hym.load('%s', 30, 1)" % url2)
            QTimer.singleShot(900, self._restage)

    # -- actions -------------------------------------------------------
    def on_generate(self):
        if self.worker and self.worker.isRunning():
            if isinstance(self.worker, VideoWorker) and QMessageBox.question(
                    self, "HY Motion Studio",
                    "Stop the video capture?") == QMessageBox.Yes:
                self.worker.cancel()
                self.btn_go.setEnabled(False)
                self.btn_go.setText("Stopping...")
            return
        if self._video_mode():
            self.on_video()
            return
        s = self._gather()
        if not s["prompt"]:
            QMessageBox.warning(self, "HY Motion Studio",
                                "Describe the motion first.")
            return
        if s["characters"] >= 2 and not s["prompt2"]:
            QMessageBox.warning(self, "HY Motion Studio",
                                "Character 2 needs a prompt too.")
            return
        if not Path(s["target_rig"]).is_file():
            QMessageBox.warning(self, "HY Motion Studio",
                                "Preview character not found:\n"
                                + s["target_rig"])
            return
        if s["randomise"]:
            s["seed"] = int.from_bytes(os.urandom(4), "big") % 2147483647
            s["seed2"] = int.from_bytes(os.urandom(4), "big") % 2147483647
            self.sp_seed.setValue(s["seed"])
            self.sp_seed2.setValue(s["seed2"])
        self.settings.update({k: v for k, v in s.items() if k in C.DEFAULTS})
        self.settings.save()

        self.btn_go.setEnabled(False)
        self.btn_go.setText("Generating...")
        self.status("Submitting...", True)
        self.log("\n> C1: " + s["prompt"][:90])
        if s["characters"] >= 2:
            self.log("  C2: " + s["prompt2"][:90])
            self.log("  two characters - each clip is generated separately")

        self.worker = GenerateWorker(self.engine, s, self)
        self.worker.log.connect(self.log)
        self.worker.status.connect(lambda t: self.status(t, True))
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._fail)
        self.worker.start()

    def _done(self, res):
        self.last = res
        s = self._gather()
        self.btn_go.setEnabled(True)
        self.btn_go.setText(self._go_label())
        self.status("Done  -  %s" % Path(res["c1"]["retarget_fbx"]).name, False)
        self.lb_result.setText(
            "%s\n\nProject: %s\n%s\nTotal %.0fs"
            % (Path(res["c1"]["retarget_fbx"]).name,
               Path(res["project"]).name,
               "2 characters" if res.get("two") else "1 character",
               res["seconds"]))
        self.log("Retargeted: " + res["c1"]["retarget_fbx"])
        if res.get("two"):
            self.log("Retargeted: " + res["c2"]["retarget_fbx"])
        self._show_result_in_viewport(res)

        H.add({
            "stem": res["stem"], "project": res["project"],
            "prompt": s["prompt"], "duration": s["duration"], "seed": s["seed"],
            "prompt2": s["prompt2"] if res.get("two") else "",
            "duration2": s["duration2"], "seed2": s["seed2"],
            "model": s["model"], "fingers": s["fingers"],
            "glb": res["c1"]["glb"], "fbx": res["c1"]["retarget_fbx"],
            "source": res["c1"]["source_fbx"],
            "glb2": res.get("c2", {}).get("glb", ""),
            "fbx2": res.get("c2", {}).get("retarget_fbx", ""),
            "source2": res.get("c2", {}).get("source_fbx", ""),
        })
        self._reload_history()

    def _fail(self, msg):
        self.btn_go.setEnabled(True)
        self.btn_go.setText(self._go_label())
        if msg.strip() == "Cancelled.":
            self.status("Stopped.", False)
            self.log("Stopped.")
            return
        self.status("Failed.", False)
        self.log("ERROR: " + msg.splitlines()[0])
        QMessageBox.critical(self, "HY Motion Studio", msg)

    # -- video -> animation ----------------------------------------------
    def on_video(self):
        s = self._gather()
        path = s["video_path"]
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "HY Motion Studio", "Choose a video first.")
            return
        length = s["video_end"] - s["video_start"]
        if length < 0.5:
            QMessageBox.warning(self, "HY Motion Studio",
                                "End must be at least half a second after Start.")
            return
        if not Path(s["target_rig"]).is_file():
            QMessageBox.warning(self, "HY Motion Studio",
                                "Preview character not found:\n" + s["target_rig"])
            return
        if not C.video_ready():
            QMessageBox.warning(
                self, "HY Motion Studio",
                "Video capture is not set up yet.\n\nIt needs the "
                "ComfyUI-MotionCapture nodes and the SMPL-X body model - see "
                "Help > Setup Check, and the README.")
            return
        if length > 30.0:
            fps = float(self._video_info.get("fps") or 30.0)
            mins = (length * fps * 0.6 + 60) / 60.0
            if QMessageBox.question(
                    self, "HY Motion Studio",
                    "That is a long clip (%.0f s). It will take about %.0f minutes.\n"
                    "Go ahead?" % (length, mins)) != QMessageBox.Yes:
                return
        self.settings.update({k: v for k, v in s.items() if k in C.DEFAULTS})
        self.settings.save()

        self.btn_go.setText("Cancel")
        self.status("Starting video capture...", True)
        self.log("\n> VIDEO: %s  %.1f-%.1f s  (%s camera)"
                 % (Path(path).name, s["video_start"], s["video_end"],
                    "moving" if s["video_moving"] else "fixed"))
        self.worker = VideoWorker(self.engine, s, self)
        self.worker.log.connect(self.log)
        self.worker.status.connect(lambda t: self.status(t, True))
        self.worker.finished_ok.connect(self._video_done)
        self.worker.failed.connect(self._fail)
        self.worker.start()

    def _video_done(self, res):
        self.last = res
        self.btn_go.setEnabled(True)
        self.btn_go.setText(self._go_label())
        name = Path(res["c1"]["retarget_fbx"]).name
        self.status("Done  -  %s" % name, False)
        self.lb_result.setText(
            "%s\n\nProject: %s\nFrom video: %s  (%.1f-%.1f s)\nTotal %.0fs\n\n"
            "Previs only - keyframe over it before shipping."
            % (name, Path(res["project"]).name, Path(res["video"]).name,
               res["t0"], res["t1"], res["seconds"]))
        self.log("Retargeted: " + res["c1"]["retarget_fbx"])
        self.log("Person-tracking check sheet: " + res.get("mask_check", ""))
        self._show_result_in_viewport(res)
        H.add({
            "kind": "video", "stem": res["stem"], "project": res["project"],
            "prompt": "VIDEO: %s  %.1f-%.1f s" % (Path(res["video"]).name,
                                                   res["t0"], res["t1"]),
            "duration": res["t1"] - res["t0"], "seed": 0,
            "prompt2": "", "duration2": 0, "seed2": 0,
            "model": "GVHMR video capture (previs only)", "fingers": "animate",
            "video": res["video"], "t0": res["t0"], "t1": res["t1"],
            "moving": res["moving"],
            "glb": res["c1"]["glb"], "fbx": res["c1"]["retarget_fbx"],
            "source": res["c1"]["source_fbx"],
            "glb2": "", "fbx2": "", "source2": "",
        })
        self._reload_history()

    # -- pipeline buttons ---------------------------------------------
    def _need_result(self):
        if not self.last:
            QMessageBox.information(self, "HY Motion Studio",
                                    "Generate a clip first.")
            return False
        return True

    def _pick_actor_fbx(self, what):
        """With two characters, ask which one the action applies to."""
        if not self.last.get("two"):
            return self.last["c1"]["retarget_fbx"]
        who, ok = QInputDialog.getItem(
            self, "HY Motion Studio", "Which character to %s?" % what,
            ["Character 1", "Character 2"], 0, False)
        if not ok:
            return None
        return self.last["c1" if who.endswith("1") else "c2"]["retarget_fbx"]

    def on_open_blender(self):
        if not self._need_result():
            return
        fbx = self._pick_actor_fbx("open")
        if not fbx:
            return
        try:
            exe = self.settings.blender_exe
            launcher = exe.parent / "blender-launcher.exe" if exe else None
            P.open_in_blender(
                launcher if (launcher and launcher.is_file()) else exe,
                fbx, self.log)
        except Exception as e:
            QMessageBox.critical(self, "HY Motion Studio", str(e))

    def on_export_blender(self):
        if not self._need_result():
            return
        src = self._pick_actor_fbx("export")
        if not src:
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Export FBX",
            str(Path(self.last["project"]) / "Exports"
                / (Path(src).stem + "_final.fbx")),
            "FBX files (*.fbx)")
        if not out:
            return
        try:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            self.log("Exported: " + out)
            self.status("Exported " + Path(out).name)
        except Exception as e:
            QMessageBox.critical(self, "HY Motion Studio", str(e))

    def on_export_unity(self):
        if not self._need_result():
            return
        proj = Path(self.last["project"])
        src = self.last["c1"]["source_fbx"]
        out = proj / "Exports" / (self.last["stem"] + "_unity.fbx")
        self.status("Preparing Unity FBX...", True)

        def work():
            try:
                P.to_unity(self.settings.blender_exe, src, out,
                           self.ck_strip.isChecked(), self.log)
                self.log("Unity FBX: " + str(out))
                self.status("Unity FBX ready.", False)
            except Exception as e:
                self.log("ERROR: " + str(e).splitlines()[0])
                self.status("Unity export failed.", False)
        threading.Thread(target=work, daemon=True).start()

    def on_cascadeur(self):
        if not self._need_result():
            return
        src = self._pick_actor_fbx("send")
        if not src:
            return
        try:
            proj = Path(self.last["project"])
            dst = proj / "Cascadeur" / (Path(src).stem + "_cascadeur.fbx")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            P.send_to_cascadeur(self.settings.cascadeur_exe, dst, self.log)
            self.status("Opened in Cascadeur.")
        except Exception as e:
            QMessageBox.critical(self, "HY Motion Studio", str(e))

    def on_open_folder(self):
        base = Path(self.last["project"]) if self.last \
            else P.ensure_project(self.cb_project.currentText())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(base)))

    # -- shutdown ------------------------------------------------------
    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(
                    self, "HY Motion Studio",
                    "A generation is still running. Close anyway?") \
                    != QMessageBox.Yes:
                ev.ignore()
                return
            self.worker.cancel()
        try:
            self.settings.update({k: v for k, v in self._gather().items()
                                  if k in C.DEFAULTS})
            self.settings.save()
        except Exception:
            pass
        self.poll.stop()
        self.engine.stop()
        try:
            self.srv.shutdown()
        except Exception:
            pass
        ev.accept()


def main():
    QApplication.setApplicationName("HY Motion Studio")
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    w = Studio()
    w.show()
    sys.exit(app.exec())
