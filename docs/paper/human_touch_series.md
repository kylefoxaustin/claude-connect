# Human-touch series (supporting artifact for RQ1 / §V-A)

Human prompts per **active project**, from `~/.claude/history.jsonl` (human prompts only, un-swept
back to 2026-01-14). Normalized by projects active in the bucket. As-of 2026-07-27.

## Monthly (Table 2 in the paper)
| month | human prompts | active projects | prompts / project |
|---|---:|---:|---:|
| 2026-01 | 1 | 1 | 1.0 | *(pre-ramp startup, omitted)* |
| 2026-03 | 7 | 1 | 7.0 | *(pre-ramp startup, omitted)* |
| 2026-04 | 2,027 | 10 | 202.7 | *(substrate build-out month — bootstrap-heavy, omitted)* |
| 2026-05 | 1,117 | 16 | 69.8 |
| 2026-06 | 1,936 | 27 | 71.7 |
| 2026-07 | 1,219 | 34 | 35.9 |

Three monthly buckets cannot establish a trend, and the middle is non-monotonic (June ≈ May); the
paper reports the **shape** (near 70 across May–June, then a drop to 36 in July), not a ratio.

## Weekly (the finer breakdown the paper cites; steady-state, May onward)
| ISO week | human prompts | active projects | prompts / project |
|---|---:|---:|---:|
| 2026-W18 | 51  | 3  | 17.0 |
| 2026-W19 | 311 | 5  | 62.2 |
| 2026-W20 | 189 | 5  | 37.8 |
| 2026-W21 | 373 | 12 | 31.1 |
| 2026-W22 | 193 | 8  | 24.1 |
| 2026-W23 | 706 | 12 | 58.8 |
| 2026-W24 | 517 | 13 | 39.8 |
| 2026-W25 | 327 | 17 | 19.2 |
| 2026-W26 | 297 | 17 | 17.5 |
| 2026-W27 | 351 | 17 | 20.6 |
| 2026-W28 | 371 | 23 | 16.1 |
| 2026-W29 | 270 | 19 | 14.2 |
| 2026-W30 | 295 | 23 | 12.8 |
| 2026-W31 | 21  | 10 | 2.1  | *(partial final week)* |

**Shape:** noisy but a consistent downward drift — from the ~35–40 band in early May (W18–W24, with
spikes) to the ~13–20 band in July (W28–W30), as active projects roughly double. This is why the
paper reads July's monthly drop as a sustained decline rather than a single-month artifact. It remains
observational, with the standard longitudinal confounds (task-mix change, operator learning,
per-active-project as a proxy for per-delivered-project) — a trend, not a controlled measurement.

Reproduce: bin `history.jsonl` records by ISO week of `timestamp`, count prompts and distinct
`project` values per bin.
