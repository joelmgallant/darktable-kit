from dataclasses import replace
from pathlib import Path

import pytest

from dtk.xmp import XmpError, parse_sidecar, with_appended_entries

FIXTURES = Path(__file__).parent / "fixtures"
MINIMAL = (FIXTURES / "minimal.xmp").read_text()
REAL = sorted((FIXTURES / "sidecars").glob("*.xmp"))


def test_parse_minimal():
    sidecar = parse_sidecar(MINIMAL)
    assert sidecar.history_end == 2
    assert [entry.operation for entry in sidecar.history] == ["exposure", "crop", "exposure"]
    first = sidecar.history[0]
    assert (first.num, first.enabled, first.modversion, first.multi_priority) == (0, True, 7, 0)
    assert sidecar.has_masks_history is False


def test_append_discards_undone_entries_and_moves_history_end():
    sidecar = parse_sidecar(MINIMAL)
    new_entry = replace(sidecar.history[0], num=2, params="00" * 28)
    text, discarded = with_appended_entries(sidecar, [new_entry])
    reparsed = parse_sidecar(text)
    assert discarded == 1
    assert reparsed.history_end == 3
    assert reparsed.history == (sidecar.history[0], sidecar.history[1], new_entry)
    assert 'darktable:history_end="3"' in text


def test_untouched_lines_are_kept_verbatim():
    sidecar = parse_sidecar(MINIMAL)
    text, _ = with_appended_entries(sidecar, [replace(sidecar.history[0], num=2)])
    head = MINIMAL.split('darktable:num="2"')[0].rsplit("<rdf:li", 1)[0]
    assert text.startswith(head.replace('history_end="2"', 'history_end="3"'))


def test_appending_nothing_to_a_real_sidecar_changes_nothing():
    checked = 0
    for path in REAL:
        sidecar = parse_sidecar(path.read_text())
        if sidecar.history and sidecar.history_end == len(sidecar.history):
            assert with_appended_entries(sidecar, []) == (sidecar.text, 0), path.name
            checked += 1
    assert checked >= 1


def test_multi_name_is_escaped_and_unescaped():
    sidecar = parse_sidecar(MINIMAL)
    named = replace(sidecar.history[0], num=2, multi_name="sky & <sun>")
    text, _ = with_appended_entries(sidecar, [named])
    assert 'darktable:multi_name="sky &amp; &lt;sun&gt;"' in text
    assert parse_sidecar(text).history[-1].multi_name == "sky & <sun>"


MASK_ENTRY = ('<darktable:masks_history>\n    <rdf:Seq>\n     <rdf:li darktable:mask_num="2" darktable:mask_id="1"'
              ' darktable:mask_type="2" darktable:mask_name="circle #1" darktable:mask_version="6"'
              ' darktable:mask_points="00" darktable:mask_nb="1" darktable:mask_src="0000"/>\n'
              '    </rdf:Seq>\n   </darktable:masks_history>')


def test_discarding_with_masks_in_masks_history_is_refused():
    text = MINIMAL.replace("</darktable:history>", "</darktable:history>\n   " + MASK_ENTRY)
    sidecar = parse_sidecar(text)
    assert sidecar.has_masks_history is True
    with pytest.raises(XmpError, match="masks"):
        with_appended_entries(sidecar, [replace(sidecar.history[0], num=2)])


def test_empty_masks_history_of_a_real_sidecar_allows_discarding():
    # every real sidecar carries <darktable:masks_history><rdf:Seq/></darktable:masks_history>
    real = (FIXTURES / "sidecars" / "sidecar_04.xmp").read_text()
    assert "<rdf:Seq/>" in real.split("<darktable:masks_history>", 1)[1].split("</darktable:masks_history>", 1)[0]
    total = len(parse_sidecar(real).history)
    sidecar = parse_sidecar(real.replace(f'darktable:history_end="{total}"', f'darktable:history_end="{total - 2}"'))
    assert sidecar.has_masks_history is False
    new_entry = replace(sidecar.history[0], num=total - 2)
    text, discarded = with_appended_entries(sidecar, [new_entry])
    reparsed = parse_sidecar(text)
    assert discarded == 2
    assert reparsed.history == sidecar.history[:total - 2] + (new_entry,)
    assert reparsed.history_end == total - 1


def test_sidecar_without_history():
    sidecar = parse_sidecar('<rdf:Description darktable:history_end="0"/>')
    assert sidecar.history == ()
    with pytest.raises(XmpError, match="no history stack"):
        with_appended_entries(sidecar, [])
