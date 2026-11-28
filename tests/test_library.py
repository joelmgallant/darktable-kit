import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from dtk.images import ImageNotFound, resolve_image, versioned_name
from dtk.library import find_images, from_timespan, image_by_id, snapshot, to_timespan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def library(tmp_path):
    lib, data = tmp_path / "library.db", tmp_path / "data.db"
    with sqlite3.connect(lib) as conn:
        conn.executescript((FIXTURES / "library_schema.sql").read_text())
        conn.executemany("insert into film_rolls (id, folder) values (?, ?)",
                         [(1, "/photos/iceland"), (2, "/photos/moon")])
        rows = [  # id, film, filename, flags, taken
            (1, 1, "a.CR2", 4, to_timespan(date(2025, 7, 1))),
            (2, 1, "b.CR2", 6, to_timespan(date(2025, 7, 2))),      # rating 6 = rejected
            (3, 2, "c.CR2", 2 | 8, to_timespan(date(2026, 11, 26))),  # flag 8 = rejected
            (4, 2, "d.CR2", 5, to_timespan(date(2026, 11, 26))),
        ]
        conn.executemany("insert into images (id, film_id, filename, flags, datetime_taken) values (?, ?, ?, ?, ?)",
                         rows)
        conn.executemany("insert into history_hash (imgid, basic_hash, auto_hash, current_hash) values (?, ?, ?, ?)",
                         [(1, b"b", b"a", b"x"), (4, b"b", b"a", b"a")])
        conn.execute("insert into tagged_images (imgid, tagid) values (4, 10)")
    with sqlite3.connect(data) as conn:
        conn.executescript((FIXTURES / "data_tags_schema.sql").read_text())
        conn.execute("insert into tags (id, name) values (10, 'sky|moon')")
    return lib, data


def ids(images):
    return [image.id for image in images]


def test_find_all_sorted_by_path(library):
    images = find_images(library[0])
    assert ids(images) == [1, 2, 3, 4]
    assert images[0].path == Path("/photos/iceland/a.CR2")
    assert images[0].taken == datetime(2025, 7, 1)


def test_ratings_and_rejects(library):
    by_id = {image.id: image for image in find_images(library[0])}
    assert (by_id[1].rating, by_id[2].rating, by_id[3].rating, by_id[4].rating) == (4, -1, -1, 5)
    assert ids(find_images(library[0], rating_min=4)) == [1, 4]


def test_edited_means_current_differs_from_basic_and_auto(library):
    assert ids(find_images(library[0], edited=True)) == [1]
    assert ids(find_images(library[0], edited=False)) == [2, 3, 4]


def test_roll_tag_and_since_filters(library):
    lib, data = library
    assert ids(find_images(lib, roll="moon")) == [3, 4]
    assert ids(find_images(lib, data, tag="moon")) == [4]
    assert ids(find_images(lib, since=date(2026, 1, 1))) == [3, 4]


def test_timespan_round_trip():
    assert from_timespan(63931318832360000).year == 2026
    assert from_timespan(to_timespan(date(2020, 2, 29))) == datetime(2020, 2, 29)
    assert from_timespan(None) is None


def test_snapshot_copies_without_touching_the_source(library, tmp_path):
    lib, _ = library
    before = lib.read_bytes()
    copy = snapshot(lib, tmp_path / "snap")
    assert copy != lib and ids(find_images(copy)) == [1, 2, 3, 4]
    assert lib.read_bytes() == before


def test_image_by_id_and_missing(library):
    assert image_by_id(library[0], 4).path.name == "d.CR2"
    with pytest.raises(LookupError):
        image_by_id(library[0], 99)


def test_resolve_image_by_path(tmp_path):
    raw = tmp_path / "IMG_1.CR2"
    raw.write_bytes(b"")
    (tmp_path / "IMG_1.CR2.xmp").write_text("<x/>")
    files = resolve_image(str(raw), library_snapshot=lambda: pytest.fail("library not needed"))
    assert files.xmp == tmp_path / "IMG_1.CR2.xmp"
    assert resolve_image(str(files.xmp), library_snapshot=lambda: None).raw == raw


