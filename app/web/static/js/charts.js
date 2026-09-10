/* garmin-dash chart helpers (uPlot, dark theme). */
"use strict";

const GDASH = {
  // Convert ISO dates → epoch seconds
  epoch: (iso) => Date.parse(iso + "T00:00:00Z") / 1000,

  // Stride downsample with min/max preservation (for very long series)
  downsample(values, maxPoints) {
    if (!values || values.length <= maxPoints) return values;
    const n = values.length;
    const step = Math.ceil(n / maxPoints);
    const out = [];
    for (let i = 0; i < n; i += step) {
      let min = Infinity, max = -Infinity;
      for (let j = i; j < Math.min(i + step, n); j++) {
        const v = values[j];
        if (v === null || v === undefined) continue;
        if (v < min) min = v;
        if (v > max) max = v;
      }
      if (min === Infinity) { out.push(null); continue; }
      out.push(max);           // max is what the eye wants for spikes
    }
    return out;
  },

  /* Place sparse [ts, value] samples onto a sorted x grid by TIME, forward-
     filling the last known value (step line). Before the first sample the
     value is null (gap). Both inputs must be sorted ascending by ts. */
  alignByTime(xGrid, samples) {
    const y = new Array(xGrid.length).fill(null);
    if (!samples || !samples.length) return y;
    let i = 0;
    for (let k = 0; k < xGrid.length; k++) {
      while (i + 1 < samples.length && samples[i + 1][0] <= xGrid[k]) i++;
      if (samples[i][0] <= xGrid[k]) y[k] = samples[i][1];
    }
    return y;
  },

  seriesOpts: {
    grid: { stroke: "#27272a", width: 1 },
    cursor: { stroke: "#71717a" },
    axes: [
      { stroke: "#71717a", grid: { stroke: "#27272a" }, ticks: { stroke: "#3f3f46" } },
      { stroke: "#71717a", grid: { width: 0 }, ticks: { stroke: "#3f3f46" } },
    ],
  },

  colors: {
    emerald: "#34d399", yellow: "#fbbf24", red: "#f87171",
    sky: "#38bdf8", purple: "#c084fc", zinc: "#a1a1aa",
    orange: "#fb923c", indigo: "#818cf8",
  },

  timeOpts(tzLabel) {
    return { tz: "local" };
  },
};

/* Build a uPlot line chart into `el`.
   series: [{ label, color, width?, fill?, scale? }] — NOTE: uPlot maps
   series array index 0 to the x axis, so we prepend an empty x-series
   config; `series` describes the y series only.
   x: epoch-seconds array; y: parallel arrays (nulls allowed). */
GDASH.lineChart = function (el, series, x, yArrays, opts = {}) {
  const data = [x, ...yArrays];
  // uPlot maps series index 0 to the x axis; label it so the legend row
  // shows something meaningful instead of the default "Time".
  const uplotSeries = [{ label: opts.xLabel || "datum" }].concat(series.map((s, i) => ({
    label: s.label,
    stroke: s.color,
    width: s.width || 1.5,
    fill: s.fill ? s.color + "22" : undefined,
    scale: s.scale || "%",
    points: { show: false },
    spanGaps: true,
    // uPlot calls value(self, raw, seriesIdx, idx) — unwrap the raw datum
    value: (self, v) => (s.value ? s.value(v) : v),
  })));
  const axes = [
    { stroke: "#71717a", grid: { stroke: "#27272a" }, ticks: { stroke: "#3f3f46" }, size: 48, label: "datum" },
    { stroke: "#71717a", grid: { width: 0 }, ticks: { stroke: "#3f3f46" }, size: 44, scale: "%", label: "waarde" },
  ];
  if (opts.scales) {
    for (const [key, conf] of Object.entries(opts.scales)) {
      axes[1] = { ...axes[1], ...conf.axis };
    }
  }
  const u = new uPlot(
    {
      ...GDASH.seriesOpts,
      width: el.clientWidth || 800,
      height: opts.height || 260,
      scales: opts.scales || { "%": { auto: true } },
      series: uplotSeries,
      legend: { show: true, live: true },
      axes,
      // uPlot expects fmtDate to RETURN a formatter function; it is called
      // with Date objects for ticks and epoch seconds for the legend row.
      fmtDate: () => (d) => {
        const dt = d instanceof Date ? d : new Date((Array.isArray(d) ? d[0] : d) * 1000);
        return isNaN(dt.getTime()) ? "" : dt.toLocaleDateString("nl-NL", { day: "2-digit", month: "short" });
      },
    },
    data,
    el
  );
  GDASH.autoResize(el, u, opts.height || 260);
  GDASH.legendTooltips(u, series);
  return u;
};

/* Chart with explicit second scale (e.g. HR + BB).
   Same contract as lineChart: series[0] in uPlot is the x axis, so the
   passed `series` array is prepended with an empty x-series config. */
