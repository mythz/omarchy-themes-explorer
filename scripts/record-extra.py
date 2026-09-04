#!/usr/bin/env python3
"""Record a tour of the extra (community) themes.

The same film as record-demo.py without the opening: no shortcuts overlay, no
right-click menu being demonstrated, no picker. It starts on the first extra
theme and gives every one of them the pass that script gives its second theme
onwards -- panels cleared for the wallpapers, then the centre and bottom-right
cycling together -- moving on with the next arrow.

    scripts/record-extra.py                  # all of them
    scripts/record-extra.py --themes 3       # only the first three
    scripts/record-extra.py --backgrounds 2  # at most two wallpapers each
    scripts/record-extra.py --no-record      # rehearse it
    scripts/record-extra.py --start vesper   # resume from there to the end

Extra themes are not installed, so their wallpapers come off GitHub rather than
off disk. Two things follow: the server's thumbnail cache is warmed before the
camera rolls (--no-prewarm to skip), and each wallpaper change waits for the
picture to actually arrive before the beat is counted.

Needs chromedriver (`pacman -S chromedriver`); everything else ships with
Omarchy.
"""

import argparse
import concurrent.futures
import importlib.util
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# record-demo.py owns the compositor helpers, the recorder, the driver and the
# choreography itself. Reuse them rather than keeping a second copy in step.
_spec = importlib.util.spec_from_file_location("demo", REPO / "scripts/record-demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

# A different pair from the tour's, so both can be rehearsed at once.
PORT = 8798
CHROMEDRIVER_PORT = 9598

# There are 115 extra themes and 614 wallpapers between them -- one theme has
# 29. Uncapped, the wallpapers alone would outlast everything else in the film
# several times over, and the ones past the first few say nothing new about the
# theme's colours.
MAX_BACKGROUNDS = 4

# How long a wallpaper gets to arrive before the film moves on without it. The
# thumbnail is local once the cache is warm and lands immediately; this is the
# full-size original coming from GitHub.
BACKGROUND_WAIT = 6.0


def extra_list():
    """The extra themes the app will show, in the order this film walks them.

    Read straight out of the server's own code rather than over HTTP, so the
    opening clip can find out where the tour starts without standing a server
    up. It is the same answer /api/themes gives: extra-themes.json minus
    anything already installed here.
    """
    spec = importlib.util.spec_from_file_location("server", REPO / "app/server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    installed = {t["slug"] for t in server.discover_themes()}
    return server.extra_themes(installed)


def opening_theme(start=""):
    """The slug this film opens on -- what an opening clip should end on."""
    themes = extra_list()
    if not themes:
        raise SystemExit(
            "no extra themes -- extra-themes.json is missing or empty.\n"
            "Build it with scripts/build-extra-themes.py."
        )
    if not start:
        return themes[0]["slug"]
    if not any(t["slug"] == start for t in themes):
        raise SystemExit("no extra theme with slug %r" % start)
    return start


def wallpaper_source(driver):
    return driver.js(
        "return getComputedStyle(document.getElementById('wallpaper')).backgroundImage;"
    ) or ""


def wait_for_wallpaper(driver, timeout):
    """Hold until the real picture is on screen, or the wait runs out.

    The app paints the cached thumbnail first and the original over it, so
    'https' in the computed background is the original having landed. A
    thumbnail on its own is worth waiting past but not worth failing over: at
    1600px it is honest about the theme, just softer.
    """
    deadline = time.time() + timeout
    thumbnail_at = None
    while time.time() < deadline:
        source = wallpaper_source(driver)
        if "https" in source:
            return True
        if "api/extra-background" in source:
            # Something is on screen. Give the original a moment more, but do
            # not spend the whole timeout on a download that may be minutes.
            thumbnail_at = thumbnail_at or time.time()
            if time.time() - thumbnail_at > timeout / 3:
                return True
        time.sleep(0.2)
    return False


def prewarm(url, themes, log, workers=4):
    """Build the thumbnails the film is about to ask for.

    The server makes each one by downloading the original and re-encoding it,
    which is seconds of blank wallpaper the first time. Doing it before the
    camera rolls costs the same seconds off camera.
    """
    wanted = [(t["slug"], index)
              for t in themes
              for index in range(t["backgrounds"])]
    done = 0
    misses = 0

    def fetch(job):
        slug, index = job
        target = "%sapi/extra-background?theme=%s&index=%d" % (url, slug, index)
        try:
            with urllib.request.urlopen(target, timeout=120) as response:
                response.read()
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for ok in pool.map(fetch, wanted):
            done += 1
            misses += 0 if ok else 1
            if done % 25 == 0 or done == len(wanted):
                log("warming thumbnails: %d/%d%s"
                    % (done, len(wanted), " (%d unavailable)" % misses if misses else ""))


def run(driver, beat, themes, log, background_wait):
    stage = demo.Stage(driver, beat)

    def settle():
        wait_for_wallpaper(driver, background_wait)

    for number, theme in enumerate(themes, 1):
        log("theme %d/%d: %s" % (number, len(themes), theme["name"]))

        # The first theme is already on screen -- the app was opened on it, so
        # the film's first frame is a theme rather than an arrow being pressed.
        if number > 1:
            driver.hover_click("#next", demo.HOVER_DWELL / 3)
            settle()
            stage.pause()

        stage.theme_pass(theme["backgrounds"], settle=settle)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-record", action="store_true",
                        help="run the tour without recording it")
    parser.add_argument("--themes", type=int, default=0,
                        help="stop after this many themes")
    parser.add_argument("--start", default="",
                        help="slug of the theme to begin on; runs to the end of the list")
    parser.add_argument("--backgrounds", type=int, default=MAX_BACKGROUNDS,
                        help="most wallpapers to show per theme (default %d)" % MAX_BACKGROUNDS)
    parser.add_argument("--pause", type=float, default=demo.SCENE_PAUSE,
                        help="seconds to hold each change (default %.1f)" % demo.SCENE_PAUSE)
    parser.add_argument("--background-wait", type=float, default=BACKGROUND_WAIT,
                        help="seconds a wallpaper gets to download (default %.1f)" % BACKGROUND_WAIT)
    parser.add_argument("--no-prewarm", action="store_true",
                        help="do not warm the thumbnail cache first")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--workspace", default=demo.WORKSPACE)
    args = parser.parse_args()

    if not shutil.which("chromedriver"):
        raise SystemExit("chromedriver is not installed: pacman -S chromedriver")

    def log(message):
        print("  " + message, flush=True)

    server = subprocess.Popen(
        [sys.executable, str(REPO / "app/server.py"), str(args.port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = "http://127.0.0.1:%d/" % args.port
    for _ in range(40):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(url + "api/themes", timeout=5)
            break
        except urllib.error.URLError:
            continue
    else:
        server.terminate()
        raise SystemExit("the preview server did not start on port %d" % args.port)

    extra = json.loads(urllib.request.urlopen(url + "api/themes").read()).get("extra", [])
    if not extra:
        server.terminate()
        raise SystemExit(
            "no extra themes -- extra-themes.json is missing or empty.\n"
            "Build it with scripts/build-extra-themes.py."
        )

    if args.start:
        at = next((i for i, t in enumerate(extra) if t["slug"] == args.start), None)
        if at is None:
            server.terminate()
            raise SystemExit("no extra theme with slug %r" % args.start)
        # Runs to the end of the list rather than wrapping back to the top.
        # --start is how a stopped run is resumed, and a resume that carries on
        # into the themes the first film already covered is worse than useless:
        # it is minutes of footage that has to be found and cut back out.
        extra = extra[at:]

    order = [{"name": t["name"], "slug": t["slug"],
              "backgrounds": min(len(t["backgrounds"]), max(1, args.backgrounds))}
             for t in extra]
    if args.themes:
        order = order[: args.themes]

    # Every beat the choreography spends: the arrow, the clear, the wallpapers,
    # the restore, and the three paired panel swaps.
    beats = sum(t["backgrounds"] + 5 for t in order) - 1
    print("Recording %d extra themes at %.1fs a beat on workspace %s -- about %d:%02d"
          % (len(order), args.pause, args.workspace,
             int(beats * args.pause) // 60, int(beats * args.pause) % 60))

    if not args.no_prewarm:
        prewarm(url, order, log)

    origin = demo.active_workspace()
    if not demo.go_to_workspace(args.workspace):
        server.terminate()
        raise SystemExit(
            "could not switch to workspace %s -- the recording would have been of\n"
            "whatever was already on screen. Check `hyprctl activeworkspace`."
            % args.workspace
        )
    log("on workspace %s (was %s)" % (args.workspace, origin))
    time.sleep(0.6)

    before = {c["address"] for c in demo.clients()}
    profile = "/tmp/themes-explorer-record-extra-profile"
    shutil.rmtree(profile, ignore_errors=True)
    # Opening on an extra theme is what puts the app in the extra list, which
    # is what the next arrow then walks.
    query = "&".join(["theme=" + order[0]["slug"]]
                     + ["%s=%s" % (slot, app)
                        for slot, app in demo.INITIAL_LAYOUT.items()])
    driver = demo.Driver(CHROMEDRIVER_PORT, url + "?" + query, profile)
    driver.on_move = demo.move_cursor

    window = demo.wait_for_window(before)
    if window:
        on = next((c["workspace"]["name"] for c in demo.clients()
                   if c["address"] == window), "")
        if str(on) != args.workspace:
            log("window opened on %s, moving it" % on)
            demo.hypr('hl.dsp.window.move({ workspace = "%s", window = "address:%s" })'
                      % (args.workspace, window),
                      "movetoworkspace", "%s,address:%s" % (args.workspace, window))
            demo.go_to_workspace(args.workspace)
        demo.hypr('hl.dsp.window.fullscreen({ mode = "fullscreen" })', "fullscreen", "0")

    time.sleep(demo.SETTLE)
    # The opening theme's wallpaper is a download like any other, and the film
    # should not open on the blank that precedes it.
    wait_for_wallpaper(driver, args.background_wait)

    recording = False
    if not args.no_record:
        recording = demo.start_recording()
        if not recording:
            log("recorder did not start -- carrying on without it")
        time.sleep(1.0)

    try:
        run(driver, args.pause, order, log, args.background_wait)
    except KeyboardInterrupt:
        log("interrupted")
    except Exception as failure:
        # Chrome can go away mid-run -- a crash, or someone closing the window.
        # Everything filmed up to that point is still worth having, so say what
        # happened and carry on to the report rather than dying on a traceback
        # that buries where the recording went.
        log("stopped early: %s" % failure)
    finally:
        driver.quit()
        if recording:
            demo.stop_recording()
        server.terminate()
        if origin and origin != args.workspace:
            demo.go_to_workspace(origin)

    if recording:
        newest = demo.newest_recording()
        print("\nSaved: %s" % (newest or "(recording not found)"))
        if newest:
            print("       %.1f MB" % (newest.stat().st_size / (1024 * 1024)))


if __name__ == "__main__":
    main()
