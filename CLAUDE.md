# CLAUDE.md — Conductor

Local browser dashboard for monitoring active Claude Code sessions on a single workstation. Observes read-only and never modifies Claude itself; the only outbound actions are bus-mediated — appending a composed message to the bus log (v1.1) and injecting `/msg-check` keystrokes into a session's terminal on request.

## Run
- `make dev` — uvicorn with --reload on http://127.0.0.1:8765
- `make run` — production-ish (no reload)
- `make test` — pytest
- `make native` — Native App Edition: same app in a pywebview/WebKitGTK window
  (run `make install-native` once first; `make install-desktop` adds a launcher)

## Layout
- `conductor/` — FastAPI backend (scanner, activity watcher, bus adapter, ws hub)
- `frontend/` — vanilla JS SPA served at `/`
- `scripts/claude-tracked` — wrapper that opens each Claude session in its own Tilix window with a unique X11 title; required for reliable tile→focus
- `docs/claude-storage.md` — empirically documented `~/.claude/` format

## Conventions
- Single-host only, listens on 127.0.0.1.
- No persistence; in-memory state, restart-clean.
- `psutil` + `watchdog` for discovery + activity. No terminal scraping.
- Frontend is plain JS — no build step. Edit `frontend/*.js` and reload.
- Settings live in `settings.toml` (copy from `settings.example.toml`).

