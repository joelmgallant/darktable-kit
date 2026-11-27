import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms

import dtk.procs as procs
import dtk.render as render
from dtk.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.fixture
def photo(tmp_path, monkeypatch):
    monkeypatch.setenv("DTK_STATE_DIR", str(tmp_path / "state"))
    raw = tmp_path / "photos" / "IMG_1.CR2"
    raw.parent.mkdir()
    raw.write_bytes(b"raw")
    shutil.copy(FIXTURES / "minimal.xmp", raw.with_name("IMG_1.CR2.xmp"))
    return raw


@pytest.fixture
def fake_darktable(monkeypatch):
    def run(cmd, **kwargs):
        Image.new("RGB", (640, 480), (90, 90, 90)).save(cmd[3], "JPEG", icc_profile=SRGB)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(render.subprocess, "run", run)


def test_modules_lists_exposure(capsys):
    assert main(["modules"]) == 0
    assert any(line.split()[:1] == ["exposure"] and "editable" in line for line in capsys.readouterr().out.splitlines())


def test_show_marks_undone_steps(photo, capsys):
    assert main(["show", str(photo)]) == 0
    out = capsys.readouterr().out
    assert "exposure" in out and "crop" in out and "undone" in out


def test_edit_then_apply(photo, capsys, monkeypatch):
    assert main(["edit", str(photo), "--set", "exposure.exposure=0.5", "--no-preview"]) == 0
    out = capsys.readouterr().out
    edit_id = next(line.split()[-1] for line in out.splitlines() if line.startswith("apply with: dtk apply"))
    assert photo.with_name("IMG_1.CR2.xmp").read_text() == (FIXTURES / "minimal.xmp").read_text()
    monkeypatch.setattr(procs, "darktable_running", lambda run=None: False)
    assert main(["apply", edit_id]) == 0
    assert 'darktable:history_end="3"' in photo.with_name("IMG_1.CR2.xmp").read_text()
    assert main(["apply", edit_id]) == 1
    assert "already applied" in capsys.readouterr().err


def test_edit_refusal_is_one_line_on_stderr(photo, capsys):
    assert main(["edit", str(photo), "--set", "exposure.exposure=99", "--no-preview"]) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("dtk: ") and "outside" in err and "\n" not in err


def test_edit_with_preview(photo, fake_darktable, capsys):
    assert main(["edit", str(photo), "--set", "exposure.exposure=0.5"]) == 0
    preview = next(line.split(": ", 1)[1] for line in capsys.readouterr().out.splitlines() if line.startswith("preview: "))
    assert Path(preview).exists()


def test_export_with_preset(photo, fake_darktable, capsys):
    xmp = photo.with_name("IMG_1.CR2.xmp")
    before = xmp.read_bytes()
    assert main(["export", str(photo), "--preset", "messenger"]) == 0
    assert (photo.parent / "messenger" / "IMG_1.jpg").exists()
    assert xmp.read_bytes() == before


def test_export_refuses_to_overwrite_its_source(tmp_path, fake_darktable, capsys):
    jpeg = tmp_path / "shot.jpg"
    Image.new("RGB", (10, 10)).save(jpeg)
    shutil.copy(FIXTURES / "minimal.xmp", tmp_path / "shot.jpg.xmp")
    assert main(["export", str(jpeg), "--preset", "messenger", "--out", str(tmp_path)]) == 1
    assert "would overwrite" in capsys.readouterr().err
