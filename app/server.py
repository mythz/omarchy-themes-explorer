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
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
APP_DIR = Path(__file__).resolve().parent
# The launcher ships alongside the app inside the plugin folder, so the
# server never depends on anything having been installed onto PATH.
LAUNCHER = APP_DIR.parent / "bin/omarchy-themes-explorer"
# Built by scripts/build-extra-themes.py and committed, so a fresh clone of the
# plugin already has it. Absent is a normal state, not an error: the page just
# does not offer the second column.
EXTRA_THEMES = APP_DIR.parent / "extra-themes.json"
USER_THEMES = HOME / ".config/omarchy/themes"
STOCK_THEMES = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "themes"
USER_BACKGROUNDS = HOME / ".config/omarchy/backgrounds"
CURRENT_NAME = HOME / ".local/state/omarchy/current/theme.name"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


# --- color helpers ------------------------------------------------------


def parse_hex(value):
    """Accepts #rrggbb, #rgb and 0xrrggbb -- the last is what alacritty.toml uses."""
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"(?:#|0x)?([0-9a-fA-F]{6})|#?([0-9a-fA-F]{3})", value.strip())
    if not m:
        return None
    h = (m.group(1) or m.group(2)).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def to_hex(rgb):
    # int(c + 0.5), not round(): Python rounds halves to even, awk -- and so
    # omarchy-theme-color -- rounds them up, and the two disagree on a handful
    # of derived shades.
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c + 0.5))) for c in rgb)


def luminance(rgb):
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def mix_hex(start, end, amount):
    """omarchy-theme-color's mix_color: `amount` of `end` blended into `start`."""
    a, b = parse_hex(start), parse_hex(end)
    return to_hex(tuple(a[i] * (1 - amount) + b[i] * amount for i in range(3)))


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
    """Resolve a palette the way omarchy-theme-color does.

    This mirrors that script's fallback chain rather than inventing one, because
    every generated config -- vscode-theme.json, btop.theme, hyprland.lua -- is
    rendered from the names it produces. Deriving them differently is how the
    preview ended up drawing `muted` as a mixed violet when Omarchy resolves it
    to color8, a flat grey: the file tree, line numbers, inactive tabs and the
    activity bar all read it.
    """

    c = {}
    for key, value in raw.items():
        rgb = parse_hex(value)
        if rgb:
            c[key] = to_hex(rgb)

    def alias(key, *fallbacks):
        if not c.get(key):
            for name in fallbacks:
                if c.get(name):
                    c[key] = c[name]
                    return

    # Canonical names win over the short forms an older theme may use.
    for canon, short in (
        ("background", "bg"),
        ("dark_background", "dark_bg"),
        ("darker_background", "darker_bg"),
        ("lighter_background", "lighter_bg"),
        ("foreground", "fg"),
        ("dark_foreground", "dark_fg"),
        ("light_foreground", "light_fg"),
        ("bright_foreground", "bright_fg"),
    ):
        alias(canon, short)

    alias("background", "color0")
    alias("foreground", "color7")
    c.setdefault("background", "#1a1b26")
    c.setdefault("foreground", "#c8c8c8")
    c["color0"] = c["background"]
    c["color7"] = c["foreground"]

    for name, ansi in (
        ("red", "color1"),
        ("green", "color2"),
        ("yellow", "color3"),
        ("blue", "color4"),
        ("magenta", "color5"),
        ("cyan", "color6"),
        ("bright_red", "color9"),
        ("bright_green", "color10"),
        ("bright_yellow", "color11"),
        ("bright_blue", "color12"),
        ("bright_magenta", "color13"),
        ("bright_cyan", "color14"),
    ):
        alias(name, ansi)
    alias("magenta", "purple")
    alias("bright_magenta", "bright_purple")

    alias("light_foreground", "color7", "foreground")
    alias("bright_foreground", "color15", "foreground")
    c["cursor"] = c["bright_foreground"]
    alias("lighter_background", "color0", "background")
    alias("dark_foreground", "color8", "foreground")
    alias("muted", "color8", "dark_foreground")
    alias("selection", "selection_background", "color8", "color0", "background")
    alias("selection_background", "selection")
    alias("selection_foreground", "bright_foreground")

    # A theme with no palette beyond a background and foreground still needs
    # the six hues; Omarchy's own themes always carry them.
    for name, fallback in (
        ("red", "#dc5a5a"),
        ("green", "#8cbe6e"),
        ("yellow", "#dcb464"),
        ("blue", "#78a0f0"),
        ("magenta", "#b48ce6"),
        ("cyan", "#64bec8"),
    ):
        c.setdefault(name, fallback)

    alias("orange", "yellow")
    c.setdefault("brown", mix_hex(c["orange"], "#000000", 0.50))
    c.setdefault("dark_background", mix_hex(c["background"], "#000000", 0.25))
    c.setdefault("darker_background", mix_hex(c["background"], "#000000", 0.50))
    for name in ("red", "yellow", "green", "cyan", "blue", "magenta"):
        c.setdefault("bright_" + name, mix_hex(c[name], "#ffffff", 0.20))
    c.setdefault("bright_black", c["muted"])
    c.setdefault("bright_white", c["bright_foreground"])
    c.setdefault("black", c["background"])
    c.setdefault("white", c["foreground"])
    c.setdefault("accent", c["blue"])

    is_light = str(raw.get("mode", "")).lower() == "light" or (
        "mode" not in raw and luminance(parse_hex(c["background"])) > 0.5
    )

    out = {
        key: c[key]
        for key in (
            "background", "dark_background", "darker_background", "lighter_background",
            "foreground", "dark_foreground", "light_foreground", "bright_foreground",
            "red", "green", "yellow", "blue", "magenta", "cyan",
            "black", "white", "accent", "selection", "muted", "orange", "brown",
            "bright_red", "bright_green", "bright_yellow", "bright_blue",
            "bright_magenta", "bright_cyan", "bright_black", "bright_white",
        )
    }
    out["mode"] = "light" if is_light else "dark"
    return out


