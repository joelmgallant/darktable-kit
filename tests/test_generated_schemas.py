from dtk.codec import struct_size
from dtk.schemas import current_version, load_index, load_schema


def field_names(module):
    return [field["name"] for field in load_schema(module, current_version(module))["fields"]]


def test_exposure_v7_matches_the_spike_layout():
    assert current_version("exposure") == 7
    assert field_names("exposure") == ["mode", "black", "exposure", "deflicker_percentile",
                                       "deflicker_target_level", "compensate_exposure_bias",
                                       "compensate_hilite_pres"]
    assert struct_size(load_schema("exposure", 7)) == 28


def test_crop_temperature_and_flip():
    assert (current_version("crop"), struct_size(load_schema("crop", 3))) == (3, 24)
    assert (current_version("temperature"), struct_size(load_schema("temperature", 4))) == (4, 20)
    assert load_schema("flip", 2)["fields"][0]["kind"] == "enum"


def test_module_name_is_the_file_stem():
    assert load_index()["toneequal"]["struct"] == "dt_iop_toneequalizer_params_t"


def test_index_sizes_match_codec_sizes():
    for module, entry in load_index().items():
        if entry["status"] == "ok":
            assert entry["size"] == struct_size(load_schema(module, entry["version"])), module
