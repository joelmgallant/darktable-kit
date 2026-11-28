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