def title_case(slug):
    return re.sub(r"(^|-)([a-z])", lambda m: m.group(1) + m.group(2).upper(), slug).replace("-", " ")


# Corner radius is Omarchy's, never the theme's. Every theme's staged
# hyprland.lua is generated from default/themed/hyprland.lua.tpl, which sets
# border colours and nothing else -- and a git-installed theme cannot supply
# Lua at all, so a `rounding` in its own hyprland.conf is never read. What
# Hyprland actually runs is default/hypr/looknfeel.lua, which is square.
# `rounding_power`, `dots_rounding` and `gradient_rounding` are different
# settings and must not be mistaken for it.
ROUNDING_RE = re.compile(r"(?<![\w])rounding\s*=\s*(\d+)")
LOOKNFEEL = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "default/hypr/looknfeel.lua"


def system_rounding():
    try:
        found = ROUNDING_RE.search(LOOKNFEEL.read_text(errors="replace"))
    except OSError:
        return 0
    return int(found.group(1)) if found else 0


# A theme names a Yaru icon variant in icons.theme, which is what actually
# recolours folders in the file manager. These are each variant's folder body
# colour, taken as the most common opaque pixel of its
# 256x256/places/folder.png -- the flat front face, which is what the eye reads
# as "the folder colour". Anything unrecognised falls back to the accent.
FOLDER_COLORS = {
    "Yaru": "#da5b2a",
    "Yaru-dark": "#ff7f45",
    "Yaru-blue": "#2686e6",
    "Yaru-blue-dark": "#59a9ff",
    "Yaru-magenta": "#bc65bd",
    "Yaru-magenta-dark": "#df85de",
    "Yaru-olive": "#669427",
    "Yaru-olive-dark": "#80b550",
    "Yaru-prussiangreen": "#4e9291",
    "Yaru-prussiangreen-dark": "#6db2af",
    "Yaru-purple": "#8a79dc",
    "Yaru-purple-dark": "#a69afe",
    "Yaru-red": "#dd5169",
    "Yaru-red-dark": "#ff798a",
    "Yaru-sage": "#7c8c7f",
    "Yaru-sage-dark": "#98ac9a",
    "Yaru-wartybrown": "#a08367",
    "Yaru-wartybrown-dark": "#bfa280",
    "Yaru-yellow": "#b17d26",
    "Yaru-yellow-dark": "#d49c26",
}


