"""Turn a command-line image argument into the raw file and its sidecar."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dtk.library import image_by_id


class ImageNotFound(LookupError):
    """The image or its sidecar does not exist."""


@dataclass(frozen=True)
class ImageFiles:
    raw: Path
    xmp: Path


def resolve_image(arg: str, library_snapshot: Callable[[], Path]) -> ImageFiles:
    if arg.isdigit():
        raw = image_by_id(library_snapshot(), int(arg)).path
    else:
        raw = Path(arg).expanduser()
        if raw.suffix.lower() == ".xmp":
            raw = raw.with_suffix("")
    if not raw.exists():
        raise ImageNotFound(f"{raw} does not exist")
    xmp = raw.with_name(raw.name + ".xmp")
    if not xmp.exists():
        raise ImageNotFound(f"{raw.name} has no sidecar at {xmp}; import it into darktable first")
    return ImageFiles(raw=raw, xmp=xmp)
