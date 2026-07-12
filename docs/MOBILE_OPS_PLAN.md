# The phone app is a decision queue, not a dashboard

**Status:** design proposal. Desktop app is explicitly OUT OF SCOPE and unchanged.

## The verdict

Kyle: *"the phone web UI is a dead end and fundamentally flawed. I originally asked to
replicate the desktop app verbatim. That's not what the phone is for."*

He's right, and the reason is **informational, not aesthetic**:

* The desktop app is **spatial** — a free-form canvas where *position carries meaning*
  (you arranged the tiles, grouped them, ran wires between them). That's a **workbench**.
* The phone is **episodic and interruptive** — you open it for 30 seconds because
  something needs you, or to ask *"is it on fire?"* That's a **console**.

**Responsive CSS can shrink a workbench. It cannot turn it into a console.** The failure
was porting the *information architecture* of a map onto a device that needs an *inbox*.

The proof is in the data. Right now: **13 of 15 live sessions are `WAITING`.** The desktop
board, replicated on a phone, shows *fifteen tiles that all say the same thing*. That's not
a small dashboard — **it's zero information.**

## What the research settled

Convergent practice across PagerDuty, Opsgenie, incident.io, FireHydrant, GitHub, Datadog:
**the home screen is a list of things blocked on you, not a picture of the system.**

The two loudest facts:

* **Grafana — the dashboard company — never shipped a mobile dashboard app.** It shipped an
  on-call app and told everyone to use a browser. Datadog's mobile home isn't dashboards
  either. If the dashboard companies won't put a dashboard on a phone, that settles it.
* **GitHub Mobile's gated-deployment approval — structurally the same as our push gate — is
  the one thing it does badly.** It can *only* be reached from a notification; there is no
  way to browse to a pending approval. Open, unresolved, ~2 years.
  → **THE NOTIFICATION MUST NEVER BE THE ONLY DOOR.** Every pending decision lives in a
  durable, browsable inbox. The notification is an accelerator.

The anti-pattern with a name: **the AWS Console trap** — it ported the desktop *IA* and
dropped the *actions*. The lesson is not "mobile should do less". It's **"mobile should do
the ACTIONS and drop the BROWSING."**

## The centrepiece: a decision queue

Kyle: *"a Claude is giving me choices to make — 1 or 2, or select several — and submit it
back. Responding unblocks a lot of work that I currently have to walk to the PC for."*

**This is the product.** The fleet's bottleneck was never observability — it's that **agents
stall waiting for a human choice, and the human has to be physically present.** Across 15
sessions that is enormous dead time.

**And the questions are already on disk.** Claude Code records `AskUserQuestion` in the
session transcript with the full payload:

```
question:    How should I introduce this session to the other Claudes on the bus?
header:      Hello msg      multiSelect: false
  - Just a friendly hello:  Simple greeting: image_gen session is online…
  - Hello + ask what's up:  Greet and ask the active sessions…
  - Hello + state my focus: Greet and mention this is the image_gen project…
```

An `AskUserQuestion` **tool_use with no matching tool_result** is, by definition, a Claude
sitting blocked on a human. **Conductor can surface every question the fleet already asks,
with zero adoption effort.** We never looked.

**Reading the question is free. Getting the answer back in is the hard part** — the picker
is an interactive TUI. Three routes, and they are not equal:

| | route | adoption | risk |
|---|---|---|---|
| **A** | Drive the picker (inject `2`+Enter / arrows+space) | **zero** — captures every native ask | Puppeteering a TUI we don't own. Could silently mis-select. |
| **B** | Inject the option label as free text (the "Other" path) | zero | Depends on the picker accepting text while open. |
| **C** | `bus.sh ask` — agent posts a structured decision, ends its turn; the answer arrives as a normal prompt | needs a fleet habit (~10 min, based on today) | **Bulletproof.** Same injection as `/msg-check`, which we know works. |

**Plan: build C as the guaranteed spine, and TEST A/B for real before promising them.** A
boring mechanism that always works beats a magic one that silently eats a decision. Today
taught that four separate times. **No inferring where we can measure.**

## The screens

### Home — three questions, above the fold, nothing else

Modelled on incident.io (*"am I on call? when next? is anything on fire?"*). Ours:

> **1. Is anything blocked on me?   2. Is anything actually broken?   3. Is the fleet
> running unattended right now?**

If an element doesn't answer one of those, it is not on the home screen.

