// drilldown.js — 🔬 watch one session explode outward in work.
//
// Lazily imported by heatmap.js when you click a session node in Human mode.
// Replays the WHOLE you↔session relationship on a playhead: a "you" node fires
// each prompt into the central session node, which detonates outward into the
// files it touched (deduped halo, read=blue / edited=orange), the sub-agents it
// spawned, and every tool call (pulse + live counter). Scrub the whole working
// relationship — or 🔍 focus a single exchange at a time.
//
// Pure SVG, no deps. Deterministic-`f` model (recency = f - lastTouch, no timers).

const BASE_SECONDS = 30;
const GLOW_WINDOW = 0.05;
const SPEEDS = [0.25, 0.5, 1, 2, 5];
const MAX_FILES = 320;

const svgEl = (n) => document.createElementNS("http://www.w3.org/2000/svg", n);
const lerp = (a, b, t) => a + (b - a) * t;
function hashAngle(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return (h - 90) * (Math.PI / 180); }
function fmtClock(ts) { return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }

export function open(host, data, meta, onBack) {
  const allEvents = data.events || [];
  const prompts = data.prompts || [];
  const tagLabel = meta.tag ? meta.tag.replace(/^\[|\]$/g, "").replace(/^other:/, "") : "session";

  const panel = document.createElement("div");
  panel.className = "dd-overlay";
  panel.innerHTML = `
    <div class="dd-header">
      <button class="dd-back" title="Back to timeline">← Back</button>
      <span class="dd-title"></span>
      <span class="dd-scope" id="dd-scope"></span>
      <span class="dd-summary"></span>
    </div>
    <svg class="dd-svg" id="dd-svg" aria-hidden="true">
      <defs>
        <filter id="dd-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <g id="dd-edges"></g><g id="dd-pulses"></g><g id="dd-nodes"></g>
    </svg>
    <div class="dd-tape" id="dd-tape"></div>
    <div class="dd-controls">
      <button class="dd-play" id="dd-play" title="Play / pause">⏸</button>
      <input type="range" class="dd-scrub" id="dd-scrub" min="0" max="1000" value="0" />
      <span class="dd-clock" id="dd-clock">—</span>
      <button class="dd-focus" id="dd-focus" title="Focus a single prompt">🔍 Focus prompt</button>
      <div class="dd-speeds" id="dd-speeds"></div>
    </div>`;
  host.appendChild(panel);

  panel.querySelector(".dd-title").textContent = `🔬 you ↔ ${tagLabel}`;
  const s = data.summary || {};
  panel.querySelector(".dd-summary").textContent =
    `${s.prompts || 0} prompts · ${s.tools || 0} tools · ${s.files || 0} files · ${s.edits || 0} edits · ${s.agents || 0} agents`
    + (data.dropped ? ` · +${data.dropped} older trimmed` : "");

  const svg = panel.querySelector("#dd-svg");
  const gEdges = panel.querySelector("#dd-edges");
  const gPulses = panel.querySelector("#dd-pulses");
  const gNodes = panel.querySelector("#dd-nodes");
  const tapeEl = panel.querySelector("#dd-tape");
  const scopeEl = panel.querySelector("#dd-scope");
  const playBtn = panel.querySelector("#dd-play");
  const scrub = panel.querySelector("#dd-scrub");
  const clockEl = panel.querySelector("#dd-clock");
  const focusBtn = panel.querySelector("#dd-focus");

  // --- static nodes: you (left) + session (center) -----------------------
  const youCircle = svgEl("circle"); youCircle.setAttribute("class", "dd-node dd-you"); youCircle.setAttribute("r", 9); gNodes.appendChild(youCircle);
  const youLabel = svgEl("text"); youLabel.setAttribute("class", "dd-alabel"); youLabel.setAttribute("text-anchor", "middle"); youLabel.textContent = "you"; gNodes.appendChild(youLabel);
  const sessCircle = svgEl("circle"); sessCircle.setAttribute("class", "dd-node dd-sess"); sessCircle.setAttribute("r", 14); gNodes.appendChild(sessCircle);
  const sessLabel = svgEl("text"); sessLabel.setAttribute("class", "dd-alabel"); sessLabel.setAttribute("text-anchor", "middle"); sessLabel.textContent = tagLabel; gNodes.appendChild(sessLabel);
  const youSessEdge = svgEl("line"); youSessEdge.setAttribute("class", "dd-edge dd-yedge"); gEdges.appendChild(youSessEdge);

  // --- swappable scope state (whole relationship, or one exchange) --------
  let files = new Map(), agents = [], moments = [], pos = [], nFiles = 1;
  let scopeEx = null;

  function buildScope() {
    const ev = scopeEx == null ? allEvents : allEvents.filter((e) => e.ex === scopeEx);
    const prm = scopeEx == null ? prompts : prompts.filter((p) => p.i === scopeEx);
    // pre-scan files (deduped, stable ring slot) + agents
    files = new Map(); agents = [];
    for (const e of ev) {
      if (e.kind === "file" && e.path) {
        if (!files.has(e.path) && files.size < MAX_FILES)
          files.set(e.path, { label: e.label || e.path, mode: e.mode, idx: files.size, touches: 0, revealed: false, lastTouch: -1 });
        else if (files.has(e.path) && e.mode === "write") files.get(e.path).mode = "write";
      } else if (e.kind === "agent") {
        agents.push({ label: e.label || "agent", idx: agents.length, revealed: false, lastTouch: -1 });
      }
    }
    nFiles = Math.max(1, files.size);
    // merge prompt markers + work events into one time-ordered moment stream
    moments = [
      ...prm.map((p) => ({ ts: p.ts, kind: "prompt", i: p.i, text: p.text })),
      ...ev.map((e) => ({ ...e, kind2: e.kind })),
    ].filter((m) => m.ts != null).sort((a, b) => a.ts - b.ts);
    const span = moments.length ? Math.max(1, moments[moments.length - 1].ts - moments[0].ts) : 1;
    const maxGap = span / 90;
    pos = new Array(moments.length); let v = 0;
    for (let i = 0; i < moments.length; i++) { if (i > 0) v += Math.min(moments[i].ts - moments[i - 1].ts, maxGap); pos[i] = v; }
    const vt = v || 1; for (let i = 0; i < moments.length; i++) pos[i] /= vt;
    gEdges.querySelectorAll(".dd-fedge,.dd-aedge").forEach((n) => n.remove());
    gNodes.querySelectorAll(".dd-file,.dd-agent,.dd-flabel,.dd-alabel.dd-aglabel").forEach((n) => n.remove());
    files.forEach((fp) => { fp.circle = fp.edge = fp.label_el = null; });
    played = 0; f = 0;
    scopeEl.textContent = scopeEx == null ? "" : `● focused: “${(prm[0]?.text || "").slice(0, 40)}” ✕`;
    scopeEl.style.display = scopeEx == null ? "none" : "";
  }

  // --- geometry ----------------------------------------------------------
  let W = 0, H = 0, sx = 0, sy = 0, youX = 0, youY = 0, fileR = 0, agentR = 0;
  function measure() {
    const r = svg.getBoundingClientRect();
    W = r.width; H = r.height; svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    sx = W * 0.56; sy = H / 2 + 6; youX = W * 0.12; youY = sy;
    fileR = Math.max(70, Math.min(W, H) * 0.30); agentR = Math.max(110, Math.min(W, H) * 0.44);
  }
  function filePos(idx) { const a = (-90 + (360 * idx) / nFiles) * (Math.PI / 180); return [sx + fileR * Math.cos(a), sy + fileR * Math.sin(a)]; }
  function agentPos(idx) { const n = Math.max(1, agents.length); const a = (-150 + (120 * (idx + 0.5)) / n) * (Math.PI / 180); return [sx + agentR * Math.cos(a), sy + agentR * Math.sin(a)]; }

  function ensureFileDom(fp) {
    if (fp.circle) return;
    const [x, y] = filePos(fp.idx); fp._x = x; fp._y = y;
    const edge = svgEl("line"); edge.setAttribute("class", "dd-edge dd-fedge"); gEdges.appendChild(edge); fp.edge = edge;
    const c = svgEl("circle"); c.setAttribute("class", "dd-node dd-file" + (fp.mode === "write" ? " dd-write" : "")); gNodes.appendChild(c); fp.circle = c;
    const t = svgEl("text"); t.setAttribute("class", "dd-flabel"); t.setAttribute("text-anchor", x < sx ? "end" : "start"); t.textContent = fp.label; gNodes.appendChild(t); fp.label_el = t;
  }
  function ensureAgentDom(ag) {
    if (ag.circle) return;
    const [x, y] = agentPos(ag.idx); ag._x = x; ag._y = y;
    const edge = svgEl("line"); edge.setAttribute("class", "dd-edge dd-aedge"); gEdges.appendChild(edge); ag.edge = edge;
    const c = svgEl("circle"); c.setAttribute("class", "dd-node dd-agent"); c.setAttribute("r", 8); gNodes.appendChild(c); ag.circle = c;
    const t = svgEl("text"); t.setAttribute("class", "dd-alabel dd-aglabel"); t.setAttribute("text-anchor", "middle"); t.textContent = "⚙ " + ag.label; gNodes.appendChild(t); ag.label_el = t;
  }

  // --- playback ----------------------------------------------------------
  let played = 0, f = 0, playing = true, lastTs = 0, speed = 1, dragging = false, raf = 0;
  let agentSeen = 0, promptPulse = -1, curPrompt = -1;
  const toolCounts = new Map();

  function resetCounters() { files.forEach((fp) => { fp.touches = 0; fp.revealed = false; fp.lastTouch = -1; }); agents.forEach((a) => { a.revealed = false; a.lastTouch = -1; }); toolCounts.clear(); agentSeen = 0; promptPulse = -1; curPrompt = -1; played = 0; }

  function applyMoment(i) {
    const m = moments[i], p = pos[i];
    if (m.kind === "prompt") { promptPulse = p; curPrompt = m.i; return; }
    if (m.kind2 === "file" && m.path) { const fp = files.get(m.path); if (fp) { fp.revealed = true; fp.touches += 1; fp.lastTouch = p; ensureFileDom(fp); } }
    else if (m.kind2 === "agent") { const ag = agents[agentSeen++]; if (ag) { ag.revealed = true; ag.lastTouch = p; ensureAgentDom(ag); } }
    else { toolCounts.set(m.tool, (toolCounts.get(m.tool) || 0) + 1); }
  }
  function seek(target) { if (target < f) resetCounters(); f = target; while (played < moments.length && pos[played] <= f) applyMoment(played++); }

  function pulseTarget(m) {
    if (m.kind2 === "file" && m.path && files.get(m.path)?.circle) { const fp = files.get(m.path); return [fp._x, fp._y]; }
    if (m.kind2 === "agent") { const ag = agents[Math.min(agentSeen, agents.length) - 1]; if (ag && ag._x != null) return [ag._x, ag._y]; }
    const a = hashAngle(m.tool || "x"); return [sx + fileR * 0.8 * Math.cos(a), sy + fileR * 0.8 * Math.sin(a)];
  }

  function render() {
    if (W === 0) measure();
    gPulses.textContent = "";
    youCircle.setAttribute("cx", youX); youCircle.setAttribute("cy", youY);
    youLabel.setAttribute("x", youX); youLabel.setAttribute("y", youY - 16);
    sessCircle.setAttribute("cx", sx); sessCircle.setAttribute("cy", sy);
    sessLabel.setAttribute("x", sx); sessLabel.setAttribute("y", sy - 20);
    youSessEdge.setAttribute("x1", youX); youSessEdge.setAttribute("y1", youY); youSessEdge.setAttribute("x2", sx); youSessEdge.setAttribute("y2", sy);

    const phot = promptPulse >= 0 ? Math.max(0, 1 - (f - promptPulse) / GLOW_WINDOW) : 0;
    youSessEdge.setAttribute("stroke-opacity", (0.12 + 0.5 * phot).toFixed(3));
    youCircle.setAttribute("r", (9 + phot * 5).toFixed(2));
    if (phot > 0) { const p = 1 - phot; const d = svgEl("circle"); d.setAttribute("class", "dd-pulse dd-pp"); d.setAttribute("r", 4); d.setAttribute("cx", lerp(youX, sx, p)); d.setAttribute("cy", lerp(youY, sy, p)); gPulses.appendChild(d); }

    let sessHot = phot;
    files.forEach((fp) => {
      if (!fp.circle) return;
      const hot = fp.lastTouch >= 0 ? Math.max(0, 1 - (f - fp.lastTouch) / GLOW_WINDOW) : 0;
      sessHot = Math.max(sessHot, hot);
      fp.circle.setAttribute("cx", fp._x); fp.circle.setAttribute("cy", fp._y);
      fp.circle.setAttribute("r", (3.5 + Math.min(6, Math.log2(1 + fp.touches) * 2) + hot * 3).toFixed(2));
      fp.circle.style.opacity = fp.revealed ? (0.55 + 0.45 * hot).toFixed(3) : 0;
      fp.edge.setAttribute("x1", sx); fp.edge.setAttribute("y1", sy); fp.edge.setAttribute("x2", fp._x); fp.edge.setAttribute("y2", fp._y);
      fp.edge.setAttribute("stroke-opacity", fp.revealed ? (0.08 + 0.4 * hot).toFixed(3) : 0);
      fp.label_el.setAttribute("x", fp._x + (fp._x < sx ? -7 : 7)); fp.label_el.setAttribute("y", fp._y + 3);
      fp.label_el.style.opacity = hot > 0.05 ? hot.toFixed(3) : 0; // labels only while hot — declutters a big halo
    });
    agents.forEach((ag) => {
      if (!ag.circle) return;
      const hot = ag.lastTouch >= 0 ? Math.max(0, 1 - (f - ag.lastTouch) / GLOW_WINDOW) : 0;
      sessHot = Math.max(sessHot, hot);
      ag.circle.setAttribute("cx", ag._x); ag.circle.setAttribute("cy", ag._y); ag.circle.setAttribute("r", (8 + hot * 4).toFixed(2));
      ag.circle.style.opacity = ag.revealed ? 1 : 0;
      ag.edge.setAttribute("x1", sx); ag.edge.setAttribute("y1", sy); ag.edge.setAttribute("x2", ag._x); ag.edge.setAttribute("y2", ag._y);
      ag.edge.setAttribute("stroke-opacity", ag.revealed ? 0.5 : 0);
      ag.label_el.setAttribute("x", ag._x); ag.label_el.setAttribute("y", ag._y - 12); ag.label_el.style.opacity = ag.revealed ? 1 : 0;
    });

    const lo = Math.max(0, played - 70);
    for (let i = lo; i < played; i++) {
      const m = moments[i]; if (m.kind === "prompt") continue;
      const hot = Math.max(0, 1 - (f - pos[i]) / GLOW_WINDOW); if (hot <= 0) continue;
      sessHot = Math.max(sessHot, hot);
      const [tx, ty] = pulseTarget(m); const p = 1 - hot;
      const dot = svgEl("circle");
      dot.setAttribute("class", "dd-pulse" + (m.kind2 === "agent" ? " dd-pa" : m.kind2 === "file" ? (m.mode === "write" ? " dd-pw" : " dd-pr") : ""));
      if (m.status === "error") dot.classList.add("dd-err");
      dot.setAttribute("r", m.kind2 === "file" ? 3 : 2.2); dot.setAttribute("cx", lerp(sx, tx, p)); dot.setAttribute("cy", lerp(sy, ty, p));
      gPulses.appendChild(dot);
    }
    sessCircle.setAttribute("r", (14 + sessHot * 7).toFixed(2));

    const top = [...toolCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => `${k} ×${v}`);
    const revFiles = [...files.values()].filter((x) => x.revealed).length;
    const cp = curPrompt >= 0 ? (prompts.find((p) => p.i === curPrompt)?.text || "") : "";
    tapeEl.textContent = `▶ ${revFiles} files · ${agentSeen} agents${top.length ? "  ·  " + top.join("  ·  ") : ""}${cp ? "    ↳ " + cp : ""}`;
    const ts = played > 0 && moments[played - 1] ? moments[played - 1].ts : (moments[0]?.ts || 0);
    clockEl.textContent = moments.length ? fmtClock(ts) : "—";
    if (!dragging) scrub.value = Math.round(f * 1000);
  }

  function tick(now) {
    if (!panel.isConnected) return;
    const dt = lastTs ? (now - lastTs) / 1000 : 0; lastTs = now;
    if (playing && !dragging && moments.length) { let nf = f + (dt / BASE_SECONDS) * speed; if (nf >= 1) { nf = 1; playing = false; playBtn.textContent = "↻"; } seek(nf); }
    render();
    raf = requestAnimationFrame(tick);
  }

  // --- focus a single exchange (one at a time) ---------------------------
  function setScope(ex) { scopeEx = ex; buildScope(); playing = true; playBtn.textContent = "⏸"; }
  let focusList = null;
  function closeFocus() { if (focusList) { focusList.remove(); focusList = null; } }
  focusBtn.addEventListener("click", () => {
    if (focusList) { closeFocus(); return; }
    playing = false; playBtn.textContent = "▶";
    focusList = document.createElement("div"); focusList.className = "hm-picker";
    const card = document.createElement("div"); card.className = "hm-picker-card";
    const head = document.createElement("div"); head.className = "hm-picker-head";
    const title = document.createElement("span"); title.textContent = `🔍 focus one prompt (${prompts.length})`;
    const x = document.createElement("button"); x.className = "hm-picker-close"; x.textContent = "×"; x.addEventListener("click", closeFocus);
    head.append(title, x);
    const list = document.createElement("div"); list.className = "hm-picker-list";
    prompts.slice().reverse().forEach((p) => {
      const b = document.createElement("button"); b.className = "hm-prow";
      const tt = document.createElement("span"); tt.className = "hm-prow-t"; tt.textContent = p.ts ? fmtClock(p.ts) : "";
      const xx = document.createElement("span"); xx.className = "hm-prow-x"; xx.textContent = p.text || "(prompt)";
      b.append(tt, xx); b.addEventListener("click", () => { closeFocus(); setScope(p.i); });
      list.appendChild(b);
    });
    card.append(head, list); focusList.appendChild(card);
    focusList.addEventListener("click", (e) => { if (e.target === focusList) closeFocus(); });
    panel.appendChild(focusList);
  });
  scopeEl.addEventListener("click", () => setScope(null)); // ✕ back to whole relationship

  // --- controls ----------------------------------------------------------
  playBtn.addEventListener("click", () => { if (f >= 1) { seek(0); f = 0; } playing = !playing; playBtn.textContent = playing ? "⏸" : "▶"; });
  scrub.addEventListener("input", () => { dragging = true; seek(scrub.value / 1000); });
  const stop = () => { dragging = false; }; scrub.addEventListener("change", stop); scrub.addEventListener("pointerup", stop);
  const speedsEl = panel.querySelector("#dd-speeds");
  SPEEDS.forEach((sp) => { const b = document.createElement("button"); b.className = "dd-speed" + (sp === 1 ? " on" : ""); b.textContent = sp + "×"; b.addEventListener("click", () => { speed = sp; speedsEl.querySelectorAll(".dd-speed").forEach((x) => x.classList.remove("on")); b.classList.add("on"); }); speedsEl.appendChild(b); });

  function close() { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); panel.remove(); }
  const onResize = () => { if (panel.isConnected) requestAnimationFrame(measure); };
  window.addEventListener("resize", onResize);
  panel.querySelector(".dd-back").addEventListener("click", () => { close(); onBack && onBack(); });

  measure(); buildScope();
  raf = requestAnimationFrame(tick);
  return { close };
}
