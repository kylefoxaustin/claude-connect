"""Asset-card reader (conductor/registry.py)."""

from __future__ import annotations

from conductor.registry import attach_cards, read_card

CARD = """\
# iq9-evk
kind: board
summary: Qualcomm IQ9 EVK
visibility: shown

## setup
Flash the BSP first.

## access
ssh user@10.0.0.5 -i ~/.ssh/iq9_key
user: ubuntu

## gotchas
The serial console is 115200 8N1, not 9600.

## contact
qualcomm session owns it.

## open questions
none
"""


def test_read_card_parses_sections_access_first(tmp_path):
    (tmp_path / "iq9-evk.md").write_text(CARD)
    c = read_card(tmp_path, "iq9-evk")
    assert c is not None
    assert c["kind"] == "board"
    assert c["summary"] == "Qualcomm IQ9 EVK"
    assert c["visibility"] == "shown"
    assert c["has_access"] is True
    # access is presented FIRST even though it's the 2nd section in the file
    assert [s["key"] for s in c["sections"]][0] == "access"
    access = next(s for s in c["sections"] if s["key"] == "access")
    assert "ssh user@10.0.0.5" in access["body"]
    # empty sections are dropped is n/a here; order puts setup after access, gotchas after
    keys = [s["key"] for s in c["sections"]]
    assert keys == ["access", "setup", "gotchas", "contact", "open questions"]


def test_read_card_none_when_missing(tmp_path):
    assert read_card(tmp_path, "nope") is None


def test_card_without_access_flags_it(tmp_path):
    (tmp_path / "x.md").write_text("# x\nkind: board\n\n## setup\ndo stuff\n")
    c = read_card(tmp_path, "x")
    assert c["has_access"] is False
    assert c["visibility"] is None


def test_empty_sections_are_dropped(tmp_path):
    (tmp_path / "x.md").write_text("# x\n\n## access\nssh in\n\n## docs\n\n## gotchas\nwatch out\n")
    c = read_card(tmp_path, "x")
    assert [s["key"] for s in c["sections"]] == ["access", "gotchas"]   # empty 'docs' dropped


def test_attach_cards_in_place(tmp_path):
    (tmp_path / "iq9-evk.md").write_text(CARD)
    res = [{"name": "iq9-evk"}, {"name": "no-card"}]
    attach_cards(res, tmp_path)
    assert res[0]["card"]["has_access"] is True
    assert res[1]["card"] is None
