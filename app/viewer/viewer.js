/*
 * HY Motion Studio - 3D viewport.
 *
 * Plays up to two retargeted characters on one shared timeline. Each actor is
 * an independently loaded GLB with its own AnimationMixer, placed in the scene
 * by the host, so a two-character shot is staged rather than baked together.
 *
 * The Qt host drives everything through window.hym.* and polls
 * window.hym.state() for the timeline, FPS and per-actor readouts.
 */
import * as THREE from './vendor/three.module.min.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { OrbitControls } from './vendor/OrbitControls.js';

const canvas = document.getElementById('c');
const hud = document.getElementById('hud');
const msg = document.getElementById('msg');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
// Blender's default viewport grey, so clips read the same here as there.
const BG = 0x393939;
scene.background = new THREE.Color(BG);
scene.fog = new THREE.Fog(BG, 16, 44);

const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 400);
camera.position.set(2.6, 1.7, 3.4);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 0.95, 0);
controls.maxPolarAngle = Math.PI * 0.495;
controls.minDistance = 0.6;
controls.maxDistance = 40;

// --- lighting -------------------------------------------------------------
scene.add(new THREE.HemisphereLight(0xaebfd4, 0x2a2f36, 1.05));
const key = new THREE.DirectionalLight(0xffffff, 2.0);
key.position.set(3.5, 6.5, 4.0);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
const sc = key.shadow.camera;
sc.near = 0.5; sc.far = 40; sc.left = -8; sc.right = 8; sc.top = 8; sc.bottom = -8;
key.shadow.bias = -0.0015;
scene.add(key);
const rim = new THREE.DirectionalLight(0x6f8cff, 0.65);
rim.position.set(-4, 2.5, -4);
scene.add(rim);

// --- ground ---------------------------------------------------------------
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(80, 80),
  new THREE.ShadowMaterial({ opacity: 0.38 })
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const grid = new THREE.GridHelper(40, 40, 0x4a4a4a, 0x444444);
grid.material.transparent = true;
grid.material.opacity = 0.9;
scene.add(grid);
// Blender-style floor axes: red = X, green = forward (Blender's Y).
const axes = new THREE.Group();
for (const [dir, col] of [[new THREE.Vector3(1, 0, 0), 0xb8404f],
                          [new THREE.Vector3(0, 0, 1), 0x7a9c2e]]) {
  const g = new THREE.BufferGeometry().setFromPoints(
    [dir.clone().multiplyScalar(-20), dir.clone().multiplyScalar(20)]);
  const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: col }));
  line.position.y = 0.001;
  axes.add(line);
}
scene.add(axes);

// --- viewport state -------------------------------------------------------
let playing = false, fps = 30, clipFps = 30, t = 0;
let meshVisible = true, skelVisible = false;
let follow = true, restMode = false;
const clock = new THREE.Clock();
const _fv = new THREE.Vector3(), _fprev = new THREE.Vector3(),
      _fd = new THREE.Vector3();
let followActor = null;
// Set whenever the timeline jumps rather than advances, so the follow
// camera re-anchors instead of chasing the jump.
let followResync = false;

// --- actors ---------------------------------------------------------------
// Slot 0 is C1, slot 1 is C2. Each keeps its own mixer so the two clips can
// differ in length and start at different times.
const TINT = [null, 0x8fb0ff];        // C2 gets a tint so they read apart
const loader = new GLTFLoader();
const actors = [null, null];
// Staging asked for before the GLB finished loading, applied on arrival.
const pending = [null, null];

