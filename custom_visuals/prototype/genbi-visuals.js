(() => {
  // src/dom.ts
  var SVG_NS = "http://www.w3.org/2000/svg";
  function el(tag, cls, parent, text2) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text2 !== void 0) e.textContent = text2;
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(tag, attrs, parent) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k of Object.keys(attrs)) {
      const v = attrs[k];
      if (v !== void 0) e.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, value, attrs = {}) {
    const t = svg("text", { x, y, ...attrs }, parent);
    t.textContent = value;
    return t;
  }
  function clear(e) {
    while (e.firstChild) e.removeChild(e.firstChild);
  }
  var ctx = null;
  function measure(value, font) {
    if (!ctx) ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return value.length * 7;
    ctx.font = font;
    return ctx.measureText(value).width;
  }
  function fit(value, font, maxWidth) {
    if (measure(value, font) <= maxWidth) return value;
    let s = value;
    while (s.length > 1 && measure(s + "\u2026", font) > maxWidth) s = s.slice(0, -1);
    return s.length > 1 ? s + "\u2026" : "";
  }
  function hexToRgb(hex) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return [n >> 16 & 255, n >> 8 & 255, n & 255];
  }
  function ramp(stops, t) {
    const x = Math.max(0, Math.min(1, isFinite(t) ? t : 0)) * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(x));
    const f = x - i;
    const a = hexToRgb(stops[i]);
    const b = hexToRgb(stops[i + 1]);
    const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }
  function isDark(color) {
    const m = color.match(/\d+/g);
    const [r, g, b] = color.startsWith("#") ? hexToRgb(color) : (m || ["0", "0", "0"]).map(Number);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.58;
  }

  // src/theme.ts
  var DEFAULT_TOKENS = {
    font: "'Segoe UI', 'Segoe UI Web (West European)', -apple-system, system-ui, sans-serif",
    ink: "#1F1A17",
    muted: "#6F6761",
    faint: "#A39B94",
    grid: "#EEE9E3",
    border: "#E7E0D7",
    card: "#FFFFFF",
    primary: "#DD7A12",
    primaryDark: "#9C4F0C",
    primaryLight: "#F6D3A3",
    negative: "#3B78D8",
    target: "#3A3330",
    comparison: "#A9A29B",
    good: "#2E7D3A",
    goodBg: "#E3F2E5",
    warn: "#A86400",
    warnBg: "#FCEFD4",
    bad: "#B3261E",
    badBg: "#FBE4E1"
  };
  function applyTokens(root, t) {
    const vars = {
      "--gb-font": t.font,
      "--gb-ink": t.ink,
      "--gb-muted": t.muted,
      "--gb-faint": t.faint,
      "--gb-grid": t.grid,
      "--gb-border": t.border,
      "--gb-card": t.card,
      "--gb-primary": t.primary,
      "--gb-primary-dark": t.primaryDark,
      "--gb-primary-light": t.primaryLight,
      "--gb-negative": t.negative,
      "--gb-good": t.good,
      "--gb-good-bg": t.goodBg,
      "--gb-warn": t.warn,
      "--gb-warn-bg": t.warnBg,
      "--gb-bad": t.bad,
      "--gb-bad-bg": t.badBg
    };
    for (const k of Object.keys(vars)) root.style.setProperty(k, vars[k]);
  }
  function frame(root, t, header, extraClass = "") {
    clear(root);
    root.classList.add("gb-root");
    applyTokens(root, t);
    const card = el("div", `gb-card ${header.showCard === false ? "gb-flat" : ""} ${extraClass}`.trim(), root);
    const head = el("div", "gb-head", card);
    if (header.title) el("div", "gb-title", head, header.title);
    if (header.subtitle) el("div", "gb-sub", head, header.subtitle);
    if (!header.title && !header.subtitle) head.style.display = "none";
    const body = el("div", "gb-body", card);
    const r = body.getBoundingClientRect();
    return { card, head, body, width: Math.max(10, r.width), height: Math.max(10, r.height) };
  }
  function emptyState(root, t, message) {
    const f = frame(root, t, {});
    el("div", "gb-empty", f.body, message);
  }
  function bind(node, ia, key, tip) {
    node.addEventListener("click", (e) => {
      var _a;
      const ev = e;
      ev.stopPropagation();
      (_a = ia.select) == null ? void 0 : _a.call(ia, key, ev.ctrlKey || ev.metaKey || ev.shiftKey);
    });
    node.addEventListener("mousemove", (e) => {
      var _a;
      return (_a = ia.tooltip) == null ? void 0 : _a.call(ia, e, tip(), key);
    });
    node.addEventListener("mouseleave", () => {
      var _a;
      return (_a = ia.tooltip) == null ? void 0 : _a.call(ia, null, []);
    });
    node.addEventListener("contextmenu", (e) => {
      var _a;
      e.preventDefault();
      e.stopPropagation();
      (_a = ia.contextMenu) == null ? void 0 : _a.call(ia, e, key);
    });
  }
  function dimmed(ia, key) {
    var _a;
    return !!((_a = ia.hasSelection) == null ? void 0 : _a.call(ia)) && !!ia.isActive && !ia.isActive(key);
  }
  var FONT = (size, weight = 400, t = DEFAULT_TOKENS) => `${weight} ${size}px ${t.font}`;

  // src/format.ts
  var MINUS = "\u2212";
  function parseFormat(fmt2) {
    const section = (fmt2 || "").split(";")[0];
    let prefix = "";
    let suffix = "";
    const trimmed = section.trim();
    const literals = trimmed.match(/"[^"]*"/g) || [];
    if (literals.length && trimmed.endsWith(literals[literals.length - 1])) {
      suffix = literals[literals.length - 1].slice(1, -1);
    }
    const core = trimmed.replace(/"[^"]*"/g, "").replace(/\\/g, "");
    const cur = core.match(/[$€£¥₹]/);
    if (cur) prefix = cur[0];
    const kind = core.includes("%") ? "percent" : prefix ? "currency" : "number";
    const dec = core.match(/\.(0+)/);
    const scaling = core.replace(/[$€£¥₹%\s]/g, "").match(/[0#](?:\.[0#]+)?(,+)$/);
    return { kind, prefix, suffix, decimals: dec ? dec[1].length : 0, scale: scaling ? Math.pow(1e3, scaling[1].length) : 1 };
  }
  function group(v, decimals) {
    return v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }
  function sign(v, signed) {
    if (v < 0) return MINUS;
    return signed && v > 0 ? "+" : "";
  }
  function fmt(v, nf, o = {}) {
    var _a, _b, _c, _d;
    if (v === null || v === void 0 || isNaN(v)) return "\u2013";
    const s = sign(v, !!o.signed);
    const a = Math.abs(v);
    if (nf.kind === "percent") {
      const d2 = (_a = o.decimals) != null ? _a : nf.decimals || (a * 100 >= 100 ? 0 : 1);
      return `${s}${group(a * 100, d2)}%`;
    }
    if (nf.scale > 1) {
      const d2 = (_b = o.decimals) != null ? _b : nf.decimals;
      return `${s}${nf.prefix}${group(a / nf.scale, d2)}${nf.suffix}`;
    }
    if (o.compact && a >= 1e4) {
      const [div, unit] = a >= 1e9 ? [1e9, "B"] : a >= 1e6 ? [1e6, "M"] : [1e3, "K"];
      const u = a / div;
      const d2 = (_c = o.decimals) != null ? _c : u < 10 ? 2 : u < 100 ? 1 : unit === "K" ? 0 : 1;
      return `${s}${nf.prefix}${group(u, d2)}${unit}${nf.suffix}`;
    }
    const d = (_d = o.decimals) != null ? _d : nf.decimals;
    return `${s}${nf.prefix}${group(a, d)}${nf.suffix}`;
  }
  function stepDecimals(step) {
    for (let d = 0; d < 2; d++) {
      const x = step * Math.pow(10, d);
      if (Math.abs(x - Math.round(x)) < 1e-9) return d;
    }
    return 2;
  }
  function fmtTick(v, nf, step, signed = false) {
    if (nf.kind === "percent") {
      const d = step * 100 >= 1 ? 0 : step * 100 >= 0.1 ? 1 : 2;
      return fmt(v, nf, { decimals: d, signed });
    }
    if (nf.scale > 1) return fmt(v, nf, { decimals: stepDecimals(step / nf.scale), signed });
    const a = Math.abs(v);
    if (a >= 1e4 || step >= 1e4) {
      const div = Math.max(a, step) >= 1e9 ? 1e9 : Math.max(a, step) >= 1e6 ? 1e6 : 1e3;
      const d = step / div >= 1 ? 0 : step / div >= 0.1 ? 1 : 2;
      return fmt(v, nf, { compact: true, decimals: d, signed });
    }
    return fmt(v, nf, { decimals: step >= 1 ? 0 : 1, signed });
  }
  function deltaText(a, b, nf) {
    if (nf.kind === "percent") {
      const d2 = (a - b) * 100;
      return { text: `${sign(d2, true)}${group(Math.abs(d2), 1)} pts`, diff: d2 };
    }
    if (nf.suffix.trim() && nf.scale === 1) {
      const d2 = a - b;
      return { text: fmt(d2, nf, { signed: true, decimals: Math.max(1, nf.decimals) }), diff: d2 };
    }
    const d = b ? a / b - 1 : 0;
    return { text: `${sign(d, true)}${group(Math.abs(d) * 100, 1)}%`, diff: d };
  }
  function niceTicks(min, max, count = 5) {
    if (!isFinite(min) || !isFinite(max)) return [0, 1];
    if (min === max) {
      const pad = Math.abs(min) * 0.1 || 1;
      min -= pad;
      max += pad;
    }
    const raw = (max - min) / Math.max(1, count - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const start = Math.floor(min / step) * step;
    const ticks = [];
    for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Math.round(v / step) * step);
    if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
    return ticks;
  }

  // src/charts/kpi.ts
  var STATUS_TEXT = { ok: "On track", risk: "At risk", off: "Off track" };
  function statusOf(m, diff, kind, target) {
    var _a;
    const good = m.lowerIsBetter ? diff <= 0 : diff >= 0;
    if (good) return "ok";
    const band = (_a = m.riskBand) != null ? _a : kind === "points" ? 1 : kind === "absolute" ? 0.15 : 0.03;
    const size = kind === "absolute" ? Math.abs(diff) / Math.max(Math.abs(target), 1e-9) : Math.abs(diff);
    return size <= band ? "risk" : "off";
  }
  function icon(parent, status, t) {
    const s = svg("svg", { width: 13, height: 13, viewBox: "0 0 16 16", class: "gb-pill-icon" }, parent);
    if (status === "ok") {
      svg("circle", { cx: 8, cy: 8, r: 8, fill: t.good }, s);
      svg("path", {
        d: "M4.5 8.3l2.2 2.2 4.8-4.9",
        fill: "none",
        stroke: "#fff",
        "stroke-width": 1.8,
        "stroke-linecap": "round",
        "stroke-linejoin": "round"
      }, s);
    } else {
      const c = status === "risk" ? t.warn : t.bad;
      svg("path", { d: "M8 1.2 15.2 14.4H.8z", fill: c, "stroke-linejoin": "round" }, s);
      svg("rect", { x: 7.1, y: 5.6, width: 1.8, height: 4.6, rx: 0.9, fill: "#fff" }, s);
      svg("circle", { cx: 8, cy: 12.1, r: 1, fill: "#fff" }, s);
    }
  }
  function sparkline(parent, values, t, w, h) {
    const pts = values.map((v, i) => ({ v, i })).filter((p) => p.v !== null && isFinite(p.v));
    if (pts.length < 2) return;
    const s = svg("svg", { width: w, height: h, class: "gb-spark" }, parent);
    const lo = Math.min(...pts.map((p) => p.v));
    const hi = Math.max(...pts.map((p) => p.v));
    const n = values.length - 1 || 1;
    const x = (i) => 2 + i / n * (w - 6);
    const y = (v) => h - 3 - (v - lo) / (hi - lo || 1) * (h - 7);
    const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    svg("path", {
      d,
      fill: "none",
      stroke: t.primary,
      "stroke-width": 1.6,
      "stroke-linejoin": "round",
      "stroke-linecap": "round"
    }, s);
    const last = pts[pts.length - 1];
    svg("circle", { cx: x(last.i), cy: y(last.v), r: 2.8, fill: t.primary }, s);
  }
  function renderKpi(root, m, t, header = {}) {
    if (m.value === null || m.value === void 0) {
      emptyState(root, t, "Add a measure to Value");
      return;
    }
    const f = frame(root, t, { showCard: header.showCard }, "gb-kpi");
    const nf = parseFormat(m.valueFormat);
    const box = el("div", "gb-kpi-box", f.body);
    const label = el("div", "gb-kpi-label", box);
    const [main, ...rest] = m.label.split(" \xB7 ");
    el("span", "", label, main);
    if (rest.length) el("span", "gb-kpi-label-muted", label, " \xB7 " + rest.join(" \xB7 "));
    const row = el("div", "gb-kpi-row", box);
    const valueText = fmt(m.value, nf, { compact: true, signed: m.signedValue });
    const valueEl = el("div", "gb-kpi-value", row, valueText);
    const size = Math.max(20, Math.min(32, f.height * 0.24, f.width * 0.58 / Math.max(4, valueText.length) * 1.7));
    valueEl.style.fontSize = `${size}px`;
    if (m.spark && m.spark.length > 1) sparkline(row, m.spark, t, Math.max(56, Math.min(110, f.width * 0.36)), size + 6);
    const hasTarget = m.target !== null && m.target !== void 0;
    let status = null;
    if (hasTarget) {
      const target = m.target;
      const kind = nf.kind === "percent" ? "points" : nf.suffix.trim() && nf.scale === 1 ? "absolute" : "relative";
      const d = deltaText(m.value, target, nf);
      const attain = kind === "relative" ? `${(m.value / (target || 1) * 100).toFixed(1)}%` : d.text;
      el(
        "div",
        "gb-kpi-target",
        box,
        `${m.targetLabel || "Target"} ${fmt(target, nf, { compact: true, signed: m.signedValue })} \xB7 ${attain}`
      );
      status = statusOf(m, d.diff, kind, target);
    }
    const foot = el("div", "gb-kpi-foot", box);
    if (m.comparison !== null && m.comparison !== void 0) {
      const d = deltaText(m.value, m.comparison, nf);
      const good = m.lowerIsBetter ? d.diff <= 0 : d.diff >= 0;
      const delta = el("span", `gb-delta ${good ? "good" : "bad"}`, foot);
      el("span", "gb-delta-arrow", delta, d.diff >= 0 ? "\u25B2" : "\u25BC");
      el("span", "", delta, ` ${d.text} `);
      el("span", "gb-delta-label", delta, m.comparisonLabel || "vs LY");
    } else {
      el("span", "", foot);
    }
    if (status) {
      const pill = el("span", `gb-pill ${status}`, foot);
      icon(pill, status, t);
      el("span", "", pill, STATUS_TEXT[status]);
    }
  }

  // src/charts/trend.ts
  function renderTrend(root, m, t, header, ia = {}) {
    var _a, _b;
    const series = [m.actual, m.target || [], m.comparison || []];
    const all = series.flat().filter((v) => v !== null && v !== void 0 && isFinite(v));
    if (!m.categories.length || !all.length) {
      emptyState(root, t, "Add an axis and an Actual measure");
      return;
    }
    const f = frame(root, t, header, "gb-trend");
    const nf = parseFormat(m.format);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => {
      var _a2;
      return (_a2 = ia.clear) == null ? void 0 : _a2.call(ia);
    });
    const labels = { actual: "Actual", target: "Target", comparison: "Last year", ...m.labels || {} };
    const legend = [[labels.actual, t.primary, void 0]];
    if ((_a = m.target) == null ? void 0 : _a.some((v) => v !== null)) legend.push([labels.target, t.target, "4 3"]);
    if ((_b = m.comparison) == null ? void 0 : _b.some((v) => v !== null)) legend.push([labels.comparison, t.comparison, void 0]);
    let lx = W;
    for (let i = legend.length - 1; i >= 0; i--) {
      const [name, color, dash] = legend[i];
      lx -= measure(name, FONT(11, 400, t)) + 4;
      text(s, lx, 9, name, { "font-size": 11, fill: t.muted, "font-family": t.font });
      lx -= 22;
      svg("line", { x1: lx, x2: lx + 16, y1: 5.5, y2: 5.5, stroke: color, "stroke-width": 2, "stroke-dasharray": dash }, s);
      lx -= 12;
    }
    const ticks = niceTicks(Math.min(...all), Math.max(...all), 5);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    const tickLabels = ticks.map((v) => fmtTick(v, nf, step));
    const lastIdx = m.actual.reduce((acc, v, i) => v !== null ? i : acc, -1);
    const endLabel = lastIdx >= 0 ? fmt(m.actual[lastIdx], nf, { compact: true }) : "";
    const left = Math.max(...tickLabels.map((l) => measure(l, FONT(10, 400, t)))) + 8;
    const right = measure(endLabel, FONT(11, 700, t)) + 10;
    const top = 24, bottom = 20;
    const pw = Math.max(10, W - left - right), ph = Math.max(10, H - top - bottom);
    const n = m.categories.length;
    const x = (i) => left + (n === 1 ? pw / 2 : i / (n - 1) * pw);
    const y = (v) => top + ph - (v - lo) / (hi - lo || 1) * ph;
    ticks.forEach((v, i) => {
      svg("line", { x1: left, x2: left + pw, y1: y(v), y2: y(v), stroke: t.grid, "stroke-width": 1 }, s);
      text(s, left - 6, y(v) + 3.5, tickLabels[i], { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    const labelEvery = Math.max(1, Math.ceil((measure("Mmm", FONT(10, 400, t)) + 10) / (pw / Math.max(1, n - 1) || pw)));
    m.categories.forEach((c, i) => {
      if (i % labelEvery === 0 || i === n - 1) {
        text(s, x(i), H - 4, c, { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font });
      }
    });
    const path = (vals) => {
      let d = "", pen = false;
      vals.forEach((v, i) => {
        if (v === null || v === void 0 || !isFinite(v)) {
          pen = false;
          return;
        }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    };
    if (m.comparison) svg("path", { d: path(m.comparison), fill: "none", stroke: t.comparison, "stroke-width": 2, "stroke-linejoin": "round" }, s);
    if (m.target) svg("path", { d: path(m.target), fill: "none", stroke: t.target, "stroke-width": 1.6, "stroke-dasharray": "5 4" }, s);
    svg("path", { d: path(m.actual), fill: "none", stroke: t.primary, "stroke-width": 2.6, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
    m.actual.forEach((v, i) => {
      var _a2;
      if (v === null) return;
      const key = (_a2 = m.keys) == null ? void 0 : _a2[i];
      svg("circle", {
        cx: x(i),
        cy: y(v),
        r: i === lastIdx ? 4 : 2.4,
        fill: t.primary,
        opacity: dimmed(ia, key) ? 0.3 : 1
      }, s);
    });
    if (lastIdx >= 0) {
      text(
        s,
        x(lastIdx) + 7,
        y(m.actual[lastIdx]) + 4,
        endLabel,
        { "font-size": 11, "font-weight": 700, fill: t.primaryDark, "font-family": t.font }
      );
    }
    const ann = (m.annotations || []).map((a, i) => ({ a, i })).filter((p) => p.a && m.actual[p.i] !== null);
    for (const p of m.showAllAnnotations ? ann : ann.slice(-1)) {
      const vy = y(m.actual[p.i]);
      const w = measure(p.a, FONT(11, 600, t));
      const tx = Math.min(x(p.i) - 4, left + pw - 2);
      const ty = Math.max(top + 2, vy - 12);
      text(s, Math.max(left + w, tx), ty, p.a, {
        "text-anchor": "end",
        "font-size": 11,
        "font-weight": 600,
        fill: t.ink,
        "font-family": t.font
      });
    }
    const guide = svg("line", { y1: top, y2: top + ph, stroke: t.faint, "stroke-width": 1, opacity: 0 }, s);
    const colW = n > 1 ? pw / (n - 1) : pw;
    m.categories.forEach((c, i) => {
      var _a2;
      const r = svg("rect", { x: x(i) - colW / 2, y: top, width: colW, height: ph, fill: "transparent", style: "cursor:pointer" }, s);
      const key = (_a2 = m.keys) == null ? void 0 : _a2[i];
      r.addEventListener("mousemove", (e) => {
        var _a3;
        guide.setAttribute("x1", String(x(i)));
        guide.setAttribute("x2", String(x(i)));
        guide.setAttribute("opacity", "1");
        const items = [{ name: "Period", value: c }, { name: labels.actual, value: fmt(m.actual[i], nf, { compact: true }) }];
        if (m.target) items.push({ name: labels.target, value: fmt(m.target[i], nf, { compact: true }) });
        if (m.comparison) items.push({ name: labels.comparison, value: fmt(m.comparison[i], nf, { compact: true }) });
        (_a3 = ia.tooltip) == null ? void 0 : _a3.call(ia, e, items, key);
      });
      r.addEventListener("mouseleave", () => {
        var _a3;
        guide.setAttribute("opacity", "0");
        (_a3 = ia.tooltip) == null ? void 0 : _a3.call(ia, null, []);
      });
      r.addEventListener("click", (e) => {
        var _a3;
        e.stopPropagation();
        const ev = e;
        (_a3 = ia.select) == null ? void 0 : _a3.call(ia, key, ev.ctrlKey || ev.metaKey);
      });
      r.addEventListener("contextmenu", (e) => {
        var _a3;
        e.preventDefault();
        (_a3 = ia.contextMenu) == null ? void 0 : _a3.call(ia, e, key);
      });
    });
  }

  // src/charts/bars.ts
  function renderBars(root, m, t, header, ia = {}) {
    let rows = m.rows.filter((r) => r.value !== null && r.value !== void 0 && isFinite(r.value));
    if (!rows.length) {
      emptyState(root, t, "Add a category and a value");
      return;
    }
    if (m.sort === "desc") rows = [...rows].sort((a, b) => b.value - a.value);
    if (m.sort === "asc") rows = [...rows].sort((a, b) => a.value - b.value);
    const f = frame(root, t, header, "gb-bars");
    const nf = parseFormat(m.format);
    const signed = m.signed !== false;
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => {
      var _a;
      return (_a = ia.clear) == null ? void 0 : _a.call(ia);
    });
    const labelFont = FONT(12, 400, t), valueFont = FONT(11, 700, t);
    const labelW = Math.min(W * 0.42, Math.max(...rows.map((r) => measure(r.label, labelFont))) + 14);
    const vals = rows.map((r) => r.value);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const texts = rows.map((r) => fmt(r.value, nf, { compact: true, signed }));
    const posW = Math.max(0, ...rows.map((r, i) => r.value >= 0 ? measure(texts[i], valueFont) : 0)) + 6;
    const negW = Math.max(0, ...rows.map((r, i) => r.value < 0 ? measure(texts[i], valueFont) : 0)) + 6;
    const x0 = labelW + (lo < 0 ? negW : 0);
    const x1 = W - (hi > 0 ? posW : 4);
    const sx = (v) => x0 + (v - lo) / (hi - lo || 1) * Math.max(10, x1 - x0);
    const rowH = H / rows.length;
    const barH = Math.max(6, Math.min(16, rowH * 0.5));
    rows.forEach((r, i) => {
      const v = r.value;
      const cy = rowH * i + rowH / 2;
      const g = svg("g", { opacity: dimmed(ia, r.key) ? 0.35 : 1, style: "cursor:pointer" }, s);
      svg("rect", { x: 0, y: rowH * i, width: W, height: rowH, fill: "transparent" }, g);
      text(
        g,
        labelW - 12,
        cy + 4,
        fit(r.label, labelFont, labelW - 14),
        { "text-anchor": "end", "font-size": 12, fill: t.ink, "font-family": t.font }
      );
      const a = sx(Math.min(0, v)), b = sx(Math.max(0, v));
      svg("rect", {
        x: a,
        y: cy - barH / 2,
        width: Math.max(1, b - a),
        height: barH,
        rx: 2,
        fill: v >= 0 ? t.primary : t.negative
      }, g);
      text(g, v >= 0 ? b + 5 : a - 5, cy + 4, texts[i], {
        "text-anchor": v >= 0 ? "start" : "end",
        "font-size": 11,
        "font-weight": 700,
        fill: t.ink,
        "font-family": t.font
      });
      bind(g, ia, r.key, () => [{ name: r.label, value: fmt(v, nf, { compact: true, signed }) }]);
    });
  }

  // src/charts/quadrant.ts
  function renderQuadrant(root, m, t, header, ia = {}) {
    var _a, _b, _c, _d, _e;
    const pts = m.points.filter((p) => p.x !== null && p.y !== null && isFinite(p.x) && isFinite(p.y));
    if (!pts.length) {
      emptyState(root, t, "Add details, X and Y");
      return;
    }
    const sub = (_a = header.subtitle) == null ? void 0 : _a.replace("{n}", String(pts.length));
    const f = frame(root, t, { ...header, subtitle: sub }, "gb-quadrant");
    const nfx = parseFormat(m.xFormat), nfy = parseFormat(m.yFormat), nfs = parseFormat(m.sizeFormat);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => {
      var _a2;
      return (_a2 = ia.clear) == null ? void 0 : _a2.call(ia);
    });
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const xRef = (_b = m.xRef) != null ? _b : null, yRef = (_c = m.yRef) != null ? _c : null;
    const xt = niceTicks(Math.min(...xs, xRef != null ? xRef : Infinity), Math.max(...xs, xRef != null ? xRef : -Infinity), 5);
    const yt = niceTicks(Math.min(...ys, yRef != null ? yRef : Infinity), Math.max(...ys, yRef != null ? yRef : -Infinity), 4);
    const xStep = xt[1] - xt[0], yStep = yt[1] - yt[0];
    const yl = yt.map((v) => fmtTick(v, nfy, yStep));
    const left = Math.max(...yl.map((l) => measure(l, FONT(10, 400, t)))) + 10;
    const top = 6, bottom = 20, right = 8;
    const pw = W - left - right, ph = H - top - bottom;
    const X = (v) => left + (v - xt[0]) / (xt[xt.length - 1] - xt[0] || 1) * pw;
    const Y = (v) => top + ph - (v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1) * ph;
    yt.forEach((v, i) => {
      svg("line", { x1: left, x2: left + pw, y1: Y(v), y2: Y(v), stroke: t.grid }, s);
      text(s, left - 6, Y(v) + 3.5, yl[i], { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    xt.forEach((v) => text(
      s,
      X(v),
      H - 5,
      fmtTick(v, nfx, xStep, true),
      { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font }
    ));
    if (xRef !== null) svg("line", { x1: X(xRef), x2: X(xRef), y1: top, y2: top + ph, stroke: t.target, "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);
    if (yRef !== null) svg("line", { x1: left, x2: left + pw, y1: Y(yRef), y2: Y(yRef), stroke: t.target, "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);
    const c = { topLeft: "", topRight: "", bottomLeft: "", bottomRight: "", ...m.corners || {} };
    const cs = { "font-size": 11, "font-weight": 600, fill: t.ink, "font-family": t.font };
    if (c.topLeft) text(s, left + 6, top + 13, c.topLeft, cs);
    if (c.topRight) text(s, left + pw - 6, top + 13, c.topRight, { ...cs, "text-anchor": "end" });
    if (c.bottomLeft) text(s, left + 6, top + ph - 6, c.bottomLeft, cs);
    if (c.bottomRight) text(s, left + pw - 6, top + ph - 6, c.bottomRight, { ...cs, "text-anchor": "end" });
    const xr = xRef != null ? xRef : xs.reduce((a, b) => a + b, 0) / xs.length;
    const yr = yRef != null ? yRef : ys.reduce((a, b) => a + b, 0) / ys.length;
    const sx = Math.max(...xs) - Math.min(...xs) || 1, sy = Math.max(...ys) - Math.min(...ys) || 1;
    const score = (p) => (p.x - xr) / sx + (p.y - yr) / sy;
    const named = /* @__PURE__ */ new Set([
      ...pts.filter((p) => p.x > xr && p.y > yr).sort((a, b) => score(b) - score(a)).slice(0, (_d = m.labelTop) != null ? _d : 2),
      ...pts.filter((p) => p.x < xr && p.y < yr).sort((a, b) => score(a) - score(b)).slice(0, (_e = m.labelBottom) != null ? _e : 1)
    ]);
    const sizes = pts.map((p) => {
      var _a2;
      return (_a2 = p.size) != null ? _a2 : 0;
    });
    const maxSize = Math.max(...sizes, 0);
    const [rMin, rMax] = pts.length > 60 ? [2.5, 7.5] : pts.length > 20 ? [3.5, 10] : [5, 16];
    const radius = (p) => {
      var _a2;
      return maxSize > 0 ? rMin + (rMax - rMin) * Math.sqrt(Math.max(0, (_a2 = p.size) != null ? _a2 : 0) / maxSize) : rMin + 1.5;
    };
    const names = { x: "X", y: "Y", size: "Size", ...m.names || {} };
    const dots = svg("g", {}, s);
    const top_ = svg("g", {}, s);
    const placed = [];
    const labelFont = FONT(11, 600, t);
    [...pts].sort((a, b) => radius(b) - radius(a)).forEach((p) => {
      var _a2;
      const isNamed = named.has(p);
      const cx = X(p.x), cy = Y(p.y), r = radius(p);
      const g = svg("g", { opacity: dimmed(ia, p.key) ? 0.25 : 1, style: "cursor:pointer" }, isNamed ? top_ : dots);
      svg("circle", {
        cx,
        cy,
        r,
        fill: isNamed ? t.ink : t.primary,
        "fill-opacity": isNamed ? 1 : 0.8,
        stroke: "#fff",
        "stroke-width": 0.8
      }, g);
      if (isNamed) {
        const onLeft = cx > left + pw * 0.6;
        const w = measure(p.label, labelFont);
        const lx = onLeft ? cx - r - 4 : cx + r + 4;
        const x0 = onLeft ? lx - w : lx, x1 = onLeft ? lx : lx + w;
        const dy = (_a2 = [0, 13, -13, 26, -26].find((d) => !placed.some((b) => x0 < b.x1 && x1 > b.x0 && cy + d - 9 < b.y1 && cy + d + 4 > b.y0))) != null ? _a2 : 0;
        placed.push({ x0, x1, y0: cy + dy - 9, y1: cy + dy + 4 });
        text(g, lx, cy + 4 + dy, p.label, {
          "text-anchor": onLeft ? "end" : "start",
          "font-size": 11,
          "font-weight": 600,
          fill: t.ink,
          "font-family": t.font,
          stroke: "#fff",
          "stroke-width": 3,
          "stroke-linejoin": "round",
          "paint-order": "stroke"
        });
      }
      bind(g, ia, p.key, () => {
        const items = [
          { name: "", value: p.label },
          { name: names.x, value: fmt(p.x, nfx, { signed: nfx.kind === "percent" }) },
          { name: names.y, value: fmt(p.y, nfy) }
        ];
        if (p.size !== null && p.size !== void 0) items.push({ name: names.size, value: fmt(p.size, nfs, { compact: true }) });
        return items;
      });
    });
  }

  // src/charts/treemap.ts
  function squarify(items, x, y, w, h) {
    const total = items.reduce((a, it) => a + it.size, 0);
    const scale = w * h / (total || 1);
    const areas = items.map((it) => ({ item: it, a: it.size * scale }));
    const out = [];
    let rx = x, ry = y, rw = w, rh = h;
    let row = [];
    const worst = (r, side) => {
      const sum = r.reduce((s, v) => s + v.a, 0);
      const mx = Math.max(...r.map((v) => v.a)), mn = Math.min(...r.map((v) => v.a));
      return Math.max(side * side * mx / (sum * sum), sum * sum / (side * side * mn));
    };
    const layout = (r) => {
      const sum = r.reduce((s, v) => s + v.a, 0);
      if (rw >= rh) {
        const cw = sum / rh;
        let cy = ry;
        for (const v of r) {
          const ch = v.a / cw;
          out.push({ x: rx, y: cy, w: cw, h: ch, item: v.item });
          cy += ch;
        }
        rx += cw;
        rw -= cw;
      } else {
        const ch = sum / rw;
        let cx = rx;
        for (const v of r) {
          const cw = v.a / ch;
          out.push({ x: cx, y: ry, w: cw, h: ch, item: v.item });
          cx += cw;
        }
        ry += ch;
        rh -= ch;
      }
    };
    for (const v of areas) {
      const side = Math.min(rw, rh);
      if (!row.length || worst([...row, v], side) <= worst(row, side)) row.push(v);
      else {
        layout(row);
        row = [v];
      }
    }
    if (row.length) layout(row);
    return out;
  }
  function renderTreemap(root, m, t, header, ia = {}) {
    const items = m.items.filter((i) => i.size !== null && i.size > 0).sort((a, b) => b.size - a.size);
    if (!items.length) {
      emptyState(root, t, "Add a category and a size measure");
      return;
    }
    const f = frame(root, t, header, "gb-treemap");
    const nfs = parseFormat(m.sizeFormat), nfc = parseFormat(m.colorFormat);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => {
      var _a;
      return (_a = ia.clear) == null ? void 0 : _a.call(ia);
    });
    const colors = items.map((i) => i.color).filter((v) => v !== null && v !== void 0);
    const hasColor = colors.length > 0;
    const lo = hasColor ? Math.min(...colors) : 0, hi = hasColor ? Math.max(...colors) : 1;
    const stops = [t.primaryLight, t.primary, t.primaryDark];
    const legendH = hasColor ? 18 : 0;
    if (hasColor) {
      const loT = fmt(lo, nfc, { decimals: 0 }), hiT = fmt(hi, nfc, { decimals: 0 });
      const hiW = measure(hiT, FONT(10, 400, t));
      const bx = W - hiW - 6 - 70;
      text(s, bx - 5, 10, loT, { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
      const grad = svg("linearGradient", { id: `gbtm${Math.random().toString(36).slice(2, 8)}` }, svg("defs", {}, s));
      stops.forEach((c, i) => svg("stop", { offset: `${i / (stops.length - 1) * 100}%`, "stop-color": c }, grad));
      svg("rect", { x: bx, y: 4, width: 70, height: 7, rx: 3.5, fill: `url(#${grad.getAttribute("id")})` }, s);
      text(s, W - hiW, 10, hiT, { "font-size": 10, fill: t.muted, "font-family": t.font });
    }
    const rects = squarify(items, 0, legendH, W, H - legendH);
    const names = { size: "Value", color: "Colour", ...m.names || {} };
    for (const r of rects) {
      const it = r.item;
      const fill = hasColor && it.color !== null && it.color !== void 0 ? ramp(stops, (it.color - lo) / (hi - lo || 1)) : t.primary;
      const g = svg("g", { opacity: dimmed(ia, it.key) ? 0.3 : 1, style: "cursor:pointer" }, s);
      svg("rect", { x: r.x + 1, y: r.y + 1, width: Math.max(0, r.w - 2), height: Math.max(0, r.h - 2), rx: 2, fill }, g);
      const ink = isDark(fill) ? "#FFFFFF" : t.ink;
      const nameFont = FONT(12, 700, t), subFont = FONT(10.5, 400, t);
      if (r.w > 36 && r.h > 20) {
        text(g, r.x + 7, r.y + 17, fit(it.label, nameFont, r.w - 12), { "font-size": 12, "font-weight": 700, fill: ink, "font-family": t.font });
        if (r.h > 36) {
          const line = hasColor && it.color !== null && it.color !== void 0 ? `${fmt(it.size, nfs, { compact: true })} \xB7 ${fmt(it.color, nfc)}` : fmt(it.size, nfs, { compact: true });
          const shown = measure(line, subFont) <= r.w - 12 ? line : hasColor && it.color !== null && it.color !== void 0 ? fmt(it.color, nfc) : "";
          if (shown) text(g, r.x + 7, r.y + 31, shown, { "font-size": 10.5, fill: ink, opacity: 0.92, "font-family": t.font });
        }
      }
      bind(g, ia, it.key, () => {
        const tip = [{ name: "", value: it.label }, { name: names.size, value: fmt(it.size, nfs, { compact: true }) }];
        if (hasColor) tip.push({ name: names.color, value: fmt(it.color, nfc) });
        return tip;
      });
    }
  }

  // src/charts/heatmap.ts
  function renderHeatmap(root, m, t, header, ia = {}) {
    const flat = m.values.flat().filter((v) => v !== null && v !== void 0 && isFinite(v));
    if (!m.rows.length || !m.cols.length || !flat.length) {
      emptyState(root, t, "Add rows, columns and a value");
      return;
    }
    const f = frame(root, t, header, "gb-heatmap");
    const nf = parseFormat(m.format);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => {
      var _a;
      return (_a = ia.clear) == null ? void 0 : _a.call(ia);
    });
    const lo = Math.min(...flat), hi = Math.max(...flat);
    const stops = ["#FBF0E2", t.primaryLight, t.primary, t.primaryDark];
    const legend = { low: "Low", high: "High", ...m.legend || {} };
    const lw = 64, hiW = measure(legend.high, FONT(10, 400, t));
    const lx = W - hiW - 6 - lw;
    text(s, lx - 5, 10, legend.low, { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    const grad = svg("linearGradient", { id: `gbhm${Math.random().toString(36).slice(2, 8)}` }, svg("defs", {}, s));
    stops.forEach((c, i) => svg("stop", { offset: `${i / (stops.length - 1) * 100}%`, "stop-color": c }, grad));
    svg("rect", { x: lx, y: 4, width: lw, height: 7, rx: 3.5, fill: `url(#${grad.getAttribute("id")})` }, s);
    text(s, W - hiW, 10, legend.high, { "font-size": 10, fill: t.muted, "font-family": t.font });
    const top = 18, bottom = 18;
    const left = Math.max(...m.rows.map((r) => measure(r, FONT(11, 400, t)))) + 10;
    const cw = (W - left) / m.cols.length, ch = (H - top - bottom) / m.rows.length;
    const gap = Math.min(3, cw * 0.12, ch * 0.12);
    const every = Math.max(1, Math.ceil(24 / cw));
    m.cols.forEach((c, j) => {
      if (j % every === 0) text(s, left + cw * j + cw / 2, H - 4, c, { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    let peak = { i: -1, j: -1, v: -Infinity };
    m.values.forEach((row, i) => row.forEach((v, j) => {
      if (v !== null && v > peak.v) peak = { i, j, v };
    }));
    const names = { row: "Row", col: "Column", value: "Value", ...m.names || {} };
    const label = (v) => m.indexMode ? String(Math.round(v / (hi || 1) * 100)) : fmt(v, nf, { compact: true });
    m.rows.forEach((r, i) => {
      const y = top + ch * i;
      text(s, left - 8, y + ch / 2 + 4, r, { "text-anchor": "end", "font-size": 11, fill: t.ink, "font-family": t.font });
      m.cols.forEach((c, j) => {
        var _a, _b, _c, _d;
        const v = (_a = m.values[i]) == null ? void 0 : _a[j];
        if (v === null || v === void 0) return;
        const key = (_c = (_b = m.keys) == null ? void 0 : _b[i]) == null ? void 0 : _c[j];
        const fill = ramp(stops, (v - lo) / (hi - lo || 1));
        const g = svg("g", { opacity: dimmed(ia, key) ? 0.3 : 1, style: "cursor:pointer" }, s);
        svg("rect", { x: left + cw * j + gap / 2, y: y + gap / 2, width: Math.max(1, cw - gap), height: Math.max(1, ch - gap), rx: 2, fill }, g);
        const show = m.showValues === "all" || ((_d = m.showValues) != null ? _d : "peak") === "peak" && i === peak.i && j === peak.j;
        if (show && cw > 18 && ch > 12) {
          text(g, left + cw * j + cw / 2, y + ch / 2 + 4, label(v), {
            "text-anchor": "middle",
            "font-size": 11,
            "font-weight": 700,
            fill: (v - lo) / (hi - lo || 1) > 0.55 ? "#fff" : t.ink,
            "font-family": t.font
          });
        }
        bind(g, ia, key, () => {
          const tip = [{ name: names.row, value: r }, { name: names.col, value: c }, { name: names.value, value: fmt(v, nf, { compact: true }) }];
          if (m.indexMode) tip.push({ name: "Index (peak = 100)", value: label(v) });
          return tip;
        });
      });
    });
  }

  // src/charts/funnel.ts
  function renderFunnel(root, m, t, header, ia = {}) {
    const stages = m.stages.filter((s2) => s2.value !== null && s2.value !== void 0 && isFinite(s2.value));
    if (!stages.length) {
      emptyState(root, t, "Add two or more stage measures");
      return;
    }
    const f = frame(root, t, header, "gb-funnel");
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    const first = stages[0].value;
    const max = Math.max(...stages.map((st) => st.value));
    const labelW = Math.max(...stages.map((st) => measure(st.label, FONT(12, 400, t)))) + 16;
    const vals = stages.map((st) => fmt(st.value, parseFormat(st.format), { compact: true }));
    const valW = Math.max(...vals.map((v) => measure(v, FONT(12, 700, t)))) + 18;
    const pctW = measure("100.0%", FONT(11, 400, t)) + 6;
    const area = Math.max(20, W - labelW - valW - pctW);
    const rowH = H / stages.length;
    const barH = Math.max(8, Math.min(22, rowH * 0.62));
    stages.forEach((st, i) => {
      const v = st.value;
      const cy = rowH * i + rowH / 2;
      const bw = Math.max(3, v / (max || 1) * area);
      const g = svg("g", {}, s);
      text(g, labelW - 12, cy + 4, st.label, { "text-anchor": "end", "font-size": 12, fill: t.ink, "font-family": t.font });
      svg("rect", {
        x: labelW + (area - bw) / 2,
        y: cy - barH / 2,
        width: bw,
        height: barH,
        rx: 3,
        fill: ramp([t.primary, t.primaryDark], stages.length > 1 ? i / (stages.length - 1) : 0)
      }, g);
      text(g, labelW + area + 10, cy + 4, vals[i], { "font-size": 12, "font-weight": 700, fill: t.ink, "font-family": t.font });
      const pct = first ? v / first : 0;
      text(
        g,
        W,
        cy + 4,
        pct >= 0.9995 ? "100%" : `${(pct * 100).toFixed(1)}%`,
        { "text-anchor": "end", "font-size": 11, fill: t.muted, "font-family": t.font }
      );
      g.addEventListener("mousemove", (e) => {
        var _a;
        return (_a = ia.tooltip) == null ? void 0 : _a.call(ia, e, [
          { name: "Stage", value: st.label },
          { name: "Value", value: vals[i] },
          { name: "% of first", value: `${(pct * 100).toFixed(1)}%` },
          ...i ? [{ name: "% of previous", value: `${(v / (stages[i - 1].value || 1) * 100).toFixed(1)}%` }] : []
        ]);
      });
      g.addEventListener("mouseleave", () => {
        var _a;
        return (_a = ia.tooltip) == null ? void 0 : _a.call(ia, null, []);
      });
    });
  }

  // src/charts/narrative.ts
  function rich(parent, value) {
    value.split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
      if (!part) return;
      if (part.startsWith("**") && part.endsWith("**")) el("b", "", parent, part.slice(2, -2));
      else parent.appendChild(document.createTextNode(part));
    });
  }
  function renderNarrative(root, m, t, header = {}) {
    const style = m.style || "numbered";
    const f = frame(root, t, { showCard: header.showCard }, `gb-narrative gb-${style}`);
    if (m.heading) {
      const h = el("div", "gb-nar-head", f.body);
      if (style !== "timeline") {
        const ic = svg("svg", { width: 14, height: 14, viewBox: "0 0 16 16", class: "gb-nar-icon" }, h);
        if (style === "numbered") {
          svg("path", {
            d: "M8 1.5a4.5 4.5 0 0 0-2.6 8.2V12h5.2V9.7A4.5 4.5 0 0 0 8 1.5zM5.9 13.3h4.2M6.6 14.8h2.8",
            fill: "none",
            stroke: t.primary,
            "stroke-width": 1.4,
            "stroke-linecap": "round"
          }, ic);
        } else {
          svg("rect", { x: 2, y: 2, width: 12, height: 12, rx: 2.5, fill: "none", stroke: t.primary, "stroke-width": 1.4 }, ic);
          svg("path", { d: "M5 6h6M5 8.5h6M5 11h4", stroke: t.primary, "stroke-width": 1.3, "stroke-linecap": "round" }, ic);
        }
      }
      el("span", "gb-nar-title", h, m.heading);
      if (m.note) el("span", "gb-nar-note", h, ` \xB7 ${m.note}`);
    }
    const items = m.items.filter((s) => s && s.trim());
    const list = el("div", "gb-nar-list", f.body);
    items.forEach((item, i) => {
      const row = el("div", "gb-nar-item", list);
      if (style === "timeline") {
        const [title, date, owner] = item.split("|").map((p) => p.trim());
        el("span", "gb-nar-badge", row, String(i + 1).padStart(2, "0"));
        const txt = el("div", "gb-nar-step", row);
        const top = el("div", "", txt);
        el("b", "", top, title || "");
        if (date) el("span", "gb-nar-muted", top, ` \xB7 ${date}`);
        if (owner) el("div", "gb-nar-muted", txt, owner);
        return;
      }
      if (style === "numbered") el("span", "gb-nar-num", row, String(i + 1));
      else {
        const ic = svg("svg", { width: 12, height: 12, viewBox: "0 0 12 12", class: "gb-nar-bullet" }, row);
        svg("path", { d: "M2 1.5 10 6 2 10.5z", fill: "none", stroke: t.primary, "stroke-width": 1.3, "stroke-linejoin": "round" }, ic);
      }
      rich(el("div", "gb-nar-text", row), item);
    });
  }

  // src/prototype.ts
  function interactions(rerender) {
    let tip = null;
    let selected = [];
    return {
      select(key, multi) {
        const has = selected.includes(key);
        selected = multi ? has ? selected.filter((k) => k !== key) : [...selected, key] : has && selected.length === 1 ? [] : [key];
        rerender();
      },
      clear() {
        if (selected.length) {
          selected = [];
          rerender();
        }
      },
      hasSelection: () => selected.length > 0,
      isActive: (key) => selected.includes(key),
      tooltip(ev, items) {
        if (!ev) {
          tip == null ? void 0 : tip.remove();
          tip = null;
          return;
        }
        if (!tip) {
          tip = document.createElement("div");
          tip.className = "gb-tooltip";
          document.body.appendChild(tip);
        }
        tip.innerHTML = items.map((i) => i.name ? `${i.name}: <b>${i.value}</b>` : `<b>${i.value}</b>`).join("<br>");
        tip.style.left = `${ev.clientX + 14}px`;
        tip.style.top = `${ev.clientY + 12}px`;
      }
    };
  }
  var RENDERERS = {
    kpiCard: (r, m, t, h) => renderKpi(r, m, t, h),
    trendLine: renderTrend,
    driverBars: renderBars,
    quadrant: renderQuadrant,
    treemap: renderTreemap,
    heatmap: renderHeatmap,
    funnel: renderFunnel,
    narrative: (r, m, t, h) => renderNarrative(r, m, t, h)
  };
  function render(type, root, model, header = {}, tokens = {}) {
    const t = { ...DEFAULT_TOKENS, ...tokens };
    const fn = RENDERERS[type];
    if (!fn) throw new Error(`Unknown visual type ${type}`);
    const draw = () => fn(root, model, t, header, ia);
    const ia = interactions(draw);
    draw();
    new ResizeObserver(() => draw()).observe(root);
  }
  window.GenBIVisuals = { render, DEFAULT_TOKENS, types: Object.keys(RENDERERS) };
})();
