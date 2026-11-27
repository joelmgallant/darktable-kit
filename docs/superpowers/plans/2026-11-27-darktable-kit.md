# darktable-kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `dtk`, a CLI that queries the darktable library, batch-exports with named presets, and previews/applies module edits by writing darktable XMP sidecars, as specified in `docs/superpowers/specs/2026-11-27-darktable-kit-design.md`.

**Architecture:** A generator (`schemagen/`) reads darktable's C source at tag `release-5.6.1` and writes one JSON schema per iop module. A generic codec (`dtk/codec.py`) turns params blobs into dicts and back using those schemas. A corpus gate (`dtk/corpus.py`) marks a module editable only when every real blob for it round-trips byte-for-byte and every annotated value is in range. Edits append a history entry to a copy of the sidecar, render a before/after with `darktable-cli`, and only `dtk/writer.py` ever writes a real sidecar.

**Tech Stack:** Python 3.12, uv, pytest, hatchling, Pillow. No other runtime dependencies.

## Global Constraints

- Python `>=3.12,<3.13`; package manager `uv`; tests `uv run pytest`; build backend hatchling. Match `~/Desktop/digikam-people` layout.
- darktable version is `5.6.1`. Schemas live in `dtk/schemas/5.6.1/` (inside the package so they ship with it; the spec's `schemas/<dt-version>/` means this directory).
- darktable source checkout: `~/git/github/darktable-org/darktable` at tag `release-5.6.1`, cloned with `git clone --depth 1 --branch release-5.6.1 https://github.com/darktable-org/darktable.git ~/git/github/darktable-org/darktable`.
- `dtk/writer.py` is the only code that writes a real XMP sidecar. Nothing writes `library.db` or `data.db`; those are read from a temp copy.
- Every darktable-cli run uses a temp dir with a symlink to the raw and a copy of the XMP, a temp `--configdir`, `--library :memory:` and `--conf write_sidecar_files=never`.
- A render is successful only when the output file exists, fits the requested width/height, and has an sRGB ICC profile when sRGB was requested. Exit codes are not trusted.
- Detect a running darktable with `pgrep -x darktable` only. Never use `pgrep -f`/`pkill -f`.
- Every refusal is one sentence naming the reason and the fix, printed as `dtk: <message>` on stderr with exit code 1.
- Tests never touch the real library or real sidecars. Opt-in markers: `corpus` and `darktable` (Mac only, need the real files / darktable.app). The default `pytest` run excludes them and must pass on Linux.
- Fixtures already committed: `tests/fixtures/sidecars/sidecar_01..09.xmp` (9 real sidecars, GPS/paths scrubbed), `tests/fixtures/preset_params.json` (248 built-in darktable preset blobs, 35 modules, fields `name, operation, modversion, params_hex`), `tests/fixtures/library_schema.sql`, `tests/fixtures/data_tags_schema.sql`.
- Verified facts (do not re-derive): XMP `gz` params are `"gz%02d" % min(len(raw)//len(zlib.compress(raw)) + 1, 99)` + base64(`zlib.compress(raw)`) and re-encode byte-exact (142/142 real entries). Exposure v7 params hex `00000000000080b9f828fc3f00004842000080c00100000001000000` decode to exposure = 1.97 (float32 at offset 8). darktable `datetime_taken` is microseconds since 0001-01-01. Rating is `flags & 7` (6 = rejected), and flag `8` also means rejected. An image is edited when `history_hash.current_hash` differs from both `basic_hash` and `auto_hash`.
- Modules over 200 lines get split; names stay descriptive, including callback parameters.
- Commit after every task with a conventional message ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore` | Project config (Task 1) |
| `dtk/codec.py` | Layout + decode/encode of params structs from a schema |
| `dtk/blob.py` | XMP params string (hex / gz) <-> bytes |
| `schemagen/ctext.py` | Scanning C text: comments, braces, typedefs, defines, struct bodies, enums, annotations |
| `schemagen/build.py` | Build module schemas from a darktable checkout, write `dtk/schemas/5.6.1/` |
| `dtk/schemas.py` | Load index, schemas, corpus report |
| `dtk/corpus.py` | Corpus gate, writes `dtk/schemas/5.6.1/corpus.json` |
| `dtk/xmp.py` | Parse sidecar history; produce sidecar text with appended entries |
| `dtk/library.py` | Read-only library queries on a snapshot |
| `dtk/images.py` | Resolve `<image>` argument to raw + sidecar paths |
| `dtk/render.py` | darktable-cli wrapper, output verification, side-by-side |
| `dtk/presets.py`, `dtk/presets.toml` | Named export presets |
| `dtk/state.py`, `dtk/procs.py` | State dir; darktable-running check |
| `dtk/writer.py` | Only writer of real sidecars |
| `dtk/pending.py` | Pending edit records |
| `dtk/values.py` | Apply one `--set` change to decoded values, with validation |
| `dtk/editing.py` | Plan an edit: select instance, apply changes, build new sidecar |
| `dtk/commands.py`, `dtk/cli.py` | Command implementations; argparse entry point |
| `CLAUDE.md`, `README.md` | Rules for agents; usage |
| `tests/test_mac_live.py` | Opt-in Mac checks |

---

### Task 1: Scaffold and params codec

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `dtk/__init__.py`, `dtk/codec.py`
- Test: `tests/test_codec.py`, `tests/schema_helpers.py`

**Interfaces:**
- Produces: `dtk.codec.PRIMS: dict[str, tuple[str, int]]`, `CodecError(ValueError)`, `layout(fields) -> tuple[list[int], int]`, `struct_size(schema: dict) -> int`, `decode(schema: dict, blob: bytes) -> dict`, `encode(schema: dict, values: dict, base: bytes | None = None) -> bytes`, `enum_value(field: dict, name: str) -> int`.
- Schema shape (produced by schemagen in Task 4, used everywhere): `{"module": str, "version": int, "struct": str, "status": "ok"|"unsupported", "reason": str|None, "size": int|None, "fields": [field]}`; field = `{"name", "kind": "prim"|"enum"|"struct", "ctype", "dims": [int], "min", "max", "default", "description", "enum": {name: int|None} (enum only), "fields": [field] (struct only)}`.

- [ ] **Step 1: Write project config**

`pyproject.toml`:
```toml
[project]
name = "darktable-kit"
version = "0.1.0"
description = "Query, export and edit darktable photos from the terminal"
requires-python = ">=3.12,<3.13"
dependencies = ["pillow>=11"]

[project.scripts]
dtk = "dtk.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["dtk", "schemagen"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "corpus: reads the real darktable library and sidecars on Joel's Mac (opt-in: pytest -m corpus)",
  "darktable: runs the real darktable-cli on Joel's Mac (opt-in: pytest -m darktable)",
]
addopts = "-m 'not corpus and not darktable'"
```

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

`dtk/__init__.py`:
```python
"""darktable-kit: query, export and edit darktable photos from the terminal."""
```

- [ ] **Step 2: Write test helpers and failing tests**

`tests/schema_helpers.py`:
```python
"""Hand-written schemas for unit tests, independent of generated files."""


def prim(name, ctype, dims=(), lo=None, hi=None):
    return {"name": name, "kind": "prim", "ctype": ctype, "dims": list(dims),
            "min": lo, "max": hi, "default": None, "description": None}


def enum(name, members, dims=()):
    return {"name": name, "kind": "enum", "ctype": "test_enum_t", "dims": list(dims), "enum": dict(members),
            "min": None, "max": None, "default": None, "description": None}


def nested(name, fields, dims=()):
    return {"name": name, "kind": "struct", "ctype": "test_struct_t", "dims": list(dims), "fields": fields,
            "min": None, "max": None, "default": None, "description": None}


def schema(module, fields, version=1):
    return {"module": module, "version": version, "struct": f"dt_iop_{module}_params_t",
            "status": "ok", "reason": None, "size": None, "fields": fields}


EXPOSURE_V7 = schema("exposure", [
    enum("mode", {"EXPOSURE_MODE_MANUAL": 0, "EXPOSURE_MODE_DEFLICKER": 1}),
    prim("black", "float", lo=-1.0, hi=1.0),
    prim("exposure", "float", lo=-18.0, hi=18.0),
    prim("deflicker_percentile", "float", lo=0.0, hi=100.0),
    prim("deflicker_target_level", "float", lo=-18.0, hi=18.0),
    prim("compensate_exposure_bias", "gboolean"),
    prim("compensate_hilite_pres", "gboolean"),
], version=7)

EXPOSURE_V7_HEX = "00000000000080b9f828fc3f00004842000080c00100000001000000"
```

`tests/test_codec.py`:
```python
import pytest

from dtk.codec import CodecError, decode, encode, layout, struct_size
from tests.schema_helpers import EXPOSURE_V7, EXPOSURE_V7_HEX, enum, nested, prim, schema


def test_exposure_v7_decodes_the_spike_blob():
    values = decode(EXPOSURE_V7, bytes.fromhex(EXPOSURE_V7_HEX))
    assert struct_size(EXPOSURE_V7) == 28
    assert values["mode"] == 0
    assert values["exposure"] == pytest.approx(1.97, abs=1e-5)
    assert values["deflicker_percentile"] == 50.0
    assert values["compensate_hilite_pres"] == 1


def test_round_trip_is_byte_exact():
    blob = bytes.fromhex(EXPOSURE_V7_HEX)
    assert encode(EXPOSURE_V7, decode(EXPOSURE_V7, blob)) == blob


def test_char_then_float_pads_to_four():
    offsets, size = layout([prim("flag", "uint8_t"), prim("value", "float")])
    assert offsets == [0, 4]
    assert size == 8


def test_double_aligns_to_eight_and_pads_the_tail():
    offsets, size = layout([prim("count", "int"), prim("value", "double"), prim("tail", "int")])
    assert offsets == [0, 8, 16]
    assert size == 24


def test_multi_dimensional_arrays_decode_as_nested_lists():
    sch = schema("grid", [prim("cells", "float", dims=(2, 3))])
    blob = encode(sch, {"cells": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]})
    assert len(blob) == 24
    assert decode(sch, blob)["cells"][1][2] == 6.0


def test_arrays_of_structs():
    node = [prim("x", "float"), prim("y", "float")]
    sch = schema("curve", [nested("nodes", node, dims=(2,)), prim("count", "int")])
    values = {"nodes": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.25}], "count": 2}
    assert struct_size(sch) == 20
    assert decode(sch, encode(sch, values)) == values


def test_enum_accepts_member_names():
    sch = schema("e", [enum("mode", {"A": 0, "B": 7})])
    assert decode(sch, encode(sch, {"mode": "B"}))["mode"] == 7


def test_unknown_enum_name_is_refused():
    sch = schema("e", [enum("mode", {"A": 0})])
    with pytest.raises(CodecError, match="unknown member 'Z'"):
        encode(sch, {"mode": "Z"})


def test_size_mismatch_is_refused():
    with pytest.raises(CodecError, match="blob is 4 bytes, schema expects 28"):
        decode(EXPOSURE_V7, b"\0\0\0\0")


def test_base_preserves_padding_bytes():
    sch = schema("pad", [prim("flag", "uint8_t"), prim("value", "float")])
    base = bytes([1, 0xAA, 0xAA, 0xAA]) + bytes(4)
    out = encode(sch, {"flag": 1, "value": 2.0}, base=base)
    assert out[1:4] == b"\xaa\xaa\xaa"
    assert decode(sch, out)["value"] == 2.0


def test_char_arrays_decode_as_text():
    sch = schema("named", [prim("label", "char", dims=(8,))])
    blob = encode(sch, {"label": "abc"})
    assert blob == b"abc" + bytes(5)
    assert decode(sch, blob)["label"] == "abc"


def test_char_array_overflow_is_refused():
    sch = schema("named", [prim("label", "char", dims=(4,))])
    with pytest.raises(CodecError, match="longer than 3 bytes"):
        encode(sch, {"label": "abcd"})
```

Also create an empty `tests/__init__.py` so `tests.schema_helpers` imports.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_codec.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.codec'`.

- [ ] **Step 4: Implement `dtk/codec.py`**

