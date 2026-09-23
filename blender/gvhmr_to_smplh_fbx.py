"""
GVHMR (video mocap) -> SMPL-H-style FBX that the HY Motion retarget accepts.

GVHMR outputs SMPL parameters (root orientation + translation + 21 local
body-joint rotations + shape), not an FBX. This builds an armature with the
same joint names and the same structure as the FBX HY-Motion exports, so
everything downstream - hym_retarget.py, the hand controls, the viewport and
the Unity export - works on video mocap without any changes.

Structure deliberately mirrors HY-Motion's export: every bone rests pointing
straight up at its joint position. In Blender a bone's local Y runs along the
bone, so an upward bone has a rest rotation of +90 degrees about X - which is
exactly the SMPL Y-up -> Blender Z-up conversion. The two cancel: the pose
rotation of each bone is the RAW SMPL local rotation, and the root location is
the RAW SMPL translation. Converting them again double-rotates every joint
(it was measured at up to 644 mm of pose error before this was understood).

The middle-finger bases (L_Middle1 / R_Middle1) are added from the SMPL-X
regressor even though GVHMR has no hand pose. They carry no animation of their
own, but they give the retarget a real hand direction to aim the wrist at -
without them the hand keeps ~50 degrees of error, as it did before the wrist
aim was added for HY-Motion clips.

    blender -b --factory-startup --python gvhmr_to_smplh_fbx.py -- \
        --npz smpl_params.npz --smplx SMPLX_NEUTRAL.npz --out source.fbx \
        [--src-fps 23.976] [--fps 30]
"""

import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

# SMPL body joints (first 22 of SMPL-X), in the names HY-Motion uses.
NAMES = ["Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee", "Spine2",
         "L_Ankle", "R_Ankle", "Spine3", "L_Foot", "R_Foot", "Neck",
         "L_Collar", "R_Collar", "Head", "L_Shoulder", "R_Shoulder",
         "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist"]
PAR = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14,
       16, 17, 18, 19]
# SMPL-X hand joints: 25..39 left, 40..54 right, order index/middle/pinky/
# ring/thumb, three each. Middle1 is the fourth entry of each hand.
EXTRA = {"L_Middle1": (28, 20), "R_Middle1": (43, 21),
         # Midpoint of the SMPL-X eyes (23, 24). Rides rigidly on the head and
         # gives the retarget a face direction to aim the head at - without it
         # the head keeps the orientation-transfer error and looks at the
         # floor, the same way the hand did before the wrist was aimed.
         "Face": ((23, 24), 15)}

# SMPL is Y-up, Blender is Z-up: rotate +90 degrees about X.
C = Matrix.Rotation(math.radians(90.0), 3, "X")
CT = C.transposed()


def log(m):
    print("[gvhmr] " + str(m), flush=True)


def aa_to_mat(r):
    th = float(np.linalg.norm(r))
    if th < 1e-8:
        return Matrix.Identity(3)
    return Quaternion(Vector((r / th).tolist()), th).to_matrix()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", required=True)
    ap.add_argument("--smplx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src-fps", dest="src_fps", type=float, default=23.976)
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args(argv)

    d = np.load(a.npz, allow_pickle=True)
    m = np.load(a.smplx, allow_pickle=True)
    N = int(d["body_pose"].shape[0])
    log("frames %d at %.3f fps -> resampled to %d fps" % (N, a.src_fps, a.fps))

    # rest joints for this performer's shape (median betas across the clip)
    betas = np.median(d["betas"], axis=0)
    v = m["v_template"] + np.einsum("vck,k->vc", m["shapedirs"][:, :, :10], betas)
    J = m["J_regressor"] @ v                      # (55, 3), SMPL Y-up metres

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps, sc.render.fps_base = a.fps, 1.0

    arm_data = bpy.data.armatures.new("Reference")
    arm = bpy.data.objects.new("Reference", arm_data)
    sc.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = {}
    joints = list(enumerate(NAMES)) + [(-1, n) for n in EXTRA]
    for idx, name in joints:
        jid = EXTRA[name][0] if name in EXTRA else idx
        pos = J[list(jid)].mean(axis=0) if isinstance(jid, tuple) else J[jid]
        head = C @ Vector(pos.tolist())
        b = arm_data.edit_bones.new(name)
        b.head = head
        b.tail = head + Vector((0.0, 0.0, 0.05))  # points up - see docstring
        b.roll = 0.0
        eb[name] = b
    for i, name in enumerate(NAMES):
        if PAR[i] >= 0:
            eb[name].parent = eb[NAMES[PAR[i]]]
    for name, (_, pidx) in EXTRA.items():
        eb[name].parent = eb[NAMES[pidx]]
    for b in eb.values():
        b.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    pbs = {n: arm.pose.bones[n] for n in list(NAMES) + list(EXTRA)}
    for pb in pbs.values():
        pb.rotation_mode = "QUATERNION"

    go = d["global_orient"]
    tr = d["transl"]
    bp = d["body_pose"].reshape(N, 21, 3)
    step = a.fps / a.src_fps
    prev = {}
    last = 1
    for i in range(N):
        f = 1.0 + i * step
        last = f
        # root
        q = aa_to_mat(go[i]).to_quaternion()           # raw: see docstring
        if "Pelvis" in prev and prev["Pelvis"].dot(q) < 0:
            q.negate()                            # keep interpolation short-way
        prev["Pelvis"] = q
        pbs["Pelvis"].rotation_quaternion = q
        pbs["Pelvis"].location = Vector(tr[i].tolist())  # raw: see docstring
        pbs["Pelvis"].keyframe_insert("rotation_quaternion", frame=f)
        pbs["Pelvis"].keyframe_insert("location", frame=f)
        # body
        for j in range(1, 22):
            q = aa_to_mat(bp[i, j - 1]).to_quaternion()
            n = NAMES[j]
            if n in prev and prev[n].dot(q) < 0:
                q.negate()
            prev[n] = q
            pbs[n].rotation_quaternion = q
            pbs[n].keyframe_insert("rotation_quaternion", frame=f)
        for n in EXTRA:
            pbs[n].rotation_quaternion = Quaternion()
            pbs[n].keyframe_insert("rotation_quaternion", frame=f)

    f1 = int(math.floor(last))
    sc.frame_start, sc.frame_end = 1, f1
    log("keyed %d source frames over scene frames 1-%d (%.2fs)"
        % (N, f1, f1 / float(a.fps)))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=a.out, use_selection=False, object_types={"ARMATURE"},
        axis_forward="-Z", axis_up="Y", global_scale=1.0,
        apply_scale_options="FBX_SCALE_NONE", apply_unit_scale=True,
        add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X",
        armature_nodetype="NULL", bake_anim=True, bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0)
    log("FBX -> " + a.out)


if __name__ == "__main__":
    main()
