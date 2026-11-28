"""darktable XMP sidecars: read the history stack, append entries without disturbing the rest."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

HISTORY_RE = re.compile(r"<darktable:history>\s*<rdf:Seq>(?P<body>.*?)\s*</rdf:Seq>\s*</darktable:history>", re.S)
LI_RE = re.compile(r"<rdf:li\b(?P<attrs>[^>]*?)/>", re.S)
ATTR_RE = re.compile(r'(\w+:\w+)="([^"]*)"')
HISTORY_END_RE = re.compile(r'darktable:history_end="(\d+)"')
MASKS_HISTORY_RE = re.compile(r"<darktable:masks_history>(?P<body>.*?)</darktable:masks_history>", re.S)
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
    has_masks_history: bool  # masks_history has at least one entry


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
                   has_masks_history=_has_mask_entries(text))


def _has_mask_entries(text: str) -> bool:
    """True when masks_history holds at least one rdf:li. darktable writes an empty <rdf:Seq/> into every sidecar."""
    masks = MASKS_HISTORY_RE.search(text)
    return bool(masks and re.search(r"<rdf:li\b", masks.group("body")))


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
