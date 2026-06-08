// scene3d.js — the 3D view (fork ②). A parallel renderer to the 2D board:
// session cards live as real DOM in a CSS3DRenderer scene (so text stays crisp
// and the existing global handlers — requestFocus/toggleBusActive/requestCheck —
// still work), a glowing Bus core sits at the center, and bus wires are drawn on
// an SVG overlay by projecting each card's 3D position back to screen space.
//
// Cards are *billboarded* (always face the camera) — the hard-won lesson from
// the rejected CSS-tilt prototype: never angle the content you have to read.
// Depth/motion live in the SPACE between tiles, never in the text.
//
// This module is dynamically imported by app.js only when 3D is toggled on, so
// a CDN miss on Three.js can never break the 2D default.

import * as THREE from "three";
import { CSS3DRenderer, CSS3DObject } from "three/addons/renderers/CSS3DRenderer.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const CARD_W = 240;

let scene, camera, renderer, controls;
let container, svg, controlsBar;
let busObj;
const busTarget = new THREE.Vector3(0, 0, 0);

// key -> { obj: CSS3DObject, el: HTMLElement, target: Vector3, sess }
const cards = new Map();
// key -> SVGLineElement (bus wire), reused across frames
const wires = new Map();

let layout = "carousel"; // default 3D layout (overridden by saved pref on activate)
let active = false;
let raf = 0;
let rw = 1, rh = 1; // renderer pixel size, refreshed on resize

const _v = new THREE.Vector3(); // scratch for projection

// --- DOM helpers ------------------------------------------------------------
function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) node.append(kid);
  return node;
}

function statusLabel(s) {
  return ({ active: "active", warm: "warm", idle: "idle", dormant: "dormant",
            waiting: "waiting for input", ended: "ended" }[s]) || s || "unknown";
}

// --- Groups (shared with the 2D board via the same localStorage store) -------
function loadGroups() {
  try { return JSON.parse(localStorage.getItem("conductor.groups.v2") || "{}"); }
  catch { return {}; }
}
function groupOfKey(groups, key) {
  for (const g of Object.values(groups)) if (g.members?.includes(key)) return g;
  return null;
}
// Order keys so group members are contiguous (grouped first, by group, then
// ungrouped) — index-based layouts then place each group's cards adjacently.
function orderedKeys() {
  const groups = loadGroups();
  const gid = (k) => groupOfKey(groups, k)?.id ?? null;
  return [...cards.keys()].sort((a, b) => {
    const ga = gid(a), gb = gid(b);
    if (ga === gb) return 0;
    if (ga == null) return 1;
    if (gb == null) return -1;
    return ga < gb ? -1 : 1;
  });
}

// Build the DOM for one session card. Mirrors the 2D tile's look via shared
// classes, but trimmed to what reads well floating in space.
function makeCardEl(s, state) {
  const card = el("div", { class: "card3d" });
  fillCardEl(card, s, state);
  return card;
}

function fillCardEl(card, s, state) {
  card.className = `card3d status-${s.status}`;
  card.dataset.sessionId = s.session_id;
  card.dataset.tag = s.tag || "";

  const busActive = (state.busActiveTags || []).includes(s.tag);
  const tagChip = s.tag
    ? el("span", {
        class: `tag-chip bus-toggle ${busActive ? "bus-active" : "bus-passive"}`,
        title: busActive
          ? `${s.tag} · Active — auto-notified. Click to make Passive.`
          : `${s.tag} · Passive — manual only. Click to make Active.`,
        onclick: (e) => { e.stopPropagation(); window.toggleBusActive(s.tag, !busActive); },
      }, s.tag)
    : null;

  const pending = s.pending_count || 0;
  const pendingBadge = pending > 0
    ? el("span", {
        class: "pending-badge",
        title: `${pending} unread bus message(s) — click to run /msg-check`,
        onclick: (e) => { e.stopPropagation(); window.requestCheck(s.session_id, s.status); },
      }, `📬 ${pending}`)
    : null;

  const focusBtn = el("button", {
    class: "icon-btn",
    title: state.wmctrlAvailable ? "Focus terminal" : "wmctrl not installed",
    disabled: state.wmctrlAvailable ? null : "true",
    onclick: (e) => { e.stopPropagation(); if (state.wmctrlAvailable) window.requestFocus(s.session_id); },
  }, "▶");

  card.replaceChildren(
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: `status-dot ${s.status}`, title: statusLabel(s.status) }),
        el("span", { class: "tile-title", title: s.title || "" }, s.title || "(untitled)"),
      ),
      el("div", { class: "tile-actions" }, pendingBadge, focusBtn),
    ),
    el("div", { class: "tile-projectdir", title: s.project_dir }, tagChip, tagChip ? " " : null, s.project_dir),
    el("div", { class: "tile-preview" }, s.preview || ""),
  );
}

