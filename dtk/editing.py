"""Plan an edit: select the module instance, apply changes, append history entries."""
from __future__ import annotations

from dataclasses import dataclass, replace

from dtk import schemas
from dtk.blob import decode_param_string, encode_param_string
from dtk.codec import CodecError, decode, encode
from dtk.values import Change, EditRefused, apply_change
from dtk.xmp import HistoryEntry, parse_sidecar, with_appended_entries


@dataclass(frozen=True)
class EditPlan:
    new_text: str
    diff: tuple[tuple[str, object, object], ...]
    discarded: int
    instances: tuple[str, ...]


def _select_instance(active: tuple[HistoryEntry, ...], module: str, instance: str | None) -> HistoryEntry:
    matches = [entry for entry in active if entry.operation == module]
    if not matches:
        raise EditRefused(f"{module} is not in this image's history; enable it in darktable or apply a style first")
    if instance is not None:
        matches = [entry for entry in matches if entry.multi_name == instance]
        if not matches:
            raise EditRefused(f"{module} has no {instance!r} instance; dtk show lists instance names")
    return matches[-1]


def _label(entry: HistoryEntry) -> str:
    return f"{entry.operation} ({entry.multi_name or 'default instance'})"


def plan_edit(sidecar_text: str, changes: list[Change], instance: str | None = None, *,
              schema_for=None, editable=None, version_of=None) -> EditPlan:
    schema_for = schema_for or schemas.load_schema
    editable = editable or schemas.is_editable
    version_of = version_of or schemas.current_version
    sidecar = parse_sidecar(sidecar_text)
    if sidecar.history_end > len(sidecar.history):
        raise EditRefused("history_end points past the history stack; open the image in darktable to repair it")
    active = sidecar.history[:sidecar.history_end]
    grouped: dict[str, list[Change]] = {}
    for change in changes:
        grouped.setdefault(change.module, []).append(change)
    new_entries, diff, chosen = [], [], []
    for module, module_changes in grouped.items():
        if not editable(module):
            raise EditRefused(f"{module} is not editable yet (see dtk modules)")
        entry = _select_instance(active, module, instance)
        if entry.modversion != version_of(module):
            raise EditRefused(f"{module} is stored as v{entry.modversion} but dtk knows v{version_of(module)}; "
                              "open the image in darktable once to upgrade it, then retry")
        schema = schema_for(module, entry.modversion)
        raw, fmt = decode_param_string(entry.params)
        try:
            values = decode(schema, raw)
            for change in module_changes:
                old, new = apply_change(schema, values, change)
                diff.append((".".join((module,) + change.path), old, new))
            params = encode_param_string(encode(schema, values, base=raw), fmt)
        except CodecError as exc:
            raise EditRefused(str(exc)) from None
        new_entries.append(replace(entry, num=sidecar.history_end + len(new_entries), enabled=True, params=params))
        chosen.append(_label(entry))
    new_text, discarded = with_appended_entries(sidecar, new_entries)
    return EditPlan(new_text, tuple(diff), discarded, tuple(chosen))
