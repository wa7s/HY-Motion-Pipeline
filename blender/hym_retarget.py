"""
HY-Motion -> target rig retargeting (Blender 5.x headless).

Takes the SMPL-H animation HY-Motion (or the video-capture bridge) produces and
transfers it onto a real character rig - Mixamo, Unreal UE4/UE5, 3ds Max Biped
or a Unity-Humanoid-named rig - then writes an FBX for the DCC pipeline and a
GLB for the app's viewport.

    blender.exe -b --factory-startup --python hym_retarget.py -- \
        --source "hymotion.fbx" \
        --target "character.fbx" \
        --out-fbx "retargeted.fbx" \
        --out-glb "preview.glb" \
        [--profile auto|biped|mixamo|ue5|ue4|unity|smplh] \
        [--fingers rest|animate] \
        [--offset X,Y,Z] [--yaw DEG] \
        [--fps 30] [--keep-source]

Retarget method
---------------
The two rigs' worlds are related by s2t, a pure turn about the vertical taken
from each rig's rest hip line (gravity is never touched).

Per bone pair we copy the source's *change from its own rest pose*, not its
absolute orientation, re-expressed in the target's world:

    delta       = s2t · (R_src_pose · R_src_rest⁻¹) · s2t⁻¹
    R_tgt_pose  = delta · R_tgt_rest

Limbs are then aimed so each child joint lies exactly on the source's
direction (the SMPL rig's bone axes are degenerate, so rotations alone are
not enough). Spine and neck are aimed by their change from rest relative to
the pelvis instead, because skeletons place spine joints very differently.
On a Biped the lower-spine bone also carries the thighs; its twist follows
the source hips.

The result is converted to each target bone's basis rotation analytically,
so no depsgraph round-trip is needed per bone - the whole clip bakes in one
pass.

Checking results: Blender adds one frame of offset on every FBX import, so a
retargeted file re-imported next to its source sits one frame later.

Unmapped target bones (twist bones, Nubs, IK helpers) inherit their parent's
motion and keep their rest offset, so the rig stays coherent.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# Rig profiles.  Keys are SMPL-H joint names (the source); values are the
# corresponding bone on the target rig.
# ---------------------------------------------------------------------------

# 3ds Max Biped (Bip001 ...), as exported by many older game rigs.
# Note the inconsistent prefixes on the finger bones - that is how such files
# come, not a typo. Biped Finger0=thumb, 1=index, 2=middle, 3=ring, 4=pinky.
BIPED = {
    "Pelvis": "Bip001 Pelvis",
    "Spine1": "Bip001 Spine",
    # Biped has only two spine bones, so SMPL's Spine2 is deliberately dropped
    # and Spine3 drives the upper one.
    "Spine3": "Bip001 Spine1",
    "Neck": "Bip001 Neck",
    "Head": "Bip001 Head",
}
for _s, _b in (("L", "L"), ("R", "R")):
    BIPED.update({
        f"{_s}_Collar": f"Bip001 {_b} Clavicle",
        f"{_s}_Shoulder": f"Bip001 {_b} UpperArm",
        f"{_s}_Elbow": f"Bip001 {_b} Forearm",
        f"{_s}_Wrist": f"Bip001 {_b} Hand",
        f"{_s}_Hip": f"Bip001 {_b} Thigh",
        f"{_s}_Knee": f"Bip001 {_b} Calf",
        f"{_s}_Ankle": f"Bip001 {_b} Foot",
        f"{_s}_Foot": f"Bip001 {_b} Toe0",
        # thumb root carries the Bip001 prefix, the rest carry "Bones"
        f"{_s}_Thumb1": f"Bip001 {_b} Finger0",
        f"{_s}_Thumb2": f"Bones {_b} Finger01",
        f"{_s}_Thumb3": f"Bones {_b} Finger02",
    })
    for _i, _digit in enumerate(("Index", "Middle", "Ring", "Pinky"), start=1):
        BIPED[f"{_s}_{_digit}1"] = f"Bones {_b} Finger{_i}"
        BIPED[f"{_s}_{_digit}2"] = f"Bones {_b} Finger{_i}1"
        BIPED[f"{_s}_{_digit}3"] = f"Bones {_b} Finger{_i}2"

# Mixamo. The prefix varies between downloads ("mixamorig:", "mixamorig1:",
# none at all) - resolve_profile() matches on the part after the colon.
# Mixamo's middle spine bone is deliberately left unmapped: it then rides its
# parent rigidly, which keeps the aimed chest joint exact (a separately
# rotated in-between bone would pull it off the aim).
MIXAMO = {
    "Pelvis": "mixamorig:Hips",
    "Spine1": "mixamorig:Spine",
    "Spine3": "mixamorig:Spine2",
    "Neck": "mixamorig:Neck",
    "Head": "mixamorig:Head",
}
for _s, _m in (("L", "Left"), ("R", "Right")):
    MIXAMO.update({
        f"{_s}_Collar": f"mixamorig:{_m}Shoulder",
        f"{_s}_Shoulder": f"mixamorig:{_m}Arm",
        f"{_s}_Elbow": f"mixamorig:{_m}ForeArm",
        f"{_s}_Wrist": f"mixamorig:{_m}Hand",
        f"{_s}_Hip": f"mixamorig:{_m}UpLeg",
        f"{_s}_Knee": f"mixamorig:{_m}Leg",
        f"{_s}_Ankle": f"mixamorig:{_m}Foot",
        f"{_s}_Foot": f"mixamorig:{_m}ToeBase",
    })
    for _digit, _mx in (("Thumb", "HandThumb"), ("Index", "HandIndex"),
                        ("Middle", "HandMiddle"), ("Ring", "HandRing"),
                        ("Pinky", "HandPinky")):
        for _n in (1, 2, 3):
            MIXAMO[f"{_s}_{_digit}{_n}"] = f"mixamorig:{_m}{_mx}{_n}"

# Unity-Humanoid names - what blender/hymotion_to_unity.py emits.
UNITY = {
    "Pelvis": "Hips", "Spine1": "Spine", "Spine2": "Chest",
    "Spine3": "UpperChest", "Neck": "Neck", "Head": "Head",
}
for _s, _u in (("L", "Left"), ("R", "Right")):
    UNITY.update({
        f"{_s}_Collar": f"{_u}Shoulder", f"{_s}_Shoulder": f"{_u}UpperArm",
        f"{_s}_Elbow": f"{_u}LowerArm", f"{_s}_Wrist": f"{_u}Hand",
        f"{_s}_Hip": f"{_u}UpperLeg", f"{_s}_Knee": f"{_u}LowerLeg",
        f"{_s}_Ankle": f"{_u}Foot", f"{_s}_Foot": f"{_u}Toes",
    })
    for _d, _ud in (("Thumb", "Thumb"), ("Index", "Index"),
                    ("Middle", "Middle"), ("Ring", "Ring"),
                    ("Pinky", "Little")):
        for _n, _stage in ((1, "Proximal"), (2, "Intermediate"), (3, "Distal")):
            UNITY[f"{_s}_{_d}{_n}"] = f"{_u}{_ud}{_stage}"

# Unreal Engine skeletons - UE5 Manny/Quinn and the UE4 mannequin, which most
# marketplace characters share. UE5 has five spine and two neck bones; the
# in-between ones stay unmapped for the same reason as Mixamo's.
def _unreal(upper_spine):
    t = {"Pelvis": "pelvis", "Spine1": "spine_01", "Spine3": upper_spine,
         "Neck": "neck_01", "Head": "head"}
    for _s, _u in (("L", "l"), ("R", "r")):
        t.update({
            f"{_s}_Collar": f"clavicle_{_u}", f"{_s}_Shoulder": f"upperarm_{_u}",
            f"{_s}_Elbow": f"lowerarm_{_u}", f"{_s}_Wrist": f"hand_{_u}",
            f"{_s}_Hip": f"thigh_{_u}", f"{_s}_Knee": f"calf_{_u}",
            f"{_s}_Ankle": f"foot_{_u}", f"{_s}_Foot": f"ball_{_u}",
        })
        for _d, _ud in (("Thumb", "thumb"), ("Index", "index"), ("Middle", "middle"),
                        ("Ring", "ring"), ("Pinky", "pinky")):
            for _n in (1, 2, 3):
                t[f"{_s}_{_d}{_n}"] = f"{_ud}_0{_n}_{_u}"
    return t


UE5 = _unreal("spine_05")
UE4 = _unreal("spine_03")

# Identity - target rig is itself SMPL-H.
SMPLH = {k: k for k in list(UNITY.keys())}

# Order matters only for ties: a UE5 rig also has spine_03, so UE5 is tried
# first and keeps the tie.
PROFILES = {"biped": BIPED, "mixamo": MIXAMO, "ue5": UE5, "ue4": UE4,
            "unity": UNITY, "smplh": SMPLH}


def resolve_profile(table, names):
    """Map a profile onto a rig's real bone names.

    Exact names win; otherwise the part after any 'prefix:' is compared
    without case, so 'mixamorig1:Hips', 'Hips' and 'mixamorig:Hips' all match.
    """
    bare = {}
    for n in names:
        bare.setdefault(n.split(":")[-1].lower(), n)
    out = {}
    for s, t in table.items():
        if t in names:
            out[s] = t
        else:
            hit = bare.get(t.split(":")[-1].lower())
            if hit:
                out[s] = hit
    return out

# Bones whose direction can be measured from the source's joint positions:
# (bone, the child joint it should point at). The pelvis is deliberately absent
# - it has no single "direction", and aiming it would swing the whole body.
AIM_CHAIN = [
    ("Spine1", "Spine3"), ("Spine3", "Neck"), ("Neck", "Head"),
]
for _s in ("L", "R"):
    AIM_CHAIN += [
        (f"{_s}_Collar", f"{_s}_Shoulder"),
        (f"{_s}_Shoulder", f"{_s}_Elbow"),
        (f"{_s}_Elbow", f"{_s}_Wrist"),
        # The hand is aimed at the middle-finger base. Without this the hand
        # bone keeps the old orientation transfer's error, so the palm faces
        # the wrong way and the animated fingers hang off it at a strange
        # angle - which reads as "weird hands" even when the arm is right.
        (f"{_s}_Wrist", f"{_s}_Middle1"),
        (f"{_s}_Hip", f"{_s}_Knee"),
        (f"{_s}_Knee", f"{_s}_Ankle"),
        (f"{_s}_Ankle", f"{_s}_Foot"),
    ]

# Aimed bones whose direction is transferred as a change from rest rather than
# copied (see the aim setup in retarget()).
SPINE_REL = {"Spine1", "Spine3", "Neck"}

FINGER_TOKENS = ("Thumb", "Index", "Middle", "Ring", "Pinky")

DIGITS = ("Thumb", "Index", "Middle", "Ring", "Pinky")

# How far each named pose curls each digit, 0 = straight, 1 = fully closed.
HAND_POSES = {
    "open":    dict.fromkeys(DIGITS, 0.0),
    "relaxed": {"Thumb": 0.20, "Index": 0.28, "Middle": 0.32,
                "Ring": 0.36, "Pinky": 0.40},
    "fist":    {"Thumb": 0.75, "Index": 1.00, "Middle": 1.00,
                "Ring": 1.00, "Pinky": 1.00},
    "grip":    dict.fromkeys(DIGITS, 0.60),
    "point":   {"Thumb": 0.45, "Index": 0.00, "Middle": 0.95,
                "Ring": 0.95, "Pinky": 0.95},
}

# Radians of bend at full curl, per joint along the digit. The middle knuckle
# closes hardest on a real hand, and the thumb barely folds at all.
CURL_RAD = (1.05, 1.25, 0.85)
THUMB_SCALE = 0.55


def is_finger(smplh_name):
    return any(t in smplh_name for t in FINGER_TOKENS)


def _rest_pos(obj, name):
    b = obj.data.bones.get(name)
    return (obj.matrix_world @ b.matrix_local).translation if b else None


def detect_profile(arm):
    """Pick the profile whose bone names best match this armature."""
    names = {b.name for b in arm.data.bones}
    best, score, table_best = None, 0, None
    for key, table in PROFILES.items():
        resolved = resolve_profile(table, names)
        if len(resolved) > score:
            best, score, table_best = key, len(resolved), resolved
    if not best or score < 8:
        raise RuntimeError(
            "Could not recognise the character's skeleton. Supported: 3ds Max "
            "Biped, Mixamo, Unreal (UE4/UE5), Unity-Humanoid names. Bones seen: "
            + ", ".join(sorted(names)[:15]))
    print(f"[retarget] profile '{best}' matched {score} bones")
    return table_best, best


# ---------------------------------------------------------------------------
def log(msg):
    print("[retarget] " + str(msg))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="HY-Motion FBX")
    p.add_argument("--target", required=True, help="character FBX to drive")
    p.add_argument("--out-fbx", dest="out_fbx", default="")
    p.add_argument("--out-glb", dest="out_glb", default="")
    p.add_argument("--profile", default="auto",
                   choices=["auto"] + list(PROFILES))
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--keep-source", action="store_true",
                   help="leave the SMPL-H rig in the scene (debugging)")
    p.add_argument("--fingers", default="animate", choices=["rest", "animate"],
                   help="HY-Motion's finger output is unconstrained, so the "
                        "default leaves hands in the target rig's rest pose")
    p.add_argument("--left-hand", dest="left_hand", default="source",
                   choices=["source", "relaxed", "fist", "open", "point", "grip"],
                   help="drive the left hand directly; 'source' keeps whatever "
                        "the clip carries")
    p.add_argument("--right-hand", dest="right_hand", default="source",
                   choices=["source", "relaxed", "fist", "open", "point", "grip"])
    p.add_argument("--left-hand-cycle", dest="left_cycle", type=float, default=0.0,
                   help="open/close cycles per second for the left hand (0 = off)")
    p.add_argument("--right-hand-cycle", dest="right_cycle", type=float, default=0.0)
    p.add_argument("--aim", default="on", choices=["on", "off"],
                   help="aim bones at the source's joint positions; 'off' "
                        "restores the old orientation-only transfer")
    p.add_argument("--offset", default="0,0,0",
                   help="stage the character: X,Y,Z metres")
    p.add_argument("--yaw", type=float, default=0.0,
                   help="stage the character: rotation about up, degrees")
    return p.parse_args(argv)


def import_fbx(path, tag):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(
        filepath=path, use_anim=True,
        automatic_bone_orientation=False,   # preserve original bone axes
        ignore_leaf_bones=False,            # SMPL terminals are real joints
        force_connect_children=False)
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError(f"No armature found in {tag}: {path}")
    log(f"{tag}: '{arms[0].name}' {len(arms[0].data.bones)} bones, "
        f"{len([o for o in new if o.type == 'MESH'])} mesh(es)")
    return arms[0], new


def clip_range(arm):
    if arm.animation_data and arm.animation_data.action:
        a, b = arm.animation_data.action.frame_range
        return int(round(a)), int(round(b))
    return 1, 1


def clear_anim(obj):
    if obj.animation_data:
        obj.animation_data_clear()


def hierarchy_order(arm):
    """Bones parent-first."""
    out, seen = [], set()

    def walk(b):
        if b.name in seen:
            return
        seen.add(b.name)
        out.append(b)
        for c in b.children:
            walk(c)

    for b in arm.data.bones:
        if b.parent is None:
            walk(b)
    return out


def retarget(src, tgt, table, fps, fingers="animate", aim="on",
             hands=None):
    scene = bpy.context.scene
    f0, f1 = clip_range(src)
    log(f"frames {f0}-{f1} @ {fps}fps = {(f1 - f0 + 1) / fps:.2f}s")

    clear_anim(tgt)
    for pb in tgt.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.matrix_basis = Matrix()

    src_names = {b.name for b in src.data.bones}
    tgt_names = {b.name for b in tgt.data.bones}
    pairs, missing, skipped = {}, [], 0
    for s, t in table.items():
        if fingers == "rest" and is_finger(s):
            skipped += 1
            continue                      # leave the hand at its rest pose
        if s in src_names and t in tgt_names:
            pairs[t] = s
        elif s in src_names:
            missing.append(t)
    log(f"mapped {len(pairs)} bone pairs"
        + (f"  (fingers at rest, {skipped} skipped)" if skipped else ""))
    if missing:
        log(f"target bones not found ({len(missing)}): {missing[:8]}")

    # Rest rotations in world space, computed once.
    srcR = src.matrix_world.to_3x3()
    tgtR = tgt.matrix_world.to_3x3()
    s_rest = {b.name: (srcR @ b.matrix_local.to_3x3()) for b in src.data.bones}
    t_rest = {b.name: (tgtR @ b.matrix_local.to_3x3()) for b in tgt.data.bones}
    s_rest_inv = {k: v.inverted() for k, v in s_rest.items()}

    # Hand rigs are built before the bake so the empirical sign test runs on a
    # clean rest pose.
    hands = {k: dict(v) for k, v in (hands or {}).items()}
    hand_rigs = {}
    for side in ("L", "R"):
        want = hands.get(side, {}).get("pose", "source")
        # "From clip" only means something when the clip has finger joints.
        # Video capture has none, so the fingers would sit in the character's
        # rest pose - on most rigs a flat, splayed hand. Relax them instead.
        # (The video bridge carries only the middle-finger base, as an aim
        # target for the wrist - that is not finger motion.)
        if want == "source" and not any(
                is_finger(s) and s.startswith(side + "_") and s != side + "_Middle1"
                and table.get(s) in pairs for s in table):
            want = "relaxed"
            hands.setdefault(side, {})["pose"] = want
            log("hand %s: the clip has no finger motion - using a relaxed hand" % side)
        if want != "source":
            hand_rigs[side] = build_hand_rig(tgt, table, side)
            log("hand %s: %s%s (%d bones)"
                % (side, want,
                   ", cycling %.2f Hz" % hands[side]["cycle"]
                   if hands[side].get("cycle", 0) > 0 else "",
                   len(hand_rigs[side])))

    src_pb = {b.name: src.pose.bones[b.name] for b in src.data.bones}
    tgt_pb = {b.name: tgt.pose.bones[b.name] for b in tgt.data.bones}

    # --- position-based aiming ---------------------------------------------
    # The SMPL rig HY-Motion exports has degenerate bone orientations - every
    # rest bone points +Z - so "copy the change from rest" alone leaves the
    # arms ~50 degrees abducted and the spine hunched. Limb DIRECTION is
    # reliable: it comes from joint positions. So the spine, arms, hands and
    # legs are aimed at the source's joints instead.
    #
    # Using a source direction on the target needs the rotation between the
    # two rigs' worlds (s2t). It is a pure turn about the vertical, from each
    # rig's rest hip line - see below.
    AIM = Vector((0.0, 1.0, 0.0))     # Blender bones run along local +Y
    aim_pairs = []
    s2t = None

    if aim == "on":
        for s_b, s_c in AIM_CHAIN:
            t_b = table.get(s_b)
            if t_b and t_b in pairs and s_b in src_names and s_c in src_names:
                aim_pairs.append((t_b, s_b, s_c))

        t_pelvis = table.get("Pelvis", "")
        need = [t_pelvis, table.get("Spine1", ""),
                table.get("L_Hip", ""), table.get("R_Hip", "")]
        have = all(n and n in tgt_names for n in need) and \
            all(n in src_names for n in ("Pelvis", "Spine1", "L_Hip", "R_Hip"))

        if have and t_pelvis in pairs:
            # The mapping is a pure turn about the vertical: both rigs stand
            # on the same ground with the same up, so the only thing that can
            # differ between their worlds is which way they face at rest.
            # Facing comes from the rest hip line of each rig.
            #
            # It used to be solved from the pelvis frame (pelvis->spine,
            # hip->hip), which quietly folded the two skeletons' different
            # spine angles into the mapping as a PITCH. Every aimed bone then
            # inherited it and the whole body tipped as one piece: 17 deg
            # forward on video mocap, 2.5 deg on HY-Motion clips. No joint
            # angle check can see that - only a check against gravity can.
            def _rest_facing(obj, lh, rh):
                a, b = _rest_pos(obj, lh), _rest_pos(obj, rh)
                if a is None or b is None:
                    return None
                ac = b - a
                ac.z = 0.0
                if ac.length < 1e-6:
                    return None
                return Vector((0.0, 0.0, 1.0)).cross(ac.normalized()).normalized()

            fs_ = _rest_facing(src, "L_Hip", "R_Hip")
            ft_ = _rest_facing(tgt, need[2], need[3])
            if fs_ is not None and ft_ is not None:
                yaw = math.atan2(fs_.cross(ft_).z, fs_.dot(ft_))
                s2t = Matrix.Rotation(yaw, 3, "Z")
                log("aim: rest facing source (%.2f, %.2f) -> target (%.2f, %.2f), "
                    "turn %.1f deg" % (fs_.x, fs_.y, ft_.x, ft_.y, math.degrees(yaw)))

        if s2t is None:
            aim_pairs = []
            log("aim: disabled (falling back to orientation-only transfer)")
        else:
            # What actually has to point at the source's joint is the CHILD
            # JOINT, not the bone's own +Y axis. On a Biped rig the bones are
            # disconnected - a bone's tail does not reach the next joint - so
            # aiming the axis leaves the joint somewhere else entirely. Each
            # aimed bone therefore carries the rest offset to its child,
            # expressed in its own rest frame.
            resolved = []
            for t_b, s_b, s_c in aim_pairs:
                t_c = table.get(s_c)
                if not t_c or t_c not in tgt_names:
                    continue
                off = t_rest[t_b].inverted() @ (
                    (tgt.matrix_world @ tgt.data.bones[t_c].matrix_local).translation
                    - (tgt.matrix_world @ tgt.data.bones[t_b].matrix_local).translation)
                if off.length < 1e-6:
                    continue
                # Spine/neck segments carry the source's change FROM REST,
                # measured against the pelvis, not its absolute direction.
                # Skeletons place spine joints very differently - at rest the
                # lower-spine segment leans +16 deg on the GVHMR skeleton,
                # -7.5 on HY-Motion's and -1.6 on the mannequin - so copying
                # the direction bent an upright performer 15 deg forward.
                # Limbs keep exact directions so hands and feet land where
                # the source puts them.
                rel = None
                if s_b in SPINE_REL:
                    vs = _rest_pos(src, s_c) - _rest_pos(src, s_b)
                    vt = _rest_pos(tgt, t_c) - _rest_pos(tgt, t_b)
                    if vs.length > 1e-6 and vt.length > 1e-6:
                        rel = (vs.normalized(), s2t.transposed() @ vt.normalized())
                resolved.append((t_b, s_b, s_c, off, rel))
            aim_pairs = resolved
            log("aim: %d bones aimed from source joint positions "
                "(%d spine bones relative to rest)"
                % (len(aim_pairs), sum(1 for p in aim_pairs if p[4])))

    # On a Biped the thighs hang off the lower SPINE bone, not the pelvis. That
    # bone's twist comes from the source's lumbar joint, so whenever the hips
    # sway against the waist (any catwalk) the target's hip joints swung with
    # the waist instead of the pelvis - ~5 deg on average, ~10 at worst, which
    # slides the feet. The fix spins that bone about its own aim line until
    # the hip line matches the source's; the aim, and the chest above it, are
    # untouched.
    hip_fix = None
    t_lh, t_rh = table.get("L_Hip"), table.get("R_Hip")
    if aim_pairs and t_lh in tgt_names and t_rh in tgt_names:
        hp = tgt.data.bones[t_lh].parent
        if (hp is not None and hp == tgt.data.bones[t_rh].parent
                and hp.name != table.get("Pelvis")
                and any(p[0] == hp.name for p in aim_pairs)):
            hip_off = t_rest[hp.name].inverted() @ (
                _rest_pos(tgt, t_rh) - _rest_pos(tgt, t_lh))
            hip_fix = (hp.name, hip_off)
            log("hips: thighs hang off '%s' - its twist follows the source hips"
                % hp.name)

    order = hierarchy_order(tgt)
    s2t_T = s2t.transposed() if s2t is not None else None

    # --- root translation setup -------------------------------------------
    root_name = table.get("Pelvis")
    root_bone = tgt.data.bones.get(root_name) if root_name else None
    src_root = src.data.bones.get("Pelvis")
    scale = 1.0
    do_root = bool(root_bone and src_root)
    if do_root:
        # Scale from LEG LENGTH, not hip height. Hip height is measured from
        # the armature origin, which for the SMPL rig sits above the pelvis -
        # that yields a negative number and a mirrored, wildly wrong scale.
        def leg_len(arm, obj, names):
            pts = []
            for n in names:
                b = arm.bones.get(n)
                if b is None:
                    return None
                pts.append((obj.matrix_world @ b.matrix_local).translation)
            return sum((pts[i] - pts[i + 1]).length for i in range(len(pts) - 1))

        s_leg = leg_len(src.data, src, ["L_Hip", "L_Knee", "L_Ankle"])
        t_leg = leg_len(tgt.data, tgt,
                        [table.get(k, "") for k in ("L_Hip", "L_Knee", "L_Ankle")])
        if s_leg and t_leg and s_leg > 1e-4:
            scale = t_leg / s_leg
        log(f"leg length source {s_leg:.3f} -> target {t_leg:.3f}  "
            f"(scale {scale:.3f})")

        root_basis_m3 = root_bone.matrix_local.to_3x3().inverted()
        tgt_w_inv = tgt.matrix_world.inverted()
        src_root_rest_ws = (src.matrix_world @ src_root.matrix_local).translation
        tgt_root_rest_ws = (tgt.matrix_world @ root_bone.matrix_local).translation

        # Height is anchored on the GROUND, not on rest. The SMPL rig's rest
        # pelvis sits below its armature origin, so a rest-relative height
        # offset lifts the character a metre into the air.
        foot_keys = ("L_Ankle", "R_Ankle", "L_Foot", "R_Foot")
        src_ground = 1e9
        scene.frame_set(f0)
        src_root_start_ws = (src.matrix_world
                             @ src.pose.bones["Pelvis"].matrix).translation.copy()
        for _f in range(f0, f1 + 1):
            scene.frame_set(_f)
            for _n in foot_keys:
                _pb = src.pose.bones.get(_n)
                if _pb:
                    src_ground = min(
                        src_ground,
                        (src.matrix_world @ _pb.matrix).translation.z)
        tgt_ground = 1e9
        for _n in foot_keys:
            _b = tgt.data.bones.get(table.get(_n, ""))
            if _b:
                tgt_ground = min(
                    tgt_ground,
                    (tgt.matrix_world @ _b.matrix_local).translation.z)
        if src_ground > 1e8 or tgt_ground > 1e8:
            src_ground = src_root_rest_ws.z
            tgt_ground = tgt_root_rest_ws.z
            log("ground reference unavailable - falling back to rest height")
        log(f"ground source {src_ground:.3f} -> target {tgt_ground:.3f}")


    for f in range(f0, f1 + 1):
        scene.frame_set(f)

        # A world-space change measured on the source is re-expressed in the
        # target's world before use. Without this, rigs that face opposite
        # ways at rest (video mocap does) get every un-aimed tilt mirrored:
        # a head nodding down on the source nods UP on the target.
        deltas = {}
        for t_name, s_name in pairs.items():
            Rp = (src.matrix_world @ src_pb[s_name].matrix).to_3x3()
            d = Rp @ s_rest_inv[s_name]
            deltas[t_name] = d if s2t is None else s2t @ d @ s2t_T

        # desired world-space directions for this frame, from source joints
        want = {}
        if s2t is not None and aim_pairs:
            Dp = ((src.matrix_world @ src_pb["Pelvis"].matrix).to_3x3()
                  @ s_rest_inv["Pelvis"])
            Dp_inv = Dp.inverted()
            for t_b, s_b, s_c, off, rel in aim_pairs:
                a = (src.matrix_world @ src_pb[s_b].matrix).translation
                c = (src.matrix_world @ src_pb[s_c].matrix).translation
                v = c - a
                if v.length < 1e-6:
                    continue
                if rel is None:
                    d = v.normalized()
                else:
                    # bend relative to the pelvis, as a swing away from the
                    # source's rest direction, replayed on the target's rest
                    vs_rest, vt_rest = rel
                    u = (Dp_inv @ v).normalized()
                    d = Dp @ (vs_rest.rotation_difference(u) @ vt_rest)
                want[t_b] = ((s2t @ d).normalized(), off)

        world = {}
        for b in order:
            if b.name in deltas:
                world[b.name] = deltas[b.name] @ t_rest[b.name]
                got = want.get(b.name)
                if got is not None:
                    d, off = got
                    cur = world[b.name] @ off
                    if cur.length > 1e-9:
                        cur.normalize()
                        # minimal-arc swing: puts the child joint on the
                        # source's direction without adding twist
                        world[b.name] = (cur.rotation_difference(d).to_matrix()
                                         @ world[b.name])
                    if hip_fix is not None and b.name == hip_fix[0]:
                        cur_h = world[b.name] @ hip_fix[1]
                        src_h = s2t @ (
                            (src.matrix_world @ src_pb["R_Hip"].matrix).translation
                            - (src.matrix_world @ src_pb["L_Hip"].matrix).translation)
                        cur_h -= d * cur_h.dot(d)
                        src_h -= d * src_h.dot(d)
                        if cur_h.length > 1e-6 and src_h.length > 1e-6:
                            spin = math.atan2(d.dot(cur_h.cross(src_h)),
                                              cur_h.dot(src_h))
                            world[b.name] = (Matrix.Rotation(spin, 3, d)
                                             @ world[b.name])
            elif b.parent is None:
                world[b.name] = t_rest[b.name]
            else:
                # unmapped: ride the parent, keep the rest offset
                local_rest = t_rest[b.parent.name].inverted() @ t_rest[b.name]
                world[b.name] = world[b.parent.name] @ local_rest

        for b in order:
            if b.parent is None:
                Wp, Wrp = tgtR, tgtR
            else:
                Wp, Wrp = world[b.parent.name], t_rest[b.parent.name]
            local_pose = Wp.inverted() @ world[b.name]
            local_rest = Wrp.inverted() @ t_rest[b.name]
            pb = tgt_pb[b.name]
            pb.rotation_quaternion = (local_rest.inverted()
                                      @ local_pose).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=f)

        if do_root:
            p_ws = (src.matrix_world @ src_pb["Pelvis"].matrix).translation
            # Horizontal travel is measured from where the source starts and
            # rotated by the SAME source->target mapping the aimed bones use.
            # Applying it in the source's raw world axes is what made clips
            # walk backwards: whenever the two rigs' world frames disagreed
            # (by ~180 deg for video mocap), the body faced one way and the
            # root travelled the other. HY-Motion clips happened to line up,
            # which hid it.
            disp = (p_ws - src_root_start_ws) * scale
            if s2t is not None:
                disp = s2t @ disp
            desired_ws = Vector((
                tgt_root_rest_ws.x + disp.x,
                tgt_root_rest_ws.y + disp.y,
                tgt_ground + (p_ws.z - src_ground) * scale,
            ))
            p_as = tgt_w_inv @ desired_ws
            pb = tgt_pb[root_name]
            pb.location = root_basis_m3 @ (p_as - root_bone.matrix_local.translation)
            pb.keyframe_insert("location", frame=f)

        # hands are driven directly - the model has no finger joints
        for side, rig in hand_rigs.items():
            cfg = hands.get(side, {})
            apply_hand(rig, cfg.get("pose", "source"),
                       float(cfg.get("cycle", 0.0)),
                       (f - f0) / float(fps), f)

    scene.frame_start, scene.frame_end = f0, f1
    scene.render.fps, scene.render.fps_base = fps, 1.0
    log("bake complete")
    return f0, f1


def build_hand_rig(tgt, table, side):
    """Work out how to curl one hand on this rig.

    Fingers curl about the knuckle line, so that axis is measured from the rig
    itself rather than assumed. The sign is then found by trying a small bend
    and keeping whichever direction moves the fingertip toward the wrist -
    that is "closing" on any rig, however its axes happen to be laid out.

    Returns a list of (pose_bone, local_axis, radians_at_full_curl, digit).
    """
    def rest_head(name):
        b = tgt.data.bones.get(name)
        return (tgt.matrix_world @ b.matrix_local).translation if b else None

    idx = rest_head(table.get(f"{side}_Index1", ""))
    pnk = rest_head(table.get(f"{side}_Pinky1", ""))
    wri = rest_head(table.get(f"{side}_Wrist", ""))
    if idx is None or pnk is None or wri is None:
        return []
    across = (pnk - idx)
    if across.length < 1e-6:
        return []
    across.normalize()

    out = []
    for digit in DIGITS:
        for n in (1, 2, 3):
            t_name = table.get(f"{side}_{digit}{n}")
            b = tgt.data.bones.get(t_name) if t_name else None
            if b is None:
                continue
            rest3 = (tgt.matrix_world @ b.matrix_local).to_3x3()
            local_axis = rest3.inverted() @ across
            if local_axis.length < 1e-9:
                continue
            local_axis.normalize()
            rad = CURL_RAD[n - 1] * (THUMB_SCALE if digit == "Thumb" else 1.0)
            out.append([tgt.pose.bones[b.name], local_axis, rad, digit, b])

    # decide the closing direction empirically
    if out:
        pb, axis, rad, digit, bone = out[0]
        tip = rest_head(table.get(f"{side}_Middle3", "")) or \
            rest_head(table.get(f"{side}_Middle2", ""))
        if tip is not None:
            base = (tip - wri).length
            best, bestd = 1.0, -1e9
            for sign in (1.0, -1.0):
                for e in out:
                    e[0].rotation_mode = "QUATERNION"
                    e[0].rotation_quaternion = Matrix.Rotation(
                        sign * e[2] * 0.9, 4, e[1]).to_quaternion()
                bpy.context.view_layer.update()
                mid = table.get(f"{side}_Middle3") or table.get(f"{side}_Middle2")
                pbm = tgt.pose.bones.get(mid)
                if pbm is None:
                    continue
                d = base - ((tgt.matrix_world @ pbm.head) - wri).length
                if d > bestd:
                    bestd, best = d, sign
            for e in out:
                e[0].rotation_quaternion = Matrix().to_quaternion()
            bpy.context.view_layer.update()
            for e in out:
                e[1] = e[1] * best
    return out


def apply_hand(rig, pose_name, cycle_hz, t_seconds, frame):
    """Key one hand for one frame."""
    if not rig or pose_name == "source":
        return
    table = HAND_POSES.get(pose_name, HAND_POSES["relaxed"])
    for pb, axis, rad, digit, bone in rig:
        amt = table.get(digit, 0.0)
        if cycle_hz > 0.0:
            # smooth open <-> close; the named pose sets how far it closes
            phase = 0.5 - 0.5 * math.cos(2.0 * math.pi * cycle_hz * t_seconds)
            amt = max(amt, 0.15) * phase
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = Matrix.Rotation(amt * rad, 4, axis).to_quaternion()
        pb.keyframe_insert("rotation_quaternion", frame=frame)


def stage(roots, offset, yaw_deg):
    """Place the character in the scene, for two-actor shots."""
    if not any(offset) and abs(yaw_deg) < 1e-6:
        return
    m = Matrix.Translation(Vector(offset)) @ Matrix.Rotation(
        math.radians(yaw_deg), 4, "Z")
    for o in roots:
        o.matrix_world = m @ o.matrix_world
    log(f"staged at {tuple(round(v, 3) for v in offset)} yaw {yaw_deg:g} deg")


def export_fbx(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=path, use_selection=False,
        object_types={"ARMATURE", "MESH"},
        axis_forward="-Z", axis_up="Y",
        global_scale=1.0, apply_scale_options="FBX_SCALE_NONE",
        apply_unit_scale=True, add_leaf_bones=False,
        primary_bone_axis="Y", secondary_bone_axis="X",
        armature_nodetype="NULL", use_armature_deform_only=False,
        bake_anim=True, bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode="STRIP", embed_textures=False, mesh_smooth_type="FACE")
    log("FBX -> " + path)


def export_glb(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB",
        export_animations=True, export_skins=True,
        export_yup=True, export_apply=False,
        export_frame_range=True, export_force_sampling=True,
        export_bake_animation=True, export_anim_slide_to_zero=True,
        export_optimize_animation_size=False,
        export_materials="EXPORT", export_image_format="AUTO")
    log("GLB -> " + path)


def main():
    a = parse_args()
    for p in (a.source, a.target):
        if not os.path.isfile(p):
            raise SystemExit("[error] not found: " + p)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = a.fps
    bpy.context.scene.render.fps_base = 1.0

    tgt, tgt_objs = import_fbx(a.target, "target")
    src, src_objs = import_fbx(a.source, "source")

    # The mannequin file ships with its own clip; it must not survive.
    clear_anim(tgt)
    for o in tgt_objs:
        clear_anim(o)

    if a.profile == "auto":
        table, name = detect_profile(tgt)
    else:
        table, name = resolve_profile(PROFILES[a.profile], {b.name for b in tgt.data.bones}), a.profile
        log(f"profile '{name}' (forced)")

    hands = {"L": {"pose": a.left_hand, "cycle": a.left_cycle},
             "R": {"pose": a.right_hand, "cycle": a.right_cycle}}
    retarget(src, tgt, table, a.fps, a.fingers, a.aim, hands)

    if not a.keep_source:
        for o in src_objs:
            bpy.data.objects.remove(o, do_unlink=True)
        log("source rig removed")

    try:
        off = [float(v) for v in a.offset.split(",")]
        off = (off + [0.0, 0.0, 0.0])[:3]
    except Exception:
        off = [0.0, 0.0, 0.0]
    stage([o for o in tgt_objs if o.parent is None and o.name in bpy.data.objects],
          off, a.yaw)

    if a.out_fbx:
        export_fbx(a.out_fbx)
    if a.out_glb:
        export_glb(a.out_glb)
    log("done")


if __name__ == "__main__":
    main()