# A theme ships btop's palette outright, so the preview reads it instead of
# guessing one from the terminal colours. btop picks the box borders and meter
# gradients independently of the ANSI palette -- omacon's mem box is #8563ff
# while its cpu box is #ff66ff -- and no derivation recovers that.
BTOP_KEY_RE = re.compile(r'theme\[([a-z_]+)\]\s*=\s*"(#[0-9a-fA-F]{3,6})"')

# Only the keys the page actually paints with: the file has forty-odd, and the
# rest would be dead weight in extra-themes.json.
BTOP_KEYS = {
    "title", "hi_fg", "inactive_fg", "div_line", "proc_misc",
    "cpu_box", "mem_box", "net_box", "proc_box",
    "selected_bg", "selected_fg", "meter_bg",
    "cpu_start", "cpu_mid", "cpu_end", "temp_start",
    "download_mid", "upload_mid",
}


def btop_colors_from_text(text):
    out = {}
    for key, value in BTOP_KEY_RE.findall(text or ""):
        if key in BTOP_KEYS and parse_hex(value):
            out[key] = to_hex(parse_hex(value))
    return out


# What Omarchy renders from default/themed/btop.theme.tpl for a theme that
# ships no btop.theme of its own. Only the keys the page paints with.
BTOP_TEMPLATE = {
    "title": "foreground",
    "hi_fg": "accent",
    "inactive_fg": "muted",
    "div_line": "muted",
    "proc_misc": "light_foreground",
    "cpu_box": "magenta",
    "mem_box": "green",
    "net_box": "red",
    "proc_box": "accent",
    "selected_bg": "selection",
    "selected_fg": "accent",
    "meter_bg": "selection",
    "cpu_start": "cyan",
    "cpu_mid": "blue",
    "cpu_end": "magenta",
    "temp_start": "green",
    "download_mid": "red",
    "upload_mid": "cyan",
}


def btop_colors(theme_dir, colors):
    try:
        found = btop_colors_from_text((theme_dir / "btop.theme").read_text(errors="replace"))
    except OSError:
        found = {}
    return found or {k: colors[v] for k, v in BTOP_TEMPLATE.items()}


# Hyprland border colours come from colors.toml, not from a theme's own
# hyprland config: the staged hyprland.lua is rendered from
# default/themed/hyprland.lua.tpl, which reads `hyprland_active_border`
# (defaulting to the accent) and `hyprland_inactive_border` (defaulting to a
# fixed grey). Either may be a gradient of several colours plus an angle; the
# first stop is the one a flat preview can show.
HYPR_COLOR_RE = re.compile(
    r"rgba?\(\s*([0-9a-fA-F]{6,8})\s*\)|0x([0-9a-fA-F]{8})|#([0-9a-fA-F]{6,8})"
)
DEFAULT_INACTIVE_BORDER = "rgba(595959aa)"


def hypr_color(value, fallback=""):
    """First stop of a Hyprland colour or gradient, as CSS."""
    found = HYPR_COLOR_RE.search(str(value or ""))
    if not found:
        return fallback
    if found.group(2):
        # 0xaarrggbb -> #rrggbbaa
        digits = found.group(2)
        return ("#" + digits[2:] + digits[:2]).lower()
    # rgb()/rgba()/# are already rrggbb[aa]
    return ("#" + (found.group(1) or found.group(3))).lower()


def border_colors(raw, colors):
    return {
        "active": hypr_color(raw.get("hyprland_active_border"), colors["accent"]),
        "inactive": hypr_color(raw.get("hyprland_inactive_border"))
        or hypr_color(DEFAULT_INACTIVE_BORDER),
    }