def test_resolve_image_refuses_missing_sidecar(tmp_path):
    raw = tmp_path / "IMG_2.CR2"
    raw.write_bytes(b"")
    with pytest.raises(ImageNotFound, match="no sidecar"):
        resolve_image(str(raw), library_snapshot=lambda: None)


def test_snapshot_of_a_missing_library_is_a_clear_refusal(tmp_path):
    with pytest.raises(LookupError, match="no darktable library at .*DTK_LIBRARY"):
        snapshot(tmp_path / "missing.db", tmp_path / "snap")


@pytest.fixture
def duplicates(tmp_path):
    """An original (version 0) and one darktable duplicate (version 1) of the same raw, files on disk."""
    folder = tmp_path / "roll"
    folder.mkdir()
    (folder / "IMG_1.CR2").write_bytes(b"raw")
    (folder / "IMG_1.CR2.xmp").write_text("<original/>")
    (folder / "IMG_1_01.CR2.xmp").write_text("<duplicate/>")
    lib = tmp_path / "library.db"
    with sqlite3.connect(lib) as conn:
        conn.executescript((FIXTURES / "library_schema.sql").read_text())
        conn.execute("insert into film_rolls (id, folder) values (1, ?)", (str(folder),))
        conn.executemany("insert into images (id, film_id, filename, flags, version) values (?, 1, 'IMG_1.CR2', 1, ?)",
                         [(1, 0), (2, 1)])
    return lib, folder


def test_images_carry_their_duplicate_version(duplicates):
    lib, _ = duplicates
    assert [(image.id, image.version) for image in find_images(lib)] == [(1, 0), (2, 1)]
    assert image_by_id(lib, 2).version == 1


def test_library_id_of_a_duplicate_resolves_to_its_own_sidecar(duplicates):
    lib, folder = duplicates
    original = resolve_image("1", library_snapshot=lambda: lib)
    duplicate = resolve_image("2", library_snapshot=lambda: lib)
    assert (original.raw, original.xmp, original.version) == (folder / "IMG_1.CR2", folder / "IMG_1.CR2.xmp", 0)
    assert (duplicate.raw, duplicate.xmp, duplicate.version) == (folder / "IMG_1.CR2", folder / "IMG_1_01.CR2.xmp", 1)


def test_duplicate_sidecar_path_resolves_to_the_raw(duplicates):
    _, folder = duplicates
    files = resolve_image(str(folder / "IMG_1_01.CR2.xmp"), library_snapshot=lambda: pytest.fail("no library"))
    assert (files.raw, files.xmp, files.version) == (folder / "IMG_1.CR2", folder / "IMG_1_01.CR2.xmp", 1)


def test_raw_whose_own_name_ends_in_digits_is_not_a_duplicate(tmp_path):
    raw = tmp_path / "DSC_0001.NEF"
    raw.write_bytes(b"raw")
    (tmp_path / "DSC_0001.NEF.xmp").write_text("<x/>")
    files = resolve_image(str(tmp_path / "DSC_0001.NEF.xmp"), library_snapshot=lambda: None)
    assert (files.raw, files.version) == (raw, 0)


def test_missing_duplicate_sidecar_names_the_versioned_path(duplicates):
    lib, folder = duplicates
    (folder / "IMG_1_01.CR2.xmp").unlink()
    with pytest.raises(ImageNotFound, match="IMG_1_01.CR2.xmp"):
        resolve_image("2", library_snapshot=lambda: lib)


@pytest.mark.parametrize("version, expected", [(0, "IMG_1.CR2"), (1, "IMG_1_01.CR2"), (42, "IMG_1_42.CR2"),
                                               (100, "IMG_1_100.CR2"), (999, "IMG_1_999.CR2")])
def test_versioned_name_follows_darktable(version, expected):
    # src/common/image.c dt_image_path_append_version_no_db: "_%02d" before the last '.', version 0 unchanged
    assert versioned_name("IMG_1.CR2", version) == expected
