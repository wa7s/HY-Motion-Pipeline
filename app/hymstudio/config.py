"""Paths, tool discovery and persisted settings for HY Motion Studio.

Nothing here assumes a particular machine. Every external location - ComfyUI,
its Python, Blender, Cascadeur, the character, the projects folder - comes
from Preferences, and anything left blank is auto-detected. apply() turns the
saved settings into the module-level paths the rest of the app reads, and is
called again whenever Preferences are saved.
"""

import glob
import json
import os
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Where the app itself lives
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
    APP_DIR = BUNDLE_DIR                       # bundled viewer lives here
    # The app's home is the first folder above the exe holding the Blender
    # scripts (the repository layout). A bare exe folder also works: the
    # scripts are bundled inside it as a fallback.
    PIPELINE_DIR = next((p for p in (EXE_DIR, *EXE_DIR.parents)
                         if (p / "blender" / "hym_retarget.py").is_file()), EXE_DIR)
else:
    APP_DIR = Path(__file__).resolve().parent.parent       # .../app
    BUNDLE_DIR = APP_DIR
    PIPELINE_DIR = APP_DIR.parent                          # repository root


def _scripts(sub):
    d = PIPELINE_DIR / sub
    if d.is_dir():
        return d
    b = BUNDLE_DIR / sub
    return b if b.is_dir() else d


BLENDER_DIR = _scripts("blender")
VIDEO_DIR = _scripts("video")
RETARGET_SCRIPT = BLENDER_DIR / "hym_retarget.py"
UNITY_SCRIPT = BLENDER_DIR / "hymotion_to_unity.py"
BRIDGE_SCRIPT = BLENDER_DIR / "gvhmr_to_smplh_fbx.py"
VIEWER_DIR = APP_DIR / "viewer"
MANNEQUIN_DIR = (PIPELINE_DIR / "Mannequin"
                 if any((PIPELINE_DIR / "Mannequin").glob("*.fbx"))
                 else BUNDLE_DIR / "Mannequin")
PRESETS_FILE = PIPELINE_DIR / "presets.json"
SETTINGS_FILE = PIPELINE_DIR / "settings.json"
README_FILE = next((p for p in (PIPELINE_DIR / "README.md", BUNDLE_DIR / "README.md")
                    if p.is_file()), PIPELINE_DIR / "README.md")
CREATE_NO_WINDOW = 0x08000000

VERSION = "1.0.0"
GITHUB_URL = ""          # set to the repository URL when published; Help menu hides it if empty


def default_character():
    """A character dropped into Mannequin/ is picked up automatically.

    The user's own files win over the bundled CC0 mannequins (Base_*).
    """
    if MANNEQUIN_DIR.is_dir():
        fbx = sorted(MANNEQUIN_DIR.glob("*.fbx"),
                     key=lambda p: (p.name.startswith("Base_"), p.name.lower()))
        if fbx:
            return fbx[0]
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def is_comfy_dir(p):
    p = Path(p)
    return (p / "main.py").is_file() and (p / "comfy").is_dir()


def normalise_comfy_dir(p):
    """Accept either the ComfyUI folder or a portable install's root."""
    if not p:
        return None
    p = Path(p)
    if is_comfy_dir(p):
        return p
    if is_comfy_dir(p / "ComfyUI"):
        return p / "ComfyUI"
    return None


def find_comfy_dir():
    here = [PIPELINE_DIR, *PIPELINE_DIR.parents]
    home = Path.home()
    common = [Path(d) / n for d in ("C:\\", "D:\\", "E:\\", str(home), str(home / "Desktop"),
                                     str(home / "Documents"), str(home / "Downloads"))
              for n in ("ComfyUI_windows_portable", "ComfyUI")]
    for c in here + common:
        d = normalise_comfy_dir(c)
        if d:
            return d
    return None


def find_comfy_python(comfy_dir):
    if not comfy_dir:
        return None
    comfy_dir = Path(comfy_dir)
    for c in (comfy_dir.parent / "python_embeded" / "python.exe",   # portable
              comfy_dir / "venv" / "Scripts" / "python.exe",
              comfy_dir / ".venv" / "Scripts" / "python.exe",
              comfy_dir.parent / "venv" / "Scripts" / "python.exe",
              comfy_dir.parent / ".venv" / "Scripts" / "python.exe"):
        if c.is_file():
            return c
    return None


def _version_key(path):
    m = re.search(r"(\d+)\.(\d+)", str(path))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def find_blender():
    hits = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        hits += glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe"))
        hits += glob.glob(os.path.join(base, "Steam", "steamapps", "common", "Blender",
                                       "blender.exe"))
    hits = sorted(hits, key=_version_key, reverse=True)
    if hits:
        return Path(hits[0])
    w = shutil.which("blender")
    return Path(w) if w else None


