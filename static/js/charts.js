/**
 * Chart.js sparklines: EAR and MAR over the last 30 seconds (streaming).
 */
(function () {
  const WINDOW_MS = 30_000;
  const points = [];

  function trim() {
    const cutoff = performance.now() - WINDOW_MS;
    while (points.length && points[0].x < cutoff) points.shift();
  }

  let chartEar = null;
  let chartMar = null;

  function initCharts() {
    if (typeof Chart === "undefined") return;

    const commonOpts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 0 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true },
      },
      scales: {
        x: {
          type: "linear",
          display: true,
          min: -30,
          max: 0,
          ticks: {
            color: "#94a3b8",
            maxTicksLimit: 7,
            callback: (v) => `${v}s`,
          },
          grid: { color: "rgba(148,163,184,0.15)" },
        },
        y: {
          display: true,
          ticks: { color: "#94a3b8" },
          grid: { color: "rgba(148,163,184,0.15)" },
        },
      },
    };

    const earEl = document.getElementById("chart-ear");
    const marEl = document.getElementById("chart-mar");
    if (earEl) {
      chartEar = new Chart(earEl.getContext("2d"), {
        type: "line",
        data: {
          datasets: [
            {
              label: "EAR (avg)",
              data: [],
              borderColor: "#38bdf8",
              backgroundColor: "rgba(56,189,248,0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 0,
            },
          ],
        },
        options: {
          ...commonOpts,
          plugins: {
            ...commonOpts.plugins,
            title: { display: true, text: "EAR (30s)", color: "#cbd5e1", font: { size: 11 } },
          },
          scales: {
            ...commonOpts.scales,
            y: { ...commonOpts.scales.y, min: 0, max: 0.5 },
          },
        },
      });
    }
    if (marEl) {
      chartMar = new Chart(marEl.getContext("2d"), {
        type: "line",
        data: {
          datasets: [
            {
              label: "MAR",
              data: [],
              borderColor: "#a78bfa",
              backgroundColor: "rgba(167,139,250,0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 0,
            },
          ],
        },
        options: {
          ...commonOpts,
          plugins: {
            ...commonOpts.plugins,
            title: { display: true, text: "MAR (30s)", color: "#cbd5e1", font: { size: 11 } },
          },
          scales: {
            ...commonOpts.scales,
            y: { ...commonOpts.scales.y, min: 0, max: 0.8 },
          },
        },
      });
    }
  }

  function pushPoint(earAvg, mar) {
    const x = performance.now();
    points.push({ x, ear: earAvg, mar });
    trim();

    const now = performance.now();
    const toSec = (t) => (t - now) / 1000;

    if (chartEar) {
      chartEar.data.datasets[0].data = points.map((p) => ({ x: toSec(p.x), y: p.ear }));
      chartEar.update("none");
    }
    if (chartMar) {
      chartMar.data.datasets[0].data = points.map((p) => ({ x: toSec(p.x), y: p.mar }));
      chartMar.update("none");
    }
  }

  window.addEventListener("dms-metric", (e) => {
    const d = e.detail;
    if (!d) return;
    const earAvg = (Number(d.ear_left) + Number(d.ear_right)) / 2;
    pushPoint(earAvg, Number(d.mar));
  });

  function boot() {
    initCharts();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
