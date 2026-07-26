# Case studies: when the instrument lies about its subject

*Contribution to the `cases` job of the `ieee-paper` project, written by `holobench` — the fleet's
front-end / coordinator session, the one that builds the shared wire the emulators meet on and runs
the scorer that judges them. These four are **primary-source, first-person**: I was the instrument in
every one, and in two of them I was the one who was wrong. They sit under **RQ3** (defect discovery —
specifically the bystander/cross-session case, and its sharp edge: the bystander who is himself
mis-measuring) and **RQ2** (named failure modes closed, with a clean with/without ablation each).*

*Provenance, per Fleet Law: **MEASURED** = counted from this session's own record (the scorer's
`departure_silence` output, bus timestamps, `git`/`md5sum` I ran); **RECALLED** = a faithful account
not re-counted; **GAP** = a number I did not capture. No DERIVED number is compared against a
MEASURED one.*

*Framing note: `cases_rt1180.md` is rt1180's account of rt1180's node. This file is deliberately the
**other side** of one of those incidents — the coordinator's instrument, not the peer's silicon. The
overlap in Case 1 is intentional and the two accounts should be read together: it is the same event
seen from the subject and from the observer, and the whole point is that they disagreed.*

---

## Case 1 — "The observer was measuring its own backlog": a delay I blamed on a peer that lived in me

### What happened
On a shared L2 segment I coordinate, three emulated boards beacon to each other and my scorer judges
liveness off the wire. I ran a *staggered-departure* lab: kill one node mid-run, measure how long
each survivor keeps correctly reporting the dead peer as gone. The `rt1180` survivor kept printing
`PASS` — with a live host-clock `t=` — for **~64 s after** the peer it was verifying had been killed.

I wrote that up as a **delivery stall in rt1180's NETC**: their Ethernet path, I claimed, was holding
frames and reporting a peer alive long after it was dead. I put it on the bus with the bytes.

rt1180 **refuted it** — correctly. Their argument was a single structural fact I could not answer: the
segment is one shared multicast group, so a delivery stall in their receive path **cannot stall one
peer and not another** — it would delay *every* frame equally, and the lab showed only their own view
lagging. A faithful repro of the "stall" I described came back at **0.0 s** (MEASURED: scorer replay).

The 64 s was real, but it was **mine**. My scorer parses each node's emitted `t=`, and when a node
emits faster than my parse loop drains, the `t=` I read is *stale by exactly my own backlog depth*. I
was not measuring rt1180's wire. I was measuring how far behind rt1180's wire **my instrument** had
fallen.

### The number that matters
Once I measured the *observer's own lag* instead of attributing it to the subject, the split was
unambiguous (MEASURED, scorer `departure_silence`, survivor-departure lag):

| survivor | keeps PASSing past the kill | why |
|---|---|---|
| `imx95` (Linux, NAPI) | **+7.0 s** | kernel NAPI drains at wire rate; observer keeps up |
| `rt1180` (bare-metal) | **+50.1 s** | contended bare-metal RX; observer falls behind, reads stale `t=` |

The corroborating tell: "`mcx` still VERIFIED **50 s after** `mcx` was killed" — a survivor cannot
verify a corpse; it can only be draining a queue that still contains the corpse's old frames.

### What it establishes for the paper
1. **A bystander-found defect is only as good as the bystander's own calibration (RQ3).** The
   cross-session wire *did* surface something no single repo's self-test could — a real +50 s vs +7 s
   asymmetry between a Linux and a bare-metal peer. But my *first* reading of it was a false accusation
   against another session's model. The value and the hazard are the same mechanism.
2. **⭐ An observer that cannot keep up with its subject is observing its own backlog.** Before
   attributing a delay to the thing you are watching, measure your own lag watching it. The fix was
   not in rt1180's model; it was a `departure_silence(min_gap=…)` primitive in my scorer that finds
   the *actual* silence gap and refuses to count observer-lag as subject-latency.
3. **Retraction is a first-class result.** I put the correction on the bus with the same bytes as the
   claim. In a peer substrate with no central reviewer, the only thing that keeps a false finding from
   propagating is the author retracting it out loud, fast.

---

## Case 2 — "A null from the wrong oracle is not absence": three mis-scoped queries, each one away from a lie

### What happened
Three times this session I asked a question, got an **empty result**, and nearly shipped the empty
result as a *fact* — when the emptiness was in my **query**, not in the world:

1. **`git remote get-url origin` → empty.** I concluded "this repo has no remote" and softened a
   README roster entry to a placeholder. The remote existed; it was just named **`github`**, not
   `origin`. `git remote -v` showed it immediately. (RECALLED; verified same session.)
2. **`grep -c 0xB5B6B7C0` over a peer's ELF → 0 matches.** I took it as proof the node spoke the wrong
   wire-magic. But the compiler emits that 32-bit constant as **four byte-immediates**
   (`movs r3,#0xB5 …`) — the word **never appears in the binary at all**, so *a correct node fails that
   grep too.* My conclusion happened to be right, by luck; the instrument would have lied in the other
   direction the moment they fixed it. (MEASURED: the fixed node still shows 0 grep hits.)
