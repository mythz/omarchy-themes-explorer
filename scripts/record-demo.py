#!/usr/bin/env python3
"""Record a scripted tour of Themes Explorer.

Opens the preview full screen on an empty workspace, records the monitor with
Omarchy's own screen recorder, and drives the page through a fixed
choreography: the shortcuts overlay, the backgrounds, the two swappable panels,
and then every installed theme in turn.

The page is driven through WebDriver rather than by synthesising clicks into
the compositor, so every step is a real click at real coordinates with the
cursor visible where it lands -- and it is deterministic, which matters when a
run takes minutes and you want to change one beat and go again.

    scripts/record-demo.py                  # the full tour
    scripts/record-demo.py --no-record      # rehearse it without recording
    scripts/record-demo.py --themes 3       # only the first three themes
    scripts/record-demo.py --pause 0.6      # quicker

Needs chromedriver (`pacman -S chromedriver`); everything else ships with
Omarchy.
"""

import argparse
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# --- what the tour does -------------------------------------------------

WORKSPACE = "5"          # the empty workspace to perform on
PORT = 8799              # the preview server's port for this run
CHROMEDRIVER_PORT = 9599

# Where the bar's paintbrush sits, in Hyprland's logical pixels. The cursor is
# parked there before the window opens, so the recording reads as if the widget
# had been clicked -- synthesising a real click into the bar would need ydotool
# and a uinput device, which Omarchy does not ship.
# Measured off a screenshot of the bar: the widget's ink sits at device
# (3574, 15) on a 3840px monitor at scale 1.25. It moves whenever the tray
# does, so re-measure with `grim` if the cursor lands somewhere odd.
PAINTBRUSH_XY = (2859, 15)

CENTER_APPS = ["nvim", "vscode", "omenu", "none"]
CORNER_APPS = ["nautilus", "lazyvim", "none", "ls"]
CORNER_SLOT = "right-bottom"

FIRST_THEME = "catppuccin"   # where the tour starts, and the intro's subject


# --- webdriver ----------------------------------------------------------


class Driver:
    """Just enough of the WebDriver protocol, so there is no dependency."""

    def __init__(self, port, url, profile):
        self.base = "http://127.0.0.1:%d" % port
        self.process = subprocess.Popen(
            ["chromedriver", "--port=%d" % port],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(40):
            time.sleep(0.25)
            try:
                self.call("GET", "/status")
                break
            except urllib.error.URLError:
                continue
        else:
            raise SystemExit("chromedriver did not start")

        self.session = self.call("POST", "/session", {
            "capabilities": {"alwaysMatch": {"goog:chromeOptions": {"args": [
                "--app=" + url,
                "--user-data-dir=" + profile,
                "--no-first-run",
                "--disable-features=Translate,MediaRouter",
                "--autoplay-policy=no-user-gesture-required",
            ]}}}
        })["sessionId"]

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())["value"]

    def js(self, script, *args):
        return self.call("POST", "/session/%s/execute/sync" % self.session,
                         {"script": script, "args": list(args)})

    def centre(self, selector):
        return self.js(
            "const e=document.querySelector(arguments[0]);"
            "if(!e) return null;"
            "const r=e.getBoundingClientRect();"
            "return [Math.round(r.x+r.width/2), Math.round(r.y+r.height/2)];",
            selector,
        )

    def pointer(self, actions):
        self.call("POST", "/session/%s/actions" % self.session, {"actions": [
            {"type": "pointer", "id": "mouse",
             "parameters": {"pointerType": "mouse"}, "actions": actions}
        ]})

    def click(self, selector, button=0):
        spot = self.centre(selector)
        if not spot:
            return False
        self.pointer([
            {"type": "pointerMove", "duration": 220, "x": spot[0], "y": spot[1]},
            {"type": "pause", "duration": 90},
            {"type": "pointerDown", "button": button},
            {"type": "pointerUp", "button": button},
        ])
        return True

    def quit(self):
        try:
            self.call("DELETE", "/session/" + self.session)
        except Exception:
            pass
        self.process.terminate()


# --- the compositor -----------------------------------------------------


def hypr(*args):
    subprocess.run(["hyprctl"] + list(args), capture_output=True)


def clients():
    done = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return []


