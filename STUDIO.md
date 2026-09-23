# HY Motion Studio - user guide

A desktop app for AI character animation: text to motion with HY-Motion,
video to motion with GVHMR, a real 3D viewport, automatic retargeting onto
your character, and one-click hand-off to Blender, Cascadeur and Unity.

It drives your existing ComfyUI and Blender; it does not change either.
See the README for installation.

---

## Start it

Double-click **HY Motion Studio.exe** (in the `HY Motion Studio` folder of the
download), or make a desktop shortcut to it. No console, no browser.

The first time, **Edit > Preferences** opens so you can confirm where ComfyUI,
Blender and your character are. Anything it finds by itself shows a green dot.
The ComfyUI engine then starts hidden in the background on port 8189 and shuts
down when you close the window.

---

## One-button workflow

Press **Generate Animation** and this runs end to end:

```
prompt ─► HY-Motion (ComfyUI, hidden) ─► SMPL-H FBX + NPZ
       ─► Blender headless: retarget onto your character
       ─► FBX (pipeline) + GLB (viewport)
       ─► loads into the 3D viewport, playing
```

Verified timing on the RTX 4090 Laptop: **~41 s** generation for a 2.5 s clip,
plus ~15 s for the Blender retarget. The first run of a session adds ~50 s
while 13 GB of models load.

---

## Video → animation (motion capture)

At the top of the left panel, set **Make animation from** to **Video**. Then:

1. **Choose video...** Any mp4, mov, webm, mkv or avi works. A frame from
   the video appears, with its length and frame rate.
2. Set **Start** and **End** in seconds. The preview frame follows Start.
   **Use whole video** takes all of it. The app shows how long the job will
   take (roughly half a second per video frame; the first run of a session is slower).
3. **Camera:** *Fixed* for a tripod or locked-off shot, *Moving* for
   handheld or panning footage.
4. Set **Hands** if you want them. Video capture records the body only.
5. Press **Make Animation from Video**. The button becomes **Cancel** while
   the job runs.

```
video ─► cut + downscale ─► find the person on every frame ─► GVHMR capture
      ─► build a skeleton like HY-Motion's ─► retarget onto the mannequin
      ─► FBX + GLB, playing in the viewport, added to History
```

Files land in the current project: the cut clip and a person-tracking check
sheet in `Input/`, the capture in `Generated/`, and the character FBX and GLB
in `Blender/`. Blender, Cascadeur and export buttons work on it as usual.

Before capture the app tells the engine to drop HY-Motion's cached models,
because both won't fit on a 16 GB card together. The next text generation
reloads them, which adds the usual first-run wait.

**Good footage:** one person, whole body and feet in view, plain clothing.
Long skirts and coats hide the legs.

**Reference / previs only.** GVHMR and the SMPL-X body model are licensed for
research and non-commercial use. Keyframe over the result in Cascadeur before
anything ships.

---

## The window

| Area | Contents |
|---|---|
| **Left** | Project, **Make animation from** (Text / Video). Text: characters, presets, prompt, duration, model, seed, guidance, encoder, CPU offload. Video: file, preview frame, start/end, camera. Both: hands, then the go button |
| **Centre** | Real-time 3D viewport + transport |
| **Right** | Target rig, skeleton mapping, Blender/Cascadeur hand-off, export options, last result |
| **Bottom** | Status, progress, log |

### Viewport

Real GPU-skinned three.js rendering inside the app — orbit (drag), zoom
(wheel), pan (right-drag), shadows, ground grid.

| Control | What it does |
|---|---|
| Play / pause | transport |
| Timeline | scrub frame by frame |
| Frame readout | `frame / total   seconds` |
| FPS | live render rate |
| View mode | Character + skeleton / Character only / Skeleton only |
| **Follow** | keeps a travelling character in shot, preserving your orbit angle |
| Grid | ground plane on/off |
| Reset view | reframe on the character |

The last clip is restored when you reopen the app.

---

## Presets

Nineteen built-in prompts, tuned with per-preset durations:

| Combat | Movement | Animation |
|---|---|---|
| Punch, Hook punch, Kick, Sword attack, Dodge, Block, Knockback | Walk, Run, Jump, Climb, Crouch walk, Roll | Idle, Combat idle, Dance, Gesture, Sit down, Victory |

Double-click one to load it. **Save current** stores your own under any
category; **Delete** removes user presets (built-ins are protected). User
presets live in `presets.json`, so built-ins can still be updated.

---

## Projects

Every generation files itself:

```
Projects/<Project>/
    Input/        your own reference files
    Generated/    raw SMPL-H FBX + NPZ from HY-Motion
    Blender/      retargeted FBX + preview GLB
    Cascadeur/    clips sent to Cascadeur
    Exports/      final FBX for Unity
```

Create projects with **New**. **Open project folder** jumps straight there.

---

## Retargeting

HY-Motion always produces **SMPL-H, 52 joints, 30 fps, metres**. That is the
source; the target rig is whatever you point at.

| Profile | Rig | Detection |
|---|---|---|
| `ue5` / `ue4` | Unreal skeletons (`pelvis`, `spine_01` …) - including the bundled CC0 mannequins | automatic |
| `biped` | 3ds Max Biped (`Bip001 …`) | automatic |
| `mixamo` | Mixamo characters (`mixamorig:…`) | automatic |
| `unity` | Unity-Humanoid-named rigs | automatic |
| `smplh` | SMPL-H itself | automatic |

Leave **Skeleton mapping** on `auto` — it scores bone-name matches and picks
the best profile. On the bundled mannequins it maps 51 of 51 pairs.

