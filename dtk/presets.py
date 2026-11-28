"""Named export presets from presets.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from dtk.render import RenderSpec

PRESETS_FILE = Path(__file__).resolve().parent / "presets.toml"
SPEC_KEYS = ("width", "height", "quality", "icc_type", "icc_intent", "hq", "upscale")


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    spec: RenderSpec
    out_dir: str


def _preset(name: str, table: dict) -> Preset:
    spec = RenderSpec(**{key: table[key] for key in SPEC_KEYS if key in table})
    return Preset(name, table.get("description", ""), spec, table.get("out_dir", "{folder}"))


def list_presets() -> list[Preset]:
    tables = tomllib.loads(PRESETS_FILE.read_text())
    return [_preset(name, table) for name, table in sorted(tables.items())]


def load_preset(name: str) -> Preset:
    for preset in list_presets():
        if preset.name == name:
            return preset
    raise LookupError(f"no preset named {name!r}; add it to {PRESETS_FILE}")


def out_dir_for(preset: Preset, raw: Path) -> Path:
    return Path(preset.out_dir.format(folder=raw.parent)).expanduser()