def find_cascadeur():
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
        for c in sorted(glob.glob(os.path.join(base, "Cascadeur*", "cascadeur.exe")),
                        reverse=True):
            return Path(c)
    return None


def _file(p):
    if p:
        p = Path(p)
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DEFAULTS = {
    "prompt": "A person runs forward three steps, plants the left foot, and "
              "throws a heavy right hook punch, then recovers to a fighting stance.",
    "duration": 4.0,
    "model": "HY-Motion-1.0",
    "seed": 42,
    "randomise": True,
    "cfg_scale": 5.0,
    "num_samples": 1,
    "quantization": "bnb-4bit",
    "offload_llm": False,
    "project": "Default",
    "target_rig": "",
    "profile": "auto",
    # --- locations (blank = auto-detect) ---
    "comfy_dir": "",
    "comfy_python": "",
    "blender": "",
    "cascadeur": "",
    "projects_dir": "",
    # --- engine ---
    "engine_port": 8189,             # 8189 never collides with a normal 8188 ComfyUI
    "engine_autostart": True,
    "engine_args": "",
    "setup_done": False,
    # --- interface ---
    "view_mode": "both",
    "show_grid": True,
    "follow": True,
    "show_info": True,
    "collapsed": {},
    # Hands default to ANIMATED. The alternative - parking them in the target
    # rig's rest pose - reads far worse on most rigs, whose rest hand is flat.
    "fingers": "animate",
    # Neither HY-Motion nor video capture produces finger motion, so the hands
    # are driven directly.
    "left_hand": "source",
    "right_hand": "source",
    "left_cycle": 0.0,
    "right_cycle": 0.0,
    # Two-character shots are staged from two separate single-actor clips.
    "characters": 1,
    "prompt2": "A person is struck, falls backwards to the floor, then clutches "
               "their head and rolls in pain.",
    "duration2": 4.0,
    "seed2": 99,
    "c2_distance": 1.4,
    "c2_facing": 180.0,
    "c2_delay": 0.6,
    # "text" = HY-Motion from a prompt, "video" = motion capture from a clip.
    "source_mode": "text",
    "video_path": "",
    "video_start": 0.0,
    "video_end": 0.0,
    "video_moving": False,
}


class Settings(dict):
    """Tiny JSON-backed settings store."""

    def __init__(self):
        super().__init__(DEFAULTS)
        self.load()

    def load(self):
        try:
            if SETTINGS_FILE.is_file():
                data = json.loads(SETTINGS_FILE.read_text("utf-8"))
                if isinstance(data, dict):
                    self.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception:
            pass          # a corrupt settings file must never block startup
        if not self.get("target_rig"):
            d = default_character()
            if d:
                self["target_rig"] = str(d)

    def save(self):
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(dict(self), indent=2), "utf-8")
        except Exception:
            pass

    @property
    def blender_exe(self):
        return _file(self.get("blender")) or find_blender()

    @property
    def cascadeur_exe(self):
        return _file(self.get("cascadeur")) or find_cascadeur()


# ---------------------------------------------------------------------------
# Runtime paths - module globals the rest of the app reads as C.<NAME>
# ---------------------------------------------------------------------------
COMFY_DIR = None
ROOT = PIPELINE_DIR
COMFY_PY = Path("python.exe")
COMFY_MAIN = Path("main.py")
COMFY_OUT = COMFY_IN = OUT_FBX_DIR = OUT_NPZ_DIR = Path(".")
MOCAP_NODE_DIR = SMPLX_NEUTRAL = Path(".")
PROJECTS_DIR = PIPELINE_DIR / "Projects"
PORT = 8189
HOST = f"http://127.0.0.1:{PORT}"


def apply(s):
    """Resolve the saved settings into concrete paths."""
    g = globals()
    comfy = normalise_comfy_dir(s.get("comfy_dir")) or find_comfy_dir()
    g["COMFY_DIR"] = comfy
    base = comfy or PIPELINE_DIR
    g["ROOT"] = comfy.parent if comfy else PIPELINE_DIR
    g["COMFY_PY"] = (_file(s.get("comfy_python")) or find_comfy_python(comfy)
                     or Path("python.exe"))
    g["COMFY_MAIN"] = base / "main.py"
    g["COMFY_OUT"] = base / "output"
    g["COMFY_IN"] = base / "input"
    g["OUT_FBX_DIR"] = base / "output" / "hymotion_fbx"
    g["OUT_NPZ_DIR"] = base / "output" / "hymotion_npz"
    g["MOCAP_NODE_DIR"] = base / "custom_nodes" / "ComfyUI-MotionCapture"
    g["SMPLX_NEUTRAL"] = (base / "models" / "motion_capture" / "body_models"
                          / "smplx" / "SMPLX_NEUTRAL.npz")
    pd = s.get("projects_dir")
    g["PROJECTS_DIR"] = Path(pd) if pd else PIPELINE_DIR / "Projects"
    try:
        port = int(s.get("engine_port") or 8189)
    except Exception:
        port = 8189
    g["PORT"] = port
    g["HOST"] = f"http://127.0.0.1:{port}"


