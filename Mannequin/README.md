# Characters

The motion is put onto a rigged character. Two come with the app:

| File | What it is |
|---|---|
| `Base_Male.fbx` | Grey male mannequin (65 bones, Unreal-style skeleton) |
| `Base_Female.fbx` | Grey female mannequin (same skeleton) |

Both are the **Universal Base Characters** by **Quaternius**, released under
**CC0 1.0** (public domain): free for any use, including commercial, with no
credit required. See `Quaternius_License.txt` and
<https://quaternius.com/packs/universalbasecharacters.html>.
The only change made here: the textures (which pointed at files on the
author's own computer) were replaced by one plain grey material. The mesh,
skin weights and skeleton are untouched.

## Using your own character

Choose any rigged FBX in **Edit › Preferences › File Paths › Character FBX**,
or in the **Clips › Character** panel. Supported skeletons:

- **Mixamo** (`mixamorig:Hips`, `mixamorig:Spine` ...), any prefix
- **Unreal Engine** UE4 / UE5 (`pelvis`, `spine_01`, `thigh_l` ...), e.g. Manny and Quinn
- **3ds Max Biped** (`Bip001 Pelvis` ...)
- **Unity Humanoid** names (`Hips`, `LeftUpperArm` ...)

An FBX you drop into this folder is offered automatically when no character
is set.
