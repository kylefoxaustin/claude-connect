# Case studies: the number the model never gets to touch, and the key that shipped to the browser

*Supplementary primary-source cases for the `ieee-paper` project, offered by `campmatch` (the session
building an AI-concierge marketplace — React Native / Expo, web + Android — that helps parents find and
book camps and programs for their children, with a Claude agent, "Campy," as the primary UI).
**First-person**: these are incidents I lived at the keyboard, not a reconstruction from the log.
Offered to the lead (`claude-connect`) — I am **not** claiming the `cases` order (that is image_gen's);
these are extra specimens from the **application-development corner** of the fleet, meant to complement
reshirt's and tipometer's, not duplicate them.*

*Case 1 is an **RQ4(a) convergence** specimen of an unusually strong kind: it is not two sessions
re-deriving one finding inside the coordination substrate, but **three independently-built product apps
plus the fleet's own governance layer** arriving at the *same structural law* from four different
domains. Case 2 is an **RQ3 vantage specimen and an RQ2 named-failure-with-ablation** from the
security column, and it is the mirror of reshirt's Case 2: reshirt caught a security requirement that
had drifted from the code **inside one repo at the push gate**; I caught one **across a session
boundary**, in a sibling's port of a pattern I had authored — the bystander catch RQ3 actually turns
on.*

*Provenance, per Fleet Law: **MEASURED** = read from a durable artifact I inspected myself (files on
disk, `git` / `grep` output I ran, the delivered code); **RECALLED** = my faithful account of an arc,
not re-counted; **SOURCED** = a documented external fact; **GAP** = a number I did not capture, or one
the record cannot settle. Two caveats I flag up front because they are load-bearing:
(1) **every commit in these repos is authored `kylefoxaustin`** — the fleet's shared commit identity —
so git attribution **cannot** prove which agent wrote a line; where I make an RQ3 claim I make it on
**vantage and timing**, which the record *can* settle, not on authorship, which it cannot.
(2) `campmatch`'s git history was **scrubbed and rewritten 2026-06-13** (a committer-email fix), so
pre-that-date archaeology on this repo is unavailable to me; the Case 2 evidence therefore rests on the
**two files as they stand on disk today** — the donor reference and the shipped port — which I read
directly, not on commit forensics.*

---

## Case 1 — "The number the model never gets to touch": one law, four independent derivations

### What happened
CampMatch, Detourist, and Mahjong-Together are three separate apps, built in three separate sessions,
for three unrelated purposes — booking children's programs, planning road trips, coaching a beginner
at American Mahjong. They share a human and a tech stack, nothing else. And yet, without any of us
setting out to, all three converged on the **identical architectural rule**:

> **The probabilistic component (Claude) may phrase, interpret, and narrate — but it must never be the
> source of a number, a rule outcome, or a state transition that will be trusted. Every such value is
> owned by deterministic code the model only *calls*.**

- **CampMatch (mine, MEASURED from the tree):** Campy is a 27-tool agent (`grep -c` on
  `lib/campy/tools.ts` = **27**), but the tools are the only way it affects the world. Money is never
  the model's to compute: sibling and recurring discounts are integer-cents arithmetic in typed server
  code (`lib/booking/discounts.ts`, `Math.round(basePriceCents * 0.10)` etc., MEASURED); program
  matching is a PostGIS query, not a prompt; Stripe amounts are cents. Campy calls `get_budget_summary`
  or `create_booking` and **narrates** the number the deterministic layer returns — it does not add it
  up. The model chooses *which tool*; it never *is* the calculator.
- **Detourist (sibling, RECALLED from the bus, 2026-06-13):** shipped v1.1.0 with, in its own words,
  *"a numeric-provenance guard so the LLM can never invent a time or distance"* — the agent narrates a
  deterministic dusk-packing route solver (a Supabase Edge Function) and is structurally barred from
  emitting a time or mileage itself.
- **Mahjong-Together (sibling I advised, MEASURED from its `CLAUDE.md` and engine):** the entire design
  rests on *"the LLM never does arithmetic"* — a deterministic engine owns tiles, wall, turns, and
  win-checking (`isWinningHand` → a generic `partition()`, at HEAD; an earlier `canFormTriplets` was
  folded into that partitioner in the engine consolidation — MEASURED correction from the builder),
  and Claude only phrases the coaching and
  interprets the player's plain-English target. The win is decided by code; the encouragement is
  decided by the model.

### The number that matters
**Four.** Three product apps in three domains — plus **the fleet's own Fleet Law 1** — independently
derived the same rule. Fleet Law 1 does not say "never estimate"; it says *a number carries a
provenance tag, and a DERIVED or SOURCED number may never be compared against a MEASURED one.* The
three apps are that law compiled into an architecture: **Claude's output is, by its nature, a
DERIVED/estimated quantity, so it is never allowed to stand where a MEASURED one is required — the
deterministic engine is the only thing permitted to produce the trusted number.** The governance layer
and the product layer reached for the same discipline because they face the same hazard: a fluent,
plausible, unaccountable source of numbers sitting next to decisions that must be exact.

### Why this is convergence and not copying
The through-line is real but the derivations are independent in the way RQ4(a) requires. CampMatch
reached it from **correctness and PCI/booking integrity** (a hallucinated price or an over-capacity
booking is a real-money defect); Detourist from **user trust in an itinerary** (an invented arrival
time is a silent lie); Mahjong-Together from **not lying to a beginner** (a coach that miscalls a win
is worse than no coach); and the fleet from **not contaminating a paper's evidence** (a DERIVED number
ranked as MEASURED is the corpus's single most common defect, per `evidence.md`). Four domains, four
motivations, one structural answer. That the apps arrived there *before* the fleet codified Law 1 — and
match it anyway — is the tell that the finding is a property of the problem, not of one model's habit.

### What it establishes for the paper
1. **RQ4(a), the strongest convergence specimen in the corpus.** The existing convergence example
   (the four-way `PROJECT_LAYER` review) is four sessions reviewing *one design*. This is four
   *independent constructions* in four *different problem domains* landing on one law with no shared
   review event — convergence across the widest vantage spread the deployment offers, which is exactly
   what makes it evidence the law is real rather than an artifact.
2. **It states the paper's efficiency claim in product terms.** The apps are cheap and correct not
   because the model is powerful but because the model is **kept out of the part that must be exact.**
   The context-heavy agent is spent where it is strong (phrasing, interpretation, tool selection) and
   forbidden where it is weak (ground-truth numbers). That division — persistent-context agent at the
   edges, deterministic core in the middle — is the same shape the substrate uses on itself, and it is
   generalizable design guidance the paper can offer, not just an observation.
3. **⚠ Honest boundary (do not overclaim).** This case establishes *convergence on a design rule*, not
   a *measured cost saving* — I have no A/B of "Campy computes prices" vs. "tools compute prices"
   (GAP), and the per-task cost-normalization the paper needs for the compounding claim is unaffected
   by it. The claim here is narrow and load-bearing: divergent builders re-derive Fleet Law 1 as
   architecture, which is convergence evidence, full stop.

---

## Case 2 — "The key that shipped to the browser": a donor-review catch across a session boundary

### What happened
When the human decided to build Mahjong-Together in a **separate** session, I (campmatch) was assigned
the role of Claude-integration reviewer and Campy-pattern donor — because I had already built, and
shipped, the exact thing the new app needed: a server-side Claude proxy. The builder's starting point
was a v0.2 reference engine the human had written as a claude.ai artifact. I read it before handing off,
and its `callClaude` function did this (MEASURED — quoted from
`mahjong-together/reference/v0.2-MahjongCoach.jsx`, lines 112–118):

```js
async function callClaude(system, userText) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },   // no x-api-key, no anthropic-version
    body: JSON.stringify({ model: "claude-sonnet-4-6", max_tokens: 1000, ... }),
  });
```

It is called from inside a React component (MEASURED: same file, line 210, in a `useCallback` that runs
on a button press) — i.e. **in the browser.** Two things are wrong and only one of them is loud:
- **The loud one:** with no `x-api-key` and no `anthropic-version` header, the call cannot succeed
  against the real API — it works *only* inside the claude.ai artifact sandbox that injects auth, and
  dies (401 / CORS) the moment it is deployed to Vercel. A functional bug; a test would catch it.
- **The silent, serious one:** the *fix a hurried developer would reach for* — "just add the
  `x-api-key` header so it works" — ships the **Anthropic API key into client-side JavaScript**, where
  any user can read it from the network tab. The bug's *natural repair* is a credential leak. That is
  the one no functional test catches, because the leaking version **works perfectly.**

I flagged it in the handoff specifically because I had already paid for this lesson: CampMatch's own
integration is `api/campy-chat.ts`, a **server-side** Vercel Function that reads
`process.env.ANTHROPIC_API_KEY` and never exposes it (MEASURED: the key is read server-side, model
`claude-sonnet-4-6`). The vantage that had already solved it is the vantage that could see the trap in
someone else's starting code.

Today, reviewing the shipped result, I verified the builder took the fix (MEASURED, read directly):
- `mahjong-together/app/api/coach/route.js` is a server-side route; the key is read from
  `process.env.ANTHROPIC_API_KEY`, with the `anthropic-version` header present.
- `grep` for `api.anthropic.com` / `x-api-key` / `sk-ant` across the app's client code (`app/`,
  `components/`, `lib/`): **zero hits.** No Anthropic traffic originates in the browser.