```python
"""Schema-driven codec for darktable iop params structs.

Layout rules: little-endian, natural C alignment, every struct padded to a
multiple of its largest member's alignment. Schemas come from schemagen.
"""
from __future__ import annotations

import math
import struct
from typing import Any

PRIMS: dict[str, tuple[str, int]] = {
    "float": ("f", 4), "double": ("d", 8),
    "int": ("i", 4), "int32_t": ("i", 4), "gint": ("i", 4), "gboolean": ("i", 4),
    "unsigned int": ("I", 4), "uint32_t": ("I", 4), "guint": ("I", 4), "unsigned": ("I", 4),
    "int16_t": ("h", 2), "short": ("h", 2), "uint16_t": ("H", 2), "unsigned short": ("H", 2),
    "char": ("b", 1), "gchar": ("b", 1), "int8_t": ("b", 1), "signed char": ("b", 1),
    "uint8_t": ("B", 1), "unsigned char": ("B", 1), "guchar": ("B", 1),
    "int64_t": ("q", 8), "uint64_t": ("Q", 8),
}
CHAR_TYPES = frozenset({"char", "gchar"})
ENUM_FORMAT = ("i", 4)


class CodecError(ValueError):
    """A blob does not fit its schema, or a value cannot be encoded."""


def _round_up(offset: int, align: int) -> int:
    return (offset + align - 1) // align * align


def _element_count(dims: list[int]) -> int:
    return math.prod(dims) if dims else 1


def _scalar_format(field: dict) -> tuple[str, int]:
    if field["kind"] == "enum":
        return ENUM_FORMAT
    try:
        return PRIMS[field["ctype"]]
    except KeyError:
        raise CodecError(f"no binary format for C type {field['ctype']!r}") from None


def field_align(field: dict) -> int:
    if field["kind"] == "struct":
        return max((field_align(sub) for sub in field["fields"]), default=1)
    return _scalar_format(field)[1]


def element_size(field: dict) -> int:
    if field["kind"] == "struct":
        return layout(field["fields"])[1]
    return _scalar_format(field)[1]


def layout(fields: list[dict]) -> tuple[list[int], int]:
    """Return (offset of each field, padded total size)."""
    offset, struct_align, offsets = 0, 1, []
    for field in fields:
        align = field_align(field)
        offset = _round_up(offset, align)
        offsets.append(offset)
        offset += element_size(field) * _element_count(field["dims"])
        struct_align = max(struct_align, align)
    return offsets, _round_up(offset, struct_align)


def struct_size(schema: dict) -> int:
    return layout(schema["fields"])[1]


def _is_char_array(field: dict, dims: list[int]) -> bool:
    return field["kind"] == "prim" and field["ctype"] in CHAR_TYPES and len(dims) == 1


def decode(schema: dict, blob: bytes) -> dict[str, Any]:
    expected = struct_size(schema)
    if len(blob) != expected:
        raise CodecError(f"{schema['module']} v{schema['version']}: blob is {len(blob)} bytes, "
                         f"schema expects {expected}")
    return _decode_fields(schema["fields"], blob, 0)


def _decode_fields(fields: list[dict], buf: bytes, base: int) -> dict[str, Any]:
    offsets, _ = layout(fields)
    return {field["name"]: _decode_value(field, buf, base + offset, field["dims"])
            for field, offset in zip(fields, offsets)}


def _decode_value(field: dict, buf: bytes, offset: int, dims: list[int]) -> Any:
    if dims and _is_char_array(field, dims):
        return bytes(buf[offset:offset + dims[0]]).split(b"\0", 1)[0].decode("latin-1")
    if dims:
        stride = element_size(field) * _element_count(dims[1:])
        return [_decode_value(field, buf, offset + index * stride, dims[1:]) for index in range(dims[0])]
    if field["kind"] == "struct":
        return _decode_fields(field["fields"], buf, offset)
    fmt, _ = _scalar_format(field)
    return struct.unpack_from("<" + fmt, buf, offset)[0]


def encode(schema: dict, values: dict[str, Any], base: bytes | None = None) -> bytes:
    size = struct_size(schema)
    if base is not None and len(base) != size:
        raise CodecError(f"{schema['module']}: base blob is {len(base)} bytes, schema expects {size}")
    buf = bytearray(base) if base is not None else bytearray(size)
    _encode_fields(schema["fields"], values, buf, 0)
    return bytes(buf)


def _encode_fields(fields: list[dict], values: dict[str, Any], buf: bytearray, base: int) -> None:
    offsets, _ = layout(fields)
    for field, offset in zip(fields, offsets):
        if field["name"] not in values:
            raise CodecError(f"missing value for field {field['name']!r}")
        _encode_value(field, values[field["name"]], buf, base + offset, field["dims"])


def _encode_value(field: dict, value: Any, buf: bytearray, offset: int, dims: list[int]) -> None:
    if dims and _is_char_array(field, dims):
        data = str(value).encode("latin-1")
        if len(data) >= dims[0]:
            raise CodecError(f"{field['name']}: text longer than {dims[0] - 1} bytes")
        buf[offset:offset + dims[0]] = data + bytes(dims[0] - len(data))
        return
    if dims:
        if len(value) != dims[0]:
            raise CodecError(f"{field['name']}: expected {dims[0]} items, got {len(value)}")
        stride = element_size(field) * _element_count(dims[1:])
        for index, item in enumerate(value):
            _encode_value(field, item, buf, offset + index * stride, dims[1:])
        return
    if field["kind"] == "struct":
        _encode_fields(field["fields"], value, buf, offset)
        return
    if field["kind"] == "enum" and isinstance(value, str):
        value = enum_value(field, value)
    fmt, _ = _scalar_format(field)
    try:
        struct.pack_into("<" + fmt, buf, offset, float(value) if fmt in "fd" else int(value))
    except struct.error as exc:
        raise CodecError(f"{field['name']}: {exc}") from None


def enum_value(field: dict, name: str) -> int:
    members = field.get("enum") or {}
    if members.get(name) is None:
        known = ", ".join(member for member, number in members.items() if number is not None)
        raise CodecError(f"{field['name']}: unknown member {name!r}; known: {known}")
    return members[name]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_codec.py -v`