# The scopes the preview's tokeniser can distinguish, each resolved out of the
# theme's own vscode-theme.json. Guessing these from the ANSI palette is what
# made the editor look plausible but wrong: Tokyo Night paints an import
# keyword (#7aa2f7) and a plain keyword (#bb9af7) in different colours, and
# neither is a slot in colors.toml.
# VS Code settings files and theme files are JSONC.
def strip_jsonc(text):
    out = []
    i, n = 0, len(text)
    in_string = escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


EXTENSION_DIRS = (
    HOME / ".vscode/extensions",
    HOME / ".vscode-oss/extensions",
    HOME / ".vscode-insiders/extensions",
)


def extension_theme(descriptor):
    """Locate the colour theme an installed extension contributes.

    A theme may hand VS Code off to a third-party extension instead of the
    generated file -- Omarchy's Tokyo Night ships
    `{"name": "Tokyo Night", "extension": "enkia.tokyo-night"}` -- and
    omarchy-theme-set-vscode then installs it and points workbench.colorTheme
    at that label. Nineteen of the shipped themes do this, so reading the
    generated file for them describes colours the editor never shows.
    """
    name = (descriptor.get("name") or "").strip()
    extension = (descriptor.get("extension") or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z0-9._-]+", extension):
        return None
    for root in EXTENSION_DIRS:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            # Directories are "<publisher>.<name>-<version>[-<target>]".
            if not entry.is_dir() or entry.name.lower().find(extension.lower() + "-") != 0:
                continue
            try:
                package = json.loads(strip_jsonc((entry / "package.json").read_text(errors="replace")))
            except (OSError, ValueError):
                continue
            for contributed in (package.get("contributes") or {}).get("themes") or []:
                label = contributed.get("label") or contributed.get("id") or ""
                if label != name:
                    continue
                path = (entry / (contributed.get("path") or "")).resolve()
                try:
                    return json.loads(strip_jsonc(path.read_text(errors="replace")))
                except (OSError, ValueError):
                    return None
    return None


def vscode_theme_json(theme_dir):
    """The colour theme VS Code actually loads for this Omarchy theme."""
    try:
        descriptor = json.loads(strip_jsonc((theme_dir / "vscode.json").read_text(errors="replace")))
    except (OSError, ValueError):
        descriptor = None
    if isinstance(descriptor, dict):
        found = extension_theme(descriptor)
        if found:
            return found
    try:
        return json.loads(strip_jsonc((theme_dir / "vscode-theme.json").read_text(errors="replace")))
    except (OSError, ValueError):
        return None


# Semantic tokens override TextMate scopes, but only when the theme turns
# semantic highlighting on -- enkia's Tokyo Night does not, which is why its
# `Palette` is the plain foreground of entity.name.type and not the yellow its
# unused semanticTokenColors would give an interface.
SEMANTIC_SCOPES = {
    "key": "keyword",
    "fn": "function",
    "str": "string",
    "num": "number",
    "bool": "boolean",
    "op": "operator",
    "typ": "type",
    "prop": "property",
    "var": "variable",
    "objkey": "property.declaration",
    "com": "comment",
}

SYNTAX_SCOPES = {
    "key": "keyword",
    "imp": "keyword.control.import",
    "fn": "entity.name.function",
    "str": "string",
    "num": "constant.numeric",
    "com": "comment",
    "typ": "entity.name.type",
    "prim": "support.type",
    "op": "keyword.operator",
    "pun": "punctuation",
    "var": "variable",
    "prop": "variable.other.property",
    "objkey": "meta.object-literal.key",
    "docTag": "storage.type.class.jsdoc",
    "docType": "entity.name.type.instance.jsdoc",
    "docName": "variable.other.jsdoc",
    "builtin": "variable.language",
    "ctor": "support.class",
    "param": "variable.parameter",
    "cst": "variable.other.constant",
    "bool": "constant.language.boolean",
}