function makeBusEl() {
  return el("div", { class: "bus-core3d" },
    el("div", { class: "bus-core3d-glyph" }, "BUS"),
    el("div", { class: "bus-core3d-count" }, "0 msgs"),
  );
}

// --- Lifecycle --------------------------------------------------------------
export function init() {
  if (renderer) return; // once

  container = el("div", { class: "scene3d" });
  document.body.appendChild(container);

  renderer = new CSS3DRenderer();
  container.appendChild(renderer.domElement);

  // SVG wire overlay sits on top of the cards (bus connections).
  svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "scene3d-wires");
  container.appendChild(svg);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(55, 1, 1, 12000);
  camera.position.set(0, 240, 1700);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 500;
  controls.maxDistance = 5000;
  controls.target.set(0, 0, 0);

  busObj = new CSS3DObject(makeBusEl());
  scene.add(busObj);

  buildControlBar();
  resize();
  window.addEventListener("resize", resize);
}

function buildControlBar() {
  const mk = (name, label) => el("button", {
    class: "scene3d-layout-btn",
    "data-layout": name,
    onclick: () => setLayout(name),
  }, label);

  controlsBar = el("div", { class: "scene3d-controls" },
    el("div", { class: "scene3d-seg" },
      mk("orbital", "Orbital"),
      mk("gallery", "Gallery"),
      mk("carousel", "Carousel"),
    ),
    el("span", { class: "scene3d-hint" }, "drag to orbit · scroll to zoom"),
  );
  container.appendChild(controlsBar);
  syncLayoutButtons();
}

function syncLayoutButtons() {
  if (!controlsBar) return;
  for (const b of controlsBar.querySelectorAll(".scene3d-layout-btn")) {
    b.classList.toggle("on", b.dataset.layout === layout);
  }
}

export function activate(state, savedLayout) {
  init();
  if (savedLayout) layout = savedLayout;
  syncLayoutButtons();
  active = true;
  document.body.classList.add("view-3d");
  container.style.display = "";
  resize();
  update(state);
  if (!raf) loop();
}

export function deactivate() {
  active = false;
  if (raf) { cancelAnimationFrame(raf); raf = 0; }
  if (container) container.style.display = "none";
  document.body.classList.remove("view-3d");
}

export function setLayout(name) {
  layout = name;
  syncLayoutButtons();
  applyLayout();
  if (window.conductorPrefs) { window.conductorPrefs.layout3d = name; window.saveConductorPrefs?.(); }
}

