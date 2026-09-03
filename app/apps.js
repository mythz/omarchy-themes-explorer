/* Simulated applications. Each renderer returns the innerHTML for a panel and
   draws purely with CSS custom properties, so swapping the palette repaints
   every window at once. Content is deterministic — only the colours move. */

(function (global) {
  "use strict";

  const esc = (s) =>
    String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  const rep = (s, n) => (n > 0 ? s.repeat(n) : "");

  /* Deterministic noise so graphs look organic but never flicker between
     themes or re-renders. */
  function noise(seed) {
    let s = seed >>> 0;
    return function () {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }

  const SPARK = "▁▂▃▄▅▆▇█";

  function sparkline(count, seed, min, max) {
    const rnd = noise(seed);
    let wave = 0.5;
    let out = "";
    for (let i = 0; i < count; i++) {
      wave = Math.min(1, Math.max(0, wave + (rnd() - 0.5) * 0.42));
      const v = min + wave * (max - min);
      out += SPARK[Math.min(7, Math.max(0, Math.round(v * 7)))];
    }
    return out;
  }

  /* btop-style braille meter: filled cells recoloured as the value climbs. */
  /* btop colours a meter by position along its length, not by the value: a
     block near the right end is the gradient's end colour whatever the reading
     is. So the filled run carries a gradient spanning the whole meter and the
     empty run is painted flat -- see .gauge in app.css. */
  function gauge(pct, width) {
    const filled = Math.round((pct / 100) * width);
    return (
      '<span class="gauge"><i>' + rep("⣿", filled) + "</i>" +
      "<u>" + rep("⣀", width - filled) + "</u></span>"
    );
  }

  const pad = (s, n) => (String(s) + " ".repeat(n)).slice(0, n);
  const padL = (s, n) => (" ".repeat(n) + String(s)).slice(-n);

  const GLYPH = {
    home: "", folder: "", folderOpen: "", file: "",
    image: "", doc: "", download: "", music: "",
    video: "", picture: "", trash: "", search: "",
    gear: "", term: "", clock: "", disk: "",
    chip: "", display: "", bolt: "", refresh: "",
    power: "", bars: "", left: "", right: "",
    book: "", camera: "", brush: "", cloud: "",
    info: "", cogs: "", linux: "", git: "",
    code: "", pkg: "", db: "", star: "",
    files: "", plug: "", play: "", close: "",
    branch: "",
  };

  /* The status tray, matching what Omarchy's own bar shows on the right:
     bluetooth, network, volume, display. Inline SVG on currentColor rather
     than Nerd Font glyphs, so they keep their shape whatever font the theme
     leaves us with, and take the bar's dimmed foreground like the rest of it. */
  const TRAY_SVG = {
    bluetooth:
      '<svg class="tray-icon tray-bluetooth" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">' +
      '<path d="M10.28 2.22A.75.75 0 0 0 9 2.75v5.674L6.223 6.168a.75.75 0 1 0-.946 1.164' +
      'L8.561 10l-3.284 2.668a.75.75 0 0 0 .946 1.164L9 11.576v5.674a.75.75 0 0 0 1.28.53l4-4' +
      'a.75.75 0 0 0-.057-1.112L10.939 10l3.284-2.668a.75.75 0 0 0 .057-1.112zm.22 13.22v-3.864' +
      'l2.132 1.732zm2.132-8.748L10.5 8.424V4.561zM4 10a1 1 0 1 1-2 0a1 1 0 0 1 2 0m13 0' +
      'a1 1 0 1 1-2 0a1 1 0 0 1 2 0"/></svg>',
    network:
      '<svg class="tray-icon tray-network" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path d="M7 15h2v3h2v-3h2v3h2v-3h2v3h2V9h-4V6H9v3H5v9h2zM4.38 3h15.25A2.37 2.37 0 0 1 22 5.38' +
      'v14.25A2.37 2.37 0 0 1 19.63 22H4.38A2.37 2.37 0 0 1 2 19.63V5.38C2 4.06 3.06 3 4.38 3"/></svg>',
    speaker:
      '<svg class="tray-icon tray-speaker" viewBox="0 0 56 56" fill="currentColor" aria-hidden="true">' +
      '<path d="M48.16 48.934c.717.484 1.665.29 2.227-.503C53.929 43.359 56 36.836 56 29.926' +
      'S53.91 16.472 50.386 11.4c-.56-.794-1.51-.987-2.226-.484c-.735.503-.851 1.471-.29 2.284' +
      'c3.116 4.588 5.052 10.472 5.052 16.725c0 6.252-1.877 12.214-5.052 16.724c-.561.794-.445 1.761.29 2.284' +
      'M21.642 47.6c1.317 0 2.265-.968 2.265-2.265V14.459c0-1.297-.948-2.38-2.303-2.38c-.949 0-1.588.425-2.614 1.393' +
      'l-8.536 8.072a.76.76 0 0 1-.503.174H4.2c-2.729 0-4.2 1.49-4.2 4.394v7.51c0 2.904 1.471 4.395 4.2 4.395h5.75' +
      'a.76.76 0 0 1 .503.174l8.536 8.15c.93.87 1.704 1.258 2.652 1.258m18.719-3.95c.754.504 1.684.31 2.226-.464' +
      'c2.555-3.562 4.026-8.304 4.026-13.26c0-4.974-1.452-9.717-4.026-13.278c-.562-.755-1.472-.949-2.227-.446' +
      'c-.735.504-.851 1.452-.27 2.284c2.11 3.098 3.406 7.163 3.406 11.44c0 4.278-1.258 8.382-3.426 11.44' +
      'c-.542.833-.445 1.781.29 2.285m-7.724-5.226c.658.465 1.607.31 2.168-.445c1.51-2.032 2.42-5.013 2.42-8.053' +
      'c0-3.038-.93-6-2.42-8.071c-.561-.755-1.49-.91-2.168-.446c-.852.562-.949 1.549-.33 2.4c1.124 1.51 1.801 3.814 1.801 6.118' +
      'c0 2.303-.716 4.607-1.82 6.136c-.58.832-.483 1.78.349 2.361"/></svg>',
    display:
      '<svg class="tray-icon tray-display" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<path d="M0 1v10h16V1zm15 9H1V2h14zm-4.5 2h-5L5 14l-1 1h8l-1-1z"/></svg>',
    robot:
      '<svg class="tray-icon tray-robot" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1' +
      'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73' +
      'c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2M7.5 13A2.5 2.5 0 0 0 5 15.5A2.5 2.5 0 0 0 7.5 18a2.5 2.5 0 0 0 2.5-2.5' +
      'A2.5 2.5 0 0 0 7.5 13m9 0a2.5 2.5 0 0 0-2.5 2.5a2.5 2.5 0 0 0 2.5 2.5a2.5 2.5 0 0 0 2.5-2.5a2.5 2.5 0 0 0-2.5-2.5"/></svg>',
    /* Tailscale's mark is two rows of dots at different opacities. Drawn on
       currentColor rather than the brand white it ships with, so it dims into
       the bar with everything else instead of glaring out of a light theme. */
    tailscale:
      '<svg class="tray-icon tray-tailscale" viewBox="0 0 512 512" fill="currentColor" aria-hidden="true">' +
      '<path d="M65.6 318.1c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9S1.8 219 1.8 254.2s28.6 63.9 63.8 63.9' +
      'm191.6 0c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9s-63.9 28.6-63.9 63.9s28.6 63.9 63.9 63.9' +
      'm0 193.9c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9s-63.9 28.6-63.9 63.9s28.6 63.9 63.9 63.9' +
      'm189.2-193.9c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9s-63.9 28.6-63.9 63.9s28.6 63.9 63.9 63.9"/>' +
      '<path opacity=".5" d="M65.6 127.7c35.3 0 63.9-28.6 63.9-63.9S100.9 0 65.6 0S1.8 28.6 1.8 63.9s28.6 63.8 63.8 63.8' +
      'm0 384.3c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9s-63.8 28.7-63.8 63.9S30.4 512 65.6 512' +
      'm191.6-384.3c35.3 0 63.9-28.6 63.9-63.9S292.5 0 257.2 0s-63.9 28.6-63.9 63.9s28.6 63.8 63.9 63.8' +
      'm189.2 0c35.3 0 63.9-28.6 63.9-63.9S481.6 0 446.4 0c-35.3 0-63.9 28.6-63.9 63.9s28.6 63.8 63.9 63.8' +
      'm0 384.3c35.3 0 63.9-28.6 63.9-63.9s-28.6-63.9-63.9-63.9s-63.9 28.6-63.9 63.9s28.6 63.9 63.9 63.9"/></svg>',
    chevron:
      '<svg class="tray-icon tray-chevron" viewBox="0 0 1024 1024" fill="currentColor" aria-hidden="true">' +
      '<path d="M724 218.3V141c0-6.7-7.7-10.4-12.9-6.3L260.3 486.8a31.86 31.86 0 0 0 0 50.3l450.8 352.1' +
      'c5.3 4.1 12.9.4 12.9-6.3v-77.3c0-4.9-2.3-9.6-6.1-12.6l-360-281l360-281.1c3.8-3 6.1-7.7 6.1-12.6"/></svg>',
    coffee:
      '<svg class="tray-icon tray-coffee" viewBox="0 0 640 640" fill="currentColor" aria-hidden="true">' +
      '<path d="M96 128c0-17.7 14.3-32 32-32h352c70.7 0 128 57.3 128 128s-57.3 128-128 128c0 53-43 96-96 96' +
      'H192c-53 0-96-43-96-96zm448 96c0-35.3-28.7-64-64-64v128c35.3 0 64-28.7 64-64M96 512h384c17.7 0 32 14.3 32 32' +
      's-14.3 32-32 32H96c-17.7 0-32-14.3-32-32s14.3-32 32-32"/></svg>',
    cloud:
      '<svg class="tray-icon tray-cloud" viewBox="0 0 1024 1024" fill="currentColor" aria-hidden="true">' +
      '<path d="M811.4 418.7C765.6 297.9 648.9 212 512.2 212S258.8 297.8 213 418.6C127.3 441.1 64 519.1 64 612' +
      'c0 110.5 89.5 200 199.9 200h496.2C870.5 812 960 722.5 960 612c0-92.7-63.1-170.7-148.6-193.3' +
      'm36.3 281a123.07 123.07 0 0 1-87.6 36.3H263.9c-33.1 0-64.2-12.9-87.6-36.3A123.3 123.3 0 0 1 140 612' +
      'c0-28 9.1-54.3 26.2-76.3a125.7 125.7 0 0 1 66.1-43.7l37.9-9.9l13.9-36.6c8.6-22.8 20.6-44.1 35.7-63.4' +
      'a245.6 245.6 0 0 1 52.4-49.9c41.1-28.9 89.5-44.2 140-44.2s98.9 15.3 140 44.2c19.9 14 37.5 30.8 52.4 49.9' +
      'c15.1 19.3 27.1 40.7 35.7 63.4l13.8 36.5l37.8 10c54.3 14.5 92.1 63.8 92.1 120c0 33.1-12.9 64.3-36.3 87.7"/></svg>',
  };

  /* VS Code's own iconography, so the rail is not a row of approximated Nerd
     Font glyphs. They ride on currentColor and take the activity bar's muted /
     foreground pair -- except the product logo, which keeps its brand blues the
     way the real title bar does. */
  const VSCODE_SVG = {
    logo:
      '<svg class="vs-ico vs-ico-logo" viewBox="0 0 32 32" aria-hidden="true">' +
      '<path fill="#0065a9" d="m29.01 5.03l-5.766-2.776a1.74 1.74 0 0 0-1.989.338L2.38 19.8' +
      'a1.166 1.166 0 0 0-.08 1.647q.037.04.077.077l1.541 1.4a1.165 1.165 0 0 0 1.489.066' +
      'L28.142 5.75A1.158 1.158 0 0 1 30 6.672v-.067a1.75 1.75 0 0 0-.99-1.575"/>' +
      '<path fill="#007acc" d="m29.01 26.97l-5.766 2.777a1.745 1.745 0 0 1-1.989-.338L2.38 12.2' +
      'a1.166 1.166 0 0 1-.08-1.647q.037-.04.077-.077l1.541-1.4A1.165 1.165 0 0 1 5.41 9.01' +
      'l22.732 17.24A1.158 1.158 0 0 0 30 25.328v.072a1.75 1.75 0 0 1-.99 1.57"/>' +
      '<path fill="#1f9cf0" d="M23.244 29.747a1.745 1.745 0 0 1-1.989-.338A1.025 1.025 0 0 0 23 28.684' +
      'V3.316a1.024 1.024 0 0 0-1.749-.724a1.74 1.74 0 0 1 1.989-.339l5.765 2.772A1.75 1.75 0 0 1 30 6.6' +
      'v18.8a1.75 1.75 0 0 1-.991 1.576Z"/></svg>',
    explorer:
      '<svg class="vs-ico vs-ico-explorer" viewBox="0 0 48 48" fill="currentColor" aria-hidden="true">' +
      '<path d="M11.5 10.376V33.75a6.75 6.75 0 0 0 6.75 6.75h15.374A4.25 4.25 0 0 1 29.75 43h-11.5' +
      'A9.25 9.25 0 0 1 9 33.75v-19.5a4.25 4.25 0 0 1 2.5-3.874M25.757 5a4.25 4.25 0 0 1 3.006 1.245' +
      'l8.992 8.992A4.25 4.25 0 0 1 39 18.243V33.75A4.25 4.25 0 0 1 34.75 38h-16.5A4.25 4.25 0 0 1 14 33.75' +
      'V9.25A4.25 4.25 0 0 1 18.25 5zM25 7.5h-6.75a1.75 1.75 0 0 0-1.75 1.75v24.5c0 .967.784 1.75 1.75 1.75' +
      'h16.5a1.75 1.75 0 0 0 1.75-1.75V19h-7.25a4.25 4.25 0 0 1-4.245-4.044L25 14.75zm10.482 9L27.5 8.518' +
      'v6.232a1.75 1.75 0 0 0 1.607 1.744l.143.006z"/></svg>',
    search:
      '<svg class="vs-ico vs-ico-search" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path fill-rule="evenodd" d="M14.385 15.446a6.751 6.751 0 1 1 1.06-1.06l5.156 5.155a.75.75 0 1 1-1.06 1.06z' +
      'M6.46 13.884a5.25 5.25 0 1 1 7.43-.005l-.005.005l-.005.004a5.25 5.25 0 0 1-7.42-.004" clip-rule="evenodd"/></svg>',
    git:
      '<svg class="vs-ico vs-ico-git" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<path d="M14 5.5C14 4.121 12.879 3 11.5 3A2.5 2.5 0 0 0 9 5.5c0 1.182.826 2.169 1.93 2.428A1.5 1.5 0 0 1 9.5 9' +
      'h-3c-.565 0-1.081.195-1.5.512V4.949C6.14 4.717 7 3.707 7 2.5C7 1.121 5.879 0 4.5 0A2.5 2.5 0 0 0 2 2.5' +
      'c0 1.208.86 2.217 2 2.449v6.101c-1.14.232-2 1.242-2 2.449c0 1.379 1.121 2.5 2.5 2.5s2.5-1.121 2.5-2.5' +
      'a2.5 2.5 0 0 0-1.93-2.428A1.5 1.5 0 0 1 6.5 9.999h3a2.5 2.5 0 0 0 2.454-2.046A2.5 2.5 0 0 0 14 5.5' +
      'm-11-3C3 1.673 3.673 1 4.5 1S6 1.673 6 2.5S5.327 4 4.5 4S3 3.327 3 2.5m3 11c0 .827-.673 1.5-1.5 1.5' +
      'S3 14.327 3 13.5S3.673 12 4.5 12s1.5.673 1.5 1.5M11.5 7c-.827 0-1.5-.673-1.5-1.5S10.673 4 11.5 4' +
      's1.5.673 1.5 1.5S12.327 7 11.5 7"/></svg>',
    debug:
      '<svg class="vs-ico vs-ico-debug" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path d="m19.854 13.96l-6.643 3.737a2.25 2.25 0 0 0-1.172-1.056l.015-.015l7.063-3.974a.75.75 0 0 0 0-1.307' +
      'l-12-6.749A.75.75 0 0 0 6 5.25v5.25c-.531 0-1.026.121-1.5.291V5.25c0-1.72 1.853-2.805 3.353-1.96l12 6.75' +
      'c1.528.859 1.528 3.061 0 3.922zm-9.354 2.1V18h.75a.75.75 0 0 1 0 1.5h-.75c0 .576-.11 1.125-.307 1.632' +
      'l1.588 1.588a.75.75 0 0 1-1.062 1.061l-1.327-1.328a4.492 4.492 0 0 1-6.783 0L1.28 23.781a.753.753 0 0 1-1.062 0' +
      'a.75.75 0 0 1 0-1.06l1.589-1.589A4.5 4.5 0 0 1 1.5 19.5H.75a.75.75 0 0 1 0-1.5h.75v-1.94L.219 14.78' +
      'a.75.75 0 0 1 1.06-1.061L2.562 15H3c0-1.655 1.346-3 3-3c1.655 0 3 1.345 3 3h.44l1.28-1.281a.75.75 0 0 1 1.061 1.06z' +
      'M4.5 15h3a1.5 1.5 0 0 0-3 0M9 16.5H3v3c0 1.654 1.346 3 3 3c1.655 0 3-1.346 3-3z"/></svg>',
    extensions:
      '<svg class="vs-ico vs-ico-ext" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<path d="M15 4.957c0-.37-.144-.716-.405-.977L12.01 1.392c-.522-.523-1.431-.523-1.953 0L8 3.452v-.129' +
      'c0-.772-.628-1.401-1.4-1.401H2.4c-.772 0-1.4.629-1.4 1.401V13.6c0 .77.628 1.4 1.4 1.4h10.267' +
      'c.771 0 1.4-.629 1.4-1.401V9.395c0-.772-.629-1.401-1.4-1.401h-.13l2.058-2.059c.26-.26.405-.609.405-.978' +
      'M2.4 2.855h4.2c.257 0 .467.21.467.467v4.671H1.933v-4.67c0-.259.21-.468.467-.468m-.467 10.743v-4.67h5.134v5.137' +
      'H2.4a.47.47 0 0 1-.467-.467m11.2-4.204v4.204c0 .257-.21.467-.466.467H8V8.927h4.667c.256 0 .466.21.466.467' +
      'M8 7.993v-1.53l1.529 1.53zm5.935-2.72l-2.586 2.59a.456.456 0 0 1-.633 0L8.13 5.272a.445.445 0 0 1 0-.632' +
      'l2.586-2.588a.444.444 0 0 1 .633 0l2.586 2.588a.445.445 0 0 1 0 .632"/></svg>',
    account:
      '<svg class="vs-ico vs-ico-account" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
      '<path d="M12 6c-2.28 0-4 1.72-4 4s1.72 4 4 4s4-1.72 4-4s-1.72-4-4-4m0 6c-1.18 0-2-.82-2-2s.82-2 2-2' +
      's2 .82 2 2s-.82 2-2 2"/>' +
      '<path d="M12 2C6.49 2 2 6.49 2 12c0 3.26 1.58 6.16 4 7.98V20h.03c1.67 1.25 3.73 2 5.97 2s4.31-.75 5.97-2' +
      'H18v-.02c2.42-1.83 4-4.72 4-7.98c0-5.51-4.49-10-10-10M8.18 19.02C8.59 17.85 9.69 17 11 17h2' +
      'c1.31 0 2.42.85 2.82 2.02c-1.14.62-2.44.98-3.82.98s-2.69-.35-3.82-.98m9.3-1.21c-.81-1.66-2.51-2.82-4.48-2.82' +
      'h-2c-1.97 0-3.66 1.16-4.48 2.82A7.96 7.96 0 0 1 4 11.99c0-4.41 3.59-8 8-8s8 3.59 8 8c0 2.29-.97 4.36-2.52 5.82"/></svg>',
    settings:
      '<svg class="vs-ico vs-ico-settings" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<path d="M8 6a2 2 0 1 0 0 4a2 2 0 0 0 0-4M7 8a1 1 0 1 1 2 0a1 1 0 0 1-2 0m3.618-3.602a.71.71 0 0 1-.824-.567' +
      'l-.26-1.416a.35.35 0 0 0-.275-.282a6.1 6.1 0 0 0-2.519 0a.35.35 0 0 0-.275.282l-.259 1.416a.71.71 0 0 1-.936.538' +
      'l-1.359-.484a.36.36 0 0 0-.382.095a6 6 0 0 0-1.262 2.173a.35.35 0 0 0 .108.378l1.102.931q.045.037.081.081' +
      'a.704.704 0 0 1-.081.995l-1.102.931a.35.35 0 0 0-.108.378A6 6 0 0 0 3.53 12.02a.36.36 0 0 0 .382.095l1.36-.484' +
      'a.708.708 0 0 1 .936.538l.258 1.416c.026.14.135.252.275.281a6.1 6.1 0 0 0 2.52 0a.35.35 0 0 0 .274-.281l.26-1.416' +
      'a.71.71 0 0 1 .936-.538l1.359.484c.135.048.286.01.382-.095a6 6 0 0 0 1.262-2.173a.35.35 0 0 0-.108-.378l-1.102-.931' +
      'a.703.703 0 0 1 0-1.076l1.102-.931a.35.35 0 0 0 .108-.378A6 6 0 0 0 12.47 3.98a.36.36 0 0 0-.382-.095l-1.36.484' +
      'a1 1 0 0 1-.111.03m-6.62.58l.937.333a1.71 1.71 0 0 0 2.255-1.3l.177-.97a5 5 0 0 1 1.265 0l.178.97' +
      'a1.708 1.708 0 0 0 2.255 1.3L12 4.977q.384.503.63 1.084l-.754.637a1.704 1.704 0 0 0 0 2.604l.755.637' +
      'a5 5 0 0 1-.63 1.084l-.937-.334a1.71 1.71 0 0 0-2.255 1.3l-.178.97a5 5 0 0 1-1.265 0l-.177-.97' +
      'a1.708 1.708 0 0 0-2.255-1.3L4 11.023a5 5 0 0 1-.63-1.084l.754-.638a1.704 1.704 0 0 0 0-2.603l-.755-.637' +
      'q.248-.581.63-1.084"/></svg>',
  };

  const OMARCHY_MARK_SVG =
    '<svg class="oma-mark" viewBox="0 0 1200 1200" fill="currentColor" ' +
    'xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path ' +
    'fill-rule="evenodd" clip-rule="evenodd" d="m1200 1200h-480v-80h400v-1040' +
    'h-479.996v160h-400v720h720v-720h-80v-80h159.996v880h-400v160h-640v-1200h1200z' +
    'm-1120-80h480v-80h-400l.004-400h-80.004zm0-560h80.004v-400h400v-80h-480.004z"' +
    '/></svg>';

  /* ── ascii art ───────────────────────────────────────────────────── */

  const OMARCHY_WORDMARK = [
    "                 ▄▄▄",
    " ▄█████▄    ▄███████████▄    ▄███████   ▄███████   ▄███████   ▄█   █▄    ▄█   █▄",
    "███   ███  ███   ███   ███  ███   ███  ███   ███  ███   ███  ███   ███  ███   ███",
    "███   ███  ███   ███   ███  ███   ███  ███   ███  ███   █▀   ███   ███  ███   ███",
    "███   ███  ███   ███   ███ ▄███▄▄▄███ ▄███▄▄▄██▀  ███       ▄███▄▄▄███▄ ███▄▄▄███",
    "███   ███  ███   ███   ███ ▀███▀▀▀███ ▀███▀▀▀▀    ███      ▀▀███▀▀▀███  ▀▀▀▀▀▀███",
    "███   ███  ███   ███   ███  ███   ███ ██████████  ███   █▄   ███   ███  ▄██   ███",
    "███   ███  ███   ███   ███  ███   ███  ███   ███  ███   ███  ███   ███  ███   ███",
    " ▀█████▀    ▀█   ███   █▀   ███   █▀   ███   ███  ███████▀   ███   █▀    ▀█████▀",
    "                                       ███   █▀",
  ].join("\n");

  const LAZYVIM_ART = [
    "██╗      █████╗ ███████╗██╗   ██╗██╗   ██╗██╗███╗   ███╗",
    "██║     ██╔══██╗╚══███╔╝╚██╗ ██╔╝██║   ██║██║████╗ ████║",
    "██║     ███████║  ███╔╝  ╚████╔╝ ██║   ██║██║██╔████╔██║",
    "██║     ██╔══██║ ███╔╝    ╚██╔╝  ╚██╗ ██╔╝██║██║╚██╔╝██║",
    "███████╗██║  ██║███████╗   ██║    ╚████╔╝ ██║██║ ╚═╝ ██║",
    "╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝     ╚═══╝  ╚═╝╚═╝     ╚═╝",
  ].join("\n");

  /* ── typescript highlighter ──────────────────────────────────────── */

  /* Split the way the theme's tokenColors split. An import keyword and a plain
     keyword are different scopes and, under Tokyo Night, different colours
     (#7aa2f7 against #bb9af7); so are a primitive type and a named one, an
     operator and a bracket, a boolean and an identifier. Lumping them is what
     made the preview look plausible but wrong. */
  const IMPORTS = new RegExp("\\b(import|export|from|require)\\b");

  const KEYWORDS = new RegExp(
    "\\b(const|let|var|function|return|async|await|default|new|" +
      "if|else|for|while|of|in|class|interface|type|enum|extends|implements|throw|" +
      "try|catch|finally|as|void|this|super|switch|case|" +
      "break|continue|yield|typeof|instanceof|delete|readonly|private|public|static)\\b"
  );

  const BOOLS = new RegExp("\\b(true|false|null|undefined)\\b");

  /* storage.type.primitive and support.type, which the template paints in the
     plain foreground -- unlike the named types below it. */
  const PRIMITIVES = new RegExp(
    "\\b(string|number|boolean|bigint|symbol|any|unknown|never|object|void)\\b"
  );

  const TYPES = new RegExp(
    "\\b(Promise|Uint8Array|ArrayBuffer|CryptoKey|TextEncoder|TextDecoder|Record|" +
      "Array|Map|Set|Date|Error|JSON|Math|Object|Window|Buffer|Partial|Readonly|" +
      "Palette)\\b"
  );

  const TOKEN = new RegExp(
    "(\\/\\/.*$)|" + //  1 line comment
      "(`[^`]*`|'[^']*'|\"[^\"]*\")|" + //  2 string
      "(\\b0x[0-9a-fA-F]+\\b|\\b\\d+(?:\\.\\d+)?\\b)|" + //  3 number
      "(" + IMPORTS.source + ")|" + //  4 import keyword
      "(" + BOOLS.source + ")|" + //  6 boolean / null
      "(" + KEYWORDS.source + ")|" + //  8 keyword
      "(" + PRIMITIVES.source + ")|" + // 10 primitive type
      "(" + TYPES.source + ")|" + // 12 named type
      "([A-Za-z_$][\\w$]*)(?=\\s*\\()|" + // 14 call
      // A dotted name is an accessor plus either a method call or a property,
      // and the theme colours those two differently -- so the call form has to
      // be tried first or every `.map(` comes out as a property.
      "(\\.)([A-Za-z_$][\\w$]*)(?=\\s*\\()|" + // 15 accessor, 16 method
      "(\\.)([A-Za-z_$][\\w$]*)|" + // 17 accessor, 18 property
      // `name:` -- an object literal key or an interface member. Its own scope
      // (meta.object-literal.key), and themes do give it its own colour.
      "([A-Za-z_$][\\w$]*)(?=\\s*:)|" + // 19 object key
      "(=>|===|!==|==|!=|<=|>=|\\?\\?|\\|\\||&&|\\.\\.\\.|[=<>!&|+\\-*/?%]+)|" + // 20 operator
      "([{}()\\[\\];,.:]+)", // 21 punctuation
    "g"
  );

  /* A doc comment is three scopes, not one: the tag, the {type} beside it, and
     the name that follows -- treesitter reports @keyword, @type and
     @variable.parameter, and both editors colour them differently from the
     prose. Only the tags that actually take a name claim one, so the `A` in
     "@returns {string} A 32-character string" stays prose. */
  const DOC_TAG = /(@\w+)([ \t]*)(\{[^}]*\})?([ \t]*)([A-Za-z_$][\w$]*)?/g;
  const NAMED_TAGS = /^@(param|arg|argument|property|prop)$/;

  function highlightComment(text) {
    return esc(text).replace(DOC_TAG, function (all, tag, gap1, type, gap2, name) {
      let out = '<span class="t-tag">' + tag + "</span>" + gap1;
      if (type) out += '<span class="t-doctype">' + type + "</span>";
      out += gap2 || "";
      if (name) {
        out += NAMED_TAGS.test(tag)
          ? '<span class="t-docname">' + name + "</span>"
          : name;
      }
      return out;
    });
  }

  /* Highlights one line of TS; `state` carries block-comment continuation. */
  function highlightLine(line, state) {
    if (state.block) {
      const end = line.indexOf("*/");
      if (end === -1) return '<span class="t-doc">' + highlightComment(line) + "</span>";
      state.block = false;
      return (
        '<span class="t-doc">' +
        highlightComment(line.slice(0, end + 2)) +
        "</span>" +
        highlightLine(line.slice(end + 2), state)
      );
    }

    const open = line.indexOf("/*");
    if (open !== -1) {
      const head = highlightLine(line.slice(0, open), state);
      state.block = true;
      return head + highlightLine(line.slice(open), state);
    }

    let out = "";
    let last = 0;
    TOKEN.lastIndex = 0;
    let m;
    while ((m = TOKEN.exec(line))) {
      out += esc(line.slice(last, m.index));
      if (m[15] || m[17]) {
        /* punctuation.accessor, then the method or the property. */
        out +=
          '<span class="t-op">.</span><span class="' + (m[15] ? "t-fn" : "t-prop") +
          '">' + esc(m[16] || m[18]) + "</span>";
        last = m.index + m[0].length;
        continue;
      }
      const cls = m[1] ? "t-com" : m[2] ? "t-str" : m[3] ? "t-num"
        : m[4] ? "t-imp" : m[6] ? "t-bool" : m[8] ? "t-key"
        : m[10] ? "t-prim" : m[12] ? "t-typ" : m[14] ? "t-fn"
        : m[19] ? "t-objkey" : m[20] ? "t-op" : "t-pun";
      out += '<span class="' + cls + '">' + esc(m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return out + esc(line.slice(last));
  }

  function highlightAll(lines) {
    const state = { block: false };
    return lines.map((l) => highlightLine(l, state));
  }

  const CRYPTO_TS = [
    "/**",
    " * Generates a random 256-bit (32-byte) salt.",
    " * @returns {string} A 32-character string to be used as a salt.",
    " */",
    "export const generateSalt = (): string => {",
    "  return nanoid(32);",
    "};",
    "",
    "/**",
    " * Derives a 256-bit AES-GCM key from a user-provided string.",
    " * Uses PBKDF2 for key derivation, which is more secure than hashing.",
    " * @param {string} userKeyString - The user's password or generated key.",
    " * @param {string} salt - A unique identifier for the secret.",
    " * @returns {Promise<CryptoKey>} A promise that resolves to a CryptoKey.",
    " */",
    "async function getDerivedKey(userKeyString: string, salt: string) {",
    "  const keyMaterial = await window.crypto.subtle.importKey(",
    "    'raw',",
    "    new TextEncoder().encode(userKeyString),",
    "    { name: 'PBKDF2' },",
    "    false,",
    "    ['deriveBits', 'deriveKey']",
    "  );",
    "",
    "  return window.crypto.subtle.deriveKey(",
    "    {",
    "      name: 'PBKDF2',",
    "      salt: new TextEncoder().encode(salt),",
    "      iterations: 100000,",
    "      hash: 'SHA-256',",
    "    },",
    "    keyMaterial,",
    "    { name: 'AES-GCM', length: 256 },",
    "    true,",
    "    ['encrypt', 'decrypt']",
    "  );",
    "}",
    "",
    "/**",
    " * Encrypts data using AES-256-GCM.",
    " * @param {string} text - The string data to encrypt.",
    " * @param {string} userEncryptionKey - The user's password.",
    " * @param {string} salt - The salt to use for key derivation.",
    " * @returns {Promise<Uint8Array>} Resolves to the encrypted data.",
    " */",
    "export const encrypt = async (text: string, userKey: string, salt: string) => {",
    "  const key = await getDerivedKey(userKey, salt);",
    "  const iv = window.crypto.getRandomValues(new Uint8Array(12));",
    "",
    "  const ciphertext = await window.crypto.subtle.encrypt(",
    "    {",
    "      name: 'AES-GCM',",
    "      iv: iv,",
    "    },",
    "    key,",
    "    plaintext",
    "  );",
    "",
    "  const fullMessage = new Uint8Array(iv.length + ciphertext.byteLength);",
    "  fullMessage.set(iv);",
    "  fullMessage.set(new Uint8Array(ciphertext), iv.length);",
    "",
    "  return fullMessage;",
    "};",
    "",
    "/**",
    " * Encrypts a file buffer using AES-256-GCM.",
    " * @param {ArrayBuffer} fileBuffer - The file data to encrypt.",
    " * @param {string} userEncryptionKey - The user's password.",
    " * @param {string} salt - The salt to use for key derivation.",
    " * @returns {Promise<Uint8Array>} Resolves to the encrypted data.",
    " */",
    "export const encryptFile = async (fileBuffer: ArrayBuffer) => {",
    "  const key = await getDerivedKey(userKey, salt);",
    "  return aesGcmSeal(key, new Uint8Array(fileBuffer));",
    "};",
  ];

  const THEME_TS = [
    "import { readFile } from 'node:fs/promises';",
    "import { parse } from 'smol-toml';",
    "",
    "export interface Palette {",
    "  background: string;",
    "  foreground: string;",
    "  accent: string;",
    "  bright: Record<string, string>;",
    "}",
    "",
    "const ANSI = ['black', 'red', 'green', 'yellow',",
    "  'blue', 'magenta', 'cyan', 'white'] as const;",
    "",
    "/** Reads colors.toml and folds both dialects into one palette. */",
    "export async function loadPalette(dir: string): Promise<Palette> {",
    "  const raw = parse(await readFile(`${dir}/colors.toml`, 'utf8'));",
    "  const named = typeof raw.red === 'string';",
    "",
    "  const bright = Object.fromEntries(",
    "    ANSI.map((name, i) => [",
    "      name,",
    "      named ? raw[`bright_${name}`] : raw[`color${i + 8}`],",
    "    ])",
    "  );",
    "",
    "  return {",
    "    background: raw.background ?? raw.color0,",
    "    foreground: raw.foreground ?? raw.color7,",
    "    accent: raw.accent ?? raw.color4,",
    "    bright,",
    "  };",
    "}",
    "",
    "export function isLight(hex: string): boolean {",
    "  const [r, g, b] = hex.match(/\\w\\w/g)!.map((c) => parseInt(c, 16));",
    "  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5;",
    "}",
    "",
    "/** Mixes two hex colours; t of 0 returns a, t of 1 returns b. */",
    "export function mix(a: string, b: string, t: number): string {",
    "  const channels = (hex: string) =>",
    "    hex.match(/\\w\\w/g)!.map((c) => parseInt(c, 16));",
    "",
    "  const [ar, ag, ab] = channels(a);",
    "  const [br, bg, bb] = channels(b);",
    "",
    "  return ('#' +",
    "    [ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t]",
    "      .map((c) => Math.round(c).toString(16).padStart(2, '0'))",
    "      .join(''));",
    "}",
    "",
    "/** Fills in whatever a theme leaves out, so downstream code sees a",
    " *  complete palette no matter which dialect it was written in. */",
    "export function complete(palette: Partial<Palette>): Palette {",
    "  const background = palette.background ?? '#1a1b26';",
    "  const foreground = palette.foreground ?? '#c0caf5';",
    "  const light = isLight(background);",
    "",
    "  return {",
    "    ...palette,",
    "    background,",
    "    foreground,",
    "    accent: palette.accent ?? mix(foreground, background, 0.3),",
    "    muted: palette.muted ?? mix(background, foreground, 0.42),",
    "    selection: palette.selection ?? mix(background, foreground, 0.2),",
    "    surface: mix(background, light ? '#000000' : '#ffffff', 0.1),",
    "  } as Palette;",
    "}",
  ];

  /* ── renderers ───────────────────────────────────────────────────── */

  function shellPrompt(theme, cmd) {
    return (
      '<span class="prompt-dir">' + esc(theme.slug) + "</span> " +
      '<span class="prompt-git">' + GLYPH.git + " main</span> " +
      '<span class="prompt-mark">❯</span> ' +
      (cmd ? esc(cmd) : '<span class="cursor-block"></span>')
    );
  }

  function renderLogo() {
    return (
      '<div class="app app-logo">' +
      '<pre class="logo-art">' + esc(OMARCHY_WORDMARK) + "</pre>" +
      '<div class="logo-prompt">~ <span class="prompt-mark">❯</span> ' +
      '<span class="cursor-block"></span></div>' +
      "</div>"
    );
  }

  function renderBtop() {
    const cores = [];
    const rnd = noise(20260902);
    for (let i = 0; i < 12; i++) {
      const pct = Math.round(rnd() * 22) + (i % 4 === 0 ? 8 : 1);
      cores.push(
        '<span class="dim">' + pad("C" + i, 3) + "</span>" +
        padL(pct, 3) + "% " + gauge(pct, 6)
      );
    }
    let coreRows = "";
    for (let i = 0; i < 12; i += 3) {
      coreRows += "<div>" + cores.slice(i, i + 3).join("  ") + "</div>";
    }

    const procs = [
      ["45916", "spotify", "mythz", "487M", "2.4"],
      ["348377", "claude", "mythz", "440M", "0.0"],
      ["3264", "chromium", "mythz", "507M", "0.2"],
      ["352417", "nvim", "mythz", "49M", "1.5"],
      ["1092", "Hyprland", "mythz", "179M", "0.3"],
      ["262835", "dotnet", "mythz", "2.0G", "0.0"],
      ["306265", "chromium", "mythz", "1.0G", "0.1"],
      ["351741", "alacritty", "mythz", "244M", "0.1"],
      ["353024", "btop", "mythz", "35M", "0.1"],
      ["1396", "chromium", "mythz", "244M", "0.0"],
      ["256840", "rider", "mythz", "1.0G", "0.0"],
      ["319145", "btop", "mythz", "36M", "0.0"],
    ];
    const procRows = procs
      .map(
        (p, i) =>
          '<div class="proc-row' + (i === 1 ? " sel" : "") + '">' +
          padL(p[0], 7) + " " + pad(p[1], 11) +
          '<span class="dim">' + pad(p[2], 7) + "</span>" +
          '<span class="ok">' + padL(p[3], 5) + "</span>" +
          padL(p[4], 6) +
          "</div>"
      )
      .join("");

    const mem = [
      ["Total", "15,5 GiB", 100, "dim"],
      ["Used", "12,5 GiB", 80, ""],
      ["Avail", "3,04 GiB", 20, ""],
      ["Cache", "4,13 GiB", 27, ""],
      ["Free", "387 MiB", 2, ""],
    ]
      .map(
        (m) =>
          "<div>" +
          '<span class="key">' + pad(m[0] + ":", 6) + "</span>" +
          '<span class="' + (m[3] || "") + '">' + padL(m[1], 9) + "</span> " +
          gauge(m[2], 10) +
          "</div>"
      )
      .join("");

    return (
      '<div class="app app-btop">' +
        '<div class="box" style="flex:0 0 auto">' +
          '<span class="box-title">cpu</span>' +
          '<span class="box-tools">menu · preset · 17:52:00</span>' +
          "<div>" +
            '<span class="key">Ryzen 5 2600X</span> ' +
            gauge(7, 22) +
            ' <span class="dim">7%</span>  <span class="ok">42°C</span>' +
            '  <span class="dim">2000ms</span>' +
          "</div>" +
          '<div class="graph">' + sparkline(96, 7, 0.05, 0.75) + "</div>" +
          '<div class="graph alt">' + sparkline(96, 11, 0.02, 0.45) + "</div>" +
          coreRows +
          "<div>" +
            '<span class="key">GPU</span>  ' + gauge(1, 10) +
            ' <span class="dim">1%</span>  <span class="ok">3.0G/8.0G</span>' +
            '  <span class="ok">47°C</span> <span class="dim">27.6W</span>' +
          "</div>" +
        "</div>" +
        '<div class="btop-row" style="flex:1">' +
          '<div class="col" style="flex:1;display:flex;flex-direction:column;gap:1.1em">' +
            '<div class="box box-mem">' +
              '<span class="box-title">mem</span>' +
              '<span class="box-tools">disks</span>' +
              mem +
              '<div class="btop-disks" style="margin-top:.35em">' +
                '<span class="key">root</span> ' + gauge(64, 10) +
                ' <span class="dim">446G</span>' +
              "</div>" +
              '<div class="btop-disks">' +
                '<span class="key">boot</span> ' + gauge(20, 10) +
                ' <span class="dim">1,0G</span>' +
              "</div>" +
            "</div>" +
            '<div class="box box-net">' +
              '<span class="box-title">net</span>' +
              '<span class="box-tools">enp5s0</span>' +
              '<div class="dim">▼ download <span class="ok">3,18 KiB/s</span></div>' +
              '<div class="graph">' + sparkline(38, 31, 0.05, 0.9) + "</div>" +
              '<div class="dim">▲ upload <span class="hot">1,91 KiB/s</span></div>' +
              '<div class="graph up">' + sparkline(38, 43, 0.02, 0.6) + "</div>" +
            "</div>" +
          "</div>" +
          '<div class="box box-proc btop-proc" style="flex:1.25">' +
            '<span class="box-title">proc</span>' +
            '<span class="box-tools">cpu lazy</span>' +
            '<div class="proc-head">' +
              padL("Pid", 7) + " " + pad("Program", 11) + pad("User", 7) +
              padL("MemB", 5) + padL("Cpu%", 6) +
            "</div>" +
            procRows +
          "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function renderFastfetch(theme) {
    const group = (title, rows) =>
      '<div class="ff-group ff-' + title.toLowerCase() + '">' +
      '<span class="box-title">' + esc(title) + "</span>" +
      rows
        .map(
          (r) =>
            '<div class="ff-line"><b>' + r[0] + "</b><span>" + esc(r[1]) + "</span></div>"
        )
        .join("") +
      "</div>";

    const swatches = ["red", "yellow", "green", "cyan", "blue", "magenta", "fg", "muted"]
      .map((c) => '<i style="background:var(--' + c + ')"></i>')
      .join("");

    return (
      '<div class="app app-fastfetch">' +
        '<div class="ff-art">' + OMARCHY_MARK_SVG + "</div>" +
        '<div class="ff-info">' +
          group("Hardware", [
            [GLYPH.display, "Komplett PC"],
            [GLYPH.chip, "AMD Ryzen 5 2600X (12) @ 3.6 GHz"],
            [GLYPH.display, "NVIDIA GeForce RTX 3060"],
            [GLYPH.disk, "3840x2160 @ 60 Hz"],
            [GLYPH.db, "12.5 GiB / 15.5 GiB (80%)"],
            [GLYPH.disk, "2.75 TiB / 3.63 TiB (75%)"],
          ]) +
          group("Software", [
            [GLYPH.linux, "Omarchy v2.12 x86_64"],
            [GLYPH.git, "master"],
            [GLYPH.term, "Linux 6.16.7-arch1-1"],
            [GLYPH.bars, "Hyprland 0.51.1 (Wayland)"],
            [GLYPH.term, "alacritty 0.16.1"],
            [GLYPH.pkg, "1061 (pacman), 23 (aur)"],
            [GLYPH.brush, theme.name],
            [GLYPH.star, "JetBrainsMono Nerd Font"],
          ]) +
          '<div class="ff-line ff-uptime"><b>' + GLYPH.clock + "</b><span>" +
            "OS Age 52 days · Uptime 23 hours</span></div>" +
          '<div class="ff-swatches">' + swatches + "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function renderLs(theme) {
    const perm = (mode) =>
      '<span class="ls-perm">' +
      mode
        .split("")
        .map((c) => {
          const cls = { d: "d", r: "r", w: "w", x: "x" }[c];
          return cls ? '<span class="' + cls + '">' + c + "</span>" : c;
        })
        .join("") +
      "</span>";

    const entries = [
      ["drwxr-xr-x", "-", "backgrounds", "dir", GLYPH.folder],
      [".rw-r--r--", "1.8M", "  1.png", "img", GLYPH.image, 1],
      [".rw-r--r--", "962k", "  2.jpg", "img", GLYPH.image, 1],
      ["drwxr-xr-x", "-", "colors", "dir", GLYPH.folder],
      [".rw-r--r--", "1.0k", "alacritty.toml", "doc", GLYPH.file],
      [".rw-r--r--", "1.5k", "btop.theme", "doc", GLYPH.file],
      [".rw-r--r--", "508", "chromium.theme", "doc", GLYPH.file],
      [".rw-r--r--", "1.1k", "colors.toml", "doc", GLYPH.file],
      [".rw-r--r--", "224", "ghostty.conf", "file", GLYPH.file],
      [".rw-r--r--", "233", "hyprland.conf", "file", GLYPH.file],
      [".rw-r--r--", "112", "hyprlock.conf", "file", GLYPH.file],
      [".rw-r--r--", "9", "icons.theme", "file", GLYPH.file],
      [".rw-r--r--", "335", "kitty.conf", "file", GLYPH.file],
      [".rw-r--r--", "165", "mako.ini", "file", GLYPH.file],
      [".rw-r--r--", "3.3k", "neovim.lua", "doc", GLYPH.file],
      [".rw-r--r--", "1.1k", "README.md", "doc", GLYPH.file],
      [".rw-r--r--", "191", "swayosd.css", "file", GLYPH.file],
      [".rw-r--r--", "334", "walker.css", "file", GLYPH.file],
      [".rw-r--r--", "795", "waybar.css", "file", GLYPH.file],
      [".rw-r--r--", "612", "vscode.json", "doc", GLYPH.file],
    ];

    const rows = entries
      .map(
        (e) =>
          "<div>" +
          perm(e[0]) + " " +
          '<span class="ls-size">' + padL(e[1], 5) + "</span> " +
          '<span class="ls-user">mythz</span> ' +
          '<span class="ls-date">14 Sep 15:3' + (e[2].length % 10) + "  </span>" +
          (e[5] ? '<span class="ls-perm">└─ </span>' : "") +
          '<span class="ls-' + e[3] + '">' + e[4] + " " + esc(e[2].trim()) + "</span>" +
          "</div>"
      )
      .join("");

    return (
      '<div class="app app-ls term">' +
        "<div>" + shellPrompt(theme, "eza -l --tree --level=2") + "</div>" +
        rows +
        '<div style="margin-top:.4em">' + shellPrompt(theme) + "</div>" +
      "</div>"
    );
  }

  /* Nautilus, following the real window: a headerbar whose path button shows
     just the current folder, an icon grid of Adwaita icons, and a places
     sidebar that the narrow layout trades for a bottom action bar. */
  function renderNautilus(theme) {
    const ico = global.AdwaitaIcons;

    const places = [
      ["home", "Home", "on"],
      ["recent", "Recent"],
      ["star", "Starred"],
      ["network", "Network"],
      ["trash", "Trash"],
      ["sep"],
      ["folder", "media"],
      ["folder", "opt"],
      ["folder", "src"],
      ["download", "Downloads"],
    ]
      .map((p) =>
        p[0] === "sep"
          ? '<div class="nt-sep"></div>'
          : '<div class="nt-place ' + (p[2] || "") + '">' +
            ico.symbol(p[0]) + "<span>" + esc(p[1]) + "</span></div>"
      )
      .join("");

    const items = [
      ["dir", "backgrounds", "on"],
      ["dir", "colors"],
      ["doc", "alacritty.toml"],
      ["doc", "btop.theme"],
      ["doc", "colors.toml"],
      ["doc", "ghostty.conf"],
      ["dir", "themes"],
      ["doc", "hyprland.conf"],
      ["doc", "icons.theme"],
      ["doc", "kitty.conf"],
      ["doc", "neovim.lua"],
      ["doc", "preview.png"],
      ["doc", "README.md"],
      ["doc", "vscode.json"],
      ["doc", "waybar.css"],
      ["doc", "walker.css"],
      ["dir", "backgrounds-extra"],
      ["doc", "mako.ini"],
      ["doc", "swayosd.css"],
      ["doc", "wofi.css"],
      ["doc", "hyprlock.conf"],
      ["doc", "chromium.theme"],
      ["doc", "keyboard.rgb"],
      ["doc", "shell.toml"],
      ["doc", "helix.toml"],
      ["doc", "gum_env.lua"],
      ["doc", "unlock.png"],
      ["doc", "LICENSE"],
      ["doc", "foot.ini"],
    ]
      .map(
        (it) =>
          '<div class="nt-item ' + (it[2] || "") + '">' +
          (it[0] === "dir" ? ico.folderIcon() : ico.docIcon()) +
          "<span>" + esc(it[1]) + "</span></div>"
      )
      .join("");

    /* One pill naming the folder you are in — Nautilus does not spell out the
       whole path, and a wrapped breadcrumb chain looked nothing like it. */
    const pathButton =
      '<div class="nt-path">' + ico.symbol("home") +
      "<span>" + esc(theme.name) + "</span>" + ico.symbol("more", "dim") + "</div>";

    return (
      '<div class="app app-nautilus">' +
        '<div class="nt-side">' +
          '<div class="nt-side-head">' +
            '<button class="nt-btn">' + ico.symbol("search") + "</button>" +
            "<b>Files</b>" +
            '<button class="nt-btn">' + ico.symbol("menu") + "</button>" +
          "</div>" +
          '<div class="nt-places">' + places + "</div>" +
        "</div>" +
        '<div class="nt-main">' +
          '<div class="nt-head">' +
            '<button class="nt-btn only-narrow">' + ico.symbol("sidebar") + "</button>" +
            '<button class="nt-btn only-wide">' + ico.symbol("prev") + "</button>" +
            '<button class="nt-btn only-wide">' + ico.symbol("next") + "</button>" +
            pathButton +
            '<button class="nt-btn">' + ico.symbol("find") + "</button>" +
            '<button class="nt-btn only-wide">' + ico.symbol("list") + "</button>" +
            '<button class="nt-btn only-wide">' + ico.symbol("down") + "</button>" +
            '<button class="nt-btn round">' + ico.symbol("close") + "</button>" +
          "</div>" +
          '<div class="nt-grid">' + items + "</div>" +
          '<div class="nt-foot only-narrow">' +
            '<button class="nt-btn">' + ico.symbol("prev") + "</button>" +
            '<button class="nt-btn">' + ico.symbol("next") + "</button>" +
            '<div style="flex:1"></div>' +
            '<button class="nt-btn">' + ico.symbol("list") + "</button>" +
            '<button class="nt-btn">' + ico.symbol("down") + "</button>" +
          "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function renderLazyVim(theme) {
    const items = [
      [GLYPH.search, "Find File", "f"],
      [GLYPH.file, "New File", "n"],
      [GLYPH.clock, "Recent Files", "r"],
      [GLYPH.book, "Find Text", "g"],
      [GLYPH.gear, "Config", "c"],
      [GLYPH.refresh, "Restore Session", "s"],
      [GLYPH.pkg, "Lazy Extras", "x"],
      [GLYPH.bolt, "Lazy", "l"],
      [GLYPH.power, "Quit", "q"],
    ]
      .map(
        (it, i) =>
          '<div class="lv-item' + (i === 0 ? " on" : "") + '"><i>' + it[0] + "</i>" +
          esc(it[1]) + "<b>" + it[2] + "</b></div>"
      )
      .join("");

    return (
      '<div class="app app-lazyvim term">' +
        '<pre class="lv-art">' + esc(LAZYVIM_ART) + "</pre>" +
        '<div class="lv-menu">' + items + "</div>" +
        '<div class="lv-foot">' + GLYPH.bolt +
          " Neovim loaded 42/280 plugins in 31.42ms · " + esc(theme.name) + "</div>" +
      "</div>"
    );
  }

  function renderNvim(theme) {
    const cursorAt = 24; // index into CRYPTO_TS that holds the cursor
    const code = highlightAll(CRYPTO_TS);
    const selection = [19, 20, 21, 22];

    const lines = code
      .map((html, i) => {
        const rel = Math.abs(i - cursorAt);
        const num = i === cursorAt ? 56 : rel;
        const cls =
          "nv-line" + (i === cursorAt ? " on" : "") + (selection.includes(i) ? " nv-sel" : "");
        return (
          '<div class="' + cls + '">' +
          '<span class="nv-num">' + num + "</span>" +
          '<span class="nv-code">' + (html || "&nbsp;") + "</span>" +
          "</div>"
        );
      })
      .join("");

    return (
      '<div class="app app-nvim">' +
        '<div class="nv-tabline">' +
          '<div class="nv-tab"><i>' + GLYPH.code + "</i>api.ts" +
            '<span class="x">' + GLYPH.close + "</span></div>" +
          '<div class="nv-tab on"><i>' + GLYPH.code + "</i>crypto.ts" +
            '<span class="x">' + GLYPH.close + "</span></div>" +
          '<div style="flex:1"></div>' +
        "</div>" +
        '<div class="nv-body">' + lines + "</div>" +
        '<div class="nv-status">' +
          '<span class="nv-mode">VISUAL</span>' +
          '<span class="nv-branch">' + GLYPH.git + " main</span>" +
          '<span class="nv-file">' + GLYPH.folder + " ~/Code/lib/crypto.ts</span>" +
          "<span>" + esc(theme.name) + "</span>" +
          "<span>33%</span><span>56:22</span>" +
          '<span class="nv-right">' + GLYPH.clock + " 17:52</span>" +
        "</div>" +
      "</div>"
    );
  }

  function renderVscode(theme) {
    const code = highlightAll(THEME_TS);
    const lines = code
      .map(
        (html, i) =>
          "<div>" +
          '<span class="vs-num">' + (i + 1) + "</span>" +
          (html || "&nbsp;") +
          "</div>"
      )
      .join("");

    /* VS Code orders a folder's children folders-first, each group A-Z, and
       marks expandable rows with a chevron rather than a folder icon. Badges
       are the problem counts the language server reports. */
    const ICON = {
      ts: '<b class="vs-ts">TS</b>',
      json: '<i class="vs-json">{}</i>',
      md: '<i class="vs-md">' + GLYPH.info + "</i>",
      toml: '<i class="vs-toml">' + GLYPH.gear + "</i>",
      png: '<i class="vs-png">' + GLYPH.image + "</i>",
    };

    const tree = [
      [0, "dir", "chev", "omarchy-themes", ""],
      [1, "dir err", "chev", "src", "dot"],
      [2, "", "ts", "index.ts", ""],
      [2, "", "ts", "palette.ts", ""],
      [2, "on err", "ts", "theme.ts", "4"],
      [1, "dir", "chev", "test", ""],
      [2, "", "ts", "theme.test.ts", ""],
      [1, "dir", "chev", "themes", ""],
      [2, "", "toml", "colors.toml", ""],
      [2, "", "png", "preview.png", ""],
      [1, "", "json", "package.json", ""],
      [1, "", "md", "README.md", ""],
      [1, "err", "json", "tsconfig.json", "1"],
    ]
      .map(function (n) {
        const icon = n[2] === "chev" ? '<i class="vs-chev">\u2304</i>' : ICON[n[2]];
        const badge =
          n[4] === "dot"
            ? '<u class="vs-dot"></u>'
            : n[4]
            ? '<u class="vs-badge">' + n[4] + "</u>"
            : "";
        return (
          '<div class="vs-node ' + n[1] + '" style="--depth:' + n[0] + '">' +
          icon + "<span>" + esc(n[3]) + "</span>" + badge +
          "</div>"
        );
      })
      .join("");

    /* The minimap is drawn from the buffer itself: one hairline per line, at the
       line's indent, as long as the line is, in the colour of its first token.
       Reusing the t-* classes means it tracks the theme with the code. */
    const mini = THEME_TS.map(function (line, i) {
      const text = line.replace(/\s+$/, "");
      if (!text.trim()) return '<span class="blank"></span>';
      const indent = text.length - text.replace(/^\s+/, "").length;
      const found = /class="(t-[a-z]+)"/.exec(code[i] || "");
      const width = Math.min(100 - indent * 1.1, (text.length - indent) * 1.15);
      return (
        '<span class="' + (found ? found[1] : "t-var") +
        '" style="margin-left:' + (indent * 1.1).toFixed(1) +
        "%;width:" + Math.max(4, width).toFixed(1) + '%"></span>'
      );
    }).join("");

    return (
      '<div class="app app-vscode">' +
        /* VS Code draws its own title bar: menus, the command centre with the
           workspace name, and the window controls. */
        '<div class="vs-title">' +
          VSCODE_SVG.logo +
          '<span class="vs-menu">File</span><span class="vs-menu">Edit</span>' +
          '<span class="vs-menu">Selection</span><span class="vs-menu">\u22ef</span>' +
          '<div class="vs-centre">' + VSCODE_SVG.search + " omarchy-themes</div>" +
          '<span class="vs-wctl">\u2500</span><span class="vs-wctl">\u25a1</span>' +
          '<span class="vs-wctl">\u2715</span>' +
        "</div>" +
        '<div class="vs-top">' +
          '<div class="vs-rail">' +
            "<i class='on'>" + VSCODE_SVG.explorer + "</i>" +
            "<i>" + VSCODE_SVG.search + "</i>" +
            "<i>" + VSCODE_SVG.git + "</i>" +
            "<i>" + VSCODE_SVG.debug + "</i>" +
            "<i>" + VSCODE_SVG.extensions + "</i>" +
            "<div style='flex:1'></div>" +
            "<i>" + VSCODE_SVG.account + "</i><i>" + VSCODE_SVG.settings + "</i>" +
          "</div>" +
          '<div class="vs-side">' +
            '<div class="vs-side-head">Explorer<span>\u22ef</span></div>' +
            '<div class="vs-tree">' + tree + "</div>" +
            '<div class="vs-panes">' +
              '<div><i class="vs-chev">\u203a</i><span>Outline</span></div>' +
              '<div><i class="vs-chev">\u203a</i><span>Timeline</span></div>' +
            "</div>" +
          "</div>" +
          '<div class="vs-main">' +
            '<div class="vs-tabs">' +
              '<div class="vs-tab"><b class="vs-ts">TS</b>palette.ts</div>' +
              '<div class="vs-tab on"><b class="vs-ts">TS</b>theme.ts' +
                '<u class="vs-badge">4</u></div>' +
              '<div class="vs-tab"><i class="vs-toml">' + GLYPH.gear + "</i>colors.toml</div>" +
            "</div>" +
            '<div class="vs-crumbs">src &rsaquo; <b class="vs-ts">TS</b> theme.ts &rsaquo; loadPalette</div>' +
            '<div class="vs-editor">' +
              '<div class="vs-code">' + lines + "</div>" +
              '<div class="vs-mini">' + mini + "</div>" +
            "</div>" +
          "</div>" +
        "</div>" +
        '<div class="vs-status">' +
          "<span>" + GLYPH.git + " main*</span>" +
          "<span>" + GLYPH.close + " 5 " + GLYPH.refresh + " 0</span>" +
          '<span class="right">' +
            "<span>Ln 18, Col 42</span><span>Spaces: 2</span><span>UTF-8</span>" +
            "<span>LF</span><span>{} TypeScript</span><span>" + esc(theme.name) + "</span>" +
          "</span>" +
        "</div>" +
      "</div>"
    );
  }

  /* Mirrors Omarchy's own root menu: the entries from omarchy-menu.jsonc,
     a "Go" header, and a chevron on every row that drills down. */
  function renderOmarchyMenu() {
    const items = [
      ["\u{F003B}", "Apps", true],
      ["\u{F09D1}", "Learn", true],
      ["\u{F14DE}", "Trigger", true],
      ["\u{EBCF}", "Style", true],
      ["\u{E615}", "Setup", true],
      ["\u{F0249}", "Install", true],
      ["\u{F0B4C}", "Remove", true],
      ["\u{F021}", "Update", true],
      ["\u{EA74}", "About", false],
      ["\u{F011}", "System", true],
    ]
      .map(
        (it, i) =>
          '<div class="om-item' + (i === 0 ? " on" : "") + '">' +
          "<i>" + it[0] + "</i><span>" + esc(it[1]) + "</span>" +
          (it[2] ? '<b class="om-chevron">\u203a</b>' : "") +
          "</div>"
      )
      .join("");

    return (
      '<div class="app app-omenu">' +
        '<div class="om-card">' +
          '<div class="om-header">Go\u2026</div>' +
          '<div class="om-rows">' + items + "</div>" +
        "</div>" +
      "</div>"
    );
  }

  function renderBar(theme) {
    const active = 1;
    const occupied = [2, 3];
    const ws = [1, 2, 3, 4, 5]
      .map((n) => {
        if (n === active) return '<span class="ws on"><i class="ws-pill"></i></span>';
        const cls = occupied.includes(n) ? "ws used" : "ws";
        return '<span class="' + cls + '">' + n + "</span>";
      })
      .join("");

    /* The clock is positioned against the bar itself rather than sitting
       between two spacers, so a longer theme name cannot shift it. */
    return (
      '<div class="bar-left">' +
        '<div class="bar-logo">' + OMARCHY_MARK_SVG + "</div>" +
        '<div class="bar-ws">' + ws + "</div>" +
        '<div class="bar-theme">' + GLYPH.brush + " " + esc(theme.name) + "</div>" +
      "</div>" +
      '<div class="bar-clock">' +
        TRAY_SVG.coffee + "<span>Wednesday 17:52</span>" + TRAY_SVG.cloud +
      "</div>" +
      '<div class="bar-tray">' +
        TRAY_SVG.chevron +
        '<span class="tray-glyph">' + GLYPH.brush + "</span>" +
        TRAY_SVG.tailscale + TRAY_SVG.robot +
        TRAY_SVG.bluetooth + TRAY_SVG.network + TRAY_SVG.speaker + TRAY_SVG.display +
      "</div>"
    );
  }

  /* ── registry ────────────────────────────────────────────────────── */

  const SMALL = [
    { id: "logo", label: "Omarchy logo", glyph: "", render: renderLogo },
    { id: "btop", label: "btop", glyph: "", render: renderBtop },
    { id: "fastfetch", label: "fastfetch", glyph: "", render: renderFastfetch },
    { id: "ls", label: "eza / ls -l", glyph: "", render: renderLs },
    { id: "nautilus", label: "Nautilus", glyph: "", render: renderNautilus },
    { id: "lazyvim", label: "LazyVim", glyph: "", render: renderLazyVim },
    { id: "none", label: "Nothing (show wallpaper)", glyph: "", render: () => "" },
  ];

  const LARGE = [
    { id: "nvim", label: "Neovim", glyph: "", render: renderNvim },
    { id: "vscode", label: "VS Code", glyph: "", render: renderVscode },
    { id: "omenu", label: "Omarchy menu", glyph: "", render: renderOmarchyMenu },
    { id: "none", label: "Nothing (show wallpaper)", glyph: "", render: () => "" },
  ];

  global.OmarchyApps = { SMALL, LARGE, renderBar };
})(window);
