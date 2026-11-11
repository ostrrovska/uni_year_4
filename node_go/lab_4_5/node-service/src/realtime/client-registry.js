const crypto = require('node:crypto');

// Requirement 7.1: the server keeps a list of active WebSocket connections.
//
// The registry owns that list and nothing else. It does not send, it does not
// decide policy, it does not touch a socket - it records what is known about
// each connection, which is what lets both the WebSocket module and an ordinary
// HTTP endpoint (GET /api/ws/clients) read the same truth without one of them
// reaching into the other.
//
// The lifecycle is explicit rather than implied by which fields happen to be
// set, because every transition in requirement 8 has to be observable:
//
//   connecting --hello ok--> active --buffer over soft limit--> slow
//        |                     |  ^------------buffer drained------|
//        |                     |
//        +--timeout/bad token--+--close/terminate--> (removed)
const State = {
  Connecting: 'connecting',
  Active: 'active',
  Slow: 'slow',
  Closing: 'closing',
};

class ClientRecord {
  constructor({ socket, remoteAddress, userAgent, topics }) {
    // Short enough to read in a log line, long enough not to collide.
    this.clientId = crypto.randomUUID().slice(0, 8);
    this.socket = socket;
    this.name = null;
    this.connectedAt = new Date().toISOString();
    this.connectedAtMs = Date.now();
    this.state = State.Connecting;
    this.remoteAddress = remoteAddress;
    this.userAgent = userAgent;
    this.topics = new Set(topics);

    this.counters = { sent: 0, received: 0, dropped: 0, invalid: 0, batched: 0 };

    // Heartbeat bookkeeping: see the ping loop in ws-server.js.
    this.lastPongAt = Date.now();
    this.missedPongs = 0;

    // Backpressure bookkeeping, kept here because the policy must be able to
    // ask "how long has this client been behind", not just "is it behind now".
    this.slowSince = null;
    this.hardSince = null;
    this.peakBufferedAmount = 0;
    this.lastProgressSentAt = 0;
  }

  // The socket itself is never exposed: a snapshot has to be safe to serialise
  // into an HTTP response or a stats frame.
  toJSON() {
    return {
      clientId: this.clientId,
      name: this.name,
      connectedAt: this.connectedAt,
      uptimeMs: Date.now() - this.connectedAtMs,
      state: this.state,
      remoteAddress: this.remoteAddress,
      topics: [...this.topics],
      bufferedAmount: this.socket?.bufferedAmount ?? 0,
      peakBufferedAmount: this.peakBufferedAmount,
      slowForMs: this.slowSince === null ? 0 : Date.now() - this.slowSince,
      overHardLimitForMs: this.hardSince === null ? 0 : Date.now() - this.hardSince,
      ...this.counters,
    };
  }
}

class ClientRegistry {
  constructor() {
    this.clients = new Map();
    this.totalConnections = 0;
  }

  add(options) {
    const client = new ClientRecord(options);
    this.clients.set(client.clientId, client);
    this.totalConnections += 1;
    return client;
  }

  get(clientId) {
    return this.clients.get(clientId) ?? null;
  }

  // Looking a record up by socket is what the ws event handlers need, since ws
  // hands them the socket and not our id.
  bySocket(socket) {
    for (const client of this.clients.values()) {
      if (client.socket === socket) {
        return client;
      }
    }
    return null;
  }

  remove(clientId) {
    const client = this.clients.get(clientId) ?? null;
    this.clients.delete(clientId);
    return client;
  }

  list() {
    return [...this.clients.values()];
  }

  get size() {
    return this.clients.size;
  }

  // Only clients past identification receive broadcasts: a socket still in
  // "connecting" has not proved who it is.
  active() {
    return this.list().filter((client) => client.state === State.Active || client.state === State.Slow);
  }

  snapshot() {
    const clients = this.list().map((client) => client.toJSON());
    return {
      total: clients.length,
      totalConnections: this.totalConnections,
      byState: clients.reduce((acc, client) => {
        acc[client.state] = (acc[client.state] ?? 0) + 1;
        return acc;
      }, {}),
      totalDropped: clients.reduce((sum, client) => sum + client.dropped, 0),
      clients,
    };
  }
}

module.exports = { ClientRegistry, ClientRecord, State };
