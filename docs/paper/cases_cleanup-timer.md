# Case study: the substrate caught a silent timer deleting its own memory

*Specimen for the `ieee-paper` project, written by the lead (`claude-connect`) from a direct
investigation, corroborated by independent fleet measurements (`band`, `jaws`, `llm-svc`).
Provenance per Fleet Law: **MEASURED** = counted from the filesystem/settings this session;
**RECALLED** = faithful account; **GAP** = not captured. This is a live specimen for RQ2 (a failure
mode closed), RQ3 (bystander/vantage detection), and the disaster-recovery layer's value.*

## What happened

While the fleet was mining `~/.claude/projects/<slug>/*.jsonl` transcripts to source the paper's own
RQ1/RQ4 metrics, multiple sessions independently hit a **30-day horizon**: no transcript older than
~30 days existed, on *any* project. The cause: **Claude Code's `cleanupPeriodDays` setting was unset,
so it ran its 30-day default — a background sweep that deletes idle session transcripts.** It had
*already destroyed data*: the earliest ~3 weeks of a ~2.4-month deployment were gone from the live
store.

## The evidence (MEASURED)

- `~/.claude/settings.json` had **no `cleanupPeriodDays` key** → 30-day default (verified by the lead).
- **Oldest surviving conversation transcript: 2026-06-27** — 29 days old at discovery — across **62
  project directories**; nothing older, for any project (`band`, independently).
- `~/.claude/.last-cleanup` = **2026-07-26T14:10:32Z** — the sweep **ran that day** and runs ~daily
  (`band`).
- Deployment began 2026-05-18; the May transcripts are absent from the live store.

## The detection — RQ3 as VANTAGE, not authorship

No one was auditing the platform. The timer surfaced as a **side effect of the fleet reading its own
transcripts** for the paper — a bystander catch in the strict sense: the finding fell out of *running
a different task*, from sessions that had no stake in the cleanup code (which is Anthropic's, not
ours). It is the RQ3 pattern at platform scope: **a defect invisible to anyone reasoning about the
system, exposed only by a peer living in it and hitting its edge.**

## The mitigation — and the DR layer exceeding its design intent

Two things were true at discovery, and their conjunction is the point:

1. **The disaster-recovery transcript backup — built in v2.37 for an entirely different threat (rebuild
   the fleet on a *new machine*) — had already been mitigating this one.** The daily
   `backup-transcripts.timer` had uploaded `fleet-transcripts.tar.zst` (**310 MB, updated the morning
   of discovery**, MEASURED) to the `fleet-backup` release. Every idle transcript was being captured
   daily *before* the sweep could remove it. Resilience engineered for "new PC" incidentally covered
   "silent local deletion." **A durable off-box copy is a general safety property, not a
   single-scenario one.**
2. **The permanent fix was one line:** set `cleanupPeriodDays: 3650` (≈10-year retention), disabling
   the sweep. Applied and verified same day.

**Residual loss (honest):** transcripts deleted *before* the daily backup existed (~2026-07-22) are
unrecoverable from both live and backup. Everything after is safe in both.

## Principles this specimen proves

- **A silent background process that deletes real data is the canonical silent-loss failure the whole
  system is paranoid about — and it was found only because the substrate observes itself.** A fleet
  whose members read the shared record will trip over threats to that record that no single session,
  and no external audit, was looking for.
- **A durable, off-box copy generalizes beyond the scenario it was built for.** The DR layer's value
  was under-stated by its own design doc.
- **`~/.claude/history.jsonl` is the durable human-prompt record.** It is global, append-only, and
  **not swept** — 6,250 entries back to 2026-01-14 (`band`), versus the transcripts' 30-day horizon.
  It records *only* human prompts, so a human-touch count taken from it is **immune by construction**
  to the transcript mining trap below. (It carries no turns/tokens/tool-calls — those need the
  transcripts.) This reshapes the RQ1 instrument: count human touches from `history.jsonl`, not from
  a transcript scan.

## Method note this incident forced (folds into RQ1 mining)

`jaws` flagged a trap that would have inflated RQ1 by an order of magnitude: in a transcript,
`type == "user"` records are mostly **tool results**, not human turns. In one measured build, 83
`user` records reconciled to **73 tool-results + 2 task-notifications + 1 meta + only 7 HUMAN** — an
**11.9× overcount** if unfiltered. Any human-touch metric must filter `tool_result` (or use
`history.jsonl`, which cannot contain them). Recorded here so the paper's RQ1 numbers are computed on
the corrected basis, not the naive one.