def wait_for_window(before, timeout=25):
    """The address of the window that appeared since `before`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for client in clients():
            if client["address"] not in before and client["class"].startswith("chrome"):
                return client["address"]
        time.sleep(0.25)
    return None


# --- the recorder -------------------------------------------------------


def recorder_running():
    return subprocess.run(["pgrep", "-f", "^gpu-screen-recorder"],
                          capture_output=True).returncode == 0


def start_recording():
    subprocess.run(["omarchy-capture-screenrecording", "--fullscreen"],
                   capture_output=True)
    for _ in range(40):
        if recorder_running():
            return True
        time.sleep(0.25)
    return False


def stop_recording():
    subprocess.run(["omarchy-capture-screenrecording", "--stop-recording"],
                   capture_output=True)
    for _ in range(60):
        if not recorder_running():
            return
        time.sleep(0.25)


def newest_recording():
    directory = Path(os.environ.get("OMARCHY_SCREENRECORD_DIR")
                     or os.environ.get("XDG_VIDEOS_DIR")
                     or (Path.home() / "Videos"))
    files = sorted(directory.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


# --- the choreography ---------------------------------------------------


def run(driver, beat, themes, log):
    def pause(times=1):
        time.sleep(beat * times)

    def swap(slot, app):
        """Right click a panel and pick an app out of the menu it opens."""
        if not driver.click('[data-slot="%s"]' % slot, button=2):
            return
        pause(0.5)
        driver.click('.menu-item[data-app="%s"]' % app)
        pause()

    log("intro: shortcuts overlay")
    driver.click("#help")
    pause(2)
    driver.click("#help")
    pause()

    log("intro: four backgrounds")
    for _ in range(4):
        driver.click("#cycleBg")
        pause()

    log("intro: the centre panel")
    for app in CENTER_APPS:
        swap("center", app)
    swap("center", "nvim")

    log("intro: the bottom-right panel")
    for app in CORNER_APPS:
        swap(CORNER_SLOT, app)

    for number, theme in enumerate(themes, 1):
        log("theme %d/%d: %s" % (number, len(themes), theme["name"]))
        driver.js(
            "for (const row of document.querySelectorAll('#pickerList .picker-item'))"
            "  if (row.querySelector('.picker-name').textContent === arguments[0])"
            "    { row.click(); return; }",
            theme["name"],
        )
        pause()

        for _ in range(max(0, theme["backgrounds"] - 1)):
            driver.click("#cycleBg")
            pause()

        for app in CENTER_APPS:
            swap("center", app)
        swap("center", "nvim")

        for app in CORNER_APPS:
            swap(CORNER_SLOT, app)


# --- main ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-record", action="store_true",
                        help="run the tour without recording it")
    parser.add_argument("--themes", type=int, default=0,
                        help="stop after this many themes")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="seconds to hold each change (default 1)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--workspace", default=WORKSPACE)
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

    themes = json.loads(urllib.request.urlopen(url + "api/themes").read())["themes"]
    order = [t for t in themes if t["slug"] == FIRST_THEME]
    order += [t for t in themes if t["slug"] != FIRST_THEME]
    order = [{"name": t["name"], "backgrounds": len(t["backgrounds"])} for t in order]
    if args.themes:
        order = order[: args.themes]

    print("Recording %d themes at %.1fs a beat on workspace %s"
          % (len(order), args.pause, args.workspace))

    hypr("dispatch", "workspace", args.workspace)
    time.sleep(0.6)
    hypr("dispatch", "movecursor", str(PAINTBRUSH_XY[0]), str(PAINTBRUSH_XY[1]))
    time.sleep(0.4)

    recording = False
    if not args.no_record:
        recording = start_recording()
        if not recording:
            log("recorder did not start -- carrying on without it")
        time.sleep(1.2)

    before = {c["address"] for c in clients()}
    profile = "/tmp/themes-explorer-record-profile"
    shutil.rmtree(profile, ignore_errors=True)
    driver = Driver(CHROMEDRIVER_PORT, url + "?theme=" + FIRST_THEME, profile)

    window = wait_for_window(before)
    if window:
        hypr("dispatch", "fullscreen", "0")
    time.sleep(1.5)

    try:
        run(driver, args.pause, order, log)
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        driver.quit()
        if recording:
            stop_recording()
        server.terminate()

    if recording:
        newest = newest_recording()
        print("\nSaved: %s" % (newest or "(recording not found)"))
        if newest:
            size = newest.stat().st_size / (1024 * 1024)
            print("       %.1f MB" % size)


if __name__ == "__main__":
    main()
