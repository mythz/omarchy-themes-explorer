#!/usr/bin/env python3
"""Build extra-themes.json: every community theme listed in the Omarchy manual,
described well enough for the preview page to render it without installing it.

The page already knows how to draw a theme from the shape `/api/themes` returns,
so this produces that same shape -- slug, mode, rounding, iconTheme, folderColor,
colors -- for themes that live in someone else's git repo instead of on disk. The
colour maths is imported from server.py rather than reimplemented, so an extra
theme and an installed one are folded through identical code and cannot drift.

Backgrounds stay as GitHub URLs. Nothing is downloaded into the repo: the page
points <img> straight at github.com, which keeps this file small enough for the
plugin to refresh on every launch.

Usage:
    scripts/build-extra-themes.py                 # write extra-themes.json
    scripts/build-extra-themes.py --refresh       # ignore the on-disk cache
    scripts/build-extra-themes.py -o /tmp/x.json  # somewhere else

Needs a GitHub token for the tree API -- 117 repos is well past the 60/hour
unauthenticated budget. GITHUB_TOKEN, GH_TOKEN or a logged-in `gh` all work.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

# The single source of truth for how a palette is derived. Importing it is the
# point: a change to server.py's fallbacks reaches extra themes on the next build.
from server import (  # noqa: E402
    FOLDER_COLORS,
    IMAGE_EXT,
    ROUNDING_RE,
    flatten_alacritty,
    normalize,
)

EXTRA_THEMES_URL = "https://learn.omacom.io/2/the-omarchy-manual/90/extra-themes"
DOCS_BASE = "https://learn.omacom.io"
GITHUB_API = "https://api.github.com"
OUTPUT = REPO_ROOT / "extra-themes.json"
CACHE_DIR = REPO_ROOT / ".cache/extra-themes"

# learn.omacom.io answers urllib's default User-Agent with a 403 (and a 503 when
# it is being less polite about it), so say who we are. This is the same string
# curl would send; nothing here depends on being mistaken for a browser.
USER_AGENT = "omarchy-themes-explorer-build/1.0 (+https://github.com/mythz/omarchy-themes-explorer)"

# A theme repo is a directory holding one of these next to the rest of the
# config. Most are the repo root; a few vendor their theme a level down.
COLOR_FILES = ("colors.toml", "alacritty.toml")
MAX_WORKERS = 8


# --- http ---------------------------------------------------------------


class Http:
    """Fetcher with a disk cache, a token, and enough patience for rate limits."""

    def __init__(self, cache_dir, refresh=False, token=""):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.token = token
        self.hits = 0
        self.misses = 0
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url):
        if not self.cache_dir:
            return None
        return self.cache_dir / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url, api=False, optional=False):
        """Return bytes, or None when `optional` and the file is simply absent."""
        path = self._cache_path(url)
        if path and not self.refresh and path.is_file():
            self.hits += 1
            body = path.read_bytes()
            return None if body == b"\0missing" else body

        headers = {"User-Agent": USER_AGENT}
        if api:
            headers["Accept"] = "application/vnd.github+json"
            if self.token:
                headers["Authorization"] = "Bearer " + self.token

        body = None
        last = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=30
                ) as response:
                    body = response.read()
                break
            except urllib.error.HTTPError as ex:
                last = ex
                if ex.code == 404 and optional:
                    body = None
                    break
                # Secondary rate limits answer 403 with a reset time; honour it
                # rather than hammering, but never sleep longer than a coffee.
                if ex.code in (403, 429):
                    reset = ex.headers.get("X-RateLimit-Reset")
                    remaining = ex.headers.get("X-RateLimit-Remaining")
                    if remaining == "0" and reset:
                        wait = min(300, max(1, int(reset) - int(time.time()) + 2))
                        print("rate limited, waiting %ds" % wait, file=sys.stderr)
                        time.sleep(wait)
                        continue
                if ex.code < 500 and ex.code not in (403, 429):
                    raise
                time.sleep(2**attempt)
            except (urllib.error.URLError, OSError) as ex:
                last = ex
                time.sleep(2**attempt)
        else:
            raise RuntimeError("GET %s failed: %s" % (url, last))

        self.misses += 1
        if path:
            path.write_bytes(b"\0missing" if body is None else body)
        return body

    def json(self, url, optional=False):
        body = self.get(url, api=True, optional=optional)
        return None if body is None else json.loads(body)

    def text(self, url, optional=False):
        body = self.get(url, optional=optional)
        return None if body is None else body.decode("utf-8", "replace")


def github_token():
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name].strip()
    try:
        done = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if done.returncode == 0:
            return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# --- the manual ---------------------------------------------------------


LISTING_RE = re.compile(
    r'<p>.*?<img\s+src="([^"]+)"[^>]*>.*?'
    r'<a\s+href="(https://github\.com/[^"]+)">([^<]+)</a>\s*</p>',
    re.DOTALL,
)


def listed_themes(http):
    """Name, repo and screenshot for each theme in the manual's Extra Themes page."""
    html = http.text(EXTRA_THEMES_URL)
    start = html.find('id="extra-themes"')
    if start < 0:
        raise SystemExit("extra-themes section not found; the manual's markup changed")
    end = html.find("</main>", start)
    section = html[start : end if end > 0 else len(html)]

    themes = []
    seen = set()
    for preview, repo, name in LISTING_RE.findall(section):
        repo = repo.strip().rstrip("/")
        if repo in seen:
            continue
        seen.add(repo)
        if preview.startswith("/"):
            preview = DOCS_BASE + preview
        themes.append({"name": name.strip(), "repo": repo, "preview": preview.strip()})
    return themes


