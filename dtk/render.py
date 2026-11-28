"""darktable-cli wrapper. Real sidecars are never handed to darktable-cli."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms

DEFAULT_CLI = "/Applications/darktable.app/Contents/MacOS/darktable-cli"
STDERR_TAIL_LINES = 8
GAP_PIXELS = 8
RENDER_TIMEOUT_SECONDS = 600


def cli_path() -> str:
    return os.environ.get("DTK_DARKTABLE_CLI", DEFAULT_CLI)


@dataclass(frozen=True)
class RenderSpec:
    width: int = 0
    height: int = 0
    quality: int = 90
    icc_type: str | None = "SRGB"
    icc_intent: str = "PERCEPTUAL"
    hq: bool = True
    upscale: bool = False


PREVIEW_SPEC = RenderSpec(width=1024, height=1024, quality=85)


class RenderError(RuntimeError):
    """darktable-cli did not produce the image we asked for."""


def _flag(value: bool) -> str:
    return "true" if value else "false"


def build_command(raw_link: Path, xmp_copy: Path, out: Path, spec: RenderSpec, configdir: Path) -> list[str]:
    cmd = [cli_path(), str(raw_link), str(xmp_copy), str(out),
           "--width", str(spec.width), "--height", str(spec.height),
           "--hq", _flag(spec.hq), "--upscale", _flag(spec.upscale)]
    if spec.icc_type:
        cmd += ["--icc-type", spec.icc_type, "--icc-intent", spec.icc_intent]
    return cmd + ["--core", "--configdir", str(configdir), "--library", ":memory:",
                  "--conf", "write_sidecar_files=never",
                  "--conf", f"plugins/imageio/format/jpeg/quality={spec.quality}"]


def _profile_description(image: Image.Image) -> str:
    icc = image.info.get("icc_profile")
    if not icc:
        return ""
    return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))


def _verify(produced: Path, spec: RenderSpec, result: subprocess.CompletedProcess) -> None:
    tail = "\n".join((result.stderr or "").strip().splitlines()[-STDERR_TAIL_LINES:])
    if not produced.exists() or produced.stat().st_size == 0:
        raise RenderError(f"darktable-cli produced no image (exit {result.returncode}): {tail}")
    with Image.open(produced) as image:
        width, height = image.size
        if (spec.width and width > spec.width) or (spec.height and height > spec.height):
            raise RenderError(f"output is {width}x{height}, larger than {spec.width}x{spec.height}")
        if spec.icc_type == "SRGB" and "sRGB" not in _profile_description(image):
            raise RenderError("output has no sRGB colour profile; check the --icc-type handling")


def render(raw: Path, xmp_text: str, out: Path, spec: RenderSpec, run=None) -> Path:
    run = run or subprocess.run
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dtk-render-") as tmp_name:
        tmp = Path(tmp_name)
        raw_link = tmp / raw.name
        raw_link.symlink_to(raw.resolve())
        xmp_copy = tmp / (raw.name + ".xmp")
        xmp_copy.write_text(xmp_text, encoding="utf-8")
        configdir = tmp / "config"
        configdir.mkdir()
        produced = tmp / ("render" + (out.suffix or ".jpg"))
        try:
            result = run(build_command(raw_link, xmp_copy, produced, spec, configdir),
                         capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS)
        except FileNotFoundError:
            raise RenderError(f"darktable-cli not found at {cli_path()}; install darktable or set "
                              "DTK_DARKTABLE_CLI to its path") from None
        except subprocess.TimeoutExpired:
            raise RenderError(f"darktable-cli did not finish within {RENDER_TIMEOUT_SECONDS} s; "
                              "check the raw opens in darktable") from None
        _verify(produced, spec, result)
        out.unlink(missing_ok=True)
        shutil.move(str(produced), out)
    return out


def side_by_side(before: Path, after: Path, out: Path) -> Path:
    with Image.open(before) as left_image, Image.open(after) as right_image:
        height = min(left_image.height, right_image.height)
        left = left_image.convert("RGB").resize((left_image.width * height // left_image.height, height))
        right = right_image.convert("RGB").resize((right_image.width * height // right_image.height, height))
    pair = Image.new("RGB", (left.width + GAP_PIXELS + right.width, height), (255, 255, 255))
    pair.paste(left, (0, 0))
    pair.paste(right, (left.width + GAP_PIXELS, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    pair.save(out, "JPEG", quality=90)
    return out
