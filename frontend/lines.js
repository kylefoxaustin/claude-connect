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

// Autonomy windows — the green connectors. Drawn into the SAME overlay as the bus
// wires, so they re-anchor for free whenever a tile is dragged or resized.
//
// Topology matters here: a clique reads beautifully for a handful of sessions, but
// "whole fleet" over 30 tiles would be 435 lines of spaghetti. So: draw every pair up
// to 6 members, and a closed ring beyond that — N lines instead of N²/2, and a loop
// still reads unmistakably as "this group is wired together".
// Where the line from `from` toward `to` crosses the tile's border. Drawing
// edge-to-edge instead of centre-to-centre matters: adjacent tiles are usually only
// a gap apart, so a centre-to-centre line is almost entirely UNDER the two tiles —
// which is why the green wires seemed to vanish in "lines behind" mode. Clipped to
// the borders, the whole line lives in the gap between them and never crosses tile
// content in either mode.
function edgePoint(rect, toward) {
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = toward.x - cx;
  const dy = toward.y - cy;
  if (!dx && !dy) return { x: cx, y: cy };
  const sx = dx ? (rect.width / 2) / Math.abs(dx) : Infinity;
  const sy = dy ? (rect.height / 2) / Math.abs(dy) : Infinity;
  const s = Math.min(sx, sy);                       // first slab we exit through
  return { x: cx + dx * s, y: cy + dy * s };
}

function drawAutonomyLinks(layer, state) {
  const wins = (state.autonomy && state.autonomy.windows) || [];
  for (const w of wins) {
    const els = (w.members || []).map(sessionTileElByTag).filter(Boolean);
    if (els.length < 2) continue;
    const pairs = [];
    if (els.length <= 6) {
      for (let i = 0; i < els.length; i++)
        for (let j = i + 1; j < els.length; j++) pairs.push([els[i], els[j]]);
    } else {
      for (let i = 0; i < els.length; i++) pairs.push([els[i], els[(i + 1) % els.length]]);
    }
    for (const [ea, eb] of pairs) {
      const ra = ea.getBoundingClientRect(), rb = eb.getBoundingClientRect();
      const a = edgePoint(ra, center(eb));
      const b = edgePoint(rb, center(ea));
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", `M ${a.x} ${a.y} L ${b.x} ${b.y}`);
      path.setAttribute("class", "autonomy-link");
      path.dataset.a = ea.dataset.tag || "";
      path.dataset.b = eb.dataset.tag || "";
      layer.appendChild(path);
      // A dot on each end, so a very short hop between neighbours still reads as
      // a deliberate connection rather than a stray dash.
      for (const p of [a, b]) {
        const dot = document.createElementNS(SVG_NS, "circle");
        dot.setAttribute("cx", p.x);
        dot.setAttribute("cy", p.y);
        dot.setAttribute("r", "3.5");
        dot.setAttribute("class", "autonomy-plug");
        layer.appendChild(dot);
      }
    }
  }
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

  // Green "they may talk to each other" connectors. Always drawn into the FRONT
  // layer (above the tiles), never the main overlay — these are semantic, not
  // decoration, so the "lines behind tiles" preference must not be able to bury them.
  drawAutonomyLinks(front || svg, state);
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
