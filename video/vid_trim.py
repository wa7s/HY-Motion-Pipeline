"""Cut a segment out of a video and downscale it, re-encoding to H.264 MP4.

    python vid_trim.py <in> <out.mp4> <start_s> <end_s> [max_side=1280]

The longer side is brought down to max_side (never up), so a 4K landscape
clip becomes 1280x720 and a phone portrait clip 720x1280. Motion capture
works on crops around the performer, so more pixels only cost time.

Frames are rebuilt from plain RGB pixels before encoding. Passing decoded
frames straight through carries the source's colour metadata (a 4K VP9
master, for instance), which libx264 rejects with EINVAL at open.

Prints one line:  RESULT {"frames": .., "fps": .., "width": .., "height": ..}
"""
import json
import sys
from fractions import Fraction

import av

src, dst = sys.argv[1], sys.argv[2]
t0, t1 = float(sys.argv[3]), float(sys.argv[4])
max_side = int(sys.argv[5]) if len(sys.argv) > 5 else 1280

inp = av.open(src)
vs = inp.streams.video[0]
fps = Fraction(vs.average_rate) if vs.average_rate else Fraction(24000, 1001)
W0, H0 = vs.codec_context.width, vs.codec_context.height
k = min(1.0, max_side / float(max(W0, H0)))
W = max(2, int(round(W0 * k / 2)) * 2)
H = max(2, int(round(H0 * k / 2)) * 2)
start = vs.start_time or 0

out = av.open(dst, mode="w")
st = out.add_stream("libx264", rate=fps)
st.width, st.height, st.pix_fmt = W, H, "yuv420p"
st.options = {"crf": "18", "preset": "medium"}

inp.seek(int(max(0.0, t0 - 1.0) / vs.time_base) + start, stream=vs, backward=True)
n = 0
for fr in inp.decode(vs):
    if fr.pts is None:
        continue
    t = float((fr.pts - start) * vs.time_base)
    if t < t0:
        continue
    if t >= t1:
        break
    rgb = fr.reformat(width=W, height=H, format="rgb24").to_ndarray()
    clean = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format="yuv420p")
    for pkt in st.encode(clean):
        out.mux(pkt)
    n += 1
for pkt in st.encode():
    out.mux(pkt)
out.close()
inp.close()
print("wrote %dx%d  %d frames  %.3f fps  %.2f s" % (W, H, n, float(fps), n / float(fps)))
print("RESULT " + json.dumps({"frames": n, "fps": float(fps), "width": W, "height": H}),
      flush=True)
if n == 0:
    sys.exit(2)
