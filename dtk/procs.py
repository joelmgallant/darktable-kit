"""Is darktable running? Exact process name only: a -f pattern can match unrelated processes."""
from __future__ import annotations

import subprocess


def darktable_running(run=None) -> bool:
    run = run or subprocess.run
    return run(["pgrep", "-x", "darktable"], capture_output=True).returncode == 0
