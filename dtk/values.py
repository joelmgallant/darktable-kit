"""Apply one --set change to decoded params values, validating against the schema."""
from __future__ import annotations

import math
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
        members = field.get("enum") or {}
        known = ", ".join(name for name, value in members.items() if value is not None)
        if text.lstrip("-").isdigit():
            if int(text) not in members.values():
                raise EditRefused(f"{label}={text} is not a member; known: {known}")
            return int(text)
        number = members.get(text)
        if number is None:
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
    if not math.isfinite(number):
        raise EditRefused(f"{label} must be a finite number, not {text!r}")
    if change.op == "+=":
        number = old + number
    elif change.op == "-=":
        number = old - number
    if not math.isfinite(number):
        raise EditRefused(f"{label} must stay a finite number")
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