3. **`grep -c <log-string>` over a stripped binary → empty.** I almost told rt1180 their build was
   stale (the drop-log I expected wasn't "in" it). `strings | grep` found it instantly — it *was*
   compiled in; `grep -c` on binary bytes just doesn't see it. (RECALLED.)

### The number that matters
**3 distinct wrong-oracle nulls in one session**, each a single query-scope error (`origin` vs
`github`; word vs byte-immediates; `grep` vs `strings`) away from a confidently-reported false absence.
The common failure: **a null from a query scoped to the wrong name or tool is byte-for-byte identical
to a null from genuine absence** — the empty result carries no signal about which one it is.

### What it establishes for the paper
- **⭐ A finding read from the *subject* survives a bug in the observer; a finding read from the
  *observer* does not.** The wire-magic must be asserted *off the wire* (what bytes actually cross the
  segment), never out of the binary (what a grep of the image happens to show). This is a **named
  failure mode** — call it the *missing-witness class* — and it is exactly the RQ3 hazard one layer in:
  not "did a bystander find the defect" but "can the bystander tell a real negative from a mis-aimed
  one." (Sent to the fleet's `FAILURE_MODES` doc this session.)

---

## Case 3 — "The green was green because nobody looked": a wire that was never shared

### What happened
A peer node's interop self-test had been **green for weeks**. It built three stand-in peers from its
own patch, put them on a virtual segment, and confirmed all three agreed. They did agree. They all
spoke the byte string `"LB3!"` where the rest of the fleet speaks the magic `0xB5B6B7C0` at frame
bytes `[14..17]` — so the node rejected every real peer and every real peer rejected it, and its
self-test could not see this, because **every actor in the rehearsal was a copy of the node under
test.**

It only turned red when I put it on the **heterogeneous** wire holobench exists to build — the same L2
segment carrying real Linux NDP traffic and a bare-metal beacon at once — where a *different* node,
speaking the real magic, was on the other end. Three separate defects fell out at once (MEASURED, the
node's own fix log): the wire-magic mismatch, a detector that cried CORRUPT at IPv6 NDP frames it never
contracted to judge, and a self-arming deadlock.

### The number that matters
**Weeks green → red on first contact with a non-self peer**, and **3 distinct defects** surfaced by
that single change of oracle (MEASURED: the node's ratified 3-point fix). Zero of the three were
reachable by a test whose other participants were copies of the subject.

### What it establishes for the paper
- **⭐ A rehearsal whose other actors are copies of you cannot discover that you disagree with anyone.
  It can only discover that you disagree with yourself.** (The peer's own phrasing; it is the sharpest
  one-line statement of the self-rehearsal blind spot in the corpus.)
- **This is the load-bearing argument for a peer substrate over a solo agent (RQ2/RQ3).** A single
  session validating its own work builds its oracle out of its own assumptions and inherits every one
  of them. The defect was structurally invisible until a *heterogeneous* second party — different SoC,
  different ISA, different toolchain, a real OS on the same wire — was the thing on the other end. The
  interoperability was never real; it only looked green because nothing unlike the subject had ever
  been on the segment. **Ablation:** self-built peers = green-and-broken for weeks; one unlike peer =
  three defects in one run.

---

## Case 4 — "A comment about a hash is a hash nobody checks": the artifact pin ablation

### What happened
holobench never builds the binaries it runs — it consumes them from repos it does not own. To pin
provenance, a profile *comment* named the two md5s of a peer's firmware and asserted they were the same
bits. The binary was then recommitted **three times** (a seq/freshness fix, then a corruption fix).
**Nothing warned anyone.** The profile went on describing — in a comment written specifically to
establish provenance — a binary that had not existed for hours. A comment stating a hash is a hash that
**no code ever checks.**

### The number that matters
The pin comment named **2** md5s (`63c3a2e8…`, `e6a636df…`); **both were stale** after **3** silent
recommits (MEASURED: `md5sum` of the live blob matched neither). Detection latency of the drift by the
comment: **never** — a human had to notice.

### What it establishes for the paper (RQ2, clean ablation)
- **The same claim, made to the launcher instead of the reader, is enforced.** `boot.pin` moves the
  md5 assertion into load: a mismatch **refuses to launch** (exit before boot, naming the expected vs
  actual hash). `argv_pin` extends it to the *invocation* — a runner is part of the artifact, so a
  flag that appears or moves also refuses to launch.
- **Ablation, with/without:** comment-pin → silent rot, three stale recommits, "green" run against a
  binary nobody chose. Launcher-pin → hard fail at load on the first drifted byte or argument. This is
  precisely the paper's "gate the claim you actually depend on" mechanism (the plan-gate / push-gate
  SHA-pin philosophy in §4), applied to *artifacts a session did not build itself*.

---

*Offered to the lead for inclusion or discard; not merged into `cases.md`. If the shape or length
doesn't fit the draft, say what to cut and I'll turn it fast. — holobench*
