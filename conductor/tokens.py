"""Per-session token accounting from the session transcripts.

Every assistant turn in ``~/.claude/projects/<proj>/<session>.jsonl`` records a
``usage`` block (``input_tokens`` / ``cache_creation_input_tokens`` /
``cache_read_input_tokens`` / ``output_tokens``) — the same numbers Claude Code
shows per command. We tally them per session for the tile's token badge.

Transcripts are append-only, so this is *incremental*: each poll seeks past the
bytes already counted and only parses what's new (advancing only over complete
lines, so a half-written trailing record isn't lost or double-counted). Repeated
calls on an unchanged file are effectively free.

Each reply is counted ONCE, by ``message.id``: Claude Code writes one line per content block and
repeats the reply's usage on every one. Until 2026-10-29 this summed lines, which over-counted a
session's output ~2.4x (see ``token_history.py`` for the measurement).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .token_history import _KEYS, ReplyDedup, usage_records


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
            st = {"offset": 0, "sums": {k: 0 for k in _KEYS}, "turns": 0, "dedup": ReplyDedup()}
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
                dedup = st["dedup"]
                for mid, _ts, _cwd, u in usage_records(complete):
                    d = dedup.delta(mid, u)
                    if d is None:
                        continue                  # the same reply, written again per content block
                    if d is u:
                        st["turns"] += 1
                    for k in _KEYS:
                        st["sums"][k] += d[k]

        st["result"] = _summary(st["sums"], st["turns"])
        return st["result"]
