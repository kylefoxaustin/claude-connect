"""Asset cards — the 'how to access / set up / gotchas' notes that travel with each resource.

The fleet registry (``~/.claude/bus-state/registry/<name>.md``, written by ``bus.sh asset``)
holds one markdown card per asset: a header (``kind:``, ``summary:`` …) then ``##`` sections —
``access`` (usernames / hosts / ssh commands / key PATHS — credentials are *referenced*, not
inlined), ``setup``, ``gotchas``, ``docs``, ``contact``, ``open questions``. Conductor reads a
card so the dashboard can show 'how do I reach this EVK?' next to the live lease.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# The order we prefer to present sections in — access first (the thing you came for).
_PREFERRED = ["access", "setup", "gotchas", "docs", "contact", "open questions"]


def _header(text: str, key: str) -> str | None:
    m = re.search(rf'^{re.escape(key)}:\s*(.+)$', text, re.M)
    return m.group(1).strip() if m else None


def read_card(registry_root: Path, name: str) -> dict[str, Any] | None:
    """Parse ``registry/<name>.md`` into ``{name, kind, summary, visibility, sections[]}`` —
    or None if there's no card. ``sections`` is an ordered list of ``{key, title, body}`` with
    ``access`` first. ``visibility`` is the card's optional ``visibility:`` header (e.g.
    ``hidden``) — the hook for the future 'keep access hidden' option; the reader just surfaces
    it, it never redacts here."""
    f = registry_root / f"{name}.md"
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    raw: dict[str, str] = {}
    order: list[str] = []
    cur: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        hm = re.match(r'^##\s+(.+?)\s*$', line)
        if hm:
            if cur is not None:
                raw[cur] = "\n".join(buf).strip()
            cur = hm.group(1).strip()
            order.append(cur)
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        raw[cur] = "\n".join(buf).strip()

    # Present access first, then the rest of the preferred order, then anything else as authored.
    keys = list(order)
    def _rank(title: str) -> tuple[int, int]:
        low = title.strip().lower()
        return (_PREFERRED.index(low), 0) if low in _PREFERRED else (len(_PREFERRED), keys.index(title))
    sections = [
        {"key": t.strip().lower(), "title": t, "body": raw[t]}
        for t in sorted(keys, key=_rank)
        if raw.get(t)          # skip empty sections
    ]
    return {
        "name": name,
        "kind": _header(text, "kind"),
        "summary": _header(text, "summary"),
        "visibility": (_header(text, "visibility") or "").lower() or None,
        "sections": sections,
        "has_access": any(s["key"] == "access" for s in sections),
    }


def attach_cards(resources: list[dict[str, Any]], registry_root: Path) -> None:
    """In-place: give each resource entry a ``card`` (the parsed card, or None)."""
    for r in resources:
        r["card"] = read_card(registry_root, r.get("name", ""))
