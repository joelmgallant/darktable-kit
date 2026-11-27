import pytest

from schemagen.ctext import (ParseError, eval_int, find_aliases, find_defines, find_typedefs, parse_annotations,
                             parse_enum_body, parse_struct_body, resolve_ints)

EXPOSURE_SRC = '''
typedef enum dt_iop_exposure_mode_t
{
  EXPOSURE_MODE_MANUAL,   // $DESCRIPTION: "manual"
  EXPOSURE_MODE_DEFLICKER // $DESCRIPTION: "automatic"
} dt_iop_exposure_mode_t;

typedef struct dt_iop_exposure_params_t
{
  dt_iop_exposure_mode_t mode;      // $DEFAULT: EXPOSURE_MODE_MANUAL
  float black;                      // $MIN: -1.0 $MAX: 1.0 $DEFAULT: 0.0 $DESCRIPTION: "black level correction"
  float exposure;                   // $MIN: -18.0 $MAX: 18.0 $DEFAULT: 0.0
  gboolean compensate_exposure_bias;// $DEFAULT: FALSE $DESCRIPTION: "compensate exposure bias"
} dt_iop_exposure_params_t;

int legacy_params(void)
{
  typedef struct dt_iop_exposure_params_v6_t
  {
    float black;
  } dt_iop_exposure_params_v6_t;
}
'''

BASECURVE_SRC = '''
#define MAXNODES 20
typedef struct dt_iop_basecurve_node_t
{
  float x; // $MIN: 0.0 $MAX: 1.0
  float y; // $MIN: 0.0 $MAX: 1.0
} dt_iop_basecurve_node_t;

typedef struct dt_iop_basecurve_params_t
{
  // three curves (c, ., .) with max number of nodes
  dt_iop_basecurve_node_t basecurve[3][MAXNODES];
  int basecurve_nodes[3]; // $MIN: 0 $MAX: MAXNODES $DEFAULT: 0
  int exposure_fusion;    /* number of exposure fusion steps
                             $DEFAULT: 0 $DESCRIPTION: "fusion" */
  float exposure_stops;   /* number of stops between fusion images
                             $MIN: 0.01 $MAX: 4.0 $DEFAULT: 1.0 $DESCRIPTION: "exposure shift" */
} dt_iop_basecurve_params_t;
'''


def test_find_typedefs_ignores_indented_legacy_structs():
    found = find_typedefs(EXPOSURE_SRC)
    assert set(found) == {"dt_iop_exposure_mode_t", "dt_iop_exposure_params_t"}
    assert found["dt_iop_exposure_mode_t"][0] == "enum"
    assert found["dt_iop_exposure_params_t"][0] == "struct"


def test_struct_fields_and_trailing_annotations():
    body = find_typedefs(EXPOSURE_SRC)["dt_iop_exposure_params_t"][1]
    fields = parse_struct_body(body)
    assert [(f.ctype, f.name) for f in fields] == [
        ("dt_iop_exposure_mode_t", "mode"), ("float", "black"), ("float", "exposure"),
        ("gboolean", "compensate_exposure_bias")]
    assert parse_annotations(fields[1].note) == {
        "min": "-1.0", "max": "1.0", "default": "0.0", "description": "black level correction"}
    assert parse_annotations(fields[0].note) == {"default": "EXPOSURE_MODE_MANUAL"}


def test_block_comment_annotations_span_lines():
    body = find_typedefs(BASECURVE_SRC)["dt_iop_basecurve_params_t"][1]
    fields = {f.name: f for f in parse_struct_body(body)}
    assert fields["basecurve"].dims == ("3", "MAXNODES")
    assert parse_annotations(fields["exposure_fusion"].note) == {"default": "0", "description": "fusion"}
    assert parse_annotations(fields["exposure_stops"].note)["max"] == "4.0"
    assert parse_annotations(fields["basecurve_nodes"].note)["max"] == "MAXNODES"


def test_defines_and_int_expressions():
    defines = find_defines(BASECURVE_SRC + "\n#define TWICE (MAXNODES * 2) // comment\n#define F(x) x\n")
    assert defines == {"MAXNODES": "20", "TWICE": "(MAXNODES * 2)"}
    assert resolve_ints(defines, {}) == {"MAXNODES": 20, "TWICE": 40}
    assert eval_int("0x10 + 2U", {}) == 18
    assert eval_int("UNKNOWN + 1", {}) is None
    assert eval_int("7 / 2", {}) == 3


def test_enum_values_implicit_and_explicit():
    body = "A, B = 5, C, // $DESCRIPTION: \"c\"\n D = A | 8, E = MISSING, F"
    assert parse_enum_body(body, {}) == {"A": 0, "B": 5, "C": 6, "D": 8, "E": None, "F": None}


def test_scalar_aliases():
    src = "typedef int32_t dt_imgid_t;\ntypedef struct foo foo;\ntypedef unsigned int uint;\n"
    assert find_aliases(src) == {"dt_imgid_t": "int32_t", "uint": "unsigned int"}


def test_multiple_declarators():
    fields = parse_struct_body("float x, y[2]; // $MIN: 0\n")
    assert [(f.name, f.dims) for f in fields] == [("x", ()), ("y", ("2",))]


@pytest.mark.parametrize("body", ["float *values;", "union { int a; float b; } u;", "void (*fn)(void);"])
def test_unsupported_declarations_raise(body):
    with pytest.raises(ParseError):
        parse_struct_body(body)


def test_indented_top_level_typedefs_count_but_function_local_ones_do_not():
    # src/common/rgb_norms.h indents its enum typedef by one space at file scope
    src = " typedef enum dt_iop_rgb_norms_t\n {\n   DT_RGB_NORM_NONE = 0,\n } dt_iop_rgb_norms_t;\n" + EXPOSURE_SRC
    found = find_typedefs(src)
    assert found["dt_iop_rgb_norms_t"][0] == "enum"
    assert "dt_iop_exposure_params_v6_t" not in found
