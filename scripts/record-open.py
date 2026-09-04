#!/usr/bin/env python3
"""Record just the opening: the paintbrush in the bar, and the app arriving.

A short clip meant to be stitched in front of record-demo.py's tour -- an empty
workspace, the pointer travelling up to Themes Explorer's widget in the bar, and
the window opening full screen.

    scripts/record-open.py                 # record it
    scripts/record-open.py --no-record     # rehearse
    scripts/record-open.py --brush 2889,16 # if the bar's contents moved

The one thing it does not do is press the widget. Clicking into Quickshell would
need a synthetic pointer button, and Hyprland's Lua dispatcher table has
hl.dsp.cursor.move but nothing that clicks -- so the cursor travels to the
paintbrush, rests there long enough for the widget's own hover state to come up,
and the script launches the app itself. On camera it is the same beat.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The tour script owns the compositor and recorder helpers; reuse them rather
# than keeping a second copy in step.
_spec = importlib.util.spec_from_file_location("demo", REPO / "scripts/record-demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

WORKSPACE = "5"

# Themes Explorer's widget in the bar, in Hyprland's logical pixels. Measured
# off a screenshot: it is the third icon in the right-hand cluster, at device
# (3611, 20) on a 3840px monitor at scale 1.25. Re-measure with `grim` if the
# tray gains or loses anything to the left of it.
PAINTBRUSH = (2889, 16)

# Where the pointer starts, so it has somewhere to travel from.
START = (1500, 900)

LAUNCHERS = [
    Path.home() / ".config/omarchy/plugins/mythz.themes-explorer/bin/omarchy-themes-explorer",
    REPO / "bin/omarchy-themes-explorer",
]

APPROACH = 1.6      # seconds the pointer takes to reach the widget
DWELL = 1.4         # resting on it, which is when the hover state shows
HOLD = 5.0          # how long the opened app stays on screen
TAIL = 1.0          # a beat of stillness before the recorder stops


def launcher():
    for path in LAUNCHERS:
        if path.is_file():
            return path
    return None


def glide(start, end, seconds):
    """Walk the cursor across, slowly enough to read as a hand moving."""
    steps = max(8, int(seconds * 30))
    demo.move_cursor(start[0], start[1], glide=False)
    for step in range(1, steps + 1):
        fraction = step / steps
        # Ease out, so it arrives rather than stops.
        eased = 1 - (1 - fraction) ** 3
        demo.move_cursor(
            round(start[0] + (end[0] - start[0]) * eased),
            round(start[1] + (end[1] - start[1]) * eased),
            glide=False,
        )
        time.sleep(seconds / steps)


def arguments(description):
    """The options every opening clip takes.

    Shared with record-open-extra.py, which films the same beat and differs
    only in which theme the window opens on.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--workspace", default=WORKSPACE)
    parser.add_argument("--brush", default="%d,%d" % PAINTBRUSH,
                        help="the widget's position as x,y in logical pixels")
    parser.add_argument("--hold", type=float, default=HOLD,
                        help="seconds to hold on the opened app (default 5)")
    return parser


def open_app(theme, args):
    """Film the pointer reaching the widget and the app opening on `theme`."""
    try:
        brush = tuple(int(part) for part in args.brush.split(","))
    except ValueError:
        raise SystemExit("--brush wants x,y")

    run = launcher()
    if not run:
        raise SystemExit("could not find the Themes Explorer launcher")

    # Open on exactly what the tour opens on, so the two clips join without a
    # jump: the first theme, its first background, and the same layout. The
    # launcher passes this through to the page as query parameters.
    environment = dict(os.environ)
    environment["OMARCHY_THEMES_EXPLORER_QUERY"] = "&".join(
        ["theme=" + theme]
        + ["%s=%s" % (slot, app) for slot, app in demo.INITIAL_LAYOUT.items()]
    )

    # Close it first, so what is filmed is a window opening rather than a
    # scratchpad being toggled back into view. `--stop` shuts the server down
    # but leaves the window, so the window is closed by hand as well -- and
    # without that the clip shows the right thing while the script waits out
    # its timeout for a window that already existed.
    subprocess.run([str(run), "--stop"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    for client in demo.clients():
        if "themes-explorer" in (client.get("class") or ""):
            demo.hypr('hl.dsp.window.close({ window = "address:%s" })' % client["address"],
                      "closewindow", "address:%s" % client["address"])
    time.sleep(1.2)

    origin = demo.active_workspace()
    if not demo.go_to_workspace(args.workspace):
        raise SystemExit("could not switch to workspace %s" % args.workspace)
    demo.move_cursor(START[0], START[1], glide=False)
    time.sleep(1.2)

    recording = False
    if not args.no_record:
        recording = demo.start_recording()
        if not recording:
            print("  recorder did not start -- carrying on without it")
        time.sleep(1.2)

    print("  pointer to the paintbrush")
    glide(START, brush, APPROACH)
    time.sleep(DWELL)

    print("  opening the app")
    before = {c["address"] for c in demo.clients()}
    subprocess.Popen(["setsid", str(run)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True,
                     env=environment)
    window = demo.wait_for_window(before, timeout=25)
    if not window:
        print("  the window never appeared")

    time.sleep(args.hold)

    if recording:
        time.sleep(TAIL)
        demo.stop_recording()
        newest = demo.newest_recording()
        print("\nSaved: %s" % (newest or "(recording not found)"))
        if newest:
            print("       %.1f MB" % (newest.stat().st_size / (1024 * 1024)))

    if origin and origin != args.workspace:
        demo.go_to_workspace(origin)


def main():
    open_app(demo.FIRST_THEME, arguments(__doc__.split("\n\n")[0]).parse_args())


if __name__ == "__main__":
    main()