Expected: 12 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore uv.lock dtk/__init__.py dtk/codec.py tests/__init__.py tests/schema_helpers.py tests/test_codec.py
git commit -m "feat: schema-driven params codec"
```

---

### Task 2: XMP params strings (hex and gz)

**Files:**
- Create: `dtk/blob.py`
- Test: `tests/test_blob.py`

**Interfaces:**
- Produces: `BlobError(ValueError)`, `decode_param_string(text: str) -> tuple[bytes, str]` (format is `"hex"` or `"gz"`), `encode_param_string(raw: bytes, fmt: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_blob.py`:
```python
import re
from pathlib import Path

import pytest

from dtk.blob import BlobError, decode_param_string, encode_param_string

SIDECARS = sorted((Path(__file__).parent / "fixtures" / "sidecars").glob("*.xmp"))
PARAM_RE = re.compile(r'darktable:(?:params|blendop_params)="([^"]*)"')


def test_hex_round_trip():
    raw, fmt = decode_param_string("0000c03f")
    assert (raw, fmt) == (bytes.fromhex("0000c03f"), "hex")
    assert encode_param_string(raw, fmt) == "0000c03f"


def test_every_real_params_string_re_encodes_exactly():
    strings = [s for path in SIDECARS for s in PARAM_RE.findall(path.read_text())]
    assert len(strings) > 200
    for text in strings:
        raw, fmt = decode_param_string(text)
        assert encode_param_string(raw, fmt) == text


def test_gz_factor_matches_darktable():
    raw = bytes(400)
    text = encode_param_string(raw, "gz")
    assert text.startswith("gz")
    assert decode_param_string(text) == (raw, "gz")


def test_garbage_is_refused():
    with pytest.raises(BlobError):
        decode_param_string("zz-not-hex")


def test_unknown_format_is_refused():
    with pytest.raises(BlobError):
        encode_param_string(b"", "base85")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_blob.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.blob'`.

- [ ] **Step 3: Implement `dtk/blob.py`**

```python
"""darktable XMP params strings: lowercase hex, or gz<NN> + base64(zlib)."""
from __future__ import annotations

import base64
import binascii
import re
import zlib

_GZ_RE = re.compile(r"gz(\d\d)(.+)", re.S)


class BlobError(ValueError):
    """A params string is not valid hex or gz."""


def decode_param_string(text: str) -> tuple[bytes, str]:
    if text.startswith("gz"):
        match = _GZ_RE.fullmatch(text)
        if not match:
            raise BlobError(f"malformed gz params string {text[:16]!r}")
        try:
            return zlib.decompress(base64.b64decode(match.group(2))), "gz"
        except (binascii.Error, zlib.error) as exc:
            raise BlobError(f"cannot inflate gz params string: {exc}") from None
    try:
        return bytes.fromhex(text), "hex"
    except ValueError:
        raise BlobError(f"params string is neither hex nor gz: {text[:16]!r}") from None


def encode_param_string(raw: bytes, fmt: str) -> str:
    if fmt == "hex":
        return raw.hex()
    if fmt == "gz":
        packed = zlib.compress(raw)
        factor = min(len(raw) // len(packed) + 1, 99)
        return f"gz{factor:02d}" + base64.b64encode(packed).decode("ascii")
    raise BlobError(f"unknown params format {fmt!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_blob.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add dtk/blob.py tests/test_blob.py
git commit -m "feat: XMP params string encoding (hex and gz)"
```

---

### Task 3: C text scanning for schemagen

**Files:**
- Create: `schemagen/__init__.py` (empty docstring), `schemagen/ctext.py`
- Test: `tests/test_ctext.py`

**Interfaces:**
- Produces: `ParseError(ValueError)`, `RawField(ctype: str, name: str, dims: tuple[str, ...], note: str)`, `strip_comments(text) -> str`, `match_brace(text, open_index) -> int`, `find_typedefs(src) -> dict[str, tuple[str, str]]` (name -> (`"struct"|"enum"`, body)), `find_aliases(src) -> dict[str, str]`, `find_defines(src) -> dict[str, str]`, `eval_int(expr, names: dict[str, int]) -> int | None`, `resolve_ints(exprs: dict[str, str], seed: dict[str, int]) -> dict[str, int]`, `parse_struct_body(body) -> list[RawField]`, `parse_annotations(note) -> dict[str, str]` (keys `min`, `max`, `default`, `description`), `parse_enum_body(body, known: dict[str, int]) -> dict[str, int | None]`.

Facts about darktable source this must handle (verified in `src/iop/*.c` at `release-5.6.1`):
- The params typedef is at column 0: `typedef struct dt_iop_exposure_params_t\n{ ... } dt_iop_exposure_params_t;`. Legacy `dt_iop_*_params_vN_t` structs are indented inside functions and must be ignored (only `^typedef` at column 0 counts).
- Annotations follow the field on the same line as `// $MIN: -18.0 $MAX: 18.0 $DEFAULT: 0.0 $DESCRIPTION: "black level correction"`, or in a `/* ... */` block that starts on that line and can span lines (basecurve: `int exposure_fusion;    /* number of exposure fusion steps\n   $DEFAULT: 0 $DESCRIPTION: "fusion" */`).
- Array sizes use macros: `dt_iop_basecurve_node_t basecurve[3][MAXNODES];` with `#define MAXNODES 20`.
- Enum members may carry `// $DESCRIPTION:` comments and explicit values.

- [ ] **Step 1: Write the failing tests**

`tests/test_ctext.py`:
```python
import pytest

from schemagen.ctext import (ParseError, eval_int, find_aliases, find_defines, find_typedefs, parse_annotations,
                             parse_enum_body, parse_struct_body, resolve_ints)

EXPOSURE_SRC = '''
typedef enum dt_iop_exposure_mode_t
{
  EXPOSURE_MODE_MANUAL,   // $DESCRIPTION: "manual"
  EXPOSURE_MODE_DEFLICKER // $DESCRIPTION: "automatic"
} dt_iop_exposure_mode_t;

typedef struct dt_iop_exposure_params_t
{
  dt_iop_exposure_mode_t mode;      // $DEFAULT: EXPOSURE_MODE_MANUAL
  float black;                      // $MIN: -1.0 $MAX: 1.0 $DEFAULT: 0.0 $DESCRIPTION: "black level correction"
  float exposure;                   // $MIN: -18.0 $MAX: 18.0 $DEFAULT: 0.0
  gboolean compensate_exposure_bias;// $DEFAULT: FALSE $DESCRIPTION: "compensate exposure bias"
} dt_iop_exposure_params_t;

int legacy_params(void)
{
  typedef struct dt_iop_exposure_params_v6_t
  {
    float black;
  } dt_iop_exposure_params_v6_t;
}
'''

BASECURVE_SRC = '''
#define MAXNODES 20
typedef struct dt_iop_basecurve_node_t
{
  float x; // $MIN: 0.0 $MAX: 1.0
  float y; // $MIN: 0.0 $MAX: 1.0
} dt_iop_basecurve_node_t;

typedef struct dt_iop_basecurve_params_t
{
  // three curves (c, ., .) with max number of nodes
  dt_iop_basecurve_node_t basecurve[3][MAXNODES];
  int basecurve_nodes[3]; // $MIN: 0 $MAX: MAXNODES $DEFAULT: 0
  int exposure_fusion;    /* number of exposure fusion steps
                             $DEFAULT: 0 $DESCRIPTION: "fusion" */
  float exposure_stops;   /* number of stops between fusion images
                             $MIN: 0.01 $MAX: 4.0 $DEFAULT: 1.0 $DESCRIPTION: "exposure shift" */
} dt_iop_basecurve_params_t;
'''


def test_find_typedefs_ignores_indented_legacy_structs():
    found = find_typedefs(EXPOSURE_SRC)
    assert set(found) == {"dt_iop_exposure_mode_t", "dt_iop_exposure_params_t"}
    assert found["dt_iop_exposure_mode_t"][0] == "enum"
    assert found["dt_iop_exposure_params_t"][0] == "struct"


def test_struct_fields_and_trailing_annotations():
    body = find_typedefs(EXPOSURE_SRC)["dt_iop_exposure_params_t"][1]
    fields = parse_struct_body(body)
    assert [(f.ctype, f.name) for f in fields] == [
        ("dt_iop_exposure_mode_t", "mode"), ("float", "black"), ("float", "exposure"),
        ("gboolean", "compensate_exposure_bias")]
    assert parse_annotations(fields[1].note) == {
        "min": "-1.0", "max": "1.0", "default": "0.0", "description": "black level correction"}
    assert parse_annotations(fields[0].note) == {"default": "EXPOSURE_MODE_MANUAL"}


def test_block_comment_annotations_span_lines():
    body = find_typedefs(BASECURVE_SRC)["dt_iop_basecurve_params_t"][1]
    fields = {f.name: f for f in parse_struct_body(body)}
    assert fields["basecurve"].dims == ("3", "MAXNODES")
    assert parse_annotations(fields["exposure_fusion"].note) == {"default": "0", "description": "fusion"}
    assert parse_annotations(fields["exposure_stops"].note)["max"] == "4.0"
    assert parse_annotations(fields["basecurve_nodes"].note)["max"] == "MAXNODES"


def test_defines_and_int_expressions():
    defines = find_defines(BASECURVE_SRC + "\n#define TWICE (MAXNODES * 2) // comment\n#define F(x) x\n")
    assert defines == {"MAXNODES": "20", "TWICE": "(MAXNODES * 2)"}
    assert resolve_ints(defines, {}) == {"MAXNODES": 20, "TWICE": 40}
    assert eval_int("0x10 + 2U", {}) == 18
    assert eval_int("UNKNOWN + 1", {}) is None
    assert eval_int("7 / 2", {}) == 3


def test_enum_values_implicit_and_explicit():
    body = "A, B = 5, C, // $DESCRIPTION: \"c\"\n D = A | 8, E = MISSING, F"
    assert parse_enum_body(body, {}) == {"A": 0, "B": 5, "C": 6, "D": 8, "E": None, "F": None}


def test_scalar_aliases():
    src = "typedef int32_t dt_imgid_t;\ntypedef struct foo foo;\ntypedef unsigned int uint;\n"
    assert find_aliases(src) == {"dt_imgid_t": "int32_t", "uint": "unsigned int"}


def test_multiple_declarators():
    fields = parse_struct_body("float x, y[2]; // $MIN: 0\n")
    assert [(f.name, f.dims) for f in fields] == [("x", ()), ("y", ("2",))]


@pytest.mark.parametrize("body", ["float *values;", "union { int a; float b; } u;", "void (*fn)(void);"])
def test_unsupported_declarations_raise(body):
    with pytest.raises(ParseError):
        parse_struct_body(body)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ctext.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemagen'`.

- [ ] **Step 3: Implement `schemagen/__init__.py` and `schemagen/ctext.py`**

`schemagen/__init__.py`:
```python
"""Offline generator for dtk params schemas from darktable source."""
```

`schemagen/ctext.py`:
```python
"""Scanning helpers for the C subset darktable uses in iop params declarations."""
from __future__ import annotations

import re
from dataclasses import dataclass


class ParseError(ValueError):
    """The C text uses a construct this scanner does not model."""


DEFINE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]+)$", re.M)
TYPEDEF_BLOCK_RE = re.compile(r"^typedef[ \t]+(struct|enum)\b[ \t]*(?:[A-Za-z_]\w*)?\s*\{", re.M)
TYPEDEF_ALIAS_RE = re.compile(
    r"^typedef[ \t]+((?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*;", re.M)
ANNOTATION_RE = re.compile(r'\$(MIN|MAX|DEFAULT|DESCRIPTION):\s*("(?:[^"\\]|\\.)*"|[^\s$]+)')
COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
DECL_RE = re.compile(r"^(?P<ctype>(?:(?:const|unsigned|signed)\s+)*[A-Za-z_]\w*)\s+(?P<declarators>.+)$", re.S)
DECLARATOR_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<dims>(?:\[[^\]]+\]\s*)*)$")
INT_TOKEN_RE = re.compile(r"\s*(0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|<<|>>|[-+*/%()|&~^])")


@dataclass(frozen=True)
class RawField:
    ctype: str
    name: str
    dims: tuple[str, ...]
    note: str


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub(" ", text)


def _skip_quoted(text: str, index: int) -> int:
    quote, index = text[index], index + 1
    while index < len(text) and text[index] != quote:
        index += 2 if text[index] == "\\" else 1
    return index + 1


def match_brace(text: str, open_index: int) -> int:
    depth, index = 0, open_index
    while index < len(text):
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        char = text[index]
        if char in "\"'":
            index = _skip_quoted(text, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ParseError("unbalanced braces")


def find_typedefs(src: str) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for match in TYPEDEF_BLOCK_RE.finditer(src):
        open_index = match.end() - 1
        try:
            close_index = match_brace(src, open_index)
        except ParseError:
            continue
        tail = re.match(r"\s*([A-Za-z_]\w*)\s*;", src[close_index + 1:])
        if tail:
            found[tail.group(1)] = (match.group(1), src[open_index + 1:close_index])
    return found


def find_aliases(src: str) -> dict[str, str]:
    return {alias: " ".join(target.split()) for target, alias in TYPEDEF_ALIAS_RE.findall(src)
            if target not in ("struct", "enum", "union")}


def find_defines(src: str) -> dict[str, str]:
    defines = {}
    for name, value in DEFINE_RE.findall(src):
        value = strip_comments(value).strip()
        if value and not value.endswith("\\"):
            defines[name] = value
    return defines


def eval_int(expr: str, names: dict[str, int]) -> int | None:
    expr = strip_comments(expr).strip()
    if not expr:
        return None
    pieces, position = [], 0
    while position < len(expr):
        match = INT_TOKEN_RE.match(expr, position)
        if not match:
            return None
        token, position = match.group(1), match.end()
        if token[0].isalpha() or token[0] == "_":
            if names.get(token) is None:
                return None
            pieces.append(str(names[token]))
        elif token[0].isdigit():
            digits = token.rstrip("uUlL")
            pieces.append(str(int(digits, 16) if digits[:2].lower() == "0x" else int(digits, 10)))
        elif token == "/":
            pieces.append("//")
        else:
            pieces.append(token)
        while position < len(expr) and expr[position].isspace():
            position += 1
    try:
        value = eval(" ".join(pieces), {"__builtins__": {}}, {})  # tokens are restricted to ints and operators
    except Exception:
        return None
    return value if isinstance(value, int) else None


def resolve_ints(exprs: dict[str, str], seed: dict[str, int]) -> dict[str, int]:
    known, pending, changed = dict(seed), dict(exprs), True
    while changed:
        changed = False
        for name, expr in list(pending.items()):
            value = eval_int(expr, known)
            if value is not None:
                known[name] = value
                del pending[name]
                changed = True
    return known


def _skip_space_and_comments(body: str, index: int) -> int:
    while index < len(body):
        if body[index].isspace():
            index += 1
        elif body.startswith("//", index):
            end = body.find("\n", index)
            index = len(body) if end < 0 else end
        elif body.startswith("/*", index):
            end = body.find("*/", index + 2)
            index = len(body) if end < 0 else end + 2
        else:
            break
    return index


def _note_end(body: str, start: int) -> int:
    line_end = body.find("\n", start)
    line_end = len(body) if line_end < 0 else line_end
    segment = body[start:line_end]
    block, line = segment.find("/*"), segment.find("//")
    if block >= 0 and (line < 0 or block < line):
        close = body.find("*/", start + block + 2)
        return len(body) if close < 0 else close + 2
    return line_end


def _declarators(decl: str, note: str) -> list[RawField]:
    match = DECL_RE.match(" ".join(decl.split()))
    if not match:
        raise ParseError(f"cannot read declaration {decl!r}")
    ctype = re.sub(r"^const\s+", "", match.group("ctype"))
    fields = []
    for part in match.group("declarators").split(","):
        declarator = DECLARATOR_RE.match(part.strip())
        if not declarator:
            raise ParseError(f"cannot read declarator {part.strip()!r}")
        dims = tuple(size.strip() for size in re.findall(r"\[([^\]]+)\]", declarator.group("dims")))
        fields.append(RawField(ctype, declarator.group("name"), dims, note))
    return fields


def parse_struct_body(body: str) -> list[RawField]:
    fields, index = [], 0
    while True:
        index = _skip_space_and_comments(body, index)
        if index >= len(body):
            return fields
        semicolon = body.find(";", index)
        if semicolon < 0:
            raise ParseError(f"unterminated declaration {body[index:index + 40]!r}")
        decl = strip_comments(body[index:semicolon]).strip()
        outside_brackets = re.sub(r"\[[^\]]*\]", "[]", decl)
        if any(char in outside_brackets for char in "{}()*#"):
            raise ParseError(f"unsupported declaration {decl!r}")
        note_end = _note_end(body, semicolon + 1)
        fields.extend(_declarators(decl, body[semicolon + 1:note_end]))
        index = note_end


def parse_annotations(note: str) -> dict[str, str]:
    return {key.lower(): value[1:-1] if value.startswith('"') else value
            for key, value in ANNOTATION_RE.findall(note)}


def parse_enum_body(body: str, known: dict[str, int]) -> dict[str, int | None]:
    members: dict[str, int | None] = {}
    scope, next_value = dict(known), 0
    for item in strip_comments(body).split(","):
        item = item.strip()
        if not item:
            continue
        name, _, expr = item.partition("=")
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ParseError(f"cannot read enum member {item!r}")
        value = eval_int(expr, scope) if expr.strip() else next_value
        members[name] = value
        if value is None:
            next_value = None
        else:
            scope[name] = value
            next_value = value + 1
    return members
```

Note: `"union { int a; float b; } u;"` raises because `parse_struct_body` sees `{` before the first `;`. `"void (*fn)(void);"` raises on `(`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ctext.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add schemagen/__init__.py schemagen/ctext.py tests/test_ctext.py
git commit -m "feat: C text scanning for schema generation"
```

---

### Task 4: Schema builder, generated schemas, schema loader

**Files:**
- Create: `schemagen/build.py`, `dtk/schemas.py`, `dtk/schemas/5.6.1/*.json` (generated), `dtk/schemas/5.6.1/index.json` (generated)
- Test: `tests/test_schemagen_build.py`, `tests/test_generated_schemas.py`

**Interfaces:**
- Consumes: Task 3 functions; `dtk.codec.PRIMS`, `struct_size`, `CodecError`.
- Produces: `schemagen.build.TypeTable`, `int_names(table, seed) -> dict[str, int]`, `build_module_schema(module, src, shared, shared_names) -> dict | None`, `generate(src_root: Path, out_dir: Path) -> list[dict]`, `main(argv=None)`. `dtk.schemas.DT_VERSION = "5.6.1"`, `SCHEMA_DIR: Path`, `SchemaMissing(LookupError)`, `load_index() -> dict[str, dict]`, `current_version(module) -> int | None`, `load_schema(module, version) -> dict`, `load_corpus_report() -> dict[str, dict]`, `is_editable(module) -> bool`.
- The module name is the `.c` file stem (`toneequal.c` -> `toneequal`, even though its struct is `dt_iop_toneequalizer_params_t`); it matches `darktable:operation` in XMPs.

- [ ] **Step 1: Write the failing builder tests**

`tests/test_schemagen_build.py`:
```python
from schemagen.build import TypeTable, build_module_schema, int_names
from tests.test_ctext import BASECURVE_SRC, EXPOSURE_SRC


def build(module, src, header=""):
    shared = TypeTable()
    shared.add_source(header)
    return build_module_schema(module, src, shared, int_names(shared, {}))


def test_exposure_schema():
    schema = build("exposure", "DT_MODULE_INTROSPECTION(7, dt_iop_exposure_params_t)\n" + EXPOSURE_SRC)
    assert schema["status"] == "ok"
    assert schema["version"] == 7
    assert [f["name"] for f in schema["fields"]] == ["mode", "black", "exposure", "compensate_exposure_bias"]
    mode, black = schema["fields"][0], schema["fields"][1]
    assert mode["kind"] == "enum"
    assert mode["enum"] == {"EXPOSURE_MODE_MANUAL": 0, "EXPOSURE_MODE_DEFLICKER": 1}
    assert mode["default"] == "EXPOSURE_MODE_MANUAL"
    assert (black["min"], black["max"], black["description"]) == (-1.0, 1.0, "black level correction")
    assert schema["fields"][3]["default"] == 0
    assert schema["size"] == 16


def test_basecurve_resolves_macros_and_nested_structs():
    schema = build("basecurve", "DT_MODULE_INTROSPECTION(6, dt_iop_basecurve_params_t)\n" + BASECURVE_SRC)
    curve = schema["fields"][0]
    assert curve["kind"] == "struct"
    assert curve["dims"] == [3, 20]
    assert schema["fields"][1]["max"] == 20
    assert schema["size"] == 3 * 20 * 8 + 3 * 4 + 4 + 4


def test_types_from_shared_headers():
    header = "typedef enum dt_image_orientation_t\n{\n  ORIENTATION_NONE = 0,\n  ORIENTATION_FLIP_Y = 1 << 0\n} dt_image_orientation_t;\n"
    src = ("DT_MODULE_INTROSPECTION(2, dt_iop_flip_params_t)\n"
           "typedef struct dt_iop_flip_params_t\n{\n  dt_image_orientation_t orientation;\n} dt_iop_flip_params_t;\n")
    schema = build("flip", src, header)
    assert schema["fields"][0]["enum"] == {"ORIENTATION_NONE": 0, "ORIENTATION_FLIP_Y": 1}


def test_unknown_type_marks_module_unsupported():
    src = ("DT_MODULE_INTROSPECTION(1, dt_iop_x_params_t)\n"
           "typedef struct dt_iop_x_params_t\n{\n  dt_mystery_t value;\n} dt_iop_x_params_t;\n")
    schema = build("x", src)
    assert schema["status"] == "unsupported"
    assert "dt_mystery_t" in schema["reason"]
    assert schema["fields"] == []


def test_files_without_introspection_are_skipped():
    assert build("helper", "int x;") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schemagen_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schemagen.build'`.

- [ ] **Step 3: Implement `schemagen/build.py`**

```python
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
```

- [ ] **Step 4: Run builder tests to verify they pass**

Run: `uv run pytest tests/test_schemagen_build.py -v`
Expected: 5 passed.

- [ ] **Step 5: Clone darktable and generate the real schemas**

```bash
mkdir -p ~/git/github/darktable-org
git clone --depth 1 --branch release-5.6.1 https://github.com/darktable-org/darktable.git ~/git/github/darktable-org/darktable
uv run python -m schemagen.build
```
Expected: a summary line like `NN modules: MM ok, KK unsupported` followed by one line per unsupported module with its reason. Record the summary line and the unsupported list in the PR description. If `ok` is under 40, investigate the most common reason before continuing: that is a parser gap, not a property of darktable.

- [ ] **Step 6: Write the schema loader `dtk/schemas.py`**

```python
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
```

- [ ] **Step 7: Write tests that pin the generated schemas to known darktable facts**

`tests/test_generated_schemas.py`:
```python
from dtk.codec import struct_size
from dtk.schemas import current_version, load_index, load_schema


def field_names(module):
    return [field["name"] for field in load_schema(module, current_version(module))["fields"]]


def test_exposure_v7_matches_the_spike_layout():
    assert current_version("exposure") == 7
    assert field_names("exposure") == ["mode", "black", "exposure", "deflicker_percentile",
                                       "deflicker_target_level", "compensate_exposure_bias",
                                       "compensate_hilite_pres"]
    assert struct_size(load_schema("exposure", 7)) == 28


def test_crop_temperature_and_flip():
    assert (current_version("crop"), struct_size(load_schema("crop", 3))) == (3, 24)
    assert (current_version("temperature"), struct_size(load_schema("temperature", 4))) == (4, 20)
    assert load_schema("flip", 2)["fields"][0]["kind"] == "enum"


def test_module_name_is_the_file_stem():
    assert load_index()["toneequal"]["struct"] == "dt_iop_toneequalizer_params_t"


def test_index_sizes_match_codec_sizes():
    for module, entry in load_index().items():
        if entry["status"] == "ok":
            assert entry["size"] == struct_size(load_schema(module, entry["version"])), module
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -v`
Expected: all pass. If `test_crop_temperature_and_flip` fails, read the module's struct in `~/git/github/darktable-org/darktable/src/iop/<module>.c` and fix the parser; do not edit the generated JSON by hand.

- [ ] **Step 9: Commit**

```bash
git add schemagen/build.py dtk/schemas.py dtk/schemas/5.6.1 tests/test_schemagen_build.py tests/test_generated_schemas.py
git commit -m "feat: generate params schemas from darktable 5.6.1 source"
```

---

### Task 5: XMP sidecar model

**Files:**
- Create: `dtk/xmp.py`, `tests/fixtures/minimal.xmp`
- Test: `tests/test_xmp.py`

**Interfaces:**
- Produces: `XmpError(ValueError)`; frozen dataclass `HistoryEntry(num: int, operation: str, enabled: bool, modversion: int, params: str, multi_name: str, multi_name_hand_edited: str, multi_priority: int, blendop_version: int, blendop_params: str)`; frozen dataclass `Sidecar(text: str, history: tuple[HistoryEntry, ...], history_end: int, has_masks_history: bool)`; `parse_sidecar(text: str) -> Sidecar`; `format_entry(entry: HistoryEntry, indent: str) -> str`; `with_appended_entries(sidecar: Sidecar, entries: list[HistoryEntry]) -> tuple[str, int]` returning (new text, number of discarded undone entries).

(Task 6 depends on this, which is why it comes before the corpus gate.)

- [ ] **Step 1: Write the fixture `tests/fixtures/minimal.xmp`**

Three entries, `history_end="2"`, so entry 2 is undone. Entry 0 is the exposure blob from the spike, entry 1 a crop, entry 2 an exposure at 3.0 EV.
```xml
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:darktable="http://darktable.sf.net/"
   darktable:xmp_version="5"
   darktable:history_end="2">
   <darktable:history>
    <rdf:Seq>
     <rdf:li
      darktable:num="0"
      darktable:operation="exposure"
      darktable:enabled="1"
      darktable:modversion="7"
      darktable:params="00000000000080b9f828fc3f00004842000080c00100000001000000"
      darktable:multi_name=""
      darktable:multi_name_hand_edited="0"
      darktable:multi_priority="0"
      darktable:blendop_version="14"
      darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li
      darktable:num="1"
      darktable:operation="crop"
      darktable:enabled="1"
      darktable:modversion="3"
      darktable:params="000000000000000036f22a3f0000803f0100000001000000"
      darktable:multi_name=""
      darktable:multi_name_hand_edited="0"
      darktable:multi_priority="0"
      darktable:blendop_version="14"
      darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
     <rdf:li
      darktable:num="2"
      darktable:operation="exposure"
      darktable:enabled="1"
      darktable:modversion="7"
      darktable:params="00000000000080b90000404000004842000080c00100000001000000"
      darktable:multi_name=""
      darktable:multi_name_hand_edited="0"
      darktable:multi_priority="0"
      darktable:blendop_version="14"
      darktable:blendop_params="gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_xmp.py`:
```python
from dataclasses import replace
from pathlib import Path

import pytest

from dtk.xmp import XmpError, parse_sidecar, with_appended_entries

FIXTURES = Path(__file__).parent / "fixtures"
MINIMAL = (FIXTURES / "minimal.xmp").read_text()
REAL = sorted((FIXTURES / "sidecars").glob("*.xmp"))


def test_parse_minimal():
    sidecar = parse_sidecar(MINIMAL)
    assert sidecar.history_end == 2
    assert [entry.operation for entry in sidecar.history] == ["exposure", "crop", "exposure"]
    first = sidecar.history[0]
    assert (first.num, first.enabled, first.modversion, first.multi_priority) == (0, True, 7, 0)
    assert sidecar.has_masks_history is False


def test_append_discards_undone_entries_and_moves_history_end():
    sidecar = parse_sidecar(MINIMAL)
    new_entry = replace(sidecar.history[0], num=2, params="00" * 28)
    text, discarded = with_appended_entries(sidecar, [new_entry])
    reparsed = parse_sidecar(text)
    assert discarded == 1
    assert reparsed.history_end == 3
    assert reparsed.history == (sidecar.history[0], sidecar.history[1], new_entry)
    assert 'darktable:history_end="3"' in text


def test_untouched_lines_are_kept_verbatim():
    sidecar = parse_sidecar(MINIMAL)
    text, _ = with_appended_entries(sidecar, [replace(sidecar.history[0], num=2)])
    head = MINIMAL.split('darktable:num="2"')[0].rsplit("<rdf:li", 1)[0]
    assert text.startswith(head.replace('history_end="2"', 'history_end="3"'))


def test_appending_nothing_to_a_real_sidecar_changes_nothing():
    checked = 0
    for path in REAL:
        sidecar = parse_sidecar(path.read_text())
        if sidecar.history and sidecar.history_end == len(sidecar.history):
            assert with_appended_entries(sidecar, []) == (sidecar.text, 0), path.name
            checked += 1
    assert checked >= 1


def test_multi_name_is_escaped_and_unescaped():
    sidecar = parse_sidecar(MINIMAL)
    named = replace(sidecar.history[0], num=2, multi_name="sky & <sun>")
    text, _ = with_appended_entries(sidecar, [named])
    assert 'darktable:multi_name="sky &amp; &lt;sun&gt;"' in text
    assert parse_sidecar(text).history[-1].multi_name == "sky & <sun>"


def test_discarding_with_masks_history_is_refused():
    text = MINIMAL.replace("</darktable:history>", "</darktable:history>\n   <darktable:masks_history>\n   </darktable:masks_history>")
    sidecar = parse_sidecar(text)
    with pytest.raises(XmpError, match="masks"):
        with_appended_entries(sidecar, [replace(sidecar.history[0], num=2)])


def test_sidecar_without_history():
    sidecar = parse_sidecar('<rdf:Description darktable:history_end="0"/>')
    assert sidecar.history == ()
    with pytest.raises(XmpError, match="no history stack"):
        with_appended_entries(sidecar, [])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_xmp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.xmp'`.

- [ ] **Step 4: Implement `dtk/xmp.py`**

```python
"""darktable XMP sidecars: read the history stack, append entries without disturbing the rest."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

HISTORY_RE = re.compile(r"<darktable:history>\s*<rdf:Seq>(?P<body>.*?)\s*</rdf:Seq>\s*</darktable:history>", re.S)
LI_RE = re.compile(r"<rdf:li\b(?P<attrs>[^>]*?)/>", re.S)
ATTR_RE = re.compile(r'(\w+:\w+)="([^"]*)"')
HISTORY_END_RE = re.compile(r'darktable:history_end="(\d+)"')
DEFAULT_INDENT = "     "


class XmpError(ValueError):
    """The sidecar cannot be read or changed safely."""


@dataclass(frozen=True)
class HistoryEntry:
    num: int
    operation: str
    enabled: bool
    modversion: int
    params: str
    multi_name: str
    multi_name_hand_edited: str
    multi_priority: int
    blendop_version: int
    blendop_params: str


@dataclass(frozen=True)
class Sidecar:
    text: str
    history: tuple[HistoryEntry, ...]
    history_end: int
    has_masks_history: bool


def _entry(attrs: str) -> HistoryEntry:
    values = {key.split(":", 1)[1]: html.unescape(value) for key, value in ATTR_RE.findall(attrs)}
    try:
        return HistoryEntry(
            num=int(values["num"]), operation=values["operation"], enabled=values["enabled"] == "1",
            modversion=int(values["modversion"]), params=values["params"],
            multi_name=values.get("multi_name", ""),
            multi_name_hand_edited=values.get("multi_name_hand_edited", "0"),
            multi_priority=int(values.get("multi_priority", "0")),
            blendop_version=int(values.get("blendop_version", "0")),
            blendop_params=values.get("blendop_params", ""))
    except KeyError as missing:
        raise XmpError(f"history entry lacks darktable:{missing.args[0]}") from None


def parse_sidecar(text: str) -> Sidecar:
    match = HISTORY_RE.search(text)
    history = tuple(_entry(li.group("attrs")) for li in LI_RE.finditer(match.group("body"))) if match else ()
    end = HISTORY_END_RE.search(text)
    return Sidecar(text=text, history=history, history_end=int(end.group(1)) if end else len(history),
                   has_masks_history="<darktable:masks_history>" in text)


def format_entry(entry: HistoryEntry, indent: str) -> str:
    attrs = [("num", str(entry.num)), ("operation", entry.operation), ("enabled", "1" if entry.enabled else "0"),
             ("modversion", str(entry.modversion)), ("params", entry.params), ("multi_name", entry.multi_name),
             ("multi_name_hand_edited", entry.multi_name_hand_edited),
             ("multi_priority", str(entry.multi_priority)), ("blendop_version", str(entry.blendop_version)),
             ("blendop_params", entry.blendop_params)]
    lines = [f'{indent} darktable:{name}="{html.escape(value, quote=True)}"' for name, value in attrs]
    return "<rdf:li\n" + "\n".join(lines) + "/>"


def with_appended_entries(sidecar: Sidecar, entries: list[HistoryEntry]) -> tuple[str, int]:
    match = HISTORY_RE.search(sidecar.text)
    if not match:
        raise XmpError("this sidecar has no history stack; edit the image in darktable first")
    body = match.group("body")
    items = list(LI_RE.finditer(body))
    keep = min(sidecar.history_end, len(items))
    discarded = len(items) - keep
    if discarded and sidecar.has_masks_history:
        raise XmpError("undone history steps carry masks; compress history in darktable, then retry")
    if not entries and not discarded:
        return sidecar.text, 0
    indent = DEFAULT_INDENT
    if items:
        line_start = body.rfind("\n", 0, items[0].start()) + 1
        indent = body[line_start:items[0].start()]
    pieces = [item.group(0) for item in items[:keep]] + [format_entry(entry, indent) for entry in entries]
    new_body = "".join(f"\n{indent}{piece}" for piece in pieces)
    text = sidecar.text[:match.start("body")] + new_body + sidecar.text[match.end("body"):]
    new_end = f'darktable:history_end="{keep + len(entries)}"'
    if HISTORY_END_RE.search(text):
        text = HISTORY_END_RE.sub(new_end, text, count=1)
    return text, discarded
```

Check: in darktable's own output, `html.escape` of plain ASCII hex/base64 is a no-op, so real entries written by `format_entry` match darktable's format (`base64` has `+`, `/` and `=`, none of which are escaped).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_xmp.py -v`
Expected: 7 passed. If `test_appending_nothing_to_a_real_sidecar_changes_nothing` checks 0 sidecars, list each sidecar's `history_end` vs `len(history)` in the PR so Joel knows.

- [ ] **Step 6: Commit**

```bash
git add dtk/xmp.py tests/fixtures/minimal.xmp tests/test_xmp.py
git commit -m "feat: parse and append darktable XMP history"
```

---

### Task 6: Corpus gate

**Files:**
- Create: `dtk/corpus.py`, `dtk/schemas/5.6.1/corpus.json` (generated)
- Test: `tests/test_corpus.py`

**Interfaces:**
- Consumes: `dtk.blob.decode_param_string`, `dtk.codec.decode/encode/CodecError`, `dtk.schemas.load_index/load_schema/SCHEMA_DIR`, `dtk.xmp.parse_sidecar`.
- Produces: `Blob = tuple[str, int, bytes, str]` (module, modversion, raw, source label); `blobs_from_presets(path) -> list[Blob]`; `blobs_from_sidecars(paths) -> list[Blob]`; `range_problems(schema, values) -> list[str]`; `evaluate(blobs) -> dict[str, dict]` mapping module -> `{"status": "editable"|"read-only"|"no-corpus"|"unsupported", "version": int, "blobs": int, "problems": [str]}`; `main(argv=None)`.

Why the range check matters: decode/encode of a blob whose size matches is nearly always byte-identical even if fields are in the wrong order, so the byte round-trip alone mostly proves the size. The range check (`$MIN/$MAX`, booleans in {0,1}, enum values known) is what catches a misread layout, because misplaced floats read as absurd values.

- [ ] **Step 1: Write the failing tests**

`tests/test_corpus.py`:
```python
import json
from pathlib import Path

import pytest

import dtk.corpus as corpus
from dtk.codec import encode
from dtk.schemas import SCHEMA_DIR
from tests.schema_helpers import enum, prim, schema

FIXTURES = Path(__file__).parent / "fixtures"
UNIT = schema("unit", [prim("level", "float", lo=0.0, hi=1.0), prim("on", "gboolean"), enum("mode", {"A": 0, "B": 1})])


@pytest.fixture
def unit_index(monkeypatch):
    index = {"unit": {"module": "unit", "version": 1, "status": "ok", "reason": None},
             "broken": {"module": "broken", "version": 2, "status": "unsupported", "reason": "unknown type x"}}
    monkeypatch.setattr(corpus, "load_index", lambda: index)
    monkeypatch.setattr(corpus, "load_schema", lambda module, version: UNIT)


def blob(level=0.5, on=1, mode=0):
    return encode(UNIT, {"level": level, "on": on, "mode": mode})


def test_in_range_blobs_make_a_module_editable(unit_index):
    report = corpus.evaluate([("unit", 1, blob(), "a"), ("unit", 1, blob(level=1.0), "b")])
    assert report["unit"] == {"status": "editable", "version": 1, "blobs": 2, "problems": []}
    assert report["broken"]["status"] == "unsupported"


@pytest.mark.parametrize("bad, reason", [
    (blob(level=7.5), "level=7.5 is above 1.0"),
    (blob(on=2), "on=2 is not a boolean"),
    (blob(mode=9), "mode=9 is not a member"),
    (b"\0\0\0\0", "blob is 4 bytes"),
])
def test_one_bad_blob_makes_a_module_read_only(unit_index, bad, reason):
    report = corpus.evaluate([("unit", 1, blob(), "good"), ("unit", 1, bad, "bad")])
    assert report["unit"]["status"] == "read-only"
    assert any(reason in problem for problem in report["unit"]["problems"])


def test_blobs_at_other_versions_do_not_count(unit_index):
    assert corpus.evaluate([("unit", 0, blob(), "old")])["unit"]["status"] == "no-corpus"


def test_committed_report_is_current():
    blobs = corpus.blobs_from_presets(FIXTURES / "preset_params.json")
    blobs += corpus.blobs_from_sidecars(sorted((FIXTURES / "sidecars").glob("*.xmp")))
    committed = json.loads((SCHEMA_DIR / "corpus.json").read_text())
    assert corpus.evaluate(blobs) == committed


def test_exposure_is_editable():
    committed = json.loads((SCHEMA_DIR / "corpus.json").read_text())
    assert committed["exposure"]["status"] == "editable", committed["exposure"]["problems"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_corpus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.corpus'`.

- [ ] **Step 3: Implement `dtk/corpus.py`**

```python
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
        problems: list[str] = []
        for raw, source in current:
            try:
                values = decode(schema, raw)
            except CodecError as exc:
                problems.append(f"{source}: {exc}")
                continue
            if encode(schema, values) != raw:
                problems.append(f"{source}: re-encoding changed the bytes")
            problems.extend(f"{source}: {problem}" for problem in range_problems(schema, values))
        status = "no-corpus" if not current else "editable" if not problems else "read-only"
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
```

Note: `json.dumps(..., sort_keys=True)` sorts the problem dicts' keys too, so `test_committed_report_is_current` compares parsed JSON, not text.

- [ ] **Step 4: Generate the committed report**

Run: `uv run python -m dtk.corpus`
Expected: a count line such as `NN editable, MM no-corpus, KK read-only, JJ unsupported`, then the editable list. `exposure` must be in it. Put the count line and editable list in the PR description. For every `read-only` module, look at its first problem. If the problem points at a parser bug (for example every field out of range), fix the parser in Task 3/4 code, regenerate schemas, and rerun. If it is a genuine darktable value outside the annotation, leave the module read-only and note it in the PR.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add dtk/corpus.py dtk/schemas/5.6.1/corpus.json tests/test_corpus.py
git commit -m "feat: corpus gate decides which modules are editable"
```

---

### Task 7: Library queries and image resolution

**Files:**
- Create: `dtk/library.py`, `dtk/images.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Produces: `dtk.library.DEFAULT_LIBRARY`, `DEFAULT_DATA` (honour env `DTK_LIBRARY`, `DTK_DATA`), frozen dataclass `Image(id: int, path: Path, rating: int, edited: bool, taken: datetime | None)` (rating `-1` = rejected), `snapshot(src: Path, dest_dir: Path) -> Path`, `find_images(library: Path, data: Path | None = None, *, roll: str | None = None, rating_min: int | None = None, tag: str | None = None, edited: bool | None = None, since: date | None = None) -> list[Image]`, `image_by_id(library: Path, image_id: int) -> Image`, `to_timespan(day: date) -> int`, `from_timespan(value: int | None) -> datetime | None`. `dtk.images.ImageNotFound(LookupError)`, frozen dataclass `ImageFiles(raw: Path, xmp: Path)`, `resolve_image(arg: str, library_snapshot: Callable[[], Path]) -> ImageFiles`.

- [ ] **Step 1: Write the failing tests**

`tests/test_library.py`:
```python
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from dtk.images import ImageNotFound, resolve_image
from dtk.library import find_images, from_timespan, image_by_id, snapshot, to_timespan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def library(tmp_path):
    lib, data = tmp_path / "library.db", tmp_path / "data.db"
    with sqlite3.connect(lib) as conn:
        conn.executescript((FIXTURES / "library_schema.sql").read_text())
        conn.executemany("insert into film_rolls (id, folder) values (?, ?)",
                         [(1, "/photos/iceland"), (2, "/photos/moon")])
        rows = [  # id, film, filename, flags, taken
            (1, 1, "a.CR2", 4, to_timespan(date(2025, 7, 1))),
            (2, 1, "b.CR2", 6, to_timespan(date(2025, 7, 2))),      # rating 6 = rejected
            (3, 2, "c.CR2", 2 | 8, to_timespan(date(2026, 11, 26))),  # flag 8 = rejected
            (4, 2, "d.CR2", 5, to_timespan(date(2026, 11, 26))),
        ]
        conn.executemany("insert into images (id, film_id, filename, flags, datetime_taken) values (?, ?, ?, ?, ?)",
                         rows)
        conn.executemany("insert into history_hash (imgid, basic_hash, auto_hash, current_hash) values (?, ?, ?, ?)",
                         [(1, b"b", b"a", b"x"), (4, b"b", b"a", b"a")])
        conn.execute("insert into tagged_images (imgid, tagid) values (4, 10)")
    with sqlite3.connect(data) as conn:
        conn.executescript((FIXTURES / "data_tags_schema.sql").read_text())
        conn.execute("insert into tags (id, name) values (10, 'sky|moon')")
    return lib, data


def ids(images):
    return [image.id for image in images]


def test_find_all_sorted_by_path(library):
    images = find_images(library[0])
    assert ids(images) == [1, 2, 3, 4]
    assert images[0].path == Path("/photos/iceland/a.CR2")
    assert images[0].taken == datetime(2025, 7, 1)


def test_ratings_and_rejects(library):
    by_id = {image.id: image for image in find_images(library[0])}
    assert (by_id[1].rating, by_id[2].rating, by_id[3].rating, by_id[4].rating) == (4, -1, -1, 5)
    assert ids(find_images(library[0], rating_min=4)) == [1, 4]


def test_edited_means_current_differs_from_basic_and_auto(library):
    assert ids(find_images(library[0], edited=True)) == [1]
    assert ids(find_images(library[0], edited=False)) == [2, 3, 4]


def test_roll_tag_and_since_filters(library):
    lib, data = library
    assert ids(find_images(lib, roll="moon")) == [3, 4]
    assert ids(find_images(lib, data, tag="moon")) == [4]
    assert ids(find_images(lib, since=date(2026, 1, 1))) == [3, 4]


def test_timespan_round_trip():
    assert from_timespan(63931318832360000).year == 2026
    assert from_timespan(to_timespan(date(2020, 2, 29))) == datetime(2020, 2, 29)
    assert from_timespan(None) is None


def test_snapshot_copies_without_touching_the_source(library, tmp_path):
    lib, _ = library
    before = lib.read_bytes()
    copy = snapshot(lib, tmp_path / "snap")
    assert copy != lib and ids(find_images(copy)) == [1, 2, 3, 4]
    assert lib.read_bytes() == before


def test_image_by_id_and_missing(library):
    assert image_by_id(library[0], 4).path.name == "d.CR2"
    with pytest.raises(LookupError):
        image_by_id(library[0], 99)


def test_resolve_image_by_path(tmp_path):
    raw = tmp_path / "IMG_1.CR2"
    raw.write_bytes(b"")
    (tmp_path / "IMG_1.CR2.xmp").write_text("<x/>")
    files = resolve_image(str(raw), library_snapshot=lambda: pytest.fail("library not needed"))
    assert files.xmp == tmp_path / "IMG_1.CR2.xmp"
    assert resolve_image(str(files.xmp), library_snapshot=lambda: None).raw == raw


def test_resolve_image_refuses_missing_sidecar(tmp_path):
    raw = tmp_path / "IMG_2.CR2"
    raw.write_bytes(b"")
    with pytest.raises(ImageNotFound, match="no sidecar"):
        resolve_image(str(raw), library_snapshot=lambda: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_library.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.library'`.

- [ ] **Step 3: Implement `dtk/library.py`**

```python
"""Read-only queries on a snapshot of darktable's library.db."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_LIBRARY = Path(os.environ.get("DTK_LIBRARY") or "~/.config/darktable/library.db").expanduser()
DEFAULT_DATA = Path(os.environ.get("DTK_DATA") or "~/.config/darktable/data.db").expanduser()
EPOCH = datetime(1, 1, 1)
RATING_MASK, RATING_REJECTED, FLAG_REJECTED = 7, 6, 8

SELECT = """
select i.id, f.folder, i.filename, i.flags, i.datetime_taken, h.basic_hash, h.auto_hash, h.current_hash
from images i join film_rolls f on f.id = i.film_id left join history_hash h on h.imgid = i.id
"""


@dataclass(frozen=True)
class Image:
    id: int
    path: Path
    rating: int
    edited: bool
    taken: datetime | None


def to_timespan(day: date) -> int:
    return (datetime(day.year, day.month, day.day) - EPOCH) // timedelta(microseconds=1)


def from_timespan(value: int | None) -> datetime | None:
    return None if value is None else EPOCH + timedelta(microseconds=value)


def snapshot(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return dest


def _rating(flags: int) -> int:
    stars = flags & RATING_MASK
    return -1 if stars == RATING_REJECTED or flags & FLAG_REJECTED else stars


def _image(row) -> Image:
    image_id, folder, filename, flags, taken, basic, auto, current = row
    edited = current is not None and current != basic and current != auto
    return Image(image_id, Path(folder) / filename, _rating(flags or 0), edited, from_timespan(taken))


def find_images(library: Path, data: Path | None = None, *, roll: str | None = None, rating_min: int | None = None,
                tag: str | None = None, edited: bool | None = None, since: date | None = None) -> list[Image]:
    clauses, params = [], []
    if roll:
        clauses.append("f.folder like '%' || ? || '%'")
        params.append(roll)
    if since:
        clauses.append("i.datetime_taken >= ?")
        params.append(to_timespan(since))
    conn = sqlite3.connect(f"file:{library}?mode=ro", uri=True)  # uri=True so the attach below honours its URI
    try:
        if tag:
            if data is None:
                raise ValueError("filtering by tag needs data.db")
            conn.execute("attach database ? as data", (f"file:{data}?mode=ro",))
            clauses.append("i.id in (select ti.imgid from tagged_images ti join data.tags t on t.id = ti.tagid "
                           "where t.name like '%' || ? || '%')")
            params.append(tag)
        where = f" where {' and '.join(clauses)}" if clauses else ""
        rows = conn.execute(SELECT + where + " order by f.folder, i.filename", params).fetchall()
    finally:
        conn.close()
    images = [_image(row) for row in rows]
    if rating_min is not None:
        images = [image for image in images if image.rating >= rating_min]
    if edited is not None:
        images = [image for image in images if image.edited == edited]
    return images


def image_by_id(library: Path, image_id: int) -> Image:
    conn = sqlite3.connect(library)
    try:
        row = conn.execute(SELECT + " where i.id = ?", (image_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"no image with id {image_id} in the darktable library")
    return _image(row)
```

- [ ] **Step 4: Implement `dtk/images.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_library.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add dtk/library.py dtk/images.py tests/test_library.py
git commit -m "feat: read-only library queries and image resolution"
```

---

### Task 8: Rendering and export presets

**Files:**
- Create: `dtk/render.py`, `dtk/presets.py`, `dtk/presets.toml`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `dtk.render.DEFAULT_CLI`, `cli_path() -> str` (env `DTK_DARKTABLE_CLI` overrides), frozen dataclass `RenderSpec(width: int = 0, height: int = 0, quality: int = 90, icc_type: str | None = "SRGB", icc_intent: str = "PERCEPTUAL", hq: bool = True, upscale: bool = False)`, `RenderError(RuntimeError)`, `build_command(raw_link, xmp_copy, out, spec, configdir) -> list[str]`, `render(raw: Path, xmp_text: str, out: Path, spec: RenderSpec, run=None) -> Path`, `side_by_side(before: Path, after: Path, out: Path) -> Path`, `PREVIEW_SPEC`. `dtk.presets.Preset(name, description, spec: RenderSpec, out_dir: str)`, `load_preset(name) -> Preset`, `list_presets() -> list[Preset]`, `out_dir_for(preset, raw: Path) -> Path`.

darktable-cli facts (verified with 5.6.1): usage `darktable-cli IN XMP OUT [--width N] [--height N] [--hq true|false] [--upscale true|false] [--icc-type SRGB] [--icc-intent PERCEPTUAL] --core --configdir DIR --library :memory: --conf key=value`. If `OUT` already exists, darktable-cli writes `name_01.jpg` instead of replacing it, so always render into an empty temp dir and move the result.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:
```python
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms

from dtk.presets import list_presets, load_preset, out_dir_for
from dtk.render import RenderError, RenderSpec, render, side_by_side

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def fake_darktable(size=(800, 600), icc=True, produce=True, seen=None):
    def run(cmd, **kwargs):
        raw_link, xmp_copy, out = Path(cmd[1]), Path(cmd[2]), Path(cmd[3])
        if seen is not None:
            seen.update(cmd=cmd, is_link=raw_link.is_symlink(), target=raw_link.resolve(),
                        xmp_text=xmp_copy.read_text())
        if produce:
            Image.new("RGB", size, (90, 90, 90)).save(out, "JPEG", **({"icc_profile": SRGB} if icc else {}))
        return subprocess.CompletedProcess(cmd, 0 if produce else 1, "", "boom: cannot load raw\n")
    return run


@pytest.fixture
def raw(tmp_path):
    path = tmp_path / "IMG_1.CR2"
    path.write_bytes(b"raw")
    return path


def test_render_uses_a_symlink_and_a_sidecar_copy(raw, tmp_path):
    seen = {}
    out = render(raw, "<xmp edited/>", tmp_path / "out" / "a.jpg", RenderSpec(width=1024, height=1024),
                 run=fake_darktable(seen=seen))
    assert out.exists()
    assert seen["is_link"] and seen["target"] == raw.resolve()
    assert seen["xmp_text"] == "<xmp edited/>"
    cmd = seen["cmd"]
    for expected in (["--library", ":memory:"], ["--icc-type", "SRGB"], ["--width", "1024"]):
        index = cmd.index(expected[0])
        assert cmd[index:index + 2] == expected
    assert "write_sidecar_files=never" in cmd
    assert "plugins/imageio/format/jpeg/quality=90" in cmd


def test_existing_output_is_replaced(raw, tmp_path):
    out = tmp_path / "a.jpg"
    out.write_bytes(b"old")
    render(raw, "<x/>", out, RenderSpec(), run=fake_darktable())
    assert out.read_bytes()[:2] == b"\xff\xd8"


def test_missing_output_is_an_error_with_stderr(raw, tmp_path):
    with pytest.raises(RenderError, match="cannot load raw"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(), run=fake_darktable(produce=False))


def test_oversize_output_is_an_error(raw, tmp_path):
    with pytest.raises(RenderError, match="larger than"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(width=100, height=100), run=fake_darktable())


def test_missing_srgb_profile_is_an_error(raw, tmp_path):
    with pytest.raises(RenderError, match="sRGB"):
        render(raw, "<x/>", tmp_path / "a.jpg", RenderSpec(), run=fake_darktable(icc=False))


def test_side_by_side(tmp_path):
    before, after = tmp_path / "b.jpg", tmp_path / "a.jpg"
    Image.new("RGB", (100, 80)).save(before)
    Image.new("RGB", (100, 80)).save(after)
    with Image.open(side_by_side(before, after, tmp_path / "pair.jpg")) as pair:
        assert pair.size == (208, 80)


def test_messenger_preset():
    preset = load_preset("messenger")
    assert (preset.spec.width, preset.spec.height, preset.spec.quality) == (2048, 2048, 90)
    assert preset.spec.icc_type == "SRGB" and preset.spec.upscale is False
    assert out_dir_for(preset, Path("/photos/moon/IMG_1.CR2")) == Path("/photos/moon/messenger")
    assert "messenger" in [p.name for p in list_presets()]


def test_unknown_preset():
    with pytest.raises(LookupError, match="no preset named 'nope'"):
        load_preset("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.render'`.

- [ ] **Step 3: Implement `dtk/render.py`**

```python
"""darktable-cli wrapper. Real sidecars are never handed to darktable-cli."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms

DEFAULT_CLI = "/Applications/darktable.app/Contents/MacOS/darktable-cli"
STDERR_TAIL_LINES = 8
GAP_PIXELS = 8


def cli_path() -> str:
    return os.environ.get("DTK_DARKTABLE_CLI", DEFAULT_CLI)


@dataclass(frozen=True)
class RenderSpec:
    width: int = 0
    height: int = 0
    quality: int = 90
    icc_type: str | None = "SRGB"
    icc_intent: str = "PERCEPTUAL"
    hq: bool = True
    upscale: bool = False


PREVIEW_SPEC = RenderSpec(width=1024, height=1024, quality=85)


class RenderError(RuntimeError):
    """darktable-cli did not produce the image we asked for."""


def _flag(value: bool) -> str:
    return "true" if value else "false"


def build_command(raw_link: Path, xmp_copy: Path, out: Path, spec: RenderSpec, configdir: Path) -> list[str]:
    cmd = [cli_path(), str(raw_link), str(xmp_copy), str(out),
           "--width", str(spec.width), "--height", str(spec.height),
           "--hq", _flag(spec.hq), "--upscale", _flag(spec.upscale)]
    if spec.icc_type:
        cmd += ["--icc-type", spec.icc_type, "--icc-intent", spec.icc_intent]
    return cmd + ["--core", "--configdir", str(configdir), "--library", ":memory:",
                  "--conf", "write_sidecar_files=never",
                  "--conf", f"plugins/imageio/format/jpeg/quality={spec.quality}"]


def _profile_description(image: Image.Image) -> str:
    icc = image.info.get("icc_profile")
    if not icc:
        return ""
    return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))


def _verify(produced: Path, spec: RenderSpec, result: subprocess.CompletedProcess) -> None:
    tail = "\n".join((result.stderr or "").strip().splitlines()[-STDERR_TAIL_LINES:])
    if not produced.exists() or produced.stat().st_size == 0:
        raise RenderError(f"darktable-cli produced no image (exit {result.returncode}): {tail}")
    with Image.open(produced) as image:
        width, height = image.size
        if (spec.width and width > spec.width) or (spec.height and height > spec.height):
            raise RenderError(f"output is {width}x{height}, larger than {spec.width}x{spec.height}")
        if spec.icc_type == "SRGB" and "sRGB" not in _profile_description(image):
            raise RenderError("output has no sRGB colour profile; check the --icc-type handling")


def render(raw: Path, xmp_text: str, out: Path, spec: RenderSpec, run=None) -> Path:
    run = run or subprocess.run
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dtk-render-") as tmp_name:
        tmp = Path(tmp_name)
        raw_link = tmp / raw.name
        raw_link.symlink_to(raw.resolve())
        xmp_copy = tmp / (raw.name + ".xmp")
        xmp_copy.write_text(xmp_text, encoding="utf-8")
        configdir = tmp / "config"
        configdir.mkdir()
        produced = tmp / ("render" + (out.suffix or ".jpg"))
        result = run(build_command(raw_link, xmp_copy, produced, spec, configdir),
                     capture_output=True, text=True, timeout=600)
        _verify(produced, spec, result)
        out.unlink(missing_ok=True)
        shutil.move(str(produced), out)
    return out


def side_by_side(before: Path, after: Path, out: Path) -> Path:
    with Image.open(before) as left_image, Image.open(after) as right_image:
        height = min(left_image.height, right_image.height)
        left = left_image.convert("RGB").resize((left_image.width * height // left_image.height, height))
        right = right_image.convert("RGB").resize((right_image.width * height // right_image.height, height))
    pair = Image.new("RGB", (left.width + GAP_PIXELS + right.width, height), (255, 255, 255))
    pair.paste(left, (0, 0))
    pair.paste(right, (left.width + GAP_PIXELS, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    pair.save(out, "JPEG", quality=90)
    return out
```

- [ ] **Step 4: Implement `dtk/presets.toml` and `dtk/presets.py`**

`dtk/presets.toml`:
```toml
[messenger]
description = "Facebook Messenger: 2048 px long edge, JPEG quality 90, sRGB"
width = 2048
height = 2048
quality = 90
icc_type = "SRGB"
icc_intent = "PERCEPTUAL"
hq = true
upscale = false
out_dir = "{folder}/messenger"
```

`dtk/presets.py`:
```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_render.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add dtk/render.py dtk/presets.py dtk/presets.toml tests/test_render.py
git commit -m "feat: darktable-cli rendering with output checks, export presets"
```

---

### Task 9: Writer and pending edits

**Files:**
- Create: `dtk/state.py`, `dtk/procs.py`, `dtk/writer.py`, `dtk/pending.py`
- Test: `tests/test_writer.py`

**Interfaces:**
- Produces: `dtk.state.state_dir() -> Path` (env `DTK_STATE_DIR`, default `~/.local/state/dtk`). `dtk.procs.darktable_running(run=None) -> bool`. `dtk.writer.WriteRefused(RuntimeError)`, `sha256_bytes(data: bytes) -> str`, `write_xmp(xmp: Path, new_text: str, expected_sha: str, *, is_running=None, backup_dir: Path | None = None, now=None) -> Path` (returns backup path). `dtk.pending.PendingEdit` dataclass (`id, raw, xmp, original_sha, new_text, diff: list[list], preview: str | None, created: str, applied: bool = False`), `new_id(now=None) -> str`, `save(edit, root=None) -> Path`, `load(edit_id, root=None) -> PendingEdit`, `mark_applied(edit_id, root=None) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_writer.py`:
```python
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import dtk.procs as procs
from dtk import pending
from dtk.writer import WriteRefused, sha256_bytes, write_xmp

MINIMAL = (Path(__file__).parent / "fixtures" / "minimal.xmp").read_text()
NEW_TEXT = MINIMAL.replace('history_end="2"', 'history_end="1"')


@pytest.fixture
def xmp(tmp_path):
    path = tmp_path / "IMG_1.CR2.xmp"
    path.write_text(MINIMAL)
    return path


def sha(path):
    return sha256_bytes(path.read_bytes())


def test_write_backs_up_then_replaces(xmp, tmp_path):
    backup = write_xmp(xmp, NEW_TEXT, sha(xmp), is_running=lambda: False, backup_dir=tmp_path / "bk",
                       now=lambda: datetime(2026, 11, 27, 9, 30, 0, 123456))
    assert xmp.read_text() == NEW_TEXT
    assert backup == tmp_path / "bk" / "IMG_1.CR2.xmp.20261127-093000-123456.xmp"
    assert backup.read_text() == MINIMAL
    assert not list(xmp.parent.glob(".*dtk-tmp"))


def test_refuses_while_darktable_runs(xmp, tmp_path):
    with pytest.raises(WriteRefused, match="darktable is running"):
        write_xmp(xmp, NEW_TEXT, sha(xmp), is_running=lambda: True, backup_dir=tmp_path / "bk")
    assert xmp.read_text() == MINIMAL


def test_refuses_stale_previews(xmp, tmp_path):
    with pytest.raises(WriteRefused, match="changed since the preview"):
        write_xmp(xmp, NEW_TEXT, "0" * 64, is_running=lambda: False, backup_dir=tmp_path / "bk")
    assert xmp.read_text() == MINIMAL
    assert not (tmp_path / "bk").exists()


def test_default_running_check_uses_exact_process_name(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 1)
    assert procs.darktable_running(run=fake_run) is False
    assert seen["cmd"] == ["pgrep", "-x", "darktable"]


def test_pending_round_trip(tmp_path):
    edit = pending.PendingEdit(id=pending.new_id(lambda: datetime(2026, 11, 27, 9, 0, 0)), raw="/p/a.CR2",
                               xmp="/p/a.CR2.xmp", original_sha="ab", new_text="<x/>",
                               diff=[["exposure.exposure", 1.0, 2.0]], preview=None, created="2026-11-27T09:00:00")
    assert edit.id.startswith("20261127-090000-")
    pending.save(edit, root=tmp_path)
    assert pending.load(edit.id, root=tmp_path) == edit
    pending.mark_applied(edit.id, root=tmp_path)
    assert pending.load(edit.id, root=tmp_path).applied is True
    with pytest.raises(LookupError, match="no pending edit"):
        pending.load("nope", root=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_writer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the four modules**

`dtk/state.py`:
```python
"""Where dtk keeps pending edits, previews and backups."""
from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    return Path(os.environ.get("DTK_STATE_DIR") or "~/.local/state/dtk").expanduser()
```

`dtk/procs.py`:
```python
"""Is darktable running? Exact process name only: a -f pattern can match unrelated processes."""
from __future__ import annotations

import subprocess


def darktable_running(run=None) -> bool:
    run = run or subprocess.run
    return run(["pgrep", "-x", "darktable"], capture_output=True).returncode == 0
```

`dtk/writer.py`:
```python
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
```

`dtk/pending.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_writer.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add dtk/state.py dtk/procs.py dtk/writer.py dtk/pending.py tests/test_writer.py
git commit -m "feat: guarded sidecar writer and pending edit records"
```

---

### Task 10: Edit planning

**Files:**
- Create: `dtk/values.py`, `dtk/editing.py`
- Test: `tests/test_editing.py`

**Interfaces:**
- Consumes: `dtk.blob`, `dtk.codec`, `dtk.schemas.load_schema/is_editable/current_version`, `dtk.xmp.parse_sidecar/with_appended_entries/HistoryEntry`.
- Produces: `dtk.values.EditRefused(ValueError)`, frozen dataclass `Change(module: str, path: tuple[str, ...], op: str, value: str)` (op is `"="`, `"+="` or `"-="`), `parse_set(arg: str) -> Change`, `apply_change(schema: dict, values: dict, change: Change) -> tuple[object, object]` (old, new; mutates `values`). `dtk.editing.EditPlan(new_text: str, diff: tuple[tuple[str, object, object], ...], discarded: int, instances: tuple[str, ...])`, `plan_edit(sidecar_text: str, changes: list[Change], instance: str | None = None, *, schema_for=None, editable=None, version_of=None) -> EditPlan`.
- Path syntax: `module.field`, with `.N` for an array index and `.name` for a struct member, e.g. `basecurve.basecurve.0.3.x`.

- [ ] **Step 1: Write the failing tests**

`tests/test_editing.py`:
```python
from pathlib import Path

import pytest

from dtk.blob import decode_param_string
from dtk.codec import decode
from dtk.editing import plan_edit
from dtk.values import Change, EditRefused, apply_change, parse_set
from dtk.xmp import parse_sidecar
from tests.schema_helpers import EXPOSURE_V7, nested, prim, schema

MINIMAL = (Path(__file__).parent / "fixtures" / "minimal.xmp").read_text()
CROP_V3 = schema("crop", [prim("cx", "float", lo=0.0, hi=1.0), prim("cy", "float", lo=0.0, hi=1.0),
                          prim("cw", "float", lo=0.0, hi=1.0), prim("ch", "float", lo=0.0, hi=1.0),
                          prim("ratio_n", "int"), prim("ratio_d", "int")], version=3)
SCHEMAS = {("exposure", 7): EXPOSURE_V7, ("crop", 3): CROP_V3}


def plan(text, *sets, instance=None, editable=lambda module: True, version_of=lambda module: {"exposure": 7, "crop": 3}.get(module)):
    return plan_edit(text, [parse_set(s) for s in sets], instance,
                     schema_for=lambda module, version: SCHEMAS[(module, version)],
                     editable=editable, version_of=version_of)


def last_values(text):
    entry = parse_sidecar(text).history[-1]
    raw, fmt = decode_param_string(entry.params)
    return entry, fmt, decode(SCHEMAS[(entry.operation, entry.modversion)], raw)


def test_parse_set():
    assert parse_set("exposure.exposure=+0.5") == Change("exposure", ("exposure",), "=", "+0.5")
    assert parse_set("basecurve.basecurve.0.3.x+=0.1") == Change("basecurve", ("basecurve", "0", "3", "x"), "+=", "0.1")
    with pytest.raises(EditRefused, match="module.field=value"):
        parse_set("exposure")


def test_absolute_edit_appends_an_entry_and_drops_undone_steps():
    result = plan(MINIMAL, "exposure.exposure=0.97")
    entry, fmt, values = last_values(result.new_text)
    assert result.discarded == 1
    assert parse_sidecar(result.new_text).history_end == 3
    assert (entry.num, entry.operation, entry.enabled, fmt) == (2, "exposure", True, "hex")
    assert values["exposure"] == pytest.approx(0.97, abs=1e-6)
    assert values["deflicker_percentile"] == 50.0
    assert result.diff[0][0] == "exposure.exposure"
    assert result.diff[0][1] == pytest.approx(1.97, abs=1e-5)


def test_relative_edit():
    _, _, values = last_values(plan(MINIMAL, "exposure.exposure+=1").new_text)
    assert values["exposure"] == pytest.approx(2.97, abs=1e-5)


def test_two_modules_make_two_entries():
    sidecar = parse_sidecar(plan(MINIMAL, "exposure.exposure=1", "crop.cx=0.1").new_text)
    assert [e.operation for e in sidecar.history[2:]] == ["exposure", "crop"]
    assert [e.num for e in sidecar.history[2:]] == [2, 3]


def test_enum_by_name():
    _, _, values = last_values(plan(MINIMAL, "exposure.mode=EXPOSURE_MODE_DEFLICKER").new_text)
    assert values["mode"] == 1


@pytest.mark.parametrize("arg, message", [
    ("exposure.exposure=40", "outside -18.0..18.0"),
    ("exposure.nonsense=1", "has no field 'nonsense'"),
    ("exposure.mode=SIDEWAYS", "unknown member"),
    ("exposure.compensate_hilite_pres=maybe", "true or false"),
    ("exposure.exposure=abc", "not a number"),
])
def test_bad_values_are_refused(arg, message):
    with pytest.raises(EditRefused, match=message):
        plan(MINIMAL, arg)


def test_module_not_in_history_is_refused():
    with pytest.raises(EditRefused, match="not in this image's history"):
        plan(MINIMAL, "temperature.red=1", version_of=lambda module: 4)


def test_non_editable_module_is_refused():
    with pytest.raises(EditRefused, match="not editable"):
        plan(MINIMAL, "exposure.exposure=1", editable=lambda module: False)


def test_old_module_version_is_refused():
    with pytest.raises(EditRefused, match="open the image in darktable once"):
        plan(MINIMAL, "exposure.exposure=1", version_of=lambda module: 8)


def test_instance_selection_by_name():
    with pytest.raises(EditRefused, match="no 'sky' instance"):
        plan(MINIMAL, "exposure.exposure=1", instance="sky")


def test_array_and_struct_paths():
    sch = schema("curve", [nested("nodes", [prim("x", "float", lo=0.0, hi=1.0), prim("y", "float")], dims=(2,))])
    values = {"nodes": [{"x": 0.1, "y": 0.0}, {"x": 0.9, "y": 1.0}]}
    old, new = apply_change(sch, values, parse_set("curve.nodes.1.x=0.5"))
    assert (old, new, values["nodes"][1]["x"]) == (0.9, 0.5, 0.5)
    with pytest.raises(EditRefused, match="add an index"):
        apply_change(sch, values, parse_set("curve.nodes=1"))
    with pytest.raises(EditRefused, match="index 5 is outside 0..1"):
        apply_change(sch, values, parse_set("curve.nodes.5.x=0.5"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_editing.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `dtk/values.py`**

```python
"""Apply one --set change to decoded params values, validating against the schema."""
from __future__ import annotations

import re
from dataclasses import dataclass

SET_RE = re.compile(r"^(?P<module>[a-z0-9_]+)\.(?P<path>[A-Za-z0-9_.]+?)(?P<op>\+=|-=|=)(?P<value>.+)$")
TRUE_WORDS, FALSE_WORDS = {"true", "1", "yes", "on"}, {"false", "0", "no", "off"}


class EditRefused(ValueError):
    """The requested edit is not allowed or not valid."""


@dataclass(frozen=True)
class Change:
    module: str
    path: tuple[str, ...]
    op: str
    value: str


def parse_set(arg: str) -> Change:
    match = SET_RE.match(arg.strip())
    if not match:
        raise EditRefused(f"cannot read --set {arg!r}; use module.field=value, module.field+=delta or -=delta")
    return Change(match["module"], tuple(match["path"].split(".")), match["op"], match["value"].strip())


def _member(fields: list[dict], name: str, owner: str) -> dict:
    for field in fields:
        if field["name"] == name:
            return field
    raise EditRefused(f"{owner} has no field {name!r}; see dtk show for field names")


def _is_text(field: dict, dims: list[int]) -> bool:
    return field["kind"] == "prim" and field["ctype"] in ("char", "gchar") and len(dims) == 1


def _coerce(field: dict, change: Change, old):
    label, text = ".".join((change.module,) + change.path), change.value
    if field["kind"] == "enum" or field["ctype"] == "gboolean" or isinstance(old, str):
        if change.op != "=":
            raise EditRefused(f"{label} only takes =, not {change.op}")
    if isinstance(old, str):
        return text
    if field["kind"] == "enum":
        if text.lstrip("-").isdigit():
            return int(text)
        number = (field.get("enum") or {}).get(text)
        if number is None:
            known = ", ".join(name for name, value in field["enum"].items() if value is not None)
            raise EditRefused(f"{label}: unknown member {text!r}; known: {known}")
        return number
    if field["ctype"] == "gboolean":
        if text.lower() in TRUE_WORDS:
            return 1
        if text.lower() in FALSE_WORDS:
            return 0
        raise EditRefused(f"{label} takes true or false, not {text!r}")
    try:
        number = float(text) if field["ctype"] in ("float", "double") else int(text)
    except ValueError:
        raise EditRefused(f"{label}: {text!r} is not a number") from None
    if change.op == "+=":
        return old + number
    if change.op == "-=":
        return old - number
    return number


def _check_range(field: dict, change: Change, value) -> None:
    low, high = field.get("min"), field.get("max")
    if isinstance(value, str):
        return
    if (isinstance(low, (int, float)) and value < low) or (isinstance(high, (int, float)) and value > high):
        label = ".".join((change.module,) + change.path)
        raise EditRefused(f"{label}={value} is outside {low}..{high}")


def apply_change(schema: dict, values: dict, change: Change) -> tuple[object, object]:
    field = _member(schema["fields"], change.path[0], change.module)
    container, key, dims = values, change.path[0], list(field["dims"])
    for segment in change.path[1:]:
        if dims and not _is_text(field, dims):
            if not segment.isdigit():
                raise EditRefused(f"{segment!r} is not an index into {field['name']}")
            index = int(segment)
            if index >= dims[0]:
                raise EditRefused(f"index {index} is outside 0..{dims[0] - 1} for {field['name']}")
            container, key, dims = container[key], index, dims[1:]
        elif field["kind"] == "struct":
            container = container[key]
            field = _member(field["fields"], segment, field["name"])
            key, dims = segment, list(field["dims"])
        else:
            raise EditRefused(f"{field['name']} has no member {segment!r}")
    if dims and not _is_text(field, dims):
        raise EditRefused(f"{field['name']} is an array; add an index, e.g. {'.'.join(change.path)}.0")
    if field["kind"] == "struct":
        raise EditRefused(f"{field['name']} is a struct; name one of its fields")
    old = container[key]
    new = _coerce(field, change, old)
    _check_range(field, change, new)
    container[key] = new
    return old, new
```

- [ ] **Step 4: Implement `dtk/editing.py`**

```python
"""Plan an edit: select the module instance, apply changes, append history entries."""
from __future__ import annotations

from dataclasses import dataclass, replace

from dtk import schemas
from dtk.blob import decode_param_string, encode_param_string
from dtk.codec import CodecError, decode, encode
from dtk.values import Change, EditRefused, apply_change
from dtk.xmp import HistoryEntry, parse_sidecar, with_appended_entries


@dataclass(frozen=True)
class EditPlan:
    new_text: str
    diff: tuple[tuple[str, object, object], ...]
    discarded: int
    instances: tuple[str, ...]


def _select_instance(active: tuple[HistoryEntry, ...], module: str, instance: str | None) -> HistoryEntry:
    matches = [entry for entry in active if entry.operation == module]
    if not matches:
        raise EditRefused(f"{module} is not in this image's history; enable it in darktable or apply a style first")
    if instance is not None:
        matches = [entry for entry in matches if entry.multi_name == instance]
        if not matches:
            raise EditRefused(f"{module} has no {instance!r} instance; dtk show lists instance names")
    return matches[-1]


def _label(entry: HistoryEntry) -> str:
    return f"{entry.operation} ({entry.multi_name or 'default instance'})"


def plan_edit(sidecar_text: str, changes: list[Change], instance: str | None = None, *,
              schema_for=None, editable=None, version_of=None) -> EditPlan:
    schema_for = schema_for or schemas.load_schema
    editable = editable or schemas.is_editable
    version_of = version_of or schemas.current_version
    sidecar = parse_sidecar(sidecar_text)
    if sidecar.history_end > len(sidecar.history):
        raise EditRefused("history_end points past the history stack; open the image in darktable to repair it")
    active = sidecar.history[:sidecar.history_end]
    grouped: dict[str, list[Change]] = {}
    for change in changes:
        grouped.setdefault(change.module, []).append(change)
    new_entries, diff, chosen = [], [], []
    for module, module_changes in grouped.items():
        if not editable(module):
            raise EditRefused(f"{module} is not editable yet (see dtk modules)")
        entry = _select_instance(active, module, instance)
        if entry.modversion != version_of(module):
            raise EditRefused(f"{module} is stored as v{entry.modversion} but dtk knows v{version_of(module)}; "
                              "open the image in darktable once to upgrade it, then retry")
        schema = schema_for(module, entry.modversion)
        raw, fmt = decode_param_string(entry.params)
        try:
            values = decode(schema, raw)
            for change in module_changes:
                old, new = apply_change(schema, values, change)
                diff.append((".".join((module,) + change.path), old, new))
            params = encode_param_string(encode(schema, values, base=raw), fmt)
        except CodecError as exc:
            raise EditRefused(str(exc)) from None
        new_entries.append(replace(entry, num=sidecar.history_end + len(new_entries), enabled=True, params=params))
        chosen.append(_label(entry))
    new_text, discarded = with_appended_entries(sidecar, new_entries)
    return EditPlan(new_text, tuple(diff), discarded, tuple(chosen))
```

Note: `num` uses `sidecar.history_end` because entries above it are discarded, so the first new entry takes index `history_end`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_editing.py -v`
Expected: 15 passed. (The parametrized test counts as 5.)

- [ ] **Step 6: Commit**

```bash
git add dtk/values.py dtk/editing.py tests/test_editing.py
git commit -m "feat: plan module edits as appended history entries"
```

---

### Task 11: CLI, docs, and Mac-only checks

**Files:**
- Create: `dtk/commands.py`, `dtk/cli.py`, `CLAUDE.md`, `README.md`, `tests/test_cli.py`, `tests/test_mac_live.py`

**Interfaces:**
- Consumes: everything above.
- Produces: console script `dtk` with subcommands `find`, `show`, `modules`, `export`, `edit`, `apply`; `dtk.cli.main(argv=None) -> int`.

- [ ] **Step 1: Write the failing CLI tests**

`tests/test_cli.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms

import dtk.procs as procs
import dtk.render as render
from dtk.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.fixture
def photo(tmp_path, monkeypatch):
    monkeypatch.setenv("DTK_STATE_DIR", str(tmp_path / "state"))
    raw = tmp_path / "photos" / "IMG_1.CR2"
    raw.parent.mkdir()
    raw.write_bytes(b"raw")
    shutil.copy(FIXTURES / "minimal.xmp", raw.with_name("IMG_1.CR2.xmp"))
    return raw


@pytest.fixture
def fake_darktable(monkeypatch):
    def run(cmd, **kwargs):
        Image.new("RGB", (640, 480), (90, 90, 90)).save(cmd[3], "JPEG", icc_profile=SRGB)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(render.subprocess, "run", run)


def test_modules_lists_exposure(capsys):
    assert main(["modules"]) == 0
    assert any(line.split()[:1] == ["exposure"] and "editable" in line for line in capsys.readouterr().out.splitlines())


def test_show_marks_undone_steps(photo, capsys):
    assert main(["show", str(photo)]) == 0
    out = capsys.readouterr().out
    assert "exposure" in out and "crop" in out and "undone" in out


def test_edit_then_apply(photo, capsys, monkeypatch):
    assert main(["edit", str(photo), "--set", "exposure.exposure=0.5", "--no-preview"]) == 0
    out = capsys.readouterr().out
    edit_id = next(line.split()[-1] for line in out.splitlines() if line.startswith("apply with: dtk apply"))
    assert photo.with_name("IMG_1.CR2.xmp").read_text() == (FIXTURES / "minimal.xmp").read_text()
    monkeypatch.setattr(procs, "darktable_running", lambda run=None: False)
    assert main(["apply", edit_id]) == 0
    assert 'darktable:history_end="3"' in photo.with_name("IMG_1.CR2.xmp").read_text()
    assert main(["apply", edit_id]) == 1
    assert "already applied" in capsys.readouterr().err


def test_edit_refusal_is_one_line_on_stderr(photo, capsys):
    assert main(["edit", str(photo), "--set", "exposure.exposure=99", "--no-preview"]) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("dtk: ") and "outside" in err and "\n" not in err


def test_edit_with_preview(photo, fake_darktable, capsys):
    assert main(["edit", str(photo), "--set", "exposure.exposure=0.5"]) == 0
    preview = next(line.split(": ", 1)[1] for line in capsys.readouterr().out.splitlines() if line.startswith("preview: "))
    assert Path(preview).exists()


def test_export_with_preset(photo, fake_darktable, capsys):
    xmp = photo.with_name("IMG_1.CR2.xmp")
    before = xmp.read_bytes()
    assert main(["export", str(photo), "--preset", "messenger"]) == 0
    assert (photo.parent / "messenger" / "IMG_1.jpg").exists()
    assert xmp.read_bytes() == before


def test_export_refuses_to_overwrite_its_source(tmp_path, fake_darktable, capsys):
    jpeg = tmp_path / "shot.jpg"
    Image.new("RGB", (10, 10)).save(jpeg)
    shutil.copy(FIXTURES / "minimal.xmp", tmp_path / "shot.jpg.xmp")
    assert main(["export", str(jpeg), "--preset", "messenger", "--out", str(tmp_path)]) == 1
    assert "would overwrite" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtk.cli'`.

- [ ] **Step 3: Implement `dtk/commands.py`**

```python
"""Implementations of the dtk subcommands. Each returns an exit code."""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

from dtk import pending, render
from dtk.blob import decode_param_string
from dtk.codec import CodecError, decode
from dtk.editing import plan_edit
from dtk.images import resolve_image
from dtk.library import DEFAULT_DATA, DEFAULT_LIBRARY, find_images, snapshot
from dtk.presets import load_preset, out_dir_for
from dtk.schemas import current_version, load_corpus_report, load_index, load_schema
from dtk.state import state_dir
from dtk.values import EditRefused, parse_set
from dtk.writer import sha256_bytes, write_xmp
from dtk.xmp import parse_sidecar

SUMMARY_FIELDS = 6


def _library_snapshot() -> Path:
    return snapshot(DEFAULT_LIBRARY, Path(tempfile.mkdtemp(prefix="dtk-library-")))


def _data_snapshot() -> Path:
    return snapshot(DEFAULT_DATA, Path(tempfile.mkdtemp(prefix="dtk-data-")))


def cmd_find(args) -> int:
    images = find_images(_library_snapshot(), _data_snapshot() if args.tag else None, roll=args.roll,
                         rating_min=args.rating, tag=args.tag, edited=True if args.edited else None,
                         since=date.fromisoformat(args.since) if args.since else None)
    for image in images:
        stars = "rejected" if image.rating < 0 else "*" * image.rating or "-"
        taken = image.taken.strftime("%Y-%m-%d") if image.taken else "----------"
        print(f"{image.id:>6}  {stars:<8} {'edited' if image.edited else '      '}  {taken}  {image.path}")
    print(f"{len(images)} images")
    return 0


def _summary(entry) -> str:
    version = current_version(entry.operation)
    if version is None:
        return "(no schema)"
    if version != entry.modversion:
        return f"(stored v{entry.modversion}, dtk knows v{version})"
    try:
        values = decode(load_schema(entry.operation, version), decode_param_string(entry.params)[0])
    except CodecError as exc:
        return f"(cannot decode: {exc})"
    shown = [f"{name}={value:.4g}" if isinstance(value, float) else f"{name}={value}"
             for name, value in values.items() if not isinstance(value, (list, dict))]
    more = len(values) - len(shown[:SUMMARY_FIELDS])
    return " ".join(shown[:SUMMARY_FIELDS]) + (f" (+{more} more)" if more > 0 else "")


def cmd_show(args) -> int:
    files = resolve_image(args.image, _library_snapshot)
    sidecar = parse_sidecar(files.xmp.read_text(encoding="utf-8"))
    print(f"{files.raw}  history_end={sidecar.history_end}")
    for entry in sidecar.history:
        state = "undone" if entry.num >= sidecar.history_end else ("on" if entry.enabled else "off")
        instance = f" [{entry.multi_name}]" if entry.multi_name else ""
        print(f"{entry.num:>3} {state:<6} {entry.operation}{instance} v{entry.modversion}  {_summary(entry)}")
    return 0


def cmd_modules(args) -> int:
    report = load_corpus_report()
    for module, entry in sorted(load_index().items()):
        row = report.get(module, {"status": "unknown", "blobs": 0})
        if row["status"] == "unsupported" and not args.all:
            continue
        print(f"{module:<20} v{entry['version']:<3} {row['status']:<11} {row['blobs']:>4} blobs")
    return 0


def cmd_export(args) -> int:
    preset = load_preset(args.preset)
    for image in args.images:
        files = resolve_image(image, _library_snapshot)
        out_dir = Path(args.out).expanduser() if args.out else out_dir_for(preset, files.raw)
        out = out_dir / f"{files.raw.stem}.jpg"
        if str(out.resolve()).casefold() == str(files.raw.resolve()).casefold():
            raise EditRefused(f"exporting {files.raw.name} to {out_dir} would overwrite the source; pick another --out")
        render.render(files.raw, files.xmp.read_text(encoding="utf-8"), out, preset.spec)
        print(out)
    return 0


def cmd_edit(args) -> int:
    files = resolve_image(args.image, _library_snapshot)
    original = files.xmp.read_bytes()
    text = original.decode("utf-8")
    plan = plan_edit(text, [parse_set(arg) for arg in args.set], args.instance)
    edit_id = pending.new_id()
    preview = None
    if not args.no_preview:
        folder = state_dir() / "previews" / edit_id
        before = render.render(files.raw, text, folder / "before.jpg", render.PREVIEW_SPEC)
        after = render.render(files.raw, plan.new_text, folder / "after.jpg", render.PREVIEW_SPEC)
        preview = str(render.side_by_side(before, after, folder / "before-after.jpg"))
    pending.save(pending.PendingEdit(id=edit_id, raw=str(files.raw), xmp=str(files.xmp),
                                     original_sha=sha256_bytes(original), new_text=plan.new_text,
                                     diff=[list(row) for row in plan.diff], preview=preview,
                                     created=datetime.now().isoformat(timespec="seconds")))
    print("editing: " + ", ".join(plan.instances))
    for label, old, new in plan.diff:
        print(f"  {label}: {old} -> {new}")
    if plan.discarded:
        print(f"warning: {plan.discarded} undone history step(s) will be discarded, as darktable does")
    if preview:
        print(f"preview: {preview}")
    print(f"apply with: dtk apply {edit_id}")
    return 0


def cmd_apply(args) -> int:
    edit = pending.load(args.id)
    if edit.applied:
        raise EditRefused(f"edit {edit.id} is already applied")
    backup = write_xmp(Path(edit.xmp), edit.new_text, edit.original_sha)
    pending.mark_applied(edit.id)
    print(f"wrote {edit.xmp} (backup: {backup})")
    print("open darktable: it should offer to reload the changed sidecar")
    return 0
```

- [ ] **Step 4: Implement `dtk/cli.py`**

```python
"""dtk command-line entry point."""
from __future__ import annotations

import argparse
import sys

from dtk import commands
from dtk.blob import BlobError
from dtk.codec import CodecError
from dtk.images import ImageNotFound
from dtk.render import RenderError
from dtk.schemas import SchemaMissing
from dtk.values import EditRefused
from dtk.writer import WriteRefused
from dtk.xmp import XmpError

REFUSALS = (EditRefused, WriteRefused, RenderError, ImageNotFound, XmpError, CodecError, BlobError,
            SchemaMissing, LookupError, ValueError)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dtk", description="Query, export and edit darktable photos.")
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find", help="list images in the darktable library")
    find.add_argument("--roll")
    find.add_argument("--rating", type=int)
    find.add_argument("--tag")
    find.add_argument("--edited", action="store_true")
    find.add_argument("--since", metavar="YYYY-MM-DD")
    find.set_defaults(handler=commands.cmd_find)

    show = sub.add_parser("show", help="decoded history stack of one image")
    show.add_argument("image", help="raw path, sidecar path, or library id")
    show.set_defaults(handler=commands.cmd_show)

    modules = sub.add_parser("modules", help="which modules dtk can edit")
    modules.add_argument("--all", action="store_true", help="include unsupported modules")
    modules.set_defaults(handler=commands.cmd_modules)

    export = sub.add_parser("export", help="render images with a preset")
    export.add_argument("images", nargs="+")
    export.add_argument("--preset", required=True)
    export.add_argument("--out")
    export.set_defaults(handler=commands.cmd_export)

    edit = sub.add_parser("edit", help="preview an edit; writes nothing to your sidecars")
    edit.add_argument("image")
    edit.add_argument("--set", action="append", required=True, metavar="MODULE.FIELD=VALUE")
    edit.add_argument("--instance", help="multi_name of the module instance to edit")
    edit.add_argument("--no-preview", action="store_true", help="skip rendering the before/after")
    edit.set_defaults(handler=commands.cmd_edit)

    apply = sub.add_parser("apply", help="write a previewed edit to the real sidecar")
    apply.add_argument("id")
    apply.set_defaults(handler=commands.cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except REFUSALS as exc:
        message = " ".join(str(exc).split())
        print(f"dtk: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run CLI tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 7 passed. `test_modules_lists_exposure` depends on Task 6's committed `corpus.json`.

- [ ] **Step 6: Write the Mac-only checks `tests/test_mac_live.py`**

```python
"""Opt-in checks against Joel's real darktable install. Run on the Mac:

    uv run pytest -m corpus      # live sidecars agree with the committed corpus report
    DTK_TEST_RAW=~/Pictures/Darktable/20261126_no_name/20261126_0002.CR2 uv run pytest -m darktable
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from dtk import corpus, render
from dtk.editing import plan_edit
from dtk.library import DEFAULT_LIBRARY, find_images, snapshot
from dtk.presets import load_preset
from dtk.schemas import load_corpus_report
from dtk.values import parse_set
from dtk.writer import sha256_bytes

needs_cli = pytest.mark.skipif(not Path(render.cli_path()).exists(), reason="darktable-cli not installed")


def live_sidecars():
    library = snapshot(DEFAULT_LIBRARY, Path(tempfile.mkdtemp()))
    paths = [image.path.with_name(image.path.name + ".xmp") for image in find_images(library)]
    return [path for path in paths if path.exists()]


@pytest.mark.corpus
def test_live_sidecars_agree_with_committed_report():
    live = corpus.evaluate(corpus.blobs_from_sidecars(live_sidecars()))
    for module, row in load_corpus_report().items():
        if row["status"] == "editable" and live[module]["blobs"]:
            assert live[module]["status"] == "editable", (module, live[module]["problems"])


@pytest.fixture
def test_raw():
    path = Path(os.environ.get("DTK_TEST_RAW", "")).expanduser()
    if not path.is_file():
        pytest.skip("set DTK_TEST_RAW to a raw with a sidecar")
    return path


def mean_luminance(path):
    with Image.open(path) as image:
        return ImageStat.Stat(image.convert("L")).mean[0]


@pytest.mark.darktable
@needs_cli
def test_plus_one_ev_renders_brighter(test_raw, tmp_path):
    text = test_raw.with_name(test_raw.name + ".xmp").read_text()
    plan = plan_edit(text, [parse_set("exposure.exposure+=1")])
    spec = render.RenderSpec(width=512, height=512)
    before = render.render(test_raw, text, tmp_path / "before.jpg", spec)
    after = render.render(test_raw, plan.new_text, tmp_path / "after.jpg", spec)
    assert mean_luminance(after) > mean_luminance(before) * 1.3


@pytest.mark.darktable
@needs_cli
def test_messenger_export_leaves_the_sidecar_alone(test_raw, tmp_path):
    xmp = test_raw.with_name(test_raw.name + ".xmp")
    before = sha256_bytes(xmp.read_bytes())
    preset = load_preset("messenger")
    out = render.render(test_raw, xmp.read_text(), tmp_path / "m.jpg", preset.spec)
    assert sha256_bytes(xmp.read_bytes()) == before
    with Image.open(out) as image:
        assert max(image.size) <= 2048
    if shutil.which("magick"):
        quality = subprocess.run(["magick", "identify", "-format", "%Q", str(out)],
                                 capture_output=True, text=True).stdout.strip()
        assert quality == "90"
```

Run: `uv run pytest -v`
Expected: all default tests pass; the Mac tests are deselected (shown in the summary as deselected).

- [ ] **Step 7: Write `CLAUDE.md`**

```markdown
# darktable-kit (`dtk`)

CLI for darktable 5.6.1: query the library, export with presets, preview and apply module edits by writing
XMP sidecars. Spec: `docs/superpowers/specs/2026-11-27-darktable-kit-design.md`.

## Rules
- `dtk/writer.py` is the ONLY code that writes a real sidecar. It refuses while darktable runs
  (`pgrep -x darktable`, never `-f`), refuses stale previews (SHA-256), backs up to
  `~/.local/state/dtk/backups/`, writes atomically, and re-reads.
- Nothing writes `library.db` or `data.db`. Queries run on a temp snapshot.
- darktable-cli only ever sees a temp symlink to the raw and a COPY of the sidecar, with
  `write_sidecar_files=never`. Never pass a real sidecar path to it.
- A render counts only if the file exists, fits the size, and has an sRGB profile when asked: the exit code is not
  the report.
- A module is editable only if `dtk/schemas/5.6.1/corpus.json` says `editable`. Never hand-edit schema JSON or
  corpus.json; fix the generator and regenerate.
- Tests never touch real files. `pytest -m corpus` and `pytest -m darktable` are Mac-only, opt-in.

## Regenerating after a darktable upgrade
1. `git -C ~/git/github/darktable-org/darktable fetch --depth 1 origin tag release-X.Y.Z && git -C ... checkout release-X.Y.Z`
2. Change `DT_VERSION` in `dtk/schemas.py` and `DEFAULT_OUT` in `schemagen/build.py`.
3. `uv run python -m schemagen.build`, then `uv run python -m dtk.corpus`, then `uv run pytest`.
4. Refresh `tests/fixtures/preset_params.json` from the new `data.db` (built-in presets, `writeprotect = 1`).

## Restoring a sidecar
Quit darktable, copy the backup from `~/.local/state/dtk/backups/` over the sidecar, reopen darktable and accept
the reload prompt.
```

- [ ] **Step 8: Write `README.md`**

```markdown
# darktable-kit

`dtk` works with darktable 5.6.1 from the terminal.

    uv sync
    uv run dtk find --edited
    uv run dtk show 66
    uv run dtk export 66 67 --preset messenger
    uv run dtk edit 66 --set exposure.exposure+=0.5 --set colorbalancergb.saturation_global=0.15
    uv run dtk apply <id>          # darktable must be closed
    uv run dtk modules             # what can be edited

`edit` writes nothing to your sidecars; it renders a before/after into `~/.local/state/dtk/previews/`.
`apply` writes the sidecar after backing it up. When darktable next opens it should offer to reload the
changed sidecar; the edit shows as a new step in the history panel and can be undone there.

Values: `=` sets, `+=`/`-=` adjust. Arrays and nested fields use dots: `basecurve.basecurve.0.3.x=0.5`.
Enums take member names (`exposure.mode=EXPOSURE_MODE_DEFLICKER`), booleans take true/false.
```

- [ ] **Step 9: Run the full suite and the CLI by hand**

```bash
uv run pytest -v
uv run dtk modules
uv run dtk show tests/fixtures/minimal.xmp
```
The `show` command needs a raw next to the sidecar, so it will refuse with `dtk: .../minimal does not exist`; that one-line refusal is the expected output. Paste the `dtk modules` output into the PR description.

- [ ] **Step 10: Commit**

```bash
git add dtk/commands.py dtk/cli.py CLAUDE.md README.md tests/test_cli.py tests/test_mac_live.py
git commit -m "feat: dtk CLI, docs, and opt-in Mac checks"
```

---

## After merge (on the Mac, with Joel)

These cannot run on the build box (no darktable.app, no real photos):

1. `uv run pytest -m corpus` and `DTK_TEST_RAW=~/Pictures/Darktable/20261126_no_name/20261126_0002.CR2 uv run pytest -m darktable`.
2. Manual check from the spec: `dtk edit 66 --set exposure.exposure+=0.3`, look at the preview, `dtk apply <id>` with darktable closed, open darktable, confirm the reload prompt, the new history step, and that undo works. Record the outcome in the spec's Testing section.
