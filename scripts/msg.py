#!/usr/bin/env python3
"""msgbox — two Claude Code sessions, two machines, one git repository.

The transport is the repo itself: write a file, commit, push; the other side
pulls and reads. No server, no daemon, nothing to keep running.

Written in PYTHON on purpose. lostchild's equivalent is Node because that is
what its machines guarantee; here the guaranteed runtime is Python — Conductor
is a Python app, so any machine that can run it can run this. One dependency
fewer on the Windows box is one fewer thing to install before you can talk.

    python scripts/msg.py                 what is waiting (default)
    python scripts/msg.py whoami NAME     set this clone's identity (do NOT use echo >)
    python scripts/msg.py send TO SUBJECT what you want to say...
    python scripts/msg.py read FILE       print one message
    python scripts/msg.py close FILE      move it to done/ once you have acted

⚠️ Use `whoami` rather than a shell redirect. `echo 'x' > msgbox/.whoami` is a
bash idiom; cmd.exe does not treat single quotes as quoting, so the file ends up
containing the quotes and every message you send is signed wrong — in a way
nobody notices until they read a filename.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "msgbox"
OPEN, DONE, WHO = BOX / "open", BOX / "done", BOX / ".whoami"


def _slug(s: str) -> str:
    """A filename fragment that is safe on Windows as well as POSIX."""
    # keep underscores: a session named win_conductor must round-trip, not become
    # win-conductor. "--" is the field separator in the filename, "_" is safe on both platforms.
    s = re.sub(r"[^A-Za-z0-9_]+", "-", s.lower()).strip("-")
    return (s[:60] or "message").rstrip("-")


def _me() -> str:
    if not WHO.exists():
        sys.exit("this clone has no identity yet — run:\n"
                 "    python scripts/msg.py whoami <name>   e.g. skippy-claude, win_conductor")
    name = WHO.read_text(encoding="utf-8").strip().strip("'\"")
    if not name:
        sys.exit("msgbox/.whoami is empty — run: python scripts/msg.py whoami <name>")
    return name


def cmd_whoami(argv: list[str]) -> None:
    if not argv:
        print(_me() if WHO.exists() else "(unset)")
        return
    name = _slug(argv[0])
    BOX.mkdir(exist_ok=True)
    # newline-terminated, no quotes — the whole reason this is a command and not a redirect
    WHO.write_text(name + "\n", encoding="utf-8")
    print(f"this clone is now: {name}")


def cmd_list(_argv: list[str]) -> None:
    OPEN.mkdir(parents=True, exist_ok=True)
    msgs = sorted(OPEN.glob("*.md"))
    if not msgs:
        print("msgbox/open is empty — nothing is waiting.")
        return
    who = WHO.read_text(encoding="utf-8").strip() if WHO.exists() else None
    print(f"{len(msgs)} waiting in msgbox/open:\n")
    for m in msgs:
        # the filename carries who/whom/subject, so ls alone is a useful inbox
        parts = m.stem.split("--")
        frm = next((p[5:] for p in parts if p.startswith("from-")), "?")
        to = next((p[3:] for p in parts if p.startswith("to-")), "?")
        subj = parts[-1].replace("-", " ") if len(parts) > 3 else m.stem
        mine = "  <- YOU" if who and to == who else ""
        print(f"  {m.name}")
        print(f"      from {frm} to {to}: {subj}{mine}\n")
    print("read:  python scripts/msg.py read <file>")
    print("close: python scripts/msg.py close <file>   (only after you have ACTED on it)")


def cmd_send(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit('usage: python scripts/msg.py send <to> "<subject>" <body...>')
    to, subject = _slug(argv[0]), argv[1]
    body = " ".join(argv[2:])
    me = _me()
    ts = datetime.now(timezone.utc)
    name = (f"{ts.strftime('%Y-%m-%dT%H%M%SZ')}--from-{me}--to-{to}--{_slug(subject)}.md")
    OPEN.mkdir(parents=True, exist_ok=True)
    path = OPEN / name
    path.write_text(
        "---\n"
        f"from:   {me}\n"
        f"to:     {to}\n"
        "needs:  agent\n"          # or "human" — an escalation nobody should act on alone
        f"about:  {subject}\n"
        f"opened: {ts.strftime('%Y-%m-%dT%H:%MZ')}\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}\n\nNow commit and push — the push IS the send:")
    print(f"    git add {path.relative_to(ROOT)} && git commit -m 'msgbox: {subject}' && git push")


def _resolve(arg: str) -> Path:
    p = Path(arg)
    for cand in (p, OPEN / p.name, DONE / p.name):
        if cand.is_file():
            return cand
    sys.exit(f"no such message: {arg}")


def cmd_read(argv: list[str]) -> None:
    if not argv:
        sys.exit("usage: python scripts/msg.py read <file>")
    print(_resolve(argv[0]).read_text(encoding="utf-8"))


def cmd_close(argv: list[str]) -> None:
    if not argv:
        sys.exit("usage: python scripts/msg.py close <file>")
    src = _resolve(argv[0])
    if src.parent == DONE:
        print(f"already closed: {src.name}")
        return
    DONE.mkdir(parents=True, exist_ok=True)
    dst = DONE / src.name
    src.rename(dst)
    print(f"closed -> {dst.relative_to(ROOT)}\n\nCommit the move so the other side sees it:")
    print(f"    git add -A msgbox && git commit -m 'msgbox: close {src.name[:40]}' && git push")


CMDS = {"list": cmd_list, "whoami": cmd_whoami, "send": cmd_send,
        "read": cmd_read, "close": cmd_close}

if __name__ == "__main__":
    args = sys.argv[1:]
    verb = args[0] if args and args[0] in CMDS else "list"
    rest = args[1:] if args and args[0] in CMDS else args
    CMDS[verb](rest)
