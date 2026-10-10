"""Server-side alert dismissals — the store that works where localStorage does not."""
from pathlib import Path
from conductor.coord import read_alert_dismissals, write_alert_dismissals


def test_roundtrip(tmp_path: Path):
    write_alert_dismissals(tmp_path, {"stale:x": {"at": 1000.0, "n": 20.0}})
    assert read_alert_dismissals(tmp_path)["stale:x"]["n"] == 20.0


def test_missing_file_is_empty_not_an_error(tmp_path: Path):
    assert read_alert_dismissals(tmp_path) == {}


def test_corrupt_file_degrades_to_empty(tmp_path: Path):
    (tmp_path / "alert-dismissals.json").write_text("{not json", encoding="utf-8")
    assert read_alert_dismissals(tmp_path) == {}


def test_junk_entries_are_dropped_not_trusted(tmp_path: Path):
    (tmp_path / "alert-dismissals.json").write_text(
        '{"good":{"at":1,"n":2},"bad":"nope","worse":{"n":5}}', encoding="utf-8")
    d = read_alert_dismissals(tmp_path)
    assert set(d) == {"good"}, "an entry with no timestamp must not suppress a row"


def test_bounded_to_newest_200(tmp_path: Path):
    big = {f"k{i}": {"at": float(i), "n": 1.0} for i in range(400)}
    write_alert_dismissals(tmp_path, big)
    d = read_alert_dismissals(tmp_path)
    assert len(d) == 200 and "k399" in d and "k0" not in d, "must keep the NEWEST 200"


def test_write_never_raises_on_an_unwritable_root(tmp_path: Path):
    bad = tmp_path / "nope"
    bad.write_text("i am a file, not a directory", encoding="utf-8")
    write_alert_dismissals(bad, {"k": {"at": 1.0, "n": 1.0}})   # must not raise


def test_survives_a_restart_which_is_the_whole_point(tmp_path: Path):
    """localStorage cannot do this in the native app; the file can."""
    write_alert_dismissals(tmp_path, {"quiet:a": {"at": 5.0, "n": 3.0}})
    assert read_alert_dismissals(tmp_path) == {"quiet:a": {"at": 5.0, "n": 3.0}}