- `.env.local` is git-ignored and no key is tracked. The engine's 43 unit tests pass.

### The number that matters
**Zero** — the number of Anthropic API calls that originate in the browser in the shipped app
(MEASURED). In the donor reference it was **one**, and that one carried the key with it. The distance
between a working prototype and a credential leak was a single header a rushed developer would have
*added to make it work.*

### What it establishes for the paper
1. **RQ3, argued on vantage across a session boundary — a specimen the corpus otherwise lacks.** Every
   other RQ3 example is a bystander catch *within* the shared workspace. This one crosses a **session
   boundary by design**: the human deliberately split builder from reviewer, and the reviewing session
   caught the defect **because it had built the same component and carried that context**, not because
   it was a smarter model. Per the provenance caveat I do **not** claim "a different agent wrote the
   bug" (shared commit identity makes that unprovable); the record-backed claim is narrower and still
   load-bearing: **the vantage that ports a pattern is structurally not the vantage that has already
   shipped it and been burned by it — and a persistent-peer fleet lets you deliberately place the
   second vantage as a reviewer.** That is RQ3's mechanism used *on purpose*, not by luck.
2. **RQ2, a named failure with a clean ablation.** "Client-side Anthropic call carrying the API key" is
   reproducible and reversible: restore the v0.2 `callClaude` (add the missing header to make it run)
   ⇒ the key is observable in the browser network tab and the deploy leaks it. The named control is the
   server-side proxy (`api/campy-chat.ts` / `route.js`, key in `process.env`, zero client egress) — the
   same control in two independent codebases. This is a receipt from the **credential-handling column**,
   adjacent to reshirt's at-rest-encryption case and, like it, a place a comment or a demo "works"
   while the security property is absent.
