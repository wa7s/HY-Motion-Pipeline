# Video → animation (GVHMR) — the manual route

**Normal use: HY Motion Studio.** Open the *Video to Motion* workspace, choose
the file, set Start and End, and press *Make Animation from Video*. The app
runs every step below by itself. This file is only for troubleshooting.

GVHMR and the SMPL / SMPL-X body models are licensed for research and
non-commercial use. Use the result as reference to keyframe over (for example
in Cascadeur); don't ship it.

GVHMR captures the **body only** - it has no finger data. The app gives the
hands a relaxed pose automatically, or use the Hands panel.

## Steps

`PY` is ComfyUI's Python (`python_embeded\python.exe` in the portable build),
`BL` is your `blender.exe`, `APP` is the HY Motion Studio folder and `COMFY`
is the ComfyUI folder.

1. **Cut and downscale** the part you want (the longer side becomes 1280 px):

       PY APP\video\vid_trim.py  in.mp4  COMFY\input\clip.mp4  8  16

2. **Person mask.** Keeps the largest person on each frame, and writes a check
   sheet so you can see what it tracked:

       PY APP\video\make_mask.py  COMFY\input\clip.mp4  COMFY\input\clip_mask.mp4  mask_check.jpg

   Both videos must sit directly in `COMFY\input\` - ComfyUI's LoadVideo node
   only lists files at the top level.

3. **GVHMR.** With ComfyUI running on port 8189 (the port the app uses):

       PY APP\video\run_gvhmr.py  clip.mp4  clip_mask.mp4  [static|moving]

   Use `moving` only if the camera moves. The result is
   `COMFY\output\smpl_params_NNNN.npz`.

4. **Rebuild the skeleton** in the same layout HY-Motion exports:

       BL -b --factory-startup --python APP\blender\gvhmr_to_smplh_fbx.py -- ^
          --npz COMFY\output\smpl_params_0001.npz ^
          --smplx COMFY\models\motion_capture\body_models\smplx\SMPLX_NEUTRAL.npz ^
          --out clip_smplh.fbx --src-fps 30

   Set `--src-fps` to the video's frame rate.

5. **Put it on a character:**

       BL -b --factory-startup --python APP\blender\hym_retarget.py -- ^
          --source clip_smplh.fbx --target APP\Mannequin\Base_Male.fbx ^
          --out-fbx clip_retargeted.fbx --out-glb clip_preview.glb

## Good footage

- One person, whole body in frame, feet visible.
- A fixed camera if possible.
- Plain clothing. Long skirts and coats hide the legs.