def scope_color(rules, wanted):
    """TextMate resolution: the longest matching scope prefix wins, later rules
    beating earlier ones on a tie -- which is how VS Code itself picks."""
    best = (-1, None, None)
    for index, rule in enumerate(rules):
        settings = rule.get("settings") or {}
        fg = settings.get("foreground")
        if not fg or not parse_hex(fg):
            continue
        scopes = rule.get("scope") or []
        if isinstance(scopes, str):
            scopes = [part.strip() for part in scopes.split(",")]
        for scope in scopes:
            scope = scope.strip()
            # A descendant selector ("source.json meta...") is too narrow to
            # stand in for a bare scope.
            if not scope or " " in scope:
                continue
            if wanted == scope or wanted.startswith(scope + "."):
                if (len(scope), index) > (best[0], best[1] if best[1] is not None else -1):
                    best = (len(scope), index, (to_hex(parse_hex(fg)), settings.get("fontStyle", "")))
    return best[2]


# What default/themed/vscode-theme.json.tpl assigns each of those scopes. Only
# two of the installed themes ship a vscode-theme.json of their own; for the
# rest Omarchy renders this, and rendering it here reproduces the staged file
# exactly -- checked value by value against Tokyo Night's.
SYNTAX_TEMPLATE = {
    "key": "bright_magenta",     # keyword, storage.type.class
    "imp": "blue",               # keyword.control.import / export / from
    "fn": "blue",                # entity.name.function
    "str": "green",              # string
    "num": "orange",             # constant.numeric
    "com": "muted",              # comment, italic
    "typ": "yellow",             # storage.type, entity.name.type
    "prim": "foreground",        # storage.type.primitive, support.type
    "op": "bright_blue",         # keyword.operator
    "pun": "dark_foreground",    # punctuation, meta.brace
    "var": "foreground",         # variable
    "prop": "cyan",              # variable.other.property
    "objkey": "foreground",      # meta.object-literal.key
    "docTag": "bright_magenta",  # @param / @returns
    "docType": "yellow",         # the {type} beside it
    "docName": "foreground",     # the name after the type
    "builtin": "foreground",     # variable.language -- window, this
    "ctor": "yellow",            # support.class -- the name after `new`
    "param": "cyan",             # variable.parameter
    "cst": "bright_yellow",      # variable.other.constant
    "bool": "orange",            # constant.language.boolean
}


def syntax_colors(theme_dir, colors):
    """Token colours from the colour theme VS Code actually loads, falling back
    to the mapping Omarchy's own template would have rendered."""
    out = {}
    data = vscode_theme_json(theme_dir) or {}
    rules = data.get("tokenColors")
    if isinstance(rules, list):
        for name, scope in SYNTAX_SCOPES.items():
            found = scope_color(rules, scope)
            if found:
                out[name] = found[0]
                if "italic" in found[1]:
                    out[name + "_italic"] = True
    if data.get("semanticHighlighting"):
        semantic = data.get("semanticTokenColors") or {}
        for name, key in SEMANTIC_SCOPES.items():
            value = semantic.get(key)
            if isinstance(value, dict):
                style = value.get("fontStyle", "")
                value = value.get("foreground")
            else:
                style = ""
            if isinstance(value, str) and parse_hex(value):
                out[name] = to_hex(parse_hex(value))
                if "italic" in style:
                    out[name + "_italic"] = True
    for name, key in SYNTAX_TEMPLATE.items():
        out.setdefault(name, colors[key])
    out.setdefault("com_italic", True)
    return out


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
        raw = raw_colors(theme_dir)
        colors = normalize(raw)
        icons = icon_theme_for(theme_dir)
        images = backgrounds_for(slug, theme_dir)
        themes.append(
            {
                "slug": slug,
                "name": title_case(slug),
                "source": source,
                "mode": colors.pop("mode"),
                "borders": border_colors(raw, colors),
                "btop": btop_colors(theme_dir, colors),
                "syntax": syntax_colors(theme_dir, colors),
                "iconTheme": icons,
                "folderColor": FOLDER_COLORS.get(icons, colors["accent"]),
                "colors": colors,
                "backgrounds": [
                    "/api/background?theme=%s&index=%d" % (slug, i) for i in range(len(images))
                ],
            }
        )
    return themes


