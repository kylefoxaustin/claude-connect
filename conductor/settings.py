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
    jsonl_path: str = "~/.claude/bus.jsonl"
    idle_seconds: float = 30.0
    # Optional pretty-tag mapping: directory path -> bare tag name (e.g.
    # "~/code/my-api" = "api"). Mirrors the case-table in your bus.sh so
    # Conductor labels tiles with the same tag the bus uses. Anything not
    # listed falls back to [other:<dirname>]. Lives in settings.toml (local,
    # gitignored) so the repo ships no project-specific names.
    tags: dict[str, str] = field(default_factory=dict)

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
class UISettings:
    end_fadeout_seconds: float = 30.0


@dataclass
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    bus: BusSettings = field(default_factory=BusSettings)
    ui: UISettings = field(default_factory=UISettings)


DEFAULT_SETTINGS_PATH = Path("settings.toml")


def load_settings(path: Path | str | None = None) -> Settings:
    candidate = Path(path) if path else DEFAULT_SETTINGS_PATH
    if not candidate.exists():
        return Settings()
    with candidate.open("rb") as f:
        data = tomllib.load(f)
    return Settings(
        server=ServerSettings(**data.get("server", {})),
        scanner=ScannerSettings(**data.get("scanner", {})),
        bus=BusSettings(**data.get("bus", {})),
        ui=UISettings(**data.get("ui", {})),
    )


def _toml_scalar(v: object) -> str:
    # bool must precede int — bool is an int subclass.
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dump_settings(settings: Settings, path: Path | str | None = None) -> None:
    """Serialize settings back to TOML (Py 3.10 has no stdlib writer). Writes the
    full known structure, so the UI becomes the editor of record for settings.toml."""
    candidate = Path(path) if path else DEFAULT_SETTINGS_PATH
    sections: dict[str, dict[str, object]] = {
        "server": {"host": settings.server.host, "port": settings.server.port},
        "scanner": {
            "interval_seconds": settings.scanner.interval_seconds,
            "claude_home": settings.scanner.claude_home,
        },
        "bus": {
            "adapter": settings.bus.adapter,
            "markdown_path": settings.bus.markdown_path,
            "state_dir": settings.bus.state_dir,
            "script_path": settings.bus.script_path,
            "jsonl_path": settings.bus.jsonl_path,
            "idle_seconds": settings.bus.idle_seconds,
        },
        "ui": {"end_fadeout_seconds": settings.ui.end_fadeout_seconds},
    }
    out: list[str] = []
    for section, kv in sections.items():
        out.append(f"[{section}]")
        for k, v in kv.items():
            out.append(f"{k} = {_toml_scalar(v)}")
        out.append("")
        # The pretty-tag map is a sub-table of [bus]; emit it right after the
        # bus scalars so a UI-driven save round-trips it instead of dropping it.
        if section == "bus" and settings.bus.tags:
            out.append("[bus.tags]")
            for path, tag in settings.bus.tags.items():
                out.append(f"{_toml_scalar(path)} = {_toml_scalar(tag)}")
            out.append("")
    candidate.write_text("\n".join(out).rstrip() + "\n")