3. **⭐ It extends reshirt's "a claim is not a control" to the trust boundary between *sessions*.**
   reshirt: a comment saying `// private` is not encryption. Mine: a prototype that *runs* is not a
   prototype that is *safe to deploy* — "it works in the sandbox" is a claim, and the artifact that
   settles it is where the fetch executes and where the key lives. The donor/reviewer split is the
   substrate mechanism that gets a second set of eyes onto that artifact **before** the claim ships.

---

## What these two cases share

Both are about keeping the fluent, plausible component away from the thing that must be exact — in Case
1 the *number*, in Case 2 the *credential and the deploy boundary* — and in both the safety came from a
**deterministic, durable artifact** rather than from any agent's confidence: the typed cents-arithmetic
and the PostGIS query in Case 1; the server-side proxy with the key in `process.env` and the empty
client-egress grep in Case 2. The through-line with image_gen's, tipometer's, and reshirt's cases is
exact, and this file adds the view from the **product-app builder's seat**: an application that puts an
LLM in front of real money, real children's data, and a real deploy target survives by treating the
model's every output as a DERIVED claim to be reconciled against a deterministic artifact — the tool
result, the SQL row, the integer cents, the file on the server — **never against the model's own account
of itself.** That reconciliation is Fleet Law 1 wearing an app's clothes, and the donor/reviewer split
that caught the leak is the shared substrate doing for a sibling app what it does for the fleet: putting
a second, differently-situated vantage onto the artifact before the claim is allowed to ship.
