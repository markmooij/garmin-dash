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
   series: [{ label, color, width?, fill?, scale? }]
   x: epoch-seconds array; y: parallel arrays (nulls allowed). */
GDASH.lineChart = function (el, series, x, yArrays, opts = {}) {
  const data = [x, ...yArrays];
  const uplotSeries = series.map((s, i) => ({
    label: s.label,
    stroke: s.color,
    width: s.width || 1.5,
    fill: s.fill ? s.color + "22" : undefined,
    scale: s.scale || "%",
    points: { show: false },
    spanGaps: true,
    value: s.value,
  }));
  const axes = [
    { stroke: "#71717a", grid: { stroke: "#27272a" }, ticks: { stroke: "#3f3f46" }, size: 48 },
    { stroke: "#71717a", grid: { width: 0 }, ticks: { stroke: "#3f3f46" }, size: 44, scale: "%" },
  ];
  if (opts.scales) {
    for (const [key, conf] of Object.entries(opts.scales)) {
      axes[1] = { ...axes[1], ...conf.axis };
    }
  }
  return new uPlot(
    {
      ...GDASH.seriesOpts,
      width: el.clientWidth || 800,
      height: opts.height || 260,
      scales: opts.scales || { "%": { auto: true } },
      legend: { show: true, live: true },
      axes,
      fmtDate: (d) => new Date(d[0] * 1000).toLocaleDateString("nl-NL", { day: "2-digit", month: "short" }),
    },
    data,
    el
  );
};

/* Chart with explicit second scale (e.g. HR + BB). */
GDASH.twoScaleChart = function (el, series, x, yArrays, opts = {}) {
  const scales = opts.scales || {
    hr: { auto: true },
    bb: { auto: true },
  };
  const axes = [
    { stroke: "#71717a", grid: { stroke: "#27272a" }, ticks: { stroke: "#3f3f46" }, size: 48 },
    { stroke: "#71717a", grid: { width: 0 }, ticks: { stroke: "#3f3f46" }, size: 44, scale: "bb" },
  ];
  return new uPlot(
    {
      ...GDASH.seriesOpts,
      width: el.clientWidth || 800,
      height: opts.height || 300,
      scales,
      legend: { show: true, live: true },
      axes,
      fmtDate: (d) => new Date(d[0] * 1000).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" }),
      bands: opts.bands || [],
    },
    [x, ...yArrays],
    el
  );
};