// --- State sync -------------------------------------------------------------
export function update(state) {
  if (!active || !renderer) return;
  const showEnded = window.conductorPrefs ? window.conductorPrefs.showEnded : true;
  const sessions = (state.sessions || []).filter((s) => showEnded || s.status !== "ended");

  const live = new Set();
  for (const s of sessions) {
    const key = `proj:${s.project_dir}`;
    live.add(key);
    let c = cards.get(key);
    if (!c) {
      const el_ = makeCardEl(s, state);
      const obj = new CSS3DObject(el_);
      obj.position.copy(_v.copy(busTarget).add(new THREE.Vector3(0, 0, 1))); // born near bus, lerps out
      scene.add(obj);
      c = { obj, el: el_, target: new THREE.Vector3(), sess: s };
      cards.set(key, c);
    } else {
      fillCardEl(c.el, s, state);
      c.sess = s;
    }
  }

  // Remove cards whose session is gone.
  for (const [key, c] of cards) {
    if (!live.has(key)) {
      scene.remove(c.obj);
      c.el.remove();
      cards.delete(key);
      const w = wires.get(key);
      if (w) { w.remove(); wires.delete(key); }
    }
  }

  const total = state.busTotal || 0;
  const countEl = busObj.element.querySelector(".bus-core3d-count");
  if (countEl) countEl.textContent = `${total} msg${total === 1 ? "" : "s"}`;

  applyLayout();
  applyGroupStyling();

  // Snap brand-new cards straight to their layout target (no fly-in from the
  // origin); the lerp in the loop is reserved for smooth *relayout* transitions.
  for (const c of cards.values()) {
    if (c.__placed) continue;
    c.obj.position.copy(c.target);
    c.__placed = true;
  }
}

// Tint each card with its group color (border + glow); clear it when ungrouped.
function applyGroupStyling() {
  const groups = loadGroups();
  for (const [key, c] of cards) {
    const g = groupOfKey(groups, key);
    if (g) {
      c.el.style.borderColor = g.color;
      c.el.style.boxShadow = `0 0 0 1px ${g.color}, 0 0 22px -4px ${g.color}, 0 18px 40px rgba(0,0,0,0.45)`;
    } else {
      c.el.style.borderColor = "";
      c.el.style.boxShadow = "";
    }
  }
}

// --- Layouts: each just sets every card's target Vector3 --------------------
function applyLayout() {
  const keys = orderedKeys(); // group members contiguous → adjacent placement
  const n = keys.length;
  busTarget.set(0, 0, 0);
  if (!n) return;

  if (layout === "gallery") layoutGallery(keys);
  else if (layout === "carousel") layoutCarousel(keys);
  else layoutOrbital(keys);
}

// Sphere distribution (fibonacci) around the bus — true 3D from any angle.
function layoutOrbital(keys) {
  const n = keys.length;
  const R = Math.max(480, 150 * Math.sqrt(n));
  const golden = Math.PI * (3 - Math.sqrt(5));
  keys.forEach((key, i) => {
    const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2; // 1..-1
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    cards.get(key).target.set(Math.cos(theta) * r * R, y * R, Math.sin(theta) * r * R);
  });
}

// Reuse the durable 2D layout (conductor.positions.v2): keep x/y, lift to depth
// by status so active work floats toward you. Centered on the bus.
function layoutGallery(keys) {
  let positions = {};
  try { positions = JSON.parse(localStorage.getItem("conductor.positions.v2") || "{}"); } catch {}
  const zForStatus = (st) =>
    ({ active: 260, warm: 180, waiting: 90, idle: -60, dormant: -200, ended: -260 }[st] ?? 0);

  // Centroid of known positions so the cloud sits around the bus.
  const known = keys.map((k) => positions[k]).filter((p) => p && Number.isFinite(p.x));
  const cx = known.length ? known.reduce((a, p) => a + p.x, 0) / known.length : 0;
  const cy = known.length ? known.reduce((a, p) => a + p.y, 0) / known.length : 0;

  // Base target = saved position (centered) + depth by status.
  const base = new Map();
  keys.forEach((key, i) => {
    const p = positions[key];
    const st = cards.get(key).sess?.status;
    if (p && Number.isFinite(p.x)) {
      base.set(key, new THREE.Vector3(p.x - cx, -(p.y - cy), zForStatus(st))); // screen y down -> 3D y up
    } else {
      const col = i % 5, row = Math.floor(i / 5);
      base.set(key, new THREE.Vector3((col - 2) * 300, -(row - 1) * 220, zForStatus(st)));
    }
  });

  // Cluster: pull each group's members partway toward the group centroid, so
  // groups tighten into recognizable clumps without losing the saved layout.
  const groups = loadGroups();
  const byGroup = {};
  for (const key of keys) {
    const g = groupOfKey(groups, key);
    if (g) (byGroup[g.id] ||= []).push(key);
  }
  for (const members of Object.values(byGroup)) {
    if (members.length < 2) continue;
    const cen = new THREE.Vector3();
    members.forEach((k) => cen.add(base.get(k)));
    cen.multiplyScalar(1 / members.length);
    members.forEach((k) => base.get(k).lerp(cen, 0.45));
  }

  for (const key of keys) cards.get(key).target.copy(base.get(key));
}

