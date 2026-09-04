/* Wires the simulated desktop to the installed themes: arrow keys walk the
   list, right click swaps an app into a panel, Enter hands the theme to
   `omarchy theme set`. */

(function () {
  "use strict";

  const { SMALL, LARGE, renderBar } = window.OmarchyApps;

  const SLOTS = {
    "left-top": "small",
    "left-bottom": "small",
    "right-top": "small",
    "right-bottom": "small",
    center: "large",
  };

  const DEFAULT_LAYOUT = {
    "left-top": "logo",
    "left-bottom": "btop",
    center: "nvim",
    "right-top": "fastfetch",
    "right-bottom": "ls",
  };

  /* palette key -> css custom property */
  const VARS = {
    background: "--bg",
    dark_background: "--bg-dark",
    darker_background: "--bg-darker",
    lighter_background: "--lighter-bg",
    foreground: "--fg",
    dark_foreground: "--fg-dark",
    light_foreground: "--fg-light",
    bright_foreground: "--fg-bright",
    accent: "--accent",
    selection: "--sel",
    muted: "--muted",
    red: "--red",
    green: "--green",
    yellow: "--yellow",
    blue: "--blue",
    magenta: "--magenta",
    cyan: "--cyan",
    orange: "--orange",
    brown: "--brown",
    black: "--black",
    white: "--white",
    bright_red: "--br-red",
    bright_green: "--br-green",
    bright_yellow: "--br-yellow",
    bright_blue: "--br-blue",
    bright_magenta: "--br-magenta",
    bright_cyan: "--br-cyan",
  };

  const STORE_KEY = "omarchy-themes-explorer";

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const panels = Array.from(document.querySelectorAll(".panel"));

  const state = {
    themes: [],
    metrics: { rounding: 0, border: 2 },
    /* Community themes from extra-themes.json that are not installed here.
       Everything below treats the two lists identically -- `list` says which
       one `index` is walking -- because an extra theme carries exactly the
       fields an installed one does. The only thing it cannot do is be applied,
       so the apply button offers to install it instead. */
    extra: [],
    list: "installed",
    index: 0,
    current: "",
    layout: Object.assign({}, DEFAULT_LAYOUT),
    focus: "center",
    bgIndex: {},
  };

  function appsFor(slot) {
    return SLOTS[slot] === "large" ? LARGE : SMALL;
  }

  function findApp(slot, id) {
    const list = appsFor(slot);
    return list.find((a) => a.id === id) || list[0];
  }

  /* ── persistence ─────────────────────────────────────────────────── */

  /* ?left-top=nautilus&center=vscode&theme=nord — handy for screenshots and
     for pinning a particular arrangement in a bookmark. */
  function applyQuery() {
    const q = new URLSearchParams(location.search);
    Object.keys(SLOTS).forEach((slot) => {
      const want = q.get(slot);
      if (want && findApp(slot, want).id === want) state.layout[slot] = want;
    });
    if (q.get("focus") && SLOTS[q.get("focus")]) state.focus = q.get("focus");
    if (q.get("theme")) state.wantTheme = q.get("theme");
  }

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      if (saved.layout) {
        Object.keys(SLOTS).forEach((slot) => {
          if (saved.layout[slot] && findApp(slot, saved.layout[slot]).id === saved.layout[slot]) {
            state.layout[slot] = saved.layout[slot];
          }
        });
      }
      if (saved.focus && SLOTS[saved.focus]) state.focus = saved.focus;
      if (saved.theme) state.wantTheme = saved.theme;
    } catch (e) {
      /* first run, or storage disabled — defaults are fine */
    }
  }

  function save() {
    try {
      localStorage.setItem(
        STORE_KEY,
        JSON.stringify({
          layout: state.layout,
          focus: state.focus,
          theme: (theme() || {}).slug,
        })
      );
    } catch (e) {
      /* non-fatal */
    }
  }

  /* ── rendering ───────────────────────────────────────────────────── */

  function activeList() {
    return state.list === "extra" ? state.extra : state.themes;
  }

  function theme() {
    return activeList()[state.index];
  }

  function isExtra() {
    return state.list === "extra";
  }

  /* An installed theme's wallpaper is a local file and paints at once. An extra
     theme's is on GitHub and can be megabytes, so the server's cached thumbnail
     goes up first and the original replaces it when it arrives. Both are raced
     rather than chained: whichever answers first shows, and the token means a
     theme you have already arrowed past cannot paint over the one you are on. */
  let wallpaperToken = 0;

  function showWallpaper(slug, index, url) {
    const el = $("wallpaper");
    const token = ++wallpaperToken;
    let full = false;

    const original = new Image();
    original.onload = function () {
      full = true;
      if (token === wallpaperToken) el.style.backgroundImage = 'url("' + url + '")';
    };
    original.src = url;

    /* Already decoded -- a theme you have seen before, or a local file the
       browser still holds. Paint it without ever clearing, so arrowing back
       and forth does not flash. */
    if (original.complete) {
      el.style.backgroundImage = 'url("' + url + '")';
      return;
    }

    /* An installed theme's wallpaper is a local file and lands in milliseconds,
       so it is left to arrive over whatever is on screen -- clearing first only
       buys a blank flash between two pictures that are both about to be right.
       A remote one is a different matter: seconds, sometimes megabytes. */
    if (!/^https?:/i.test(url)) return;

    /* Drop the outgoing theme's wallpaper immediately, or the desktop spends
       the download wearing one theme's colours and another's picture. The
       element's own background is the theme's darkest shade, which is what
       shows through. */
    el.style.backgroundImage = "none";

    const thumb = new Image();
    thumb.onload = function () {
      /* Never over the real thing, which may already have landed. */
      if (token === wallpaperToken && !full) {
        el.style.backgroundImage = 'url("' + thumb.src + '")';
      }
    };
    thumb.src =
      "/api/extra-background?theme=" + encodeURIComponent(slug) + "&index=" + index;
    if (thumb.complete && !full && token === wallpaperToken) {
      el.style.backgroundImage = 'url("' + thumb.src + '")';
    }
  }

  function paint() {
    const t = theme();
    if (!t) return;

    const root = document.documentElement.style;
    Object.keys(VARS).forEach((key) => {
      if (t.colors[key]) root.setProperty(VARS[key], t.colors[key]);
    });
    /* Window borders come from the theme's own Hyprland config when it sets
       them -- omacon's are #f200f3 and #4a2e4a, neither of which is derivable
       from the ANSI palette -- and fall back to the palette otherwise. */
    const borders = t.borders || {};
    root.setProperty("--panel-border", borders.inactive || t.colors.muted);
    root.setProperty("--panel-border-active", borders.active || t.colors.accent);

    /* Same for btop: a theme ships its whole btop palette, and btop picks box
       borders and meter gradients independently of the terminal colours. Each
       falls back to what the preview used to derive. */
    const bt = t.btop || {};
    const BTOP_VARS = {
      "--bt-title": bt.title || t.colors.accent,
      "--bt-hi": bt.hi_fg || t.colors.accent,
      "--bt-dim": bt.inactive_fg || t.colors.dark_foreground,
      "--bt-div": bt.div_line || t.colors.muted,
      "--bt-cpu-box": bt.cpu_box || t.colors.muted,
      "--bt-mem-box": bt.mem_box || t.colors.muted,
      "--bt-net-box": bt.net_box || t.colors.muted,
      "--bt-proc-box": bt.proc_box || t.colors.muted,
      "--bt-graph": bt.cpu_mid || t.colors.accent,
      "--bt-graph-alt": bt.cpu_start || t.colors.cyan,
      "--bt-meter-start": bt.cpu_start || t.colors.green,
      "--bt-meter-mid": bt.cpu_mid || t.colors.yellow,
      "--bt-meter-end": bt.cpu_end || t.colors.red,
      "--bt-temp": bt.temp_start || t.colors.green,
      "--bt-key": bt.proc_misc || t.colors.yellow,
      "--bt-down": bt.download_mid || t.colors.green,
      "--bt-up": bt.upload_mid || t.colors.magenta,
      "--bt-sel-bg": bt.selected_bg || t.colors.selection,
      "--bt-sel-fg": bt.selected_fg || t.colors.bright_foreground,
      "--bt-meter-bg": bt.meter_bg || t.colors.muted,
    };
    Object.keys(BTOP_VARS).forEach((key) => root.setProperty(key, BTOP_VARS[key]));

    /* VS Code's token colours come from the theme's tokenColors -- or from the
       mapping Omarchy's template would have rendered -- rather than from the
       ANSI palette, which cannot tell an import keyword from a plain one. */
    const sx = t.syntax || {};
    Object.keys(sx).forEach((key) => {
      if (typeof sx[key] === "string") root.setProperty("--vs-" + key, sx[key]);
    });

    /* fastfetch draws its logo in ANSI green -- `"color": {"1": "green"}` in
       Omarchy's fastfetch config -- which is why omacon's mark is violet on
       the real desktop and not the magenta accent. */
    root.setProperty("--logo-ink", t.colors.green || t.colors.accent);
    /* Neovim's Visual and Comment are the colorscheme's, not the terminal's:
       a theme's `selection_background` is a terminal colour and using it paints
       the selected block in whatever the terminal highlights with -- a light
       pink, under omacon. Both are derived against the background instead. */
    root.setProperty(
      "--nv-visual",
      "color-mix(in srgb, " + t.colors.blue + " 20%, " + t.colors.darker_background + ")"
    );
    root.setProperty(
      "--nv-comment",
      "color-mix(in srgb, " + t.colors.muted + " 55%, " + t.colors.background + ")"
    );
    root.setProperty("--folder", t.folderColor || t.colors.accent);
    /* Rounding and border width belong to Omarchy, not to the theme -- every
       theme's staged hyprland.lua only carries border colours -- so they are
       one value for the whole list.

       The border is matched in *device* pixels, because that is what Hyprland
       draws: measured off a screenshot at scale 1.25, a border_size of 2 comes
       out 2 device pixels wide, not 2.5. A flat 2px of CSS is 2.5 device pixels
       at that scale, which is the panel edge reading a pixel heavier than every
       real window beside it. */
    root.setProperty("--radius", (state.metrics.rounding || 0) / 19.2 + "vw");
    root.setProperty(
      "--border-w",
      (state.metrics.border || 0) / (window.devicePixelRatio || 1) + "px"
    );
    document.body.dataset.mode = t.mode;

    const backgrounds = t.backgrounds;
    if (backgrounds.length) {
      const i = (state.bgIndex[t.slug] || 0) % backgrounds.length;
      showWallpaper(t.slug, i, backgrounds[i]);
    } else {
      wallpaperToken++;
      $("wallpaper").style.backgroundImage = "none";
    }

    $("bar").innerHTML = renderBar(t);

    panels.forEach((panel) => {
      const slot = panel.dataset.slot;
      const app = findApp(slot, state.layout[slot]);
      panel.dataset.app = app.id;
      panel.innerHTML = app.render(t);
      panel.classList.toggle("is-empty", app.id === "none");
      panel.classList.toggle("is-focused", slot === state.focus && app.id !== "none");
    });

    $("themeName").textContent = t.name;
    $("themeMeta").textContent =
      t.mode + " · " + t.source + " · " + (state.index + 1) + "/" + activeList().length;

    $("swatches").innerHTML = ["accent", "red", "yellow", "green", "cyan", "blue", "magenta"]
      .map((k) => '<i style="background:' + t.colors[k] + '"></i>')
      .join("");

    markPicker();

    const isCurrent = !isExtra() && t.slug === state.current;
    const apply = $("apply");
    apply.textContent = isExtra()
      ? "Install theme"
      : isCurrent
      ? "✓ Current theme"
      : "Set as current theme";
    apply.classList.toggle("is-current", isCurrent);
    $("cycleBg").disabled = backgrounds.length < 2;

    document.title = t.name + " — Omarchy Themes Explorer";
  }

  function go(delta) {
    const n = activeList().length;
    if (!n) return;
    state.index = (((state.index + delta) % n) + n) % n;
    paint();
    save();
  }

  function jump(list, index) {
    state.list = list;
    state.index = Math.max(0, Math.min(activeList().length - 1, index));
    paint();
    save();
  }

  /* ── theme picker ────────────────────────────────────────────────── */

  const SWATCHES = ["accent", "red", "yellow", "green", "cyan", "blue", "magenta"];

  /* Marks a light theme in the list. The palette swatches alone do not say it:
     plenty of dark themes are pale and a couple of light ones are muted. */
  const SUN =
    '<svg class="picker-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
    /* Filled core, stroked rays: at 12px an outlined circle closes up into a
       smudge, while a solid dot still reads as the middle of a sun. */
    '<circle cx="12" cy="12" r="3.6" fill="currentColor" stroke="none"/>' +
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4' +
    'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

  function rowsFor(themes, list) {
    return themes
      .map(
        (t, i) =>
          '<div class="picker-item" data-list="' + list + '" data-index="' + i +
          '" title="' + esc(t.name) + (t.mode === "light" ? " (light)" : "") + '">' +
          '<span class="picker-dots">' +
          SWATCHES.map((k) => '<i style="background:' + t.colors[k] + '"></i>').join("") +
          "</span>" +
          '<span class="picker-name">' + esc(t.name) + "</span>" +
          (t.mode === "light" ? SUN : "") +
          '<span class="picker-tag"></span>' +
          "</div>"
      )
      .join("");
  }

  function buildPicker() {
    $("pickerList").innerHTML = rowsFor(state.themes, "installed");
    $("extraList").innerHTML = rowsFor(state.extra, "extra");
    $("extraCol").hidden = !state.extra.length;
    $("extraHead").textContent = "Extra themes · " + state.extra.length;
  }

  function markList(el, themes, list) {
    const rows = el.children;
    for (let i = 0; i < rows.length; i++) {
      const isCurrent = list === "installed" && themes[i].slug === state.current;
      rows[i].classList.toggle("on", list === state.list && i === state.index);
      rows[i].classList.toggle("current", isCurrent);
      /* By class, not lastElementChild: a light theme's row ends with the sun. */
      rows[i].querySelector(".picker-tag").textContent = isCurrent ? "current" : "";
    }
  }

  function markPicker() {
    markList($("pickerList"), state.themes, "installed");
    markList($("extraList"), state.extra, "extra");
  }

  $("picker").addEventListener("click", (e) => {
    const row = e.target.closest(".picker-item");
    if (row) jump(row.dataset.list, +row.dataset.index);
  });

  /* The lists open from the theme name or the palette beside it, and close on a
     timer so that crossing the gap between them -- or the seam between the two
     lists -- does not shut them. Any of the regions cancels a pending close. */
  const HOVER_GRACE = 260;
  let closeTimer;

  function openPicker() {
    clearTimeout(closeTimer);
    if ($("themeWrap").classList.contains("is-open")) return;
    $("themeWrap").classList.add("is-open");
    const row = $("picker").querySelector(".picker-item.on");
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function closePickerSoon() {
    clearTimeout(closeTimer);
    closeTimer = setTimeout(() => $("themeWrap").classList.remove("is-open"), HOVER_GRACE);
  }

  [$("themeWrap"), $("swatches"), $("picker")].forEach((el) => {
    el.addEventListener("mouseenter", openPicker);
    el.addEventListener("mouseleave", closePickerSoon);
  });

  /* ── toast ───────────────────────────────────────────────────────── */

  let toastTimer;
  function toast(message, bad) {
    const el = $("toast");
    el.textContent = message;
    el.classList.toggle("bad", !!bad);
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  }

  /* ── context menu ────────────────────────────────────────────────── */

  const menu = $("menu");
  let menuSlot = null;

  function openMenu(slot, x, y) {
    menuSlot = slot;
    $("menuTitle").textContent =
      SLOTS[slot] === "large" ? "Main window" : "Panel — " + slot.replace("-", " ");

    const active = state.layout[slot];
    $("menuItems").innerHTML = appsFor(slot)
      .map(
        (app) =>
          '<div class="menu-item' + (app.id === active ? " on" : "") + '" data-app="' +
          app.id + '"><span class="glyph">' + app.glyph + "</span>" + app.label +
          (app.id === active ? '<span class="tick">✓</span>' : "") + "</div>"
      )
      .join("");

    menu.hidden = false;
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, window.innerWidth - rect.width - 8) + "px";
    menu.style.top = Math.min(y, window.innerHeight - rect.height - 8) + "px";
    document.querySelector('[data-slot="' + slot + '"]').classList.add("is-target");
  }

  function closeMenu() {
    menu.hidden = true;
    menuSlot = null;
    panels.forEach((p) => p.classList.remove("is-target"));
  }

  panels.forEach((panel) => {
    panel.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openMenu(panel.dataset.slot, e.clientX, e.clientY);
    });
    panel.addEventListener("click", () => {
      if (state.layout[panel.dataset.slot] === "none") return;
      state.focus = panel.dataset.slot;
      paint();
      save();
    });
  });

  menu.addEventListener("click", (e) => {
    const item = e.target.closest(".menu-item");
    if (!item || !menuSlot) return;
    state.layout[menuSlot] = item.dataset.app;
    if (item.dataset.app === "none" && state.focus === menuSlot) state.focus = "center";
    closeMenu();
    paint();
    save();
  });

  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target)) closeMenu();
  });
  document.addEventListener("contextmenu", (e) => {
    if (!e.target.closest(".panel")) e.preventDefault();
  });

  /* ── controls ────────────────────────────────────────────────────── */

  $("prev").addEventListener("click", () => go(-1));
  $("next").addEventListener("click", () => go(1));
  $("help").addEventListener("click", () => ($("shortcuts").hidden = !$("shortcuts").hidden));

  $("cycleBg").addEventListener("click", () => {
    const t = theme();
    if (!t || t.backgrounds.length < 2) return;
    state.bgIndex[t.slug] = ((state.bgIndex[t.slug] || 0) + 1) % t.backgrounds.length;
    paint();
  });

  /* `omarchy theme install` clones the repo and then applies it, so a
     successful install leaves the theme both installed and current. Rebuild
     both lists from the server's answer and follow the theme across: it has
     just moved out of the extra column and into the installed one. */
  async function installTheme() {
    const t = theme();
    if (!t) return;
    const button = $("apply");
    button.disabled = true;
    button.textContent = "Installing…";
    try {
      const res = await fetch("/api/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: t.slug }),
      });
      const data = await res.json();
      if (data.ok) {
        state.themes = data.themes || state.themes;
        state.extra = state.extra.filter((x) => x.slug !== t.slug);
        state.current = data.current || t.slug;
        const at = state.themes.findIndex((x) => x.slug === t.slug);
        state.list = "installed";
        state.index = at === -1 ? state.index : at;
        buildPicker();
        toast(t.name + " installed and applied");
      } else {
        toast(data.error || "omarchy theme install failed", true);
      }
    } catch (err) {
      toast("Could not reach the preview server", true);
    } finally {
      button.disabled = false;
      paint();
      save();
    }
  }

  async function applyTheme() {
    const t = theme();
    if (!t) return;
    if (isExtra()) return installTheme();
    const button = $("apply");
    button.disabled = true;
    button.textContent = "Applying…";
    try {
      const res = await fetch("/api/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: t.slug }),
      });
      const data = await res.json();
      if (data.ok) {
        state.current = data.current || t.slug;
        toast(t.name + " is now your theme");
      } else {
        toast(data.error || "omarchy theme set failed", true);
      }
    } catch (err) {
      toast("Could not reach the preview server", true);
    } finally {
      button.disabled = false;
      paint();
    }
  }

  $("apply").addEventListener("click", applyTheme);

  /* Hides the window rather than closing it, so the next open comes back to
     the theme and layout you left. */
  function hideApp() {
    fetch("/api/hide", { method: "POST" }).catch(() => {});
  }
  $("close").addEventListener("click", hideApp);

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case "ArrowLeft": go(-1); break;
      case "ArrowRight": go(1); break;
      case "Home": jump(state.list, 0); break;
      case "End": jump(state.list, activeList().length - 1); break;
      case "Enter": applyTheme(); break;
      case "b": case "B": $("cycleBg").click(); break;
      case "h": case "H": $("hud").classList.toggle("hidden"); break;
      case "?": $("shortcuts").hidden = !$("shortcuts").hidden; break;
      case "Escape":
        /* Escape peels one layer at a time, dismissing the app only once
           nothing is open on top of it. */
        if (!menu.hidden) closeMenu();
        else if (!$("shortcuts").hidden) $("shortcuts").hidden = true;
        else hideApp();
        break;
      default: return;
    }
    e.preventDefault();
  });

  /* ── boot ────────────────────────────────────────────────────────── */

  load();
  applyQuery();

  fetch("/api/themes")
    .then((r) => r.json())
    .then((data) => {
      state.themes = data.themes;
      state.extra = data.extra || [];
      state.metrics = data.metrics || state.metrics;
      state.current = data.current;
      buildPicker();
      const wanted = state.wantTheme || data.current;
      let at = state.themes.findIndex((t) => t.slug === wanted);
      if (at === -1) {
        /* The remembered theme may be one of the extras. */
        const other = state.extra.findIndex((t) => t.slug === wanted);
        if (other !== -1) state.list = "extra";
        at = other;
      }
      state.index = at === -1 ? 0 : at;
      paint();
    })
    .catch(() => toast("Could not load installed themes", true));
})();
