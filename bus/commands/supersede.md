---
description: Replace an instruction you sent another session with a corrected one
argument-hint: "<to-tag> \"<ignore X, do Y instead>\""
---
Like /retract, but for a CORRECTION — you're replacing a prior instruction, not just
cancelling it. Posts a loud 🛑 CORRECTION addressed to the recipient and wakes their
session immediately (even mid-task) so they act on the new version, not the old.
```bash
~/.claude/bin/bus.sh supersede $ARGUMENTS
```
Example: `/supersede docs "ignore the fp8 path, use the calibrated int8 one"`.
