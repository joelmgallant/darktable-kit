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


def test_float_too_large_for_float32_is_a_codec_error():
    with pytest.raises(CodecError, match="exposure"):
        encode(EXPOSURE_V7, {**decode(EXPOSURE_V7, bytes.fromhex(EXPOSURE_V7_HEX)), "exposure": 1e39})
