// heatmap.js — 🕸 Bus history time-lapse.
//
// Self-contained, lazily imported (mirrors scene3d.js): a CDN miss or a throw
// in here can never touch the 2D board. No external deps — pure SVG.
//
// Fetches /api/bus/heatmap and replays it: sessions are nodes (on a ring, in a
// live force-cluster, or radial-by-volume) that fade in as each first speaks,
// mention-lines thicken with traffic, and a pulse-dot flies each wire on use,
// sized by message length.
//
// With the 👤 toggle it re-fetches ?human=1 and weaves in the HUMAN↔Claude
// layer — a [you] node plus prompt/reply turns from the transcripts, on the
// same scrubbable timeline (gold edges to distinguish them from the bus).
//
// Everything visible is a pure function of one scalar — `f`, progress in [0,1].
// Glow/pulse "recency" is `f - lastTouch`, not a timer, so scrubbing backward
// is a cheap replay from 0. No setTimeout anywhere.

const BASE_SECONDS = 45;   // wall-clock seconds for 1x to play the whole history
const GLOW_WINDOW = 0.045; // how long (in f-units) a node/edge stays "hot"
const SPEEDS = [0.25, 0.5, 1, 2, 5];
const LAYOUTS = [["clusters", "Clusters"], ["ring", "Ring"], ["orbit", "Orbit"]];
const LS_LAYOUT = "conductor.heatmapLayout";
const LS_HUMAN = "conductor.heatmapHuman";
const LS_3D = "conductor.heatmap3d";
// 3D rotation: weak perspective (camera distance) + gentle idle auto-spin.
const CAM_D = 1700;          // perspective distance; larger = subtler foreshortening
const SPIN_RATE = 0.18;      // idle auto-spin, radians/sec of yaw
const PITCH_LIMIT = 1.35;    // clamp drag pitch so the plane never flips past edge-on
const START_PITCH = -0.5;    // initial tilt when 3D turns on (so it reads as 3D at once)

let root = null;
let raf = 0;
let onResize = null;

function hueFor(tag) {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) % 360;
  return h;
}
const bare = (t) => t.replace(/^\[/, "").replace(/\]$/, "").replace(/^other:/, "");
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const svgEl = (n) => document.createElementNS("http://www.w3.org/2000/svg", n);

