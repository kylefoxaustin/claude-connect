"""End-to-end acceptance for the persistence gate: a tool call on stdin, a verdict out.

WHY THIS EXISTS ALONGSIDE test_gate_interpreter.py, which is not redundant with it:
that suite covers the interpreter axis exhaustively -- missing, present, a Store alias
that resolves and does not run, an override, controls both ways -- but it drives the gate
with a payload crafted in Python. Nothing there starts from stdin, and nothing there
covers the FALSE-POSITIVE class: the paths a merely-safe gate denies and a correct one
allows. That class is what decides whether the gate is USABLE, not just safe.

Measured on Windows 2026-08-23: with no usable interpreter the gate denied transcripts,
bus-state and reads of gated paths -- all correct-by-fail-closed, all unusable in
practice. Those four rows are the ones this table exists to hold.

The table is DATA (gate_acceptance.json) and is also driven by
scripts/bootstrap-windows.ps1 on Windows, so a verdict cannot drift on one platform
without the other going red. Keep new cases in the JSON, not here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT  = Path(__file__).resolve().parent.parent
GATE  = ROOT / "bus" / "persist-gate.sh"
TABLE = json.loads((Path(__file__).parent / "gate_acceptance.json").read_text(encoding="utf-8"))

DENY, ALLOW = 2, 0
_WANT = {"deny": DENY, "allow": ALLOW}


@pytest.fixture
def sandbox(tmp_path):
    """A throwaway ~/.claude. BUS_STATE_DIR is set EXPLICITLY: the gate derives it from
    $HOME otherwise, and Git Bash rewrites HOME into an MSYS path on the way in, so the
    sandbox and the thing under test end up disagreeing about where state lives."""
    ch = tmp_path / "claude"
    for d in ("bin", "commands", "bus-state/registry", "projects"):
        (ch / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "coord").mkdir(exist_ok=True)
    (tmp_path / "proj").mkdir(exist_ok=True)
    return {
        "TMP": str(tmp_path),
        "CH": str(ch),
        "PROJ": str(tmp_path / "proj"),
        # POSIX spelling of CH, for the cases that deliberately probe the other namespace
        "CH_POSIX": ch.as_posix(),
        "_env": {
            "COORD_STATE_DIR": str(tmp_path / "coord"),
            "CLAUDE_CONFIG_DIR": str(ch),
            "BUS_STATE_DIR": str(ch / "bus-state"),
            "HOME": str(tmp_path),
            # Pin the interpreter so this suite tests the DECISION, not the resolution.
            # test_gate_interpreter.py owns the resolution axis.
            "CLAUDE_BUS_PYTHON": sys.executable,
            "PATH": os.environ.get("PATH", ""),
        },
    }


def _subst(obj, vals):
    if isinstance(obj, str):
        for k, v in vals.items():
            if not k.startswith("_"):
                obj = obj.replace("{%s}" % k, v)
        return obj
    if isinstance(obj, dict):
        return {k: _subst(v, vals) for k, v in obj.items()}
    return obj


def run_case(case, sandbox) -> int:
    """Feed the gate one case and return its exit code."""
    if "raw_stdin" in case:
        payload = _subst(case["raw_stdin"], sandbox).encode("utf-8")
    else:
        # A REAL serializer, always. Hand-built JSON with Windows backslashes throws in
        # json.loads, which looks exactly like the bug this table tests for -- it fooled
        # win_conductor once before the numbers were trusted.
        doc = {
            "cwd": sandbox["PROJ"],
            "tool_name": case["tool"],
            "tool_input": _subst(case["input"], sandbox),
        }
        payload = json.dumps(doc).encode("utf-8")
    if case.get("stdin_bom"):
        payload = b"\xef\xbb\xbf" + payload

    env = dict(os.environ)
    env.update(sandbox["_env"])
    p = subprocess.run(["bash", str(GATE)], input=payload,
                       capture_output=True, env=env)
    return p.returncode


def _ids(rows):
    return [r["name"] for r in rows]


@pytest.mark.skipif(not GATE.exists(), reason="gate not present in this checkout")
@pytest.mark.parametrize("case", TABLE["cases"], ids=_ids(TABLE["cases"]))
def test_gate_verdict(case, sandbox):
    """Every row is a verdict the gate must produce for a payload arriving on stdin."""
    rc = run_case(case, sandbox)
    want = _WANT[case["expect"]]
    got = {DENY: "DENY", ALLOW: "ALLOW"}.get(rc, f"rc={rc}")
    assert rc == want, (
        f"{case['name']}: got {got}, expected {case['expect'].upper()}\n"
        f"  why this row exists: {case['why']}"
    )


@pytest.mark.skipif(not GATE.exists(), reason="gate not present in this checkout")
@pytest.mark.parametrize("case", TABLE["known_gaps"], ids=_ids(TABLE["known_gaps"]))
def test_known_gap(case, sandbox):
    """Rows that are CLOSED on some platforms and OPEN on others.

    Where a gap is open, the assertion is INVERTED rather than skipped -- so the day
    someone closes it, this goes red and tells them to move the row. A skip would let a
    fix land silently and leave the table claiming a gap that no longer exists.
    """
    rc = run_case(case, sandbox)
    want = _WANT[case["expect"]]
    if sys.platform in case.get("open_on", []):
        assert rc != want, (
            f"{case['name']}: this gap appears to be CLOSED on {sys.platform} now.\n"
            f"  Good news -- move it out of known_gaps into cases.\n"
            f"  Recorded reason it was open: {case['why']}"
        )
    else:
        assert rc == want, (
            f"{case['name']}: expected {case['expect'].upper()} on {sys.platform}, got rc={rc}.\n"
            f"  This row is NOT marked open here, so this is a regression.\n"
            f"  {case['why']}"
        )
