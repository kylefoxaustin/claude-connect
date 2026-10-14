"""Launcher pins / hides — shared across desktop, phone and native app (were per-device)."""
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from conductor.coord import LAUNCHER_PREFS_CAP, read_launcher_prefs, write_launcher_prefs


def test_roundtrip_and_survives_a_restart(tmp_path: Path):
    write_launcher_prefs(tmp_path, {"pins": {"/a": 1.0}, "hidden": {"/b": 2.0}})
    assert read_launcher_prefs(tmp_path) == {"pins": {"/a": 1.0}, "hidden": {"/b": 2.0}}


def test_missing_or_corrupt_is_empty_not_an_error(tmp_path: Path):
    assert read_launcher_prefs(tmp_path) == {"pins": {}, "hidden": {}}
    (tmp_path / "launcher-prefs.json").write_text("{nope", encoding="utf-8")
    assert read_launcher_prefs(tmp_path) == {"pins": {}, "hidden": {}}


def test_junk_entries_are_dropped(tmp_path: Path):
    (tmp_path / "launcher-prefs.json").write_text(
        '{"pins":{"/ok":1,"relative":2,"/bad":"x"},"hidden":[1,2]}', encoding="utf-8")
    assert read_launcher_prefs(tmp_path) == {"pins": {"/ok": 1.0}, "hidden": {}}


def test_bounded_newest_first(tmp_path: Path):
    big = {f"/p{i}": float(i) for i in range(LAUNCHER_PREFS_CAP + 50)}
    write_launcher_prefs(tmp_path, {"pins": big, "hidden": {}})
    pins = read_launcher_prefs(tmp_path)["pins"]
    assert len(pins) == LAUNCHER_PREFS_CAP and f"/p{LAUNCHER_PREFS_CAP + 49}" in pins and "/p0" not in pins


def test_write_never_raises_on_an_unwritable_root(tmp_path: Path):
    bad = tmp_path / "file"
    bad.write_text("not a dir", encoding="utf-8")
    write_launcher_prefs(bad, {"pins": {"/a": 1.0}, "hidden": {}})


# --- the endpoints ------------------------------------------------------------------------

def _client(tmp_path: Path, live_dirs=(), monkeypatch=None):
    from conductor import main
    from conductor.models import Status
    from conductor.settings import load_settings

    settings = load_settings()
    settings.server.auth_token = ""   # the real settings.toml has one
    if monkeypatch is not None:
        monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)

    class Hub:
        sent: list = []
        async def broadcast(self, kind, payload):
            Hub.sent.append((kind, payload))

    sessions = {str(i): SimpleNamespace(project_dir=d, status=Status.IDLE) for i, d in enumerate(live_dirs)}
    cond = SimpleNamespace(coord_root=tmp_path, sessions=sessions, hub=Hub(), settings=settings)
    main.app.state.cond = cond
    return TestClient(main.app), Hub


def test_set_clear_and_broadcast(tmp_path: Path, monkeypatch):
    c, hub = _client(tmp_path, monkeypatch=monkeypatch)
    r = c.post("/api/launcher-prefs", json={"dir": "/x", "pin": True, "hidden": True})
    assert r.json() == {"pins": ["/x"], "hidden": ["/x"]}
    assert hub.sent[-1] == ("launcher_prefs", {"pins": ["/x"], "hidden": ["/x"]})
    r = c.post("/api/launcher-prefs", json={"dir": "/x", "pin": False})
    assert r.json() == {"pins": [], "hidden": ["/x"]}, "omitting a flag must leave it alone"
    assert c.get("/api/launcher-prefs").json() == {"pins": [], "hidden": ["/x"]}


def test_rejects_a_non_absolute_dir(tmp_path: Path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch=monkeypatch)
    assert c.post("/api/launcher-prefs", json={"dir": "rel", "pin": True}).status_code == 400
    assert read_launcher_prefs(tmp_path) == {"pins": {}, "hidden": {}}


def test_merge_only_adds(tmp_path: Path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch=monkeypatch)
    c.post("/api/launcher-prefs", json={"dir": "/keep", "pin": True})
    r = c.post("/api/launcher-prefs", json={"merge": {"pins": ["/new", "junk"], "hidden": ["/h"]}})
    assert r.json() == {"pins": ["/keep", "/new"], "hidden": ["/h"]}


def test_a_hide_clears_once_the_folder_is_live_again(tmp_path: Path, monkeypatch):
    write_launcher_prefs(tmp_path, {"pins": {"/live": 1.0}, "hidden": {"/live": 1.0, "/gone": 1.0}})
    c, _ = _client(tmp_path, live_dirs=["/live"], monkeypatch=monkeypatch)
    assert c.get("/api/launcher-prefs").json() == {"pins": ["/live"], "hidden": ["/gone"]}
    assert "/live" not in read_launcher_prefs(tmp_path)["hidden"], "the clear must persist"
