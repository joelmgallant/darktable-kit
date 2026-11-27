"""Generate dtk params schemas from a darktable source checkout.

Usage: uv run python -m schemagen.build [--src ~/git/github/darktable-org/darktable] [--out dtk/schemas/5.6.1]
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from dtk.codec import PRIMS, CodecError, struct_size
from schemagen.ctext import (ParseError, eval_int, find_aliases, find_defines, find_typedefs, parse_annotations,
                             parse_enum_body, parse_struct_body, resolve_ints)

INTROSPECTION_RE = re.compile(r"^DT_MODULE_INTROSPECTION\(\s*(\d+)\s*,\s*([A-Za-z_]\w*)\s*\)", re.M)
NUMBER_RE = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?[fF]?")
DEFAULT_SRC = Path("~/git/github/darktable-org/darktable").expanduser()
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "dtk" / "schemas" / "5.6.1"
MAX_NESTING = 8


class Unsupported(Exception):
    """The params struct uses a type or construct dtk cannot lay out."""


@dataclass
class TypeTable:
    blocks: dict[str, tuple[str, str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    defines: dict[str, str] = field(default_factory=dict)

    def add_source(self, src: str) -> None:
        self.blocks.update(find_typedefs(src))
        self.aliases.update(find_aliases(src))
        self.defines.update(find_defines(src))

    def overlay(self, src: str) -> "TypeTable":
        combined = TypeTable(dict(self.blocks), dict(self.aliases), dict(self.defines))
        combined.add_source(src)
        return combined


def int_names(table: TypeTable, seed: dict[str, int]) -> dict[str, int]:
    names = resolve_ints(table.defines, seed)
    for kind, body in table.blocks.values():
        if kind != "enum":
            continue
        try:
            members = parse_enum_body(body, names)
        except ParseError:
            continue
        names.update({member: value for member, value in members.items() if value is not None})
    return names


def _normalize(ctype: str) -> str:
    return " ".join(re.sub(r"^const\s+", "", ctype).split())


def _resolve_alias(ctype: str, table: TypeTable) -> str:
    for _ in range(10):
        if ctype in PRIMS or ctype not in table.aliases:
            return ctype
        ctype = _normalize(table.aliases[ctype])
    raise Unsupported(f"alias loop at {ctype}")


def annotation_value(text: str | None, names: dict[str, int], members: dict[str, int | None]):
    if text is None:
        return None
    if text in members:
        return text
    if text in ("TRUE", "FALSE"):
        return int(text == "TRUE")
    if NUMBER_RE.fullmatch(text):
        literal = text.rstrip("fF")
        return int(literal) if re.fullmatch(r"[-+]?\d+", literal) else float(literal)
    value = eval_int(text, names)
    return value if value is not None else text


def _struct_fields(name: str, table: TypeTable, names: dict[str, int], depth: int) -> list[dict]:
    if depth > MAX_NESTING:
        raise Unsupported(f"{name}: nesting deeper than {MAX_NESTING}")
    block = table.blocks.get(name)
    if block is None or block[0] != "struct":
        raise Unsupported(f"unknown struct {name}")
    return [_field(raw, table, names, depth) for raw in parse_struct_body(block[1])]


def _field(raw, table: TypeTable, names: dict[str, int], depth: int) -> dict:
    ctype = _resolve_alias(_normalize(raw.ctype), table)
    dims = []
    for expr in raw.dims:
        size = eval_int(expr, names)
        if size is None or size <= 0:
            raise Unsupported(f"{raw.name}: cannot size array [{expr}]")
        dims.append(size)
    notes = parse_annotations(raw.note)
    result = {"name": raw.name, "ctype": ctype, "dims": dims, "description": notes.get("description")}
    members: dict[str, int | None] = {}
    block_kind = table.blocks.get(ctype, ("", ""))[0]
    if ctype in PRIMS:
        result["kind"] = "prim"
    elif block_kind == "enum":
        members = parse_enum_body(table.blocks[ctype][1], names)
        result.update(kind="enum", enum=members)
    elif block_kind == "struct":
        result.update(kind="struct", fields=_struct_fields(ctype, table, names, depth + 1))
    else:
        raise Unsupported(f"{raw.name}: unknown type {raw.ctype}")
    for key in ("min", "max", "default"):
        result[key] = annotation_value(notes.get(key), names, members)
    return result


def build_module_schema(module: str, src: str, shared: TypeTable, shared_names: dict[str, int]) -> dict | None:
    match = INTROSPECTION_RE.search(src)
    if not match:
        return None
    version, struct_name = int(match.group(1)), match.group(2)
    local = TypeTable()
    local.add_source(src)
    table = shared.overlay(src)
    names = int_names(local, shared_names)
    schema = {"module": module, "version": version, "struct": struct_name,
              "status": "ok", "reason": None, "size": None, "fields": []}
    try:
        schema["fields"] = _struct_fields(struct_name, table, names, 0)
        schema["size"] = struct_size(schema)
    except (Unsupported, ParseError, CodecError) as exc:
        schema.update(status="unsupported", reason=str(exc), fields=[])
    return schema


def generate(src_root: Path, out_dir: Path) -> list[dict]:
    shared = TypeTable()
    for header in sorted((src_root / "src").rglob("*.h")):
        if "external" in header.parts or "tests" in header.parts:
            continue
        shared.add_source(header.read_text(errors="replace"))
    shared_names = int_names(shared, {})
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.v*.json"):
        stale.unlink()
    index = []
    for module_file in sorted((src_root / "src" / "iop").glob("*.c")):
        schema = build_module_schema(module_file.stem, module_file.read_text(errors="replace"), shared, shared_names)
        if schema is None:
            continue
        (out_dir / f"{schema['module']}.v{schema['version']}.json").write_text(json.dumps(schema, indent=1) + "\n")
        index.append({key: schema[key] for key in ("module", "version", "struct", "status", "reason", "size")})
    (out_dir / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    return index


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m schemagen.build")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    index = generate(args.src, args.out)
    supported = [entry for entry in index if entry["status"] == "ok"]
    print(f"{len(index)} modules: {len(supported)} ok, {len(index) - len(supported)} unsupported")
    for entry in index:
        if entry["status"] != "ok":
            print(f"  {entry['module']}: {entry['reason']}")


if __name__ == "__main__":
    main()
