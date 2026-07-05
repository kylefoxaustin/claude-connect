"""Per-session token accounting from the session transcripts.

Every assistant turn in ``~/.claude/projects/<proj>/<session>.jsonl`` records a
``usage`` block (``input_tokens`` / ``cache_creation_input_tokens`` /
``cache_read_input_tokens`` / ``output_tokens``) — the same numbers Claude Code
shows per command. We tally them per session for the tile's token badge.

Transcripts are append-only, so this is *incremental*: each poll seeks past the
bytes already counted and only parses what's new (advancing only over complete
lines, so a half-written trailing record isn't lost or double-counted). Repeated
calls on an unchanged file are effectively free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def _summary(sums: dict[str, int], turns: int) -> dict[str, Any]:
    total = sum(sums[k] for k in _KEYS)
    return {
        "turns": turns,
        "output": sums["output_tokens"],
        "input": sums["input_tokens"],
        "cache_creation": sums["cache_creation_input_tokens"],
        "cache_read": sums["cache_read_input_tokens"],
        "total": total,
    }


class TokenAccountant:
    """Incremental per-file token tally, keyed by jsonl path."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def usage_for(self, jsonl_path: str) -> dict[str, Any]:
        st = self._state.get(jsonl_path)
        try:
            size = Path(jsonl_path).stat().st_size
        except OSError:
            return st["result"] if st else _summary({k: 0 for k in _KEYS}, 0)

        # New file, or the file shrank/rotated under the same path -> start over.
        if st is None or size < st["offset"]:
            st = {"offset": 0, "sums": {k: 0 for k in _KEYS}, "turns": 0}
            self._state[jsonl_path] = st

        if size > st["offset"]:
            try:
                with open(jsonl_path, "rb") as fh:
                    fh.seek(st["offset"])
                    chunk = fh.read()
            except OSError:
                chunk = b""
            # Only consume through the last complete line; keep a partial trailing
            # record for the next poll.
            nl = chunk.rfind(b"\n")
            if nl != -1:
                complete, consumed = chunk[: nl + 1], nl + 1
                st["offset"] += consumed
                for line in complete.split(b"\n"):
                    if not line.strip():
                        continue
                    try:
                        o = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    msg = o.get("message") if isinstance(o, dict) else None
                    u = msg.get("usage") if isinstance(msg, dict) else None
                    if not isinstance(u, dict):
                        continue
                    st["turns"] += 1
                    for k in _KEYS:
                        v = u.get(k, 0)
                        if isinstance(v, int):
                            st["sums"][k] += v

        st["result"] = _summary(st["sums"], st["turns"])
        return st["result"]
