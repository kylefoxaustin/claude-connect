/* Conductor Ops — the phone console.
 *
 * One job: show what is blocked on Kyle, and let him unblock it in a tap. Everything
 * else is secondary and lives behind a tab.
 *
 * Deliberately NOT a port of app.js. It shares no code with the desktop board, because
 * the moment it did, the board's assumptions (tiles have positions, lines have layers,
 * a session is a thing you arrange) would come with it.
 */

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- auth
// The token rides in the URL hash on the native app and is remembered here otherwise.
// Same scheme as the desktop shell so one token unlocks both.
const LS_TOKEN = "conductor.authToken";
let TOKEN = "";
(function initToken() {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) {
    TOKEN = decodeURIComponent(m[1]);
    try { localStorage.setItem(LS_TOKEN, TOKEN); } catch { /* private mode */ }
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try { TOKEN = localStorage.getItem(LS_TOKEN) || ""; } catch { TOKEN = ""; }
  }
})();

// The backend reads X-Conductor-Token (or ?token= for the WS handshake, which cannot
// carry headers). NOT an Authorization header — matching what the middleware actually
// checks, rather than what a REST API "should" use.
const headers = () => (TOKEN ? { "X-Conductor-Token": TOKEN } : {});

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...headers(), ...(opts.headers || {}) },
  });
  if (res.status === 401) { showGate(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    const e = new Error(detail);
    e.status = res.status;
    throw e;
  }
  return res.status === 204 ? null : res.json();
}

function showGate() {
  $("gate").hidden = false;
  $("app").hidden = true;
}

$("gate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  TOKEN = $("gate-token").value.trim();
  try {
    await api("/api/ops");
    try { localStorage.setItem(LS_TOKEN, TOKEN); } catch { /* private mode */ }
    $("gate").hidden = true;
    $("app").hidden = false;
    start();
  } catch {
    $("gate-err").textContent = "That token didn't work.";
    $("gate-err").hidden = false;
  }
});

// ---------------------------------------------------------------- state
let ops = null;
const selected = new Map();  // session_id -> array of Sets, one per question

// ---------------------------------------------------------------- helpers
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function ago(sec) {
  if (sec == null) return "";
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

const bare = (t) => String(t || "").replace(/^\[|\]$/g, "").replace(/^other:/, "");
const nameOf = (cwd) => String(cwd || "").split("/").filter(Boolean).pop() || "?";

// ---------------------------------------------------------------- render
function render() {
  if (!ops) return;
  const c = ops.counts;

  $("counts").innerHTML = [
    c.needs_you ? `<span class="hot"><b>${c.needs_you}</b> need you</span>` : "",
    c.blocked ? `<span class="hot"><b>${c.blocked}</b> stuck</span>` : "",
    `<span><b>${c.working}</b> working</span>`,
    `<span><b>${c.idle}</b> idle</span>`,
  ].filter(Boolean).join("");

  renderInbox();
  renderFleet();
  renderAutonomy();
  renderBlocked();

  setBadge("inbox", c.needs_you, "badge");
  setBadge("blocked", c.blocked, "badge badge-warn");
  setBadge("auto", ops.autonomy.length, "badge badge-ok");
  $("inbox-n").textContent = c.needs_you ? `· ${c.needs_you}` : "";
}

function setBadge(pane, n, cls) {
  const el = $(`tab-badge-${pane}`);
  if (!el) return;
  el.hidden = !n;
  el.className = cls;
  el.textContent = n > 99 ? "99+" : String(n);
}

/* ---- NEEDS YOU: decisions first, then push approvals ------------------- */
function renderInbox() {
  const host = $("inbox");
  const items = [];

  for (const d of ops.decisions) items.push(decisionCard(d));
  for (const p of ops.push) items.push(pushCard(p));

  if (!items.length) {
    host.innerHTML =
      `<div class="empty"><div class="empty-big">✅</div>Nothing is waiting on you.</div>`;
    return;
  }
  host.replaceChildren(...items);
}

function decisionCard(d) {
  const el = document.createElement("div");
  el.className = "card card-hot";
  const who = bare(d.tag) || nameOf(d.cwd);

  // One Set of chosen labels per question. Kept across re-renders so a 3s poll can't
  // wipe a selection out from under a thumb mid-tap.
  if (!selected.has(d.session_id)) {
    selected.set(d.session_id, d.questions.map(() => new Set()));
  }
  const sel = selected.get(d.session_id);

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML =
    `<span class="card-who">❓ ${esc(who)}</span>` +
    `<span class="row-age">${ago(d.age)}</span>`;
  el.appendChild(head);

  d.questions.forEach((q, qi) => {
    const qEl = document.createElement("div");
    qEl.className = "card-q";
    qEl.textContent = q.question;
    el.appendChild(qEl);

    q.options.forEach((o) => {
      const b = document.createElement("button");
      const on = () => sel[qi].has(o.label);
      const paint = () => {
        b.className = "opt" + (on() ? " opt-on" : "");
        b.querySelector(".opt-box").textContent = on() ? "✓" : "";
      };
      b.innerHTML =
        `<span class="opt-box${q.multiSelect ? "" : " opt-radio"}"></span>` +
        `<span class="opt-text"><span class="opt-l">${esc(o.label)}</span>` +
        (o.description ? `<span class="opt-d">${esc(o.description)}</span>` : "") +
        `</span>`;
      b.addEventListener("click", () => {
        if (q.multiSelect) {
          on() ? sel[qi].delete(o.label) : sel[qi].add(o.label);
        } else {
          // Single-select: choosing replaces. The picker on the other end can only
          // hold one, so the UI must not let him believe otherwise.
          sel[qi].clear();
          sel[qi].add(o.label);
        }
        el.querySelectorAll(".opt").forEach((x) => x.dispatchEvent(new Event("repaint")));
        submit.disabled = sel.some((s) => s.size === 0);
      });
      b.addEventListener("repaint", paint);
      paint();
      el.appendChild(b);
    });
  });

  const submit = document.createElement("button");
  submit.className = "btn btn-primary";
  submit.style.width = "100%";
  submit.style.marginTop = "6px";
  submit.textContent = "Send answer";
  submit.disabled = true;
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    submit.textContent = "Sending…";
    try {
      await api(`/api/decisions/${encodeURIComponent(d.session_id)}`, {
        method: "POST",
        body: JSON.stringify({ answers: sel.map((s) => [...s]) }),
      });
      selected.delete(d.session_id);
      // No Undo here on purpose: the answer IS the keystroke, it has already landed in
      // the Claude, and there is nothing to take back. Undo would be a lie.
      submit.textContent = "✅ Sent";
      await refresh();
    } catch (e) {
      // The common case is benign — he answered it at the keyboard a moment ago.
      submit.textContent = e.status === 409 ? "Already answered" : `Failed: ${e.message}`;
      setTimeout(refresh, 1500);
    }
  });
  el.appendChild(submit);
  return el;
}

