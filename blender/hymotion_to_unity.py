"""
HY-Motion -> Unity FBX conditioning script (Blender 5.x headless).

Takes an FBX produced by ComfyUI-HY-Motion1 (or re-exported from Cascadeur),
normalises it for Unity, optionally renames the SMPL-H skeleton to Unity-
friendly bone names so the Humanoid avatar auto-maps, and writes a clean FBX.

Usage (from the .bat wrappers, or directly):

  blender.exe -b --factory-startup --python hymotion_to_unity.py -- \
      --in  "C:/path/in.fbx" \
      --out "C:/path/out.fbx" \
      [--rename unity|none]   (default: unity)
      [--fps 30]
      [--scale 1.0]
      [--strip-fingers]
      [--armature-only]       (export rig+animation only, no skinned mesh)

Everything after the `--` is passed to this script, not to Blender.
"""

import bpy
import sys
import os
import argparse

# --- SMPL-H (52 joints) -> Unity-Humanoid-friendly names -------------------
# Unity's avatar auto-mapper keys off common substrings ("Hips", "UpperArm",
# "LowerLeg", "ThumbProximal"...). SMPL names like "L_Collar" or "L_Elbow" do
# not auto-map, which is why this table exists.
SMPLH_TO_UNITY = {
    "Pelvis":     "Hips",
    "Spine1":     "Spine",
    "Spine2":     "Chest",
    "Spine3":     "UpperChest",
    "Neck":       "Neck",
    "Head":       "Head",

    "L_Hip":      "LeftUpperLeg",   "R_Hip":      "RightUpperLeg",
    "L_Knee":     "LeftLowerLeg",   "R_Knee":     "RightLowerLeg",
    "L_Ankle":    "LeftFoot",       "R_Ankle":    "RightFoot",
    "L_Foot":     "LeftToes",       "R_Foot":     "RightToes",

    "L_Collar":   "LeftShoulder",   "R_Collar":   "RightShoulder",
    "L_Shoulder": "LeftUpperArm",   "R_Shoulder": "RightUpperArm",
    "L_Elbow":    "LeftLowerArm",   "R_Elbow":    "RightLowerArm",
    "L_Wrist":    "LeftHand",       "R_Wrist":    "RightHand",
}

# Fingers: SMPL-H's 3 joints per digit line up 1:1 with Unity's
# Proximal / Intermediate / Distal.
#
# Note the digit rename: SMPL calls the little finger "Pinky", Unity calls it
# "Little" (LeftLittleProximal). Emitting Unity's spelling is what lets the
# avatar auto-mapper pick up all 30 finger bones instead of 24.
_STAGE = {"1": "Proximal", "2": "Intermediate", "3": "Distal"}
_DIGITS = {"Thumb": "Thumb", "Index": "Index", "Middle": "Middle",
           "Ring": "Ring", "Pinky": "Little"}
for _side, _u in (("L", "Left"), ("R", "Right")):
    for _smpl_digit, _unity_digit in _DIGITS.items():
        for _n, _stage in _STAGE.items():
            SMPLH_TO_UNITY[_side + "_" + _smpl_digit + _n] = _u + _unity_digit + _stage

# Matches both spellings so --strip-fingers works before or after renaming.
FINGER_ROOTS = ("Thumb", "Index", "Middle", "Ring", "Pinky", "Little")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", dest="dst", required=True)
    p.add_argument("--rename", choices=["unity", "none"], default="unity")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--strip-fingers", action="store_true")
    p.add_argument("--armature-only", action="store_true")
    return p.parse_args(argv)


def find_armature():
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError("No armature found in the imported FBX.")
    if len(arms) > 1:
        print("[warn] %d armatures found; using '%s'" % (len(arms), arms[0].name))
    return arms[0]


def rename_bones(arm):
    """Rename SMPL-H bones to Unity-friendly names. Returns (count, unknown)."""
    renamed, unknown = 0, []
    for bone in arm.data.bones:
        # FBX rigs often carry namespace prefixes; match the trailing token too.
        key = bone.name
        if key not in SMPLH_TO_UNITY:
            for cand in SMPLH_TO_UNITY:
                if key.split(":")[-1] == cand or key.endswith("_" + cand):
                    key = cand
                    break
        if key in SMPLH_TO_UNITY:
            bone.name = SMPLH_TO_UNITY[key]
            renamed += 1
        else:
            unknown.append(bone.name)
    return renamed, unknown


