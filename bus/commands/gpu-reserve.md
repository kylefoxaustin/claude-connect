---
description: Reserve the shared GPU (soft = I'll yield if asked; hard = mine until my job is done)
argument-hint: "<duration 30m|2h> <soft|hard> [\"job description\"]"
---

Reserve the shared GPU for a duration. **Choose the mode honestly** — this is how sessions self-coordinate:

- **soft** — *"I have the GPU with code/models loaded, but I'll drop it if another session needs it."* Use when your work can pause and resume.
- **hard** — *"Mine until my job finishes or the user tells me to stop."* Use only when an interruption would lose real work (a long training/export run).

Run it, passing the arguments through as-is (avoid backticks in the job text — they get shell-evaluated):

```bash
~/.claude/bin/bus.sh gpu reserve $ARGUMENTS
```

- If it says the GPU is **already HELD** by someone else, do **NOT** start using the GPU — either `/gpu-request` it or wait.
- If **reserved**, tell the user the mode + duration, then use the GPU. When finished, `/gpu-release` it (or `/gpu-keep <duration>` to extend before it expires).
