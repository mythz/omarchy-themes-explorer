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
import pathlib
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


CENTER_APPS = ["nvim", "vscode", "omenu", "none"]
CORNER_APPS = ["nautilus", "lazyvim", "none", "ls"]
CENTER_SLOT = "center"
CORNER_SLOT = "right-bottom"

# Emptied together before the backgrounds, so only the two left-hand panels are
# left and most of the wallpaper is visible while it cycles.
CLEARED_SLOTS = ["center", "right-top", "right-bottom"]
RESTORE_AFTER_BACKGROUNDS = {"right-top": "fastfetch"}

# The menu is demonstrated once, slowly, at the top of the film. Every swap
# after that happens without it: the audience has seen how, and thirty-odd
# themes of the same menu opening is thirty-odd themes of nothing new.
SCENE_PAUSE = 3.0

# Where the right click lands, as a fraction of the panel -- near its top-right
# corner rather than the middle, so the menu opens beside the panel's content
# instead of over it.
MENU_SPOT = (0.86, 0.18)

# Long enough for Chrome's fullscreen toast to come and go before the recorder
# starts.
SETTLE = 4.5

FIRST_THEME = "catppuccin"   # where the tour starts, and the intro's subject

# The layout the film opens on. The app takes these as query parameters, so the
# first frame is already right -- nothing rearranges itself on camera. The
# middle is empty from the start, so the opening run of backgrounds plays
# against as much wallpaper as possible.
INITIAL_LAYOUT = {
    "left-top": "fastfetch",
    "left-bottom": "ls",
    "center": "none",
    "right-top": "logo",
    "right-bottom": "btop",
}


# --- webdriver ----------------------------------------------------------


class Driver:
    """Just enough of the WebDriver protocol, so there is no dependency."""

    def __init__(self, port, url, profile):
        self.base = "http://127.0.0.1:%d" % port
        # Kept rather than discarded: when this end of things goes wrong it is
        # the only thing that says why.
        self.log_path = "/tmp/record-demo-chromedriver.log"
        self.log = open(self.log_path, "w")
        self.process = subprocess.Popen(
            ["chromedriver", "--port=%d" % port],
            stdout=self.log, stderr=subprocess.STDOUT,
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

        try:
            self.session = self.start_session(url, profile)
        except Exception as error:
            self.log.flush()
            raise SystemExit(
                "could not open the browser: %s\nchromedriver said:\n%s"
                % (error, pathlib.Path(self.log_path).read_text()[-800:])
            )

    def start_session(self, url, profile):
        return self.call("POST", "/session", {
            "capabilities": {"alwaysMatch": {"goog:chromeOptions": {
                # Without this Chrome wears a yellow "controlled by automated
                # test software" bar across the top of every frame.
                "excludeSwitches": ["enable-automation"],
                "args": [
                "--app=" + url,
                "--user-data-dir=" + profile,
                "--no-first-run",
                "--disable-features=Translate,MediaRouter",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-infobars",
                "--disable-blink-features=AutomationControlled",
            ]}}}
        }, timeout=60)["sessionId"]

    def call(self, method, path, body=None, timeout=120):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())["value"]
        except urllib.error.HTTPError as error:
            # WebDriver puts the reason in the body; without it a failure is a
            # bare "404: Not Found" with nothing saying which call broke.
            detail = ""
            try:
                detail = json.loads(error.read())["value"].get("message", "")
            except Exception:
                pass
            raise RuntimeError("%s %s -> %s %s"
                               % (method, path, error.code, detail[:300])) from None

    def js(self, script, *args):
        return self.call("POST", "/session/%s/execute/sync" % self.session,
                         {"script": script, "args": list(args)})

    def spot(self, selector, fx, fy):
        """A point inside an element, as a fraction of its box."""
        return self.js(
            "const e=document.querySelector(arguments[0]);"
            "if(!e) return null;"
            "const r=e.getBoundingClientRect();"
            "return [Math.round(r.x+r.width*arguments[1]),"
            "        Math.round(r.y+r.height*arguments[2])];",
            selector, fx, fy,
        )

    def click_at(self, x, y, button=0):
        self.pointer([
            {"type": "pointerMove", "duration": 260, "x": x, "y": y},
            {"type": "pause", "duration": 120},
            {"type": "pointerDown", "button": button},
            {"type": "pointerUp", "button": button},
        ])

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


