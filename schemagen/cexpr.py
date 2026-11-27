"""Comments and integer constant expressions (#define values, enum values, array sizes) in C text."""
from __future__ import annotations

import re

DEFINE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]+)$", re.M)
COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
INT_TOKEN_RE = re.compile(r"\s*(0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|<<|>>|[-+*/%()|&~^])")


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub(" ", text)


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
