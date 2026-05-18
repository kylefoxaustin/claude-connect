"""ActivityWatcher — inotify on session jsonl files; pushes mtime/preview updates.

Watches every directory under ~/.claude/projects/ that the SessionScanner currently
knows about. On modify/create events, recomputes the preview snippet and notifies
subscribers via an asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .scanner import extract_preview

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "ActivityWatcher", loop: asyncio.AbstractEventLoop):
        self._watcher = watcher
        self._loop = loop

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix != ".jsonl":
            return
        # Hop the event onto the asyncio loop; watchdog calls us from a worker thread.
        self._loop.call_soon_threadsafe(self._watcher._on_jsonl_change, path)

    on_created = on_modified


class ActivityWatcher:
    """Maintains an inotify subscription on a dynamic set of project directories."""

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._watched_dirs: dict[str, object] = {}  # path -> ObservedWatch
        self._queue: asyncio.Queue[tuple[Path, str]] = asyncio.Queue(maxsize=512)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._observer = Observer()
        self._observer.daemon = True
        self._observer.start()

    async def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        self._watched_dirs.clear()

    def sync_watched_dirs(self, dirs: Iterable[Path]) -> None:
        """Add/remove watches so the observer matches the given set of project dirs."""
        if self._observer is None or self._loop is None:
            return
        wanted = {str(d) for d in dirs if d.is_dir()}
        current = set(self._watched_dirs)

        for path_str in wanted - current:
            try:
                handle = self._observer.schedule(
                    _Handler(self, self._loop), path_str, recursive=False
                )
                self._watched_dirs[path_str] = handle
            except (OSError, FileNotFoundError) as e:
                log.debug("watch %s failed: %s", path_str, e)

        for path_str in current - wanted:
            handle = self._watched_dirs.pop(path_str, None)
            if handle is not None:
                try:
                    self._observer.unschedule(handle)
                except KeyError:
                    pass

    async def events(self) -> "asyncio.Queue[tuple[Path, str]]":
        return self._queue

    def _on_jsonl_change(self, path: Path) -> None:
        try:
            preview = extract_preview(path)
        except OSError:
            preview = ""
        try:
            self._queue.put_nowait((path, preview))
        except asyncio.QueueFull:
            # Drop oldest.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((path, preview))
            except asyncio.QueueEmpty:
                pass