// The stock skeleton helper, minus the line from a static `root` bone.
// Unreal-style rigs keep `root` at the origin while the body travels, so the
// stock helper draws a long line from the world origin to the hips that looks
// like a broken bone.
class BodySkeletonHelper extends THREE.SkeletonHelper {
  constructor(object) {
    super(object);
    const isStaticRoot = (b) => b && b.isBone && /^root$/i.test(b.name) &&
                                !(b.parent && b.parent.isBone);
    const keep = this.bones.filter((b) => !isStaticRoot(b.parent));
    if (keep.length === this.bones.length) return;
    this.bones = keep;
    const n = keep.filter((b) => b.parent && b.parent.isBone).length;
    const col = new Float32Array(n * 6);
    for (let i = 0; i < n; i++) col.set([0, 0, 1, 0, 1, 0], i * 6);   // stock blue -> green
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(n * 6), 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    this.geometry.dispose();
    this.geometry = g;
  }
}

function makeActor(gltf, slot) {
  const root = gltf.scene;
  const holder = new THREE.Group();     // staging transform lives here
  holder.add(root);
  scene.add(holder);

  root.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = true;
    o.frustumCulled = false;            // skinned bounds go stale otherwise
    if (o.material) {
      o.material = o.material.clone();
      o.material.side = THREE.FrontSide;
      if (TINT[slot] != null && o.material.color) {
        o.material.color.setHex(TINT[slot]);
      }
    }
  });

  const skel = new BodySkeletonHelper(root);
  skel.visible = skelVisible;
  holder.add(skel);

  let mixer = null, action = null, duration = 0;
  if (gltf.animations && gltf.animations.length) {
    mixer = new THREE.AnimationMixer(root);
    action = mixer.clipAction(gltf.animations[0]);
    action.play();
    duration = gltf.animations[0].duration;
  }

  // The bone the follow camera tracks. On Unreal-style rigs the top bone is a
  // `root` that stays at the origin, so track its child (the hips) instead.
  let rootBone = null;
  root.traverse((o) => {
    if (!rootBone && o.isBone && !(o.parent && o.parent.isBone)) rootBone = o;
  });
  if (rootBone && /^root$/i.test(rootBone.name)) {
    const hips = rootBone.children.find((c) => c.isBone);
    if (hips) rootBone = hips;
  }

  return { holder, root, skel, mixer, action, duration, rootBone,
           delay: 0, place: { x: 0, z: 0, yaw: 0 } };
}

function disposeActor(slot) {
  const a = actors[slot];
  if (!a) return;
  scene.remove(a.holder);
  if (a.mixer) a.mixer.stopAllAction();
  actors[slot] = null;
  pending[slot] = null;
  if (followActor === a) followActor = null;
}

function anyActor() { return actors[0] || actors[1]; }

function totalDuration() {
  let d = 0;
  for (const a of actors) if (a) d = Math.max(d, a.delay + a.duration);
  return d;
}

/*
 * Box3.setFromObject() on a SkinnedMesh measures the geometry in bind pose
 * through the mesh's own (usually identity) transform, which for this rig
 * reports a ~0.3 unit blob instead of a 1.8 m figure. Framing from that puts
 * the camera inside the mesh, and with front-face culling the character then
 * appears to be missing entirely. Measuring the bones instead gives the real
 * extents.
 */
function modelBox(obj) {
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  let bones = 0;
  obj.updateWorldMatrix(true, true);
  obj.traverse((o) => {
    if (!o.isBone) return;
    // a static `root` bone sits at the origin, not on the body
    if (/^root$/i.test(o.name) && !(o.parent && o.parent.isBone)) return;
    box.expandByPoint(o.getWorldPosition(v)); bones++;
  });
  if (bones < 2) box.setFromObject(obj);
  return box;
}

function frameCamera() {
  const box = new THREE.Box3();
  for (const a of actors) if (a) box.union(modelBox(a.holder));
  if (box.isEmpty() || !isFinite(box.min.x)) return;
  const size = box.getSize(new THREE.Vector3());
  const ctr = box.getCenter(new THREE.Vector3());
  const h = Math.max(size.y, 0.5);
  const spread = Math.max(size.x, size.z, h);
  const dist = Math.max(h * 2.3, spread * 1.7);
  controls.target.set(ctr.x, ctr.y, ctr.z);
  camera.position.set(ctr.x + dist * 0.62, ctr.y + h * 0.22, ctr.z + dist * 0.85);
  camera.near = Math.max(h / 200, 0.01);
  camera.far = Math.max(dist * 40, 400);
  camera.updateProjectionMatrix();
  controls.update();
  followActor = actors[0] || actors[1];
  if (followActor && followActor.rootBone) {
    followActor.rootBone.getWorldPosition(_fprev);
  }
}

