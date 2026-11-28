"""Turn a command-line image argument into the raw file and the sidecar of one darktable version."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dtk.library import image_by_id

DUPLICATE_STEM_RE = re.compile(r"^(?P<base>.+)_(?P<digits>\d{2,4})$")


class ImageNotFound(LookupError):
    """The image or its sidecar does not exist."""


@dataclass(frozen=True)
class ImageFiles:
    raw: Path
    xmp: Path
    version: int = 0


def versioned_name(name: str, version: int) -> str:
    """darktable's dt_image_path_append_version_no_db: version 0 unchanged, else "_%02d" before the last '.'."""
    if version <= 0:
        return name
    stem, dot, extension = name.rpartition(".")
    return f"{stem}_{version:02d}{dot}{extension}" if dot else f"{name}_{version:02d}"


def sidecar_path(raw: Path, version: int) -> Path:
    return raw.with_name(versioned_name(raw.name, version) + ".xmp")


def _from_sidecar_path(xmp: Path) -> tuple[Path, int]:
    """Raw and version for a sidecar path. A raw that exists under the plain name wins (version 0)."""
    named = xmp.with_suffix("")
    if named.exists():
        return named, 0
    duplicate = DUPLICATE_STEM_RE.match(Path(named.name).stem)
    if duplicate:
        version = int(duplicate["digits"])
        raw = named.with_name(duplicate["base"] + named.suffix)
        if version > 0 and f"{version:02d}" == duplicate["digits"] and raw.exists():
            return raw, version
    return named, 0


def resolve_image(arg: str, library_snapshot: Callable[[], Path]) -> ImageFiles:
    version = 0
    if arg.isdigit():
        image = image_by_id(library_snapshot(), int(arg))
        raw, version = image.path, image.version
    else:
        raw = Path(arg).expanduser()
        if raw.suffix.lower() == ".xmp":
            raw, version = _from_sidecar_path(raw)
    if not raw.exists():
        raise ImageNotFound(f"{raw} does not exist")
    xmp = sidecar_path(raw, version)
    if not xmp.exists():
        raise ImageNotFound(f"{raw.name} has no sidecar at {xmp}; import it into darktable first")
    return ImageFiles(raw=raw, xmp=xmp, version=version)
