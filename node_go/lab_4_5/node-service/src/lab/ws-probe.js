const WebSocket = require('ws');

// A WebSocket client the server opens against its own endpoint.
//
// The task-by-task page needs results that are produced by pressing a button,
// not by starting a second process in a terminal. So the lab tasks drive real
// clients over a real socket from inside the service: the handshake, the close
// codes and the backpressure are the same as for any other client, because
// nothing here reaches into the server - it only connects to it.
//
// tools/ws-client.js remains the command-line version of the same thing. The
// duplication is deliberate: that one is a tool a person runs and reads, this
// one is a library a task awaits and asserts on.

const DEFAULT_TOPICS = ['chat', 'presence', 'progress', 'chunks', 'stats'];

// Bookkeeping, not data. Defined as non-enumerable so a frame that has been
// handed to a waiter still serialises exactly as it arrived - these frames are
// shown verbatim as evidence on the walkthrough page, and an invented field in
// them would be worse than useless.
function markTaken(frame) {
  Object.defineProperty(frame, '__taken', { value: true, enumerable: false, configurable: true });
}

class WsProbe {
  constructor({
    url,
    token,
    name,
    topics = DEFAULT_TOPICS,
    // Never send hello: shows the server closing on its auth timeout.
    hello = true,
    // Stop reading the socket once identified: the only honest way to look like
    // a slow consumer from the outside.
    slow = false,
    // Destroy the socket without a close handshake, like a killed process.
    killAfterMs = null,
    onFrame = null,
  }) {
    this.url = url;
    this.token = token;
    this.name = name;
    this.topics = topics;
    this.hello = hello;
    this.slow = slow;
    this.killAfterMs = killAfterMs;
    this.onFrame = onFrame;

    this.socket = null;
    this.clientId = null;
    this.readyFrame = null;
    this.waiters = new Set();
    this.frames = [];
    this.byType = {};
    this.bytes = 0;
    this.close = null;
    this.timers = [];

    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });

    // Several probes are never meant to become ready - the one with a wrong
    // token, the one that never identifies - and nobody awaits their "ready".
    // Attaching a handler here marks the rejection as handled, so a probe that
    // is closed before identification does not take the process down with an
    // unhandled rejection. A caller that does await it still sees the error.
    this.ready.catch(() => undefined);
    this.closed = new Promise((resolve) => {
      this.resolveClosed = resolve;
    });
  }

  connect() {
    const socket = new WebSocket(this.url);
    this.socket = socket;

    // The listener is attached before the socket opens. The server sends
    // welcome the instant the handshake completes, so a handler added after
    // waiting for "open" can miss it and then wait for a frame that already
    // came and went.
    socket.on('message', (raw) => this.#onMessage(raw));

    socket.on('close', (code, reason) => {
      this.close = { code, reason: reason?.toString() ?? '' };
      this.#clearTimers();
      this.rejectReady(new Error(`socket closed with ${code} before it was ready`));
      this.resolveClosed(this.summary());
    });

    socket.on('error', () => {
      // A close event follows, which is where the outcome is recorded. Without
      // this handler the error would be thrown as unhandled.
    });

    if (this.killAfterMs !== null) {
      this.#later(() => socket._socket?.destroy(), this.killAfterMs);
    }

    return this;
  }

  #onMessage(raw) {
    this.bytes += raw.length;

    let frame;
    try {
      frame = JSON.parse(raw.toString('utf8'));
    } catch {
      return;
    }

    this.frames.push(frame);
    this.byType[frame.type] = (this.byType[frame.type] ?? 0) + 1;

    if (this.onFrame) {
      this.onFrame(frame);
    }

    // Waiters are served from the stored frame object, so the "already handed
    // out" mark lands on the object that waitFor() will search next time. An
    // earlier version re-parsed the payload in its own listener and marked the
    // copy, which left the stored frame looking fresh and made every second
    // waitFor() return a stale frame.
    for (const waiter of [...this.waiters]) {
      if (waiter.matches(frame)) {
        this.waiters.delete(waiter);
        clearTimeout(waiter.timer);
        markTaken(frame);
        waiter.resolve(frame);
      }
    }

    if (frame.type === 'welcome') {
      this.clientId = frame.clientId;
      if (this.hello) {
        this.send({ type: 'hello', name: this.name, token: this.token });
      }
      return;
    }

    if (frame.type === 'ready') {
      this.readyFrame = frame;
      this.send({ type: 'subscribe', topics: this.topics });
      return;
    }

    // "ready" is resolved only once the server has confirmed the subscription,
    // not when it was sent. Resolving earlier makes every caller race with the
    // server: a broadcast issued right after would be fanned out against the
    // previous topic set.
    if (frame.type === 'ack' && frame.of === 'subscribe' && this.readyFrame !== null) {
      markTaken(frame);

      if (this.slow) {
        // After the subscribe, so the server has this client on the high-volume
        // topics before it stops keeping up with them.
        this.#later(() => this.socket._socket?.pause(), 150);
      }

      this.resolveReady(this.readyFrame);
    }
  }

  // Changes the subscription and waits for the server to confirm it.
  async resubscribe(topics) {
    this.topics = topics;
    this.send({ type: 'subscribe', topics });
    return this.waitFor('ack', { where: (frame) => frame.of === 'subscribe' });
  }

  send(object) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(object));
    }
  }

  raw(text) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(text);
    }
  }

  // Waits for the next frame of a type, or for one that satisfies a predicate.
  waitFor(type, { timeoutMs = 5000, where = null } = {}) {
    const matches = (frame) => frame.type === type && (where === null || where(frame));
    const existing = this.frames.find((frame) => matches(frame) && !frame.__taken);

    if (existing !== undefined) {
      markTaken(existing);
      return Promise.resolve(existing);
    }

    return new Promise((resolve, reject) => {
      const waiter = { matches, resolve, timer: null };

      waiter.timer = setTimeout(() => {
        this.waiters.delete(waiter);
        reject(new Error(`no "${type}" frame within ${timeoutMs} ms`));
      }, timeoutMs);

      this.waiters.add(waiter);
      this.timers.push(waiter.timer);
    });
  }

  // Resolves with the close frame, or with null if the socket is still open.
  waitForClose(timeoutMs = 5000) {
    if (this.close !== null) {
      return Promise.resolve(this.close);
    }

    return Promise.race([
      this.closed.then(() => this.close),
      new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), timeoutMs);
        this.timers.push(timer);
      }),
    ]);
  }

  // A slow probe has stopped reading, so it will never see a close frame come
  // back and the handshake can never finish. terminate() is the only way to let
  // such a client go.
  async stop() {
    this.#clearTimers();

    if (this.socket === null || this.socket.readyState === WebSocket.CLOSED) {
      return this.summary();
    }

    if (this.slow || this.socket.readyState !== WebSocket.OPEN) {
      this.socket.terminate();
    } else {
      this.socket.close(1000, 'probe done');
    }

    await Promise.race([this.closed, new Promise((resolve) => setTimeout(resolve, 1500))]);

    if (this.socket.readyState !== WebSocket.CLOSED) {
      this.socket.terminate();
    }

    return this.summary();
  }

  summary() {
    return {
      name: this.name,
      clientId: this.clientId,
      received: this.frames.length,
      bytes: this.bytes,
      byType: { ...this.byType },
      close: this.close,
    };
  }

  #later(fn, ms) {
    const timer = setTimeout(fn, ms);
    timer.unref();
    this.timers.push(timer);
    return timer;
  }

  #clearTimers() {
    for (const timer of this.timers) {
      clearTimeout(timer);
    }
    this.timers = [];
  }
}

// The common case: connect, identify, subscribe, and resolve once the server
// has said "ready".
async function connectProbe(options) {
  const probe = new WsProbe(options).connect();
  await probe.ready;
  return probe;
}

module.exports = { WsProbe, connectProbe, DEFAULT_TOPICS };
