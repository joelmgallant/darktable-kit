from schemagen.build import TypeTable, build_module_schema, int_names
from tests.test_ctext import BASECURVE_SRC, EXPOSURE_SRC


def build(module, src, header=""):
    shared = TypeTable()
    shared.add_source(header)
    return build_module_schema(module, src, shared, int_names(shared, {}))


def test_exposure_schema():
    schema = build("exposure", "DT_MODULE_INTROSPECTION(7, dt_iop_exposure_params_t)\n" + EXPOSURE_SRC)
    assert schema["status"] == "ok"
    assert schema["version"] == 7
    assert [f["name"] for f in schema["fields"]] == ["mode", "black", "exposure", "compensate_exposure_bias"]
    mode, black = schema["fields"][0], schema["fields"][1]
    assert mode["kind"] == "enum"
    assert mode["enum"] == {"EXPOSURE_MODE_MANUAL": 0, "EXPOSURE_MODE_DEFLICKER": 1}
    assert mode["default"] == "EXPOSURE_MODE_MANUAL"
    assert (black["min"], black["max"], black["description"]) == (-1.0, 1.0, "black level correction")
    assert schema["fields"][3]["default"] == 0
    assert schema["size"] == 16


def test_basecurve_resolves_macros_and_nested_structs():
    schema = build("basecurve", "DT_MODULE_INTROSPECTION(6, dt_iop_basecurve_params_t)\n" + BASECURVE_SRC)
    curve = schema["fields"][0]
    assert curve["kind"] == "struct"
    assert curve["dims"] == [3, 20]
    assert schema["fields"][1]["max"] == 20
    assert schema["size"] == 3 * 20 * 8 + 3 * 4 + 4 + 4


def test_types_from_shared_headers():
    header = "typedef enum dt_image_orientation_t\n{\n  ORIENTATION_NONE = 0,\n  ORIENTATION_FLIP_Y = 1 << 0\n} dt_image_orientation_t;\n"
    src = ("DT_MODULE_INTROSPECTION(2, dt_iop_flip_params_t)\n"
           "typedef struct dt_iop_flip_params_t\n{\n  dt_image_orientation_t orientation;\n} dt_iop_flip_params_t;\n")
    schema = build("flip", src, header)
    assert schema["fields"][0]["enum"] == {"ORIENTATION_NONE": 0, "ORIENTATION_FLIP_Y": 1}


def test_unknown_type_marks_module_unsupported():
    src = ("DT_MODULE_INTROSPECTION(1, dt_iop_x_params_t)\n"
           "typedef struct dt_iop_x_params_t\n{\n  dt_mystery_t value;\n} dt_iop_x_params_t;\n")
    schema = build("x", src)
    assert schema["status"] == "unsupported"
    assert "dt_mystery_t" in schema["reason"]
    assert schema["fields"] == []


def test_files_without_introspection_are_skipped():
    assert build("helper", "int x;") is None
