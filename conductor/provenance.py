"""Attestation ledger — "was Kyle at the keyboard, or did Conductor type that?"

Kyle: *"I didn't type that /msg-check."* He was right. Conductor typed it, and it arrived in
the session's transcript **as a user turn**. Neither he nor the Claude could tell the
difference — the Claude then reported back to him as though he had asked.

There is no way to fix that from inside the channel. image_gen's spec, and it is correct:

    You cannot authenticate a sender from inside the channel the sender controls.

A self-applied marker (`/msg-check --auto`, an `[injected]` prefix) is worthless: the marker
would be typed **by the very thing you are trying to distinguish**, which can equally type it
or omit it. A convention, not a credential.

So: a ledger, written **before** the keystrokes, consumed by a `UserPromptSubmit` hook that
independently resolves its own `claude` pid. **Neither side trusts the other's label — the PID
is the join key.**

TWO THINGS THIS IS NOT, AND BOTH MATTER:

* **It is ATTESTATION, not AUTHENTICATION.** Conductor self-declares; a hostile injector
  simply wouldn't write the line. That is fine — **the threat model is AMBIGUITY, not an
  adversary.**
* **It is ADVISORY, never AUTHORITY.** It may change what a Claude *says* and whether it
  *blocks*. It may **never** change what a Claude is *permitted* to do. image_gen's warning,
  which is my own Q1 finding pointed back at me: *"a provenance label that confers authority is
  just the I-accept-the-risk checkbox with better branding."* Permission stays with the harness
  and with durable, consumable grants — the words in a terminal authorize nothing.

WHY IT IS A QUEUE AND NOT A TIMESTAMP WINDOW — the detail that would have broken the naive
version, and my own code is the witness:

    Conductor typed at        13:39:43
    It reached the transcript  ~13:46-13:53      <- SIX TO THIRTEEN MINUTES LATER

Because **a busy Claude Code session QUEUES injected keystrokes** rather than dropping them
(the same fact behind the /msg-check storm). **There is no bounded delay between injection and
arrival.** A ±5s window would have failed on the very event it was built to explain — and
failed *silently, in the direction that credits Kyle with Conductor's keystrokes*. So entries
are consumed on match, and time is used only for garbage collection.

AND WHY IT LIVES IN ITS OWN FILE, NOT THE APP LOG:

image_gen tried to audit this with `grep` on `conductor.log` and got **nothing** — the log is
uvicorn stdout with 2,426 NUL bytes in it, so grep classified it as binary and **searched
nothing, returning empty rather than an error.** It read the silence as evidence and told Kyle
he had probably typed something he hadn't.

    **An audit log a text tool cannot parse is a green light with nothing behind it.**

One JSON object per line, NUL-free by construction, never shared with stdout.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("conductor.provenance")

_LEDGER = "injections.jsonl"

# Entries older than this are wreckage: the session died, or the keystrokes went into the void
# (which happens — see the push-notice bug). Reaping them keeps an unconsumed entry from
# attaching itself to an unrelated prompt hours later.
STALE_AFTER_S = 6 * 3600


def ledger_path(state_dir: Path) -> Path:
    return state_dir / _LEDGER


def attest(
    state_dir: Path,
    *,
    target_pid: int | None,
    target_tag: str | None,
    text: str,
    why: str,
    source: str,
    actor: str = "conductor",
) -> None:
    """Record an injection BEFORE it happens.

    Called from the choke point (``_inject_text`` / the decision injector) rather than from
    each call site. image_gen's third question, and it is the right answer: **a sixth injection
    path added next month cannot forget to attest if it cannot inject without passing through
    here. Call-site attestation is the version that rots.**

    Never raises. An attestation failure must not stop a wake — but it is logged, because a
    silent attestation failure would leave a keystroke with no provenance and NOTHING would say
    so, which is the whole disease.
    """
    entry = {
        "ts": time.time(),
        "target_pid": target_pid,
        "target_tag": target_tag,
        # Strip control bytes: this file's ONLY job is to be readable by a text tool six
        # months from now, by someone trying to work out whether a human consented.
        "text": "".join(c for c in (text or "") if c.isprintable() or c in " \t")[:400],
        "why": (why or "")[:200],
        "source": source,
        "actor": actor,          # who drove it — "conductor" (autonomous) or "kyle:<client>"
        "consumed": False,
    }
    try:
        p = ledger_path(state_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("could not write the injection ledger — this keystroke will look "
                      "like Kyle typed it")


def read_ledger(state_dir: Path, *, now: float | None = None) -> list[dict[str, Any]]:
    """Unconsumed, unexpired entries. Malformed lines are skipped, never fatal."""
    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    try:
        text = ledger_path(state_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("consumed"):
            continue
        if now - float(e.get("ts") or 0) > STALE_AFTER_S:
            continue
        out.append(e)
    return out


def prune(state_dir: Path, *, now: float | None = None) -> int:
    """Drop consumed and stale entries. Returns how many were kept."""
    now = time.time() if now is None else now
    keep = read_ledger(state_dir, now=now)
    p = ledger_path(state_dir)
    if not p.exists():
        return 0
    tmp = p.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            for e in keep:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except OSError:
        return len(keep)
    return len(keep)
