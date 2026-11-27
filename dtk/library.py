"""Read-only queries on a snapshot of darktable's library.db."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_LIBRARY = Path(os.environ.get("DTK_LIBRARY") or "~/.config/darktable/library.db").expanduser()
DEFAULT_DATA = Path(os.environ.get("DTK_DATA") or "~/.config/darktable/data.db").expanduser()
EPOCH = datetime(1, 1, 1)
RATING_MASK, RATING_REJECTED, FLAG_REJECTED = 7, 6, 8

SELECT = """
select i.id, f.folder, i.filename, i.flags, i.datetime_taken, h.basic_hash, h.auto_hash, h.current_hash
from images i join film_rolls f on f.id = i.film_id left join history_hash h on h.imgid = i.id
"""


@dataclass(frozen=True)
class Image:
    id: int
    path: Path
    rating: int
    edited: bool
    taken: datetime | None


def to_timespan(day: date) -> int:
    return (datetime(day.year, day.month, day.day) - EPOCH) // timedelta(microseconds=1)


def from_timespan(value: int | None) -> datetime | None:
    return None if value is None else EPOCH + timedelta(microseconds=value)


def snapshot(src: Path, dest_dir: Path) -> Path:
    if not src.is_file():
        raise LookupError(f"no darktable library at {src}; set DTK_LIBRARY (or DTK_DATA) to its path")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return dest


def _rating(flags: int) -> int:
    stars = flags & RATING_MASK
    return -1 if stars == RATING_REJECTED or flags & FLAG_REJECTED else stars


def _image(row) -> Image:
    image_id, folder, filename, flags, taken, basic, auto, current = row
    edited = current is not None and current != basic and current != auto
    return Image(image_id, Path(folder) / filename, _rating(flags or 0), edited, from_timespan(taken))


def find_images(library: Path, data: Path | None = None, *, roll: str | None = None, rating_min: int | None = None,
                tag: str | None = None, edited: bool | None = None, since: date | None = None) -> list[Image]:
    clauses, params = [], []
    if roll:
        clauses.append("f.folder like '%' || ? || '%'")
        params.append(roll)
    if since:
        clauses.append("i.datetime_taken >= ?")
        params.append(to_timespan(since))
    conn = sqlite3.connect(f"file:{library}?mode=ro", uri=True)  # uri=True so the attach below honours its URI
    try:
        if tag:
            if data is None:
                raise ValueError("filtering by tag needs data.db")
            conn.execute("attach database ? as data", (f"file:{data}?mode=ro",))
            clauses.append("i.id in (select ti.imgid from tagged_images ti join data.tags t on t.id = ti.tagid "
                           "where t.name like '%' || ? || '%')")
            params.append(tag)
        where = f" where {' and '.join(clauses)}" if clauses else ""
        rows = conn.execute(SELECT + where + " order by f.folder, i.filename", params).fetchall()
    finally:
        conn.close()
    images = [_image(row) for row in rows]
    if rating_min is not None:
        images = [image for image in images if image.rating >= rating_min]
    if edited is not None:
        images = [image for image in images if image.edited == edited]
    return images


def image_by_id(library: Path, image_id: int) -> Image:
    conn = sqlite3.connect(library)
    try:
        row = conn.execute(SELECT + " where i.id = ?", (image_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"no image with id {image_id} in the darktable library")
    return _image(row)