function applyVisibility() {
  for (const a of actors) {
    if (!a) continue;
    a.root.traverse((o) => { if (o.isMesh) o.visible = meshVisible; });
    a.skel.visible = skelVisible;
  }
}

function applyPlacement(a) {
  a.holder.position.set(a.place.x, 0, a.place.z);
  a.holder.rotation.set(0, THREE.MathUtils.degToRad(a.place.yaw), 0);
  a.holder.updateMatrixWorld(true);
}

/* Drive every mixer from one shared clock, so the actors stay in lockstep
   however the host scrubs. */
function applyTime(time) {
  const dur = Math.max(totalDuration(), 0.0001);
  t = Math.max(0, Math.min(time, dur));
  for (const a of actors) {
    if (!a || !a.mixer) continue;
    const local = Math.max(0, Math.min(t - a.delay, a.duration));
    a.mixer.setTime(local);
  }
}

window.hym = {
  /* slot: 0 = C1, 1 = C2 */
  load(url, fpsHint, slot) {
    slot = slot | 0;
    clipFps = fpsHint || 30;
    msg.textContent = 'Loading...';
    msg.classList.remove('err');
    loader.load(url + '?t=' + Date.now(), (gltf) => {
      disposeActor(slot);
      const a = makeActor(gltf, slot);
      actors[slot] = a;
      const q = pending[slot];
      if (q) {
        a.place.x = q.x; a.place.z = q.z; a.place.yaw = q.yaw;
        a.delay = q.delay;
        pending[slot] = null;
      }
      applyPlacement(a);
      applyVisibility();
      restMode = false;
      applyTime(0);
      frameCamera();
      followResync = true;
      playing = true;
      msg.textContent = '';
    }, undefined, (err) => {
      msg.textContent = 'Could not load the animation.\n' + err;
      msg.classList.add('err');
    });
  },

  clearSlot(slot) {
    disposeActor(slot | 0);
    if (!anyActor()) { msg.textContent = 'No animation loaded.'; }
    else frameCamera();
  },

  clearAll() {
    disposeActor(0); disposeActor(1);
    playing = false;
    msg.textContent = 'No animation loaded.';
  },

  /* Live staging for two-character shots - no re-render needed. */
  setPlacement(slot, x, z, yawDeg) {
    slot = slot | 0;
    const a = actors[slot];
    if (!a) {
      const q = pending[slot] || { x: 0, z: 0, yaw: 0, delay: 0 };
      q.x = x; q.z = z; q.yaw = yawDeg;
      pending[slot] = q;
      return;
    }
    a.place.x = x; a.place.z = z; a.place.yaw = yawDeg;
    applyPlacement(a);
  },

  /* Delay an actor's entry, so C2 reacts after C1 connects. */
  setDelay(slot, seconds) {
    slot = slot | 0;
    const v = Math.max(0, seconds || 0);
    const a = actors[slot];
    if (!a) {
      const q = pending[slot] || { x: 0, z: 0, yaw: 0, delay: 0 };
      q.delay = v;
      pending[slot] = q;
      return;
    }
    a.delay = v;
    applyTime(t);
  },

  play()  { if (totalDuration() > 0) { restMode = false; playing = true; } },
  pause() { playing = false; },
  toggle() {
    if (totalDuration() <= 0) return false;
    if (restMode) { window.hym.resume(); return true; }
    playing = !playing;
    return playing;
  },

  setTime(time) {
    if (restMode) window.hym.resume();
    playing = false;
    applyTime(time);
  },

  /* Stop and show the characters in the rig's own rest pose - a neutral
     reference to judge a generated clip against. */
  restPose() {
    playing = false;
    restMode = true;
    for (const a of actors) {
      if (!a) continue;
      if (a.action) { a.action.stop(); }
      if (a.mixer) { a.mixer.stopAllAction(); a.mixer.update(0); }
      a.root.updateMatrixWorld(true);
    }
    frameCamera();
  },

  resume() {
    restMode = false;
    for (const a of actors) {
      if (!a || !a.action) continue;
      a.action.reset();
      a.action.play();
    }
    applyTime(t);
    playing = true;
  },

  /* 'character' | 'skeleton' | 'both' */
  setMode(m) {
    meshVisible = (m !== 'skeleton');
    skelVisible = (m !== 'character');
    applyVisibility();
  },

  resetView() { frameCamera(); },

  setGrid(on) { grid.visible = !!on; axes.visible = !!on; ground.visible = !!on; },

  setFollow(on) {
    follow = !!on;
    if (follow && followActor && followActor.rootBone) {
      followActor.rootBone.getWorldPosition(_fprev);
    }
  },

  state() {
    const dur = totalDuration();
    return {
      ready: !!anyActor(),
      hasAnim: dur > 0,
      duration: dur,
      time: t,
      playing: playing,
      rest: restMode,
      fps: fps,
      frames: Math.max(1, Math.round(dur * clipFps)),
      clipFps: clipFps,
      follow: follow,
      actors: [!!actors[0], !!actors[1]]
    };
  }
};

