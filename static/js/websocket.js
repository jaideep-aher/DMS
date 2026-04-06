(function () {
  const BATCH_MS = 200;
  const queue = [];
  let ws = null;
  let sessionId = null;
  let flushTimer = null;

  function wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/metrics`;
  }

  function flush() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (queue.length === 0) return;
    const samples = queue.splice(0, queue.length);
    ws.send(JSON.stringify({ session_id: sessionId, samples }));
  }

  function connect() {
    ws = new WebSocket(wsUrl());

    ws.addEventListener("open", () => {
      if (flushTimer) clearInterval(flushTimer);
      flushTimer = window.setInterval(flush, BATCH_MS);
    });

    ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "hello" && msg.session_id) {
          sessionId = msg.session_id;
          window.__DMS_SESSION_ID__ = sessionId;
        }
      } catch {
        /* ignore */
      }
    });

    ws.addEventListener("close", () => {
      if (flushTimer) {
        clearInterval(flushTimer);
        flushTimer = null;
      }
      sessionId = null;
      window.__DMS_SESSION_ID__ = null;
      window.setTimeout(connect, 2000);
    });

    ws.addEventListener("error", () => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    });
  }

  window.addEventListener("dms-metric", (e) => {
    if (e && e.detail) queue.push(e.detail);
  });

  connect();
})();
