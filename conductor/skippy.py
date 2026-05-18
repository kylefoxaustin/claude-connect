"""Skippy adapter — placeholder tiles for the Mixtral + ChromaDB stack.

Stubbed per §12.3: returns a fixed set of placeholder tiles when enabled. Real
detection (process patterns / pidfiles / service registry) goes here later.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from .models import SkippyTile, Status


class SkippyAdapter:
    def __init__(self, *, enabled: bool):
        self.enabled = enabled
        self._started_at = time.time()

    def tiles(self) -> Iterable[SkippyTile]:
        if not self.enabled:
            return ()
        # Two synthetic tiles so the UI has something to render and style.
        return (
            SkippyTile(
                component_id="skippy-mixtral",
                label="Mixtral",
                status=Status.WAITING,
                detail="placeholder — not yet detecting real process",
            ),
            SkippyTile(
                component_id="skippy-chroma",
                label="ChromaDB",
                status=Status.IDLE,
                detail="placeholder — not yet detecting real process",
            ),
        )
