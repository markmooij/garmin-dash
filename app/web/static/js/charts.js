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