def extra_themes(installed):
    """Community themes from extra-themes.json that are not installed here.

    A slug that exists locally is dropped rather than shown twice: the local
    copy is the one the page can actually apply, and `omarchy theme install`
    would overwrite it. Slugs match because the build script derives them the
    same way omarchy-theme-install does.
    """
    try:
        with open(EXTRA_THEMES, "rb") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    themes = data.get("themes")
    if not isinstance(themes, list):
        return []
    return [
        t
        for t in themes
        if isinstance(t, dict) and t.get("slug") and t["slug"] not in installed
    ]


def extra_repo(slug):
    """The clone URL we published for this slug, or "" if we did not publish one.

    The page sends a slug and never a URL: the thing about to be handed to
    `git clone` has to come from a file we shipped, not from the request.
    """
    for theme in extra_themes(set()):
        if theme["slug"] == slug:
            repo = theme.get("repo") or ""
            return repo if re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", repo) else ""
    return ""


# --- extra-theme wallpaper thumbnails ------------------------------------

# An extra theme's wallpapers live on GitHub and run to megabytes -- Pulsar's
# first one is 12MB at 7680x4320. Downloading that before anything appears
# makes browsing the list feel broken, so a small WebP of each is kept here and
# painted first while the original loads over it. Only the thumbnail is stored;
# the original is written to a temp file, encoded, and deleted.
THUMB_CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME") or (HOME / ".cache"))
    / "omarchy-themes-explorer/backgrounds"
)
# 1600px at quality 80, and only if that overshoots the budget is the encoder
# asked to hit a size instead. Measured against the original resampled to
# display width, over a detailed photo, a flat render and a painted scene:
#
#   960px q55        39.5 / 17.5 / 29.2 KB   28.7 / 32.9 / 29.5 dB
#   1600px q80       92.6 / 67.7 / 97.1 KB   32.3 / 37.4 / 34.8 dB
#
# Quality first because a simple image has no use for the whole budget -- the
# flat render lands at 68KB on its own. Width is 1600 rather than 1920 because
# under a fixed budget the extra pixels cost more than they return on a
# detailed photo (1920 measured 0.8dB *worse* there), while giving up under a
# dB on the easy ones.
THUMB_WIDTH = 1600
THUMB_QUALITY = 80
THUMB_BUDGET = 92000
THUMB_CAP = 100 * 1024
THUMB_MAX_BYTES = 64 * 1024 * 1024
USER_AGENT = "omarchy-themes-explorer/1.0"

# Bumped whenever the recipe above changes, so thumbnails encoded by an older
# one are cleared rather than served forever.
THUMB_VERSION = "2"

_thumb_lock = threading.Lock()
_thumb_busy = set()


def encoder():
    """ImageMagick under either of its names, or None -- the cache is an
    optimisation, so its absence has to be survivable."""
    for name in ("magick", "convert"):
        found = shutil.which(name)
        if found:
            return found
    return None


def thumb_path(slug, index):
    return THUMB_CACHE / slug / ("%d.webp" % index)


def clear_stale_thumbs():
    """Drop the cache when the encoding recipe has changed under it."""
    marker = THUMB_CACHE / ".version"
    try:
        if marker.read_text().strip() == THUMB_VERSION:
            return
    except OSError:
        pass
    shutil.rmtree(THUMB_CACHE, ignore_errors=True)
    try:
        THUMB_CACHE.mkdir(parents=True, exist_ok=True)
        marker.write_text(THUMB_VERSION)
    except OSError:
        pass


