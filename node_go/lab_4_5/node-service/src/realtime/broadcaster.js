const { Action } = require('./backpressure-policy');
const { State } = require('./client-registry');
const { frames, CloseCode } = require('./ws-protocol');

// Fan-out. The only component that calls socket.send().
//
// Everything above it - the WebSocket event handlers, the bridge that forwards
// stream progress - hands it a frame and a target, and it asks the policy what
// to do with each one. That is why there is no place in the codebase where a
// frame can be sent while skipping the slow-client checks, which would quietly
// undo requirement 10.
//
// Which clients a frame reaches is decided here as well, from the topic the
// frame belongs to and the topics each client subscribed to. Progress frames
// are opt-in, so a client that only chats never becomes a slow consumer of the
// data firehose.
const TOPIC_BY_TYPE = {
  message: 'chat',
  presence: 'presence',
  progress: 'progress',
  chunk: 'chunks',
  job_started: 'progress',
  job_done: 'progress',
  job_error: 'progress',
  job_aborted: 'progress',
  stats: 'stats',
};

function topicOf(type) {
  return TOPIC_BY_TYPE[type] ?? null;
}

class Broadcaster {
  constructor({ registry, policy, batchWindowMs = 50, maxQueuedFrames = 50, log = () => {} }) {
    this.registry = registry;
    this.policy = policy;
    this.batchWindowMs = batchWindowMs;
    this.maxQueuedFrames = maxQueuedFrames;
    this.log = log;

    this.queues = new Map();
    this.timer = null;
    this.totals = { produced: 0, delivered: 0, dropped: 0, batched: 0, closed: 0 };
  }

  // Returns the policy decision so callers and tests can assert on it instead
  // of inferring what happened from counters.
  sendTo(client, frame) {
    this.totals.produced += 1;

    if (!client || client.state === State.Closing || client.socket?.readyState !== 1) {
      this.totals.dropped += 1;
      return { action: Action.Drop, reason: 'socket_not_open' };
    }

    const decision = this.policy.decide(client, frame);

    switch (decision.action) {
      case Action.Send:
        this.#write(client, frame);
        return decision;

      case Action.Batch:
        this.#enqueue(client, frame);
        return decision;

      case Action.Close:
        this.#close(client, decision.code ?? CloseCode.TooSlow, decision.reason, decision.detail);
        return decision;

      default:
        client.counters.dropped += 1;
        this.totals.dropped += 1;
        return decision;
    }
  }

  // exclude: a clientId that must not receive the frame. Requirement 7.2 says a
  // chat message goes to the *other* clients, and the sender gets an ack
  // instead, so it can tell "delivered" from "echoed back".
  broadcast(frame, { exclude = null } = {}) {
    const topic = topicOf(frame.type);
    const result = { targeted: 0, delivered: 0, dropped: 0, batched: 0, closed: 0 };

    for (const client of this.registry.active()) {
      if (exclude !== null && client.clientId === exclude) {
        continue;
      }
      if (topic !== null && !client.topics.has(topic)) {
        continue;
      }

      result.targeted += 1;
      const decision = this.sendTo(client, frame);

      if (decision.action === Action.Send) result.delivered += 1;
      else if (decision.action === Action.Batch) result.batched += 1;
      else if (decision.action === Action.Close) result.closed += 1;
      else result.dropped += 1;
    }

    return result;
  }

  // Mechanism 4: batching. Frames that must not be lost are held for one
  // window and then sent as a single frame - one send() instead of twenty, and
  // one bounded queue instead of an unbounded socket buffer.
  #enqueue(client, frame) {
    let queue = this.queues.get(client.clientId);
    if (queue === undefined) {
      queue = [];
      this.queues.set(client.clientId, queue);
    }

    queue.push(frame);
    client.counters.batched += 1;
    this.totals.batched += 1;

    // Mechanism 3 applied to our own queue: a client that never drains would
    // otherwise turn this array into the unbounded buffer we moved the data out
    // of. Past the limit the oldest frames go, and the drop is counted.
    while (queue.length > this.maxQueuedFrames) {
      queue.shift();
      client.counters.dropped += 1;
      this.totals.dropped += 1;
    }

    if (this.timer === null) {
      this.timer = setInterval(() => this.flush(), this.batchWindowMs);
      this.timer.unref();
    }
  }

  flush() {
    for (const [clientId, queue] of this.queues) {
      const client = this.registry.get(clientId);

      if (client === null || client.socket?.readyState !== 1) {
        this.queues.delete(clientId);
        continue;
      }

      if (queue.length === 0) {
        this.queues.delete(clientId);
        continue;
      }

      // A batch is a protocol frame, so the policy lets it through unless the
      // client is past the hard limit - in which case it stays queued and the
      // queue limit above decides what survives.
      const buffered = this.policy.observe(client);
      if (buffered > this.policy.hardLimitBytes) {
        continue;
      }

      const batch = queue.length === 1 ? queue[0] : frames.batch({ frames: [...queue] });
      queue.length = 0;
      this.#write(client, batch);
    }

    if (this.queues.size === 0 && this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  #write(client, frame) {
    client.counters.sent += 1;
    this.totals.delivered += 1;
    // The ws callback is where a send failure surfaces; without it an error on
    // a half-closed socket becomes an unhandled "error" event on the server.
    client.socket.send(JSON.stringify(frame), (error) => {
      if (error) {
        this.log(`send to ${client.clientId} failed: ${error.message}`);
      }
    });
  }

  #close(client, code, reason, detail) {
    client.state = State.Closing;
    this.totals.closed += 1;
    this.log(`closing ${client.clientId}: ${reason} (${detail ?? 'no detail'})`);

    // The client is told why before the socket goes, which is the difference
    // between a protocol-level decision and a crash.
    try {
      client.socket.send(JSON.stringify(frames.error({ code: reason, detail: detail ?? null })));
    } catch {
      // The socket is already gone; the close below is still correct.
    }

    client.socket.close(code, reason);

    // A client that has stopped reading will not complete the closing
    // handshake either, so the socket is destroyed if it is still there after
    // one grace step.
    const killer = setTimeout(() => {
      if (client.socket.readyState !== 3) {
        client.socket.terminate();
      }
    }, 1000);
    killer.unref();
  }

  stop() {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.queues.clear();
  }

  snapshot() {
    return { ...this.totals, queued: [...this.queues.values()].reduce((sum, q) => sum + q.length, 0) };
  }
}

module.exports = { Broadcaster, topicOf, TOPIC_BY_TYPE };
