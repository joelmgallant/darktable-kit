"""Implementations of the dtk subcommands. Each returns an exit code."""
from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

from dtk import pending, render
from dtk.blob import decode_param_string
from dtk.codec import CodecError, decode
from dtk.editing import plan_edit
from dtk.images import resolve_image
from dtk.library import DEFAULT_DATA, DEFAULT_LIBRARY, find_images, snapshot
from dtk.presets import load_preset, out_dir_for
from dtk.schemas import current_version, load_corpus_report, load_index, load_schema
from dtk.state import state_dir
from dtk.values import EditRefused, parse_set
from dtk.writer import sha256_bytes, write_xmp
from dtk.xmp import parse_sidecar

SUMMARY_FIELDS = 6


def _library_snapshot() -> Path:
    return snapshot(DEFAULT_LIBRARY, Path(tempfile.mkdtemp(prefix="dtk-library-")))


def _data_snapshot() -> Path:
    return snapshot(DEFAULT_DATA, Path(tempfile.mkdtemp(prefix="dtk-data-")))


def cmd_find(args) -> int:
    images = find_images(_library_snapshot(), _data_snapshot() if args.tag else None, roll=args.roll,
                         rating_min=args.rating, tag=args.tag, edited=True if args.edited else None,
                         since=date.fromisoformat(args.since) if args.since else None)
    for image in images:
        stars = "rejected" if image.rating < 0 else "*" * image.rating or "-"
        taken = image.taken.strftime("%Y-%m-%d") if image.taken else "----------"
        print(f"{image.id:>6}  {stars:<8} {'edited' if image.edited else '      '}  {taken}  {image.path}")
    print(f"{len(images)} images")
    return 0


def _summary(entry) -> str:
    version = current_version(entry.operation)
    if version is None:
        return "(no schema)"
    if version != entry.modversion:
        return f"(stored v{entry.modversion}, dtk knows v{version})"
    try:
        values = decode(load_schema(entry.operation, version), decode_param_string(entry.params)[0])
    except CodecError as exc:
        return f"(cannot decode: {exc})"
    shown = [f"{name}={value:.4g}" if isinstance(value, float) else f"{name}={value}"
             for name, value in values.items() if not isinstance(value, (list, dict))]
    more = len(values) - len(shown[:SUMMARY_FIELDS])
    return " ".join(shown[:SUMMARY_FIELDS]) + (f" (+{more} more)" if more > 0 else "")


def cmd_show(args) -> int:
    files = resolve_image(args.image, _library_snapshot)
    sidecar = parse_sidecar(files.xmp.read_text(encoding="utf-8"))
    print(f"{files.raw}  history_end={sidecar.history_end}")
    for entry in sidecar.history:
        state = "undone" if entry.num >= sidecar.history_end else ("on" if entry.enabled else "off")
        instance = f" [{entry.multi_name}]" if entry.multi_name else ""
        print(f"{entry.num:>3} {state:<6} {entry.operation}{instance} v{entry.modversion}  {_summary(entry)}")
    return 0


def cmd_modules(args) -> int:
    report = load_corpus_report()
    for module, entry in sorted(load_index().items()):
        row = report.get(module, {"status": "unknown", "blobs": 0})
        if row["status"] == "unsupported" and not args.all:
            continue
        print(f"{module:<20} v{entry['version']:<3} {row['status']:<11} {row['blobs']:>4} blobs")
    return 0


def cmd_export(args) -> int:
    preset = load_preset(args.preset)
    for image in args.images:
        files = resolve_image(image, _library_snapshot)
        out_dir = Path(args.out).expanduser() if args.out else out_dir_for(preset, files.raw)
        out = out_dir / f"{files.raw.stem}.jpg"
        if str(out.resolve()).casefold() == str(files.raw.resolve()).casefold():
            raise EditRefused(f"exporting {files.raw.name} to {out_dir} would overwrite the source; pick another --out")
        render.render(files.raw, files.xmp.read_text(encoding="utf-8"), out, preset.spec)
        print(out)
    return 0


def cmd_edit(args) -> int:
    files = resolve_image(args.image, _library_snapshot)
    original = files.xmp.read_bytes()
    text = original.decode("utf-8")
    plan = plan_edit(text, [parse_set(arg) for arg in args.set], args.instance)
    edit_id = pending.new_id()
    preview = None
    if not args.no_preview:
        folder = state_dir() / "previews" / edit_id
        before = render.render(files.raw, text, folder / "before.jpg", render.PREVIEW_SPEC)
        after = render.render(files.raw, plan.new_text, folder / "after.jpg", render.PREVIEW_SPEC)
        preview = str(render.side_by_side(before, after, folder / "before-after.jpg"))
    pending.save(pending.PendingEdit(id=edit_id, raw=str(files.raw), xmp=str(files.xmp),
                                     original_sha=sha256_bytes(original), new_text=plan.new_text,
                                     diff=[list(row) for row in plan.diff], preview=preview,
                                     created=datetime.now().isoformat(timespec="seconds")))
    print("editing: " + ", ".join(plan.instances))
    for label, old, new in plan.diff:
        print(f"  {label}: {old} -> {new}")
    if plan.discarded:
        print(f"warning: {plan.discarded} undone history step(s) will be discarded, as darktable does")
    if preview:
        print(f"preview: {preview}")
    print(f"apply with: dtk apply {edit_id}")
    return 0


def cmd_apply(args) -> int:
    edit = pending.load(args.id)
    if edit.applied:
        raise EditRefused(f"edit {edit.id} is already applied")
    backup = write_xmp(Path(edit.xmp), edit.new_text, edit.original_sha)
    pending.mark_applied(edit.id)
    print(f"wrote {edit.xmp} (backup: {backup})")
    print("open darktable: it should offer to reload the changed sidecar")
    return 0
