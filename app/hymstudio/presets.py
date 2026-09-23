"""Motion preset library - the prompts that actually work, kept in one place.

Prompts are written the way HY-Motion responds best: concrete body mechanics,
a clear sequence, under about thirty words. Durations are tuned per action so
the clip doesn't loiter or get cut off.
"""

import json
from . import config as C

BUILTIN = {
    "Combat": {
        "Punch": (
            "A person steps forward with the left foot and throws a straight "
            "right punch, retracting quickly to guard.", 2.5),
        "Hook punch": (
            "A person plants the left foot, rotates the hips, and throws a "
            "heavy right hook, then recovers to a fighting stance.", 3.0),
        "Kick": (
            "A person shifts weight onto the left leg and delivers a high "
            "right roundhouse kick, then returns to stance.", 3.0),
        "Sword attack": (
            "A person raises a sword overhead with both hands and swings it "
            "down diagonally, then settles into a ready guard.", 3.5),
        "Dodge": (
            "A person ducks sharply to the left, slips under an incoming "
            "strike, and rises back into a fighting stance.", 2.5),
        "Block": (
            "A person raises both forearms to guard the head, absorbs an "
            "impact, and steps back one pace.", 2.5),
        "Knockback": (
            "A person is struck in the chest, staggers backward three steps, "
            "and catches their balance.", 3.0),
    },
    "Movement": {
        "Walk": (
            "A person walks forward at a steady, relaxed pace with natural "
            "arm swing.", 4.0),
        "Run": (
            "A person runs forward at speed with long strides and strong arm "
            "drive.", 3.5),
        "Jump": (
            "A person crouches, jumps straight up, and lands softly with "
            "bent knees.", 2.5),
        "Climb": (
            "A person reaches up with the right hand, pulls their body "
            "upward, and reaches again with the left hand.", 4.0),
        "Crouch walk": (
            "A person moves forward slowly in a low crouch, keeping the "
            "head down.", 4.0),
        "Roll": (
            "A person dives forward into a shoulder roll and comes up onto "
            "one knee.", 2.5),
    },
    "Animation": {
        "Idle": (
            "A person stands still with a relaxed posture, shifting weight "
            "slightly from foot to foot.", 5.0),
        "Combat idle": (
            "A person holds a fighting stance, bouncing lightly on the balls "
            "of the feet with guard raised.", 4.0),
        "Dance": (
            "A person dances rhythmically, stepping side to side and swinging "
            "both arms in time.", 6.0),
        "Gesture": (
            "A person raises the right arm and waves broadly, then lowers it "
            "to their side.", 3.0),
        "Sit down": (
            "A person walks forward two steps, turns, and sits down on a "
            "chair.", 4.5),
        "Victory": (
            "A person raises both fists above the head in celebration, then "
            "lowers them.", 3.0),
    },
}


def load():
    """Built-ins plus anything the user saved, merged."""
    data = {k: dict(v) for k, v in BUILTIN.items()}
    try:
        if C.PRESETS_FILE.is_file():
            user = json.loads(C.PRESETS_FILE.read_text("utf-8"))
            for cat, items in (user or {}).items():
                data.setdefault(cat, {})
                for name, val in items.items():
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        data[cat][name] = (val[0], float(val[1]))
    except Exception:
        pass
    return data


def save_user(category, name, prompt, duration):
    """User presets live in their own file so built-ins can still be updated."""
    user = {}
    try:
        if C.PRESETS_FILE.is_file():
            user = json.loads(C.PRESETS_FILE.read_text("utf-8")) or {}
    except Exception:
        user = {}
    user.setdefault(category, {})[name] = [prompt, float(duration)]
    C.PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    C.PRESETS_FILE.write_text(json.dumps(user, indent=2), "utf-8")


def delete_user(category, name):
    try:
        user = json.loads(C.PRESETS_FILE.read_text("utf-8")) or {}
    except Exception:
        return False
    if category in user and name in user[category]:
        del user[category][name]
        if not user[category]:
            del user[category]
        C.PRESETS_FILE.write_text(json.dumps(user, indent=2), "utf-8")
        return True
    return False


def is_builtin(category, name):
    return name in BUILTIN.get(category, {})
