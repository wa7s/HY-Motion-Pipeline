# Unity import notes — HY-Motion clips

---

## Full SMPL-H → Unity Humanoid mapping

The Blender script applies this automatically. Reproduced here so you can
hand-map in the Avatar Configure window if you ever need to.

### Body (22)

| SMPL-H | Unity Humanoid | Required? |
|---|---|---|
| `Pelvis` | Hips | **required** |
| `Spine1` | Spine | **required** |
| `Spine2` | Chest | **required** |
| `Spine3` | UpperChest | optional |
| `Neck` | Neck | optional |
| `Head` | Head | **required** |
| `L_Collar` | LeftShoulder | optional |
| `R_Collar` | RightShoulder | optional |
| `L_Shoulder` | LeftUpperArm | **required** |
| `R_Shoulder` | RightUpperArm | **required** |
| `L_Elbow` | LeftLowerArm | **required** |
| `R_Elbow` | RightLowerArm | **required** |
| `L_Wrist` | LeftHand | **required** |
| `R_Wrist` | RightHand | **required** |
| `L_Hip` | LeftUpperLeg | **required** |
| `R_Hip` | RightUpperLeg | **required** |
| `L_Knee` | LeftLowerLeg | **required** |
| `R_Knee` | RightLowerLeg | **required** |
| `L_Ankle` | LeftFoot | **required** |
| `R_Ankle` | RightFoot | **required** |
| `L_Foot` | LeftToes | optional |
| `R_Foot` | RightToes | optional |

All 17 Unity-required bones are present in SMPL-H. Nothing is missing.

### Fingers (30)

`{L,R}_{digit}{1,2,3}` → `{Left,Right}{Digit}{Proximal,Intermediate,Distal}`

| SMPL digit | Unity digit |
|---|---|
| Thumb | Thumb |
| Index | Index |
| Middle | Middle |
| Ring | Ring |
| **Pinky** | **Little** |

> **The one naming mismatch**, and it is handled. Unity's little-finger bones
> are `LeftLittleProximal` etc. while SMPL says `L_Pinky1`. The Blender script
> emits Unity's spelling, so all 30 finger bones auto-map. Verified on a real
> export: 22/22 body + 30/30 finger slots filled, nothing left unmapped.

---

## Naming gotchas

| Symptom | Cause | Fix |
|---|---|---|
| Avatar configure fails, only Hips found | raw SMPL names imported | run the Blender rename script |
| Extra `_end` bones in the hierarchy | Blender leaf bones | `add_leaf_bones=False` — already set in the script |
| Character 100× too large or small | metres/centimetres mismatch through Cascadeur | invert the Cascadeur import scale on export |
| Clip rotated 90° on import | axis conversion applied twice | Blender writes Y-up/-Z-fwd; turn **off** Unity's "Bake Axis Conversion" |
| Bone count 100+ | Cascadeur rig controllers exported | re-export joints only |

---

## Reusing one avatar across many clips

You will generate a lot of clips on one skeleton. Don't let each create its own
avatar.

1. Import the first clip. Rig → Animation Type **Humanoid**, Avatar Definition
   **Create From This Model**. Configure and Apply.
2. Every subsequent clip: Avatar Definition **Copy From Other Avatar**, point at
   the avatar from step 1.

This keeps retargeting consistent and stops Unity generating a new avatar asset
per file.

---

## Retargeting onto the 7 heroes

HY-Motion outputs a generic SMPL body, not your characters. Humanoid retargeting
handles the proportion difference, but watch two things:

- **Hand contact points.** Humanoid retargeting is proportion-relative, so a
  clip where hands meet (clasping, grabbing a weapon) will drift on a character
  with different arm length. Fix with IK at runtime or an Animation Rigging
  constraint, not by editing the clip.
- **Foot contact.** Enable Foot IK on the Animator state for grounded clips.
  This is also why fixing foot sliding in Cascadeur matters — Foot IK corrects
  small errors, not large ones.

---

## Mobile budget

52 bones per character is heavy for a phone party game with several characters
on screen.

- Strip fingers → 22 bones (`--strip-fingers` in the Blender script).
- Set Animation Compression to **Optimal** on the clip importer.
- Consider Unity's "Optimize Game Objects" on the model importer to remove the
  transform hierarchy at runtime, exposing only the bones you need.

Unless a hero's signature move needs readable fingers, strip them. The hands
still deform as rigid units and read fine at phone screen size.
