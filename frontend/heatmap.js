// heatmap.js — 🕸 Bus history time-lapse.
//
// Self-contained, lazily imported (mirrors scene3d.js): a CDN miss or a throw
// in here can never touch the 2D board. No external deps — pure SVG.
//
// Fetches /api/bus/heatmap (the whole bus, live log + monthly archives) and
// replays it: sessions are nodes on a ring that fade in as each one first
// speaks, undirected mention-lines thicken with cumulative traffic, and a
// pulse-dot flies along an edge each time it's freshly used.
//
// Everything visible is a pure function of one scalar — `f`, progress in
// [0,1]. Glow/pulse "recency" is `f - lastTouch`, not a timer, so dragging the
// scrubber backward is just a cheap replay from 0. No setTimeout anywhere.

const BASE_SECONDS = 45;   // wall-clock seconds for 1x to play the whole history
const GLOW_WINDOW = 0.045; // how long (in f-units) a node/edge stays "hot"
const SPEEDS = [0.25, 0.5, 1, 2, 5];

let root = null;          // overlay element
let raf = 0;
let onResize = null;

function hueFor(tag) {
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) % 360;
  return h;
}
const bare = (t) => t.replace(/^\[/, "").replace(/\]$/, "").replace(/^other:/, "");
const lerp = (a, b, t) => a + (b - a) * t;
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
      <span class="hm-title">🕸 Bus history · who mentions whom</span>
      <span class="hm-stats" id="hm-stats">loading…</span>
      <span class="hm-legend">line = how often · pulse size = message length</span>
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

  let data;
  try {
    const res = await fetch("/api/bus/heatmap");
    data = await res.json();
  } catch (err) {
    root.querySelector("#hm-stats").textContent = "failed to load bus history";
    return;
  }
  if (!root) return; // closed while fetching
  build(data);
}

export function deactivate() {
  if (!root) return;
  cancelAnimationFrame(raf);
  raf = 0;
  if (onResize) window.removeEventListener("resize", onResize), (onResize = null);
  if (root._escClose) document.removeEventListener("keydown", root._escClose);
  root.remove();
  root = null;
}

