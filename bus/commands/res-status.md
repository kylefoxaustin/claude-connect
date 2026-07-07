---
description: Show shared-resource reservations — all of them, or one by name
argument-hint: "[resource]"
---
Show the current shared-resource reservations. **Read-only** — sends no message. Omit the
name to see every resource; pass one (e.g. `iq9-evk`) for just that resource.
```bash
~/.claude/bin/bus.sh res status $ARGUMENTS
```
Report to the user. Respect held resources: a `hard` hold is theirs until they finish; a
`soft` hold can be `/res-request`ed.
