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
    const t = center(node);
    const path = document.createElementNS(SVG_NS, "path");
    const cx = (c.x + t.x) / 2;
    const cy = (c.y + t.y) / 2 - 20;
    path.setAttribute("d", `M${c.x},${c.y} Q${cx},${cy} ${t.x},${t.y}`);
    path.setAttribute("class", activeTags.has(key) ? "line" : "line line-passive");
    // Index by both session_id and tag so animateLineFor() can target either.
    const sid = node.dataset.sessionId || "";
    const tag = node.dataset.tag || "";
    if (sid) path.dataset.sessionId = sid;
    if (tag) path.dataset.tag = tag;
    svg.appendChild(path);
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
