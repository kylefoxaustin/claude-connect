---
description: Extend / heartbeat your hold on a shared resource before it expires
argument-hint: "<resource> <duration 30m|1h>"
---
Extend your reservation on a shared resource from now. **This is also the heartbeat**
for non-GPU resources — run it periodically while actively using the resource so the
idle-watchdog knows you're still working (otherwise it may nudge or reclaim your hold).
```bash
~/.claude/bin/bus.sh res keep $ARGUMENTS
```
Confirm the new expiry.
