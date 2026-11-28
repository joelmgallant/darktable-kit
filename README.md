# darktable-kit

`dtk` works with darktable 5.6.1 from the terminal.

    uv sync
    uv run dtk find --edited
    uv run dtk show 66
    uv run dtk export 66 67 --preset messenger
    uv run dtk edit 66 --set exposure.exposure+=0.5 --set colorbalancergb.saturation_global=0.15
    uv run dtk apply <id>          # darktable must be closed
    uv run dtk modules             # what can be edited

`edit` writes nothing to your sidecars; it renders a before/after into `~/.local/state/dtk/previews/`.
`apply` writes the sidecar after backing it up. When darktable next opens it should offer to reload the
changed sidecar; the edit shows as a new step in the history panel and can be undone there.

Values: `=` sets, `+=`/`-=` adjust. Arrays and nested fields use dots: `basecurve.basecurve.0.3.x=0.5`.
Enums take member names (`exposure.mode=EXPOSURE_MODE_DEFLICKER`), booleans take true/false.