// --- loop -----------------------------------------------------------------
let frameCount = 0, acc = 0;
function tick() {
  requestAnimationFrame(tick);
  const dt = clock.getDelta();

  frameCount++; acc += dt;
  if (acc >= 0.5) { fps = Math.round(frameCount / acc); frameCount = 0; acc = 0; }

  const dur = totalDuration();
  if (playing && dur > 0 && !restMode) {
    let nt = t + dt;
    if (nt > dur) nt -= dur;             // loop the whole shot, camera rides along
    applyTime(nt);
  }

  if (follow && !restMode && followActor && followActor.rootBone) {
    followActor.rootBone.getWorldPosition(_fv);
    if (followResync) {
      _fprev.copy(_fv);                  // new clip: re-anchor, don't lurch
      followResync = false;
    } else {
      _fd.subVectors(_fv, _fprev);
      _fd.y = 0;                         // vertical bob would make it seasick
      if (_fd.lengthSq() > 1e-12) {
        controls.target.add(_fd);
        camera.position.add(_fd);
      }
      _fprev.copy(_fv);
    }
  }

  controls.update();

  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w || canvas.height !== h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }
  renderer.render(scene, camera);

  const st = window.hym.state();
  hud.innerHTML = st.ready
    ? `<b>${st.fps}</b> fps &nbsp;·&nbsp; ${st.time.toFixed(2)}s / ${st.duration.toFixed(2)}s`
      + (st.rest ? ' &nbsp;·&nbsp; <b>rest pose</b>' : '')
      + (st.actors[1] ? ' &nbsp;·&nbsp; 2 characters' : '')
    : '';
}
tick();

// Diagnostics: what the loader actually built, and where the camera ended up.
window.__dbg = function () {
  const r = (v) => v.toArray().map((n) => +n.toFixed(2));
  const out = { cam: r(camera.position), target: r(controls.target),
                meshVisible, skelVisible, rest: restMode, actors: [] };
  actors.forEach((a, i) => {
    if (!a) { out.actors.push(null); return; }
    const box = modelBox(a.holder);
    let meshes = 0, bones = 0;
    a.root.traverse((o) => { if (o.isMesh) meshes++; if (o.isBone) bones++; });
    out.actors.push({ slot: i, meshes, bones, duration: +a.duration.toFixed(2),
                      delay: a.delay, place: a.place,
                      box: { min: r(box.min), max: r(box.max) } });
  });
  return out;
};
