#!/usr/bin/env python3
"""Build extra-themes.json: every community theme listed in the Omarchy manual,
described well enough for the preview page to render it without installing it.

The page already knows how to draw a theme from the shape `/api/themes` returns,
so this produces that same shape -- slug, mode, rounding, iconTheme, folderColor,
colors -- for themes that live in someone else's git repo instead of on disk. The
colour maths is imported from server.py rather than reimplemented, so an extra
theme and an installed one are folded through identical code and cannot drift.

Each repo is read with one blobless partial clone:

    git clone --filter=blob:limit=64k --no-checkout --depth=1 --single-branch

which is ~150KB and one round trip per theme. It names the default branch (which
is not always `main`), lists every file, and brings down the config files small
enough to matter while leaving the wallpapers on GitHub -- where they stay: the
backgrounds in the output are URLs, so this file is ~250KB and the plugin can
refresh it on every launch. Downloading each repo's zip would be the same idea
at ~20MB a theme, and its root directory is named `-HEAD`, so it would not even
answer the branch question.

No GitHub token is needed. If one happens to be around (GITHUB_TOKEN, GH_TOKEN,
or a logged-in `gh`) each theme is also annotated with its repo description,
star count and last push; without one those fields are simply left out rather
than spending the 60/hour anonymous API budget.

Usage:
    scripts/build-extra-themes.py                 # write extra-themes.json
    scripts/build-extra-themes.py --refresh       # re-clone everything
    scripts/build-extra-themes.py -o /tmp/x.json  # somewhere else
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
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
# it is being less polite about it), so say who we are. This is the same thing
# curl does; nothing here depends on being mistaken for a browser.
USER_AGENT = "omarchy-themes-explorer-build/1.0 (+https://github.com/mythz/omarchy-themes-explorer)"

# A theme repo is a directory holding one of these next to the rest of the
# config. Most are the repo root; a few vendor their theme a level down.
COLOR_FILES = ("colors.toml", "alacritty.toml")
MAX_WORKERS = 8


# --- http ---------------------------------------------------------------


class Http:
    """Small cached fetcher for the manual page and the optional API lookups."""

    def __init__(self, cache_dir, refresh=False, token=""):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.token = token
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url):
        if not self.cache_dir:
            return None
        return self.cache_dir / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url, api=False, optional=False):
        """Return bytes, or None when `optional` and the resource is absent."""
        path = self._cache_path(url)
        if path and not self.refresh and path.is_file():
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
                # A spent API budget answers 403 with the time it refills at.
                # Honour it, but never sleep longer than a coffee.
                if ex.code in (403, 429):
                    reset = ex.headers.get("X-RateLimit-Reset")
                    if ex.headers.get("X-RateLimit-Remaining") == "0" and reset:
                        wait = min(300, max(1, int(reset) - int(time.time()) + 2))
                        print("rate limited, waiting %ds" % wait, file=sys.stderr)
                        time.sleep(wait)
                        continue
                    raise
                if ex.code < 500:
                    raise
                time.sleep(2**attempt)
            except (urllib.error.URLError, OSError) as ex:
                last = ex
                time.sleep(2**attempt)
        else:
            raise RuntimeError("GET %s failed: %s" % (url, last))

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
        done = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if done.returncode == 0:
            return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


# --- git ----------------------------------------------------------------


# Never let git stop to ask for credentials: a repo that has been made private
# would otherwise hang the whole build on a password prompt no one is watching.
GIT_ENV = dict(
    os.environ,
    GIT_TERMINAL_PROMPT="0",
    GIT_ASKPASS="",
    GIT_CONFIG_NOSYSTEM="1",
    GCM_INTERACTIVE="never",
)


def git(args, cwd=None, timeout=180, check=True):
    done = subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise RuntimeError(lines[-1].strip() if lines else "git %s failed" % args[0])
    return done


class Clone:
    """A blobless, checkout-less, single-commit clone of one theme repo.

    Everything the build needs is answered locally from it: the default branch
    name, the file list, and the contents of the config files. Wallpapers are
    over the 64k filter, so they are never transferred -- they stay URLs.
    """

    def __init__(self, path):
        self.path = path
        self.branch = git(["symbolic-ref", "--short", "HEAD"], cwd=path).stdout.strip() or "HEAD"
        listing = git(["ls-tree", "-r", "--name-only", "HEAD"], cwd=path).stdout
        self.files = [line for line in listing.splitlines() if line]

    @classmethod
    def fetch(cls, url, into, refresh=False):
        if refresh and into.exists():
            shutil.rmtree(into)
        if not into.exists():
            into.parent.mkdir(parents=True, exist_ok=True)
            tmp = into.with_name(into.name + ".tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            # `--` so a URL can never be read as an option, matching the care
            # omarchy-theme-install takes with the same kind of input.
            git(
                [
                    "clone",
                    "--quiet",
                    "--filter=blob:limit=64k",
                    "--no-checkout",
                    "--depth=1",
                    "--single-branch",
                    "--",
                    url,
                    str(tmp),
                ],
                timeout=300,
            )
            tmp.rename(into)
        return cls(into)

    def read(self, path):
        """File contents, or None if it is not in the tree."""
        if path not in self.files:
            return None
        done = git(["cat-file", "-p", "HEAD:" + path], cwd=self.path, check=False)
        return done.stdout if done.returncode == 0 else None


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


def owner_repo(repo_url):
    parts = urllib.parse.urlparse(repo_url).path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("not a repo url: " + repo_url)
    owner, name = parts[0], parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    if not re.fullmatch(r"[\w.-]+", owner) or not re.fullmatch(r"[\w.-]+", name):
        raise ValueError("suspicious repo url: " + repo_url)
    return owner, name


# --- one theme ----------------------------------------------------------


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
    return "https://github.com/%s/%s/blob/%s/%s?raw=true" % (
        owner,
        repo,
        urllib.parse.quote(branch),
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
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]?(#?(?:0x)?[0-9a-fA-F]{3,8})", line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def build_theme(listing, cache_dir, refresh, http=None):
    owner, repo = owner_repo(listing["repo"])
    slug = slug_for(listing["repo"])
    if not slug:
        raise ValueError("repo name does not give a usable theme slug")

    clone = Clone.fetch(
        listing["repo"], cache_dir / "repos" / ("%s__%s" % (owner, repo)), refresh
    )
    if not clone.files:
        raise ValueError("repo is empty")

    root = theme_root(clone.files)
    prefix = root + "/" if root else ""

    # colors.toml when it exists, alacritty.toml the way server.py falls back.
    raw = {}
    text = clone.read(prefix + "colors.toml")
    if text:
        raw = parse_colors_toml(text)
    if not raw:
        text = clone.read(prefix + "alacritty.toml")
        if text:
            import tomllib

            try:
                raw = flatten_alacritty(tomllib.loads(text))
            except (tomllib.TOMLDecodeError, ValueError):
                raw = {}
    if not raw:
        raise ValueError("no usable colors.toml or alacritty.toml")

    colors = normalize(raw)
    mode = colors.pop("mode")

    rounding = 0
    for name in ("hyprland.lua", "hyprland.conf"):
        text = clone.read(prefix + name)
        if text:
            found = ROUNDING_RE.search(text)
            if found:
                rounding = int(found.group(1))
                break

    icon_theme = ""
    text = clone.read(prefix + "icons.theme")
    if text:
        lines = text.strip().splitlines()
        icon_theme = lines[0].strip() if lines else ""

    bg_prefix = prefix + "backgrounds/"
    backgrounds = [
        blob_url(owner, repo, clone.branch, path)
        for path in sorted(clone.files)
        if path.startswith(bg_prefix)
        and "/" not in path[len(bg_prefix) :]
        and os.path.splitext(path)[1].lower() in IMAGE_EXT
    ]

    theme = {
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
        "branch": clone.branch,
        "preview": listing["preview"],
        "install": "omarchy theme install %s" % listing["repo"],
    }

    # Nice to have, never required: only asked for when a token makes it free.
    if http is not None:
        try:
            meta = http.json("%s/repos/%s/%s" % (GITHUB_API, owner, repo), optional=True) or {}
            theme["description"] = (meta.get("description") or "").strip()
            theme["stars"] = meta.get("stargazers_count", 0)
            theme["updated"] = meta.get("pushed_at") or ""
        except Exception:
            pass

    return theme


# --- main ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--refresh", action="store_true", help="re-clone every repo and refetch the manual"
    )
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--limit", type=int, default=0, help="only build the first N themes")
    parser.add_argument(
        "--no-metadata", action="store_true", help="skip the API lookups even if a token exists"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero if any theme failed to build"
    )
    args = parser.parse_args()

    token = "" if args.no_metadata else github_token()
    http = Http(args.cache_dir, args.refresh, token)
    meta_http = http if token else None
    if not token and not args.no_metadata:
        print(
            "no GitHub token: skipping repo descriptions and stars "
            "(set GITHUB_TOKEN or run `gh auth login` to include them)",
            file=sys.stderr,
        )

    listings = listed_themes(http)
    if args.limit:
        listings = listings[: args.limit]
    print("%d themes listed in the manual" % len(listings), file=sys.stderr)

    themes = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as pool:
        futures = {
            pool.submit(build_theme, item, args.cache_dir, args.refresh, meta_http): item
            for item in listings
        }
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
    print("wrote %s: %d themes" % (args.output, len(themes)), file=sys.stderr)
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