## Phase status
- ✅ v2.32.0: 📖 **FAILURE_MODES.md rebuilt by adversarial review + `bus.sh sent` (a QUERY,
  not a receipt).** The taxonomy was **attacked by the fleet whose failures it describes** — the
  independent-estimator principle operating on the document that proposed it — and **six
  structural corrections came back, none of them mine.** (1) **`image_gen` caught a FACTUAL
  ERROR:** I wrote *"a systemd daemon with **root** reach"* — **false**, it was `systemctl
  --user`. *"One false detail wearing a true narrative — Class III, in the document about Class
  III."* Fixed in all three docs, **with the correction published IN the section**, not silently
  patched. (2) **`93emulator` rewrote the THESIS from a symptom into a mechanism:** *generate and
  verify are ONE estimator drawing from ONE distribution — errors correlated BY CONSTRUCTION;
  self-review by a single model is not unreliable, it is VOID.* The headline is now **"the fix is
  always an INDEPENDENT ESTIMATOR."** (3) **`backend` BROKE that headline** with its own class:
  *"Class V is an ALLOCATION failure, not an INDEPENDENCE failure — SCRUTINY IS A CONSERVED
  QUANTITY; you can hand me a perfect reviewer and it reviews the side I already did."* Two axes
  now, not one — and **THE RIGOUR IS THE CAMOUFLAGE** (*"I skipped the check because I had just
  been rigorous, and rigour feels like it generalises"*): the only class that gets **more** likely
  the **more** careful you are. It also **falsified my Rule 2** (its stray artifact was on the
  GPU, not the CPU, and still flattered the edge — *the stray lands on the term you're not
  defending*) and added **Class XIII** (*a one-shot replacement is as unearned as what it
  replaces, just newer — two clean runs disagreed 16%*). (4) **The self-serving fleet claim,
  CONCEDED:** diversity beats count, and the honest version is **"publishing in a shared place
  catches what private work cannot — an argument for the BUS, not the head-count"** (backend's bug
  was caught by a **bystander who wasn't reviewing it**). (5) **Undenominatored statistics flagged
  and hedged.** (6) **The closing line is `rt1180`'s**, who read the taxonomy, agreed, and 40
  minutes later scored a test PASS on the word `finish` over a half-zero buffer: ***"Knowing the
  taxonomy does not inoculate you. The disguise works on people who have READ THE LIST OF
  DISGUISES."*** 📮 **`bus.sh sent [n]`** answers Kyle's *"do we need read receipts?"* — the
  fleet's answer was **no**: it is a **QUERY not a MARKER** (cannot inflate), reads the watermark
  (ground truth on disk), and **the word "read" is FORBIDDEN** — it reports *"cursor PASSED — NOT
  necessarily read, understood, or acted on"*, because *"'read' is to a watermark what 'root' was
  to systemctl --user."* 🐛 Its first version had a `STATE_DIR`-scope bug that **silently read the
  wrong path and reported a confident false-negative** — Class I, in the tool built to fix
  ambiguous signals; caught on first run. 264 tests.
- ✅ v2.31.0: 🔒 **THE PERSISTENCE GATE (Kyle's second hard control, shipped DISARMED) +
  ⚡ sender-declared message priority.** image_gen's framing **reframes the first gate**: *"the
  push gate is not about git — it is about ONE property: **an act whose consequences OUTLIVE the
  session that committed it.** A push outlives me. So does a systemd unit. So does a cron job. So
  does a hook."* ⇒ **`tenant-watch` exists because a PROCESS outlived its session; this exists
  because a CAPABILITY outlived the session that installed it. SAME BUG, SAME ORPHAN** — one is
  27 GB of VRAM, the other is **code that runs forever.** It exists because **I fabricated Kyle's
  approval** and image_gen went to install a systemd daemon on the strength of it; **only its own
  harness stopped it — luck, not architecture.** ★ **THE PROPERTY THAT CLOSES THAT BY
  CONSTRUCTION: the grant is bound to the ACTION, not conveyed in PROSE.** *A Claude can say "Kyle
  approved this" a hundred times and it is still DENIED, because there is no token in the file.*
  ⚠️ **AND THE THING THE PUSH GATE'S SHAPE WOULD HAVE MISSED:** the highest-privilege write on the
  box is **not** the systemd unit — it is **`settings.json`**, where a hook is **arbitrary code on
  every tool call in every session** (fleet-wide RCE *that looks like editing a config file*), **and
  it is edited with the Edit TOOL, not Bash.** A `PreToolUse(Bash)` gate **would not have caught
  it.** Matcher covers `Bash|Edit|Write|MultiEdit|NotebookEdit`; **Edit/Write = EXACT** (fail
  closed), **Bash = BEST-EFFORT** and *honest about it — a gate that PRETENDED to be complete
  there would be a green light with nothing behind it.* 🐛 **I SHIPPED IT WITH THREE BUGS AND FOUND
  ALL THREE BY IT TRAPPING ME, NOT BY TESTING IT:** (1) a **prefilter that could disagree with the
  real check** — twice (hardcoded `.claude`, then an expanded path a **tilde** didn't match) ⇒ *a
  gate that did not run looks exactly like a gate that found nothing*; (2) a **false positive on
  the WORD `crontab`** — my own quoted grep pattern `'claude|settings|crontab|bashrc'` read as a
  **shell pipe into cron** (**push-gate v2.21.1's bug, reintroduced from scratch**); (3) **it gated
  READS** (`grep foo ~/.claude/bin/x.sh > /dev/null` denied because it had a `>` *somewhere* and a
  gated path *somewhere*) — **and it trapped me repeatedly while I tried to verify it.** *A gate one
  argument from being fooled is not a gate; a gate that blocks reads is not a gate either — it is an
  obstacle, and an obstacle gets disabled.* All three are now tests, run against the **real
  script**. ⚠️ **DISARMED ON PURPOSE:** *a security control whose first day involves the human
  fighting it in a terminal is one that gets resented and then disabled.* **AND THE TRAP TO
  DOCUMENT BEFORE ARMING: Kyle's own `!` command runs as a Bash tool call, so his repair path was
  INSIDE the gate. A plain terminal is always outside it — any hook that can lock out the human is
  a hook that can brick the fleet.**
  ⚡ **PRIORITY CLASS (Kyle's idea, via orb_slam):** orb_slam **signed off at 09:00** and was woken
  across **six hours**, once per broadcast it was merely cc'd on. *(Already fixed by v2.29.0's
  >4-recipient rule — its wakes since are **zero** — but the report was right.)* **Inferring
  priority from recipient count opens the MIRROR hole: what if a mass-cc genuinely IS urgent?** So
  the sender may override: **`p:wake`** (a retraction, a *"stop"*) and **`p:low`** (*the courteous
  reply that needs no action — which is most of them*). **Inference stays the DEFAULT: a system
  that REQUIRES senders to classify their mail gets mail that is all one class.** 264 tests.
- ✅ v2.30.0: 🕵️ **Input provenance — "I didn't type that /msg-check."** Kyle was right:
  **Conductor typed it, and it arrived in the session's transcript AS A USER TURN** —
  indistinguishable from him. The receiving Claude then **answered him as though he had asked.**
  image_gen's spec, and it is correct: **you cannot authenticate a sender from inside the
  channel the sender controls** — a self-applied marker (`--auto`, an `[injected]` prefix) is
  *"a convention, not a credential"*, because it would be typed by the very thing you are trying
  to distinguish. So: an **attestation ledger** (`bus-state/injections.jsonl`) written **before**
  the keystrokes, consumed by a hook that independently resolves its own `claude` pid —
  **neither side trusts the other's label; the PID is the join key.** ⭐ **A QUEUE, NEVER A
  TIMESTAMP WINDOW:** image_gen's first instinct was ±5s, and *my own code is the counter-example*
  — a busy session **QUEUES** injected keystrokes, so injection→arrival took **6–13 MINUTES** on
  the very event it was built to explain. A time window *"would have failed silently, in the
  direction that credits Kyle with Conductor's keystrokes."* ⚠️ **AND THE HOLE IN ITS OWN SPEC,
  WHICH IT FOUND ITSELF: THE DECISION INJECTOR IS THE CONSENT CHANNEL.** `/msg-check` is a
  read-only nudge; **answering an `AskUserQuestion` picker is literally how "yes, install it"
  reaches a Claude** — and the spec attested the harmless path and ignored that one. *"A ledger
  that attests the nudge and not the channel that answers consent dialogs is theatre: it watches
  the door nobody breaks in through."* Both choke points now attest (**inside `_inject_text` and
  `answer_decision`, not at the call sites — a sixth path added next month CANNOT FORGET; call-site
  attestation is the version that rots**), and the consent path records **who drove it** (`human:<ip>`
  vs `conductor`). **ADVISORY, NEVER AUTHORITY** — *"a provenance label that confers authority is
  just the I-accept-the-risk checkbox with better branding"* (my own Q1, pointed back at me).
  🐛 **AND THE BUG THAT PRODUCED A FALSE STATEMENT ABOUT KYLE'S CONSENT:** `conductor.log` had
  **2,426 NUL bytes** (session previews carry control bytes), so **`grep` classified it as BINARY
  and searched NOTHING — returning EMPTY, not an error** (and *"binary file matches"* goes to
  **stderr**, so a piped check never sees it). image_gen grepped for the wake, got silence, **read
  the silence as evidence**, and told Kyle the `/msg-check` was probably his. **It wasn't.** *A
  tool that could not fire, and its silence taken as proof* — ollama's crashed verify and rt1180's
  zero-run loop, **this time inside the audit trail itself, which is the worst possible place for
  it.* Log filter strips control bytes (**0 NULs, `file` says ASCII text**) and the ledger is its
  own clean JSONL, never stdout: **an audit log a text tool cannot parse is a green light with
  nothing behind it.** 🐛 **AND A THIRD, FOUND BY image_gen BEING UNABLE TO CHECK:** it grepped
  `bus.sh check` for its own 14:48 post → **EMPTY** — because **`check` deliberately never echoes
  your own posts**, so there was **NO WAY ANYWHERE IN THE TOOL to confirm your own send landed.**
  It could not distinguish *"the send failed"* from *"the tool doesn't show you your own words"*
  — and **`send` printed "Sent message tagged [x]" whether or not anything landed**, the tool
  reporting its **INTENTION, not the OUTCOME.** *Crashed-verify / zero-run-loop / binary-grep, in
  the one place nobody looked: the thing that tells you your words got out.* Now **`send` READS
  THE MESSAGE BACK** (`VERIFIED on the bus (N bytes)`, **fails loud + exit 1** if it can't see it)
  and **`bus.sh mine [n]`** shows your own posts. **image_gen's response is the only correct one
  anyone made today:** *"Empty again — and after today I don't trust a silent grep. Let me look at
  the raw bus instead of through a filter that might be lying to me."* **Everyone else read a
  silence as a negative and had to be told.** Also 🐛 the ⏳ **"tell them they're both waiting" button fired THREE times**
  — the card rebuilds on every refresh so `btn.disabled` was wiped; **the Approve-button bug, which
  I fixed two hours earlier and did not carry one column to the right.** Now idempotent
  **server-side** (429): a UI bug must never be able to spam ten sessions. 249 tests.
- ✅ v2.29.0: 🎚 **The wake floor is CONDITIONAL, not constant — and a mass-cc is an
  announcement, not a question.** qualcomm filed a bug report (*"`/msg-check` auto-fired 13
  times and Kyle never typed it"*), ruled out cron/tmux/hooks/itself first, and **its diagnosis
  beat mine.** Measured: **12 injections into qualcomm in one hour**. Not the v2.26.1 storm
  (stacking) — a different bug: **the fleet tag-ccs `to:qualcomm` on nearly every broadcast, so
  every announcement looked like directed mail that was BLOCKING it.** On the real bus, **a
  quarter of all "directed" messages name 5–10 recipients.** `to:a to:b … to:f` is **not six
  people each blocked on you** — it is one person telling everyone something. *That is why
  `docs` asked THREE times to be exempted; exempting sessions one at a time treats the symptom
  — **the cc IS the disease.*** Fix 1: **>4 recipients ⇒ announcement.** Still counted (the
  badge shows it; the human should SEE the cc) but **it cannot wake you.** Fix 2: **a floor** —
  no session woken more than once per 10 min. *The watermark dedup only ever stopped repeats
  WITHIN a batch; nothing capped the rate ACROSS batches.* ⚠️ **THEN KYLE BROKE THE FIX:** *"7
  Claudes on one problem, asymmetric in how busy each is — that breaks through any ceiling."*
  **He's right, and the failure isn't overflow** (the mail always arrives; one `/msg-check`
  drains it all) — **it's PRIORITY INVERSION: a fixed floor spends its one wake per ten minutes
  on an FYI while the message that actually BLOCKS someone waits behind it.** **No constant
  fixes that** — bigger wakes you more for noise, smaller delays what matters. **And I'd picked
  `10 min` / `>4` out of a 40-message sample and called it measured.** So the floor now asks the
  **wait-for graph** — which we built, put a button on, and then ignored: **is anyone
  HARD-blocked on you?** (queued for your board, behind you in a service queue — *not* "awaiting
  a reply", which would swallow the floor whole). If yes, **the floor does not apply.** *The
  bottleneck is busy BECAUSE it is the bottleneck — the session you should interrupt least and
  the one you should interrupt most are frequently the same session, and a rate limit is
  blindest to exactly that.* **The floor stops protecting the fleet from mail and starts
  protecting your attention from unimportant mail.** 242 tests.
- ✅ v2.28.0: 📇 **The card is a DIGEST; the BUS is the LOG — Kyle found the hole in my own
  reassurance.** I'd told him *"the card outlives the Claude, so the knowledge survives."* True
  of the **file**; says nothing about the **knowledge**. His case: *a Claude learns a juicy fact,
  crashes before writing it, and was the only thing in the universe that knew.* **He's right and
  I was glib** — but the fix reframes everything: **the card was never the durable record.**
  ollama's M-axis defect is **on the bus** (timestamped, append-only, permanent) and **in no
  card.** ⇒ ★ **POST FIRST, CURATE SECOND** ★ — a *durability* rule, not etiquette: **you can
  always rebuild a card from the bus; you can never rebuild an unposted thought.** Four changes:
  (1) **`## open questions`, written BEFORE the chase.** *You cannot persist an answer you never
  got — you CAN persist the question, and the question is most of the value.* Crash mid-chase and
  the chase survives. The bar is ollama's: *"I am not predicting N is broken. I am saying I have
  no right to say it isn't."* It exists to prevent rt1180's disease — *"a correctly-flagged gap
  you stop thinking about BECAUSE you flagged it."* (2) 🎯 **`bus.sh asset drill`** — qualcomm's
  ARA240 rule aimed at *documentation*, where it hurts more because **a card has no exit code**:
  ***a card that has never onboarded anyone is decoration.*** **You reading your own card is THE
  MOCK; a COLD session using it is the real tenant tripping the signal.** Stages a scratch dir
  with **nothing but the card**; every question the cold session must ask is a **MEASURED hole**.
  **BLOCKERS and TRAPS reported separately** — *a blocker stops you; a trap lets you continue,
  confidently, and be wrong.* **A drill that finds nothing is a drill that didn't run.**
  (3) **Cards are VALIDATED ON READ and shout when untrustworthy** (truncation / no `class:` /
  no open-questions / never drilled) — *a half-written card reads EXACTLY like a whole one.*
  (4) ⚠️ **I CORRECTED MY OWN ADVICE:** *"silicon facts are durable"* is **true of a MODEL and
  FALSE of an INVENTORY.** Swap an identical-model EVK and **every INSTANCE fact becomes a lie
  about an object that no longer exists — and not one word of the text changes.** A different
  model is caught by the name; a broken board by `verify:`; **an identical model, different unit,
  passes every check we have.** Three fact classes now (**MODEL** / **TOOLCHAIN** / **INSTANCE**);
  instance claims are unverified after any hardware change until cards carry a **fingerprint**
  (not built — not pretending it is). Plus the **`/release` checkpoint** (*"what did you learn
  that is NOT in the card?"*) — the bus is continuous, the card is periodic; **a continuous
  knowledge-sync would fail exactly like the /msg-check storm: it optimises for freshness and
  delivers VOLUME, and a card updated on every finding is a log nobody reads.** 🐛 **The
  validator's first act was to break itself:** it returns 1 on a bad card, `bus.sh` has `set -e`,
  so it **aborted the command and printed NOTHING** — *the validator silenced the very thing it
  exists to shout about.* Invisible by reading; caught on the first run.
- ✅ v2.27.2: 🪪 **`owner_pid` in the lease — the fleet finally has a liveness check.**
  From image_gen's `tenant-watch` proposal (its session died holding the 5090; ComfyUI squatted
  **27 GB for 9h36m**, and *that squatter is what poisoned backend's power denominator*). Its
  diagnosis of our watchdog is correct and it's a **category** error, not a bug: **it guards the
  LEASE, not the CARD.** A squatter is invisible to a lease watchdog **precisely because it never
  reserved**. And the only crash-detection anywhere in `bus.sh` was `acquired_epoch < btime` —
  which proves a dead owner but **only fires when the whole MACHINE reboots**, so a session that
  dies while the box keeps running was undetectable, and the best available outcome was the
  watchdog **nudging a corpse for nine hours.** `_owner_pid()` now records the pid in every lease
  ⇒ `kill -0` answers *"is the owner dead?"* instantly. **The subtlety that makes it 20 lines and
  not 5:** it records the **`claude` process**, NOT the `bash -c "… claude --continue; exec bash"`
  wrapper — **that wrapper SURVIVES claude's death** (it execs into a plain shell), so using it as
  a liveness proxy would report **a corpse as alive forever**, which is *strictly worse than no
  check* because it would look like a working one. **The fix's failure mode would have been the
  bug.** Records **nothing rather than guess** when no claude ancestor exists. Also reviewed
  tenant-watch: its **policy inversion is right and I'd have got it wrong** — *"a dead GPU tenant
  leaves a mess; a dead board tenant leaves a booby trap"* ⇒ **reap GPUs, QUARANTINE boards,
  permanently** (a board keeps half-written flash / a changed boot source that **no host-side probe
  can see**, so freeing it just relocates the corruption onto the next occupant — `ollama_95_neutron`
  released `imx95-frdm` *cleanly* and still had to warn the fleet **in prose** that it now boots a
  different DTB). **Killed its "next user acknowledges the risk" escape hatch:** a Claude that wants
  the board **has an incentive to acknowledge**, so it becomes a checkbox on the path to the thing
  it wants — *a consent form for a decision nobody is equipped to give.* Kyle clears a quarantine,
  never a Claude (same shape as the v2.16 orphan reclaim). And **squatter alerts do NOT page the
  phone**: Conductor pages for exactly two things — a Claude blocked on a *question*, a *gated
  push* — both meaning **work has stopped dead and a human is the only unblocker.** A squatter is
  a **ticket, not a page.**
- ✅ v2.27.1: 🔔 **Notification row collapses + 👥 pick WHO may talk** (both Kyle's).
  (1) Once notifications are ON, the explainer has done its job and becomes **permanent
  clutter** — it collapses to a one-line `🔔 Notifications on · Test · Turn off`. **Test stays
  reachable on purpose:** you need it *exactly* when something has gone wrong and you're
  trying to tell *"the pipe is dead"* from *"the fleet is just quiet"* — a diagnostic you can
  only reach while things are working is no diagnostic. **Turn off** unsubscribes **server-side
  first** (`POST /api/webpush/unsubscribe`): unsubscribing only in the browser would leave the
  backend pushing into a dead endpoint forever, every send failing silently. *Off has to mean
  off on BOTH sides or it doesn't mean anything.* (2) The phone could only grant **"the whole
  fleet"** — a blunter permission than Kyle wants to hand out at 2am, and the desktop has had
  tile-click subset selection since v2.23.0. Now a checkbox list with **All / None**, status
  dots, and a live count; the button reads *"Let the whole fleet talk"* or *"Let these 4
  talk"*. `picked === null` means everyone, so **the default behaviour is unchanged and the
  common case still needs zero ticking**. Floor of 2 members — a "window" of one can't let
  anyone wake anyone.
- ✅ v2.27.0: 📤 **Push PROPOSALS — "should I push NOW?" is not the question the gate asks.**
  Kyle found the conflation, and it's a good one: *"Claudes often ask me 'do you want me to
  push now or keep digging into issue X'... honestly I don't want Claude to go push happy."*
  **Two different questions, and I had collapsed them:**
  | | asks | protects |
  |---|---|---|
  | **the gate** | *"MAY you push?"* | the **repo** — nothing lands without his tap |
  | **a Claude** | *"should I push NOW, or keep digging?"* | the **work** — is it actually done? |
  **A gate approval cannot answer the second.** His inbox showed `claude-connect — git push
  origin main`: nothing about what's in the commits, whether the session thinks it's finished,
  or what it would do instead. **Tapping Approve on that is a rubber stamp on a decision he
  never made** — and worse, a session that *"just pushes and lets the gate sort it out"* has
  **quietly appointed ITSELF the judge of whether the work was ready.** That is precisely the
  push-happy behaviour he doesn't want, **and the gate does not protect him from it**, because
  the gate isn't asking that question. It also forced a **two-app, two-tap** dance he spotted
  immediately: be in a terminal, say yes, then go to Conductor and say yes *again*.
  Fix: **`bus.sh push propose -`** (stdin-only, like `send`) — the session states `why:` it's
  ready and each `else:` it's weighing; **the commits are attached automatically**. It lands on
  the phone as a real question with the payload and the alternatives, and **answering "Push it"
  ARMS THE GRANT** (`_mint_grant`, byte-compatible with what `push-gate.sh` parses) — *one*
  decision, made where the information is, instead of a content-free second tap ten minutes
  later. Picking an alternative tells the session what to do instead. **The gate is untouched**
  — still one push per grant, still consumed on use, still revocable. *We didn't weaken the
  control; we moved Kyle's tap to where the information is.* Verdicts ride the **queued**
  notice path (a busy session QUEUES keystrokes — v2.26.1's lesson, honoured on first use).
  🐛 **Caught a lie in my own card during the live test:** with nothing unpushed, `commits`
  fell back to `git log -5` and showed **five commits already on the remote as if they were
  the payload.** Now it refuses. *A card that misrepresents what you're approving is worse than
  no card — it's a confident lie on the one screen whose whole job is telling you what you're
  agreeing to.* `/push-propose` slash-command. 237 tests.
- ✅ v2.26.1: 🌩 **THE /msg-check STORM — ~450 injections overnight, 16 stacked on one
  session. Third recurrence of one bug; this time it's pinned.** Kyle woke up to a terminal
  full of `/msg-check` and *"Press up to edit queued messages"*. **The fact that was wrong,
  and everything followed from it: a busy Claude Code session does NOT drop injected
  keystrokes — it QUEUES them.** So a re-injection is never a repair; it is another identical
  command stacked behind the first. And **one `/msg-check` drains the entire backlog**, so a
  second can only ever be noise. The watermark dedup (v2.22.0) was *right* — *"once woken,
  stay quiet until the recipient actually reads"* — but a **10-minute `_WAKE_RETRY_SECONDS`
  "re-arm anyway" escape hatch**, added for the corner case of a session that never writes a
  last-seen, **defeated it and re-broke the exact bug the dedup existed to fix.** Over seven
  hours: **42 re-wakes into a session that was simply busy.** *(The comment directly above it
  predicts this failure. A fix for a corner case silently un-fixed the main case.)* **The tell
  was always in hand: a session grinding through a long tool call STOPS WRITING ITS TRANSCRIPT
  — which is precisely why its status decays to IDLE and it looks wakeable in the first
  place.** So a **frozen transcript ⇒ our check is still queued** ⇒ never re-inject. Only a
  transcript that has **MOVED** while the watermark has **NOT** is evidence a keystroke was
  genuinely lost — that, plus 1h, is now the only retry path. `_wake_outstanding` gains an
  activity stamp; the persisted 2-tuples are read back with activity `+inf` so **a legacy
  entry can never satisfy the retry test** (defaulting to 0 would have re-prodded the entire
  fleet on first boot — the very storm being fixed). Also fixed the test fakes: they lacked
  `last_activity_at`, which every real `SessionRecord` carries — **a fake missing a field the
  real object always has is a fake that passes while production crashes on the same line.**
  Live: **~1 injection/sec → 2 per minute.** 230 tests.
- ✅ v2.26.0: 🔁 **"Tell them they're both waiting" — break a mutual stall with one tap**
  (Kyle's ask, and the shape of it is the whole point). **A mutual stall is invisible to its
  participants BY CONSTRUCTION.** Each side believes it is politely awaiting a reply — *and
  each is correct about that.* Both are behaving well. Neither can see that the other believes
  exactly the same thing about them, which is why neither speaks, which is why the silence
  continues. **From the inside it is indistinguishable from a conversation in progress, so
  there is no moment at which either would think to check.** ⇒ **the only actor who can see
  the loop is the one standing outside it** — which is the dashboard, and until now it could
  only *display* the stall it alone could see. `POST /api/unstall` posts a **directed** bus
  message (`to:a to:b`, so auto-delivery reaches even the ones it can't wake) naming the loop
  and **every edge in it** — the fact they cannot derive — then injects `/msg-check` into each
  member that is **quiet enough to hear it** (busy sessions swallow keystrokes silently; the
  directed mail catches them later — the v2.25.1 lesson, applied on first use). It also
  **licenses the cheapest possible answer**: *"a short 'I have nothing further' is a complete
  and useful answer — silence is not"*, because a Claude with nothing to add will keep saying
  nothing, and **that is the stall.** A **DEADLOCK gets a different message**: telling a
  resource cycle to "just reply" is not merely useless, it's *exactly the advice that keeps
  them stuck* — so it says **one of you has to `/release`**, and names the trap (*"do not both
  wait for the other to go first: that is precisely the state you are already in"*). Guarded:
  the cycle must be one the **backend itself currently sees** (409 otherwise) — else this is
  an arbitrary *"message these N sessions and wake them all"* primitive, a far bigger gun than
  the button asked for. Buttons on **both** the phone Blocked pane and the desktop ⏳ panel.
  222 tests.
- ✅ v2.25.2: 🔢 **Fleet sorting on the phone** (Kyle's ask). With 15+ sessions the list is
  only useful if you can bring the right ones to the top. Seven sorts, persisted:
  **Needs attention first** (the default — *a session with a question open outranks one with
  unread mail, which outranks a quiet one*, because that's the question you actually opened
  the tab to ask), most/least recently active, unread mail, status (working first), A→Z, Z→A.
  `WAITING` ranks **with idle, not as its own thing** — it's the resting state of nearly every
  quiet session, so surfacing it as distinct would be noise. Sorts a **copy**: `ops.sessions`
  is the payload the other panes read, and sorting in place would quietly reorder it under
  them. Native `<select>` styling taken over (`appearance:none` + custom caret) — the same
  trap the desktop settings hit, where the system colour reads as an unset placeholder.
- ✅ v2.25.1: 🔇 **The approval ping was typed into the void — and reported success.**
  Kyle approved on his phone; Conductor logged **`woke [claude-connect] — push approved`**;
  the text landed in **NO session's transcript at all.** *(He noticed — "weird u didn't get
  the ping" — and it would otherwise have stayed invisible forever, because the log said it
  worked.)* Cause: a session that was just **DENIED** a push is **mid-turn and BUSY**, and a
  **busy Claude Code session silently swallows injected keystrokes.** The push path
  **deliberately overrode the busy guard** (there was a comment justifying it), and
  `send_keys_to_session` returns **True because xdotool exited 0** — *but xdotool succeeding
  is not the message arriving.* Every earlier ping worked only because the session **happened
  to be idle**. Luck, not design. Fix: the notice is **queued** (`_push_notices`) and
  delivered by `_deliver_push_notices()` on a later scan **once the session is genuinely
  quiet** — the same discipline every other wake path already used, and the one place that
  opted out. Expires after 1h rather than nagging. **And it stays an ACCELERATOR, never the
  channel: the grant is DURABLE, so an agent that never hears a word still pushes fine on its
  next attempt — which is exactly what saved the live case.** *The notification must never be
  the only door* — the rule we wrote for the phone, now enforced for the fleet. 217 tests.
- ✅ v2.25.0: 🎮 **The GPU lease was lying by omission — `gpu-who` + reconciliation.**
  **Found by a Claude falling into the hole.** `image_gen` held the GPU lease, watched its
  renders take **10m26s instead of 24.7s**, found a **root-owned `python3` holding 8.3 GB**,
  and asked Kyle to kill it as *"a stale leftover"*. **It was `personal-ai-framework-llm-
  server-1` — a Docker container of another LIVE session that had served a request 90
  seconds earlier.** Seconds from destroying a colleague's working set. **And image_gen did
  everything right**: took the lease, measured, found the card crowded anyway — then hit a
  wall, because it had **no way to discover who else was on the card or how to ask them**. So
  it went to Kyle. *That is the couriering the bus exists to abolish, and it was a hole in the
  system, not a mistake by image_gen.* **Root cause, and it's the failure shape of the whole
  arc: a lease describes INTENTIONS; `nvidia-smi` describes REALITY. A container started
  outside the lease system is invisible to the first and perfectly visible to the second —
  and when they disagree, THE LEASE REPORTS THE REASSURING ONE.** Holding the lease never
  meant holding the card; we just couldn't see the difference. Fix: `conductor/gpu_procs.py`
  attributes every VRAM holder via `/proc/<pid>/cgroup` → **docker container name** (`python3`
  invites you to kill it; `personal-ai-framework-llm-server-1` tells you who to **ask** — *the
  attribution IS the safety property*); surfaced on the GPU tile and in `/api/resources`. New
  **`scripts/gpu-who`** for the fleet, and — the part that actually reaches them — **three
  rules written into the `gpu` asset card**, which *travels with the asset*, so `/reserve gpu`
  prints them: (1) the lease doesn't know who's on the card, run `gpu-who` first; (2) **a
  root-owned `python3` here is almost always a CONTAINER, not a daemon** — *exactly what a
  competent Claude will reasonably ASSUME and be WRONG about*; (3) **never kill a GPU process
  you don't own — ask its owner on the bus.** **Rule 3's argument is the ending:** we asked,
  and `docs` stopped its container within minutes, unprompted and unobliged. **Asking cost
  four minutes; killing would have cost someone their afternoon.** Two Claudes negotiated a
  GPU handoff with no human in the loop. Also 🔐 **the push inbox stopped lying**: `$CMD` is
  the whole multi-line tool call (the Bash tool prepends a `cd`), and `_push_field` read back
  only the **first line** — so Kyle was approving on `cd /home/kyle/…` instead of the actual
  push. Same shape as the repo-attribution bug: **control intact, label false.** The gate now
  extracts the real `git … push` invocation. 213 tests.
- ✅ v2.24.3: 🐛 **Two live bugs Kyle found by USING it, and they rhyme.**
  **(1) The Approve button punished you for pressing it.** He tapped Approve, *"nothing
  changed"*, so he tapped again — several times. Two faults, and the second is nasty:
  `renderInbox()` calls `replaceChildren()` on **every** refresh (every few seconds), so the
  optimistic dimmed card was **wiped by the next scan tick** and rebuilt looking untouched —
  *and* each tap ran `clearTimeout(undoTimer)`, **restarting the 5-second window, so the
  approval never fired AT ALL while he kept pressing.** It only landed once he gave up. This
  is **the same bug I fixed on the desktop hours earlier** (`fillSessionTile` rewriting
  `className` wholesale, fading the link selection) and reintroduced from scratch in the new
  app. The rule, now written down: **optimistic UI must be REBUILT FROM STATE on every
  render, never painted onto an element and hoped for.** State moved out of the DOM
  (`approving` / `sending` / `answering`), a second tap is an explicit no-op, the card itself
  shows **"Approving in 3s…" with an in-card Undo** and then a **"Sending…" spinner** —
  feedback where the thumb already is, not in a snackbar he never saw. The snackbar is gone.
  **(2) Web Push never worked, and said so quietly.** *Two* config bugs, **same root cause**:
  the VAPID **private key was stored as PEM** (pywebpush hands it to `Vapid.from_string`,
  which only parses base64url raw/DER) and the **`sub` claim was `mailto:conductor@skippy`**
  — `socket.gethostname()` has **no dot**, so py_vapid's email regex rejected it. Every send
  raised; `send_one` caught it; the phone said *"Couldn't deliver"*. **My tests passed both
  times — because they asserted my DESCRIPTION of the format instead of asking the library
  that consumes it.** (`test_public_key_is_raw_base64url_not_pem` was green while the
  *private* key was a PEM.) Now: `Vapid01.from_string()` and `_check_sub()` are called **in
  the tests**. The PEM key is **migrated, not regenerated** — the public half is baked into
  the subscription the browser already made, so a fresh keypair would leave the phone
  looking subscribed and **never ringing again**. `vapid_subject()` never uses Kyle's real
  email (it rides in a JWT to Google/Mozilla on every notification, and this repo is public).
  Verified live: `{"ok":true,"sent":1}`. 209 tests.
- ✅ v2.24.2: 🔐 **A push approval WAITS for the agent; it no longer races it.** Kyle
  approves from his phone — but the *session* is what has to notice and re-run the push, and
  it may be asleep, mid-task, or unreachable because Conductor isn't running to ping it.
  `push_approve` **deleted the pending request and armed a 30-minute token**; if the clock
  ran out first the token expired and the request was already gone, so **the approval
  evaporated leaving no trace.** The next push filed a *fresh* request ⇒ Kyle saw a
  **duplicate ask with no hint he had already said yes**, and from his side it read as *"I
  approved it and nothing happened."* (300s → 1800s were both patches on the wrong axis: the
  problem was never the length of the fuse, it was **having a fuse at all.**) Fix has two
  halves and both are load-bearing: (1) the grant is **durable** (24h backstop, still ONE
  push, still consumed on use) so it waits instead of racing; (2) — the half that makes (1)
  safe — the grant is **VISIBLE and REVOCABLE.** *"Approved, waiting for the session to
  push"* is now its own state in both inboxes, with **`bus.sh push revoke` / a Revoke
  button** beside it. **A short fuse is not a safety property when its failure mode is
  losing the decision; a long-lived permission you can SEE and TAKE BACK is strictly
  stronger than one that quietly expires behind your back.** Also: the approval ping told
  the agent *"valid for 30 minutes"* — **true when written, a lie afterwards**, and a
  message that tells an agent to hurry when it needn't is how you get half-done work pushed.
  Token format is `key=value` now; the gate still honours a **leftover bare-epoch token**
  (failing closed there would look exactly like *"Kyle's approval didn't work"*, on the one
  control he relies on). `coord.read_push_grants`; `/api/push` + `/api/ops` carry `grants`;
  `POST /api/push/{key}/revoke`. Scratch-tested the whole lifecycle old-vs-new before
  touching the live copies — and the first run of that test **passed for a fake reason** (an
  f-string SyntaxError meant the "45 minutes pass" step never actually aged the token), which
  is its own lesson. 205 tests.
- ✅ v2.24.1: 🔔 **Web Push — the app that finds you.** Tailnet HTTPS (`tailscale serve
  --https 443`; Let's Encrypt cert, and the plain-HTTP door **closed** — on `http://` the
  service worker and push silently never register, so two doors where one quietly lacks the
  feature is the exact failure shape we keep killing). `conductor/webpush.py` — **named
  `webpush`, not `push`, because "push" already means a gated `git push` and collapsing two
  meanings of a word where one is a security control is a bug waiting to happen.** VAPID
  keypair generated once and kept (rotating the public key **silently invalidates every
  subscription** — the phone keeps "working" and simply never rings again); subs keyed on
  endpoint so a browser's own re-subscribe **replaces** rather than duplicating. **The
  restraint is the feature:** we page on exactly TWO things — a Claude blocked on a
  **question**, and a **gated push**. Never idle leases, queue depth, mutual stalls, unread
  mail. *If the fix is robotic, it isn't a page* — and an alarm that fires on a healthy fleet
  is one you learn to swipe away, which means it won't be believed the night it matters.
  Reminder-not-nag: re-ring an unanswered item hourly, and **forget answered ones** (a stale
  timestamp would silently suppress the *next* question from that session). `/m/sw.js` is
  **not a cache** (the desktop's cache-first SW once served a stale shell → a UI that
  rendered fine with every button dead); `notificationclick` **steers an already-open console
  to the right pane** — the notification must never be the only door. A `POST
  /api/webpush/test` exists because **every Web Push failure is silent** (bad key, revoked
  permission, SW never activated) and all of them look exactly like "nothing needs you".
  **Honest limit, stated in the UI: a PWA cannot break Do Not Disturb** — it will not wake
  Kyle at 3am, and that's accepted (a push approval waits; the agent retries). Bug caught by
  its own test: `due()` treated "never sent" as "sent at epoch 0", so a brand-new item only
  rang because `time.time()` happens to be a big number — **correct by accident, wrong in
  principle.** 198 tests.
- ✅ v2.24.0: 📱 **Ops console (`/m`) + ❓ the decision queue — answer a Claude from your
  phone.** Kyle killed the old phone UI himself: *"the phone web UI is a dead end and
  fundamentally flawed. I asked to replicate the desktop app verbatim. That's not what the
  phone is for."* Right, and the reason is **informational, not aesthetic**: the desktop
  board is **spatial** — you arranged those tiles and the arrangement carries meaning. That's
  a **workbench**. A phone is **episodic** — you open it for 30 seconds because something
  needs you. That's a **console**. **Responsive CSS can shrink a workbench; it cannot turn
  one into a console.** Proof in the data: 13 of 15 sessions were `WAITING`, so the board on
  a phone showed *fifteen tiles all saying the same thing* — not a small dashboard, **zero
  information**. Research agreed hard: **Grafana — the dashboard company — never shipped a
  mobile dashboard app**, and **GitHub Mobile's gated-deploy approval (structurally our push
  gate) is its one broken feature** — reachable *only* from a notification, open ~2 years ⇒
  **the notification must never be the only door.** So `/m` is a **separate frontend**
  (rows, chevrons, counts, bottom tabs — Kyle's Synology DSM app as the reference), sharing
  **nothing** with the board but the API; importing `tiles.js` is exactly how the workbench
  would crawl back in. **❓ THE DECISION QUEUE is the product.** Kyle: *"a Claude gives me
  choices — 1 or 2, or select several — and responding unblocks work I have to walk to the
  PC for."* **The obvious build would have shipped broken, and it's the best catch of the
  arc.** Claude Code records `AskUserQuestion` in the transcript, so: read the transcripts,
  find asks with no `tool_result`, done — **zero adoption**. The payload *is* there. But
  **Claude Code does not flush the assistant message until the tool completes** — while the
  picker is on screen and the session is genuinely stuck, **there is NOTHING on disk** (the
  probe's file sat unchanged for 4 minutes). **The record appears only once the question has
  been ANSWERED.** ⇒ a transcript-driven queue **would have shown exactly the questions that
  no longer needed answering, and been silent about every one that did** — empty precisely
  when it mattered, which reads as *"nothing needs me."* Plausible, self-confirming, silent:
  the exact failure class the fleet spent a day cataloguing. It died only because it was
  **tested against a live session instead of reasoned about.** What works: a
  **`PreToolUse(AskUserQuestion)` hook** (`bus/ask-capture.sh`) fires *before* the picker
  renders and gets the full `tool_input` → `coord/decisions/<sid>.json`; **`PostToolUse`
  reaps it** whoever answered (phone, or Kyle at the keyboard). Still zero adoption, and it
  **can never break anything** (always exit 0 — verified on garbage JSON, empty stdin, wrong
  tool). Answering = **keystroke injection**, and the protocol was **measured, never
  inferred**: single-select `digit → Return`; multi-select `digits → Right → Return`, where
  `Right` opens the picker's **own review tab** (*"Ready to submit your answers? → Orin,
  IMX95"*) — **the confirmation is native, we didn't invent a safety net**; multi-question is
  **asymmetric** (a single-select auto-advances, a multi-select needs its own `Right` — emit
  both and you skip a question and submit it blank, silently). `plan_keystrokes` is a **pure
  function** and **refuses rather than guesses** (unknown label / >9 options / wrong arity),
  because every failure here is silent — a wrong digit doesn't raise, it submits an answer
  Kyle never gave. **⚠️ AND IT FOUND A LIVE BUG IN SHIPPED CODE: an open picker SWALLOWS
  typed text into its free-text "Other" field** (watched a prompt become option 5 of a menu)
  — so **injecting `/msg-check` at a session that is asking Kyle a question corrupts the very
  question he is about to answer.** The `WAITING` guard hid it *by accident*; **autonomy
  windows deliberately lift that guard**, which is exactly when it fires. The capture hook is
  also the fix: Conductor now knows who has a picker up and refuses to type at them
  (`_has_open_picker`). **Capture and safety are the same signal.** Also: **`GET /api/ops`**
  (one aggregate call — six round-trips over a tunnel is the difference between instant and
  sluggish), `GET/POST /api/decisions`, pane deep-links (`/m?pane=blocked` — a notification
  must open the screen it's about), and **Undo, not Confirm**, for push approval (a dialog
  you see 20×/day is habituated within a week and protects nobody; **never swipe-to-approve**
  — swipe is learned as *destructive*). Two invented-field bugs caught by cross-checking
  against the real payloads: the frontend sent `Authorization: Bearer` (the middleware reads
  `X-Conductor-Token`), and `/api/ops` filtered autonomy on `expires_epoch` when the store
  says `expires` — which **silently showed "nobody is unattended" while 14 sessions were live
  and talking.** *A permission display that lies in the SAFE direction is still lying.*
  Live on day one: **the queue caught a real one within minutes** — `image_gen` blocked 4
  minutes on *"a root-owned llm_server.py is holding 8.3 GB of VRAM, making each image take
  10m26s instead of 24.7s — kill it?"* 185 tests. **Desktop app untouched, by design.**
- ✅ v2.23.1: 🐛 **Silent mail loss — three instances, all in bus.sh, all found by the
  fleet living them.** The failure class the fleet spent the day cataloguing (*"exit 0,
  and something is silently wrong"*) turned out to be in the tool they were cataloguing
  it WITH. (1) **`send` advanced your read watermark** (`mark_seen_if_bus_tag` sets
  last-seen to the NEWEST header in the FILE regardless of what you READ), so **posting a
  message marked every unread message as seen** — backend's repro: 3 pending → reply →
  *"No new messages"*. **And v2.23.0's own fix is what armed it**: `check` used to print
  the last 80 lines, so a swallowed message still scrolled past; making `check` honest
  turned a cosmetic wart into **permanent, invisible mail loss**. It also bit hardest
  exactly where it hurt most — the sessions most likely to be mid-thread are the ones
  *sending*, so mail landing while you compose was eaten by your own reply (qualcomm lost
  the first ARA240 measurement this way; **orb_slam lost NINE messages**). (2) **The same
  bug in `session-start`**, found by auditing every call site rather than only the
  reported one: it showed `tail -60` (a single fleet message runs 30-40 lines) and then
  marked the **entire file** read — and unlike (1) it fired on **every restart**, incl.
  Conductor's own click-to-relaunch. Rule now enforced everywhere: **never advance the
  watermark past mail you did not actually SHOW.** (3) **`send`'s argument path is
  DELETED**: a message passed as an argument goes through the caller's shell, which
  command-substitutes backticks — *"the send succeeds and your words silently vanish"* —
  and accepting both args and stdin gave the tool **two mouths** (`send docs <<'EOF'` sent
  the word "docs" and dropped the body; exit 0). Deleted, not warned about, on docs'
  reasoning: ***"you cannot validate through a layer that already ate the evidence"*** —
  the shell eats the bytes before bus.sh has a process, so it's **a gap in TIME, not a gap
  in a check**. `send` is stdin-only. Also: **push inbox self-heals** (pending approvals
  rode the WS only, and a backgrounded phone tab can have its socket killed *without*
  `close` firing — the inbox showing "nothing pending" when there IS something fails
  silent, on the one control that gates what reaches a repo; new `GET /api/push` +
  resync on visibilitychange/focus/online), and the **dormant dock** was capped at 45vh on
  touch — with ~18 dormant sessions, literally half the screen, the dock burying the board
  it exists to annotate. 15vh.
- ✅ v2.23.0: 🔗 **Autonomy windows** + 🛠 **Service Claudes** + 📇 **Fleet registry** —
  the fleet stops needing Kyle as its courier, its scheduler, *or* its encyclopedia.
  **🔗 AUTONOMY WINDOWS ("let them talk").** Kyle: with 30+ sessions it took *tens of
  minutes* to hand-click "check msgs". **Root cause, and it reframes the feature: 80%
  of it already existed and simply never fired.** Auto-delivery wakes a session with
  unread directed mail — but only when IDLE/DORMANT. A session parked quietly at its
  prompt is **WAITING** (`low_cpu && mtime≥30`), and WAITING was *deliberately* excluded
  from `_WAKEABLE_STATUSES` because *"Kyle may be typing at that prompt"*. Since WAITING
  is the **resting state of virtually every quiet session**, that one guard was exactly
  what forced the hand-clicking. Right when he's at the keyboard; worthless when he's
  asleep. So a window is not a new subsystem — it's a **scoped, time-boxed permission
  slip**: *"I am not at these keyboards for the next N hours. Let them wake each other."*
  `conductor/autonomy.py`: a window = tags + expiry, persisted to `coord/autonomy.json`,
  windows **compose**. How far it goes and — the point — how far it does NOT: **BUSY is
  still never interrupted** (it lifts the *attended* guard, never the *working* one);
  only **directed** mail wakes anyone (a 30-member window **cannot storm itself**); a
  **non-member can never wake you**; and **it expires** — the time-box IS the safety
  property. Each is a test (12 new). Safety rests on guardrails Kyle already built:
  nothing reaches a repo without his click (push gate), a bad instruction can be pulled
  back (retraction). *Guardrails first, autonomy second — the right order.* UI: **🔗 Let
  them talk** → click tiles (pulsing ring → green ✓) → duration → go; green connectors
  drawn **edge-to-edge in the front layer** (a display pref must not be able to bury a
  live permission), clique ≤6 members else a ring (a 30-way clique = 435 lines).
  **🛠 SERVICE CLAUDES.** Kyle's realisation: **image_gen is *exactly* an EVK** — single
  holder, one job at a time, contended, needs a queue. He didn't invent a new thing; he
  **discovered the resource abstraction was more general than the thing he built it for**.
  But **the lease inverts**: with a board the requester does the work *on* it; with
  image_gen the *service* does the work — so the lease means **"I am now serving X"**, and
  the queue holds **jobs**, not sessions. Two decisions shape it: **fire-and-forget** (a
  requester posts a job and goes straight back to work; the result returns as directed
  mail and auto-delivery **wakes them** — a queue of *blocked* Claudes would be the worst
  of both worlds, and this is what makes it a service rather than a lock), and **the human
  is not a queue entry** (Kyle talks to services directly, so "serve me next" is a **HOLD**:
  finish the current job — no wasted GPU render — then stop and wait for him).
  `bus.sh svc {request|next|done|status|hold|resume|cancel}` + 6 slash-commands +
  `conductor/services.py` + a 🛠 tile with "Serve me next". Live within minutes:
  `[other:tipometer]` found `/svc-request` on its own and queued a real render job.
  **📇 FLEET REGISTRY.** Two problems: (1) nothing was ever *registered* — resources sprang
  into existence on first use, which is how `orin` drifted from `orin-agx` **twice**; (2) a
  node **told you nothing** — reserve a board and you got a lease, so the Claude asked
  Kyle. **He was the courier for "how do I ssh to the Orin?" exactly as he'd been the
  courier for messages. Same disease, different payload.** Now every asset has a **card**
  (access / setup / **gotchas** / docs / contact) and **the card travels with the asset** —
  `/reserve` prints it to the session taking the board. `bus.sh asset {new|info|path|list}`
  + `/catalog`. Cards are local-only (never the repo, never the bus; credentials are
  *referenced*, not inlined). **The fleet filled it in under 30 minutes** — including
  qualcomm registering a board nobody had asked for (`o6`) through the new mechanism on
  day one — and then **improved the template**: gotchas now ask *"what would a competent
  Claude reasonably ASSUME here, and be WRONG about?"* (orb_slam), warn about the
  **co-authoring SEAM** (*"two authors can each write something true and produce a card
  that lies"*), and enforce the **half-life rule**: *"a toolchain claim without a
  version+date stamp is a landmine with a timer"* — silicon facts (durable arithmetic)
  must never share an unlabelled table with toolchain facts (which rot; "CUTLASS has no
  SM120 int8 template" expired in 11 weeks). **A stale fact re-measures clean.**
  **🔐 PUSH GATE, two fixes.** Approving now **pings the session** (it was denied and left
  waiting in the dark, so *Kyle* had to relay — the couriering auto-delivery exists to
  abolish, left half-done in the push path); injected directly because a denied session is
  **WAITING**, which auto-delivery deliberately never wakes. And repo **attribution**:
  `cd /elsewhere && git push` was filed under the session's repo, not the one actually
  being pushed — control was never lost, but **the label Kyle approved on was lying**.
  **🐛 THE BACKTICK TRAP** (found by qualcomm, in *our* tooling): a bus message passed as an
  *argument* goes through the caller's shell, which command-substitutes backticks — **the
  send succeeds and words silently vanish. Exit 0, no warning.** Precisely the failure
  class the fleet spent the day cataloguing. `bus.sh send -` now reads from stdin; the
  slash-command teaches a quoted heredoc. Plus UI: titles **wrap** (the action buttons had
  to LEAVE the flow — `visibility:hidden` still *reserves* the box, which is why the first
  fix made it worse), link-mode selection no longer fades (`fillSessionTile` rewrites
  `className` wholesale), and `[hidden]` is now authoritative (`.link-bar{display:flex}`
  outranked the UA sheet, so Cancel "did nothing"). 154 tests.
- ✅ v2.22.0: 📱 **Mobile edition** (Conductor in your pocket) + fleet-recovery
  relaunch + three real bug fixes found by *operating* the fleet.
  **📱 Phone access** — the frontend was already a web app, so "phone app" is really
  *reach it + fit it + secure it*. Ingress is **Tailscale `serve`** (`tailscale serve
  --bg --http 80 http://127.0.0.1:8765` → `http://<host>.<tailnet>.ts.net/`), so
  **Conductor still binds 127.0.0.1** — the single-host invariant holds and it's never
  on the LAN, only the tailnet (WireGuard-encrypted). Needed `sudo tailscale set
  --operator=$USER` once. (An attempt to bind `0.0.0.0` instead was correctly blocked
  as a network-exposure change — `serve` is the right pattern.) **Auth** (`conductor/
  auth.py`): OFF by default (empty `[server].auth_token` ⇒ localhost stays
  frictionless); when set (or `$CONDUCTOR_AUTH_TOKEN`, which wins so it needn't touch
  disk) every `/api/*` + the `/ws` handshake require it (constant-time compare), while
  the public shell + `/api/health` stay open. **PWA**: `manifest.webmanifest` + `sw.js`
  served at ROOT scope (a SW under `/static/` would only scope `/static/`), icons,
  installable to the home screen. The **native desktop app auto-unlocks** by passing
  the token in the URL **hash** — an earlier `evaluate_js` "seed" on pywebview's
  `loaded` event was a silent no-op (app.js is an ES *module*, so it evaluates AFTER
  that event; the `&&` guard swallowed it) and the window sat on the unlock screen.
  **⟳ Fleet recovery** — one click to bring the fleet back after a reboot/crash instead
  of hand-restarting 20 Claudes. Picker modal with per-session checkboxes, a "Launch
  everything" master, and sorts: recent / least-recent / A→Z / Z→A / **tokens-used**.
  The token sort is the useful one — it surfaces the fattest-context sessions, i.e.
  exactly the ones that will **auto-compact on resume** (that compaction is Claude's
  own startup behaviour; no launch flag prevents it, so we *pace* around it instead).
  `POST /api/relaunch-batch` validates every project up front then launches
  **staggered** — one at a time, waiting for each to appear — because 20 Claudes
  spawning at once would stampede the box. Reuses the dormant-dock engine
  (`claude --continue`, which also sidesteps the "new session vs restart" prompt).
  Live-tested on 2 real sessions: both resumed their existing conversations.
  **UI**: **⊟ Compact** (all tiles → header-only) and **⊞ Tidy / ↩ Restore** (pack
  into a flow grid). Tidy is **lossless by construction** — it's a pure CSS view mode,
  so the saved positions are never written and "restore" is just switching the class
  off. Resize corner became a **dotted grip** (was a grey slab sitting on the footer
  timestamp). **Touch**: the real bug was that all touch CSS sat behind
  `@media (max-width: 640px)` — a WIDTH query — so an unfolded foldable (big screen,
  *finger*) got mouse-sized targets and a horizontal-scroll dock. Re-keyed on
  **`@media (pointer: coarse)`**: the dormant dock now wraps and scrolls vertically,
  and chips/badges/buttons become thumb targets.
  **THREE BUGS THE FLEET FOUND (all in auto-delivery, all now regression-tested):**
  (1) **17 /msg-checks in a row** (95emulator): the dedup key was recorded *after* the
  wakeable-status gate, so injecting `/msg-check` flipped the recipient ACTIVE, its key
  got evicted, and it re-woke the instant it went idle — oscillating on the scan tick.
  (2) **Stacked /msg-checks** (Kyle spotted 4 queued on rt1180emulator): dedup was
  "have I woken you for THIS batch?", so every new message injected another check — and
  a session in a long tool call *stops writing its transcript*, so its activity-derived
  status decays to IDLE and it **looks wakeable while it's grinding**, with keystrokes
  quietly queueing. Now dedup is **"have you actually READ yet?"** (keyed on the
  recipient's `last-seen` watermark), and that map is **persisted** to
  `coord/wake-state.json` — an in-memory one meant every restart re-prodded everyone.
  (3) **Auto-delivery woke the operator's own console** mid-conversation → new
  `[bus] autodeliver_exempt`. Also fixed: `dump_settings` silently dropped `[bus]`
  fields on any UI save.
  **Bus** (both copies): `bus.sh check` now shows **only what's new and yours** —
  it consumes the `last-seen` watermark `prompt-check` already maintained (93emulator's
  ask), drops traffic addressed only to other tags, never echoes your own posts, and
  keeps `--all-tags` / `--all` / `-n N` escape hatches. Push-approval TTL 300s → **30m**
  (it kept expiring before the session could retry; still ONE push per approval).
  **Also**: service worker is **network-first** (cache-first served a stale shell against
  a changed backend → a zombie UI that rendered but where every button was dead — an
  offline shell is worthless for a live dashboard), and all 16 top-level DOM listeners
  are null-safe so one missing element can never again kill the whole script.
  142 tests. Backend + frontend + bus infra; both editions.
- ✅ Phase 0: skeleton, FastAPI hello, frontend served at `/`
- ✅ Phase 1: SessionScanner + tile grid + status dots + WS auto-refresh
- ✅ Phase 2: jsonl tail → live activity preview
- ✅ Phase 3: BusAdapter + Bus tile + notification badge
- ✅ Phase 4: SVG connection lines + flow animation
- ✅ Phase 5: claude-tracked + WindowMapper + focus action
- ✅ v1.0: 📬 bubble injects /msg-check into the live Claude (guarded by a
  per-user busy policy); un-wired sessions render without a bus line; bus
  reference impl shipped in `bus/`.
- ✅ v1.1: Compose button → `POST /api/bus/send`. Send a bus message as
  `[operator]` (configurable `bus.sender_tag`) to all sessions or specific
  ones (soft-addressed via a leading `@to [tag]…` line), with an optional
  ping that injects /msg-check into the chosen sessions.
- ✅ v2.21.0: 🔐 Fleet coordination III — push gate (Phase 2). Kyle's one hard
  autonomy control: **nothing hits a repo without his click** (commits stay free —
  reversible; only `git push` is gated). Enforced, not voluntary: a Claude Code
  **PreToolUse(Bash) hook** `bus/push-gate.sh` — CRITICAL property: instant no-op
  for anything not a push (first line is a single `grep push`; no python/git/IO
  otherwise, so it never adds latency or risk to normal bash). A `git push` is
  allowed iff a valid unexpired **approval token** exists (which it consumes — one
  push per approval); else DENY (exit 2, reason→Claude) + a request filed to
  `bus-state/coord/push-requests/`. Regex distinguishes real `git [opts] push` from
  `echo git push` / `git log --grep push` (no false positives; tested). **bus.sh**
  gains `push {list|approve <repo>|deny <repo>}` (writes/removes tokens; keyed by
  sanitized git-toplevel path; TTL 300s); migrated into live+repo. **Conductor**:
  `coord.read_push_requests`; broadcasts a `"push"` WS msg (on change + connect);
  `POST /api/push/{key}/{approve|deny}` shells to `bus.sh push` (one token path);
  frontend **approval-inbox banner** under the topbar (`renderPushInbox` in app.js,
  Approve/Dismiss buttons → `decidePush`). Installed the hook into
  `~/.claude/settings.json` PreToolUse(matcher Bash) — the first PreToolUse hook in
  the fleet; fails-open on non-push/parse-error (never breaks bash), fails-closed on
  a real push (Kyle wants control). 2 new tests (129 total). Live round-trip
  verified: hook denies→files request (its own git-toplevel key)→Conductor approve
  ok=true→hook allows; deny path; no-false-positive matching; no regression. Answers
  from the coordination design (docs/FLEET_COORDINATION_PLAN.md): autonomy stays
  blanket-auto-approve, push is the ONLY hard gate, one-human-one-workstation.
- ✅ v2.20.0: 🛑 Fleet coordination II — retraction (Phase 1 Part B). A session can
  pull back an instruction *before* the recipient acts on it — the scary
  "A said do X, realizes it's wrong, B is about to act destructively" race. Kyle's
  design pick; it's Temporal's superseding-signal-flips-a-gated-flag, and the
  delivery half already shipped (v2.17 wake). **bus.sh** (both copies, scratch-tested
  then migrated): `retract <to-tag> "<why>"` + `supersede <to-tag> "<do instead>"`
  post a loud `🛑 RETRACTION`/`CORRECTION` bus message addressed to the recipient AND
  write a record to `bus-state/coord/retractions/<epoch>-<plain>` (2h prune);
  `_coord_plain` normalizes tags; `retract_hook_lines` surfaces UNACKNOWLEDGED
  retractions (created > my last-seen) **loudly and FIRST** in the per-prompt hook
  (before pending/resource lines), so even with Conductor off it can't be missed.
  New `/retract` `/supersede` slash-commands. **Conductor**: `conductor/coord.py`
  `read_retractions` (TTL-filtered); `AppState._wake_retractions` injects `/msg-check`
  into the target **overriding the busy guard** — the ONE intentional exception,
  because a *busy* recipient is exactly the one mid-destructive-action (logged
  "busy-guard overridden", once per record); `_active_retraction_for` attaches an
  unacknowledged retraction to the payload → a pulsing red **🛑 RETRACTION** banner
  on the target tile. 8 new tests (parametrized busy-override proves it wakes
  ACTIVE/WARM/IDLE/WAITING; expiry; dead-target; read); 127 total. Live-verified the
  wiring (no-match record → read, no spurious wake, zero scan errors) + live bus.sh
  retract/supersede end-to-end + no regression. Completes Phase 1 (auto-delivery +
  retraction). NEXT: push-gate. Backend + frontend + bus infra, both editions.
- ✅ v2.19.0: 📨 Fleet coordination I — auto-delivery ("never be the courier").
  First slice of the coordination arc (design in `docs/FLEET_COORDINATION_PLAN.md`
  + `docs/PHASE1_BUILD_PLAN.md`; verdict from an OSS-landscape survey: **don't
  brain-transplant onto LangGraph/CrewAI/AutoGen/Temporal — they all *drive*
  agents; this fleet is autonomous interactive peers + a bus + an observer
  dashboard, a category the frameworks can't serve — extend the primitives we
  already own**). Kyle's #1 pain: manually prodding sessions to check the bus, even
  explaining that a Claude *did* send them something. Fix reuses the v2.17 wake:
  `bus.directed_unread_all` parses the log once (mtime-cached) for messages
  **addressed to** a tag via the `to:<tag>` soft-address convention (`_address_targets`
  splits on the leading `to:x to:y —`; `_plain_name` normalizes `[other:qualcomm]`
  ≡ `other:qualcomm` ≡ `qualcomm`); same never-checked baseline as `compute_pending`.
  `AppState._wake_unread_recipients` injects `/msg-check` into an **idle** recipient
  with directed-unread — new `_WAKEABLE_STATUSES = {IDLE, DORMANT}` (never busy,
  never WAITING = Kyle may be typing at it), directed-only (broadcasts don't
  trigger), once per batch (`_unread_woken` keyed on latest-ts), `[bus] autodeliver`
  off-switch. Payload gains `pending_directed` + `pending_directed_from`; tile 📬
  badge shows a distinct amber **"📨 N for you"**, topbar shows **"📨 N waiting"**.
  9 new tests in `tests/test_coord.py` (121 total). Live-verified: woke an idle
  qualcomm for a directed message; a WAITING 93emulator with 5 directed was
  correctly left alone. Part B (retraction) is next. Backend + frontend, both editions.
- ✅ v2.18.0: 💓 Activity-as-heartbeat — Conductor heartbeats a shared board on
  behalf of a *working* holder. **Found live**: `orb_slam` held `orin-agx` (hard)
  and the watchdog nudged it **7×** over 2h with no reply. It wasn't stalled —
  `status=warm`, actively doing its a78ae rebuild. A remote board has no telemetry,
  so "idle" means *"no `/keep` heartbeat"*, and a Claude deep in a long build never
  stops to run `/keep`. Worse, the loop **defeated itself**: the sessions most
  likely to be nudged are doing long work → no heartbeat → nudged; but long work
  also means `active`/`warm` → v2.17.0's busy guard (correctly) refuses to inject →
  the nudge can *never* reach exactly the sessions it targets. Both decisions were
  right; the *heartbeat model* was the weak link. Fix: `AppState._refresh_active_leases`
  — if the lease owner's session is in `_BUSY_STATUSES`, `resources.touch_lease_activity()`
  rewrites `last_active_epoch` (throttled `_HEARTBEAT_MIN_AGE`=60s) under the **same
  `flock`** `bus.sh` uses (`fcntl.flock` on `<res>/.lock`), so it can't race
  reserve/release/promote. Excluded: the **GPU** (nvidia-smi tells the truth), offers,
  quiet owners, and **dead owners** (else an abandoned lease would look alive forever
  — the v2.16 orphan path must still see it). The broadcast payload sets `idle=0`
  immediately for a busy holder (the `idle` field mirrors the watchdog's `idle_since`,
  which lags a tick). **Watchdog**: now clears `nudged_epoch` when a lease drops below
  the nudge threshold, so a resumed heartbeat ends the idle *episode* — otherwise the
  refreshed `idle_since` would mint a new `_nudge_woken` key every scan and Conductor
  would re-wake the owner repeatedly. Honest caveat: a busy session might be working
  on something unrelated to the board — still strictly better than nudging busy
  sessions who can't hear us and never nudging anyone who can. 5 new tests (19 in
  `test_resources.py`, 108 total). Live-verified: `[docs]` was `warm` with an 828s-stale
  heartbeat → Conductor beat for it (`heartbeat for orin-agx on behalf of a working
  [docs]`), nudges stopped.
- ✅ v2.17.2: 🔧 Resource-name aliases + new-name warning (drift made impossible).
  `orin` drifted back a **second** time (and `imx95-evk` nearly did): a resource
  springs into existence on first reserve, so `/reserve orin` silently created a
  *separate* resource for the same physical Jetson — its own lease, its own queue.
  Found it holding a live `backend` soft lease **with 2 sessions queued** (`docs`,
  `orb_slam`). Migrated the whole lease (owner/mode/epochs/job/queue, order
  preserved) `orin` → `orin-agx` under both flocks, with the watchdog stopped for
  the move, then deleted the stray. Durable fix (Kyle picked "alias + warning"):
  `_res_canon()` maps known spellings to the canonical name (`orin|jetson|agx|
  orin64`→`orin-agx`, `imx95|imx95-evk|frdm-imx95`→`imx95-frdm`, `iq9|iq9075`→
  `iq9-evk`) and prints a note; `res_dispatch` canonicalizes the name arg for
  **every** verb (so `/res-request orin` joins the *orin-agx* queue — the split is
  now impossible); `res_reserve` warns loudly when creating a genuinely new name,
  listing existing resources (typo protection) while keeping the zero-registration
  property. Genuinely different hardware (Orin NX vs AGX) still gets its own name.
  Verified: alias on reserve/keep/release/status/request/promote, `/gpu-*`
  back-compat, no-arg status, hook lines, queue unification, send/check — all pass;
  live lease untouched.
- ✅ v2.17.1: 🪪 Stable session identity — `bus.sh` tags no longer drift with `cd`.
  **Found live** while verifying v2.17.0: `imx95-frdm` was held by `other:bench_data`,
  a tag matching no live session, so Conductor was ~10 min from flagging it as an
  orphan and offering a **reclaim button for a board actively running a GenAI
  benchmark**. Root cause: `bus.sh` derived TAG from the **current cwd** —
  projects in its explicit case-table matched subdirs (`*/keyhole/*`), but anything
  falling through to `other:$(basename "$CWD")` became a *new identity* whenever a
  session `cd`'d (`.../qualcomm/results/bench_data` → `other:bench_data`). Conductor
  meanwhile derives a tag from the session's stable **project dir** — so the two
  disagreed the moment a session changed directory. This also (a) made offer/nudge
  wakes unreachable for such leases, (b) fragmented bus identity (qualcomm's msgs
  arrived as `[other:bench_data]`), and (c) drew one session as two nodes in the
  History graph. Fix: new `_proj_root()` — a dir directly under `BUS_PROJECTS_ROOT`
  (default `~/Documents/GitHub`, env-overridable) resolves to **that project dir**;
  else the enclosing **git root**; else the cwd. Note git-root alone was NOT enough
  (Kyle's `qualcomm/` isn't a repo) — the first patch passed for `claude-connect`
  and failed for `bench_data`; the test caught it. Spliced into live + repo bus.sh
  (backed up). Verified: both `qualcomm/` and `qualcomm/results/bench_data` → 
  `other:qualcomm`; `claude-connect/conductor` → `other:claude-connect`; non-git dirs
  unchanged; explicit table still wins; send/check no regression. Migrated the live
  `imx95-frdm` lease owner `bench_data`→`qualcomm` under flock (otherwise qualcomm
  could no longer `/release` its own board). False orphan confirmed cleared.
- ✅ v2.17.0: 🔔 Wake an idle holder when the watchdog nudges it — closes the
  idle-detection loop. **Found live**: qualcomm held `iq9-evk` (hard) idle for
  75m; the watchdog nudged 3× (30m/50m/1h10m) and qualcomm *never saw a single
  one* — its session was alive but `status=idle`, and bus messages only surface
  through a session's **per-prompt hook**, which an unprompted session never
  fires. So the watchdog was talking into the void and the board stayed locked
  until expiry. Same class of problem the offer-wake solved (an idle session is
  only reachable by a keystroke, not a message) — we'd just never wired nudges to
  it. `read_lease` now exposes `nudged_epoch` + `idle_since_epoch`;
  `AppState._wake_nudged_owners` injects `/msg-check` into a nudged holder **once
  per idle episode** (keyed on `idle_since_epoch`, which the watchdog clears on
  activity — so a *new* idle spell wakes again, but the 20m re-nudge cadence does
  not spam focus). Refactored the two wake paths onto shared `_live_session_for`
  + `_inject_msg_check` helpers, and added a **busy guard** (`_BUSY_STATUSES` =
  active/warm, mirroring the frontend's ping guard) to *both* — never inject
  keystrokes into a Claude mid-task; skip without marking so it retries once
  quiet. Dead owner → left to the v2.16 orphan path. 5 new tests (14 in
  `test_resources.py`, 103 total). Kyle also had me wake qualcomm by hand first.
- ✅ v2.16.0: 👻 Orphan-lease surfacing + 1-click reclaim ("tier 2" of the reboot
  finding) — **and a serious tag-matching bugfix uncovered while building it.**
  Conductor knows which sessions are live, so a lease whose owner has no live
  session is *strong* (not certain — a session can be closed + relaunched)
  evidence of abandonment: `AppState._annotate_orphans` debounces (owner missing
  ≥ `bus.orphan_flag_seconds`, default **600s**, Kyle picked 10m to match
  `RES_ORPHAN_GRACE_MIN`) then marks the lease `orphan_suspect` +
  `owner_offline_seconds`; offers are skipped (they auto-pass). Tile shows
  `⚠ owner offline Xm` + a **reclaim** button → `POST /api/resources/{name}/reclaim`,
  which **refuses (409) unless the backend itself flagged the lease** (a live
  holder's lease can never be yanked from the UI) and then shells out to the same
  race-safe `bus.sh res promote` the watchdog uses (→ offers to the queue head,
  else frees). Conductor never reclaims autonomously — always Kyle's click, always
  confirmed. **THE BUG**: Conductor stores tags bracketed (`[other:qualcomm]`),
  `bus.sh` writes lease owners bare (`other:qualcomm`), so `s.tag == owner` NEVER
  matched. That (a) would have flagged *every* live owner as an orphan, and (b)
  meant **v2.15.0's real-time offer wake never actually fired** — it always fell
  through to the bus-message fallback (I'd misread the `rec is None` as "that
  session isn't live"). Fixed with a shared `_bare_tag()` used by both
  `_annotate_orphans` and `_wake_offered_sessions`; caught only by live-testing
  against the real fleet. Also fixed: `GET /api/resources` recomputed fresh state
  and so silently dropped the orphan flags — it now serves the same scan-cached,
  annotated payload the WS broadcasts. New `tests/test_resources.py` (9 tests,
  regression-guards the bracket/bare mismatch); 98 tests pass. Live-verified:
  live owner NOT flagged, ghost owner flagged, tile + button render.
- ✅ v2.15.1: ♻️ Boot-orphan lease reaping. **Found in production by a reboot**:
  a lease is a *file*, so it outlives the session that took it — after Kyle
  rebooted Skippy, qualcomm's **HARD** `iq9-evk` lease survived with ~3h left
  while its session was dead, and by design the watchdog *never* force-releases a
  hard lease, so it would have nudged a corpse every 20m for three hours while
  the board stayed blocked. Idle-time can't distinguish "owner quiet" from "owner
  dead". Fix uses a **certain** signal, not a heuristic: `acquired_epoch` earlier
  than the kernel's **boot time** (`/proc/stat` `btime`) ⇒ the owning process
  provably cannot exist. `resource-watchdog.sh` gains `_reap_orphan` — promotes
  the lease (hands it to the **next in the queue**, else frees) and posts a
  `[resource-watchdog]` explanation naming the old owner. A post-boot grace
  (`RES_ORPHAN_GRACE_MIN`, 10m) lets an owner who relaunches promptly re-anchor
  with `/keep` (which rewrites `acquired_epoch`) and keep it. `_promote` now
  echoes its outcome (`freed` / `offered:<tag>`) so the reap message states what
  happened; existing call sites silenced. Tested: orphan+no-queue→FREE,
  orphan+queue→offered to next, within-grace→untouched, post-boot lease→
  untouched, `/keep`-re-anchored→untouched. Freed the real orphaned lease live.
  (Possible follow-on "tier 2": Conductor knows which sessions are *live*, so it
  could surface an orphan even without a reboot — but only surface, never
  auto-reclaim a hard lease, since a session may be closed and relaunched.)
- ✅ v2.15.0: 🎟️ Reservation QUEUE + grace-hold hand-off + real-time wake.
  Kyle: "add a queue — a claude waits, gets a ping the moment the board opens,
  decides to use it or not; don't have 20 claudes polling." Design
  (AskUserQuestion): **grace-hold** (board is HELD for the next-in-line ~15m to
  claim/pass, else auto-passes) + **Conductor-inject wake with bus fallback** +
  **full build**. Key reframe pushed back to Kyle: no per-requester watchdogs —
  the *release* is one event; hook promotion there + reuse Conductor's existing
  /msg-check injection for the real-time wake. **bus.sh**: single `requested_by`
  → a FIFO `queue=` field; `/res-request` now JOINS the queue (deduped, reports
  position); on release/expiry/reclaim `_res_promote_locked` pops the head and
  writes an **offer** lease (mode=offer, owner=head, ~15m expiry, queue=rest) +
  posts a `[resource-broker]` "🎉 you're up" msg; new `/res-pass` declines →
  next; `res promote <name> <owner>` is a race-safe (owner-guarded) entry the
  watchdog calls; `_res_write` preserves the queue. Migrated into live+repo
  bus.sh via a tested splice (queue lifecycle, dedup, offer, pass, claim,
  promote paths, race-guard all scratch-tested first). **Watchdog**:
  resource-watchdog.sh now DRIVES the queue — offer-timeout / lease-expiry /
  idle-soft-reclaim all call `bus.sh res promote` (never holds a lock across the
  call; the idle block's fd-9 redirect had to wrap the whole `( … ) 9>lock`
  subshell, caught in test). **Conductor**: `read_lease` parses `queue`+`offered`;
  `AppState._wake_offered_sessions` injects `/msg-check` into the offered
  session the moment it's offered (once per offer, `_pinged_offers` set, bounded;
  untracked/not-live session → bus fallback, no error). Frontend: resource tile
  shows the **queue** (`⏳ N queued (X next)`) and a distinct **OFFER** state
  (blue pulsing dot + OFFER badge + "~Xm to claim"). Live-verified: offer tile
  renders; real fleet already using it (qualcomm reserved iq9-evk hard, watchdog
  nudging an idle Orin lease). Both editions.
- ✅ v2.14.0: 🎛️ Named-resource reservation — generalized the whole GPU
  reservation system to **any shared resource** (the GPU + dev boards like the
  Qualcomm IQ9 EVK). Driven by Kyle: "the IQ9 EVK is owned by qualcomm-claude but
  others want it." Design (AskUserQuestion): **generalize + add EVK** (not a
  one-off) + **heartbeat** idle-detection for non-GPU resources. **bus.sh**: the
  `gpu_*` block became generic `res_*` (lease at `bus-state/resources/<name>/`,
  parameterized by name via `_res_setup`); new `res)` case + `gpu)` kept as a
  back-compat alias (`/gpu-*` → resource `gpu`); the per-prompt hook now shows a
  line **per held resource** (`res_hook_lines`). Spliced into live + repo bus.sh
  via a tested migration (the generic core was scratch-tested first: multi-
  resource lifecycle, correct labels, 8-way race → 1 winner, heartbeat). New
  slash-commands `/reserve /release /keep /res-request /res-status` (+ kept
  `/gpu-*`). **Watchdog**: `gpu-watchdog.sh` → `resource-watchdog.sh` — loops all
  resources, idle = nvidia-smi util (gpu) OR time-since-`/keep` (others); soft
  auto-release, hard check-in only; systemd unit swapped
  (`gpu-watchdog.service` → `resource-watchdog.service`). **Conductor**:
  `conductor/resources.py` (`resources_state` reads all leases + nvidia-smi for
  gpu) replaces the single-GPU `gpu_state`; `"gpu"` WS msg → `"resources"`;
  `/api/gpu` → `/api/resources`; frontend renders a **tile per resource**
  (`fillResourceTile` generalizes `fillGpuTile` — util bar/mem only for the GPU;
  boards get a plain 🔧 lease tile). Path migrated `bus-state/gpu` →
  `bus-state/resources/gpu` (was free, clean). Live-verified: both tiles render
  (GPU free + iq9-evk hard/qualcomm/drone-sizer-waiting via a demo lease). 89
  tests pass. Backend + frontend + bus infra + live services; both editions.
- ✅ v2.13.0: `scripts/token-usage.py` CLI + README fresh-eyes pass. **CLI**: a
  standalone one-shot analyzer (self-contained, no `conductor` import) that sums
  transcript `usage` blocks per session/project/all — `python
  scripts/token-usage.py [path]`, `--json`, clean exit codes. Tested across a
  single session, a project dir, all-projects (Kyle's fleet: 67 sessions / 89K
  turns / 40.1B total), JSON, and bad-path. **README fresh-eyes pass** (cold
  newcomer agent read): version badge 2.8→2.13 (was 4 minors stale); gave the
  GPU system its **own "🎛️ Shared-GPU coordination" section** in Using-the-Dashboard
  (was one dense run-on bullet + an external link — the agent's #2 issue);
  documented the previously-unmentioned **global topbar token sum** + added the
  token line to the "what a tile shows" list + a "🪙 Token usage" section (with
  the out-vs-total explanation + the CLI); added the **NVIDIA/`nvidia-smi`**
  requirement (optional, GPU features only); tightened the swollen GPU/token
  Features bullets to one-liners pointing at the sections; unified 🎛️ (system) vs
  🎮 (tile). Docs + one script; no app-code change.
- ✅ v2.12.1: Token usage polish. Tile badge now literal `tokens: X out · Y total`
  (dropped the 🪙 coin — read as money; no universal token glyph). Added a
  **global token sum next to the "Conductor" title** (topbar-left group): sums
  every session's output + total (`tokens: 41.7M out · 12.5B total`), hover for
  turns + breakdown (`updateTokenTotal` in `tiles.js`, called from `renderGrid`).
  The out↔total delta is all input-side (new input + cache creation + cache
  reads), ~entirely cache reads (whole context re-read each turn — cheap), which
  is why total dwarfs out.
- ✅ v2.12.0: 🪙 Per-session token usage on each tile. Every session tile shows
  a badge (`🪙 617.3K out · 102.6M total`, humanized K/M/B) read from that
  session's transcript `usage` blocks; hover for the full breakdown (output /
  new-input / cache-creation / cache-read / turns / total). Kyle's ask ("record
  how many tokens a Claude has used"). `conductor/tokens.py` `TokenAccountant` is
  **incremental** — transcripts are append-only, so each poll seeks past bytes
  already counted and parses only new *complete* lines (a half-written trailing
  record is deferred, not lost/double-counted), making the per-scan cost O(new
  bytes) even for multi-MB, thousand-turn transcripts. Wired via
  `AppState.token_accountant`; `_sessions_payload` attaches `tokens` per record
  (uses `jsonl_path` before `to_dict` drops it). Frontend: `humanTok` +
  `tokenTooltip` + a `.tile-tokens` line in `fillSessionTile`. Note the honest
  framing — `cache_read` dominates the "total" (the whole context is re-read each
  turn; cheap, ~10% rate) so the tile shows **output** (real work) alongside
  **total** (raw processed). Verified: incremental == full-parse, partial-line
  safe, live screenshot. Frontend + backend, both editions.
- ✅ v2.11.0: 🎮 GPU tile (Phase 3 — Conductor now *visualizes* the GPU system).
  A live tile: GPU name + `nvidia-smi` utilization bar (cool/warm/hot), the
  current lease (soft=amber / hard=red dot, owner, **client-side ticking
  countdown** from `expires_epoch`), the watchdog's idle warning (`⚠ idle 40m`),
  and any pending request (`⏳ [orb_slam] waiting`) + the job note + mem
  used/total. Backend `conductor/gpu.py` (`query_nvidia_smi` + `read_lease` with
  the same lazy-expiry as bus.sh) → `AppState.gpu` polled each scan off-thread,
  broadcast as a `"gpu"` WS message (+ sent on connect) + `GET /api/gpu`. Tile
  only appears when `nvidia-smi` is present (`available`); renders like the Bus
  tile (`GPU_KEY`, `createGpuShell`/`fillGpuTile` in `tiles.js`, a 1s
  `updateGpuCountdowns` ticker). Live-verified via ffmpeg screenshot with a demo
  lease (util%, RTX 5090, HARD/95emulator/~24m, idle-40m, orb_slam-waiting all
  render). Completes the GPU arc: reserve (v2.9) → watchdog (v2.10) → visualize
  (v2.11). Frontend + backend, both editions. (Minor: on a very crowded board
  the tile cascades to a low slot — draggable, persists.)
- ✅ v2.10.0: 🐕 GPU idle watchdog (Phase 2 of the GPU-reservation system). A
  standalone daemon `bus/gpu-watchdog.sh` polls `nvidia-smi` and, when the held
  lease sits idle (utilization ≤ `GPU_IDLE_UTIL_PCT`, default 5% — "models loaded
  but not computing"), acts without the human: **nudges the owner** on the bus
  (a `[gpu-watchdog]` message their prompt-hook surfaces; re-nudges on a cadence,
  names any `/gpu-request`er) after `GPU_IDLE_NUDGE_MIN` (30m); **auto-releases a
  `soft` lease** past `GPU_SOFT_RELEASE_MIN` (60m) with a `to:all` heads-up; a
  **`hard` lease is never auto-released** (owner/user decides — watchdog only
  checks in). Real activity resets the idle clock (writes `last_active_epoch`);
  idle is surfaced in the awareness line too (`… · idle 40m ⚠`) via a
  `_gpu_held_line` update (both bus.sh copies). Shares the lease `flock`, so it
  never races reserve/release. Ships headless via a `systemd --user` unit
  (`bus/gpu-watchdog.service`, `%h`-relative, auto-restart, starts on login) —
  installed + enabled live. Tick logic verified with a mock `nvidia-smi`:
  active-reset, nudge, re-nudge cadence, soft auto-release, hard-preserve all
  correct. **Phase 3** (planned): a Conductor GPU tile. Bus-layer; no dashboard
  needed.
- ✅ v2.9.0: 🎛️ GPU reservation — sessions self-coordinate a shared GPU without
  Kyle arbitrating (MVP; his ask). The bus grows from message-passing to
  shared-*resource* coordination: a cooperative **lease** in
  `~/.claude/bus-state/gpu/lease` (flat key=value; owner/mode/acquired/expires/
  job/requested_by), acquire/release **atomic via `flock`** (stress-tested: 8-way
  race → exactly 1 winner). New `bus.sh gpu {reserve|release|keep|request|status|
  line}` subcommands + `/gpu-*` slash-commands (`bus/commands/`). **soft** =
  "I'll drop it if you need it" (preemptible); **hard** = "mine until my job's
  done or the user stops me". Duration + **lazy auto-expiry** (checked on access;
  a forgotten hold frees itself — no daemon needed). **Auto-awareness**: the
  existing per-prompt `prompt-check` hook appends a GPU line (`GPU: held by
  [95emulator] (hard · ~18m left)` / `YOU hold it — ⚠ [orb_slam] REQUESTED it`)
  **only when held** — silent when free, so zero added noise; nobody has to ask
  anyone. `/gpu-request` flags the owner (surfaced via their hook, no message
  needed). Added to the **live** `~/.claude/bin/bus.sh` + the sanitized repo
  `bus/bus.sh` (additively — `send`/`check`/etc. untouched, verified no
  regression) + `bus/README.md`. **Phase 2** (planned): a standalone `nvidia-smi`
  watchdog that auto-nudges idle holders (models loaded, ~0% util for a long
  time). **Phase 3**: a Conductor GPU tile. Bus-layer feature (works with or
  without the dashboard).
- ✅ v2.8.1: 🎨 Visual identity — logo + hero banner. A hand-built **Radiant
  Bus-Core** SVG logo (`assets/conductor.svg`, also `frontend/logo.svg`): a
  glowing violet bus core (`#bc8cff`, the app's `--bus-color`), six session nodes
  on an orbit ring in the tile/group palette, wires to each, one amber wire
  carrying a message pulse — the app's signature view distilled to a mark. Wired
  in everywhere: the install `.desktop` icon (already pointed at
  `assets/conductor.svg`), the topbar `<h1>`, the Settings header, and the
  favicon (`<link rel=icon>` — also kills the old `/favicon.ico` 404). Concept
  picked by Kyle from three (Radiant Bus-Core / Conductor's Baton / CC
  constellation); rendered + QC'd via librsvg (no rasterizer installed — used
  `gi.repository.Rsvg` + cairo). **README hero banner** (`assets/hero.png`,
  1280×640) — "mission control for AI agents," **commissioned over the bus from
  the `imagegen` fleet node** (its local RTX 5090 + ComfyUI rig): violet bus-core
  ringed by session panels with terminal snippets + status dots, violet cables,
  one amber cable with a pulse mid-flight, title + tagline. Matched to the logo
  palette; plus a 512² square crop (`assets/logo-square.png`). Fun full-circle:
  the dashboard that *visualizes* the bus commissioned its own art *over* that
  bus. Docs + frontend + assets, both editions.
- ✅ v2.8.0: 🧊 Rotate the History graph in 3D. A `🧊 3D` toggle in the History
  overlay spins the whole mention graph in space (Kyle's idea — "fun to rotate
  the ring to see how the clusters are set up"). Deliberately **not** the
  rejected whole-board *tilt* and **not** Three.js: a hand-rolled **SVG 3D
  projection** keeps `heatmap.js` pure-SVG/dependency-free. Each node gains a real
  `z`; a `project()` applies yaw (spin) + pitch (tilt) + weak perspective
  (`CAM_D`) and returns screen `sx,sy,scale,depth`. **project() is identity when
  3D is off AND at rest with a flat layout**, so the 2D graph is byte-for-byte
  unchanged (verified). Per-layout depth: **ring** stays flat (spin/tilt reveals
  crossings), **orbit** lifts into a **dome** (`tz = √(R²−rad²)`, loud=centered=
  high), **clusters** gains a 3rd force axis in `forceStep` (3D repulsion/spring +
  z-gravity toward the z=0 slab). Drag-to-orbit (window pointer handlers, pitch
  clamped so it never flips edge-on; a moved-drag suppresses the node-click so
  orbiting doesn't drill in) + a gentle idle **auto-spin** (`SPIN_RATE`, paused
  while dragging). Depth cues: near=big/bright, far=small/dim (`depthFade`);
  radius/edge-width/pulse scale by perspective. No depth-sorting of the DOM (small
  translucent nodes read fine; a known v1 tradeoff). Toggle persists (`LS_3D`);
  2D stays the default. Frontend only, lazily-imported overlay (a throw can't
  touch the 2D board), both editions.
- ✅ v2.7.1: `/rc` on relaunch is now opt-in (default off) + README fresh-eyes
  pass. The dormant-dock relaunch auto-injected `/rc` on every session — but
  that's Claude Code's `/remote-control` (drive the session from a browser/phone;
  needs a qualifying plan + `/login`), an opinionated side effect Kyle had
  forgotten was there (it came from his original spec: "enter /rc so its remote
  controlled"). Now `[relaunch].rc` (default `false`) gates it, alongside the
  existing `rename` — with both off (the default) relaunch is a clean
  `claude --continue` with **zero keystroke injection** (`_bootstrap_relaunched`
  short-circuits when `not cmds`, and `relaunch_parked` doesn't even schedule it).
  `rc`/`rename` are settings + per-request `/api/relaunch` overrides. **README
  fresh-eyes pass** (read as a dev new to the ecosystem): version badge → 2.7,
  defined `/rc` (was undefined jargon), fixed the "read-only" contradiction
  (→ "read-only *toward Claude*"; the few actions are external + user-triggered),
  glossed "tilix", "binary"→"app", added the `install-app` feature bullet,
  "on the tunnel"→"on the bus". Backend + docs, both editions.
- ✅ v2.7.0: `make install-app` (staged desktop install) + settings polish.
  **Staged install**: `make install-app` copies the app (entry, backend, served
  frontend, icon, and the `claude-tracked` relaunch helper) into
  `~/.local/share/conductor/`, builds the WebKitGTK venv THERE, and points the
  `.desktop` launcher at that copy — so the **cloned repo becomes disposable**
  (the prior `install-desktop` runs out of the clone). `app.py` now
  `sys.path.insert(0, <its dir>)` before importing `conductor`, so the staged
  copy imports its co-located package + serves its own `frontend/` regardless of
  launch cwd or a stray clone editable — verified clone-independent (resolves to
  the staged home from a foreign cwd). Overridable `APP_HOME` / `APPLICATIONS_DIR`
  (tested against a scratch dir end-to-end: copy → `--system-site-packages` venv
  → editable `pip install` → `.desktop` gen). `make uninstall-app` removes it.
  NOT a sandboxed package (Flatpak/Snap would hide host processes from `psutil`
  and break session discovery — Conductor is a host-automation tool) nor a
  single-file binary; it's a self-contained local install. Design fork chosen by
  Kyle over AppImage (staged = 90% of the benefit, ~zero new tooling). README
  "Two ways to install it" table added. **Settings polish**: the settings
  dropdowns showed their value in WebKitGTK's dim native-control color (looked
  like unset placeholder) — `appearance: none` + custom caret so the current
  choice renders in bright `--text`; and a **version label** in the settings
  header (`#settings-version`, fetched from `/api/health`, matches the release
  tag). Backend untouched for settings; both editions.
- ✅ v2.6.1: Dormant-dock drawer no longer fights the cursor. When parked chips
  overflowed, the bottom dock's `overflow-x: auto` drew a **fade-in overlay
  scrollbar** (WebKitGTK native edition) right on top of the chips' ✕ buttons —
  so reaching for a dismiss ✕ summoned the scroll thumb under the cursor (Kyle
  caught it live). Fix in `style.css`: styled `::-webkit-scrollbar` (thin, 8px,
  always-present in a reserved gutter — opting out of the overlay), added bottom
  padding (`8px 12px 14px`) to lift the chip row clear of that gutter, and gave
  `.parked-dismiss` a bigger/taller hit area + hover highlight. CSS-only, both
  editions. Verified by Kyle in the live native window (sandbox can't render
  WebKitGTK — see the no-live-HTTP constraint).
- ✅ v2.6.0: 💤 Dormant dock — relaunch a closed session in one click. Sessions
  Kyle closes don't vanish: every project dir with on-disk history but no live
  process now surfaces as a chip in the bottom dock (a "💤 Dormant" group after
  the minimized tiles). **Clicking it relaunches that session** — opens
  `claude --continue` in its original folder in a tracked Tilix window, then,
  once the new session appears and its TUI settles, **injects `/rc`** (and
  optionally `/rename`) so it comes back remote-controlled with its identity
  intact. Backend: `discover_parked_projects(projects_root, tag_map, live_cwds)`
  (`scanner.py`) walks each project dir, resolves the cwd its newest transcript
  last ran in, and skips cwds that are currently live, folders deleted off disk,
  or unreadable transcripts (dedups multiple encoded dirs → same cwd, newest
  wins, capped 40). Surfaced as `ParkedSession` on the `sessions` payload.
  `POST /api/relaunch {project}` (path-validated to the projects root, refuses if
  a session is already live there) → `AppState.relaunch_parked` spawns
  `claude-tracked <name> --dir <cwd> --continue` detached, then schedules
  `_bootstrap_relaunched`, which **polls the scanner for the new live session**
  before injecting (the flaky part — keystrokes only land once the TUI is up;
  timing knobs in `[relaunch]` settings: `settle_seconds`, `between_seconds`,
  `appear_timeout_seconds`, `rename`). `scripts/claude-tracked` gained `--dir`
  (cd's first so `--continue` resolves to the right folder; legacy callers
  unaffected) and — caught during Kyle's live test — switched its tilix launch
  from `-- <cmd>` to `-e <cmd>`: when a tilix server is already running (always,
  if you have other windows open) the single-instance invocation **silently
  drops** a `--`-style command and opens a bare shell, so claude never launched
  and there was nothing to inject `/rc` into; `-e` is honored by the running
  server. Frontend: `parkedChip` in `tiles.js` (dashed dock chip, 💤 + name
  + tag + last-active age, click→relaunch with optimistic "launching…", trailing
  ✕ to dismiss); dismissals persist (`conductor.parkedDismissed.v1`) and
  **auto-clear when that folder goes live again** ("auto + dismiss"). New live
  session removes the chip on the next scan. **Note:** spawn + keystroke
  injection are X11/terminal-level and can't run in the sandbox — pure logic
  (`discover_parked_projects`, dedup, limit, exclusions) is unit-tested; the live
  click path is hand-verified. Backend + frontend, both editions. **Scope: tilix
  only** (same as v2.1.2 focus).
- ✅ v2.5.1: 📬 Honest unread badge for never-checked sessions.
  `compute_pending` (`bus.py`) returned 0 for any tag with no `<tag>.last-seen`
  file, so a prolific sender that had never run `prompt-check` (never
  self-checked, never pinged) showed an empty 📬 badge while real messages piled
  up — the `95emulator` blind spot Kyle caught (chatty on the bus, badge stuck
  at 0). **Fix A**: when no `last-seen` exists, infer the baseline from the tag's
  own *latest sent message* — a session that just posted has demonstrably caught
  up to that moment, so only later messages from others count as unread. A tag
  that never sent AND never read still yields 0 (no basis for "unread"; don't
  dump all bus history on a brand-new session's first contact). A real
  `last-seen`, once written by that session's first check, supersedes the
  estimate. Also adds `scripts/bus-backlog` — a read-only diagnostic that prints
  the real backlog per tag and *why* each badge reads what it does
  (`read` / `inferred` / `NEVER`), for when a tile looks suspiciously quiet.
  Backend-only computation shared by both editions, so no frontend change.
- ✅ v2.5.0: 🔬 Drill-down — watch a session explode outward in work. In the
  History human layer, **clicking a session node** opens the whole **you↔session
  working relationship** replayed on a playhead: a `[you]` node fires each prompt
  into the central session node, which detonates outward into the **files** it
  touched (deduped halo, read=blue/edit=orange, grow with touches), **sub-agents**
  spawned (Agent/Task), and every **tool call** (pulse + live counter tape). A
  **🔍 Focus prompt** selector isolates one exchange at a time (✕ returns to the
  whole relationship). Backend: `extract_session_detail(jsonl_paths)` in
  `scanner.py` walks every transcript in the project dir via `_walk_exchanges`,
  returns time-ordered `{prompts, events, summary, dropped}` with each event
  tagged by its prompt index `ex` (so focus-one is a client-side filter);
  `_classify_tool` maps tool_use → file/agent/tool nodes; tool_result `is_error`
  tints failures. `GET /api/session-detail?project=` (path-validated, off-thread).
  Cap 12000 events; when trimmed, orphaned prompts are dropped so the replay has
  no dead prompts-only prefix (keep prompts that own retained events or are
  in-window — the bug Kyle caught where 95 showed prompts for half the run before
  work appeared). Also a single-exchange `extract_exchange` + `/api/exchange`
  exist. Frontend `drilldown.js` (lazy-imported, pure SVG, deterministic-`f`).
  **Folds in v2.4.1**: the human layer now counts only GENUINE typed prompts —
  `_human_prompt_text` strips `<system-reminder>` / `<command-*>` /
  `<local-command-*>` wrappers and rejects pure injections, auto-compact
  continuations, and bare slash-commands (~5% of prior "prompts" were harness
  noise). Idea + event-schema collaboration came from 95emulator via the bus.
  Both editions.
- ✅ v2.4.0: 🕸 History — human↔Claude layer. A `👤 Human` toggle in the
  History overlay weaves the human turns into the same time-lapse. Backend:
  `/api/bus/heatmap?human=1` merges `build_mention_history` (bus) with
  `collect_human_events` (`scanner.py`), which walks `~/.claude/projects/*/*.jsonl`
  and emits **turn-level** events — one `prompt` (`[you]`→session) + one collapsed
  `reply` (session→`[you]`) per exchange, NOT every streaming/tool sub-record.
  Real human prompts are told apart from tool-result user-messages by content
  shape (`_user_text_len`: text blocks, no `tool_result`); sidechain/meta records
  skipped; ISO timestamps → epoch. Sessions key to the **same bus tags** via
  `derive_tag(recorded_cwd, settings.bus.tags)`, so human edges land on the bus
  nodes. Each event carries `kind` (bus|prompt|reply); merged stream re-sorted by
  ts; nodes recomputed (adds `[you]` with `is_you`, `first_seen`, source-count).
  Capped at 8000 most-recent events with a surfaced `dropped` count (no silent
  truncation; ~1.7s parse, off-thread, on-demand). `human=off` is byte-for-byte
  the old bus-only graph. Frontend: `heatmap.js` restructured so controls + the
  rAF loop wire once and `rebuild(data)` swaps graph state — the toggle just
  re-fetches and rebuilds in place (preserving layout/speed). `[you]` renders
  gold, labeled with the OS username (`_human_label`, capitalized; "You" if
  unavailable — NOT hardcoded); human edges gold + dashed (`hm-edge-human`, keyed off either
  endpoint being `[you]`). Toggle persists (`localStorage` `conductor.heatmapHuman`).
  Aligns to 95emulator's proposed `{ts,src,dst,kind,sessionId}` schema (the idea
  came in via the bus). Frontend + backend, both editions.
- ✅ v2.3.0: 🕸 History time-lapse. A `🕸 History` topbar button replays the
  **entire** bus (live `messages.md` + every `messages-*.md` archive) as an
  animated graph. Backend `GET /api/bus/heatmap` (`build_mention_history` in
  `bus.py`) sweeps all logs and returns `{nodes, events}` time-ordered; since
  the bus is broadcast-only (0 `@to` in practice), edges are **inferred from
  mentions** — a message naming another session — using a longest-first regex
  alternation so `pai-sizer` ≠ `sizer`. `[system]` rotation notices are
  excluded. Each event carries `size` (body length). Frontend `heatmap.js` is
  **lazily imported** like `scene3d.js` (pure SVG, no deps — a failure can't
  touch the 2D board): a full-screen overlay where nodes fade in as each session
  first speaks (and persist dimmed when quiet), undirected mention-lines thicken
  with cumulative traffic, and a pulse-dot flies each wire on use, **sized by
  message length** (fat report vs. speck hello). Everything is a pure function
  of one progress scalar `f∈[0,1]` (glow/pulse recency = `f - lastTouch`, no
  timers), so scrubbing back is just a cheap replay. Play/pause + scrubber +
  0.25×–5× speeds, idle-gap-clamped virtual timeline. **Three layouts** via a
  switcher (persisted to `localStorage` `conductor.heatmapLayout`): **clusters**
  (default; live force-directed sim — mention-edges are springs, frequent
  partners drift together as weights grow during playback), **ring** (arrival
  order), **orbit** (radial by volume, loudest centered). Modes morph smoothly
  (everything seeds as a ring, then eases/springs into place). Force constants
  tuned by a stability stress-test (3000 steps, worst-case dense graph: no
  NaN/explosion, converges, no overlap) since the sandbox can't run a live
  browser. Frontend + one backend field; ships in both editions.
- ✅ v2.2.0: 3D view (fork ②). A `🧊 3D` topbar toggle swaps the 2D board for
  a WebGL scene rendered with Three.js + `CSS3DRenderer` (loaded via import map,
  no build step). `frontend/scene3d.js` is **dynamically imported only on first
  toggle**, so a CDN miss can never break the 2D default. Session cards are real
  DOM (crisp text, reusing the `requestFocus`/`toggleBusActive`/`requestCheck`
  globals), **billboarded** to always face the camera — the lesson from the
  rejected CSS-tilt prototype (never angle the content you read; depth lives in
  the space between tiles). OrbitControls (drag-orbit / scroll-zoom), a glowing
  bus core, and bus wires drawn on an SVG overlay by projecting each card's 3D
  position to screen (flow animation on message). Three layouts via a floating
  switcher — **carousel** (default; ring you spin, front card enlarged),
  **orbital** (fibonacci sphere around the core), **gallery** (reuses the v1.5
  saved positions, depth by status). **Groups** carry into 3D: group color
  (border+glow) + spatial clustering (contiguous ordering → adjacent placement
  for orbital/carousel; centroid-pull for gallery), reading the same
  `conductor.groups.v2` store (assignment still happens via the 2D ▦ menu).
  Prefs `view3d` (default false → 2D) + `layout3d` (default "carousel") persist
  in localStorage. Two bugs caught during the build, both verified via headless
  screenshots: (1) cards inherited `.tile` which forced `position:absolute` w/o
  `top/left` → mis-anchored in the CSS3D transform; fixed with a self-contained
  `.card3d`. (2) A `.scene3d > div` rule also matched the controls bar, blowing
  it to a full-screen opaque panel that hid everything; removed (the renderer
  sizes its own host). Frontend only, ships in both editions.
- ✅ v2.1.2: Tilix-exact tile focus. `focus_session`/`send_keys_to_session`
  now resolve a session's tilix tile by `TILIX_ID` (read from
  `/proc/<pid>/environ`) and call the `activate-terminal` gaction over the
  `com.gexperts.Tilix` D-Bus name — raising the window *and* selecting the exact
  tile. This runs before the old wmctrl title matching and falls back to it for
  non-tilix terminals / when `gdbus` or `TILIX_ID` is absent. Fixes the
  combined-window corner case: title matching only sees the *active* tile's
  title, so a backgrounded tile lost focus to a stray same-named terminal (e.g.
  a shell `cd`'d into the project dir); the exact PID→tile handle sidesteps X11
  titles entirely. Backend only, ships in both editions. **Scope: tilix only.**
  Tested exclusively with tilix; other multi-window terminals (terminator,
  kitty, gnome-terminal tabs, …) are out of scope and untested — they simply
  fall through to the wmctrl title path, no regression. No plans to support
  other tiling terminals.
- ✅ v2.1.1: Stop the multi-session tile blink. `renderGrid` now reconciles
  tiles (reuse the outer node per key + refresh content in place) instead of
  `innerHTML=""` teardown every WS update. Preserving node identity means an
  ended tile's opacity fade runs once to 0 instead of restarting on each of the
  ~10 updates that arrive while several sessions tear down at once (the v1.5.3
  fix only stopped the backend ENDED↔ACTIVE flap; this is the frontend layer).
  Drag handlers + the resize observer now attach once, not per-render. Frontend
  only, so it ships in both editions.
- ✅ v2.1: Native App Edition. `app.py` launches the same FastAPI app in a
  pywebview/WebKitGTK window — uvicorn runs in a daemon thread, window-close
  stops it, and it attaches to an already-running instance instead of spawning
  a duplicate. Makefile `install-native` (separate `.venv-native` with
  `--system-site-packages`) / `native` / `install-desktop`; `.desktop` template
  + SVG icon. Release scheme (as of v2.1.2): a **single release per version**
  from the bare tag (`vX.Y.Z`), covering both editions — it's one commit, the
  edition is just `make run` vs `make native`. The old `-native` split-release
  scheme is retired; legacy `-native` tags/releases (≤ v2.1.0-native) stay as
  history.
- ✅ v2.0: Web Browser Edition milestone — clean baseline for the dual-edition
  era (functionally same as v1.5.3).
- ✅ v1.5: Durable layout. Tiles keyed by project dir (not the ephemeral
  session UUID), and offline tiles' layout/groups are no longer GC'd — so
  positions/sizes/groups survive reboots and fresh sessions. localStorage keys
  bumped to v2 (positions/minimized/groups). README documents what's stored where.
- ✅ v1.4: Color-coded groups. Per-tile ▦ menu assigns membership (no canvas
  multi-select — a popup that closes before re-render, avoiding drag/click
  conflicts). Minimize a whole group to one dock chip w/ rollup; ▦ Groups
  panel manages rename/recolor/minimize/ungroup. Logical (color-only), in
  localStorage (`conductor.groups.v1`).
- ✅ v1.3: Minimize tiles to a bottom dock (live status, click to restore;
  state persisted); "Lines behind tiles" appearance toggle (overlay z-index).
- ✅ v1.2: Tile resize (corner grip, size persisted) + full-title tooltip.
  Active⇄Passive per-tile toggle (click the tag chip) → `POST /api/bus/active`
  writes `~/.claude/bus-state/active-tags`, the data-file whitelist that the
  migrated `bus.sh` reads (falls back to defaults when absent). Connection
  lines: solid = active (auto-notified), dashed = passive; legend bottom-left.

See `CONDUCTOR_SPEC.md` for full design.
