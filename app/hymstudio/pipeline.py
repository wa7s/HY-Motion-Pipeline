"""
Everything that talks to something outside the app:

  * the ComfyUI engine (start / probe / generate)
  * Blender (retarget, Unity conditioning, opening a scene interactively)
  * Cascadeur (hand off a clean FBX)
  * project folders on disk

None of it touches Qt, so it can be unit-driven or reused headless.
"""

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config as C


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
SUBDIRS = ("Input", "Generated", "Blender", "Cascadeur", "Exports")


def project_dir(name):
    return C.PROJECTS_DIR / (name or "Default")


def ensure_project(name):
    """Create Projects/<name>/{Input,Generated,Blender,Cascadeur,Exports}."""
    base = project_dir(name)
    for sub in SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def list_projects():
    if not C.PROJECTS_DIR.is_dir():
        return ["Default"]
    names = sorted(p.name for p in C.PROJECTS_DIR.iterdir() if p.is_dir())
    return names or ["Default"]


def safe_name(text, fallback="motion"):
    keep = "-_ "
    out = "".join(c for c in (text or "") if c.isalnum() or c in keep).strip()
    return (out.replace(" ", "_") or fallback)[:48]


# ---------------------------------------------------------------------------
# ComfyUI engine
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self, log):
        self.proc = None
        self.log = log

    def is_up(self, timeout=1.5):
        try:
            urllib.request.urlopen(C.HOST + "/system_stats", timeout=timeout).read()
            return True
        except Exception:
            return False

    def start(self, wait=180):
        """Blocking start. Returns True once the engine answers.

        With "Start ComfyUI automatically" switched off in Preferences, this
        only connects - for people who run ComfyUI themselves.
        """
        if self.is_up():
            self.log("Engine already running on port %d." % C.PORT)
            return True
        s = C.Settings()
        if not s.get("engine_autostart", True):
            self.log("ComfyUI is not running on port %d, and automatic start is "
                     "off (Edit > Preferences > Engine)." % C.PORT)
            return False
        if not C.COMFY_MAIN.is_file():
            self.log("ComfyUI not found - set its folder in Edit > Preferences.")
            return False
        if not C.COMFY_PY.is_file():
            self.log("ComfyUI's python.exe not found - set it in Edit > Preferences.")
            return False
        self.log("Starting engine...")
        extra = str(s.get("engine_args") or "").split()
        self.proc = subprocess.Popen(
            [str(C.COMFY_PY), "-s", str(C.COMFY_MAIN),
             "--port", str(C.PORT), "--listen", "127.0.0.1",
             "--disable-auto-launch"] + extra,
            cwd=str(C.ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=C.CREATE_NO_WINDOW)
        for _ in range(wait):
            if self.is_up():
                self.log("Engine ready.")
                return True
            if self.proc.poll() is not None:
                self.log("Engine exited during startup.")
                return False
            time.sleep(1)
        self.log("Engine did not start within %ds." % wait)
        return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


def build_workflow(s, prefix):
    """s is a dict-like of settings."""
    return {
        "1": {"class_type": "HYMotionLoadLLM",
              "inputs": {"model_name": "Qwen3-8B-bnb-4bit",
                         "quantization": s["quantization"],
                         "offload_to_cpu": bool(s["offload_llm"])}},
        "2": {"class_type": "HYMotionLoadNetwork",
              "inputs": {"model_name": s["model"]}},
        "3": {"class_type": "HYMotionEncodeText",
              "inputs": {"llm": ["1", 0], "text": s["prompt"]}},
        "4": {"class_type": "HYMotionGenerate",
              "inputs": {"network": ["2", 0], "conditioning": ["3", 0],
                         "duration": float(s["duration"]),
                         "seed": int(s["seed"]),
                         "cfg_scale": float(s["cfg_scale"]),
                         "num_samples": int(s["num_samples"])}},
        "6": {"class_type": "HYMotionExportFBX",
              "inputs": {"motion_data": ["4", 0], "output_dir": "hymotion_fbx",
                         "filename_prefix": prefix, "custom_fbx_path": "",
                         "yaw_offset": 0.0, "scale": 0.0}},
        "7": {"class_type": "HYMotionSaveNPZ",
              "inputs": {"motion_data": ["4", 0], "output_dir": "hymotion_npz",
                         "filename_prefix": prefix}},
    }


def submit(workflow):
    req = urllib.request.Request(
        C.HOST + "/prompt", data=json.dumps({"prompt": workflow}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(_pretty_http(e.read().decode()))


def _pretty_http(body):
    try:
        d = json.loads(body)
        err = d.get("error", {})
        msg = err.get("message", "")
        det = err.get("details", "")
        extra = ""
        for node, info in (d.get("node_errors") or {}).items():
            for e in info.get("errors", []):
                extra += f"\n  {node}: {e.get('message')} {e.get('details', '')}"
        return (msg + " " + det + extra).strip() or body[:800]
    except Exception:
        return body[:800]


def readable_error(messages):
    for name, payload in messages:
        if name == "execution_error" and isinstance(payload, dict):
            msg = payload.get("exception_message", "")
            if "out of memory" in msg.lower():
                return ("Ran out of video memory.\n\n"
                        "Try a shorter clip, switch the model to "
                        "HY-Motion-1.0-Lite, enable 'Offload text encoder to "
                        "CPU', or close other GPU applications.")
            return f"{payload.get('node_type', '?')}: {msg}"
    return "The engine reported an error."


def wait_for(prompt_id, tick, cancelled, limit=1800):
    t0 = time.time()
    while time.time() - t0 < limit:
        if cancelled():
            raise RuntimeError("Cancelled.")
        try:
            h = json.loads(urllib.request.urlopen(
                C.HOST + "/history/" + prompt_id, timeout=10).read())
        except Exception:
            h = {}
        if prompt_id in h:
            st = h[prompt_id].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(readable_error(st.get("messages", [])))
            return time.time() - t0
        tick(time.time() - t0)
        time.sleep(1)
    raise RuntimeError("Timed out after 30 minutes.")


def newest(folder, ext, after_ts=0.0):
    folder = Path(folder)
    if not folder.is_dir():
        return None
    f = [p for p in folder.glob("*" + ext) if p.stat().st_mtime >= after_ts - 2]
    return max(f, key=lambda p: p.stat().st_mtime) if f else None


# ---------------------------------------------------------------------------
# Blender
# ---------------------------------------------------------------------------
def _run_blender(blender, args, log, timeout=1800):
    cmd = [str(blender), "-b", "--factory-startup"] + args
    r = subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=C.CREATE_NO_WINDOW, timeout=timeout)
    for line in r.stdout.splitlines():
        if ("[retarget]" in line or "[hymotion]" in line or "[warn]" in line
                or "[gvhmr]" in line):
            log("   " + line.split("]", 1)[-1].strip())
    return r


def retarget(blender, source_fbx, target_fbx, out_fbx, out_glb, profile, fps,
             log, fingers="animate", offset=(0.0, 0.0, 0.0), yaw=0.0,
             hands=None):
    """Drive the character rig with the generated motion. Returns (fbx, glb).

    `fingers="rest"` leaves the hands in the target rig's own pose, which is
    what you want: HY-Motion's finger channels are unconstrained and make the
    hands look tangled. `offset`/`yaw` stage the actor for two-character shots.
    """
    if not blender:
        raise RuntimeError("Blender was not found.\n\n"
                           "Set blender.exe in Edit > Preferences > File Paths.")
    if not target_fbx or not Path(target_fbx).is_file():
        raise RuntimeError("No character chosen.\n\nChoose your character's FBX in "
                           "Edit > Preferences > File Paths (or Character in the "
                           "right-hand panel).")
    args = ["--python", str(C.RETARGET_SCRIPT), "--",
            "--source", str(source_fbx), "--target", str(target_fbx),
            "--fps", str(int(fps)), "--profile", profile,
            "--fingers", fingers,
            "--offset", "%f,%f,%f" % tuple(offset),
            "--yaw", "%f" % float(yaw)]
    h = hands or {}
    args += ["--left-hand", str(h.get("left_hand", "source")),
             "--right-hand", str(h.get("right_hand", "source")),
             "--left-hand-cycle", "%f" % float(h.get("left_cycle", 0.0)),
             "--right-hand-cycle", "%f" % float(h.get("right_cycle", 0.0))]
    if out_fbx:
        args += ["--out-fbx", str(out_fbx)]
    if out_glb:
        args += ["--out-glb", str(out_glb)]
    r = _run_blender(blender, args, log)
    ok = (not out_glb or Path(out_glb).is_file()) and \
         (not out_fbx or Path(out_fbx).is_file())
    if not ok:
        tail = (r.stdout or r.stderr or "")[-1200:]
        raise RuntimeError("Retargeting failed.\n\n" + tail)
    return out_fbx, out_glb


def to_unity(blender, src_fbx, out_fbx, strip_fingers, log):
    if not blender:
        raise RuntimeError("Blender was not found. Set its path in Edit > Preferences.")
    args = ["--python", str(C.UNITY_SCRIPT), "--",
            "--in", str(src_fbx), "--out", str(out_fbx)]
    if strip_fingers:
        args.append("--strip-fingers")
    _run_blender(blender, args, log)
    if not Path(out_fbx).is_file():
        raise RuntimeError("Unity export failed.")
    return out_fbx


def open_in_blender(blender_launcher, fbx, log):
    """Open Blender interactively with the FBX already imported."""
    if not blender_launcher:
        raise RuntimeError("Blender was not found. Set its path in Preferences.")
    import tempfile
    boot = Path(tempfile.gettempdir()) / "hymstudio_open_fbx.py"
    boot.write_text(
        "import bpy, sys\n"
        "bpy.ops.wm.read_homefile(use_empty=True)\n"
        "bpy.ops.import_scene.fbx(filepath=r'''%s''', use_anim=True,\n"
        "    automatic_bone_orientation=False, ignore_leaf_bones=False)\n"
        "for a in bpy.context.screen.areas:\n"
        "    if a.type == 'VIEW_3D':\n"
        "        for s in a.spaces:\n"
        "            if s.type == 'VIEW_3D': s.shading.type = 'SOLID'\n"
        % str(fbx), "utf-8")
    subprocess.Popen([str(blender_launcher), "--python", str(boot)],
                     creationflags=C.CREATE_NO_WINDOW)
    log("Opened in Blender: " + Path(fbx).name)


def send_to_cascadeur(cascadeur, fbx, log):
    """Cascadeur takes a file path on the command line."""
    if not cascadeur:
        raise RuntimeError(
            "Cascadeur was not found. Set its path in Edit > Preferences.")
    if not Path(fbx).is_file():
        raise RuntimeError("Nothing to send - generate a clip first.")
    subprocess.Popen([str(cascadeur), str(fbx)],
                     creationflags=C.CREATE_NO_WINDOW)
    log("Sent to Cascadeur: " + Path(fbx).name)


def copy_into(src, dest_dir, new_stem=None):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    dst = dest_dir / ((new_stem + src.suffix) if new_stem else src.name)
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Video -> motion (GVHMR). Previs only: GVHMR and the SMPL-X body model are
# research / non-commercial licences.
# ---------------------------------------------------------------------------
def _run_helper(script, args, log=None, timeout=3600):
    """Run one of the video/ helper scripts in ComfyUI's embedded Python.

    Returns (returncode, result_dict, output). The scripts print a single
    'RESULT {json}' line for the app to read.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([str(C.COMFY_PY), "-s", str(C.VIDEO_DIR / script)]
                       + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=str(C.ROOT),
                       creationflags=C.CREATE_NO_WINDOW, timeout=timeout)
    res = {}
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT "):
            try:
                res = json.loads(line[7:])
            except Exception:
                pass
        elif log and line.strip() and not line.startswith("wrote "):
            log("   " + line.strip())
    return r.returncode, res, (r.stdout or "") + (r.stderr or "")


def probe_video(path, thumb=None, at=0.0):
    """Length / fps / size of a video, and optionally one frame as a JPEG."""
    args = [path] + ([thumb, "%.3f" % float(at)] if thumb else [])
    code, res, out = _run_helper("probe.py", args, timeout=120)
    if code != 0 or not res:
        raise RuntimeError("Could not read that video.\n\n" + out[-800:])
    return res


def trim_video(src, dst, t0, t1, log):
    code, res, out = _run_helper("vid_trim.py", [src, dst, "%.3f" % t0, "%.3f" % t1],
                                 log, timeout=1800)
    if code != 0 or not res.get("frames"):
        raise RuntimeError("Could not cut that part of the video.\n\n" + out[-800:])
    return res


def person_mask(src, dst, sheet, log):
    code, res, out = _run_helper("make_mask.py", [src, dst, sheet], log, timeout=3600)
    if code == 3:
        raise RuntimeError("No person was found in that part of the video.\n\n"
                           "Choose a clip where the whole body is in view.")
    if code != 0 or not res:
        raise RuntimeError("Finding the person failed.\n\n" + out[-800:])
    return res


def free_engine_memory(wait=4.0):
    """Ask the engine to drop its cached models (HY-Motion holds ~11 GB).

    Motion capture runs in its own process and needs its own share of the
    card, so the two cannot both be resident on 16 GB. The next text
    generation simply reloads HY-Motion.
    """
    req = urllib.request.Request(
        C.HOST + "/free", data=json.dumps(
            {"unload_models": True, "free_memory": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        return False
    time.sleep(wait)
    return True


def interrupt_engine():
    try:
        urllib.request.urlopen(urllib.request.Request(
            C.HOST + "/interrupt", data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=5).read()
    except Exception:
        pass


def gvhmr_workflow(clip_name, mask_name, moving):
    """clip_name / mask_name are files directly inside ComfyUI/input."""
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": clip_name}},
        "2": {"class_type": "LoadVideo", "inputs": {"file": mask_name}},
        "3": {"class_type": "LoadGVHMRModels",
              "inputs": {"model_path_override": "", "precision": "auto",
                         "attention": "auto", "load_dpvo": False}},
        "4": {"class_type": "GVHMRInference",
              "inputs": {"video": ["1", 0], "video_mask": ["2", 0],
                         "config": ["3", 0], "moving_camera": bool(moving),
                         "focal_length_mm": 0, "bbox_scale": 1.2,
                         "vo_method": "simple_vo", "vo_scale": 0.5,
                         "vo_step": 8, "chunk_size": 16}},
        # an output node is required or the engine will not run the graph;
        # it also hands back the path of the file GVHMR wrote
        "6": {"class_type": "PreviewAny", "inputs": {"source": ["4", 0]}},
    }


def gvhmr_result(prompt_id, after_ts):
    """Path of the SMPL parameter file a finished GVHMR job wrote."""
    try:
        h = json.loads(urllib.request.urlopen(
            C.HOST + "/history/" + prompt_id, timeout=10).read())
        text = h[prompt_id]["outputs"]["6"]["text"]
        p = Path(text[0] if isinstance(text, list) else text)
        if p.suffix == ".npz" and p.is_file():
            return p
    except Exception:
        pass
    f = [p for p in C.COMFY_OUT.glob("smpl_params*.npz")
         if p.stat().st_mtime >= after_ts - 2]
    return max(f, key=lambda p: p.stat().st_mtime) if f else None


def gvhmr_to_fbx(blender, npz, out_fbx, src_fps, log):
    """GVHMR parameters -> an FBX shaped like HY-Motion's, for the retarget."""
    if not blender:
        raise RuntimeError("Blender was not found. Set its path in Edit > Preferences.")
    if not C.SMPLX_NEUTRAL.is_file():
        raise RuntimeError("The SMPL-X body model is missing:\n" + str(C.SMPLX_NEUTRAL))
    args = ["--python", str(C.BRIDGE_SCRIPT), "--",
            "--npz", str(npz), "--smplx", str(C.SMPLX_NEUTRAL),
            "--out", str(out_fbx), "--src-fps", "%.4f" % float(src_fps),
            "--fps", "30"]
    r = _run_blender(blender, args, log)
    if not Path(out_fbx).is_file():
        raise RuntimeError("Building the skeleton from the capture failed.\n\n"
                           + (r.stdout or r.stderr or "")[-1200:])
    return out_fbx

# ---------------------------------------------------------------------------
# Generation sanity
# ---------------------------------------------------------------------------
SMPLH_ORDER = [
    "Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee", "Spine2",
    "L_Ankle", "R_Ankle", "Spine3", "L_Foot", "R_Foot", "Neck", "L_Collar",
    "R_Collar", "Head", "L_Shoulder", "R_Shoulder", "L_Elbow", "R_Elbow",
    "L_Wrist", "R_Wrist",
]


def heading_check(npz_path):
    """Does the clip travel the way it faces?

    HY-Motion sometimes returns a backwards walk for a 'walks forward' prompt -
    the feet are planted correctly, it just steps the wrong way. That is a
    generation outcome, not a pipeline fault, and the only cure is a different
    seed. Catching it here means it shows up in the log rather than being
    discovered in the viewport.

    Returns (ok, message). ok is True when there is nothing to report.
    """
    try:
        import numpy as np
    except Exception:
        return True, ""
    try:
        d = np.load(str(npz_path))
        kp, tr = d["keypoints3d"], d["transl"]
    except Exception:
        return True, ""
    if len(kp) < 2:
        return True, ""
    idx = {n: k for k, n in enumerate(SMPLH_ORDER)}

    def unit(v):
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-9 else v

    up = unit(kp[0, idx["Spine3"]] - kp[0, idx["Pelvis"]])
    toe = ((kp[0, idx["L_Foot"]] - kp[0, idx["L_Ankle"]])
           + (kp[0, idx["R_Foot"]] - kp[0, idx["R_Ankle"]]))
    toe = unit(toe - up * float(np.dot(toe, up)))
    travel = tr[-1] - tr[0]
    travel = travel - up * float(np.dot(travel, up))
    dist = float(np.linalg.norm(travel))
    if dist < 0.25:
        return True, ""                      # in-place clip, nothing to judge
    d_fwd = float(np.dot(unit(travel), toe))
    if d_fwd < -0.5:
        return False, ("This clip walks BACKWARDS - it travels %.2f m opposite "
                       "to the way it is facing. The feet are planted "
                       "correctly, so it is what the model generated, not a "
                       "retargeting fault. Re-roll the seed." % dist)
    if d_fwd < 0.3:
        return False, ("This clip travels mostly sideways relative to its "
                       "facing (%.2f m). Re-roll the seed if that is not "
                       "wanted." % dist)
    return True, ""