function build(data) {
  const svg = root.querySelector("#hm-svg");
  const gEdges = root.querySelector("#hm-edges");
  const gPulses = root.querySelector("#hm-pulses");
  const gNodes = root.querySelector("#hm-nodes");
  const statsEl = root.querySelector("#hm-stats");
  const clockEl = root.querySelector("#hm-clock");
  const playBtn = root.querySelector("#hm-play");
  const scrub = root.querySelector("#hm-scrub");

  const events = data.events || [];
  const nodeList = data.nodes || [];
  if (!events.length || !nodeList.length) {
    statsEl.textContent = "no bus history yet";
    return;
  }

  // --- precompute virtual timeline (clamp idle gaps so lulls don't stall) ---
  const t0 = events[0].ts;
  const t1 = events[events.length - 1].ts;
  const span = Math.max(1, t1 - t0);
  const maxGap = span / 120;
  const pos = new Array(events.length);
  let v = 0;
  for (let i = 0; i < events.length; i++) {
    if (i > 0) v += Math.min(events[i].ts - events[i - 1].ts, maxGap);
    pos[i] = v;
  }
  const vTotal = v || 1;
  for (let i = 0; i < events.length; i++) pos[i] /= vTotal;

  // --- message-size normalization (log scale) -> 0..1 "bulk" -------------
  // Drives transient pulse size: a one-line hello barely registers, a multi-KB
  // status report sends a fat dot down the wire and thumps its sender.
  let logMin = Infinity, logMax = -Infinity;
  for (const ev of events) {
    const l = Math.log(1 + (ev.size || 0));
    if (l < logMin) logMin = l;
    if (l > logMax) logMax = l;
  }
  const logRange = Math.max(1e-6, logMax - logMin);
  const bulkOf = (size) =>
    Math.min(1, Math.max(0, (Math.log(1 + (size || 0)) - logMin) / logRange));

  // --- node model + ring layout ------------------------------------------
  const nodes = new Map();
  nodeList.forEach((n, i) => {
    nodes.set(n.tag, {
      tag: n.tag, count: n.count, idx: i, hue: hueFor(n.tag),
      revealed: false, lastActive: -1, lastSize: 0,
      x: 0, y: 0, vx: 0, vy: 0, fx: 0, fy: 0,   // current pos + force-sim state
      tx: 0, ty: 0,                             // eased target (ring / orbit modes)
      ldx: 0, ldy: 0, lanchor: "middle",        // label offset relative to node
      circle: null, label: null,
    });
  });
  const N = nodeList.length;

  // --- layout engine -----------------------------------------------------
  // Three modes. Ring/Orbit ease each node toward a computed target; Clusters
  // runs a live force sim (springs = mention edges) so dots migrate together as
  // partners rack up traffic. Switching modes morphs smoothly (eased / sprung
  // from wherever the nodes currently are).
  const LAYOUTS = [
    ["clusters", "Clusters"],
    ["ring", "Ring"],
    ["orbit", "Orbit"],
  ];
  const LS_KEY = "conductor.heatmapLayout";
  let layoutsEl = null; // switcher button row (built in the controls section)
  let mode = "clusters";
  try { const m = localStorage.getItem(LS_KEY); if (m && LAYOUTS.some((l) => l[0] === m)) mode = m; } catch (_) {}

  let W = 0, H = 0, cx = 0, cy = 0, R = 0, innerR = 0;
  let maxCount = 1;
  nodes.forEach((nd) => { if (nd.count > maxCount) maxCount = nd.count; });

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
        // Loudest sessions pulled toward the center; quiet ones to the rim.
        const loud = Math.log(1 + nd.count) / Math.log(1 + maxCount);
        rad = innerR + (R - innerR) * (1 - loud);
      }
      nd.tx = cx + rad * Math.cos(a);
      nd.ty = cy + rad * Math.sin(a);
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

  // Live force-directed step (Clusters mode). ~30 nodes → trivially cheap.
  function forceStep() {
    const REP = 7000, SPRING = 0.0012, GRAV = 0.006, DAMP = 0.80, REST = 78, MAXV = 22;
    const live = [];
    nodes.forEach((nd) => { nd.fx = 0; nd.fy = 0; if (nd.revealed) live.push(nd); });
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const A = live[i], B = live[j];
        let dx = A.x - B.x, dy = A.y - B.y;
        let d2 = dx * dx + dy * dy; if (d2 < 1) { d2 = 1; dx = 0.5; }
        const d = Math.sqrt(d2), rep = REP / d2, ux = dx / d, uy = dy / d;
        A.fx += ux * rep; A.fy += uy * rep; B.fx -= ux * rep; B.fy -= uy * rep;
      }
    }
    edges.forEach((e) => {
      if (e.weight <= 0 || !e.a.revealed || !e.b.revealed) return;
      let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = SPRING * Math.log(1 + e.weight) * (d - REST);
      const ux = dx / d, uy = dy / d;
      e.a.fx += ux * force; e.a.fy += uy * force;
      e.b.fx -= ux * force; e.b.fy -= uy * force;
    });
    const m = 44;
    live.forEach((nd) => {
      nd.fx += (cx - nd.x) * GRAV; nd.fy += (cy - nd.y) * GRAV;
      nd.vx = Math.max(-MAXV, Math.min(MAXV, (nd.vx + nd.fx) * DAMP));
      nd.vy = Math.max(-MAXV, Math.min(MAXV, (nd.vy + nd.fy) * DAMP));
      nd.x = Math.max(m, Math.min(W - m, nd.x + nd.vx));
      nd.y = Math.max(m, Math.min(H - m, nd.y + nd.vy));
    });
  }

  function stepPositions() {
    if (mode === "clusters") forceStep();
    else nodes.forEach((nd) => { nd.x += (nd.tx - nd.x) * 0.12; nd.y += (nd.ty - nd.y) * 0.12; });
  }

  function setMode(next) {
    mode = next;
    try { localStorage.setItem(LS_KEY, mode); } catch (_) {}
    computeTargets();
    nodes.forEach((nd) => { nd.vx = 0; nd.vy = 0; }); // hand off cleanly to springs/easing
    if (layoutsEl) layoutsEl.querySelectorAll(".hm-layout").forEach((b) =>
      b.classList.toggle("on", b.dataset.mode === mode));
  }

  function ensureNodeDom(nd) {
    if (nd.circle) return;
    const c = svgEl("circle");
    c.setAttribute("class", "hm-node");
    c.setAttribute("r", 5);
    c.setAttribute("cx", nd.x); c.setAttribute("cy", nd.y);
    c.setAttribute("fill", `hsl(${nd.hue} 80% 60%)`);
    c.setAttribute("filter", "url(#hm-glow)");
    gNodes.appendChild(c);
    const t = svgEl("text");
    t.setAttribute("class", "hm-label");
    t.setAttribute("x", nd.x); t.setAttribute("y", nd.y);
    t.setAttribute("text-anchor", nd.lanchor);
    t.textContent = bare(nd.tag);
    gNodes.appendChild(t);
    nd.circle = c; nd.label = t;
  }

  // --- edge model (undirected, lazily created) ---------------------------
  const edges = new Map(); // "a|b" -> {a,b,weight,ab,ba,lastTouch,line}
  function edgeKey(s, d) { return s < d ? `${s}|${d}` : `${d}|${s}`; }
  function ensureEdge(s, d) {
    const key = edgeKey(s, d);
    let e = edges.get(key);
    if (!e) {
      const a = nodes.get(s), b = nodes.get(d);
      e = { a, b, weight: 0, ab: 0, ba: 0, lastTouch: -1, lastSize: 0, line: null };
      const ln = svgEl("line");
      ln.setAttribute("class", "hm-edge");
      ln.setAttribute("x1", a.x); ln.setAttribute("y1", a.y);
      ln.setAttribute("x2", b.x); ln.setAttribute("y2", b.y);
      const hue = Math.round((a.hue + b.hue) / 2);
      ln.setAttribute("stroke", `hsl(${hue} 70% 60%)`);
      e.line = ln; e.hue = hue;
      gEdges.appendChild(ln);
      edges.set(key, e);
    }
    return e;
  }

  // --- timeline state machine --------------------------------------------
  let played = 0;     // events applied so far
  let f = 0;          // progress in [0,1]
  let playing = true;
  let lastTs = 0;
  let speed = 1;
  let dragging = false;

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
    for (const m of ev.mentions) {
      const dst = nodes.get(m);
      if (!dst || !src) continue;
      dst.revealed = true; ensureNodeDom(dst);
      const e = ensureEdge(ev.source, m);
      e.weight += 1;
      if (ev.source < m) e.ab += 1; else e.ba += 1;
      e.lastTouch = p;
      e.lastSize = bulk;
      src.lastActive = p;
      src.lastSize = bulk;
    }
  }

  function seek(targetF) {
    if (targetF < f) resetGraph();
    f = targetF;
    while (played < events.length && pos[played] <= f) applyEvent(played++);
  }

  // --- render (pure function of f) ---------------------------------------
  function edgeWidth(w) { return 0.6 + Math.log2(1 + w) * 1.15; }

  function render() {
    stepPositions();
    nodes.forEach((nd) => {
      if (!nd.circle) return;
      const hot = nd.lastActive >= 0 ? Math.max(0, 1 - (f - nd.lastActive) / GLOW_WINDOW) : 0;
      // Flash size scales with the last message's bulk: a hello barely twitches,
      // a big report thumps.
      const bump = hot * (2.5 + nd.lastSize * 8);
      nd.circle.setAttribute("cx", nd.x.toFixed(1));
      nd.circle.setAttribute("cy", nd.y.toFixed(1));
      nd.circle.setAttribute("r", (4 + Math.log2(1 + nd.count) * 0.9 + bump).toFixed(2));
      nd.circle.style.opacity = nd.revealed ? (0.55 + 0.45 * hot).toFixed(3) : 0;
      nd.label.setAttribute("x", (nd.x + nd.ldx).toFixed(1));
      nd.label.setAttribute("y", (nd.y + nd.ldy).toFixed(1));
      nd.label.setAttribute("text-anchor", nd.lanchor);
      nd.label.style.opacity = nd.revealed ? (0.4 + 0.6 * hot).toFixed(3) : 0;
    });

    // clear last frame's pulse dots
    gPulses.textContent = "";
    let activeNodes = 0;
    nodes.forEach((nd) => { if (nd.revealed) activeNodes++; });

    edges.forEach((e) => {
      if (e.weight <= 0) {
        // Reset/scrub-to-start zeroed this edge — hide the stale line instead
        // of leaving it drawn at its last thickness.
        e.line.setAttribute("stroke-opacity", 0);
        return;
      }
      const hot = e.lastTouch >= 0 ? Math.max(0, 1 - (f - e.lastTouch) / GLOW_WINDOW) : 0;
      e.line.setAttribute("x1", e.a.x.toFixed(1)); e.line.setAttribute("y1", e.a.y.toFixed(1));
      e.line.setAttribute("x2", e.b.x.toFixed(1)); e.line.setAttribute("y2", e.b.y.toFixed(1));
      e.line.setAttribute("stroke-width", edgeWidth(e.weight).toFixed(2));
      const base = 0.1 + Math.min(0.42, Math.log2(1 + e.weight) / 14);
      e.line.setAttribute("stroke-opacity", (base + 0.5 * hot).toFixed(3));
      if (hot > 0) {
        // pulse dot flies a→b (or b→a) depending on which direction just fired
        const p = 1 - hot; // 0 at touch → 1 a GLOW_WINDOW later
        const fwd = e.ab >= e.ba;
        const from = fwd ? e.a : e.b, to = fwd ? e.b : e.a;
        const dot = svgEl("circle");
        dot.setAttribute("class", "hm-pulse");
        // Dot size = message length: fat packet for a bulk report, speck for a hello.
        dot.setAttribute("r", (2 + e.lastSize * 7).toFixed(2));
        dot.setAttribute("cx", lerp(from.x, to.x, p));
        dot.setAttribute("cy", lerp(from.y, to.y, p));
        dot.setAttribute("fill", `hsl(${e.hue} 90% 70%)`);
        gPulses.appendChild(dot);
      }
    });

    const playedTs = played > 0 ? events[played - 1].ts : t0;
    clockEl.textContent = fmtClock(playedTs);
    statsEl.textContent = `${activeNodes}/${N} sessions · ${played}/${events.length} messages`;
    if (!dragging) scrub.value = Math.round(f * 1000);
  }

  // --- animation loop -----------------------------------------------------
  function tick(now) {
    if (!root) return;
    const dt = lastTs ? (now - lastTs) / 1000 : 0;
    lastTs = now;
    if (playing && !dragging) {
      let nf = f + (dt / BASE_SECONDS) * speed;
      if (nf >= 1) { nf = 1; playing = false; playBtn.textContent = "↻"; }
      seek(nf);
    }
    render();
    raf = requestAnimationFrame(tick);
  }

  // --- controls -----------------------------------------------------------
  playBtn.addEventListener("click", () => {
    if (f >= 1) { seek(0); f = 0; } // replay from start
    playing = !playing;
    playBtn.textContent = playing ? "⏸" : "▶";
  });
  scrub.addEventListener("input", () => {
    dragging = true;
    seek(scrub.value / 1000);
  });
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

  layoutsEl = root.querySelector("#hm-layouts");
  LAYOUTS.forEach(([key, label]) => {
    const b = document.createElement("button");
    b.className = "hm-layout" + (key === mode ? " on" : "");
    b.dataset.mode = key;
    b.textContent = label;
    b.addEventListener("click", () => setMode(key));
    layoutsEl.appendChild(b);
  });

  onResize = () => requestAnimationFrame(() => { measure(); computeTargets(); });
  window.addEventListener("resize", onResize);

  measure();
  computeTargets();
  seedRing();      // everything starts as a ring, then eases/springs into `mode`
  raf = requestAnimationFrame(tick);
}
