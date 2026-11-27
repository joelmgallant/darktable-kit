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
