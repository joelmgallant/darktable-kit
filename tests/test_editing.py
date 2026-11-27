from dataclasses import replace
from pathlib import Path

import pytest

from dtk.blob import decode_param_string, encode_param_string
from dtk.codec import decode
from dtk.editing import plan_edit
from dtk.values import Change, EditRefused, apply_change, parse_set
from dtk.xmp import parse_sidecar, with_appended_entries
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


def with_extra_exposure(text, *, enabled, multi_name="", multi_priority=0, params=None):
    sidecar = parse_sidecar(text)
    first = sidecar.history[0]
    extra = replace(first, num=sidecar.history_end, enabled=enabled, multi_name=multi_name,
                    multi_priority=multi_priority, params=params or first.params)
    return with_appended_entries(sidecar, [extra])[0]


def test_switched_off_module_is_refused_not_re_enabled():
    text = with_extra_exposure(MINIMAL, enabled=False)
    with pytest.raises(EditRefused, match="switched off"):
        plan(text, "exposure.black=0.01")


def test_topmost_enabled_instance_is_chosen_when_another_is_off():
    # instance 1 ("sky") is on; the default instance's latest entry switches it off
    text = with_extra_exposure(MINIMAL, enabled=True, multi_name="sky", multi_priority=1)
    text = with_extra_exposure(text, enabled=False)
    result = plan(text, "exposure.exposure=0.5")
    entry, _, _ = last_values(result.new_text)
    assert (entry.multi_name, entry.multi_priority, entry.enabled) == ("sky", 1, True)


def test_gz_entries_stay_gz():
    raw, _ = decode_param_string(parse_sidecar(MINIMAL).history[0].params)
    text = with_extra_exposure(MINIMAL, enabled=True, params=encode_param_string(raw, "gz"))
    entry, fmt, values = last_values(plan(text, "exposure.exposure=0.5").new_text)
    assert fmt == "gz" and values["exposure"] == 0.5


@pytest.mark.parametrize("arg, message", [
    ("exposure.exposure=nan", "finite"),
    ("exposure.deflicker_percentile=inf", "finite"),
    ("exposure.mode=7", "not a member"),
])
def test_non_finite_and_unknown_enum_numbers_are_refused(arg, message):
    with pytest.raises(EditRefused, match=message):
        plan(MINIMAL, arg)


def test_enum_member_number_is_accepted():
    _, _, values = last_values(plan(MINIMAL, "exposure.mode=1").new_text)
    assert values["mode"] == 1
