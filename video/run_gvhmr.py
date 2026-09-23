"""Submit a GVHMR video->motion job to the running ComfyUI and wait for it."""
import json, sys, time, urllib.request, urllib.error

HOST = "http://127.0.0.1:8189"
clip, mask = sys.argv[1], sys.argv[2]
moving = (sys.argv[3].lower() == "moving") if len(sys.argv) > 3 else False


def get(path):
    return json.loads(urllib.request.urlopen(HOST + path, timeout=60).read())


info = get("/object_info")
spec = info["LoadVideo"]["input"]["required"]["file"]
# old-style combo is [ [options...] ], new-style is ["COMBO", {"options": [...]}]
files = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
for f in (clip, mask):
    if f not in files:
        print("NOT IN LoadVideo LIST:", f)
        print("  available:", [x for x in files if "mocap" in x])
        sys.exit(1)

# Something has to be an output node or ComfyUI will not execute the graph.
sink = None
for cand in ("PreviewAny", "SMPLViewer"):
    if cand in info and info[cand].get("output_node"):
        sink = cand
        break
print("output sink:", sink, "| GVHMRInference output_node:",
      info["GVHMRInference"].get("output_node"))

wf = {
    "1": {"class_type": "LoadVideo", "inputs": {"file": clip}},
    "2": {"class_type": "LoadVideo", "inputs": {"file": mask}},
    "3": {"class_type": "LoadGVHMRModels",
          "inputs": {"model_path_override": "", "precision": "auto",
                     "attention": "auto", "load_dpvo": False}},
    "4": {"class_type": "GVHMRInference",
          "inputs": {"video": ["1", 0], "video_mask": ["2", 0], "config": ["3", 0],
                     "moving_camera": moving, "focal_length_mm": 0,
                     "bbox_scale": 1.2, "vo_method": "simple_vo",
                     "vo_scale": 0.5, "vo_step": 8, "chunk_size": 16}},
}
if sink == "PreviewAny":
    wf["5"] = {"class_type": "PreviewAny", "inputs": {"source": ["4", 2]}}
    wf["6"] = {"class_type": "PreviewAny", "inputs": {"source": ["4", 0]}}
elif sink == "SMPLViewer":
    req = info["SMPLViewer"]["input"]["required"]
    ins = {"npz_path": ["4", 0]}
    for k, v in req.items():
        if k != "npz_path" and isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict):
            ins[k] = v[1].get("default")
    wf["5"] = {"class_type": "SMPLViewer", "inputs": ins}

req = urllib.request.Request(HOST + "/prompt", data=json.dumps({"prompt": wf}).encode(),
                             headers={"Content-Type": "application/json"})
try:
    pid = json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
except urllib.error.HTTPError as e:
    print("SUBMIT FAILED:", e.read().decode()[:3000])
    sys.exit(1)
print("queued", pid, "| moving_camera =", moving, flush=True)

t0 = time.time()
while time.time() - t0 < 3600:
    h = get("/history/" + pid)
    if pid in h:
        st = h[pid].get("status", {})
        print("status:", st.get("status_str"), "| %.0fs" % (time.time() - t0))
        for m in st.get("messages", []):
            if m[0] in ("execution_error",):
                p = m[1]
                print("ERROR in", p.get("node_type"), ":", p.get("exception_message"))
                tb = p.get("traceback") or []
                print("".join(tb[-8:]) if isinstance(tb, list) else tb)
        outs = h[pid].get("outputs", {})
        print("outputs:", json.dumps(outs, indent=1)[:2500])
        break
    time.sleep(5)
