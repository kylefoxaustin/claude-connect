"""A missing web-push dependency must DEGRADE, never crash the scan loop.

Regression for the 2026-07-22 incident: the service venv was missing `cryptography`
(a pywebpush dep), so `load_or_create_keys` raised `ModuleNotFoundError` inside
`_notify()` on EVERY scan tick. That (a) silently killed phone paging — a Claude sat
blocked on a human decision for 6 hours with no notification — and (b) spammed the
scan-loop error channel, masking real scan errors. Paging is an accelerator, never the
only door: a missing optional dep must disable web-push (logged once), not take down
the scan.
"""

from __future__ import annotations

import asyncio
import logging

import conductor.main as m
from conductor.main import AppState
from conductor.settings import load_settings


def _decision(sid="s1"):
    return {
        "session_id": sid,
        "cwd": "/home/kyle/Documents/GitHub/image_gen",
        "questions": [{"question": "Reboot the board?", "header": "H",
                       "multiSelect": False, "options": [{"label": "Yes", "description": ""}]}],
    }


def test_missing_dep_disables_webpush_without_raising(monkeypatch, caplog):
    app = AppState(load_settings())
    app.decisions = [_decision()]                       # a genuinely pending page

    subs_calls = {"n": 0}
    def fake_read_subs(_root):
        subs_calls["n"] += 1
        return [{"endpoint": "https://push.example/x", "keys": {"p256dh": "a", "auth": "b"}}]

    def boom(_root):
        raise ModuleNotFoundError("No module named 'cryptography'")

    monkeypatch.setattr(m, "read_subs", fake_read_subs)
    monkeypatch.setattr(m, "load_or_create_keys", boom)

    with caplog.at_level(logging.ERROR, logger="conductor"):
        asyncio.run(app._notify())                      # must NOT raise

    assert app._webpush_broken is True                  # disabled after the first failure
    assert subs_calls["n"] == 1                          # it did try once
    assert any("web-push disabled" in r.message for r in caplog.records)

    # Subsequent ticks short-circuit BEFORE touching subs — no retry-spam, no raise.
    asyncio.run(app._notify())
    asyncio.run(app._notify())
    assert subs_calls["n"] == 1                          # never called read_subs again


def test_status_dependency_missing_is_unhealthy(monkeypatch):
    app = AppState(load_settings())
    app._webpush_broken = True
    st = app._webpush_status()
    assert st["healthy"] is False and st["reason"] == "dependency_missing"


def test_status_no_subscription_is_ok_when_nothing_pending(monkeypatch):
    app = AppState(load_settings())
    app.decisions = []
    monkeypatch.setattr(m, "read_subs", lambda _r: [])       # no phone registered
    st = app._webpush_status()
    assert st["healthy"] is True and st["reason"] == "no_subscription"


def test_status_no_subscription_ALARMS_when_something_needs_you(monkeypatch):
    app = AppState(load_settings())
    app.decisions = [_decision()]                            # a blocked question exists
    monkeypatch.setattr(m, "read_subs", lambda _r: [])       # but no phone to page
    st = app._webpush_status()
    assert st["healthy"] is False and st["reason"] == "no_subscription"


def test_status_ok_when_subscribed_and_deps_present(monkeypatch):
    app = AppState(load_settings())
    monkeypatch.setattr(m, "read_subs", lambda _r: [{"endpoint": "e", "keys": {}}])
    st = app._webpush_status()
    assert st["healthy"] is True and st["reason"] == "ok"


def test_healthy_webpush_is_untouched(monkeypatch):
    """When the deps ARE present, _notify proceeds normally (no false-disable)."""
    app = AppState(load_settings())
    app.decisions = [_decision()]

    sent = {"n": 0}
    monkeypatch.setattr(m, "read_subs", lambda _r: [{"endpoint": "e", "keys": {}}])
    monkeypatch.setattr(m, "load_or_create_keys", lambda _r: {"private": "x", "public": "y"})
    monkeypatch.setattr(m, "vapid_subject", lambda _h: "mailto:k@example.com")
    def fake_send_one(_sub, _item, _keys, _subj):
        sent["n"] += 1
        return True
    monkeypatch.setattr(m, "send_one", fake_send_one)

    asyncio.run(app._notify())
    assert app._webpush_broken is False
    assert sent["n"] == 1                                 # it actually paged
