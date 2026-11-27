import json
from pathlib import Path

import pytest

import dtk.corpus as corpus
from dtk.codec import encode
from dtk.schemas import SCHEMA_DIR
from tests.schema_helpers import enum, prim, schema

FIXTURES = Path(__file__).parent / "fixtures"
UNIT = schema("unit", [prim("level", "float", lo=0.0, hi=1.0), prim("on", "gboolean"), enum("mode", {"A": 0, "B": 1})])


@pytest.fixture
def unit_index(monkeypatch):
    index = {"unit": {"module": "unit", "version": 1, "status": "ok", "reason": None},
             "broken": {"module": "broken", "version": 2, "status": "unsupported", "reason": "unknown type x"}}
    monkeypatch.setattr(corpus, "load_index", lambda: index)
    monkeypatch.setattr(corpus, "load_schema", lambda module, version: UNIT)


def blob(level=0.5, on=1, mode=0):
    return encode(UNIT, {"level": level, "on": on, "mode": mode})


def test_in_range_blobs_make_a_module_editable(unit_index):
    report = corpus.evaluate([("unit", 1, blob(), "a"), ("unit", 1, blob(level=1.0), "b")])
    assert report["unit"] == {"status": "editable", "version": 1, "blobs": 2, "problems": []}
    assert report["broken"]["status"] == "unsupported"


@pytest.mark.parametrize("bad, reason", [
    (blob(level=7.5), "level=7.5 is above 1.0"),
    (blob(on=2), "on=2 is not a boolean"),
    (blob(mode=9), "mode=9 is not a member"),
    (b"\0\0\0\0", "blob is 4 bytes"),
])
def test_one_bad_blob_makes_a_module_read_only(unit_index, bad, reason):
    report = corpus.evaluate([("unit", 1, blob(), "good"), ("unit", 1, bad, "bad")])
    assert report["unit"]["status"] == "read-only"
    assert any(reason in problem for problem in report["unit"]["problems"])


def test_blobs_at_other_versions_do_not_count(unit_index):
    assert corpus.evaluate([("unit", 0, blob(), "old")])["unit"]["status"] == "no-corpus"


def test_committed_report_is_current():
    blobs = corpus.blobs_from_presets(FIXTURES / "preset_params.json")
    blobs += corpus.blobs_from_sidecars(sorted((FIXTURES / "sidecars").glob("*.xmp")))
    committed = json.loads((SCHEMA_DIR / "corpus.json").read_text())
    assert corpus.evaluate(blobs) == committed


def test_exposure_is_editable():
    committed = json.loads((SCHEMA_DIR / "corpus.json").read_text())
    assert committed["exposure"]["status"] == "editable", committed["exposure"]["problems"]
