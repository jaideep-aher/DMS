/**
 * websocket.js — WebSocket client for streaming metric batches to backend
 */

class MetricsWSClient {
  constructor(onAck) {
    this.onAck       = onAck || (() => {});
    this.sessionId   = null;
    this.ws          = null;
    this.buffer      = [];
    this.flushInterval = null;
    this.reconnectTimer = null;
    this.reconnectDelay = 2000;
    this.maxReconnectDelay = 30000;
    this._closed = false;
  }

  connect() {
    this._closed = false;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url   = `${proto}://${location.host}/ws/metrics`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] Connected');
      this.reconnectDelay = 2000;
      this._startFlush();
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'connected') {
          this.sessionId = msg.session_id;
          console.log('[WS] Session:', this.sessionId);
        } else if (msg.type === 'ack') {
          this.onAck(msg);
        }
      } catch (e) {
        console.warn('[WS] Bad message:', e);
      }
    };

    this.ws.onclose = () => {
      console.warn('[WS] Disconnected');
      this._stopFlush();
      if (!this._closed) this._scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
    };
  }

  push(frame) {
    this.buffer.push(frame);
    // Keep buffer capped — drop oldest if too far behind
    if (this.buffer.length > 50) this.buffer.shift();
  }

  _startFlush() {
    this.flushInterval = setInterval(() => this._flush(), 200);
  }

  _stopFlush() {
    clearInterval(this.flushInterval);
    this.flushInterval = null;
  }

  _flush() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    if (this.buffer.length === 0) return;

    const batch = this.buffer.splice(0);
    try {
      this.ws.send(JSON.stringify({ frames: batch }));
    } catch (e) {
      console.warn('[WS] Send error:', e);
    }
  }

  _scheduleReconnect() {
    console.log(`[WS] Reconnecting in ${this.reconnectDelay}ms`);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  close() {
    this._closed = true;
    this._stopFlush();
    clearTimeout(this.reconnectTimer);
    if (this.ws) this.ws.close();
  }
}