/* A push approval is REVERSIBLE for five seconds instead of gated behind a confirm
 * dialog. A dialog you see twenty times a day is habituated within a week and then it
 * protects nobody; an undo window covers the only moment a mistake is actually noticed. */
let undoTimer = null;
let pendingApprove = null;

function pushCard(p) {
  const el = document.createElement("div");
  el.className = "card";
  const age = p.epoch ? Date.now() / 1000 - p.epoch : null;
  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">🔐 ${esc(p.repo_name || nameOf(p.cwd))}</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="row-sub">wants to push · <code>${esc(p.cmd || "git push")}</code></div>`;

  const row = document.createElement("div");
  row.className = "btn-row";
  row.style.marginTop = "12px";

  const approve = document.createElement("button");
  approve.className = "btn btn-primary";
  approve.textContent = "Approve";
  approve.addEventListener("click", () => armApprove(p, el));

  const deny = document.createElement("button");
  deny.className = "btn btn-danger";
  deny.textContent = "Deny";
  // Deny needs no undo: it's recoverable by construction — the agent just asks again.
  deny.addEventListener("click", async () => {
    deny.disabled = approve.disabled = true;
    await api(`/api/push/${encodeURIComponent(p.key)}/deny`, { method: "POST" }).catch(() => {});
    refresh();
  });

  row.append(approve, deny);
  el.appendChild(row);
  return el;
}

function armApprove(p, card) {
  card.style.opacity = ".45";
  pendingApprove = p;
  $("snack-text").textContent = `Approving push to ${p.repo || nameOf(p.cwd)}…`;
  $("snack").hidden = false;
  clearTimeout(undoTimer);
  undoTimer = setTimeout(async () => {
    $("snack").hidden = true;
    const target = pendingApprove;
    pendingApprove = null;
    if (!target) return;
    try {
      await api(`/api/push/${encodeURIComponent(target.key)}/approve`, { method: "POST" });
    } catch { /* refresh will show the truth */ }
    refresh();
  }, 5000);
}

$("snack-undo").addEventListener("click", () => {
  clearTimeout(undoTimer);
  pendingApprove = null;
  $("snack").hidden = true;
  render();                       // un-dim the card; nothing was ever sent
});

