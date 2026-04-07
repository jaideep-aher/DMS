/**
 * Chart.js sparklines: EAR and MAR over the last 30 seconds (streaming).
 */
(function () {
  const WINDOW_MS = 30_000;
  const points = [];

  const TICK = "#6b7288";
  const GRID = "rgba(228, 232, 240, 0.06)";
  const TITLE = "#9ca3af";

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
        tooltip: {
          enabled: true,
          backgroundColor: "rgba(19, 22, 28, 0.95)",
          titleColor: "#e8eaef",
          bodyColor: "#c9cdd5",
          borderColor: "rgba(228,232,240,0.1)",
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          type: "linear",
          display: true,
          min: -30,
          max: 0,
          ticks: {
            color: TICK,
            maxTicksLimit: 7,
            callback: (v) => `${v}s`,
            font: { size: 10, family: "'JetBrains Mono', monospace" },
          },
          grid: { color: GRID },
          border: { display: false },
        },
        y: {
          display: true,
          ticks: {
            color: TICK,
            font: { size: 10, family: "'JetBrains Mono', monospace" },
          },
          grid: { color: GRID },
          border: { display: false },
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
              borderColor: "#5cb39a",
              backgroundColor: "rgba(92, 179, 154, 0.14)",
              fill: true,
              tension: 0.35,
              pointRadius: 0,
              borderWidth: 1.5,
            },
          ],
        },
        options: {
          ...commonOpts,
          plugins: {
            ...commonOpts.plugins,
            title: {
              display: true,
              text: "Eye aspect ratio",
              color: TITLE,
              font: { size: 10, weight: "600", family: "'DM Sans', sans-serif" },
              padding: { bottom: 6 },
            },
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
              borderColor: "#c9a07a",
              backgroundColor: "rgba(201, 160, 122, 0.12)",
              fill: true,
              tension: 0.35,
              pointRadius: 0,
              borderWidth: 1.5,
            },
          ],
        },
        options: {
          ...commonOpts,
          plugins: {
            ...commonOpts.plugins,
            title: {
              display: true,
              text: "Mouth aspect ratio",
              color: TITLE,
              font: { size: 10, weight: "600", family: "'DM Sans', sans-serif" },
              padding: { bottom: 6 },
            },
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