def hypr(lua, *legacy):
    """Dispatch through Hyprland, Lua first.

    Omarchy runs the Lua config provider, where the legacy `dispatch workspace
    5` is a parse error rather than a command -- and one that goes to stderr
    while hyprctl still exits 0, so a call that silently did nothing looks
    exactly like a call that worked. The output is what says which, so it is
    read rather than discarded, and the legacy form is kept for a setup still
    on the .conf parser.
    """
    done = subprocess.run(["hyprctl", "dispatch", lua], capture_output=True, text=True)
    if done.returncode == 0 and "error" not in (done.stdout + done.stderr).lower():
        return True
    if legacy:
        done = subprocess.run(["hyprctl", "dispatch"] + list(legacy),
                              capture_output=True, text=True)
        return done.returncode == 0 and "error" not in (done.stdout + done.stderr).lower()
    return False


def active_workspace():
    done = subprocess.run(["hyprctl", "activeworkspace", "-j"],
                          capture_output=True, text=True)
    try:
        return str(json.loads(done.stdout)["name"])
    except (ValueError, KeyError):
        return ""


def go_to_workspace(name):
    hypr('hl.dsp.focus({ workspace = "%s" })' % name, "workspace", name)
    for _ in range(20):
        if active_workspace() == name:
            return True
        time.sleep(0.1)
    return False


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
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# Never capture_output= around these. The recorder is backgrounded by the
# command and inherits whatever stdout it was given, so a pipe stays open for
# as long as the recording runs -- and subprocess.run waits for that pipe to
# close, not for the command to exit. It blocks until the recording ends, which
# is never, because the thing that would end it is the rest of this script.
def start_recording():
    subprocess.run(["omarchy-capture-screenrecording", "--fullscreen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if recorder_running():
            return True
        time.sleep(0.25)
    return False


def stop_recording():
    subprocess.run(["omarchy-capture-screenrecording", "--stop-recording"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def swap_shown(slot, app):
        """Right click near the panel's corner and pick out of the menu."""
        spot = driver.spot('[data-slot="%s"]' % slot, *MENU_SPOT)
        if not spot:
            return
        driver.click_at(spot[0], spot[1], button=2)
        time.sleep(min(1.2, SCENE_PAUSE / 2))
        driver.click('.menu-item[data-app="%s"]' % app)
        time.sleep(SCENE_PAUSE)

    def swap_quiet(slot, app):
        """The same swap without the menu.

        It still goes through the app's own handlers -- the panel's contextmenu
        listener and the menu item's click -- rather than reaching into its
        state, so what is recorded is what a user would get. The menu is only
        hidden for the instant it would otherwise be on screen, and all of it
        happens inside one evaluation, so no frame ever contains it.
        """
        driver.js(
            "const panel=document.querySelector('[data-slot=\"'+arguments[0]+'\"]');"
            "const menu=document.getElementById('menu');"
            "if(!panel) return;"
            "const box=panel.getBoundingClientRect();"
            "const was=menu.style.visibility;"
            "menu.style.visibility='hidden';"
            "panel.dispatchEvent(new MouseEvent('contextmenu',"
            "  {bubbles:true,clientX:box.x+box.width/2,clientY:box.y+box.height/2}));"
            "const item=document.querySelector('.menu-item[data-app=\"'+arguments[1]+'\"]');"
            "if(item) item.click();"
            "menu.hidden=true;"
            "menu.style.visibility=was;",
            slot, app,
        )
        pause()

    log("intro: shortcuts overlay")
    driver.click("#help")
    time.sleep(SCENE_PAUSE)
    driver.click("#help")
    pause()

    log("intro: four backgrounds")
    for _ in range(4):
        driver.click("#cycleBg")
        pause()

    log("intro: the centre panel, with the menu")
    for app in CENTER_APPS:
        swap_shown(CENTER_SLOT, app)
    swap_shown(CENTER_SLOT, "nvim")

    log("intro: the bottom-right panel, with the menu")
    for app in CORNER_APPS:
        swap_shown(CORNER_SLOT, app)

    for number, theme in enumerate(themes, 1):
        log("theme %d/%d: %s" % (number, len(themes), theme["name"]))
        driver.js(
            "for (const row of document.querySelectorAll('#pickerList .picker-item'))"
            "  if (row.querySelector('.picker-name').textContent === arguments[0])"
            "    { row.click(); return; }",
            theme["name"],
        )
        pause()

        # Clear the right-hand side first, so the backgrounds play against as
        # much wallpaper as the layout can give them.
        for slot in CLEARED_SLOTS:
            swap_quiet(slot, "none")

        for _ in range(max(0, theme["backgrounds"] - 1)):
            driver.click("#cycleBg")
            pause()

        for slot, app in RESTORE_AFTER_BACKGROUNDS.items():
            swap_quiet(slot, app)

        for app in CENTER_APPS:
            swap_quiet(CENTER_SLOT, app)
        swap_quiet(CENTER_SLOT, "nvim")

        for app in CORNER_APPS:
            swap_quiet(CORNER_SLOT, app)


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

    origin = active_workspace()
    if not go_to_workspace(args.workspace):
        server.terminate()
        raise SystemExit(
            "could not switch to workspace %s -- the recording would have been of\n"
            "whatever was already on screen. Check `hyprctl activeworkspace`."
            % args.workspace
        )
    log("on workspace %s (was %s)" % (args.workspace, origin))
    time.sleep(0.6)

    before = {c["address"] for c in clients()}
    profile = "/tmp/themes-explorer-record-profile"
    shutil.rmtree(profile, ignore_errors=True)
    query = "&".join(["theme=" + FIRST_THEME]
                     + ["%s=%s" % (slot, app) for slot, app in INITIAL_LAYOUT.items()])
    driver = Driver(CHROMEDRIVER_PORT, url + "?" + query, profile)

    window = wait_for_window(before)
    if window:
        # A window that opened somewhere else would leave the recording on an
        # empty workspace, so put it where the camera is pointed.
        on = next((c["workspace"]["name"] for c in clients()
                   if c["address"] == window), "")
        if str(on) != args.workspace:
            log("window opened on %s, moving it" % on)
            hypr('hl.dsp.window.move({ workspace = "%s", window = "address:%s" })'
                 % (args.workspace, window),
                 "movetoworkspace", "%s,address:%s" % (args.workspace, window))
            go_to_workspace(args.workspace)
        # Fullscreen, so the frame is the simulated desktop and nothing else --
        # no Chrome window inside the recording of a desktop.
        hypr('hl.dsp.window.fullscreen({ mode = "fullscreen" })', "fullscreen", "0")

    # Only now start recording. Chrome puts a "press and hold Esc to exit full
    # screen" toast over the top for the first few seconds, and the film should
    # not open on it -- nor on an empty workspace waiting for a window.
    time.sleep(SETTLE)
    recording = False
    if not args.no_record:
        recording = start_recording()
        if not recording:
            log("recorder did not start -- carrying on without it")
        time.sleep(1.0)

    try:
        run(driver, args.pause, order, log)
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        driver.quit()
        if recording:
            stop_recording()
        server.terminate()
        if origin and origin != args.workspace:
            go_to_workspace(origin)

    if recording:
        newest = newest_recording()
        print("\nSaved: %s" % (newest or "(recording not found)"))
        if newest:
            size = newest.stat().st_size / (1024 * 1024)
            print("       %.1f MB" % size)


if __name__ == "__main__":
    main()
