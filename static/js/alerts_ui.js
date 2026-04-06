/**
 * Alert banner, history sidebar, optional speech for moderate+ severities.
 */
(function () {
  const banner = document.getElementById("alert-banner");
  const bannerText = document.getElementById("alert-banner-text");
  const historyEl = document.getElementById("alert-history");

  const SEVERITY_CLASS = {
    none: "sev-none",
    mild: "sev-mild",
    moderate: "sev-moderate",
    severe: "sev-severe",
  };

  function setBanner(severity, text) {
    if (!banner || !bannerText) return;
    banner.classList.remove("sev-none", "sev-mild", "sev-moderate", "sev-severe");
    const cls = SEVERITY_CLASS[severity] || "sev-none";
    banner.classList.add(cls);
    bannerText.textContent = text || "Monitoring…";
  }

  function appendHistory(severity, text, ts) {
    if (!historyEl) return;
    const li = document.createElement("li");
    const t = new Date(ts * 1000).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
    li.innerHTML = `<span class="ah-sev">${severity}</span> <span class="ah-time">${t}</span><div class="ah-msg">${escapeHtml(
      text
    )}</div>`;
    historyEl.insertBefore(li, historyEl.firstChild);
    while (historyEl.children.length > 30) {
      historyEl.removeChild(historyEl.lastChild);
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function speak(text) {
    if (!window.speechSynthesis || !text) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1;
      window.speechSynthesis.speak(u);
    } catch {
      /* ignore */
    }
  }

  async function refreshHistoryFromApi() {
    const sid = window.__DMS_SESSION_ID__;
    if (!sid) return;
    try {
      const r = await fetch(`/api/alerts?session_id=${encodeURIComponent(sid)}`);
      if (!r.ok) return;
      const data = await r.json();
      if (!historyEl || !data.alerts) return;
      historyEl.innerHTML = "";
      data.alerts
        .slice()
        .reverse()
        .forEach((a) => {
          appendHistory(a.severity, a.alert_text, a.timestamp);
        });
    } catch {
      /* ignore */
    }
  }

  window.addEventListener("dms-ws", (ev) => {
    const msg = ev.detail;
    if (!msg || typeof msg !== "object") return;

    if (msg.type === "hello" && msg.session_id) {
      setBanner("none", "Monitoring — connected. No alerts yet.");
      refreshHistoryFromApi();
      return;
    }

    if (msg.type === "alert" && msg.v === 1) {
      const sev = msg.severity || "mild";
      setBanner(sev, msg.alert_text || "");
      appendHistory(sev, msg.alert_text || "", msg.timestamp);
      if (sev === "moderate" || sev === "severe") {
        speak(msg.alert_text || "");
      }
    }
  });

  setBanner("none", "Connecting…");
})();
