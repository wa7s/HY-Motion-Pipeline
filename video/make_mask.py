"""Person mask video for GVHMR: white person on black, one mask per frame.

GVHMR needs to know where the performer is on every frame. The author's
workflow uses SAM3 for that; torchvision's Mask R-CNN (already present in the
ComfyUI environment) does the same job for a single performer. On each frame
the largest confident person instance is kept, so audience silhouettes at the
edge of the frame (a crowd, a passer-by) are ignored.

Also writes a small overlay sheet so the tracking can be checked by eye.
"""
import sys
from fractions import Fraction

import av
import numpy as np
import torch
import torchvision
from torchvision.models.detection import (maskrcnn_resnet50_fpn_v2,
                                          MaskRCNN_ResNet50_FPN_V2_Weights)

src, dst, sheet = sys.argv[1], sys.argv[2], sys.argv[3]
# usage: python make_mask.py <clip.mp4> <mask_out.mp4> <check_sheet.jpg>
# Prints one line:  RESULT {"frames": .., "misses": .., "coverage": ..}

dev = "cuda" if torch.cuda.is_available() else "cpu"
w = MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT
model = maskrcnn_resnet50_fpn_v2(weights=w).eval().to(dev)
PERSON = 1   # COCO category id

inp = av.open(src)
vs = inp.streams.video[0]
fps = Fraction(vs.average_rate)
W, H = vs.codec_context.width, vs.codec_context.height

out = av.open(dst, mode="w")
st = out.add_stream("libx264", rate=fps)
st.width, st.height, st.pix_fmt = W, H, "yuv420p"
st.options = {"crf": "8", "preset": "medium"}

kernel = torch.ones(1, 1, 9, 9, device=dev)
n, misses, area, samples = 0, 0, [], []
prev = None
with torch.no_grad():
    for fr in inp.decode(vs):
        rgb = fr.to_ndarray(format="rgb24")
        x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255).to(dev)
        r = model([x])[0]
        keep = (r["labels"] == PERSON) & (r["scores"] > 0.6)
        m = None
        if keep.any():
            masks = r["masks"][keep, 0]            # (k, H, W) soft
            areas = (masks > 0.5).flatten(1).sum(1)
            m = (masks[int(areas.argmax())] > 0.5).float()
            # small dilation so hands and hair at the silhouette edge stay in
            m = (torch.nn.functional.conv2d(m[None, None], kernel, padding=4)[0, 0] > 0).float()
            prev = m
        elif prev is not None:
            m = prev                                # hold the last good mask
            misses += 1
        else:
            m = torch.zeros(H, W, device=dev)
            misses += 1
        a = float(m.mean())
        area.append(a)
        mask8 = (m.cpu().numpy() * 255).astype(np.uint8)
        frame = av.VideoFrame.from_ndarray(np.dstack([mask8] * 3), format="rgb24")
        for pkt in st.encode(frame.reformat(format="yuv420p")):
            out.mux(pkt)
        if n % 24 == 0:
            ov = rgb.copy()
            sel = mask8 > 127
            ov[sel] = (0.45 * ov[sel] + 0.55 * np.array([60, 200, 255])).astype(np.uint8)
            samples.append(ov)
        n += 1
for pkt in st.encode():
    out.mux(pkt)
out.close()
inp.close()

# overlay sheet (aspect kept, so portrait clips are not squashed)
from PIL import Image
tw = 426
th = max(2, int(round(tw * H / float(W))))
thumbs = [Image.fromarray(x).resize((tw, th)) for x in samples[:8]]
if thumbs:
    cols = min(4, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    im = Image.new("RGB", (tw * cols, th * rows), (20, 20, 20))
    for k, t in enumerate(thumbs):
        im.paste(t, ((k % cols) * tw, (k // cols) * th))
    im.save(sheet, quality=85)

import json
area = np.array(area) if area else np.zeros(1)
print("device       :", dev)
print("frames       :", n)
print("no-detection :", misses, "(held previous mask)")
print("mask coverage: mean %.1f%%  min %.1f%%  max %.1f%%"
      % (area.mean() * 100, area.min() * 100, area.max() * 100))
print("RESULT " + json.dumps({"frames": n, "misses": misses, "device": dev,
                              "coverage": float(area.mean())}), flush=True)
if n == 0 or misses >= n:
    sys.exit(3)                  # nobody found on any frame
