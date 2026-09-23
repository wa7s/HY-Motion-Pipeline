"""Report a video's length, frame rate and size; optionally save one frame.

    python probe.py <video> [thumb.jpg] [at_seconds]

Prints one line:  RESULT {"duration": .., "fps": .., "width": .., "height": ..}

Runs in ComfyUI's embedded Python, which already has PyAV and Pillow - the
Studio exe itself carries neither.
"""
import json
import sys

import av

src = sys.argv[1]
thumb = sys.argv[2] if len(sys.argv) > 2 else ""
at = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

c = av.open(src)
vs = c.streams.video[0]
fps = float(vs.average_rate or vs.guessed_rate or 0) or 30.0
if c.duration:
    duration = float(c.duration) / av.time_base
elif vs.duration:
    duration = float(vs.duration * vs.time_base)
else:
    duration = 0.0
start = vs.start_time or 0
W, H = vs.codec_context.width, vs.codec_context.height

if thumb:
    at = max(0.0, min(at, max(duration - 0.05, 0.0)))
    c.seek(int(max(0.0, at - 1.0) / vs.time_base) + start, stream=vs, backward=True)
    last = None
    for fr in c.decode(vs):
        if fr.pts is None:
            continue
        last = fr
        if float((fr.pts - start) * vs.time_base) + 1e-3 >= at:
            break
    if last is not None:
        img = last.to_image()
        img.thumbnail((640, 640))
        img.save(thumb, quality=88)
c.close()

print("RESULT " + json.dumps({"duration": round(duration, 3), "fps": round(fps, 4),
                              "width": W, "height": H}), flush=True)