GDASH.twoScaleChart = function (el, series, x, yArrays, opts = {}) {
  const scales = opts.scales || {
    hr: { auto: true },
    bb: { auto: true },
  };
  const axes = [
    { stroke: "#71717a", grid: { stroke: "#27272a" }, ticks: { stroke: "#3f3f46" }, size: 48, label: "tijd" },
    { stroke: "#71717a", grid: { width: 0 }, ticks: { stroke: "#3f3f46" }, size: 44, scale: "bb", label: "waarde" },
  ];
  const uplotSeries = [{ label: opts.xLabel || "tijd" }].concat(series.map((s, i) => ({
    label: s.label,
    stroke: s.color,
    width: s.width || 1.5,
    fill: s.fill ? s.color + "22" : undefined,
    scale: s.scale,
    points: { show: false },
    spanGaps: true,
    // uPlot calls value(self, raw, seriesIdx, idx) — unwrap the raw datum
    value: (self, v) => (s.value ? s.value(v) : v),
  })));
  const u = new uPlot(
    {
      ...GDASH.seriesOpts,
      width: el.clientWidth || 800,
      height: opts.height || 300,
      scales,
      series: uplotSeries,
      legend: { show: true, live: true },
      axes,
      fmtDate: () => (d) => {
        const dt = d instanceof Date ? d : new Date((Array.isArray(d) ? d[0] : d) * 1000);
        return isNaN(dt.getTime()) ? "" : dt.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
      },
      // uPlot's built-in bands need a second series entry (crashes with
      // series:[1]); paint time-range shading ourselves in a draw hook.
      hooks: { draw: [GDASH.drawBands] },
    },
    [x, ...yArrays],
    el
  );
  u._gdashBands = opts.bands || [];
  GDASH.autoResize(el, u, opts.height || 300);
  GDASH.legendTooltips(u, series);
  return u;
};

/* Paint time-range bands (e.g. activity windows) across the plot area. */
GDASH.drawBands = function (u) {
  const bands = u._gdashBands;
  if (!bands || !bands.length) return;
  const { ctx, bbox } = u;
  ctx.save();
  ctx.beginPath();
  ctx.rect(bbox.left, bbox.top, bbox.width, bbox.height);
  ctx.clip();
  for (const b of bands) {
    const x0 = u.valToPosH(b.from, "x", true);
    const x1 = u.valToPosH(b.to, "x", true);
    ctx.fillStyle = b.fill;
    ctx.fillRect(bbox.left + x0, bbox.top, Math.max(0, x1 - x0), bbox.height);
  }
  ctx.restore();
};

/* Build a hover-tooltip abbreviation element, matching the `abbr()` Jinja
   macro used on the home screen (dotted underline + Alpine x-show tooltip +
   link to the matching /uitleg card). Returns the wrapper <span>. */
GDASH.abbrEl = function (label, meaning, anchor) {
  const wrap = document.createElement("span");
  wrap.className = "relative inline-flex items-center group";
  wrap.setAttribute("x-data", "{ open: false }");

  const link = document.createElement("a");
  link.href = GDASH_ROOT + "/uitleg#" + anchor;
  link.className = "underline decoration-dotted decoration-zinc-600 underline-offset-2 hover:text-zinc-100 hover:decoration-zinc-400";
  link.setAttribute("@mouseenter", "open = true");
  link.setAttribute("@mouseleave", "open = false");
  link.setAttribute("@focus", "open = true");
  link.setAttribute("@blur", "open = false");
  link.textContent = label;

  const tip = document.createElement("span");
  tip.setAttribute("x-show", "open");
  tip.setAttribute("x-cloak", "");
  tip.className = "absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-56 rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-[11px] leading-snug text-zinc-200 shadow-xl z-50 pointer-events-none";
  tip.textContent = meaning;
  const hint = document.createElement("span");
  hint.className = "block mt-1 text-[10px] text-zinc-500";
  hint.textContent = "→ Uitleg";
  tip.appendChild(hint);

  wrap.appendChild(link);
  wrap.appendChild(tip);
  return wrap;
};

/* Wrap each uPlot legend label with an abbreviation tooltip.
   `series` is the y-series config array (the same array passed to
   lineChart/twoScaleChart); entries may carry `abbr: { meaning, anchor }`.
   Call after the chart is created so the legend DOM exists. */
GDASH.legendTooltips = function (u, series) {
  const rows = (u.root || u.over).querySelectorAll(".u-legend .u-series");
  // uPlot prepends the x-axis series (index 0), so row i+1 maps to series[i].
  series.forEach((s, i) => {
    if (!s.abbr) return;
    const row = rows[i + 1];
    if (!row) return;
    const label = row.querySelector(".u-label");
    if (!label) return;
    const text = label.textContent;
    label.textContent = "";
    label.appendChild(GDASH.abbrEl(text, s.abbr.meaning, s.abbr.anchor));
  });
};

/* Keep charts sized to their container (Tailwind's browser build applies
   CSS asynchronously, so charts may init before layout exists). */
GDASH.autoResize = function (el, u, height) {
  const resize = () => {
    if (!el.isConnected) {
      ro.disconnect();
      return;
    }
    const w = el.clientWidth;
    if (w > 0) u.setSize({ width: w, height });
  };
  const ro = new ResizeObserver(resize);
  ro.observe(el);
  resize();
  u._gdashRO = ro;
};
