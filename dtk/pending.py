"""Pending edits: previewed by dtk edit, written by dtk apply."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from dtk.state import state_dir


@dataclass
class PendingEdit:
    id: str
    raw: str
    xmp: str
    original_sha: str
    new_text: str
    diff: list[list]
    preview: str | None
    created: str
    applied: bool = False


def _root(root: Path | None) -> Path:
    return root or state_dir() / "pending"


def new_id(now=None) -> str:
    now = now or datetime.now
    return f"{now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def save(edit: PendingEdit, root: Path | None = None) -> Path:
    path = _root(root) / f"{edit.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(edit), indent=1) + "\n")
    return path


def load(edit_id: str, root: Path | None = None) -> PendingEdit:
    path = _root(root) / f"{edit_id}.json"
    if not path.exists():
        raise LookupError(f"no pending edit {edit_id!r}; run dtk edit first")
    return PendingEdit(**json.loads(path.read_text()))


def mark_applied(edit_id: str, root: Path | None = None) -> None:
    edit = load(edit_id, root)
    edit.applied = True
    save(edit, root)