def slug_for(repo_url):
    """Reproduce omarchy-theme-install's naming, so an installed extra theme and
    its entry here agree on a slug. Anything it would refuse gets refused too."""
    path = repo_url
    if "://" in path:
        path = urllib.parse.urlparse(path).path
    elif ":" in path and "/" not in path.split(":", 1)[0]:
        path = path.split(":", 1)[1]
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    name = re.sub(r"^omarchy-", "", name)
    name = re.sub(r"-theme$", "", name)
    name = name.lower()
    return name if re.fullmatch(r"[a-z0-9_][a-z0-9._+-]*", name) else ""


# --- one theme ----------------------------------------------------------


def owner_repo(repo_url):
    parts = urllib.parse.urlparse(repo_url).path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("not a repo url: " + repo_url)
    return parts[0], parts[1][:-4] if parts[1].endswith(".git") else parts[1]


def theme_root(paths):
    """The directory the theme config actually lives in.

    Shallowest wins, and a colours file beats a bare backgrounds/ directory: a
    repo that ships previews under backgrounds/ at the root but the real theme
    one level down should resolve to the level down.
    """
    best = None
    for path in paths:
        directory, _, name = path.rpartition("/")
        if name in COLOR_FILES:
            depth = directory.count("/") if directory else -1
            if best is None or depth < best[0]:
                best = (depth, directory)
    if best is not None:
        return best[1]
    for path in sorted(paths):
        if "backgrounds/" in path:
            return path.split("backgrounds/", 1)[0].rstrip("/")
    return ""


def blob_url(owner, repo, branch, path):
    quoted = urllib.parse.quote(path)
    return "https://github.com/%s/%s/blob/%s/%s?raw=true" % (owner, repo, branch, quoted)


def raw_url(owner, repo, branch, path):
    return "https://raw.githubusercontent.com/%s/%s/%s/%s" % (
        owner,
        repo,
        branch,
        urllib.parse.quote(path),
    )


