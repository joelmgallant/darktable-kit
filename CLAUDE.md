# darktable-kit (`dtk`)

CLI for darktable 5.6.1: query the library, export with presets, preview and apply module edits by writing
XMP sidecars. Spec: `docs/superpowers/specs/2026-11-27-darktable-kit-design.md`.

## Rules
- `dtk/writer.py` is the ONLY code that writes a real sidecar. It refuses while darktable runs
  (`pgrep -x darktable`, never `-f`), refuses stale previews (SHA-256), backs up to
  `~/.local/state/dtk/backups/`, writes atomically, and re-reads.
- Nothing writes `library.db` or `data.db`. Queries run on a temp snapshot.
- darktable-cli only ever sees a temp symlink to the raw and a COPY of the sidecar, with
  `write_sidecar_files=never`. Never pass a real sidecar path to it.
- A render counts only if the file exists, fits the size, and has an sRGB profile when asked: the exit code is not
  the report.
- A module is editable only if `dtk/schemas/5.6.1/corpus.json` says `editable`. Never hand-edit schema JSON or
  corpus.json; fix the generator and regenerate.
- Tests never touch real files. `pytest -m corpus` and `pytest -m darktable` are Mac-only, opt-in.

## Regenerating after a darktable upgrade
1. `git -C ~/git/github/darktable-org/darktable fetch --depth 1 origin tag release-X.Y.Z && git -C ... checkout release-X.Y.Z`
2. Change `DT_VERSION` in `dtk/schemas.py` and `DEFAULT_OUT` in `schemagen/build.py`.
3. `uv run python -m schemagen.build`, then `uv run python -m dtk.corpus`, then `uv run pytest`.
4. Refresh `tests/fixtures/preset_params.json` from the new `data.db` (built-in presets, `writeprotect = 1`).

## Restoring a sidecar
Quit darktable, copy the backup from `~/.local/state/dtk/backups/` over the sidecar, reopen darktable and accept
the reload prompt.
