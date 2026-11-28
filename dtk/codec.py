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
    except (struct.error, OverflowError) as exc:
        raise CodecError(f"{field['name']}: {exc}") from None


def enum_value(field: dict, name: str) -> int:
    members = field.get("enum") or {}
    if members.get(name) is None:
        known = ", ".join(member for member, number in members.items() if number is not None)
        raise CodecError(f"{field['name']}: unknown member {name!r}; known: {known}")
    return members[name]
