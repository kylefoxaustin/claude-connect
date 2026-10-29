// tokens.js — 🪙 Token history time-lapse.
//
// The bus history (heatmap.js) replays who talked to whom; this replays what it COST: every
// session's tokens since Conductor first saw a transcript, by day and project, from
// /api/tokens/history. Same discipline as heatmap.js — lazily imported, self-contained, pure SVG,
// and everything visible is a pure function of one scalar `f` (progress in [0,1]), so scrubbing
// backward is just drawing an earlier frame. No setTimeout in the render path.
//
// Three layers, one playhead:
//   • a running odometer — the fleet's cumulative total up to the playhead's day;
//   • a bar race — projects ranked by cumulative spend, sliding as they overtake each other;
//   • a day strip — one column per day, stacked by project, lit as the playhead passes it
//     (the days ahead stay as faint ghosts, so you can see the shape coming).

const BASE_SECONDS = 30;          // wall-clock seconds for 1x to play the whole history
const SPEEDS = [0.25, 0.5, 1, 2, 5];
const TOP_BARS = 12;              // projects in the race
const TOP_STACK = 8;              // projects coloured in the day strip; the rest are "other"
const METRICS = [["output", "Output", "tokens the models generated — the work done"],
                 ["total", "Total processed", "everything read + written, mostly cheap cache re-reads"]];
const LS_METRIC = "conductor.tokensMetric";

let root = null;
let raf = 0;
let onResize = null;
let pollTimer = 0;

function hueFor(tag) {            // same hash as heatmap.js, so a project keeps its colour
  let h = 0;
  for (let i = 0; i < tag.length; i++) h = (h * 31 + tag.charCodeAt(i)) % 360;
  return h;
}
const colorFor = (name) => (name === "other" ? "hsl(220 10% 45%)" : `hsl(${hueFor(name)} 70% 60%)`);
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const svgEl = (n) => document.createElementNS("http://www.w3.org/2000/svg", n);

export function humanTok(n) {
  n = n || 0;
  for (const [div, suf] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
    if (n >= div) return `${(n / div).toFixed(n / div >= 100 ? 0 : 1)}${suf}`;
  }
  return String(Math.round(n));
}

function dayList(first, last) {   // every calendar day, gaps included, so time is linear
  const out = [];
  const d = new Date(`${first}T12:00:00`);
  const end = new Date(`${last}T12:00:00`);
  while (d <= end && out.length < 5000) {
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    d.setDate(d.getDate() + 1);
  }
  return out;
}
const fmtDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined,
  { weekday: "short", month: "short", day: "numeric", year: "numeric" });

export async function activate() {
  if (root) return;
  root = document.createElement("div");
  root.className = "heatmap-overlay tokens-overlay";
  root.innerHTML = `
    <div class="hm-header">
      <span class="hm-title">🪙 Token history</span>
      <span class="hm-stats" id="tk-stats">loading…</span>
      <span class="hm-legend" id="tk-legend"></span>
      <button class="hm-close" title="Close (Esc)">×</button>
    </div>
    <svg class="hm-svg" id="tk-svg" aria-hidden="true">
      <defs>
        <filter id="tk-glow" x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <g id="tk-odo"></g>
      <g id="tk-bars"></g>
      <g id="tk-strip"></g>
    </svg>
    <div class="hm-controls">
      <div class="hm-layouts" id="tk-metrics" title="Which number to race"></div>
      <button class="hm-play" id="tk-play" title="Play / pause (space)">⏸</button>
      <input type="range" class="hm-scrub" id="tk-scrub" min="0" max="1000" value="0" />
      <span class="hm-clock" id="tk-clock">—</span>
      <div class="hm-speeds" id="tk-speeds"></div>
    </div>`;
  document.body.appendChild(root);
  root.querySelector(".hm-close").addEventListener("click", deactivate);
  const keys = (e) => {
    if (e.key === "Escape") deactivate();
    else if (e.key === " " && root) { e.preventDefault(); root.querySelector("#tk-play").click(); }
  };
  document.addEventListener("keydown", keys);
  root._keys = keys;
  run();
}

