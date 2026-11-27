"""Load generated params schemas and the corpus report shipped with dtk."""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path

DT_VERSION = "5.6.1"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas" / DT_VERSION


class SchemaMissing(LookupError):
    """No schema exists for this module and version."""


@cache
def load_index() -> dict[str, dict]:
    path = SCHEMA_DIR / "index.json"
    if not path.exists():
        return {}
    return {entry["module"]: entry for entry in json.loads(path.read_text())}


def current_version(module: str) -> int | None:
    entry = load_index().get(module)
    return entry["version"] if entry else None


@cache
def load_schema(module: str, version: int) -> dict:
    path = SCHEMA_DIR / f"{module}.v{version}.json"
    if not path.exists():
        raise SchemaMissing(f"no schema for {module} v{version} (darktable {DT_VERSION})")
    return json.loads(path.read_text())


@cache
def load_corpus_report() -> dict[str, dict]:
    path = SCHEMA_DIR / "corpus.json"
    return json.loads(path.read_text()) if path.exists() else {}


def is_editable(module: str) -> bool:
    return load_corpus_report().get(module, {}).get("status") == "editable"