// Horizontal ring in the XZ plane — orbit the camera to spin through it.
function layoutCarousel(keys) {
  const n = keys.length;
  const R = Math.max(520, 130 * n);
  keys.forEach((key, i) => {
    const a = (i / n) * Math.PI * 2;
    cards.get(key).target.set(Math.sin(a) * R, 0, Math.cos(a) * R);
  });
}

// --- Render loop ------------------------------------------------------------
function loop() {
  raf = requestAnimationFrame(loop);
  controls.update();

  for (const c of cards.values()) {
    c.obj.position.lerp(c.target, 0.14);
    c.obj.quaternion.copy(camera.quaternion); // billboard: face the camera
    if (layout === "carousel") {
      const d = camera.position.distanceTo(c.obj.position);
      c.obj.scale.setScalar(THREE.MathUtils.clamp(1600 / d, 0.55, 1.45));
    } else {
      c.obj.scale.setScalar(1);
    }
  }
  busObj.position.lerp(busTarget, 0.2);
  busObj.quaternion.copy(camera.quaternion);

  renderer.render(scene, camera);
  drawWires();
}

// Project the bus + each card to screen space and draw/update the wires.
function drawWires() {
  const bus = projectToScreen(busObj.position);
  for (const [key, c] of cards) {
    let line = wires.get(key);
    if (!line) {
      line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      svg.appendChild(line);
      wires.set(key, line);
    }
    const p = projectToScreen(c.obj.position);
    if (!bus || !p) { line.style.display = "none"; continue; }
    line.style.display = "";
    line.setAttribute("x1", bus.x); line.setAttribute("y1", bus.y);
    line.setAttribute("x2", p.x);   line.setAttribute("y2", p.y);
    const tag = c.sess?.tag;
    const isActive = tag && (window.conductorState?.busActiveTags || []).includes(tag);
    line.setAttribute("class", `wire ${isActive ? "wire-active" : "wire-passive"}`);
  }
}

function projectToScreen(pos) {
  _v.copy(pos).project(camera);
  if (_v.z > 1) return null; // behind the camera
  return { x: (_v.x * 0.5 + 0.5) * rw, y: (-_v.y * 0.5 + 0.5) * rh };
}

// Flash flow along a session's wire when it sends/receives a bus message.
export function animateForTag(tag) {
  for (const c of cards.values()) {
    if (c.sess?.tag === tag) {
      const w = wires.get(`proj:${c.sess.project_dir}`);
      if (w) { w.classList.add("flowing"); setTimeout(() => w.classList.remove("flowing"), 800); }
    }
  }
}

function resize() {
  if (!renderer) return;
  rw = container.clientWidth || window.innerWidth;
  rh = container.clientHeight || (window.innerHeight - 60);
  renderer.setSize(rw, rh);
  camera.aspect = rw / rh;
  camera.updateProjectionMatrix();
  svg.setAttribute("viewBox", `0 0 ${rw} ${rh}`);
  svg.setAttribute("width", rw);
  svg.setAttribute("height", rh);
}