def parse_colors_toml(text):
    """colors.toml is `key = "#hex"` lines; tomllib is stricter than the themes are."""
    import tomllib

    try:
        return tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        pass
    # Salvage what a hand-written file meant. A theme with one unquoted value
    # should still get a palette rather than fall out of the list entirely.
    out = {}
    for line in text.splitlines():
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]?(#?[0-9a-fA-F]{3,8})", line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def build_theme(http, listing):
    owner, repo = owner_repo(listing["repo"])
    slug = slug_for(listing["repo"])
    if not slug:
        raise ValueError("repo name does not give a usable theme slug")

    meta = http.json("%s/repos/%s/%s" % (GITHUB_API, owner, repo))
    branch = meta.get("default_branch") or "main"
    tree = http.json(
        "%s/repos/%s/%s/git/trees/%s?recursive=1" % (GITHUB_API, owner, repo, branch)
    )
    if tree.get("truncated"):
        print("  %s: tree truncated, may be missing files" % slug, file=sys.stderr)
    paths = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
    if not paths:
        raise ValueError("repo is empty")

    root = theme_root(paths)
    prefix = root + "/" if root else ""

    def under(name):
        return prefix + name

    def fetch(name):
        return http.text(raw_url(owner, repo, branch, under(name)), optional=True)

    # colors.toml when it exists, alacritty.toml the way server.py falls back.
    raw = {}
    if under("colors.toml") in paths:
        raw = parse_colors_toml(fetch("colors.toml") or "")
    if not raw and under("alacritty.toml") in paths:
        import tomllib

        try:
            raw = flatten_alacritty(tomllib.loads(fetch("alacritty.toml") or ""))
        except (tomllib.TOMLDecodeError, ValueError):
            raw = {}
    if not raw:
        raise ValueError("no usable colors.toml or alacritty.toml")

    colors = normalize(raw)
    mode = colors.pop("mode")

    rounding = 0
    for name in ("hyprland.lua", "hyprland.conf"):
        if under(name) not in paths:
            continue
        found = ROUNDING_RE.search(fetch(name) or "")
        if found:
            rounding = int(found.group(1))
            break

    icon_theme = ""
    if under("icons.theme") in paths:
        text = (fetch("icons.theme") or "").strip().splitlines()
        icon_theme = text[0].strip() if text else ""

    backgrounds = [
        blob_url(owner, repo, branch, path)
        for path in sorted(paths)
        if path.startswith(prefix + "backgrounds/")
        and "/" not in path[len(prefix) + len("backgrounds/") :]
        and os.path.splitext(path)[1].lower() in IMAGE_EXT
    ]

    return {
        "slug": slug,
        "name": listing["name"],
        "source": "extra",
        "mode": mode,
        "rounding": rounding,
        "iconTheme": icon_theme,
        "folderColor": FOLDER_COLORS.get(icon_theme, colors["accent"]),
        "colors": colors,
        "backgrounds": backgrounds,
        "repo": listing["repo"],
        "branch": branch,
        "preview": listing["preview"],
        "description": (meta.get("description") or "").strip(),
        "stars": meta.get("stargazers_count", 0),
        "updated": meta.get("pushed_at") or "",
        "install": "omarchy theme install %s" % listing["repo"],
    }


# --- main ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--refresh", action="store_true", help="ignore the cache and refetch everything"
    )
    parser.add_argument("--no-cache", action="store_true", help="do not read or write a cache")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--limit", type=int, default=0, help="only build the first N themes")
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero if any theme failed to build"
    )
    args = parser.parse_args()

    token = github_token()
    if not token:
        print(
            "warning: no GitHub token (GITHUB_TOKEN, GH_TOKEN or `gh auth login`).\n"
            "         The tree API allows 60 requests/hour unauthenticated, which is\n"
            "         not enough for the full list. Expect rate-limit waits.",
            file=sys.stderr,
        )

    http = Http(None if args.no_cache else args.cache_dir, args.refresh, token)

    listings = listed_themes(http)
    if args.limit:
        listings = listings[: args.limit]
    print("%d themes listed in the manual" % len(listings), file=sys.stderr)

    themes = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as pool:
        futures = {pool.submit(build_theme, http, item): item for item in listings}
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            try:
                themes.append(future.result())
            except Exception as ex:  # one bad repo must not lose the other 116
                failures.append((item["name"], item["repo"], str(ex)))

    themes.sort(key=lambda t: t["slug"])

    # Two themes can install to the same slug; the page keys on it, so say so.
    seen = {}
    for theme in themes:
        seen.setdefault(theme["slug"], []).append(theme["name"])
    for slug, names in seen.items():
        if len(names) > 1:
            print("  collision: %s <- %s" % (slug, ", ".join(names)), file=sys.stderr)

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": EXTRA_THEMES_URL,
        "count": len(themes),
        "themes": themes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")

    no_bg = [t["slug"] for t in themes if not t["backgrounds"]]
    print(
        "wrote %s: %d themes, %d cache hits, %d fetched"
        % (args.output, len(themes), http.hits, http.misses),
        file=sys.stderr,
    )
    if no_bg:
        print("  no backgrounds: %s" % ", ".join(no_bg), file=sys.stderr)
    if failures:
        print("  %d failed:" % len(failures), file=sys.stderr)
        for name, repo, error in failures:
            print("    %-24s %s (%s)" % (name, error, repo), file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
