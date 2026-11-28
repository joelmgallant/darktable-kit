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


def test_edit_with_preview(photo, monkeypatch, capsys):
    rendered = []

    def recording_darktable(cmd, **kwargs):
        rendered.append((Path(cmd[3]).name, Path(cmd[2]).read_text()))
        Image.new("RGB", (640, 480), (90, 90, 90)).save(cmd[3], "JPEG", icc_profile=SRGB)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(render.subprocess, "run", recording_darktable)
    assert main(["edit", str(photo), "--set", "exposure.exposure=0.5"]) == 0
    preview = next(line.split(": ", 1)[1] for line in capsys.readouterr().out.splitlines() if line.startswith("preview: "))
    assert Path(preview).exists()
    (_, before_text), (_, after_text) = rendered
    assert before_text == (FIXTURES / "minimal.xmp").read_text()
    assert 'darktable:history_end="3"' in after_text and 'darktable:history_end="3"' not in before_text


def test_show_marks_bad_and_unsupported_entries_without_aborting(photo, capsys):
    xmp = photo.with_name("IMG_1.CR2.xmp")
    text = xmp.read_text().replace('darktable:params="000000000000000036f22a3f0000803f0100000001000000"',
                                   'darktable:params="zz-not-params"', 1)
    text = text.replace('darktable:operation="exposure"\n      darktable:enabled="1"\n      darktable:modversion="7"\n'
                        '      darktable:params="00000000000080b90000404000004842000080c00100000001000000"',
                        'darktable:operation="dither"\n      darktable:enabled="1"\n      darktable:modversion="1"\n'
                        '      darktable:params="00000000000080b90000404000004842000080c00100000001000000"', 1)
    assert 'operation="dither"' in text and "zz-not-params" in text
    xmp.write_text(text)
    assert main(["show", str(photo)]) == 0
    out = capsys.readouterr().out
    assert "crop v3  (cannot read params:" in out
    assert "dither v1  (unsupported:" in out


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


def test_export_refuses_to_overwrite_a_camera_jpeg_next_to_the_raw(photo, fake_darktable, capsys):
    camera_jpeg = photo.with_name("IMG_1.jpg")
    camera_jpeg.write_bytes(b"camera original")
    assert main(["export", str(photo), "--preset", "messenger", "--out", str(photo.parent)]) == 1
    assert "would overwrite" in capsys.readouterr().err
    assert camera_jpeg.read_bytes() == b"camera original"


def test_export_refuses_two_images_with_the_same_output_name(photo, fake_darktable, tmp_path, capsys):
    other = tmp_path / "elsewhere" / "IMG_1.CR2"
    other.parent.mkdir()
    other.write_bytes(b"raw")
    shutil.copy(FIXTURES / "minimal.xmp", other.with_name("IMG_1.CR2.xmp"))
    out = tmp_path / "out"
    assert main(["export", str(photo), str(other), "--preset", "messenger", "--out", str(out)]) == 1
    assert "same output" in capsys.readouterr().err
    assert not out.exists()


def test_library_snapshots_are_removed_at_exit(tmp_path, monkeypatch):
    import sqlite3

    import dtk.commands as commands
    library = tmp_path / "library.db"
    sqlite3.connect(library).close()
    monkeypatch.setattr(commands, "DEFAULT_LIBRARY", library)
    cleanups = []
    monkeypatch.setattr(commands.atexit, "register", lambda func, *args, **kwargs: cleanups.append((func, args, kwargs)))
    copy = commands._library_snapshot()
    assert copy.exists()
    for func, args, kwargs in cleanups:
        func(*args, **kwargs)
    assert not copy.parent.exists()


@pytest.fixture
def duplicate_photo(photo):
    """photo plus a darktable duplicate (version 1) whose sidecar is IMG_1_01.CR2.xmp."""
    shutil.copy(FIXTURES / "minimal.xmp", photo.with_name("IMG_1_01.CR2.xmp"))
    return photo


def test_export_of_a_duplicate_does_not_overwrite_the_original_export(duplicate_photo, fake_darktable):
    duplicate_sidecar = duplicate_photo.with_name("IMG_1_01.CR2.xmp")
    assert main(["export", str(duplicate_photo), str(duplicate_sidecar), "--preset", "messenger"]) == 0
    exports = sorted(path.name for path in (duplicate_photo.parent / "messenger").iterdir())
    assert exports == ["IMG_1.jpg", "IMG_1_01.jpg"]


def test_find_shows_the_duplicate_version(duplicate_photo, tmp_path, monkeypatch, capsys):
    import sqlite3

    import dtk.commands as commands
    library = tmp_path / "library.db"
    with sqlite3.connect(library) as conn:
        conn.executescript((FIXTURES / "library_schema.sql").read_text())
        conn.execute("insert into film_rolls (id, folder) values (1, ?)", (str(duplicate_photo.parent),))
        conn.executemany("insert into images (id, film_id, filename, flags, version) values (?, 1, 'IMG_1.CR2', 1, ?)",
                         [(1, 0), (2, 1)])
    monkeypatch.setattr(commands, "DEFAULT_LIBRARY", library)
    assert main(["find"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "(duplicate" not in lines[0] and lines[1].rstrip().endswith("(duplicate 1)")
