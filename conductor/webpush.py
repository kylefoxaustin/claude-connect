"""Web Push — the app that finds you, instead of the app you remember to check.

NAMING: ``webpush``, not ``push``. In this codebase "push" already means *a gated ``git
push`` awaiting Kyle's approval*. Two unrelated meanings of the same word, one of them a
security control — collapsing them would produce a genuinely dangerous confusion someday.

WHAT WE NOTIFY ABOUT, and what we refuse to.

Google's SRE page test — *actionable, needs a human, novel, urgent* — plus the thing this
fleet has learned the hard way: an alarm that fires on a healthy system is one you learn to
ignore, and then it isn't believed on the night it matters.

  * **NOTIFY** — a Claude is blocked on a QUESTION, or on a git-push approval. A human is
    the only unblocker. These are the two things that stop work dead.
  * **NEVER** — idle leases, queue depth, orphaned resources, mutual stalls, unread mail.
    They resolve themselves or they wait. **If the fix is robotic, it is not a page.**

A HARD LIMIT, stated plainly: **a PWA cannot break through Do Not Disturb.** That is a
web-platform limit, not something we can engineer around — every on-call vendor ships
native code for it. So this can reach Kyle when he is awake and available; it will never
wake him at 3am. That is an accepted tradeoff: a push approval can wait until morning, and
the agent simply retries.

AND: **the notification is never the only door.** Everything it tells you about is also
sitting in the ``/m`` inbox, browsable, forever. GitHub Mobile's gated-deploy approval is
reachable *only* from a notification, and that bug has been open for two years. We are not
repeating it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("conductor.webpush")

_SUBS = "webpush-subs.json"
_KEYS = "webpush-vapid.json"

# Re-notify about the same still-unanswered item at most this often. A question Kyle
# hasn't answered in an hour is worth one more nudge; it is not worth one every scan tick.
RENOTIFY_AFTER_S = 3600.0


# --- VAPID identity ---------------------------------------------------------
def load_or_create_keys(coord_root: Path) -> dict[str, str]:
    """The VAPID keypair identifying this Conductor to the push services.

    Generated once and kept on disk: the PUBLIC key is baked into every subscription a
    browser creates, so rotating it silently invalidates every existing subscription —
    the phone would keep "working" and simply never ring again.
    """
    path = coord_root / _KEYS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("private") and data.get("public"):
            return data
    except (OSError, ValueError):
        pass

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid01

    v = Vapid01()
    v.generate_keys()
    # The browser wants the raw uncompressed P-256 point, base64url, unpadded — that is
    # what `applicationServerKey` is. A PEM here silently produces a subscription that
    # every push then fails to authenticate against.
    raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    data = {
        "private": v.private_pem().decode("utf-8"),
        "public": _b64(raw),
    }
    coord_root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    os.chmod(path, 0o600)          # it's a private key
    log.info("generated a new VAPID keypair")
    return data


def _b64(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# --- subscriptions ----------------------------------------------------------
def read_subs(coord_root: Path) -> list[dict[str, Any]]:
    try:
        subs = json.loads((coord_root / _SUBS).read_text(encoding="utf-8"))
        return [s for s in subs if isinstance(s, dict) and s.get("endpoint")]
    except (OSError, ValueError):
        return []


def write_subs(coord_root: Path, subs: list[dict[str, Any]]) -> None:
    coord_root.mkdir(parents=True, exist_ok=True)
    path = coord_root / _SUBS
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(subs), encoding="utf-8")
    os.replace(tmp, path)


def add_sub(coord_root: Path, sub: dict[str, Any]) -> list[dict[str, Any]]:
    """Register a device. Keyed on endpoint, so re-subscribing the same phone (which
    browsers do on their own schedule) replaces rather than duplicates — otherwise one
    device would ring three times."""
    subs = [s for s in read_subs(coord_root) if s.get("endpoint") != sub.get("endpoint")]
    subs.append(sub)
    write_subs(coord_root, subs)
    return subs


def drop_sub(coord_root: Path, endpoint: str) -> None:
    write_subs(coord_root, [s for s in read_subs(coord_root) if s.get("endpoint") != endpoint])


# --- what is worth interrupting a human for ---------------------------------
def notifiable(decisions: list[dict[str, Any]],
               push_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The only two things that page. Each carries a stable ``key`` so we can tell "still
    unanswered" from "new" — the difference between a reminder and a nag."""
    out: list[dict[str, Any]] = []
    for d in decisions:
        q = (d.get("questions") or [{}])[0]
        who = Path(d.get("cwd", "")).name or "a session"
        out.append({
            "key": f"decision:{d['session_id']}",
            "title": f"❓ {who} needs a decision",
            "body": (q.get("question") or "")[:140],
            "url": "/m?pane=inbox",
            "tag": "decision",
        })
    for p in push_requests:
        out.append({
            "key": f"push:{p['key']}",
            "title": f"🔐 {p.get('repo_name') or 'a repo'} wants to push",
            "body": (p.get("cmd") or "git push")[:140],
            "url": "/m?pane=inbox",
            "tag": "gitpush",
        })
    return out


def due(items: list[dict[str, Any]], sent: dict[str, float],
        *, now: float | None = None) -> list[dict[str, Any]]:
    """Which of ``items`` to actually send: ones never sent, or last sent long enough ago
    that a second nudge is a reminder rather than a nag."""
    now = time.time() if now is None else now
    out = []
    for i in items:
        last = sent.get(i["key"])
        # "Never sent" is its own case, not `last = 0`. Defaulting to 0 and subtracting
        # only works because time.time() happens to be a big number — which is a fact about
        # the clock, not about the logic, and it is exactly the kind of accidental
        # correctness that breaks the first time someone passes a different `now`.
        if last is None or now - last >= RENOTIFY_AFTER_S:
            out.append(i)
    return out


def prune_sent(sent: dict[str, float], items: list[dict[str, Any]]) -> dict[str, float]:
    """Forget items that are no longer pending, so the same question asked again later
    rings immediately instead of being suppressed by a stale timestamp."""
    live = {i["key"] for i in items}
    return {k: v for k, v in sent.items() if k in live}


# --- delivery ---------------------------------------------------------------
def send_one(sub: dict[str, Any], payload: dict[str, Any], keys: dict[str, str],
             subject: str) -> bool | None:
    """Deliver to one device.

    Returns True on success, False on a transient failure, and **None when the
    subscription is dead** (410 Gone / 404) — the caller must then drop it, or a phone that
    was reinstalled once will generate a failing request forever.
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=keys["private"],
            vapid_claims={"sub": subject},
            timeout=10,
        )
        return True
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        if code in (404, 410):
            log.info("push subscription is gone (%s) — dropping it", code)
            return None
        log.warning("push failed (%s): %s", code, e)
        return False
    except Exception:
        log.exception("push failed")
        return False
