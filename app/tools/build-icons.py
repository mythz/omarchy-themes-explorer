#!/usr/bin/env python3
"""Regenerate icons.js from the system Adwaita icon theme.

The folder colours in server.py's FOLDER_COLORS were sampled alongside these,
one per installed Yaru variant:

    for d in /usr/share/icons/*/; do
      magick "$d/256x256/places/folder.png" -crop 40%x30%+30%+50% +repage \\
        -resize 1x1 -format '%[hex:p{0,0}]' info:
    done


Run after an Adwaita update if the shapes drift:  python3 tools/build-icons.py
"""
import json
import re
from pathlib import Path

A = Path("/usr/share/icons/Adwaita")
OUT = Path(__file__).resolve().parent.parent / "icons.js"

SYMBOLIC = {
    "home": "places/user-home-symbolic.svg",
    "folder": "places/folder-symbolic.svg",
    "trash": "places/user-trash-symbolic.svg",
    "download": "places/folder-download-symbolic.svg",
    "network": "places/network-server-symbolic.svg",
    "search": "actions/system-search-symbolic.svg",
    "menu": "actions/open-menu-symbolic.svg",
    "prev": "actions/go-previous-symbolic.svg",
    "next": "actions/go-next-symbolic.svg",
    "more": "actions/view-more-symbolic.svg",
    "close": "ui/window-close-symbolic.svg",
    "list": "actions/view-list-symbolic.svg",
    "down": "ui/pan-down-symbolic.svg",
    "star": "status/starred-symbolic.svg",
    "recent": "actions/document-open-recent-symbolic.svg",
    "sidebar": "actions/sidebar-show-symbolic.svg",
    "find": "actions/edit-find-symbolic.svg",
}

paths = lambda s: re.findall(r'<path\b[^>]*?d="([^"]+)"[^>]*?/>', s)
viewbox = lambda s: re.search(r'viewBox="([^"]+)"', s).group(1)

sym = {}
for name, rel in SYMBOLIC.items():
    text = (A / "symbolic" / rel).read_text()
    sym[name] = {"v": viewbox(text), "d": paths(text)}

folder_svg = (A / "scalable/places/folder.svg").read_text()
fp = paths(folder_svg)
folder = {"v": viewbox(folder_svg), "back": fp[0], "front": fp[2]}

doc_svg = (A / "scalable/mimetypes/text-x-generic.svg").read_text()
dp = paths(doc_svg)
doc = {"v": viewbox(doc_svg), "page": dp[0], "lines": dp[1:]}

body = OUT.read_text()
for token, value in (("SYM", sym), ("FOLDER", folder), ("DOC", doc)):
    body = re.sub(
        r"(const %s = )\{.*?\n  \};" % token,
        lambda m: m.group(1) + json.dumps(value, indent=2).replace("\n", "\n  ") + ";",
        body,
        flags=re.S,
    )
OUT.write_text(body)
print("updated", OUT)

# Note for whoever regenerates the menu items in apps.js from
# /usr/share/omarchy/default/omarchy/omarchy-menu.jsonc: five of those icons
# are astral (U+F003B apps, U+F09D1 brain, U+F14DE rocket, U+F0249 floppy,
# U+F0B4C folder-remove). They must be written as \u{XXXXX}; a "\uXXXX"
# escape truncates them and JS renders the wrong glyph plus a stray letter.
