"""Settings loader. Reads ./settings.toml if present, else uses defaults."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover — exercised only on 3.10
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class ScannerSettings:
    interval_seconds: float = 3.0
    claude_home: str = "~/.claude"

    @property
    def claude_home_path(self) -> Path:
        return Path(os.path.expanduser(self.claude_home))


@dataclass
class BusSettings:
    adapter: str = "markdown"  # "markdown" | "jsonl" | "fake"
    markdown_path: str = "~/Documents/claude-bus/messages.md"
    state_dir: str = "~/.claude/bus-state"
    script_path: str = "~/.claude/bin/bus.sh"
    jsonl_path: str = "~/.skippy/bus.jsonl"
    idle_seconds: float = 30.0

    @property
    def markdown_path_resolved(self) -> Path:
        return Path(os.path.expanduser(self.markdown_path))

    @property
    def state_dir_resolved(self) -> Path:
        return Path(os.path.expanduser(self.state_dir))

    @property
    def script_path_resolved(self) -> Path:
        return Path(os.path.expanduser(self.script_path))

    @property
    def jsonl_path_resolved(self) -> Path:
        return Path(os.path.expanduser(self.jsonl_path))


@dataclass
class SkippySettings:
    enabled: bool = False


@dataclass
class UISettings:
    end_fadeout_seconds: float = 30.0


@dataclass
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    bus: BusSettings = field(default_factory=BusSettings)
    skippy: SkippySettings = field(default_factory=SkippySettings)
    ui: UISettings = field(default_factory=UISettings)


def load_settings(path: Path | str | None = None) -> Settings:
    candidate = Path(path) if path else Path("settings.toml")
    if not candidate.exists():
        return Settings()
    with candidate.open("rb") as f:
        data = tomllib.load(f)
    return Settings(
        server=ServerSettings(**data.get("server", {})),
        scanner=ScannerSettings(**data.get("scanner", {})),
        bus=BusSettings(**data.get("bus", {})),
        skippy=SkippySettings(**data.get("skippy", {})),
        ui=UISettings(**data.get("ui", {})),
    )
