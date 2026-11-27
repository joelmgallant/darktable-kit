"""The only code that writes a real darktable sidecar."""
from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path

from dtk import procs
from dtk.state import state_dir
from dtk.xmp import parse_sidecar


class WriteRefused(RuntimeError):
    """The sidecar was not written."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_xmp(xmp: Path, new_text: str, expected_sha: str, *, is_running=None,
              backup_dir: Path | None = None, now=None) -> Path:
    is_running = is_running or procs.darktable_running
    now = now or datetime.now
    if is_running():
        raise WriteRefused("darktable is running; quit it, then run dtk apply again")
    current = xmp.read_bytes()
    if sha256_bytes(current) != expected_sha:
        raise WriteRefused(f"{xmp.name} changed since the preview; run dtk edit again")
    backup_dir = backup_dir or state_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{xmp.name}.{now():%Y%m%d-%H%M%S-%f}.xmp"
    shutil.copy2(xmp, backup)
    data = new_text.encode("utf-8")
    temp = xmp.with_name(f".{xmp.name}.dtk-tmp")
    temp.write_bytes(data)
    os.replace(temp, xmp)
    written = xmp.read_bytes()
    if written != data:
        raise WriteRefused(f"{xmp.name} did not read back as written; restore from {backup}")
    parse_sidecar(written.decode("utf-8"))
    return backup
