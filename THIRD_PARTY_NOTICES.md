# Third-party notices

HY Motion Studio's own code is released under the GNU GPL v3 (see `LICENSE`).
It ships no AI model weights.

## Bundled with the app

| Component | Licence | Notes |
|---|---|---|
| [three.js](https://threejs.org) r160 (`app/viewer/vendor`) | MIT | Copyright 2010-2023 three.js authors |
| [Qt for Python / PySide6](https://doc.qt.io/qtforpython/) | LGPL-3.0 | Loaded as separate DLLs in the exe folder, so you can replace them |
| [NumPy](https://numpy.org) | BSD-3-Clause | |
| [PyInstaller](https://pyinstaller.org) bootloader | GPL-2.0 with bootloader exception | Only used to build the exe |
| **Universal Base Characters** by [Quaternius](https://quaternius.com) (`Mannequin/Base_*.fbx`) | CC0 1.0 (public domain) | Textures replaced with a plain grey material; see `Mannequin/Quaternius_License.txt` |

### three.js - MIT licence

```
The MIT License

Copyright © 2010-2023 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Not bundled - you install these yourself

Each has its own licence. **Read them before you use the output in a product.**

| Component | Licence (summary - read the original) |
|---|---|
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | GPL-3.0 |
| [ComfyUI-HY-Motion1](https://github.com/jtydhr88/ComfyUI-HY-Motion1) nodes | MIT |
| [HY-Motion 1.0](https://huggingface.co/tencent/HY-Motion-1.0) model (Tencent) | Tencent Hunyuan Community Licence - its territory excludes the EU, the UK and South Korea, and very large products need a separate licence |
| [ComfyUI-MotionCapture](https://github.com/PozzettiAndrea/ComfyUI-MotionCapture) nodes | GPL-3.0 |
| [GVHMR](https://github.com/zju3dv/GVHMR) model | Non-commercial / research use |
| [SMPL-X](https://smpl-x.is.tue.mpg.de) body model | Non-commercial / research use, registration required |
| [Blender](https://www.blender.org) | GPL |
| [Cascadeur](https://cascadeur.com) | Proprietary (Nekki) |

HY Motion Studio is an independent community project. It is not affiliated
with or endorsed by Tencent, the Blender Foundation, Nekki, Quaternius or the
authors of the tools above.
