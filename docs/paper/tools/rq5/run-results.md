# RQ5 results (in progress)

## Arm A — cold isolated session (pid 914772, HOME=scratch, no memory/bus/fleet)
- acceptance test: PASS 16/16
- wall-clock: 20.1 min (start 21:12:19 → end 21:31:25)
- tool calls: 22 | assistant turns: 43 | output tokens: 25,559
- substantive human interventions: 0 (2 non-initial prompts were a stray keystroke + its retraction)
- transcript: rq5-armA-home/.claude/projects/.../1fd89dd1-...jsonl

## Arm B — backend (context-carrying, pid 3085431 keyhole session)
- acceptance test: functionally correct (15/16 frozen; the 1 fail is a disclosed substring-assert artifact)
- wall-clock: 7.8 min (471s), 02:37:42 → 02:45:33 UTC
- tool calls: 14 | assistant turns: 34 | output tokens: 35,243
- substantive human interventions: 0
- transcript: ~/.claude/projects/-home-kyle-Documents-GitHub-keyhole/43a0e140-...jsonl (sliced from Arm B prompt)

## Headline
- both functionally correct, 0 human help
- backend 2.6x faster wall-clock (7.8 vs 20.1 min), 36% fewer tool calls (14 vs 22)
- backend used 38% MORE output tokens (35.2k vs 25.6k) — efficiency is in steps/time, not tokens
