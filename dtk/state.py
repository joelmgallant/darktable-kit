"""Where dtk keeps pending edits, previews and backups."""
from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("DTK_STATE_DIR") or "~/.local/state/dtk").expanduser()
