#!/usr/bin/env python3
"""Local web server backing Themes Explorer.

Serves the static preview page and a small JSON API over the themes that are
actually installed on this machine, so the page can render each one and hand
"make this the current theme" back to `omarchy theme set`.
"""

import json
import mimetypes
import os
import re
import subprocess
import sys
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
APP_DIR = Path(__file__).resolve().parent
# The launcher ships alongside the app inside the plugin folder, so the
# server never depends on anything having been installed onto PATH.
LAUNCHER = APP_DIR.parent / "bin/omarchy-themes-explorer"
USER_THEMES = HOME / ".config/omarchy/themes"
STOCK_THEMES = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "themes"
USER_BACKGROUNDS = HOME / ".config/omarchy/backgrounds"
CURRENT_NAME = HOME / ".local/state/omarchy/current/theme.name"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


# --- color helpers ------------------------------------------------------


def parse_hex(value):
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})|#?([0-9a-fA-F]{3})", value.strip())
    if not m:
        return None
    h = (m.group(1) or m.group(2)).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


def luminance(rgb):
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def shade(rgb, amount):
    """Positive lightens toward white, negative darkens toward black."""
    target = (255, 255, 255) if amount > 0 else (0, 0, 0)
    return mix(rgb, target, abs(amount))


# --- theme loading ------------------------------------------------------


def read_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def flatten_alacritty(data):
    """Pull an ANSI palette out of an alacritty.toml (legacy v2-era themes)."""
    colors = data.get("colors", {})
    out = {}
    primary = colors.get("primary", {})
    for key, name in (("background", "background"), ("foreground", "foreground")):
        if parse_hex(primary.get(key)):
            out[name] = primary[key]
    cursor = colors.get("cursor", {}).get("cursor")
    if parse_hex(cursor):
        out["accent"] = cursor
    for group, offset in (("normal", 0), ("bright", 8)):
        for i, name in enumerate(ANSI_NAMES):
            value = colors.get(group, {}).get(name)
            if parse_hex(value):
                out["color%d" % (offset + i)] = value
    selection = colors.get("selection", {}).get("background")
    if parse_hex(selection):
        out["selection"] = selection
    return out


def raw_colors(theme_dir):
    colors_toml = theme_dir / "colors.toml"
    if colors_toml.is_file():
        data = read_toml(colors_toml)
        if data:
            return data
    alacritty = theme_dir / "alacritty.toml"
    if alacritty.is_file():
        return flatten_alacritty(read_toml(alacritty))
    return {}


def normalize(raw):
    """Fold both colors.toml dialects (named keys, ANSI colorN) into one palette."""

    def get(*keys):
        for key in keys:
            rgb = parse_hex(raw.get(key))
            if rgb:
                return rgb
        return None

    background = get("background", "color0") or (26, 27, 38)
    foreground = get("foreground", "color7") or (200, 200, 200)
    is_light = str(raw.get("mode", "")).lower() == "light" or (
        "mode" not in raw and luminance(background) > 0.5
    )

    step = 0.10 if not is_light else 0.05
    palette = {
        "background": background,
        "dark_background": get("dark_background") or shade(background, -step),
        "darker_background": get("darker_background") or shade(background, -step * 2),
        "lighter_background": get("lighter_background") or mix(background, foreground, 0.10),
        "foreground": foreground,
        "dark_foreground": get("dark_foreground") or mix(foreground, background, 0.45),
        "light_foreground": get("light_foreground") or foreground,
        "bright_foreground": get("bright_foreground")
        or shade(foreground, 0.25 if not is_light else -0.25),
        "red": get("red", "color1") or (220, 90, 90),
        "green": get("green", "color2") or (140, 190, 110),
        "yellow": get("yellow", "color3") or (220, 180, 100),
        "blue": get("blue", "color4") or (120, 160, 240),
        "magenta": get("magenta", "color5") or (180, 140, 230),
        "cyan": get("cyan", "color6") or (100, 190, 200),
        "black": get("black", "color0") or shade(background, -0.3),
        "white": get("white", "color7") or foreground,
    }
    palette["accent"] = get("accent") or palette["blue"]
    palette["selection"] = get("selection", "selection_background") or mix(
        background, palette["accent"], 0.28
    )
    palette["muted"] = get("muted") or mix(background, foreground, 0.42)
    palette["orange"] = get("orange") or mix(palette["red"], palette["yellow"], 0.45)
    palette["brown"] = get("brown") or shade(palette["orange"], -0.4)

    for name, ansi in (
        ("red", "color9"),
        ("green", "color10"),
        ("yellow", "color11"),
        ("blue", "color12"),
        ("magenta", "color13"),
        ("cyan", "color14"),
    ):
        key = "bright_" + name
        palette[key] = get(key, ansi) or shade(palette[name], 0.18)
    palette["bright_black"] = get("bright_black", "color8") or palette["muted"]
    palette["bright_white"] = get("bright_white", "color15") or palette["bright_foreground"]

    out = {k: to_hex(v) for k, v in palette.items()}
    out["mode"] = "light" if is_light else "dark"
    return out


def title_case(slug):
    return re.sub(r"(^|-)([a-z])", lambda m: m.group(1) + m.group(2).upper(), slug).replace("-", " ")


# Omarchy's own default is square corners; a theme opts into rounding by
# setting decoration.rounding in its Hyprland config. `rounding_power`,
# `dots_rounding` and `gradient_rounding` are different settings and must not
# be mistaken for it.
ROUNDING_RE = re.compile(r"(?<![\w])rounding\s*=\s*(\d+)")


