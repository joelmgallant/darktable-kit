"""Scanning helpers for the C subset darktable uses in iop params declarations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from schemagen.cexpr import eval_int, find_defines, resolve_ints, strip_comments

__all__ = ["ParseError", "RawField", "eval_int", "find_aliases", "find_defines", "find_typedefs", "match_brace",
           "parse_annotations", "parse_enum_body", "parse_struct_body", "resolve_ints", "strip_comments"]


class ParseError(ValueError):
    """The C text uses a construct this scanner does not model."""


TYPEDEF_BLOCK_RE = re.compile(r"^(?P<indent>[ \t]*)typedef[ \t]+(struct|enum)\b[ \t]*(?:[A-Za-z_]\w*)?\s*\{", re.M)
TYPEDEF_ALIAS_RE = re.compile(
    r"^typedef[ \t]+((?:unsigned[ \t]+|signed[ \t]+)?[A-Za-z_]\w*)[ \t]+([A-Za-z_]\w*)[ \t]*;", re.M)
LITERAL_OR_COMMENT_RE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', re.S)
ANNOTATION_RE = re.compile(r'\$(MIN|MAX|DEFAULT|DESCRIPTION):\s*("(?:[^"\\]|\\.)*"|[^\s$,]+)')
DECL_RE = re.compile(r"^(?P<ctype>(?:(?:const|unsigned|signed)\s+)*[A-Za-z_]\w*)\s+(?P<declarators>.+)$", re.S)
DECLARATOR_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(?P<dims>(?:\[[^\]]+\]\s*)*)$")


@dataclass(frozen=True)
class RawField:
    ctype: str
    name: str
    dims: tuple[str, ...]
    note: str


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


def _blank_comments_and_literals(src: str) -> str:
    return LITERAL_OR_COMMENT_RE.sub(lambda found: " " * len(found.group(0)), src)


def _at_file_scope(blanked: str, index: int) -> bool:
    return blanked.count("{", 0, index) == blanked.count("}", 0, index)


def find_typedefs(src: str) -> dict[str, tuple[str, str]]:
    """Typedef'd struct/enum bodies at file scope.

    A typedef at column 0 always counts. An indented one counts only outside every brace: headers such as
    src/common/rgb_norms.h indent file-scope typedefs, while legacy params structs sit indented inside functions.
    """
    found: dict[str, tuple[str, str]] = {}
    blanked = None
    for match in TYPEDEF_BLOCK_RE.finditer(src):
        if match.group("indent"):
            blanked = blanked if blanked is not None else _blank_comments_and_literals(src)
            if not _at_file_scope(blanked, match.start()):
                continue
        open_index = match.end() - 1
        try:
            close_index = match_brace(src, open_index)
        except ParseError:
            continue
        tail = re.match(r"\s*([A-Za-z_]\w*)\s*;", src[close_index + 1:])
        if tail:
            found[tail.group(1)] = (match.group(2), src[open_index + 1:close_index])
    return found


def find_aliases(src: str) -> dict[str, str]:
    return {alias: " ".join(target.split()) for target, alias in TYPEDEF_ALIAS_RE.findall(src)
            if target not in ("struct", "enum", "union")}


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