/* ---- FLEET: a list, grouped by state. Never a grid of 30 tiles. -------- */
function renderFleet() {
  const host = $("fleet");
  if (!ops.sessions.length) {
    host.innerHTML = `<div class="empty">No live sessions.</div>`;
    return;
  }
  host.replaceChildren(...ops.sessions.map((s) => {
    const el = document.createElement("div");
    el.className = "row";
    const badges = [
      s.asking ? `<span class="pill pill-ask">ASKING</span>` : "",
      s.pending ? `<span class="pill">📬 ${s.pending}</span>` : "",
    ].join("");
    el.innerHTML =
      `<span class="st st-${esc(s.status)}"></span>` +
      `<div class="row-body">` +
      `<div class="row-title">${esc(s.name)} ${badges}</div>` +
      `<div class="row-sub">${esc(s.preview || s.status)}</div>` +
      `</div>` +
      `<span class="row-age">${ago(s.idle_seconds)}</span>`;
    return el;
  }));
}

/* ---- UNATTENDED ------------------------------------------------------- */
function renderAutonomy() {
  const host = $("autonomy");
  if (!ops.autonomy.length) {
    host.innerHTML =
      `<div class="empty">Nobody is talking unattended.<br>` +
      `Sessions only wake each other when you allow it.</div>`;
    return;
  }
  const now = Date.now() / 1000;
  host.replaceChildren(...ops.autonomy.map((w) => {
    const el = document.createElement("div");
    el.className = "row";
    const left = Math.max(0, w.expires - now);   // the store's field is `expires`
    el.innerHTML =
      `<div class="row-body">` +
      `<div class="row-title">🔗 ${w.members.length} sessions</div>` +
      `<div class="row-sub">${esc(w.members.map(bare).join(", "))}</div>` +
      `</div>` +
      `<span class="row-age">${ago(left)} left</span>`;
    const rev = document.createElement("button");
    rev.className = "btn btn-danger";
    rev.textContent = "Revoke";
    rev.addEventListener("click", async () => {
      rev.disabled = true;
      await api(`/api/autonomy/${encodeURIComponent(w.id)}`, { method: "DELETE" }).catch(() => {});
      refresh();
    });
    el.appendChild(rev);
    return el;
  }));
}

$("grant-go").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    await api("/api/autonomy", {
      method: "POST",
      body: JSON.stringify({
        members: ops.sessions.map((s) => s.tag).filter(Boolean),
        hours: Number($("grant-hours").value),
      }),
    });
    await refresh();
  } finally {
    e.target.disabled = false;
  }
});

/* ---- BLOCKED ---------------------------------------------------------- */
function renderBlocked() {
  const host = $("blocked");
  const w = ops.waiting || {};
  const hard = (w.edges || []).filter((e) => e.hard);
  const bits = [];

  for (const c of w.cycles || []) {
    const el = document.createElement("div");
    el.className = "card" + (c.deadlock ? " card-hot" : "");
    el.innerHTML =
      `<div class="card-who">${c.deadlock ? "🛑 DEADLOCK" : "🔁 Mutual stall"}</div>` +
      `<div class="row-sub" style="white-space:normal">${esc(c.nodes.join(" → "))} → ${esc(c.nodes[0])}</div>` +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">${esc(c.label)}</div>`;
    bits.push(el);
  }

  for (const e of hard) {
    const el = document.createElement("div");
    el.className = "row";
    el.innerHTML =
      `<div class="row-body">` +
      `<div class="row-title">${esc(e.src)} → ${esc(e.dst)}</div>` +
      `<div class="row-sub">${esc(e.why)}</div>` +
      `</div><span class="row-age">${ago(e.age)}</span>`;
    bits.push(el);
  }

  if (!bits.length) {
    // Deliberately does NOT count the soft "awaiting a reply" edges as trouble. A
    // dashboard that shouts on a healthy fleet is one you learn to ignore — and then it
    // won't be believed the night something genuinely deadlocks.
    const awaiting = w.awaiting_count || 0;
    host.innerHTML =
      `<div class="empty"><div class="empty-big">👍</div>Nobody is stuck.` +
      (awaiting ? `<br><span style="font-size:13px">${awaiting} awaiting a reply — that's a conversation, not a problem.</span>` : "") +
      `</div>`;
    return;
  }
  host.replaceChildren(...bits);
}

// ---------------------------------------------------------------- tabs
const PANES = ["inbox", "fleet", "auto", "blocked"];

function showPane(name) {
  if (!PANES.includes(name)) name = "inbox";
  document.querySelectorAll(".tab").forEach(
    (x) => x.classList.toggle("tab-on", x.dataset.pane === name));
  for (const p of PANES) $(`pane-${p}`).hidden = p !== name;
  window.scrollTo(0, 0);
}

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => showPane(t.dataset.pane));
});