export function deactivate() {
  if (!root) return;
  cancelAnimationFrame(raf); raf = 0;
  clearTimeout(pollTimer); pollTimer = 0;
  if (onResize) { window.removeEventListener("resize", onResize); onResize = null; }
  if (root._keys) document.removeEventListener("keydown", root._keys);
  if (root._pointerUp) window.removeEventListener("pointerup", root._pointerUp);
  root.remove();
  root = null;
}

function run() {
  const svg = root.querySelector("#tk-svg");
  const gOdo = root.querySelector("#tk-odo");
  const gBars = root.querySelector("#tk-bars");
  const gStrip = root.querySelector("#tk-strip");
  const statsEl = root.querySelector("#tk-stats");
  const legendEl = root.querySelector("#tk-legend");
  const clockEl = root.querySelector("#tk-clock");
  const playBtn = root.querySelector("#tk-play");
  const scrub = root.querySelector("#tk-scrub");

  let metric = "output";
  try { const m = localStorage.getItem(LS_METRIC); if (METRICS.some((x) => x[0] === m)) metric = m; } catch (_) {}

  // ---- data (rebuilt on a metric switch) --------------------------------
  let snap = null, days = [], names = [], D = 0, P = 0;
  let cum = [], daily = [], rank = [], fleetCum = [], stackNames = [], dayStack = [], maxDaily = 1, peakDay = -1;

  // ---- playback ---------------------------------------------------------
  let played = 0, f = 0, playing = true, lastTs = 0, speed = 1, dragging = false;

  // ---- geometry ---------------------------------------------------------
  let W = 0, H = 0, odoH = 0, barTop = 0, barH = 0, stripTop = 0, stripH = 0, padL = 0, padR = 0;

  function prepare() {
    const idx = metric === "output" ? 0 : 1;
    days = dayList(snap.days[0], snap.days[snap.days.length - 1]);
    D = days.length;
    names = snap.projects.map((p) => p.name);
    P = names.length;
    const pIndex = new Map(names.map((n, i) => [n, i]));
    daily = names.map(() => new Float64Array(D));
    days.forEach((day, d) => {
      const row = snap.series[day] || {};
      for (const [n, v] of Object.entries(row)) { const p = pIndex.get(n); if (p !== undefined) daily[p][d] = v[idx]; }
    });
    cum = daily.map((arr) => { const c = new Float64Array(D); let s = 0; for (let d = 0; d < D; d++) { s += arr[d]; c[d] = s; } return c; });
    fleetCum = new Float64Array(D);
    for (let d = 0; d < D; d++) { let s = 0; for (let p = 0; p < P; p++) s += cum[p][d]; fleetCum[d] = s; }
    // rank[d][p] = place of project p on day d (0 = leader); ties keep a stable order.
    rank = [];
    const order = names.map((_, i) => i);
    for (let d = 0; d < D; d++) {
      order.sort((a, b) => (cum[b][d] - cum[a][d]) || (a - b));
      const r = new Int16Array(P);
      order.forEach((p, k) => { r[p] = k; });
      rank.push(r);
    }
    // day strip: the overall top projects (by this metric) get colours, the rest pool as "other".
    const byTotal = names.map((_, p) => p).sort((a, b) => cum[b][D - 1] - cum[a][D - 1]);
    const coloured = byTotal.slice(0, TOP_STACK);
    stackNames = coloured.map((p) => names[p]).concat(P > TOP_STACK ? ["other"] : []);
    dayStack = [];
    maxDaily = 1; peakDay = -1;
    for (let d = 0; d < D; d++) {
      const seg = coloured.map((p) => daily[p][d]);
      if (P > TOP_STACK) { let o = 0; for (const p of byTotal.slice(TOP_STACK)) o += daily[p][d]; seg.push(o); }
      const tot = seg.reduce((a, b) => a + b, 0);
      if (tot > maxDaily) { maxDaily = tot; peakDay = d; }
      dayStack.push(seg);
    }
    const m = METRICS.find((x) => x[0] === metric);
    legendEl.textContent = `${m[1]}: ${m[2]}`;
    statsEl.textContent = `${P} projects · ${D} days · ${humanTok(snap.all_time.output)} output · `
      + `${humanTok(snap.all_time.total)} processed · ${snap.all_time.replies.toLocaleString()} replies`;
  }

  function measure() {
    const rect = svg.getBoundingClientRect();
    W = rect.width; H = rect.height;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    padL = Math.max(16, Math.min(160, W * 0.14)); padR = Math.max(16, W * 0.06);
    odoH = clamp(H * 0.17, 70, 130);
    stripH = clamp(H * 0.24, 70, 200);
    stripTop = H - stripH - 26;
    barTop = odoH + 10;
    barH = Math.max(60, stripTop - barTop - 24);
  }

  // ---- static scaffolding (rebuilt on data/metric/resize) ----------------
  let barEls = [], colEls = [], odoBig = null, odoSmall = null, odoDay = null, peakMark = null, cursor = null;
  function build() {
    gOdo.replaceChildren(); gBars.replaceChildren(); gStrip.replaceChildren();
    odoBig = svgEl("text"); odoBig.setAttribute("class", "tk-odo-big");
    odoBig.setAttribute("x", padL); odoBig.setAttribute("y", odoH * 0.58); odoBig.setAttribute("filter", "url(#tk-glow)");
    odoSmall = svgEl("text"); odoSmall.setAttribute("class", "tk-odo-small");
    odoSmall.setAttribute("x", padL); odoSmall.setAttribute("y", odoH * 0.88);
    odoDay = svgEl("text"); odoDay.setAttribute("class", "tk-odo-day");
    odoDay.setAttribute("x", W - padR); odoDay.setAttribute("y", odoH * 0.58); odoDay.setAttribute("text-anchor", "end");
    gOdo.append(odoBig, odoSmall, odoDay);

    barEls = names.map((n) => {
      const g = svgEl("g"); g.setAttribute("class", "tk-bar");
      const r = svgEl("rect"); r.setAttribute("rx", 4); r.setAttribute("fill", colorFor(n));
      const label = svgEl("text"); label.setAttribute("class", "tk-bar-name"); label.setAttribute("text-anchor", "end");
      label.textContent = n;
      const val = svgEl("text"); val.setAttribute("class", "tk-bar-val");
      g.append(r, label, val);
      gBars.appendChild(g);
      return { g, r, label, val, shown: null };
    });

    const colW = (W - padL - padR) / Math.max(1, D);
    colEls = dayStack.map((seg, d) => {
      const g = svgEl("g");
      let y = stripTop + stripH;
      seg.forEach((v, s) => {
        const h = (v / maxDaily) * stripH;
        if (h < 0.3) return;
        const r = svgEl("rect");
        r.setAttribute("x", padL + d * colW + colW * 0.12); r.setAttribute("width", Math.max(1, colW * 0.76));
        y -= h; r.setAttribute("y", y); r.setAttribute("height", h);
        r.setAttribute("fill", colorFor(stackNames[s]));
        g.appendChild(r);
      });
      g.setAttribute("opacity", "0.12");
      gStrip.appendChild(g);
      return { g, lit: false };
    });
    const base = svgEl("line");
    base.setAttribute("x1", padL); base.setAttribute("x2", W - padR);
    base.setAttribute("y1", stripTop + stripH + 0.5); base.setAttribute("y2", stripTop + stripH + 0.5);
    base.setAttribute("class", "tk-axis");
    gStrip.appendChild(base);
    // month ticks under the strip
    days.forEach((day, d) => {
      // the first day gets a label too, unless a month boundary is right behind it
      if (day.endsWith("-01") || (d === 0 && Number(day.slice(8)) < 20)) {
        const t = svgEl("text"); t.setAttribute("class", "tk-tick");
        t.setAttribute("x", padL + d * colW); t.setAttribute("y", stripTop + stripH + 16);
        t.textContent = new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { month: "short" });
        gStrip.appendChild(t);
      }
    });
    const lbl = svgEl("text"); lbl.setAttribute("class", "tk-tick");
    lbl.setAttribute("x", padL); lbl.setAttribute("y", stripTop - 6);
    lbl.textContent = `per day · peak ${humanTok(maxDaily)} on ${peakDay >= 0 ? fmtDay(days[peakDay]) : "—"}`;
    gStrip.appendChild(lbl);
    peakMark = svgEl("text"); peakMark.setAttribute("class", "tk-peak"); peakMark.setAttribute("text-anchor", "middle");
    peakMark.textContent = "▼ peak";
    if (peakDay >= 0) {
      const top = dayStack[peakDay].reduce((a, b) => a + b, 0) / maxDaily * stripH;
      peakMark.setAttribute("x", padL + (peakDay + 0.5) * colW); peakMark.setAttribute("y", stripTop + stripH - top - 4);
    }
    peakMark.setAttribute("opacity", "0");
    gStrip.appendChild(peakMark);
    cursor = svgEl("line"); cursor.setAttribute("class", "tk-cursor");
    cursor.setAttribute("y1", stripTop - 2); cursor.setAttribute("y2", stripTop + stripH + 2);
    gStrip.appendChild(cursor);
  }

  // ---- one frame: a pure function of f ------------------------------------
  function draw() {
    if (!D) return;
    const x = f * (D - 1);
    const i = Math.floor(x), j = Math.min(D - 1, i + 1), fr = x - i;
    const fleet = lerp(fleetCum[i], fleetCum[j], fr);
    odoBig.textContent = humanTok(fleet);
    odoSmall.textContent = `${Math.round(fleet).toLocaleString()} ${metric === "output" ? "output tokens" : "tokens processed"}`;
    odoDay.textContent = fmtDay(days[Math.round(x)]);
    clockEl.textContent = days[Math.round(x)];

    // bar race
    // One spare slot below the race: a bar dropping out fades through it instead of drawing
    // over the day strip.
    const slot = barH / (TOP_BARS + 1);
    let maxV = 1;
    for (let p = 0; p < P; p++) maxV = Math.max(maxV, lerp(cum[p][i], cum[p][j], fr));
    const barW = W - padL - padR - 70;
    for (let p = 0; p < P; p++) {
      const e = barEls[p];
      const r = lerp(rank[i][p], rank[j][p], fr);
      const v = lerp(cum[p][i], cum[p][j], fr);
      const visible = r < TOP_BARS && v > 0;
      if (!visible) { if (e.shown !== false) { e.g.setAttribute("opacity", "0"); e.shown = false; } continue; }
      e.shown = true;
      const op = clamp(TOP_BARS - r, 0, 1);
      const y = barTop + r * slot;
      const w = Math.max(2, (v / maxV) * barW);
      const h = slot * 0.74;
      e.g.setAttribute("opacity", op.toFixed(3));
      e.r.setAttribute("x", padL); e.r.setAttribute("y", y); e.r.setAttribute("width", w); e.r.setAttribute("height", h);
      e.label.setAttribute("x", padL - 8); e.label.setAttribute("y", y + h / 2);
      e.val.setAttribute("x", padL + w + 6); e.val.setAttribute("y", y + h / 2);
      e.val.textContent = humanTok(v);
      // a project spending TODAY glows: its share of the day vs the day's biggest spender
      const today = daily[p][Math.round(x)];
      e.r.setAttribute("filter", today > 0 && today >= maxDaily * 0.08 ? "url(#tk-glow)" : "");
    }

    // day strip
    const colW = (W - padL - padR) / Math.max(1, D);
    for (let d = 0; d < D; d++) {
      const lit = d <= x + 1e-9;
      if (lit !== colEls[d].lit) { colEls[d].g.setAttribute("opacity", lit ? "0.95" : "0.12"); colEls[d].lit = lit; }
    }
    cursor.setAttribute("x1", padL + (x + 0.5) * colW); cursor.setAttribute("x2", padL + (x + 0.5) * colW);
    peakMark.setAttribute("opacity", peakDay >= 0 && x >= peakDay ? "1" : "0");
  }

  // ---- controls -----------------------------------------------------------
  const metricsEl = root.querySelector("#tk-metrics");
  METRICS.forEach(([key, label, tip]) => {
    const b = document.createElement("button");
    b.className = "hm-layout" + (key === metric ? " on" : ""); b.textContent = label; b.title = tip;
    b.addEventListener("click", () => {
      if (metric === key) return;
      metric = key;
      try { localStorage.setItem(LS_METRIC, metric); } catch (_) {}
      metricsEl.querySelectorAll(".hm-layout").forEach((x) => x.classList.toggle("on", x === b));
      if (snap) { prepare(); build(); draw(); }
    });
    metricsEl.appendChild(b);
  });
  const speedsEl = root.querySelector("#tk-speeds");
  SPEEDS.forEach((s) => {
    const b = document.createElement("button");
    b.className = "hm-speed" + (s === speed ? " on" : ""); b.textContent = `${s}×`;
    b.addEventListener("click", () => {
      speed = s;
      speedsEl.querySelectorAll(".hm-speed").forEach((x) => x.classList.toggle("on", x === b));
    });
    speedsEl.appendChild(b);
  });
  playBtn.addEventListener("click", () => {
    if (!playing && f >= 1) { played = 0; f = 0; }   // replay from the start
    playing = !playing;
    playBtn.textContent = playing ? "⏸" : "▶";
  });
  scrub.addEventListener("pointerdown", () => { dragging = true; });
  root._pointerUp = () => { dragging = false; };
  window.addEventListener("pointerup", root._pointerUp);
  scrub.addEventListener("input", () => {
    f = scrub.value / 1000; played = f * BASE_SECONDS;
    draw();
  });

  function tick(ts) {
    if (!root) return;
    const dt = lastTs ? Math.min(0.1, (ts - lastTs) / 1000) : 0;
    lastTs = ts;
    if (playing && !dragging && D) {
      played += dt * speed;
      f = clamp(played / BASE_SECONDS, 0, 1);
      if (f >= 1) { playing = false; playBtn.textContent = "↻"; }
      scrub.value = String(Math.round(f * 1000));
      draw();
    }
    raf = requestAnimationFrame(tick);
  }

  onResize = () => { if (!snap) return; measure(); build(); draw(); };
  window.addEventListener("resize", onResize);

  async function load() {
    let j = null;
    try {
      const r = await fetch("/api/tokens/history");
      j = r.ok ? await r.json() : null;
    } catch (_) { j = null; }
    if (!root) return;
    if (!j) { statsEl.textContent = "couldn't load the token history"; return; }
    if (!j.ready || !j.days.length) {
      // The very first scan reads every transcript on the box, paced so it never starves the
      // disk — minutes, once. Say so and check back, rather than drawing an empty chart.
      statsEl.textContent = j.ready ? "no token usage found in any transcript yet"
        : "counting every transcript for the first time — paced to go easy on the disk, a few minutes, once…";
      if (!j.ready) pollTimer = setTimeout(load, 5000);
      return;
    }
    snap = j;
    prepare(); measure(); build();
    f = 0; played = 0; draw();
    raf = requestAnimationFrame(tick);
  }
  load();
}
