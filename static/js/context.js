/**
 * Driving simulation: speed, derived road type, session timer, local time/daypart.
 * Exposes window.getDmsDrivingContext() for WebSocket payloads.
 */
(function () {
  const sessionStart = Date.now();

  const speedEl = document.getElementById("speed-slider");
  const speedValEl = document.getElementById("speed-value");
  const roadEl = document.getElementById("road-type");
  const timerEl = document.getElementById("session-timer");
  const clockEl = document.getElementById("local-clock");
  const daypartEl = document.getElementById("daypart");

  function roadTypeFromSpeed(mph) {
    if (mph <= 35) return "city";
    if (mph <= 55) return "suburban";
    return "highway";
  }

  function daypartFromHour(h) {
    if (h >= 5 && h < 12) return "morning";
    if (h >= 12 && h < 17) return "afternoon";
    if (h >= 17 && h < 21) return "evening";
    return "night";
  }

  function formatClock(d) {
    return d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }

  function tick() {
    const mph = speedEl ? Number(speedEl.value) : 0;
    if (speedValEl) speedValEl.textContent = String(mph);
    const rt = roadTypeFromSpeed(mph);
    if (roadEl) roadEl.textContent = rt;

    const elapsedMin = Math.floor((Date.now() - sessionStart) / 60000);
    if (timerEl) timerEl.textContent = String(elapsedMin);

    const now = new Date();
    if (clockEl) clockEl.textContent = formatClock(now);
    const dp = daypartFromHour(now.getHours());
    if (daypartEl) daypartEl.textContent = dp;
  }

  window.setInterval(tick, 500);
  tick();
  if (speedEl) speedEl.addEventListener("input", tick);

  window.getDmsDrivingContext = function () {
    const mph = speedEl ? Number(speedEl.value) : 0;
    const now = new Date();
    const session_elapsed_sec = Math.floor((Date.now() - sessionStart) / 1000);
    return {
      speed_mph: mph,
      road_type: roadTypeFromSpeed(mph),
      session_elapsed_sec,
      time_of_day: now.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
      daypart: daypartFromHour(now.getHours()),
    };
  };

})();
