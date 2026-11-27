"""Opt-in checks against Joel's real darktable install. Run on the Mac:

    uv run pytest -m corpus      # live sidecars agree with the committed corpus report
    DTK_TEST_RAW=~/Pictures/Darktable/20261126_no_name/20261126_0002.CR2 uv run pytest -m darktable
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from dtk import corpus, render
from dtk.editing import plan_edit
from dtk.library import DEFAULT_LIBRARY, find_images, snapshot
from dtk.presets import load_preset
from dtk.schemas import load_corpus_report
from dtk.values import parse_set
from dtk.writer import sha256_bytes

needs_cli = pytest.mark.skipif(not Path(render.cli_path()).exists(), reason="darktable-cli not installed")


def live_sidecars():
    library = snapshot(DEFAULT_LIBRARY, Path(tempfile.mkdtemp()))
    paths = [image.path.with_name(image.path.name + ".xmp") for image in find_images(library)]
    return [path for path in paths if path.exists()]


@pytest.mark.corpus
def test_live_sidecars_agree_with_committed_report():
    live = corpus.evaluate(corpus.blobs_from_sidecars(live_sidecars()))
    for module, row in load_corpus_report().items():
        if row["status"] == "editable" and live[module]["blobs"]:
            assert live[module]["status"] == "editable", (module, live[module]["problems"])


@pytest.fixture
def test_raw():
    path = Path(os.environ.get("DTK_TEST_RAW", "")).expanduser()
    if not path.is_file():
        pytest.skip("set DTK_TEST_RAW to a raw with a sidecar")
    return path


def mean_luminance(path):
    with Image.open(path) as image:
        return ImageStat.Stat(image.convert("L")).mean[0]


@pytest.mark.darktable
@needs_cli
def test_plus_one_ev_renders_brighter(test_raw, tmp_path):
    text = test_raw.with_name(test_raw.name + ".xmp").read_text()
    plan = plan_edit(text, [parse_set("exposure.exposure+=1")])
    spec = render.RenderSpec(width=512, height=512)
    before = render.render(test_raw, text, tmp_path / "before.jpg", spec)
    after = render.render(test_raw, plan.new_text, tmp_path / "after.jpg", spec)
    assert mean_luminance(after) > mean_luminance(before) * 1.3


@pytest.mark.darktable
@needs_cli
def test_messenger_export_leaves_the_sidecar_alone(test_raw, tmp_path):
    xmp = test_raw.with_name(test_raw.name + ".xmp")
    before = sha256_bytes(xmp.read_bytes())
    preset = load_preset("messenger")
    out = render.render(test_raw, xmp.read_text(), tmp_path / "m.jpg", preset.spec)
    assert sha256_bytes(xmp.read_bytes()) == before
    with Image.open(out) as image:
        assert max(image.size) <= 2048
    if shutil.which("magick"):
        quality = subprocess.run(["magick", "identify", "-format", "%Q", str(out)],
                                 capture_output=True, text=True).stdout.strip()
        assert quality == "90"
