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
          theme: (state.themes[state.index] || {}).slug,
        })
      );
    } catch (e) {
      /* non-fatal */
    }
  }

  /* ── rendering ───────────────────────────────────────────────────── */

  function theme() {
    return state.themes[state.index];
  }

  function paint() {
    const t = theme();
    if (!t) return;

    const root = document.documentElement.style;
    Object.keys(VARS).forEach((key) => {
      if (t.colors[key]) root.setProperty(VARS[key], t.colors[key]);
    });
    root.setProperty("--panel-border", t.colors.muted);
    root.setProperty("--folder", t.folderColor || t.colors.accent);
    /* Hyprland rounding is in logical px against a 1920-wide screen; the
       preview's viewport stands in for that screen, so scale it the same way. */
    root.setProperty("--radius", (t.rounding || 0) / 19.2 + "vw");
    document.body.dataset.mode = t.mode;

    const backgrounds = t.backgrounds;
    if (backgrounds.length) {
      const i = (state.bgIndex[t.slug] || 0) % backgrounds.length;
      $("wallpaper").style.backgroundImage = 'url("' + backgrounds[i] + '")';
    } else {
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
      t.mode + " · " + t.source + " · " + (state.index + 1) + "/" + state.themes.length;

    $("swatches").innerHTML = ["accent", "red", "yellow", "green", "cyan", "blue", "magenta"]
      .map((k) => '<i style="background:' + t.colors[k] + '"></i>')
      .join("");

    markPicker();

    const isCurrent = t.slug === state.current;
    const apply = $("apply");
    apply.textContent = isCurrent ? "✓ Current theme" : "Set as current theme";
    apply.classList.toggle("is-current", isCurrent);
    $("cycleBg").disabled = backgrounds.length < 2;

    document.title = t.name + " — Omarchy Themes Explorer";
  }

  function go(delta) {
    if (!state.themes.length) return;
    const n = state.themes.length;
    state.index = (((state.index + delta) % n) + n) % n;
    paint();
    save();
  }

  function jump(index) {
    state.index = Math.max(0, Math.min(state.themes.length - 1, index));
    paint();
    save();
  }

  /* ── theme picker ────────────────────────────────────────────────── */

  const SWATCHES = ["accent", "red", "yellow", "green", "cyan", "blue", "magenta"];

  function buildPicker() {
    $("pickerList").innerHTML = state.themes
      .map(
        (t, i) =>
          '<div class="picker-item" data-index="' + i + '" title="' + esc(t.name) + '">' +
          '<span class="picker-dots">' +
          SWATCHES.map((k) => '<i style="background:' + t.colors[k] + '"></i>').join("") +
          "</span>" +
          '<span class="picker-name">' + esc(t.name) + "</span>" +
          '<span class="picker-tag"></span>' +
          "</div>"
      )
      .join("");
  }

  function markPicker() {
    const rows = $("pickerList").children;
    for (let i = 0; i < rows.length; i++) {
      const isCurrent = state.themes[i].slug === state.current;
      rows[i].classList.toggle("on", i === state.index);
      rows[i].classList.toggle("current", isCurrent);
      rows[i].lastElementChild.textContent = isCurrent ? "current" : "";
    }
  }

  $("pickerList").addEventListener("click", (e) => {
    const row = e.target.closest(".picker-item");
    if (row) jump(+row.dataset.index);
  });

  /* Bring the selected row into view whenever the list opens. */
  $("themeWrap").addEventListener("mouseenter", () => {
    const row = $("pickerList").querySelector(".picker-item.on");
    if (row) row.scrollIntoView({ block: "nearest" });
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

  async function applyTheme() {
    const t = theme();
    if (!t) return;
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
      case "Home": jump(0); break;
      case "End": jump(state.themes.length - 1); break;
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
      state.current = data.current;
      buildPicker();
      const wanted = state.wantTheme || data.current;
      const at = state.themes.findIndex((t) => t.slug === wanted);
      state.index = at === -1 ? 0 : at;
      paint();
    })
    .catch(() => toast("Could not load installed themes", true));
})();