def build_thumb(slug, index, url):
    """Fetch one wallpaper and write a small WebP of it. Runs off the request."""
    tool = encoder()
    if not tool:
        return
    destination = thumb_path(slug, index)
    temp_source = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > THUMB_MAX_BYTES:
                return
            with tempfile.NamedTemporaryFile(delete=False) as handle:
                temp_source = handle.name
                shutil.copyfileobj(response, handle, 1 << 20)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # ">" only ever shrinks; a wallpaper already smaller than the thumbnail
        # is left at its own size rather than blown up.
        partial = destination.with_name(destination.name + ".part")

        def encode(extra):
            # `webp:` names the format outright. Without it ImageMagick reads
            # the format off the output extension, and a ".part" it does not
            # recognise silently leaves the file in the input's format -- a JPEG
            # that then gets renamed to .webp and served with the wrong type.
            done = subprocess.run(
                [tool, temp_source, "-resize", "%dx>" % THUMB_WIDTH]
                + extra
                + ["-strip", "webp:" + str(partial)],
                capture_output=True,
                timeout=120,
            )
            if done.returncode != 0 or not partial.is_file():
                return 0
            return partial.stat().st_size

        size = encode(["-quality", str(THUMB_QUALITY)])
        if size > THUMB_CAP:
            size = encode(["-define", "webp:target-size=%d" % THUMB_BUDGET])
        if size:
            partial.replace(destination)
        elif partial.exists():
            partial.unlink()
    except (OSError, ValueError, urllib.error.URLError, subprocess.SubprocessError):
        pass
    finally:
        if temp_source:
            try:
                os.unlink(temp_source)
            except OSError:
                pass
        with _thumb_lock:
            _thumb_busy.discard((slug, index))


def request_thumb(slug, index, url):
    with _thumb_lock:
        if (slug, index) in _thumb_busy:
            return
        _thumb_busy.add((slug, index))
    threading.Thread(target=build_thumb, args=(slug, index, url), daemon=True).start()


def extra_background(slug, index):
    """The published URL of one extra theme's wallpaper, or "" if there is none."""
    for theme in extra_themes(set()):
        if theme["slug"] != slug:
            continue
        images = theme.get("backgrounds") or []
        if 0 <= index < len(images):
            return images[index]
        return ""
    return ""


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
            themes = discover_themes()
            self.send_json(
                {
                    "current": current_slug(),
                    "rounding": system_rounding(),
                    "themes": themes,
                    "extra": extra_themes({t["slug"] for t in themes}),
                }
            )
            return

        if url.path == "/api/extra-background":
            slug = (query.get("theme") or [""])[0]
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", slug):
                self.send_error(404)
                return
            try:
                index = int((query.get("index") or ["0"])[0])
            except ValueError:
                self.send_error(404)
                return
            path = thumb_path(slug, index)
            if path.is_file():
                self.send_file(path, cache=True)
                return
            # Nothing cached yet: answer 404 so the page falls straight through
            # to the original, and fetch it in the background for next time.
            remote = extra_background(slug, index)
            if remote:
                request_thumb(slug, index, remote)
            self.send_error(404)
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

        if path not in ("/api/apply", "/api/install"):
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

        # Cloning a theme someone else wrote, so the URL is looked up by slug in
        # the file we shipped rather than taken from the request. `omarchy theme
        # install` clones it and then applies it, which is why this answers with
        # the same fields as /api/apply.
        if path == "/api/install":
            repo = extra_repo(slug)
            if not repo:
                self.send_json({"ok": False, "error": "not a known extra theme"}, 404)
                return
            # omarchy-theme-install rm -rf's an existing theme of the same name
            # before cloning. The page never offers this -- an installed slug is
            # filtered out of the extra list -- so reaching here means a request
            # the UI cannot produce, and it must not eat a local theme.
            if any((root / slug).is_dir() for root in (USER_THEMES, STOCK_THEMES)):
                self.send_json({"ok": False, "error": "already installed"}, 409)
                return
            try:
                done = subprocess.run(
                    ["omarchy", "theme", "install", repo],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
            except (OSError, subprocess.SubprocessError) as ex:
                self.send_json({"ok": False, "error": str(ex)}, 500)
                return
            installed = any((root / slug).is_dir() for root in (USER_THEMES, STOCK_THEMES))
            ok = done.returncode == 0 and installed
            self.send_json(
                {
                    "ok": ok,
                    "current": current_slug(),
                    "themes": discover_themes(),
                    "error": None if ok else (done.stderr or done.stdout).strip(),
                },
                200 if ok else 500,
            )
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
    clear_stale_thumbs()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Themes Explorer on http://127.0.0.1:%d" % server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
