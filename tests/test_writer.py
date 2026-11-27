import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import dtk.procs as procs
from dtk import pending
from dtk.writer import WriteRefused, sha256_bytes, write_xmp

MINIMAL = (Path(__file__).parent / "fixtures" / "minimal.xmp").read_text()
NEW_TEXT = MINIMAL.replace('history_end="2"', 'history_end="1"')


@pytest.fixture
def xmp(tmp_path):
    path = tmp_path / "IMG_1.CR2.xmp"
    path.write_text(MINIMAL)
    return path


def sha(path):
    return sha256_bytes(path.read_bytes())


def test_write_backs_up_then_replaces(xmp, tmp_path):
    backup = write_xmp(xmp, NEW_TEXT, sha(xmp), is_running=lambda: False, backup_dir=tmp_path / "bk",
                       now=lambda: datetime(2026, 11, 27, 9, 30, 0, 123456))
    assert xmp.read_text() == NEW_TEXT
    assert backup == tmp_path / "bk" / "IMG_1.CR2.xmp.20261127-093000-123456.xmp"
    assert backup.read_text() == MINIMAL
    assert not list(xmp.parent.glob(".*dtk-tmp"))


def test_refuses_while_darktable_runs(xmp, tmp_path):
    with pytest.raises(WriteRefused, match="darktable is running"):
        write_xmp(xmp, NEW_TEXT, sha(xmp), is_running=lambda: True, backup_dir=tmp_path / "bk")
    assert xmp.read_text() == MINIMAL


def test_refuses_stale_previews(xmp, tmp_path):
    with pytest.raises(WriteRefused, match="changed since the preview"):
        write_xmp(xmp, NEW_TEXT, "0" * 64, is_running=lambda: False, backup_dir=tmp_path / "bk")
    assert xmp.read_text() == MINIMAL
    assert not (tmp_path / "bk").exists()


def test_default_running_check_uses_exact_process_name(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 1)
    assert procs.darktable_running(run=fake_run) is False
    assert seen["cmd"] == ["pgrep", "-x", "darktable"]


def test_pending_round_trip(tmp_path):
    edit = pending.PendingEdit(id=pending.new_id(lambda: datetime(2026, 11, 27, 9, 0, 0)), raw="/p/a.CR2",
                               xmp="/p/a.CR2.xmp", original_sha="ab", new_text="<x/>",
                               diff=[["exposure.exposure", 1.0, 2.0]], preview=None, created="2026-11-27T09:00:00")
    assert edit.id.startswith("20261127-090000-")
    pending.save(edit, root=tmp_path)
    assert pending.load(edit.id, root=tmp_path) == edit
    pending.mark_applied(edit.id, root=tmp_path)
    assert pending.load(edit.id, root=tmp_path).applied is True
    with pytest.raises(LookupError, match="no pending edit"):
        pending.load("nope", root=tmp_path)