function fmtClock(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export async function activate() {
  if (root) return;
  root = document.createElement("div");
  root.className = "heatmap-overlay";
  root.innerHTML = `
    <div class="hm-header">
      <span class="hm-title">🕸 Bus history</span>
      <span class="hm-stats" id="hm-stats">loading…</span>
      <span class="hm-legend" id="hm-legend">line = how often · pulse size = message length</span>
      <button class="hm-close" title="Close (Esc)">×</button>
    </div>
    <svg class="hm-svg" id="hm-svg" aria-hidden="true">
      <defs>
        <filter id="hm-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <g id="hm-edges"></g>
      <g id="hm-pulses"></g>
      <g id="hm-nodes"></g>
    </svg>
    <div class="hm-controls">
      <div class="hm-layouts" id="hm-layouts" title="Arrange the sessions"></div>
      <button class="hm-3d" id="hm-3d" title="Rotate the graph in 3D — drag to orbit, it idles with a slow spin">🧊 3D</button>
      <button class="hm-human" id="hm-human" title="Weave in human ↔ Claude turns (your prompts + replies)">👤 Human</button>
      <button class="hm-play" id="hm-play" title="Play / pause">⏸</button>
      <input type="range" class="hm-scrub" id="hm-scrub" min="0" max="1000" value="0" />
      <span class="hm-clock" id="hm-clock">—</span>
      <div class="hm-speeds" id="hm-speeds"></div>
    </div>`;
  document.body.appendChild(root);

  root.querySelector(".hm-close").addEventListener("click", deactivate);
  const escClose = (e) => { if (e.key === "Escape") deactivate(); };
  document.addEventListener("keydown", escClose);
  root._escClose = escClose;

  run();
}

export function deactivate() {
  if (!root) return;
  cancelAnimationFrame(raf);
  raf = 0;
  if (onResize) { window.removeEventListener("resize", onResize); onResize = null; }
  if (root._escClose) document.removeEventListener("keydown", root._escClose);
  if (root._orbitMove) window.removeEventListener("pointermove", root._orbitMove);
  if (root._orbitUp) window.removeEventListener("pointerup", root._orbitUp);
  root.remove();
  root = null;
}

// One closure holds all controls, the rAF loop, and the swappable graph state.
function run() {
  const svg = root.querySelector("#hm-svg");
  const gEdges = root.querySelector("#hm-edges");
  const gPulses = root.querySelector("#hm-pulses");
  const gNodes = root.querySelector("#hm-nodes");
  const statsEl = root.querySelector("#hm-stats");
  const legendEl = root.querySelector("#hm-legend");
  const clockEl = root.querySelector("#hm-clock");
  const playBtn = root.querySelector("#hm-play");
  const scrub = root.querySelector("#hm-scrub");
  const layoutsEl = root.querySelector("#hm-layouts");
  const humanBtn = root.querySelector("#hm-human");

  // ---- persistent prefs -------------------------------------------------
  let mode = "clusters";
  try { const m = localStorage.getItem(LS_LAYOUT); if (m && LAYOUTS.some((l) => l[0] === m)) mode = m; } catch (_) {}
  let humanOn = false;
  try { humanOn = localStorage.getItem(LS_HUMAN) === "1"; } catch (_) {}

  // ---- 3D rotation state ------------------------------------------------
  // threeD off ⇒ project() is identity ⇒ the 2D graph is byte-for-byte unchanged.
  let threeD = false;
  try { threeD = localStorage.getItem(LS_3D) === "1"; } catch (_) {}
  let yaw = 0, pitch = threeD ? START_PITCH : 0;
  let orbitDrag = false, orbitMoved = false;
  let dragX0 = 0, dragY0 = 0, yaw0 = 0, pitch0 = 0;

  // ---- swappable graph state (reassigned by rebuild) --------------------
  let nodes = new Map();
  let edges = new Map();
  let events = [];
  let pos = [];
  let t0 = 0, t1 = 0, dropped = 0;
  let logMin = 0, logRange = 1, maxCount = 1, N = 0;

  // ---- playback state (survives a rebuild) ------------------------------
  let played = 0, f = 0, playing = true, lastTs = 0, speed = 1, dragging = false;

  // ---- drill-down (🔬 one prompt → its tool/file/agent fan-out) ----------
  let drillMod = null, drillHandle = null, drillOpen = false;

  // ---- geometry ---------------------------------------------------------
  let W = 0, H = 0, cx = 0, cy = 0, R = 0, innerR = 0;

  const bulkOf = (size) =>
    Math.min(1, Math.max(0, (Math.log(1 + (size || 0)) - logMin) / logRange));

  function measure() {
    const rect = svg.getBoundingClientRect();
    W = rect.width; H = rect.height;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    cx = W / 2; cy = H / 2;
    R = Math.max(80, Math.min(W, H) / 2 - 96);
    innerR = R * 0.26;
  }

  function computeTargets() {
    nodes.forEach((nd) => {
      const a = (-90 + (360 * nd.idx) / N) * (Math.PI / 180);
      let rad = R;
      if (mode === "orbit") {
        const loud = Math.log(1 + nd.count) / Math.log(1 + maxCount);
        rad = innerR + (R - innerR) * (1 - loud);
      }
      nd.tx = cx + rad * Math.cos(a);
      nd.ty = cy + rad * Math.sin(a);
      // Depth target (used only in 3D): ring stays flat (spin/tilt reveals it);
      // orbit lifts into a dome — loud sessions (small radius, centered) rise
      // toward the top, quiet ones sit on the rim.
      nd.tz = mode === "orbit" ? Math.sqrt(Math.max(0, R * R - rad * rad)) * 0.9 : 0;
      if (mode === "clusters") {
        nd.ldx = 10; nd.ldy = -2; nd.lanchor = "start";
      } else {
        nd.ldx = Math.cos(a) * 13; nd.ldy = Math.sin(a) * 13;
        nd.lanchor = Math.cos(a) > 0.25 ? "start" : Math.cos(a) < -0.25 ? "end" : "middle";
      }
    });
  }

  function seedRing() {
    nodes.forEach((nd) => {
      const a = (-90 + (360 * nd.idx) / N) * (Math.PI / 180);
      nd.x = cx + R * Math.cos(a); nd.y = cy + R * Math.sin(a);
      nd.vx = 0; nd.vy = 0;
    });
  }

  // Live force-directed step (Clusters mode). ~30-40 nodes → trivially cheap.
  function forceStep() {
    const REP = 7000, SPRING = 0.0012, GRAV = 0.006, DAMP = 0.80, REST = 78, MAXV = 22;
    // In 3D, the sim gains a real z axis so clumps spread into depth; the z
    // gravity pulls gently toward the z=0 plane so it stays a slab, not a sphere.
    const D3 = threeD, ZLIM = R * 0.7, ZGRAV = 0.012;
    const live = [];
    nodes.forEach((nd) => { nd.fx = 0; nd.fy = 0; nd.fz = 0; if (nd.revealed) live.push(nd); });
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const A = live[i], B = live[j];
        let dx = A.x - B.x, dy = A.y - B.y, dz = D3 ? A.z - B.z : 0;
        let d2 = dx * dx + dy * dy + dz * dz; if (d2 < 1) { d2 = 1; dx = 0.5; }
        const d = Math.sqrt(d2), rep = REP / d2, ux = dx / d, uy = dy / d, uz = dz / d;
        A.fx += ux * rep; A.fy += uy * rep; B.fx -= ux * rep; B.fy -= uy * rep;
        if (D3) { A.fz += uz * rep; B.fz -= uz * rep; }
      }
    }
    edges.forEach((e) => {
      if (e.weight <= 0 || !e.a.revealed || !e.b.revealed) return;
      let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, dz = D3 ? e.b.z - e.a.z : 0;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const force = SPRING * Math.log(1 + e.weight) * (d - REST);
      const ux = dx / d, uy = dy / d, uz = dz / d;
      e.a.fx += ux * force; e.a.fy += uy * force;
      e.b.fx -= ux * force; e.b.fy -= uy * force;
      if (D3) { e.a.fz += uz * force; e.b.fz -= uz * force; }
    });
    const m = 44;
    live.forEach((nd) => {
      nd.fx += (cx - nd.x) * GRAV; nd.fy += (cy - nd.y) * GRAV;
      nd.vx = clamp((nd.vx + nd.fx) * DAMP, -MAXV, MAXV);
      nd.vy = clamp((nd.vy + nd.fy) * DAMP, -MAXV, MAXV);
      nd.x = clamp(nd.x + nd.vx, m, W - m);
      nd.y = clamp(nd.y + nd.vy, m, H - m);
      if (D3) {
        nd.fz += (0 - nd.z) * ZGRAV;
        nd.vz = clamp((nd.vz + nd.fz) * DAMP, -MAXV, MAXV);
        nd.z = clamp(nd.z + nd.vz, -ZLIM, ZLIM);
      } else if (nd.z !== 0) {
        nd.z += (0 - nd.z) * 0.12;  // ease back to flat when leaving 3D
      }
    });
  }

  function stepPositions() {
    if (mode === "clusters") { forceStep(); return; }
    nodes.forEach((nd) => {
      nd.x += (nd.tx - nd.x) * 0.12;
      nd.y += (nd.ty - nd.y) * 0.12;
      nd.z += ((threeD ? nd.tz : 0) - nd.z) * 0.12;
    });
  }

  function setMode(next) {
    mode = next;
    try { localStorage.setItem(LS_LAYOUT, mode); } catch (_) {}
    computeTargets();
    nodes.forEach((nd) => { nd.vx = 0; nd.vy = 0; });
    layoutsEl.querySelectorAll(".hm-layout").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  }

  function ensureNodeDom(nd) {
    if (nd.circle) return;
    const c = svgEl("circle");
    c.setAttribute("class", nd.isYou ? "hm-node hm-you" : "hm-node");
    c.setAttribute("r", 5);
    c.setAttribute("cx", nd.x); c.setAttribute("cy", nd.y);
    c.setAttribute("fill", nd.isYou ? "#ffd54a" : `hsl(${nd.hue} 80% 60%)`);
    c.setAttribute("filter", "url(#hm-glow)");
    gNodes.appendChild(c);
    const t = svgEl("text");
    t.setAttribute("class", nd.isYou ? "hm-label hm-label-you" : "hm-label");
    t.setAttribute("x", nd.x); t.setAttribute("y", nd.y);
    t.setAttribute("text-anchor", nd.lanchor);
    t.textContent = nd.label || (nd.isYou ? "You" : bare(nd.tag));
    gNodes.appendChild(t);
    nd.circle = c; nd.label = t;
    c.style.cursor = "pointer";
    c.addEventListener("click", () => openSessionDrill(nd));
  }

  function edgeKey(s, d) { return s < d ? `${s}|${d}` : `${d}|${s}`; }
  function ensureEdge(s, d) {
    const key = edgeKey(s, d);
    let e = edges.get(key);
    if (!e) {
      const a = nodes.get(s), b = nodes.get(d);
      const human = a.isYou || b.isYou;
      e = { a, b, weight: 0, ab: 0, ba: 0, lastTouch: -1, lastSize: 0, human, line: null };
      const ln = svgEl("line");
      ln.setAttribute("class", human ? "hm-edge hm-edge-human" : "hm-edge");
      const hue = human ? 45 : Math.round((a.hue + b.hue) / 2);
      ln.setAttribute("stroke", human ? "#ffcf4a" : `hsl(${hue} 70% 60%)`);
      e.line = ln; e.hue = human ? 45 : hue;
      gEdges.appendChild(ln);
      edges.set(key, e);
    }
    return e;
  }

  function resetGraph() {
    nodes.forEach((nd) => { nd.revealed = false; nd.lastActive = -1; nd.lastSize = 0; });
    edges.forEach((e) => { e.weight = 0; e.ab = 0; e.ba = 0; e.lastTouch = -1; e.lastSize = 0; });
    played = 0;
  }

  function applyEvent(i) {
    const ev = events[i];
    const p = pos[i];
    const bulk = bulkOf(ev.size);
    const src = nodes.get(ev.source);
    if (src) { src.revealed = true; src.lastActive = p; src.lastSize = bulk; ensureNodeDom(src); }
    for (const m of ev.mentions || []) {
      const dst = nodes.get(m);
      if (!dst || !src) continue;
      dst.revealed = true; ensureNodeDom(dst);
      const e = ensureEdge(ev.source, m);
      e.weight += 1;
      if (ev.source < m) e.ab += 1; else e.ba += 1;
      e.lastTouch = p; e.lastSize = bulk;
      src.lastActive = p; src.lastSize = bulk;
    }
  }

  function seek(targetF) {
    if (targetF < f) resetGraph();
    f = targetF;
    while (played < events.length && pos[played] <= f) applyEvent(played++);
  }

  function edgeWidth(w) { return 0.6 + Math.log2(1 + w) * 1.15; }

  // Project a node's world (x,y,z) to screen (sx,sy) with a scale + depth.
  // Identity when 3D is off, so the 2D graph is untouched. Rotation is yaw
  // (around the vertical axis, the spin) then pitch (tilt toward the viewer),
  // then a weak perspective divide.
  function project(nd) {
    if (!threeD) { nd.sx = nd.x; nd.sy = nd.y; nd.scale = 1; nd.depth = 0; return; }
    const px = nd.x - cx, py = nd.y - cy, pz = nd.z;
    const cyaw = Math.cos(yaw), syaw = Math.sin(yaw);
    const x1 = px * cyaw + pz * syaw;
    const z1 = -px * syaw + pz * cyaw;
    const cpit = Math.cos(pitch), spit = Math.sin(pitch);
    const y2 = py * cpit - z1 * spit;
    const z2 = py * spit + z1 * cpit;
    const scale = CAM_D / (CAM_D - z2);
    nd.sx = cx + x1 * scale;
    nd.sy = cy + y2 * scale;
    nd.scale = scale;
    nd.depth = z2;   // + = toward camera; used to dim far nodes/edges
  }
  // Far nodes dim, near nodes brighten (subtle) — the main non-perspective depth cue.
  function depthFade(z) { return threeD ? clamp(0.62 + 0.38 * (z / (R * 0.9)), 0.32, 1) : 1; }

  function render() {
    if (drillOpen || !events.length) return; // drill-down overlays the timeline
    stepPositions();
    nodes.forEach(project);
    nodes.forEach((nd) => {
      if (!nd.circle) return;
      const hot = nd.lastActive >= 0 ? Math.max(0, 1 - (f - nd.lastActive) / GLOW_WINDOW) : 0;
      const baseR = nd.isYou ? 8 : 4 + Math.log2(1 + nd.count) * 0.9;
      const bump = hot * (2.5 + nd.lastSize * 8);
      const fade = depthFade(nd.depth);
      nd.circle.setAttribute("cx", nd.sx.toFixed(1));
      nd.circle.setAttribute("cy", nd.sy.toFixed(1));
      nd.circle.setAttribute("r", ((baseR + bump) * nd.scale).toFixed(2));
      nd.circle.style.opacity = nd.revealed ? ((0.55 + 0.45 * hot) * fade).toFixed(3) : 0;
      nd.label.setAttribute("x", (nd.sx + nd.ldx).toFixed(1));
      nd.label.setAttribute("y", (nd.sy + nd.ldy).toFixed(1));
      nd.label.setAttribute("text-anchor", nd.lanchor);
      nd.label.style.opacity = nd.revealed ? ((0.4 + 0.6 * hot) * fade).toFixed(3) : 0;
    });

    gPulses.textContent = "";
    let activeNodes = 0;
    nodes.forEach((nd) => { if (nd.revealed) activeNodes++; });

    edges.forEach((e) => {
      if (e.weight <= 0) { e.line.setAttribute("stroke-opacity", 0); return; }
      const hot = e.lastTouch >= 0 ? Math.max(0, 1 - (f - e.lastTouch) / GLOW_WINDOW) : 0;
      e.line.setAttribute("x1", e.a.sx.toFixed(1)); e.line.setAttribute("y1", e.a.sy.toFixed(1));
      e.line.setAttribute("x2", e.b.sx.toFixed(1)); e.line.setAttribute("y2", e.b.sy.toFixed(1));
      const efade = depthFade((e.a.depth + e.b.depth) / 2);
      e.line.setAttribute("stroke-width", (edgeWidth(e.weight) * (threeD ? (e.a.scale + e.b.scale) / 2 : 1)).toFixed(2));
      const base = 0.1 + Math.min(0.42, Math.log2(1 + e.weight) / 14);
      e.line.setAttribute("stroke-opacity", ((base + 0.5 * hot) * efade).toFixed(3));
      if (hot > 0) {
        const p = 1 - hot;
        const fwd = e.ab >= e.ba;
        const from = fwd ? e.a : e.b, to = fwd ? e.b : e.a;
        const dot = svgEl("circle");
        dot.setAttribute("class", "hm-pulse");
        dot.setAttribute("r", ((2 + e.lastSize * 7) * (threeD ? to.scale : 1)).toFixed(2));
        dot.setAttribute("cx", lerp(from.sx, to.sx, p));
        dot.setAttribute("cy", lerp(from.sy, to.sy, p));
        dot.setAttribute("fill", `hsl(${e.hue} 90% 70%)`);
        gPulses.appendChild(dot);
      }
    });

    const playedTs = played > 0 ? events[played - 1].ts : t0;
    clockEl.textContent = fmtClock(playedTs);
    const trimmed = dropped > 0 ? ` · +${dropped} older trimmed` : "";
    statsEl.textContent = `${activeNodes}/${N} nodes · ${played}/${events.length} events${trimmed}`;
    if (!dragging) scrub.value = Math.round(f * 1000);
  }

  function tick(now) {
    if (!root) return;
    const dt = lastTs ? (now - lastTs) / 1000 : 0;
    lastTs = now;
    if (threeD && !orbitDrag) yaw += SPIN_RATE * dt;  // gentle idle spin (drag pauses it)
    if (playing && !dragging && events.length) {
      let nf = f + (dt / BASE_SECONDS) * speed;
      if (nf >= 1) { nf = 1; playing = false; playBtn.textContent = "↻"; }
      seek(nf);
    }
    render();
    raf = requestAnimationFrame(tick);
  }

  // ---- (re)build graph state from fetched data --------------------------
  function rebuild(data) {
    gEdges.textContent = ""; gPulses.textContent = ""; gNodes.textContent = "";
    edges = new Map();
    events = data.events || [];
    dropped = data.dropped || 0;
    const nodeList = data.nodes || [];
    N = nodeList.length;
    nodes = new Map();
    maxCount = 1;
    nodeList.forEach((n, i) => {
      if (n.count > maxCount) maxCount = n.count;
      nodes.set(n.tag, {
        tag: n.tag, count: n.count, idx: i, hue: hueFor(n.tag), isYou: !!n.is_you, label: n.label || null,
        revealed: false, lastActive: -1, lastSize: 0,
        x: 0, y: 0, vx: 0, vy: 0, fx: 0, fy: 0, tx: 0, ty: 0,
        z: 0, vz: 0, fz: 0, tz: 0,          // depth for 3D (0 ⇒ flat, as in 2D)
        sx: 0, sy: 0, scale: 1, depth: 0,   // projected screen coords + perspective
        ldx: 0, ldy: 0, lanchor: "middle", circle: null, label: null,
      });
    });

    if (events.length) {
      t0 = events[0].ts; t1 = events[events.length - 1].ts;
      const span = Math.max(1, t1 - t0), maxGap = span / 120;
      pos = new Array(events.length);
      let v = 0;
      for (let i = 0; i < events.length; i++) {
        if (i > 0) v += Math.min(events[i].ts - events[i - 1].ts, maxGap);
        pos[i] = v;
      }
      const vTotal = v || 1;
      for (let i = 0; i < events.length; i++) pos[i] /= vTotal;
      logMin = Infinity; let logMax = -Infinity;
      for (const ev of events) {
        const l = Math.log(1 + (ev.size || 0));
        if (l < logMin) logMin = l; if (l > logMax) logMax = l;
      }
      logRange = Math.max(1e-6, logMax - logMin);
    } else {
      pos = []; t0 = t1 = 0;
    }

    played = 0; f = 0;
    measure(); computeTargets(); seedRing();

    if (!events.length) {
      clockEl.textContent = "—";
      statsEl.textContent = humanOn
        ? "no transcript history found"
        : "no bus history yet — connect the message bus, or toggle 👤 Human for your prompt/reply history";
    }
  }

  // ---- drill-down: click a session → its whole working relationship ------
  async function openSessionDrill(nd) {
    if (!humanOn || nd.isYou || drillOpen) return; // drill-down is a human-layer feature; [you] is the hub, not a session
    // a tag's prompts all share a project dir — grab it to locate the transcripts
    const pe = events.find((e) => e.kind === "prompt" && e.mentions[0] === nd.tag && e.project);
    if (!pe) return;
    playing = false; playBtn.textContent = "▶";
    statsEl.textContent = `loading ${bare(nd.tag)}…`;
    try {
      const res = await fetch(`/api/session-detail?project=${encodeURIComponent(pe.project)}`);
      if (!res.ok || !root) return;
      const data = await res.json();
      if (!root) return;
      if (!drillMod) drillMod = await import("/static/drilldown.js");
      drillOpen = true;
      drillHandle = drillMod.open(root, data, { tag: nd.tag }, () => { drillOpen = false; drillHandle = null; });
    } catch (err) {
      console.error("drilldown failed to load", err);
    }
  }

  async function reload() {
    statsEl.textContent = "loading…";
    humanBtn.classList.toggle("on", humanOn);
    legendEl.textContent = humanOn
      ? "gold = you ↔ Claude · 🔬 click a session to drill into a prompt"
      : "line = how often · pulse size = message length";
    try { localStorage.setItem(LS_HUMAN, humanOn ? "1" : "0"); } catch (_) {}
    let data;
    try {
      const res = await fetch("/api/bus/heatmap" + (humanOn ? "?human=1" : ""));
      data = await res.json();
    } catch (err) {
      statsEl.textContent = "failed to load bus history";
      return;
    }
    if (!root) return;
    rebuild(data);
  }

  // ---- controls (wired once) --------------------------------------------
  playBtn.addEventListener("click", () => {
    if (f >= 1) { seek(0); f = 0; }
    playing = !playing;
    playBtn.textContent = playing ? "⏸" : "▶";
  });
  scrub.addEventListener("input", () => { dragging = true; seek(scrub.value / 1000); });
  const stopDrag = () => { dragging = false; };
  scrub.addEventListener("change", stopDrag);
  scrub.addEventListener("pointerup", stopDrag);

  const speedsEl = root.querySelector("#hm-speeds");
  SPEEDS.forEach((s) => {
    const b = document.createElement("button");
    b.className = "hm-speed" + (s === 1 ? " on" : "");
    b.textContent = s + "×";
    b.addEventListener("click", () => {
      speed = s;
      speedsEl.querySelectorAll(".hm-speed").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
    });
    speedsEl.appendChild(b);
  });

  LAYOUTS.forEach(([key, label]) => {
    const b = document.createElement("button");
    b.className = "hm-layout" + (key === mode ? " on" : "");
    b.dataset.mode = key;
    b.textContent = label;
    b.addEventListener("click", () => setMode(key));
    layoutsEl.appendChild(b);
  });

  humanBtn.addEventListener("click", () => {
    humanOn = !humanOn;
    playing = true; playBtn.textContent = "⏸";
    reload();
  });

  // ---- 3D toggle + drag-to-orbit ----------------------------------------
  const btn3d = root.querySelector("#hm-3d");
  function apply3d() {
    btn3d.classList.toggle("on", threeD);
    svg.style.cursor = threeD ? "grab" : "";
    if (threeD) { yaw = 0; pitch = START_PITCH; }
    else { yaw = 0; pitch = 0; }         // flat: project() becomes identity
    try { localStorage.setItem(LS_3D, threeD ? "1" : "0"); } catch (_) {}
  }
  btn3d.addEventListener("click", () => { threeD = !threeD; apply3d(); });
  apply3d();

  svg.addEventListener("pointerdown", (e) => {
    if (!threeD) return;
    orbitDrag = true; orbitMoved = false;
    dragX0 = e.clientX; dragY0 = e.clientY; yaw0 = yaw; pitch0 = pitch;
    svg.style.cursor = "grabbing";
  });
  window.addEventListener("pointermove", onOrbitMove);
  window.addEventListener("pointerup", onOrbitUp);
  root._orbitMove = onOrbitMove; root._orbitUp = onOrbitUp;  // for cleanup
  function onOrbitMove(e) {
    if (!orbitDrag) return;
    const dx = e.clientX - dragX0, dy = e.clientY - dragY0;
    if (Math.abs(dx) + Math.abs(dy) > 3) orbitMoved = true;
    yaw = yaw0 + dx * 0.008;
    pitch = clamp(pitch0 + dy * 0.008, -PITCH_LIMIT, PITCH_LIMIT);
  }
  function onOrbitUp() {
    if (!orbitDrag) return;
    orbitDrag = false;
    svg.style.cursor = threeD ? "grab" : "";
    // Suppress the click that follows a real drag (so orbiting doesn't drill in).
    if (orbitMoved) { const g = (ev) => { ev.stopPropagation(); }; svg.addEventListener("click", g, { capture: true, once: true }); }
  }

  onResize = () => requestAnimationFrame(() => { measure(); computeTargets(); });
  window.addEventListener("resize", onResize);

  measure();
  reload();
  raf = requestAnimationFrame(tick);
}
