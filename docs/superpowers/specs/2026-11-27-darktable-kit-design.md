# darktable-kit (`dtk`) design

Date: 2026-11-27
Status: approved design, not yet implemented

## Goal

Let Claude Code (and Joel, by hand) work with darktable 5.6.1 on macOS from the terminal:

- query the darktable library,
- batch-export edited raws with named presets,
- preview and apply edits to darktable modules by writing XMP sidecars,

without a running GUI and without a patched darktable build.

## Non-goals (v1)

- Live control of the open darktable GUI (a Lua bridge is a possible phase 2).
- An MCP server. `dtk` is a CLI; Claude drives it from Bash and reads preview JPEGs with Read.
- Adding a module that is not already in an image's history stack.
- Editing masks or drawn shapes.
- Writing to `library.db` or `data.db`.

## Context established by the spike (2026-11-26)

- darktable: `/Applications/darktable.app`, version 5.6.1, Lua API 9.7.0 compiled in. The bundle has
  `darktable-cli` but no `darktable-mcp`.
- Config: `~/.config/darktable/`. `library.db` holds 69 images in 8 film rolls (23 edited) at spike time.
- `write_sidecar_files=on import`, so every image has an XMP sidecar `<raw>.xmp` next to it.
- `run_crawler_on_start=TRUE`: darktable looks for XMP files changed outside it at startup.
- Headless render that worked, about 10 s per CR2:

  ```
  darktable-cli IN.CR2 IN.CR2.xmp OUT.jpg --width 2048 --height 2048 --hq true --icc-type SRGB \
    --core --configdir <tmp> --library :memory: --conf plugins/imageio/format/jpeg/quality=90
  ```

  The result matched the GUI export visually (sRGB, edits and crop applied; 2047x2048 vs the GUI's 2048x2048).
- XMP history entries carry `darktable:operation`, `modversion`, `enabled`, `multi_name`, `multi_priority`,
  and `params`. `params` is the module's packed C params struct, either as lowercase hex or as `gz<NN>` followed
  by base64 of zlib-compressed bytes. `darktable:history_end` marks the active top of the stack.
- Proven edit: exposure v7 params are `mode:int32, black:float, exposure:float, deflicker_percentile:float,
  deflicker_target_level:float, compensate_exposure_bias:int32, ...`. Changing the exposure float in a copied
  XMP from 1.97 to 0.97 and rendering with darktable-cli produced an image one stop darker.
- Existing MCP servers were assessed and rejected for v1: the official `darktable-mcp` is master-only and needs
  `USE_MCP`; `w1ne/darktable-mcp` needs a patched fork for module edits; `Caleb68864/darktable-mcp` is
  Windows/DBus only.

## Approach

Module params layouts are generated from darktable's own source rather than decoded by hand. Every iop module
declares `typedef struct dt_iop_<name>_params_t` in `src/iop/<name>.c`, annotates fields with
`$MIN/$MAX/$DEFAULT/$DESCRIPTION` comments, and declares its version with `DT_MODULE_INTROSPECTION(N, ...)`.
A generator turns these into JSON schemas; one generic codec handles every module with a schema.

A module counts as editable only after every real params blob for it in Joel's sidecars decodes and re-encodes
byte-for-byte (the corpus round-trip). This grounds correctness in real darktable output, not in the parser
agreeing with itself.

## Project layout

`~/Desktop/darktable-kit`, local git repo (no remote). Python 3.12, uv, pytest, hatchling, matching
`~/Desktop/digikam-people`. Console script: `dtk = "dtk.cli:main"`.

| Unit | Responsibility | Depends on |
|---|---|---|
| `schemagen/` | Offline generator: darktable source at a tag -> `schemas/<dt-version>/<module>.v<N>.json`. Output is committed; not used at runtime. | darktable checkout |
| `dtk/codec.py` | Pure: params blob (hex or gz) <-> dict, given a schema. C alignment and padding. | schemas |
| `dtk/xmp.py` | Pure: parse a sidecar's history stack; produce new sidecar text with one appended entry. No file I/O beyond reading. | codec |
| `dtk/library.py` | Read-only queries on a temp copy of `library.db`. | sqlite3 |
| `dtk/render.py` | darktable-cli wrapper used by preview and export. | darktable.app |
| `dtk/presets.py` | Named export presets from `presets.toml`. | - |
| `dtk/writer.py` | The only code that writes a real XMP. | xmp |
| `dtk/cli.py` | Commands: `find`, `show`, `modules`, `export`, `edit`, `apply`. | all |

Modules over 200 lines get split before they grow further.

## Schema generation

- Source: shallow clone of `darktable-org/darktable` at tag `release-5.6.1` in
  `~/git/github/darktable-org/darktable`.
- Parser: a purpose-built tokenizer for the subset darktable uses, not pycparser (which needs preprocessed C).
  It reads the params typedef plus the enums and nested struct typedefs it references, from the module file and
  from shared headers under `src/` (for example `src/common/` and `src/iop/`).
- Schema per module and version: ordered fields with `name`, `ctype`, `array_len` (or null), nested `fields` for
  structs, `enum` (name -> value) for enums, and `min`, `max`, `default`, `description` when annotated.
- Any unrecognised type marks the module `unsupported` with the reason recorded in the schema file. The
  generator never guesses a size.
- An index file `schemas/<dt-version>/index.json` lists every module with its version and status.

## Codec

- Natural C alignment: `float`, `int`, `int32_t`, `uint32_t`, `gboolean`, enums = 4 bytes; `double`, `int64_t`,
  `uint64_t` = 8; `int16_t`, `uint16_t` = 2; `char`, `gchar`, `uint8_t`, `int8_t` = 1. A struct aligns to its
  largest member and is padded to a multiple of that alignment. Little-endian.
- Decode refuses when the computed struct size differs from the blob length.
- Padding bytes are preserved from the original blob on re-encode, so round-trips are exact.
- Encoding on write keeps the original entry's format (hex, or gz with the same level).
- An entry whose `modversion` differs from the schema version is read-only, with the message: open the image in
  darktable once to upgrade the module, then retry.

## Commands

- `dtk find [--roll TEXT] [--rating N] [--tag TEXT] [--edited] [--since DATE]` - list images (id, path, rating,
  edited flag) from a copy of `library.db`.
- `dtk show <image>` - the decoded history stack, marking entries above `history_end` as undone.
- `dtk modules` - each module: schema status and corpus round-trip status (editable / read-only / unsupported).
- `dtk export <image...> --preset NAME [--out DIR]` - render with a preset. Default out dir follows the preset.
- `dtk edit <image> --set module.field=value [...] [--instance NAME]` - preview only (see Edit flow).
- `dtk apply <pending-id>` - write a previewed edit to the real XMP.

`<image>` is a file path or a library id from `dtk find`.

Initial preset `messenger`: 2048x2048 bounding box, JPEG quality 90, sRGB, perceptual intent, high-quality
resampling, no upscaling.

## Edit flow

`dtk edit`:

1. Resolve the image and read its real XMP (read-only).
2. Select the topmost enabled instance of the module at or below `history_end`, or the one named by `--instance`
   (matched against `multi_name`). Refuse if the module is not in the stack.
3. Decode, apply `--set` values, validate type, `min`/`max`, and enum names.
4. Build new sidecar text: drop entries above `history_end` (printing a warning that undone steps are discarded,
   as darktable does), append the new entry with the next `num` and the same `multi_priority`/`multi_name`, and
   set `history_end` to the new length.
5. Write that text to a scratch XMP and render a 1024 px before/after side-by-side JPEG.
6. Store `~/.local/state/dtk/pending/<id>.json` with the image path, the original XMP's SHA-256, and the new
   sidecar text. Print the id, the field diff, and the preview path.

`dtk apply <id>` calls `writer.write_xmp`, which:

1. refuses while a process named exactly `darktable` is running,
2. refuses if the XMP's current SHA-256 differs from the pending record (stale),
3. copies the current XMP to `~/.local/state/dtk/backups/<name>.<timestamp-with-microseconds>.xmp`,
4. writes a temp file in the same directory and renames it over the XMP,
5. re-reads and verifies the decoded history equals the planned history,
6. marks the pending record applied.

## Render and export safety

- Every darktable-cli run uses a temp directory holding a symlink to the raw and a copy of the XMP, a temp
  `--configdir`, `--library :memory:`, and `--conf write_sidecar_files=never`. Real sidecars are never passed.
- A render succeeds only if the output file exists, fits within the requested width and height, and carries an sRGB
  profile when the preset asks for one. Exit code alone is not trusted. On failure, print the tail of stderr.

## Errors

Every refusal prints one sentence naming the reason and the fix, and exits non-zero. No command writes partially.

## Testing

- Unit (default `pytest`): codec on synthetic schemas (padding, arrays, nested structs, enums, size mismatch);
  schemagen on C snippets; xmp parse, append, and truncate on fixture sidecars; writer guards with an injected
  process check (darktable running, stale SHA, backup created, atomic rename, verify).
- Corpus (`pytest -m corpus`, opt-in): every params blob in the real sidecars round-trips byte-for-byte. This
  produces the editable list behind `dtk modules`. Reads real files, writes nothing.
- Render (`pytest -m darktable`, opt-in): a +1 EV edit renders measurably brighter by mean luminance; an export
  leaves the real XMP's SHA-256 unchanged; a messenger export is sRGB, 2048 px on the long edge, quality 90.
- Fixtures are copies of real sidecars with GPS and personal metadata removed. Tests never touch the real
  library or real sidecars.
- Manual, once with Joel: `dtk apply` on a real photo, open darktable, confirm it offers to reload the XMP, the
  new step appears in history, and undo works. Record the outcome in this spec.

## Risks

- darktable upgrades bump module versions. Mitigation: schemas are per darktable version; mismatched
  `modversion` is read-only; regenerate schemas after upgrading.
- Some params structs use layouts the parser cannot model (unions, pointers, flexible arrays). Mitigation: marked
  unsupported, never guessed; the corpus test is the gate for editability.
- darktable might not pick up an XMP changed while its library entry is newer. Mitigation: the manual check above
  settles it before relying on `apply`.
