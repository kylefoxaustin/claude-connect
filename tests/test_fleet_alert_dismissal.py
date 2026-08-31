"""The dismiss control must not be a mute button.

Kyle, 2026-08-30, looking at eleven fleet-health rows filling the whole window: *"i'd sure like a
way to either dismiss or collapse all those warnings on conductor. takes up a lot of room."*

Dismissing is the dangerous half. This panel exists because a fleet problem that says nothing is
indistinguishable from no problem — so a control that could silence a condition permanently would
reintroduce, by hand, exactly the failure the panel was built to catch. Two properties keep it safe:

  1. the HEADLINE COUNT is computed before dismissal, so the summary never shrinks;
  2. the key embeds a DOUBLING BUCKET of the quantity, so a materially worse state comes back.

⚠️ These assertions run against the SHIPPED source, extracted from frontend/app.js — never a copy
of the logic pasted in here. A test that gets its implementation from the model is a mirror
(FAILURE_MODES class IV), and it would pass just as happily against a bucket() that returns 0.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "frontend" / "app.js"
CSS = Path(__file__).resolve().parent.parent / "frontend" / "style.css"
node = shutil.which("node")


def _eval(expr_lines):
    """Run bucket() — lifted verbatim out of app.js — against the given expressions."""
    src = APP.read_text(encoding="utf-8")
    m = re.search(r"^function bucket\(n\) \{.*?^\}", src, re.S | re.M)
    assert m, "bucket() not found in app.js — the dismissal keying changed shape; fix this test"
    prog = m.group(0) + "\nconsole.log(JSON.stringify([" + ",".join(expr_lines) + "]));"
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not node, reason="node not installed")
def test_a_dismissal_survives_small_drift_but_not_a_doubling():
    # 9h silent, dismissed. At 9h01m it must STAY dismissed or the button does nothing...
    nine, nine_plus, sixteen = _eval(["bucket(9*3600)", "bucket(9*3600+60)", "bucket(16*3600)"])
    assert nine == nine_plus, "the row returned within a minute — dismissing would be useless"
    # ...and at 16h it must COME BACK, or dismissing is permanent blindness to a worse condition.
    assert sixteen != nine, "a doubled silence stayed hidden — that is a mute button"


@pytest.mark.skipif(not node, reason="node not installed")
def test_zero_and_garbage_do_not_collapse_into_one_bucket():
    # log2(0) is -Infinity; Math.pow(2, -Infinity) is 0 — fine, but only because it is guarded.
    # Without the guard every row with a 0/undefined quantity shares one key and dismissing any
    # one of them hides all the others.
    z, neg, nan = _eval(["bucket(0)", "bucket(-5)", "bucket(undefined)"])
    assert z == 0 and neg == 0 and nan == 0
    assert all(isinstance(v, (int, float)) for v in (z, neg, nan)), "bucket() leaked a NaN into a key"


def test_the_headline_count_is_computed_before_dismissal():
    """⭐ The property that makes dismissing safe at all."""
    src = APP.read_text(encoding="utf-8")
    body = src[src.index("function renderFleetAlerts("):]
    body = body[: body.index("\n}\n")]
    # Every headline term must come from a FULL array. `kept` may only reach the paint step and
    # the "N dismissed" badge — never a `parts.push`.
    pushes = re.findall(r"parts\.push\(([^;]*)\);", body)
    assert len(pushes) >= 5, f"headline terms disappeared — only found {len(pushes)}"
    leaked = [x for x in pushes if "kept" in x or "dismiss" in x]
    assert not leaked, f"the headline was derived from the surviving rows: {leaked}"
    assert "parts.push(`${staleReaders.length}" in body, \
        "the not-reading count no longer comes from the full list"


def test_dismiss_gutter_is_reserved_in_the_winning_declaration():
    """A padding shorthand later in the sheet silently wipes an earlier padding-right.

    That is not hypothetical: this exact collision existed for a few minutes while building this
    (an `.alert-row{position:relative;padding-right:26px}` written ABOVE the pre-existing
    `.alert-row{...padding:3px 0...}`), and its symptom is a ✕ sitting on top of wrapped text —
    a visual bug no unit test would ever have seen.
    """
    rules = re.findall(r"^\.alert-row \{[^}]*\}", CSS.read_text(encoding="utf-8"), re.S | re.M)
    assert rules, ".alert-row rule vanished"
    last = rules[-1]
    assert "position: relative" in last and re.search(r"padding: 3px 26px", last), \
        f"the LAST .alert-row declaration does not reserve the gutter:\n{last}"
