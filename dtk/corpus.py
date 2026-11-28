"""Corpus gate: a module is editable only when every real blob for it round-trips and stays in range.

Usage: uv run python -m dtk.corpus [--presets FILE] [--sidecars XMP ...] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from dtk.blob import decode_param_string
from dtk.codec import CodecError, decode, encode
from dtk.schemas import SCHEMA_DIR, load_index, load_schema
from dtk.xmp import parse_sidecar

Blob = tuple[str, int, bytes, str]
REPO_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
MAX_PROBLEMS = 10
TOLERANCE = 1e-6


def blobs_from_presets(path: Path) -> list[Blob]:
    return [(row["operation"], row["modversion"], bytes.fromhex(row["params_hex"]), f"preset:{row['name']}")
            for row in json.loads(Path(path).read_text())]


def blobs_from_sidecars(paths) -> list[Blob]:
    found = []
    for path in map(Path, paths):
        for entry in parse_sidecar(path.read_text(encoding="utf-8")).history:
            raw, _ = decode_param_string(entry.params)
            found.append((entry.operation, entry.modversion, raw, f"{path.name}#{entry.num}"))
    return found


def _leaves(fields: list[dict], values: dict, prefix: str = ""):
    for field in fields:
        yield from _leaf_values(field, values[field["name"]], prefix + field["name"])


def _leaf_values(field: dict, value, label: str):
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaf_values(field, item, f"{label}.{index}")
    elif field["kind"] == "struct":
        yield from _leaves(field["fields"], value, label + ".")
    else:
        yield label, field, value


def range_problems(schema: dict, values: dict) -> list[str]:
    problems = []
    for label, field, value in _leaves(schema["fields"], values):
        if isinstance(value, str):
            continue
        if isinstance(value, float) and math.isnan(value):
            problems.append(f"{label} is NaN")
            continue
        if field["kind"] == "prim" and field["ctype"] == "gboolean" and value not in (0, 1):
            problems.append(f"{label}={value} is not a boolean")
        if field["kind"] == "enum":
            numbers = list(field["enum"].values())
            if numbers and None not in numbers and value not in numbers:
                problems.append(f"{label}={value} is not a member")
        low, high = field.get("min"), field.get("max")
        if isinstance(low, (int, float)) and value < low - TOLERANCE:
            problems.append(f"{label}={value} is below {low}")
        if isinstance(high, (int, float)) and value > high + TOLERANCE:
            problems.append(f"{label}={value} is above {high}")
    return problems


def unresolved_limits(fields: list[dict], prefix: str = "") -> list[str]:
    """A limit schemagen could not turn into a number means the range check cannot run: never skip it silently."""
    problems = []
    for field in fields:
        for key in ("min", "max"):
            limit = field.get(key)
            if limit is not None and not isinstance(limit, (int, float)):
                problems.append(f"{prefix}{field['name']}: {key} limit {limit!r} is unresolved")
        problems.extend(unresolved_limits(field.get("fields", []), f"{prefix}{field['name']}."))
    return problems


def evaluate(blobs: list[Blob]) -> dict[str, dict]:
    grouped: dict[str, list[tuple[int, bytes, str]]] = defaultdict(list)
    for module, version, raw, source in blobs:
        grouped[module].append((version, raw, source))
    report = {}
    for module, entry in sorted(load_index().items()):
        if entry["status"] != "ok":
            report[module] = {"status": "unsupported", "version": entry["version"], "blobs": 0,
                              "problems": [entry["reason"]]}
            continue
        schema = load_schema(module, entry["version"])
        current = [(raw, source) for version, raw, source in grouped.get(module, []) if version == entry["version"]]
        unresolved = unresolved_limits(schema["fields"])
        problems: list[str] = list(unresolved)
        for raw, source in current:
            try:
                values = decode(schema, raw)
            except CodecError as exc:
                problems.append(f"{source}: {exc}")
                continue
            if encode(schema, values) != raw:
                problems.append(f"{source}: re-encoding changed the bytes")
            problems.extend(f"{source}: {problem}" for problem in range_problems(schema, values))
        status = "read-only" if unresolved else "no-corpus" if not current else "editable" if not problems else "read-only"
        report[module] = {"status": status, "version": entry["version"], "blobs": len(current),
                          "problems": problems[:MAX_PROBLEMS]}
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m dtk.corpus")
    parser.add_argument("--presets", type=Path, default=REPO_FIXTURES / "preset_params.json")
    parser.add_argument("--sidecars", type=Path, nargs="*",
                        default=sorted((REPO_FIXTURES / "sidecars").glob("*.xmp")))
    parser.add_argument("--out", type=Path, default=SCHEMA_DIR / "corpus.json")
    args = parser.parse_args(argv)
    report = evaluate(blobs_from_presets(args.presets) + blobs_from_sidecars(args.sidecars))
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    counts: dict[str, int] = defaultdict(int)
    for row in report.values():
        counts[row["status"]] += 1
    print(", ".join(f"{count} {status}" for status, count in sorted(counts.items())))
    for module, row in sorted(report.items()):
        if row["status"] == "editable":
            print(f"  editable: {module} ({row['blobs']} blobs)")


if __name__ == "__main__":
    main()
