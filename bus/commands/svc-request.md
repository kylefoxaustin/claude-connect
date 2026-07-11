---
description: Ask a service Claude (e.g. image_gen) to do a job — you are NOT blocked; you'll be woken when it's done
---

Queue a job with a service session. **Fire-and-forget**: you carry straight on with your own
work, and directed-mail auto-delivery will wake you when the result comes back.

```bash
~/.claude/bin/bus.sh svc request $ARGUMENTS
```

Usage: `/svc-request <service> <what you need>` —
e.g. `/svc-request image_gen a barney the dinosaur picture for AI-detection work`.

Do NOT sit and wait for it. Tell the user your queue position and get back to what you were doing.