### How the retarget works

The full method is in the header of `blender/hym_retarget.py`. In short:

- The two rigs' worlds are related by a **turn about the vertical only**,
  taken from each rig's rest hip line. Gravity is never tilted.
- Rotations are copied as *change from rest*, converted into the target's
  world.
- **Arms, hands and legs** are aimed so each joint lands exactly on the
  source's direction.
- **Spine and neck** carry the source's change from rest, measured against
  the pelvis. Different skeletons put the spine joints in very different
  places, so copying absolute angles bends an upright person forward.
- On the Biped the thighs hang off the lower-spine bone. Its twist follows
  the source's hips.

Bones with no mapping (twists, `Nub` tips) inherit their parent's motion and
keep their rest offset, so the rig stays coherent. Everything is solved
analytically and baked in one pass.

Checked on 23 September 2026 against six clips and a real video, in world
space: limbs within about 1° of the source, spine change within 0.7°, and the
walking direction right on every clip.

**Scale** comes from leg length (hip→knee→ankle), not hip height: the SMPL
rig's rest pelvis sits *below* its armature origin, so hip height yields a
negative ratio and mirrored root motion. 

**Ground** is anchored by measuring the source's lowest foot across the whole
clip and placing the target's feet at its own rest foot height, instead of
offsetting from rest — otherwise the character floats about 1.3 m in the air.

Both of those were real bugs found and fixed during the build, and both produce
plausible-looking files rather than obvious errors, so they are worth knowing
about if you ever swap in a different rig.

---

## Blender

Uses `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` headless for
retargeting and Unity conditioning, and `blender-launcher.exe` for the
interactive button.

| Button | Result |
|---|---|
| **Open in Blender** | opens Blender with the retargeted clip imported |
| **Export Blender FBX** | save the retargeted FBX wherever you like |
| **Export Unity FBX (SMPL-H)** | renames SMPL-H → Unity Humanoid, fixes axes; optional finger strip (52 → 22 bones) |

---

## Cascadeur

**Send to Cascadeur** copies the retargeted FBX into `Projects/<name>/Cascadeur/`
and opens it in `C:\Program Files\Cascadeur\cascadeur.exe`.

Cascadeur remains the cleanup step. The order that matters:

1. **Check the scene scale on import.** Cascadeur works in centimetres, the FBX
   is in metres. Its solver is gravity-aware, so a unit error gives physically
   wrong motion, not a small offset.
2. **Rigging → Quick Rig**, then fix **ground contact first** — foot sliding is
   most of what reads as "AI animation".
3. **AutoPhysics on ballistic sections only** (jumps, knockbacks). Running it
   over grounded sections undoes your pinning.
4. **Centre-of-mass trajectory** is where the weight comes from. Generated
   motion reads light by default.

Full checklist: `cascadeur/CHECKLIST.md`.

---

## Rebuilding the exe

```
HY-Motion-Pipeline\build.bat
```

Packages the Qt front end with PyInstaller into
`HY-Motion-Pipeline\HY Motion Studio\`. About 558 MB on disk (Qt + Chromium),
launches with no console.

Blender, Cascadeur and ComfyUI are **not** bundled — the exe drives the copies
already installed, and finds the ComfyUI portable by walking up from wherever
it is run, so you can move the folder.

Build environment (created once, isolated from both your system Python and
ComfyUI's embedded Python):

```
py -3.11 -m venv app\.venv
app\.venv\Scripts\python -m pip install PySide6 numpy pyinstaller
```

---

## Architecture

```
HY Motion Studio.exe          PySide6 + QtWebEngine, no console
  │
  ├─ hymstudio/config.py      paths, tool discovery, settings.json
  ├─ hymstudio/pipeline.py    engine, Blender, Cascadeur, projects
  ├─ hymstudio/presets.py     preset library
  ├─ hymstudio/theme.py       dark stylesheet
  ├─ hymstudio/main.py        window, viewport host, worker thread
  └─ viewer/                  three.js viewport (bundled, offline)
        │
        ├── HTTP on 127.0.0.1 (random port, localhost only)
        └── GLB from the Blender retarget step

ComfyUI (embedded Python 3.13, port 8189)  ──► HY-Motion 1.0
Blender 5.2 headless                       ──► retarget / Unity FBX
Cascadeur 2026.1.3                         ──► cleanup
```

Three details worth knowing if the viewport ever misbehaves:

- The viewport is served over HTTP, not `file://`, because Chromium blocks ES
  modules on `file://`. It binds to 127.0.0.1 on a random port.
- `.js` is served with an explicit `application/javascript` type. Windows
  registers `.js` as `text/plain` in HKCR, and Chromium then refuses to execute
  module scripts.
- Viewport JS errors are piped into the app log, which is how both of the above
  were found. If the viewport is blank, look there first.

---

## Performance

Unchanged from the working setup: **Qwen3-8B at 4-bit**, **HY-Motion-1.0 full**,
about 11 GB of your 16 GB. If you hit OOM: tick **Offload text encoder to CPU**,
switch **Model** to `HY-Motion-1.0-Lite`, or shorten the clip.

The app's engine runs on port **8189**, so a ComfyUI you start yourself on 8188
is untouched. Don't run heavy image generation at the same time though —
16 GB won't hold both.

---

## What the old app was

`app/MotionStudio.pyw` (tkinter, 2D stick-figure preview) is still there and
still works. Studio 2.0 supersedes it: real 3D, real character, retargeting,
projects, presets and the DCC hand-offs. Nothing depends on the old one.
