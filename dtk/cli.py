"""dtk command-line entry point."""
from __future__ import annotations

import argparse
import sys

from dtk import commands
from dtk.blob import BlobError
from dtk.codec import CodecError
from dtk.images import ImageNotFound
from dtk.render import RenderError
from dtk.schemas import SchemaMissing
from dtk.values import EditRefused
from dtk.writer import WriteRefused
from dtk.xmp import XmpError

REFUSALS = (EditRefused, WriteRefused, RenderError, ImageNotFound, XmpError, CodecError, BlobError,
            SchemaMissing, LookupError, ValueError)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dtk", description="Query, export and edit darktable photos.")
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find", help="list images in the darktable library")
    find.add_argument("--roll")
    find.add_argument("--rating", type=int)
    find.add_argument("--tag")
    find.add_argument("--edited", action="store_true")
    find.add_argument("--since", metavar="YYYY-MM-DD")
    find.set_defaults(handler=commands.cmd_find)

    show = sub.add_parser("show", help="decoded history stack of one image")
    show.add_argument("image", help="raw path, sidecar path, or library id")
    show.set_defaults(handler=commands.cmd_show)

    modules = sub.add_parser("modules", help="which modules dtk can edit")
    modules.add_argument("--all", action="store_true", help="include unsupported modules")
    modules.set_defaults(handler=commands.cmd_modules)

    export = sub.add_parser("export", help="render images with a preset")
    export.add_argument("images", nargs="+")
    export.add_argument("--preset", required=True)
    export.add_argument("--out")
    export.set_defaults(handler=commands.cmd_export)

    edit = sub.add_parser("edit", help="preview an edit; writes nothing to your sidecars")
    edit.add_argument("image")
    edit.add_argument("--set", action="append", required=True, metavar="MODULE.FIELD=VALUE")
    edit.add_argument("--instance", help="multi_name of the module instance to edit")
    edit.add_argument("--no-preview", action="store_true", help="skip rendering the before/after")
    edit.set_defaults(handler=commands.cmd_edit)

    apply = sub.add_parser("apply", help="write a previewed edit to the real sidecar")
    apply.add_argument("id")
    apply.set_defaults(handler=commands.cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except REFUSALS as exc:
        message = " ".join(str(exc).split())
        print(f"dtk: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
