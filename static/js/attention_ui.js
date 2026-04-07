/**
 * Live attention / gaze readout from dms-metric stream.
 */
(function () {
  const regionEl = document.getElementById("dms-gaze-region");
  const forwardEl = document.getElementById("dms-gaze-forward");
  const WINDOW_MS = 8000;
  const buf = [];

  window.addEventListener("dms-metric", (e) => {
    const d = e.detail;
    if (!d || !regionEl) return;
    const t = performance.now();
    const r = d.gaze_region || "unknown";
    buf.push({ t, r });
    while (buf.length && t - buf[0].t > WINDOW_MS) buf.shift();

    regionEl.textContent = r;
    const fw = buf.filter((x) => x.r === "forward").length / Math.max(1, buf.length);
    if (forwardEl) {
      forwardEl.textContent = `${Math.round(fw * 100)}% forward · last 8s`;
    }
  });
})();
