"""Comments and integer constant expressions (#define values, enum values, array sizes) in C text."""
from __future__ import annotations

import ast
import math
import re
import sys
from typing import Callable

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


# Standard C / glib constants darktable uses in $MIN/$MAX annotations, with their exact values.
STANDARD_CONSTANTS: dict[str, int | float] = {
    "FLT_MAX": float.fromhex("0x1.fffffep+127"), "FLT_MIN": float.fromhex("0x1p-126"),
    "FLT_EPSILON": float.fromhex("0x1p-23"), "DBL_MAX": sys.float_info.max, "DBL_MIN": sys.float_info.min,
    "G_MAXFLOAT": float.fromhex("0x1.fffffep+127"), "G_MINFLOAT": float.fromhex("0x1p-126"),
    "INT_MAX": 2**31 - 1, "INT_MIN": -2**31, "UINT_MAX": 2**32 - 1,
    "INT8_MAX": 127, "INT8_MIN": -128, "UINT8_MAX": 255, "INT16_MAX": 32767, "INT16_MIN": -32768,
    "UINT16_MAX": 65535, "INT32_MAX": 2**31 - 1, "INT32_MIN": -2**31, "UINT32_MAX": 2**32 - 1,
    "G_MAXINT": 2**31 - 1, "G_MININT": -2**31, "G_MAXUINT": 2**32 - 1, "G_MAXINT16": 32767,
    "G_MAXUINT16": 65535, "G_MAXUINT8": 255,
    "M_PI": math.pi, "M_PI_2": math.pi / 2, "M_PI_4": math.pi / 4, "M_1_PI": 1 / math.pi, "M_2_PI": 2 / math.pi,
    "M_E": math.e, "M_LN2": math.log(2), "M_LN10": math.log(10), "M_SQRT2": math.sqrt(2),
    "M_SQRT1_2": math.sqrt(0.5), "G_PI": math.pi,
}
NUMBER_TOKEN_RE = re.compile(r"\s*((?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[fFuUlL]*|0[xX][0-9a-fA-F]+[uUlL]*"
                             r"|[A-Za-z_]\w*|[-+*/()])")
_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b}


def _literal(token: str) -> int | float:
    if token[:2].lower() == "0x":
        return int(token.rstrip("uUlL"), 16)
    digits = token.rstrip("fFuUlL") if not re.search(r"[eE]", token) else token.rstrip("fF")
    return float(digits) if re.search(r"[.eE]", digits) else int(digits)


def _divide(left: int | float, right: int | float) -> int | float:
    if isinstance(left, int) and isinstance(right, int):
        quotient = abs(left) // abs(right)  # C integer division truncates toward zero
        return quotient if (left >= 0) == (right >= 0) else -quotient
    return left / right


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _divide(_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    raise ValueError(f"unsupported expression node {type(node).__name__}")


def eval_number(expr: str, lookup: Callable[[str], int | float | None]) -> int | float | None:
    """Evaluate a C constant expression of numbers, names, unary +/-, + - * / and parentheses; None if it can't.

    Names resolve through lookup, then STANDARD_CONSTANTS. Nothing is passed to eval: the expression is
    rebuilt from vetted tokens and walked as a whitelisted AST.
    """
    expr = strip_comments(expr).strip()
    pieces, position = [], 0
    while position < len(expr):
        match = NUMBER_TOKEN_RE.match(expr, position)
        if not match:
            return None
        token, position = match.group(1), match.end()
        if token[0].isalpha() or token[0] == "_":
            value = lookup(token)
            value = STANDARD_CONSTANTS.get(token) if value is None else value
            if value is None:
                return None
            pieces.append(f"({value!r})")
        elif token[0].isdigit() or token[0] == ".":
            pieces.append(repr(_literal(token)))
        else:
            pieces.append(token)
        while position < len(expr) and expr[position].isspace():
            position += 1
    if not pieces:
        return None
    try:
        result = _evaluate(ast.parse(" ".join(pieces), mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return result if math.isfinite(result) else None