// Deep-link a pane: /m?pane=blocked. A notification needs to open the SCREEN it is about,
// not the app's front door — landing on the inbox and making him hunt is how GitHub
// Mobile's approval flow ends up unusable.
showPane(new URLSearchParams(location.search).get("pane") || "inbox");

// ---------------------------------------------------------------- notifications
/* Web Push. Every failure mode here is silent — permission denied, a service worker that
 * never activated, a stale VAPID key — and all of them look identical to "nothing needs
 * you". So the UI always states which of those it is, and there is a Test button. */
const notifBtn = $("notif-btn");
const notifState = $("notif-state");

function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function notifStatus() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return { state: "unsupported", text: "This browser can't do notifications." };
  }
  if (!window.isSecureContext) {
    // The classic trap: over plain http everything "works" and simply never rings.
    return { state: "insecure", text: "Needs HTTPS. Open the https:// address." };
  }
  if (Notification.permission === "denied") {
    return { state: "denied", text: "Blocked. Re-allow in your browser's site settings." };
  }
  const reg = await navigator.serviceWorker.getRegistration("/m");
  const sub = reg && (await reg.pushManager.getSubscription());
  if (sub) return { state: "on", text: "On for this device." };
  return { state: "off", text: "Off. You'll only see things when you open the app." };
}

async function paintNotif() {
  if (!notifBtn) return;
  const st = await notifStatus();
  notifState.textContent = st.text;
  notifBtn.hidden = ["unsupported", "insecure", "denied"].includes(st.state);
  notifBtn.textContent = st.state === "on" ? "Send a test" : "Turn on notifications";
  notifBtn.dataset.mode = st.state === "on" ? "test" : "enable";
}

async function enableNotifications() {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return paintNotif();
  const reg = await navigator.serviceWorker.register("/m/sw.js", { scope: "/m" });
  await navigator.serviceWorker.ready;
  const { key } = await api("/api/webpush/key");
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlB64ToUint8Array(key),
  });
  await api("/api/webpush/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
  await paintNotif();
}

if (notifBtn) {
  notifBtn.addEventListener("click", async () => {
    notifBtn.disabled = true;
    try {
      if (notifBtn.dataset.mode === "test") {
        const r = await api("/api/webpush/test", { method: "POST" });
        notifState.textContent = r.sent
          ? `Sent to ${r.sent} device(s) — it should appear now.`
          : "Couldn't deliver. Try turning them on again.";
      } else {
        await enableNotifications();
      }
    } catch (e) {
      notifState.textContent = `Failed: ${e.message}`;
    } finally {
      notifBtn.disabled = false;
    }
  });
}

// A notification click steers an ALREADY-OPEN console to the right pane.
navigator.serviceWorker?.addEventListener("message", (e) => {
  if (e.data?.kind === "navigate") {
    const pane = new URL(e.data.url, location.origin).searchParams.get("pane");
    showPane(pane || "inbox");
    refresh();
  }
});

// ---------------------------------------------------------------- live
async function refresh() {
  try {
    ops = await api("/api/ops");
    $("conn-dot").classList.add("up");
    render();
  } catch {
    $("conn-dot").classList.remove("up");
  }
}

let ws = null;
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
  ws = new WebSocket(`${proto}://${location.host}/ws${q}`);
  // The socket only says "something changed" — we re-fetch /api/ops rather than trying to
  // patch state from six different message kinds. One source of truth, and a missed frame
  // can never leave the console showing a decision that is already answered.
  ws.onmessage = () => refresh();
  ws.onopen = () => { $("conn-dot").classList.add("up"); refresh(); };
  ws.onclose = () => {
    $("conn-dot").classList.remove("up");
    setTimeout(connect, 2000);
  };
}

// A backgrounded mobile tab can have its socket killed WITHOUT `close` firing — so the
// console can sit there looking connected while showing a stale, empty inbox. On the one
// screen that exists to tell you what needs you, that fails silent. Re-sync whenever the
// phone comes back to us, and poll slowly as a floor.
for (const ev of ["visibilitychange", "focus", "online"]) {
  window.addEventListener(ev, () => {
    if (document.visibilityState === "hidden") return;
    refresh();
    if (!ws || ws.readyState > 1) connect();
  });
}
setInterval(refresh, 15000);

async function start() {
  await refresh();
  connect();
  paintNotif();
}

// Is auth even on? If not, go straight in.
(async function boot() {
  try {
    await api("/api/ops");
    $("app").hidden = false;
    start();
  } catch {
    showGate();
  }
})();
