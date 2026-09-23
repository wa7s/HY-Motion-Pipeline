"""Generation history - every clip the app has produced, newest first.

Stored next to the projects so it survives rebuilds of the exe. Entries keep
the settings that produced them, so a past clip can be reloaded into the
viewport or used as the starting point for a new generation.
"""

import json
import time
from pathlib import Path

from . import config as C

HISTORY_FILE = C.PIPELINE_DIR / "history.json"
LIMIT = 200


def _load_raw():
    try:
        if HISTORY_FILE.is_file():
            data = json.loads(HISTORY_FILE.read_text("utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def load():
    """Entries whose preview GLB still exists, newest first."""
    out = []
    for e in _load_raw():
        if not isinstance(e, dict):
            continue
        e["_alive"] = bool(e.get("glb") and Path(e["glb"]).is_file())
        out.append(e)
    return out


def add(entry):
    data = _load_raw()
    entry = dict(entry)
    entry.setdefault("when", time.time())
    data.insert(0, entry)
    del data[LIMIT:]
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception:
        pass
    return entry


def clear_missing():
    """Drop entries whose files have been deleted."""
    data = [e for e in _load_raw()
            if e.get("glb") and Path(e["glb"]).is_file()]
    try:
        HISTORY_FILE.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception:
        pass
    return len(data)


def label(e):
    when = time.strftime("%d %b %H:%M", time.localtime(e.get("when", 0)))
    if e.get("kind") == "video" or str(e.get("model", "")).startswith("GVHMR"):
        name = Path(e.get("video") or "").name or e.get("stem", "")
        return "%s   video  %.1fs  %s" % (
            when, float(e.get("duration", 0) or 0), name[:24])
    who = "2ch" if e.get("prompt2") else "1ch"
    return "%s   %s   %.1fs  seed %s" % (
        when, who, float(e.get("duration", 0) or 0), e.get("seed", "?"))


def tooltip(e):
    bits = [e.get("prompt", "")]
    if e.get("prompt2"):
        bits.append("C2: " + e["prompt2"])
    bits.append("")
    bits.append("project: %s" % e.get("project", "?"))
    bits.append("model:   %s" % e.get("model", "?"))
    bits.append("hands:   %s" % e.get("fingers", "?"))
    if not e.get("_alive", True):
        bits.append("")
        bits.append("(preview file missing)")
    return "\n".join(bits)
