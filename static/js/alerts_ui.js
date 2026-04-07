/**
 * Severity badge, alert card, bottom log, speech (moderate+).
 */
(function () {
  const badge = document.getElementById("severity-badge");
  const cardText = document.getElementById("alert-card-text");
  const historyEl = document.getElementById("alert-history");

  const BADGE_BASE =
    "severity-badge text-xl sm:text-2xl md:text-3xl font-semibold tracking-tight px-5 py-2.5 rounded-xl border transition-all duration-300";

  const BADGE_STYLES = {
    none: "bg-[#122420] text-[#9fd4c4] border-[#2f5c4f] shadow-none",
    mild: "bg-[#1c1a14] text-[#dcc9a0] border-[#4a4334]",
    moderate: "bg-[#231a16] text-[#e8c4ae] border-[#5c3f32]",
    severe: "bg-[#1f1215] text-[#f0c8cf] border-[#5c3038]",
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

  function appendHistory(severity, text, ts, category) {
    if (!historyEl) return;
    const li = document.createElement("li");
    li.className =
      "rounded-xl border border-dms-line bg-dms-lift/40 px-3.5 py-2.5 text-xs md:text-sm";
    const t = new Date(ts * 1000).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    });
    const sevClass =
      {
        mild: "text-[#c9a86e]",
        moderate: "text-[#d4a090]",
        severe: "text-[#e8a0a8]",
        none: "text-dms-dim",
      }[severity] || "text-dms-muted";

    const cat = category === "distraction" ? "visual" : "fatigue";
    const catClass =
      cat === "visual" ? "text-[#81a8c4]" : "text-dms-dim";

    li.innerHTML = `<div class="flex flex-wrap items-baseline gap-2 mb-1"><span class="font-semibold uppercase tracking-[0.12em] text-[10px] ${sevClass}">${escapeHtml(
      severity
    )}</span><span class="font-medium uppercase tracking-[0.1em] text-[9px] ${catClass}">${escapeHtml(
      cat
    )}</span><span class="text-dms-dim font-mono text-[10px]">${escapeHtml(t)}</span></div><p class="text-dms-ink/90 leading-snug">${escapeHtml(
      text
    )}</p>`;
    historyEl.insertBefore(li, historyEl.firstChild);
    while (historyEl.children.length > 40) {
      historyEl.removeChild(historyEl.lastChild);
    }
  }

  function categoryFromReasoning(reasoning) {
    const r = (reasoning && String(reasoning)) || "";
    return r.toLowerCase().startsWith("distraction") ? "distraction" : "fatigue";
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
          appendHistory(a.severity, a.alert_text, a.timestamp, categoryFromReasoning(a.reasoning));
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
      appendHistory(sev, msg.alert_text || "", msg.timestamp, msg.category);
      if (sev === "moderate" || sev === "severe") {
        speak(msg.alert_text || "");
      }
    }
  });

  setSeverityUI("none", "Connecting…");
})();
