---
description: Reserve a shared resource (the GPU, the IQ9 EVK, …) with a soft or hard hold
argument-hint: "<resource> <duration 30m|2h> <soft|hard> [\"job\"]"
---

Reserve a shared resource so sessions self-coordinate access. **Resource** is a
short name like `gpu` or `iq9-evk`. **Choose the mode honestly:**

- **soft** — *"I have it + code/board set up, but I'll drop it if you need it."* Preemptible.
- **hard** — *"mine until my job's done or the user stops me."* Not preemptible; others queue.

```bash
~/.claude/bin/bus.sh res reserve $ARGUMENTS
```

If it reports the resource is **HELD**, do NOT start using it — `/res-request` it or wait.
If **reserved**, tell the user the resource + mode + duration. For a non-GPU resource
(no hardware idle-detection), run `/keep <resource> <dur>` periodically while you're
actively using it — that's the heartbeat the idle-watchdog watches. `/release <resource>` when done.
