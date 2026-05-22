// lines.js — SVG connection lines from the Bus tile to subscribed session tiles.

const SVG_NS = "http://www.w3.org/2000/svg";

function busTileEl() {
  return document.querySelector('.tile.bus-tile');
}
function sessionTileEl(sessionId) {
  return document.querySelector(`.tile[data-session-id="${CSS.escape(sessionId)}"]`);
}
function sessionTileElByTag(tag) {
  return document.querySelector(`.tile[data-tag="${CSS.escape(tag)}"]`);
}

function center(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

export function redrawLines(state) {
  const svg = document.getElementById("lines-overlay");
  if (!svg) return;

  // Match SVG viewport to the current viewport (lines are positioned in client coords).
  svg.setAttribute("viewBox", `0 0 ${window.innerWidth} ${window.innerHeight}`);
  svg.setAttribute("width", String(window.innerWidth));
  svg.setAttribute("height", String(window.innerHeight));

  // The always-on-top anchor layer (plug + stub) used in "lines behind" mode.
  const front = document.getElementById("lines-front");
  if (front) {
    front.setAttribute("viewBox", `0 0 ${window.innerWidth} ${window.innerHeight}`);
    front.setAttribute("width", String(window.innerWidth));
    front.setAttribute("height", String(window.innerHeight));
    while (front.firstChild) front.removeChild(front.firstChild);
  }
  const behind = document.body.classList.contains("lines-behind");

  // Clear previous lines.
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const bus = busTileEl();
  if (!bus) return;
  const subs = state.busTopology?.subscribers || {};
  const subKeys = Object.keys(subs);
  if (!subKeys.length) return;

  // Active tags are auto-notified of new traffic (solid line); the rest are
  // passive — on the bus but only manual, so they won't see broadcasts (dashed).
  const activeTags = new Set(state.busActiveTags || []);

  const c = center(bus);
  for (const key of subKeys) {
    // Markdown bus: subscriber keys are tags like "[backend]". Resolve to a
    // session tile by tag, falling back to session_id (jsonl bus shape).
    const node = sessionTileElByTag(key) || sessionTileEl(key);
    if (!node) continue;
    // Terminate the wire at the tag chip (the bus identity + Active/Passive
    // toggle) rather than the tile center, so the connection point is obvious.
    // Anchor at the chip's bottom-left corner so the line/plug sit off the label.
    const chip = node.querySelector(".tag-chip");
    let t;
    if (chip) {
      const r = chip.getBoundingClientRect();
      t = { x: r.left, y: r.bottom };
    } else {
      t = center(node);
    }
    const active = activeTags.has(key);
    const path = document.createElementNS(SVG_NS, "path");
    const cx = (c.x + t.x) / 2;
    const cy = (c.y + t.y) / 2 - 20;
    path.setAttribute("d", `M${c.x},${c.y} Q${cx},${cy} ${t.x},${t.y}`);
    path.setAttribute("class", active ? "line" : "line line-passive");
    // Index by both session_id and tag so animateLineFor() can target either.
    const sid = node.dataset.sessionId || "";
    const tag = node.dataset.tag || "";
    if (sid) path.dataset.sessionId = sid;
    if (tag) path.dataset.tag = tag;
    svg.appendChild(path);

    // The plug dot (and, in behind mode, a short stub) anchor the wire to its
    // chip. In behind mode they go on the front layer so they sit in front of
    // THIS tile while the main wire stays behind every tile; otherwise they
    // ride along with the wire in the main overlay.
    const layer = (behind && front) ? front : svg;
    if (behind && front) {
      // Short stub continuing the curve's tangent at the chip (toward the
      // control point), so the wire visibly emerges in front of its own tile.
      const dx = cx - t.x, dy = cy - t.y;
      const len = Math.hypot(dx, dy) || 1;
      const s = Math.min(24, len);
      const stub = document.createElementNS(SVG_NS, "path");
      stub.setAttribute("d", `M${t.x},${t.y} L${t.x + (dx / len) * s},${t.y + (dy / len) * s}`);
      stub.setAttribute("class", active ? "line" : "line line-passive");
      front.appendChild(stub);
    }
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", t.x);
    dot.setAttribute("cy", t.y);
    dot.setAttribute("r", "3");
    dot.setAttribute("class", active ? "line-plug" : "line-plug line-plug-passive");
    layer.appendChild(dot);
  }
}

export function animateLineFor(sessionId) {
  if (sessionId === "broadcast") return; // app.js handles fan-out
  if (window.conductorPrefs && !window.conductorPrefs.animation) return;
  const svg = document.getElementById("lines-overlay");
  if (!svg) return;
  const path = svg.querySelector(`path[data-session-id="${CSS.escape(sessionId)}"]`);
  if (!path) return;
  path.classList.remove("flowing");
  void path.getBoundingClientRect();  // restart animation
  path.classList.add("flowing");
  setTimeout(() => path.classList.remove("flowing"), 800);
}
