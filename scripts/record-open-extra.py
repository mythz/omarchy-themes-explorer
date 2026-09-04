#!/usr/bin/env python3
"""Record the opening for the extra-themes tour.

The same beat record-open.py films -- an empty workspace, the pointer going up
to the paintbrush in the bar, and the window opening full screen -- but ending
on the state record-extra.py starts from: the first extra theme, its first
wallpaper, and the tour's layout. Stitch it in front of that film and the two
clips join without a jump.

    scripts/record-open-extra.py                 # about 11 seconds
    scripts/record-open-extra.py --start nordic  # if the tour starts elsewhere
    scripts/record-open-extra.py --no-record     # rehearse

Which theme that is comes from record-extra.py, so the two cannot disagree
about where the tour begins.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


opening = _load("open_clip", "record-open.py")
extra = _load("extra", "record-extra.py")


def main():
    parser = opening.arguments(__doc__.split("\n\n")[0])
    parser.add_argument("--start", default="",
                        help="slug of the extra theme the tour begins on")
    args = parser.parse_args()

    theme = extra.opening_theme(args.start)
    print("  opening on %s" % theme)
    opening.open_app(theme, args)


if __name__ == "__main__":
    main()
