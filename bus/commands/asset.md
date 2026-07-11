---
description: Fleet registry: look up how to use a shared board/GPU/service, or write its card
---

The fleet registry — every shared asset (dev board, the GPU, a service Claude) has a
**card** describing what it is, how to reach it, and the traps that cost someone a day.

```bash
~/.claude/bin/bus.sh asset $ARGUMENTS
```

Usage:
- `/asset list` — the whole fleet directory
- `/asset info <name>` — the full card (how to access it, setup, gotchas)
- `/asset new <name> [board|gpu|service]` — register something new
- `/asset path <name>` — the card's file path, so you can EDIT it with your normal tools

**If you learn something painful about a board — write it into the card's `## gotchas`.**
That is the whole point: knowledge that lives in one session's context dies there.
Cards are local (`~/.claude/bus-state/registry/`). Never inline passwords — say where
the credential lives.
