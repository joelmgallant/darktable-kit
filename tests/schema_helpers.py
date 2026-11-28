"""Hand-written schemas for unit tests, independent of generated files."""


def prim(name, ctype, dims=(), lo=None, hi=None):
    return {"name": name, "kind": "prim", "ctype": ctype, "dims": list(dims),
            "min": lo, "max": hi, "default": None, "description": None}


def enum(name, members, dims=()):
    return {"name": name, "kind": "enum", "ctype": "test_enum_t", "dims": list(dims), "enum": dict(members),
            "min": None, "max": None, "default": None, "description": None}


def nested(name, fields, dims=()):
    return {"name": name, "kind": "struct", "ctype": "test_struct_t", "dims": list(dims), "fields": fields,
            "min": None, "max": None, "default": None, "description": None}


def schema(module, fields, version=1):
    return {"module": module, "version": version, "struct": f"dt_iop_{module}_params_t",
            "status": "ok", "reason": None, "size": None, "fields": fields}


EXPOSURE_V7 = schema("exposure", [
    enum("mode", {"EXPOSURE_MODE_MANUAL": 0, "EXPOSURE_MODE_DEFLICKER": 1}),
    prim("black", "float", lo=-1.0, hi=1.0),
    prim("exposure", "float", lo=-18.0, hi=18.0),
    prim("deflicker_percentile", "float", lo=0.0, hi=100.0),
    prim("deflicker_target_level", "float", lo=-18.0, hi=18.0),
    prim("compensate_exposure_bias", "gboolean"),
    prim("compensate_hilite_pres", "gboolean"),
], version=7)

EXPOSURE_V7_HEX = "00000000000080b9f828fc3f00004842000080c00100000001000000"
