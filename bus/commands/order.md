---
description: Agentic request-delivery — place/claim/deliver/accept/reject a durable ORDER (verified landing)
---

A durable **order** with a verified-landing lifecycle (image_gen's spec). Unlike a freeform
`svc-*` job, an order is a persistent object: "delivered" is a *verified fact* (the service reads
the files back before it can say DELIVERED), and **acceptance is the requester's, not the
service's** — a producer cannot grade its own delivery.

```bash
~/.claude/bin/bus.sh order $ARGUMENTS
```

Lifecycle — `PLACED → CLAIMED → (COOKING) → DELIVERED → CONFIRMED/CLOSED`, with `REJECTED → COOKING`:

- **Requester** places, then later accepts or rejects:
  `/order place tipo-btns to:image_gen path:/home/kyle/…/antique files:btn.png,btn-down.png format:'512 RGBA' accept:'reads cast-in'`
  `/order accept tipo-btns` · `/order reject tipo-btns still reads pasted, not cast-in`
- **Service** claims, cooks, then delivers (which VERIFIES the files landed — it refuses if they haven't):
  `/order claim tipo-btns eta:8m` · `/order deliver tipo-btns`
- Anyone: `/order status <id>` · `/order list`

You own the **address** (where) and the **acceptance test** (how you'll judge it) — the service
delivers to a contract it did not write. A reject bumps the revision and keeps its reason on the
order, so a crash-relaunched service won't repeat a rejected attempt.