def rounding_for(theme_dir):
    for name in ("hyprland.lua", "hyprland.conf"):
        path = theme_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        found = ROUNDING_RE.search(text)
        if found:
            return int(found.group(1))
    return 0


# A theme names a Yaru icon variant in icons.theme, which is what actually
# recolours folders in the file manager. These are the folder body colours
# sampled from each variant's 256x256/places/folder.png (see
# tools/build-icons.py's sibling note in the README); anything unrecognised
# falls back to the theme's accent.
FOLDER_COLORS = {
    "Yaru": "#c94d21",
    "Yaru-dark": "#f26f3a",
    "Yaru-blue": "#1d75da",
    "Yaru-blue-dark": "#4c9bf4",
    "Yaru-magenta": "#ad56ae",
    "Yaru-magenta-dark": "#d374d2",
    "Yaru-olive": "#58861e",
    "Yaru-olive-dark": "#72a844",
    "Yaru-prussiangreen": "#428483",
    "Yaru-prussiangreen-dark": "#5ea5a2",
    "Yaru-purple": "#7c69cf",
    "Yaru-purple-dark": "#998cf3",
    "Yaru-red": "#cc445a",
    "Yaru-red-dark": "#f2697c",
    "Yaru-sage": "#6e7e71",
    "Yaru-sage-dark": "#8b9f8d",
    "Yaru-wartybrown": "#927458",
    "Yaru-wartybrown-dark": "#b39572",
    "Yaru-yellow": "#a36d1d",
    "Yaru-yellow-dark": "#c88e1d",
}


def icon_theme_for(theme_dir):
    path = theme_dir / "icons.theme"
    try:
        return path.read_text().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def backgrounds_for(slug, theme_dir):
    found = []
    for directory in (theme_dir / "backgrounds", USER_BACKGROUNDS / slug):
        if directory.is_dir():
            for item in sorted(directory.iterdir()):
                if item.is_file() and item.suffix.lower() in IMAGE_EXT:
                    found.append(item)
    return found


def discover_themes():
    """User themes shadow stock themes of the same slug, matching omarchy."""
    dirs = {}
    for root, source in ((STOCK_THEMES, "stock"), (USER_THEMES, "user")):
        if not root.is_dir():
            continue
        for item in sorted(root.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                dirs[item.name] = (item, source)

    themes = []
    for slug in sorted(dirs):
        theme_dir, source = dirs[slug]
        colors = normalize(raw_colors(theme_dir))
        icons = icon_theme_for(theme_dir)
        images = backgrounds_for(slug, theme_dir)
        themes.append(
            {
                "slug": slug,
                "name": title_case(slug),
                "source": source,
                "mode": colors.pop("mode"),
                "rounding": rounding_for(theme_dir),
                "iconTheme": icons,
                "folderColor": FOLDER_COLORS.get(icons, colors["accent"]),
                "colors": colors,
                "backgrounds": [
                    "/api/background?theme=%s&index=%d" % (slug, i) for i in range(len(images))
                ],
            }
        )
    return themes


def current_slug():
    try:
        return CURRENT_NAME.read_text().strip()
    except OSError:
        return ""


# --- http ---------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "OmarchyThemePreview/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("OTP_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache=False):
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path == "/api/themes":
            self.send_json({"current": current_slug(), "themes": discover_themes()})
            return

        if url.path == "/api/background":
            slug = (query.get("theme") or [""])[0]
            index = int((query.get("index") or ["0"])[0])
            theme_dir = None
            for root in (USER_THEMES, STOCK_THEMES):
                if (root / slug).is_dir():
                    theme_dir = root / slug
            if theme_dir is None:
                self.send_error(404)
                return
            images = backgrounds_for(slug, theme_dir)
            if not 0 <= index < len(images):
                self.send_error(404)
                return
            self.send_file(images[index], cache=True)
            return

        name = "index.html" if url.path == "/" else url.path.lstrip("/")
        asset = (APP_DIR / name).resolve()
        if asset.is_file() and APP_DIR in asset.parents:
            self.send_file(asset)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        # Lets the page dismiss itself (Escape, or the close button) by asking
        # the launcher to toggle its scratchpad away. Takes no input: it runs
        # one fixed command.
        if path == "/api/hide":
            try:
                subprocess.run(
                    [str(LAUNCHER), "--hide"],
                    capture_output=True,
                    timeout=10,
                )
                self.send_json({"ok": True})
            except (OSError, subprocess.SubprocessError) as ex:
                self.send_json({"ok": False, "error": str(ex)}, 500)
            return

        if path != "/api/apply":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_json({"ok": False, "error": "invalid json"}, 400)
            return

        slug = str(payload.get("theme", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
            self.send_json({"ok": False, "error": "unknown theme"}, 400)
            return
        if not any((root / slug).is_dir() for root in (USER_THEMES, STOCK_THEMES)):
            self.send_json({"ok": False, "error": "theme not installed"}, 404)
            return

        try:
            done = subprocess.run(
                ["omarchy", "theme", "set", slug],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as ex:
            self.send_json({"ok": False, "error": str(ex)}, 500)
            return

        ok = done.returncode == 0
        self.send_json(
            {
                "ok": ok,
                "current": current_slug(),
                "error": None if ok else (done.stderr or done.stdout).strip(),
            },
            200 if ok else 500,
        )


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Themes Explorer on http://127.0.0.1:%d" % server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
