/**
 * Severity badge, alert card, bottom log, speech (moderate+).
 */
(function () {
  const badge = document.getElementById("severity-badge");
  const cardText = document.getElementById("alert-card-text");
  const historyEl = document.getElementById("alert-history");

  const BADGE_BASE =
    "severity-badge text-xl sm:text-2xl md:text-3xl font-bold px-4 py-2 rounded-xl border-2 transition-all duration-300";

  const BADGE_STYLES = {
    none: "bg-emerald-950/90 text-emerald-300 border-emerald-600/80",
    mild: "bg-amber-950/90 text-amber-200 border-amber-600",
    moderate: "bg-orange-950/90 text-orange-200 border-orange-500",
    severe: "bg-red-950/90 text-red-200 border-red-500",
  };

  const LABELS = { none: "NONE", mild: "MILD", moderate: "MODERATE", severe: "SEVERE" };

  function setSeverityUI(severity, alertText) {
    const sev = BADGE_STYLES[severity] ? severity : "none";
    if (badge) {
      badge.dataset.severity = sev;
      badge.textContent = LABELS[sev] || "NONE";
      badge.className = BADGE_BASE + " " + BADGE_STYLES[sev];
      if (sev !== "none") {
        badge.classList.add("animate-pulse-alert");
      } else {
        badge.classList.remove("animate-pulse-alert");
      }
    }
    if (cardText) {
      cardText.textContent =
        alertText ||
        (sev === "none" ? "No active alert. Monitoring physiological signals." : "—");
    }
  }

  function appendHistory(severity, text, ts) {
    if (!historyEl) return;
    const li = document.createElement("li");
    li.className =
      "rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-xs md:text-sm";
    const t = new Date(ts * 1000).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
    const sevClass =
      {
        mild: "text-amber-400",
        moderate: "text-orange-400",
        severe: "text-red-400",
        none: "text-slate-500",
      }[severity] || "text-slate-400";

    li.innerHTML = `<div class="flex flex-wrap items-baseline gap-2 mb-1"><span class="font-bold uppercase tracking-wide ${sevClass}">${escapeHtml(
      severity
    )}</span><span class="text-slate-500 font-mono text-[10px]">${escapeHtml(t)}</span></div><p class="text-slate-200 leading-snug">${escapeHtml(
      text
    )}</p>`;
    historyEl.insertBefore(li, historyEl.firstChild);
    while (historyEl.children.length > 40) {
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
      setSeverityUI("none", "Connected. No alerts yet.");
      refreshHistoryFromApi();
      return;
    }

    if (msg.type === "alert" && msg.v === 1) {
      const sev = msg.severity || "mild";
      setSeverityUI(sev, msg.alert_text || "");
      appendHistory(sev, msg.alert_text || "", msg.timestamp);
      if (sev === "moderate" || sev === "severe") {
        speak(msg.alert_text || "");
      }
    }
  });

  setSeverityUI("none", "Connecting…");
})();