def strip_fingers(arm):
    """Delete finger bones - useful for mobile rigs that do not animate hands."""
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    to_del = [b for b in arm.data.edit_bones
              if any(d in b.name for d in FINGER_ROOTS)]
    n = len(to_del)
    for b in to_del:
        arm.data.edit_bones.remove(b)
    bpy.ops.object.mode_set(mode="OBJECT")
    return n


def main():
    a = parse_args()
    src = os.path.abspath(a.src)
    dst = os.path.abspath(a.dst)
    if not os.path.isfile(src):
        raise SystemExit("[error] input not found: " + src)
    out_dir = os.path.dirname(dst)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = a.fps
    bpy.context.scene.render.fps_base = 1.0

    print("[hymotion] importing " + src)
    # ignore_leaf_bones MUST stay False. HY-Motion's terminal joints are real
    # SMPL-H joints, not FBX leaf padding: Head, L_Foot/R_Foot (toes) and all
    # ten finger distals. Stripping them drops the 52-bone rig to 39 and
    # removes Head, which Unity requires for a Humanoid avatar.
    #
    # automatic_bone_orientation stays False so the original FBX bone axes
    # survive the round trip unchanged.
    bpy.ops.import_scene.fbx(
        filepath=src,
        use_anim=True,
        automatic_bone_orientation=False,
        ignore_leaf_bones=False,
        force_connect_children=False,
    )

    arm = find_armature()
    print("[hymotion] armature '%s' with %d bones" % (arm.name, len(arm.data.bones)))

    if a.rename == "unity":
        n, unknown = rename_bones(arm)
        print("[hymotion] renamed %d bones to Unity Humanoid names" % n)
        if unknown:
            print("[hymotion] left unrenamed (%d): %s" % (len(unknown), unknown[:12]))

    if a.strip_fingers:
        print("[hymotion] stripped %d finger bones" % strip_fingers(arm))

    if a.scale != 1.0:
        arm.scale = (a.scale,) * 3
        bpy.context.view_layer.objects.active = arm
        arm.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        print("[hymotion] applied scale x%s" % a.scale)

    # Trim the scene frame range to the actual keyed range.
    action = arm.animation_data.action if arm.animation_data else None
    if action:
        fs, fe = (int(round(v)) for v in action.frame_range)
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = fs, fe
        dur = (fe - fs + 1) / float(a.fps)
        print("[hymotion] frames %d-%d @ %dfps = %.2fs" % (fs, fe, a.fps, dur))
    else:
        print("[warn] armature has no action - exporting rest pose only")

    obj_types = {"ARMATURE"} if a.armature_only else {"ARMATURE", "MESH"}

    print("[hymotion] exporting " + dst)
    bpy.ops.export_scene.fbx(
        filepath=dst,
        use_selection=False,
        object_types=obj_types,
        # Unity wants Y-up / -Z-forward; this pairing is what stops Unity
        # importing the clip with a 90-degree root rotation.
        axis_forward="-Z",
        axis_up="Y",
        global_scale=1.0,
        apply_scale_options="FBX_SCALE_NONE",
        apply_unit_scale=True,
        # Leaf bones are the classic source of phantom "_end" bones in Unity.
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        armature_nodetype="NULL",
        use_armature_deform_only=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,   # no decimation - Cascadeur/Unity handle it
        # STRIP, not COPY: the bundled mannequin's 14 MB base-colour texture is
        # dead weight on an animation clip, and COPY duplicates it into a .fbm
        # folder beside every single export. The mesh is a placeholder that your
        # own characters replace, so its texture never ships.
        path_mode="STRIP",
        embed_textures=False,
        mesh_smooth_type="FACE",
    )
    print("[hymotion] OK -> " + dst)


if __name__ == "__main__":
    main()
