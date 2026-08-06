"""A request that can be FILED must be DISMISSIBLE.

Kyle, 2026-08-06: "I keep getting an approval request for an $d". A `git push` inside a test
harness produced a repo path containing `$d`; the push gate sanitized the key with `tr '/ ' '__'`
(slashes and spaces ONLY), so `$` survived into the key — and Conductor's API then refused to act
on it with "bad request key". The request sat in the inbox re-ringing his phone every hour, and
neither the desktop nor the phone could clear it.

**A control surface that can raise an alarm it cannot lower teaches the operator to ignore the
alarm** — which is the one thing the push gate cannot afford, since it is the control standing
between the fleet and every repo.

Two halves, both tested here:
  * the gate now sanitizes to exactly the charset the API accepts, so new keys are always clean;
  * the API also accepts a key that EXACTLY matches an existing request file, so keys already on
    disk (and any future gate that drifts) remain dismissible.
"""

from __future__ import annotations

import subprocess

import pytest

from conductor.main import _known_request_key


# ── the API side: anything on disk can be cleared ─────────────────────────────────────────

def test_charset_clean_key_is_accepted(tmp_path):
    assert _known_request_key("home_kyle_repo", tmp_path) is True


def test_the_exact_key_that_nagged_kyle_is_now_actionable(tmp_path):
    """THE REGRESSION, with the real filename from the incident."""
    bad = "home_kyle_Documents_GitHub_claude-connect_$d"
    (tmp_path / bad).write_text("repo=/x\n")
    assert _known_request_key(bad, tmp_path) is True


@pytest.mark.parametrize("name", [
    "repo_$d", "my_repo_(v2)", "a&b", "weird;name", "back`tick`",
])
def test_any_filed_request_can_be_dismissed(tmp_path, name):
    """Whatever the gate managed to write, the operator must be able to clear."""
    (tmp_path / name).write_text("x")
    assert _known_request_key(name, tmp_path) is True


def test_a_key_that_is_not_on_disk_is_still_rejected(tmp_path):
    """The fallback is 'this file exists', not 'anything goes'."""
    assert _known_request_key("repo_$d", tmp_path) is False


@pytest.mark.parametrize("evil", [
    "../../../etc/passwd", "..", "../push-tokens", "/etc/passwd", "foo/../bar",
])
def test_traversal_is_still_refused(tmp_path, evil):
    """The charset check was ALSO a path-traversal guard, so the fallback must not reopen it.
    It compares against names that already exist in the directory and never builds a path from
    the caller's string — so `../` matches nothing, even though it is not charset-clean."""
    assert _known_request_key(evil, tmp_path) is False


def test_traversal_refused_even_when_a_same_named_file_exists_elsewhere(tmp_path):
    """A file called `passwd` in the requests dir must not make `../../etc/passwd` valid."""
    (tmp_path / "passwd").write_text("x")
    assert _known_request_key("../../etc/passwd", tmp_path) is False


def test_empty_key_refused(tmp_path):
    assert _known_request_key("", tmp_path) is False


def test_missing_directory_refused(tmp_path):
    """No inbox, no dismissal — but no crash either."""
    assert _known_request_key("repo_$d", tmp_path / "nope") is False


# ── the gate side: keys are clean at the source ───────────────────────────────────────────

def _sanitize(repo: str) -> str:
    """Run the gate's ACTUAL sanitizer expression, not a python re-implementation of it — a
    re-implementation would be a mirror of my belief about the shell, which is exactly the class
    of test that passed while `grep -c .` was killing the wind-down ack."""
    return subprocess.run(
        ["bash", "-c", "printf '%s' \"$1\" | tr -c 'A-Za-z0-9._-' '_' | sed 's/^_*//'", "_", repo],
        capture_output=True, text=True, check=True,
    ).stdout


@pytest.mark.parametrize("repo", [
    "/home/kyle/Documents/GitHub/claude-connect",
    "/home/kyle/Documents/GitHub/claude-connect/$d",
    "/home/kyle/my repo (v2)",
    "/home/kyle/a&b",
    "/home/kyle/back`tick`",
    "/home/kyle/semi;colon",
])
def test_gate_keys_are_always_api_actionable(repo, tmp_path):
    """Whatever path the gate is handed, the key it files must pass the API's charset check —
    closing the hole at the source rather than relying on the fallback."""
    key = _sanitize(repo)
    assert key, f"{repo!r} sanitized to an empty key"
    assert _known_request_key(key, tmp_path) is True, f"{repo!r} -> {key!r} is not actionable"


def test_ordinary_repo_keys_are_unchanged(tmp_path):
    """The fix must not rename the keys of every existing request — a changed key would orphan
    any pending approval, turning a nag fix into a lost approval."""
    assert _sanitize("/home/kyle/Documents/GitHub/claude-connect") \
        == "home_kyle_Documents_GitHub_claude-connect"
