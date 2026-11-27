import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from dtk.images import ImageNotFound, resolve_image
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
