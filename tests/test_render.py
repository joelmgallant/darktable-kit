import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms

from dtk.presets import list_presets, load_preset, out_dir_for
from dtk.render import RenderError, RenderSpec, render, side_by_side

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def fake_darktable(size=(800, 600), icc=True, produce=True, seen=None):
    def run(cmd, **kwargs):
        raw_link, xmp_copy, out = Path(cmd[1]), Path(cmd[2]), Path(cmd[3])
        if seen is not None:
            seen.update(cmd=cmd, is_link=raw_link.is_symlink(), target=raw_link.resolve(),
                        xmp_text=xmp_copy.read_text())
        if produce:
            Image.new("RGB", size, (90, 90, 90)).save(out, "JPEG", **({"icc_profile": SRGB} if icc else {}))
        return subprocess.CompletedProcess(cmd, 0 if produce else 1, "", "boom: cannot load raw\n")
    return run


@pytest.fixture
def raw(tmp_path):
    path = tmp_path / "IMG_1.CR2"
    path.write_bytes(b"raw")
    return path


def test_render_uses_a_symlink_and_a_sidecar_copy(raw, tmp_path):
    seen = {}
    out = render(raw, "<xmp edited/>", tmp_path / "out" / "a.jpg", RenderSpec(width=1024, height=1024),
                 run=fake_darktable(seen=seen))
    assert out.exists()
    assert seen["is_link"] and seen["target"] == raw.resolve()
    assert seen["xmp_text"] == "<xmp edited/>"
    cmd = seen["cmd"]
    for expected in (["--library", ":memory:"], ["--icc-type", "SRGB"], ["--width", "1024"]):
        index = cmd.index(expected[0])
        assert cmd[index:index + 2] == expected
    assert "write_sidecar_files=never" in cmd
    assert "plugins/imageio/format/jpeg/quality=90" in cmd


def test_existing_output_is_replaced(raw, tmp_path):
    out = tmp_path / "a.jpg"
    out.write_bytes(b"old")
    render(raw, "<x/>", out, RenderSpec(), run=fake_darktable())
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_missing_output_is_an_error_with_stderr(raw, tmp_path):
    with pytest.raises(RenderError, match="cannot load raw"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(), run=fake_darktable(produce=False))


def test_oversize_output_is_an_error(raw, tmp_path):
    with pytest.raises(RenderError, match="larger than"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(width=100, height=100), run=fake_darktable())


def test_missing_srgb_profile_is_an_error(raw, tmp_path):
    with pytest.raises(RenderError, match="sRGB"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(), run=fake_darktable(icc=False))


def test_side_by_side(tmp_path):
    before, after = tmp_path / "b.jpg", tmp_path / "a.jpg"
    Image.new("RGB", (100, 80)).save(before)
    Image.new("RGB", (100, 80)).save(after)
    with Image.open(side_by_side(before, after, tmp_path / "pair.jpg")) as pair:
        assert pair.size == (208, 80)


def test_messenger_preset():
    preset = load_preset("messenger")
    assert (preset.spec.width, preset.spec.height, preset.spec.quality) == (2048, 2048, 90)
    assert preset.spec.icc_type == "SRGB" and preset.spec.upscale is False
    assert out_dir_for(preset, Path("/photos/moon/IMG_1.CR2")) == Path("/photos/moon/messenger")
    assert "messenger" in [p.name for p in list_presets()]


def test_unknown_preset():
    with pytest.raises(LookupError, match="no preset named 'nope'"):
        load_preset("nope")


def test_missing_darktable_cli_is_a_render_error(raw, tmp_path, monkeypatch):
    monkeypatch.setenv("DTK_DARKTABLE_CLI", str(tmp_path / "no-such-darktable-cli"))
    with pytest.raises(RenderError, match="DTK_DARKTABLE_CLI"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec())


def test_hung_darktable_cli_is_a_render_error(raw, tmp_path):
    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
    with pytest.raises(RenderError, match="did not finish"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(), run=hang)
