# Cascadeur cleanup checklist — HY-Motion clips

Cascadeur 2026.1.3 · `C:\Program Files\Cascadeur`

Work through this in order. Steps 1–3 are where almost all the quality comes
from; 4–6 are polish.

---

## 0. Before you import

| Check | Expected |
|---|---|
| Source file | `ComfyUI/output/hymotion_fbx/<name>_0.fbx` |
| Bone count | 52 (or 22 if fingers were stripped) |
| Root joint | `Pelvis` |
| Frame rate | 30 |
| Units | metres |

---

## 1. Import and fix scale

Cascadeur's solver is **mass- and gravity-aware**. Unit errors do not produce a
small visual offset — they produce physically wrong results, because a 1.7-unit
tall character reads as a 1.7 cm doll.

- Import the FBX.
- Check the mannequin's height in the viewport. It should read ~170 cm.
- If it arrives at ~1.7, set the import scale to **100**.
- Note whichever scale you used — you must invert it on export.

Set the scene frame rate to **30** to match the source.

---

## 2. Quick Rig

Cascadeur's tools stay inert until the skeleton is tagged.

- **Rigging → Quick Rig**, map the joints to Cascadeur's humanoid template.
- SMPL-H is a clean, standard biped — mapping is mechanical. `Pelvis` → hips,
  `Spine1/2/3` → spine chain, `L_Collar/Shoulder/Elbow/Wrist` → left arm chain,
  and so on. The full list of joint names is in `unity/SMPLH_Humanoid_Notes.md`.
- Save the rig mapping. Cascadeur can reuse it for every subsequent HY-Motion
  clip, since they all share one skeleton — this is a one-time cost.

---

## 3. Ground contact — do this first

This is the single highest-value fix. Diffusion motion models are not
contact-aware, so feet slide and sink.

- Scrub and mark the frames where each foot is planted.
- Pin the support foot across those frames.
- Push any ground penetration back to Y=0.

Most of what reads as "AI animation" is foot sliding. Fixing it alone gets a
clip most of the way to usable.

---

## 4. AutoPhysics — ballistic sections only

Apply to airborne and impact-driven sections: jumps, knockbacks, stagger
recoveries, the follow-through after a heavy swing.

**Do not run it over grounded sections you just pinned** — it will fight the
pins and reintroduce sliding.

Select the frame range first, then apply. Never apply to the whole clip.

---

## 5. Centre of mass and trajectory

HY-Motion tends to keep the COM floatier than real weight transfer.

- Open the trajectory view for the COM.
- Look for a flat arc where there should be a ballistic curve (jumps) or a
  drop (impacts, landings).
- Adjust the trajectory rather than individual joints — it propagates.

For weighty, impactful reactions this is the step that sells the
hit. Generated motion reads as light by default; the COM curve is where you add
the weight.

---

## 6. Secondary motion — sparingly

HY-Motion already produces plausible overlap and follow-through. Stacking
Cascadeur's secondary motion on top usually reads as noise rather than life.

Use it only where a specific limb needs more whip, over a short range.

---

## 7. Fingers

If you're keeping fingers, check for jitter — the 30 finger joints are the
least-constrained part of the model's output and the most likely to buzz.

Easiest fix: select the finger joints, delete keys, and pose them once as a
static fist / open hand for the whole clip.

If you're not keeping them, don't clean them — strip them in Blender later with
`--strip-fingers`.

---

## 8. Export

| Setting | Value |
|---|---|
| Format | FBX |
| Animation | **baked** |
| Frame rate | 30 |
| Scale | invert your import scale (×0.01 if you imported at ×100) |
| Contents | **joint hierarchy only** |

**Do not export Cascadeur's rig controllers.** They appear in Unity as dozens
of extra bones and will confuse the Humanoid avatar mapper.

After export, verify the bone count is still **52** (or 22). If it jumped to
100+, controllers got included — re-export.

---

## 9. Hand off to Blender

```bat
cd /d "<where you put HY Motion Studio>\blender"
RUN_hymotion_to_unity.bat "C:\path\from_cascadeur.fbx" "C:\path\clip_unity.fbx"
```

That renames SMPL-H → Unity Humanoid and fixes the axis convention. Then import
`clip_unity.fbx` into Unity with the settings in `unity/SMPLH_Humanoid_Notes.md`.
