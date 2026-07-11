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
    # Shared secret required on every /api/* request and the /ws handshake.
    # Empty (the default) = no auth, safe for the localhost-only default. Set it
    # (here or via $CONDUCTOR_AUTH_TOKEN) before exposing Conductor beyond the box
    # (e.g. a phone over Tailscale). See conductor/auth.py.
    auth_token: str = ""


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
    # A resource lease whose owner has had no live session for this long is
    # surfaced as an orphan suspect (never auto-reclaimed — a session can be
    # closed and relaunched; the user decides). Matches RES_ORPHAN_GRACE_MIN.
    orphan_flag_seconds: float = 600.0
    # Auto-delivery: wake an idle session that has a message addressed to it
    # (to:<tag>) it hasn't read, so Kyle doesn't have to prod it to check the bus.
    autodeliver: bool = True
    # Tags that auto-delivery must NEVER wake — typically the operator's own
    # console / dev session (the one you're actively typing in), which shouldn't
    # be auto-prodded to go read the bus while you're working in it. Bracketed
    # tags as shown on the tile, e.g. ["[other:claude-connect]"].
    autodeliver_exempt: list[str] = field(default_factory=list)
    # Sender tag stamped on messages you compose from the dashboard, so they're
    # distinguishable from any session (e.g. "operator" -> "[operator]").
    sender_tag: str = "operator"
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
class RelaunchSettings:
    """Click-to-relaunch a parked (dormant) session from the dock.

    Spawns ``claude-tracked <name> --dir <cwd> --continue``. By default that's
    all — a clean resume. Optionally, once the new session appears and settles,
    it injects keystrokes: ``/rc`` (Claude Code's ``/remote-control``, so the
    session is drivable from a browser/phone — off by default) when ``rc`` is on,
    and ``/rename <name>`` when ``rename`` is on (usually unneeded since
    ``--continue`` keeps the prior name). With both off, nothing is typed. The
    settle/gap knobs cover the flaky part: keystrokes only land once Claude's TUI
    is up at a prompt.
    """
    rc: bool = False                   # inject `/rc` (Claude Code remote-control) on relaunch
    rename: bool = False               # also inject `/rename <name>` after `/rc`
    appear_timeout_seconds: float = 40.0   # how long to wait for the new session
    settle_seconds: float = 2.5            # TUI draw delay before first keystroke
    between_seconds: float = 1.0           # gap between injected keystrokes
    # Batch ("relaunch selected") pacing: after each session comes up, pause before
    # starting the next. Launching 20 Claudes at once would stampede the box — and
    # a resuming session may auto-compact its transcript, which is heavy.
    batch_gap_seconds: float = 3.0


@dataclass
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    bus: BusSettings = field(default_factory=BusSettings)
    ui: UISettings = field(default_factory=UISettings)
    relaunch: RelaunchSettings = field(default_factory=RelaunchSettings)


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
        relaunch=RelaunchSettings(**data.get("relaunch", {})),
    )


def _toml_scalar(v: object) -> str:
    # A list of scalars (e.g. autodeliver_exempt) -> a TOML array.
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(x) for x in v) + "]"
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
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
            "auth_token": settings.server.auth_token,
        },
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
            "sender_tag": settings.bus.sender_tag,
            # Persisted so a UI settings-save (which rewrites the whole file)
            # doesn't drop them.
            "autodeliver": settings.bus.autodeliver,
            "autodeliver_exempt": settings.bus.autodeliver_exempt,
        },
        "ui": {"end_fadeout_seconds": settings.ui.end_fadeout_seconds},
        "relaunch": {
            "rc": settings.relaunch.rc,
            "rename": settings.relaunch.rename,
            "appear_timeout_seconds": settings.relaunch.appear_timeout_seconds,
            "settle_seconds": settings.relaunch.settle_seconds,
            "between_seconds": settings.relaunch.between_seconds,
        },
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