```
┌──────────────────────────────────────────┐
│ 2 need you · 0 stuck · 1 working · 14 idle│  ← tappable counts = navigation
├──────────────────────────────────────────┤
│ NEEDS YOU                    oldest first │
│                                           │
│ ❓ 93emulator asks — 12m                  │
│    "Which approach for the boot chain?"   │
│    ○ A: model the DDR registers           │
│    ○ B: pass mem= bootarg                 │
│    ○ C: both, gated                       │      ← tap to answer, unblocks instantly
│                                           │
│ 🔐 claude-connect wants to push — 3m      │
│    main · 4 commits                       │
│    [ Approve ]        [ Deny ]            │      ← tap + UNDO. Never swipe-to-approve.
├──────────────────────────────────────────┤
│ 🔗 UNATTENDED: 14 agents · 7h 12m [Revoke]│      ← a JIT grant. Loud while it's open.
└──────────────────────────────────────────┘
        Fleet ▾   (collapsed: working / idle / parked)
```

**Counts as navigation** (Opsgenie). Group by **state, not identity**. Never 30 tiles.

### The action model

| Action | Interaction | Why |
|---|---|---|
| **Answer a decision** | Tap option(s) → Submit | Multi-select where the ask allows it |
| **Approve a push** | **Tap → 5s snackbar with UNDO → then the token mints** | NN/g: a confirm dialog at 20×/day is habituated within a week and **protects nobody**. Undo makes it reversible across the only window where mistakes happen. |
| **Approve `main` / force-push / approve-all** | **Slide-to-confirm** | Escalate friction ONLY for high blast radius. Keep the scary thing rare or it stops being scary. |
| **Deny a push** | Swipe is fine | Recoverable — the agent just re-requests. |
| **NEVER** | ~~Swipe to approve~~ | Swipe is *learned as destructive* and is easy to trigger by accident. PagerDuty's swipe-ack works only because ack is reversible. Ours pushes code to a repo. |
| **Revoke autonomy** | One tap | A JIT grant needs a kill switch (Teleport pattern) |

### Session detail (drill-in, not the home screen)
What it's doing (one line, live), resources held, unread mail, tokens, and the actions:
**Nudge · Message · Relaunch · Release its board.**

## Architecture

**Two frontends, one backend.** A genuinely separate app at `/m` — its own HTML/JS/CSS. It
never imports `tiles.js`. **No canvas, no drag, no wires, no resize grip, no dock.**

This is cheap because **every endpoint already exists**: `/api/push`, `/api/waiting`,
`/api/autonomy`, `/api/resources`, `/api/services`, `/api/sessions`, `/api/relaunch-batch`.
The phone app is a **new view over an API that is already done.**

Two additions:
* **`GET /api/ops`** — one aggregate call with everything the console needs. On a phone over
  a tunnel, six round-trips is the difference between "instant" and "sluggish".
* **`GET/POST /api/decisions`** — the decision queue (read pending asks; submit an answer).

## Notifications — and one hard limit

Web Push on Android is at near-parity with native: service worker + VAPID, action buttons in
the notification (max 2), handled in `notificationclick`. It needs a **secure origin**, which
means flipping **"Enable HTTPS"** in the Tailscale admin console. That is the difference
between *an app you remember to check* and *an app that finds you.*

**But a PWA cannot break through Do Not Disturb.** That is a structural web-platform limit —
every on-call vendor ships native code for it. **The phone cannot wake Kyle at 3am.**

Judgement: **accept it.** A push request can wait until morning; the agent simply retries.
If a genuinely wake-me-up class ever appears, bridge *that class only* through ntfy/Pushover
and leave the PWA as the UI.

**What is notification-worthy** (Google SRE's page test: actionable, needs intelligence,
novel, urgent):

* **Notify:** a decision request. A push approval. A retraction that hasn't landed. *(A human
  is literally the only unblocker.)*
* **Badge only:** stuck sessions, idle leases, queue depth, orphan leases. These are
  **tickets, not pages** — they wait.
* **Never:** anything the watchdog or an agent resolves itself. **If the fix is robotic, it
  isn't a page.**

## Bug this surfaced, to fix BEFORE the UI

**The approval must be durable, not a race.** Notification arrives → phone is in a pocket →
Kyle looks 8 minutes later. The token TTL was 300s (bumped to 30m today, by luck, for an
unrelated reason). Even 30m is a race we don't need to run: **approving a stale request
should arm a token the agent consumes on its next retry.** Otherwise the killer feature will
feel flaky for reasons that have nothing to do with the UI.

## What we are deliberately NOT building

* No mini-canvas. The desktop board's value is *spatial*; that value does not survive a 6"
  screen, and a shrunken canvas keeps the cost (pan/zoom/tap precision) while losing the
  benefit.
* No tile-per-session grid. 30 tiles is not a small dashboard, it's noise.
* No dashboard-authoring, no layout, no groups, no 3D, no History time-lapse. Those are
  workbench features and they stay on the workbench.
