# Themes Explorer

An Omarchy bar widget that answers the question every theme switch asks: *what
will this actually look like?*

Clicking it opens a fullscreen simulated desktop — btop, fastfetch, `eza -l`,
Nautilus, LazyVim, Neovim, VS Code, the Omarchy menu and the bar itself — all
repainted live from a theme's real `colors.toml`. Arrow through your installed
themes, and apply the one you want without leaving the page.

![Themes Explorer](docs/screenshot.png)

## Install

```bash
omarchy plugin add https://github.com/mythz/omarchy-themes-explorer.git --enable
```

Pick the **right** bar section when prompted. Nothing is written outside
`~/.config/omarchy/plugins/mythz.themes-explorer` — the plugin is self-contained
and puts nothing on your `PATH`.

Remove it with `omarchy plugin remove mythz.themes-explorer`.

## Use

| | |
|---|---|
| Click the bar icon | Open, or hide it again |
| `←` `→` | Previous / next theme |
| Hover the theme name | Jump straight to any installed theme |
| `Enter` | Apply the theme you are looking at |
| Right-click a panel | Swap the app shown there |
| `Esc` or `✕` | Hide — returns to exactly the layout you left |
| `Super + W` | Quit the app entirely |
| `?` | Full key list |

Right-clicking the bar icon opens it in a normal browser tab instead, which is
handy for taking screenshots.

## How it works

Python's standard library serves the page and reads the themes; there are no
dependencies to install beyond what Omarchy already ships.

**Palettes.** Themes are read straight from `~/.config/omarchy/themes` and
`/usr/share/omarchy/themes`, and `colors.toml` is normalised across all three
dialects in the wild — named keys, `color0`–`color15`, and the older layout
where the palette only exists in `alacritty.toml`. Corner rounding is parsed out
of each theme's `hyprland.lua`/`.conf`, and the Nautilus folder tint is derived
from its `icons.theme`, so the preview matches what you would actually get.

**The window never touches your layout.** It opens on its own special
workspace, `special:themes-explorer` — a dedicated scratchpad, not Omarchy's
shared one on `Super+S`, so it never disturbs what you keep in that.

The placement is a **window rule applied when the window maps**, not a move
afterwards, and that distinction is the whole thing. Moving is too late: the
window has already mapped into your current workspace, dwindle has already
re-split your existing windows around it, and moving it out leaves those split
ratios disturbed — which is how a layout gets mangled in a way that is awkward
to undo by hand. With the rule the window is never a member of your workspace
at all, so there is nothing to reflow and nothing to restore.

The rule is registered from the launcher rather than written into
`~/.config/hypr`, so **your Hyprland config is never edited**. Omarchy runs the
Lua config provider, whose `o.window` helper is reachable from `hyprctl eval`;
there is a `hyprctl keyword windowrulev2` fallback for a `.conf` setup. Rules
registered this way last for the Hyprland run and are dropped on a config
reload — and applying a theme reloads the config — so the launcher re-registers
immediately before every launch instead of trusting an earlier one to have
survived. If the rule somehow does not take, the launcher falls back to moving
the window, and says so in a comment: that path reflows the workspace, so it is
the safety net, never the plan.

Hiding keeps the window alive, so the theme you were looking at and your panel
arrangement survive a round trip.

Verified on a live desktop with 13 windows across four workspaces: cold launch,
hide, show and hide again left every window's workspace, position, size and
floating state byte-identical, and the active workspace unchanged.

**Typography.** Font sizes are fixed rather than scaled, because that is how the
real apps behave regardless of window size. Narrow panels drop content instead
of shrinking it — btop hides its process table, `eza` drops the date column,
fastfetch stacks its logo above the specs.

## Running it standalone

The launcher works without the bar widget:

```bash
~/.config/omarchy/plugins/mythz.themes-explorer/bin/omarchy-themes-explorer --tab
```

`--hide` toggles the scratchpad, `--stop` shuts the server down, `--port N`
moves it off 8777.

## Layout

```
manifest.json                  Omarchy plugin manifest
BarWidget.qml                  the bar button
bin/omarchy-themes-explorer    launcher: server lifecycle + window placement
app/server.py                  static files, theme discovery, apply/hide
app/index.html app/app.css     the page
app/app.js                     theme navigation, panel swapping, persistence
app/apps.js                    the simulated apps
app/icons.js                   Adwaita icon geometry
app/tools/build-icons.py       regenerates icons.js from /usr/share/icons
```

## License

MIT