def video_ready():
    return (MOCAP_NODE_DIR.is_dir() and SMPLX_NEUTRAL.is_file()
            and BRIDGE_SCRIPT.is_file() and (VIDEO_DIR / "make_mask.py").is_file())


# ---------------------------------------------------------------------------
# Setup check - what a new user is missing, in plain words
# ---------------------------------------------------------------------------
OK, WARN, FAIL, OPTIONAL = "ok", "warn", "fail", "optional"


def setup_checks(s):
    """[(area, name, state, detail, fix)] - read-only, no network."""
    apply(s)
    rows = []
    comfy = COMFY_DIR

    def add(area, name, state, detail, fix=""):
        rows.append((area, name, state, str(detail), fix))

    add("Text to Motion", "ComfyUI folder", OK if comfy else FAIL,
        comfy or "not found",
        "" if comfy else "Install ComfyUI, then set its folder in File Paths.")
    add("Text to Motion", "ComfyUI's Python", OK if COMFY_PY.is_file() else FAIL,
        COMFY_PY if COMFY_PY.is_file() else "not found",
        "" if COMFY_PY.is_file() else
        "Point it at python.exe inside python_embeded (portable) or your venv.")
    if comfy:
        nodes = [p for p in (comfy / "custom_nodes").glob("*") if p.is_dir()
                 and "hy-motion" in p.name.lower().replace("_", "-")]
        add("Text to Motion", "HY-Motion nodes", OK if nodes else FAIL,
            nodes[0].name if nodes else "not installed",
            "" if nodes else "Install jtydhr88/ComfyUI-HY-Motion1 into custom_nodes.")
        ck = comfy / "models" / "HY-Motion" / "ckpts"
        full = (ck / "tencent" / "HY-Motion-1.0" / "latest.ckpt").is_file()
        lite = (ck / "tencent" / "HY-Motion-1.0-Lite" / "latest.ckpt").is_file()
        add("Text to Motion", "HY-Motion model", OK if (full or lite) else FAIL,
            ("HY-Motion-1.0" if full else "") + (" + " if full and lite else "")
            + ("Lite" if lite else "") or "not found",
            "" if (full or lite) else
            "Download tencent/HY-Motion-1.0 into models/HY-Motion/ckpts/tencent.")
        enc = (ck / "Qwen3-8B-bnb-4bit").is_dir()
        add("Text to Motion", "Text encoder (Qwen3-8B 4-bit)", OK if enc else WARN,
            "found" if enc else "not found",
            "" if enc else "Download Qwen3-8B-bnb-4bit into models/HY-Motion/ckpts.")
    b = s.blender_exe if isinstance(s, Settings) else (_file(s.get("blender")) or find_blender())
    add("Both", "Blender", OK if b else FAIL, b or "not found",
        "" if b else "Install Blender 4.2 or newer, or set blender.exe in File Paths.")
    rig = _file(s.get("target_rig"))
    add("Both", "Character (FBX)", OK if rig else FAIL, rig or "none chosen",
        "" if rig else "Choose your character's FBX in File Paths.")
    c = s.cascadeur_exe if isinstance(s, Settings) else _file(s.get("cascadeur"))
    add("Both", "Cascadeur", OK if c else OPTIONAL, c or "not found (optional)")
    if comfy:
        mc = MOCAP_NODE_DIR.is_dir()
        add("Video to Motion", "Motion-capture nodes", OK if mc else OPTIONAL,
            MOCAP_NODE_DIR.name if mc else "not installed (optional)",
            "" if mc else "Install PozzettiAndrea/ComfyUI-MotionCapture for video.")
        sx = SMPLX_NEUTRAL.is_file()
        add("Video to Motion", "SMPL-X body model", OK if sx else OPTIONAL,
            "found" if sx else "not found (optional)",
            "" if sx else "Register at smpl-x.is.tue.mpg.de and place SMPLX_NEUTRAL.npz "
                          "in models/motion_capture/body_models/smplx.")
        toml = MOCAP_NODE_DIR / "comfy-env-root.toml"
        try:
            clash = toml.is_file() and "ComfyUI-HyMotion" in toml.read_text("utf-8") \
                and any("hy-motion1" in p.name.lower() for p in (comfy / "custom_nodes").glob("*"))
        except Exception:
            clash = False
        if clash:
            add("Video to Motion", "Node clash", WARN,
                "ComfyUI-MotionCapture pulls in a second HY-Motion pack",
                "Delete the 'ComfyUI-HyMotion = ...' line from "
                "custom_nodes/ComfyUI-MotionCapture/comfy-env-root.toml.")
    return rows
