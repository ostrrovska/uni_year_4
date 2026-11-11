const { WebSocketServer } = require('ws');

const { ClientRegistry, State } = require('./client-registry');
const { BackpressurePolicy } = require('./backpressure-policy');
const { Broadcaster } = require('./broadcaster');
const {
  CloseCode,
  DEFAULT_TOPICS,
  InvalidFrame,
  frames,
  parseClientFrame,
} = require('./ws-protocol');
const { mb } = require('../streams/metrics');

// The WebSocket endpoint and the whole connection lifecycle of requirement 8.
//
// It is mounted with noServer: true and driven from the HTTP server upgrade
// event by hand, rather than letting ws bind itself to the server. Two reasons:
// an upgrade on any path other than /ws gets a proper HTTP response instead of
// a dropped socket, and the handshake stays visible in one readable place -
// which is the part of WebSocket worth seeing at least once.
//
//   Connection      -> register, state=connecting, send welcome, start auth timer
//   Identification  -> first frame must be hello with a valid token
//   Message exchange-> validate, then broadcast / ack / pong
//   Close           -> unregister, announce departure
//
// Loss of a client that never closes cleanly is handled by the heartbeat: a
// killed process leaves a socket that looks open until two pings go unanswered.

function createWebSocketServer({ server, config, log = console.log, getJobs = () => [] }) {
  const settings = config.ws;

  const registry = new ClientRegistry();
  const policy = new BackpressurePolicy({
    enabled: settings.protection,
    softLimitBytes: settings.softLimitBytes,
    hardLimitBytes: settings.hardLimitBytes,
    slowGraceMs: settings.slowGraceMs,
    progressMinIntervalMs: settings.progressMinIntervalMs,
  });
  const broadcaster = new Broadcaster({
    registry,
    policy,
    batchWindowMs: settings.batchWindowMs,
    log,
  });

  // maxPayload is ws refusing an oversized frame at the protocol level, before
  // it is buffered. The check in parseClientFrame covers the same thing for
  // frames that are large but legal, so the error is a protocol answer and not
  // a dropped connection.
  const wss = new WebSocketServer({ noServer: true, maxPayload: settings.maxMessageBytes * 4 });

  const timers = new Set();
  const interval = (fn, ms) => {
    const timer = setInterval(fn, ms);
    timer.unref();
    timers.add(timer);
    return timer;
  };

  server.on('upgrade', (request, socket, head) => {
    const { pathname } = new URL(request.url, `http://${request.headers.host ?? 'localhost'}`);

    if (pathname !== settings.path) {
      socket.write('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n');
      socket.destroy();
      return;
    }

    wss.handleUpgrade(request, socket, head, (ws) => wss.emit('connection', ws, request));
  });

  wss.on('connection', (ws, request) => {
    const client = registry.add({
      socket: ws,
      remoteAddress: request.socket.remoteAddress,
      userAgent: request.headers['user-agent'] ?? null,
      topics: DEFAULT_TOPICS,
    });

    log(`ws connect ${client.clientId} from ${client.remoteAddress} (${registry.size} active)`);

    broadcaster.sendTo(
      client,
      frames.welcome({
        clientId: client.clientId,
        authRequired: true,
        authTimeoutMs: settings.authTimeoutMs,
        serverTime: new Date().toISOString(),
        limits: {
          maxMessageBytes: settings.maxMessageBytes,
          maxTextLength: settings.maxTextLength,
          maxInvalidMessages: settings.maxInvalidMessages,
          softLimitBytes: settings.softLimitBytes,
          hardLimitBytes: settings.hardLimitBytes,
          protection: settings.protection,
        },
      }),
    );

    // An unidentified socket costs a file descriptor and a registry slot. The
    // timer is what stops an opened-and-abandoned connection from keeping them
    // for ever.
    const authTimer = setTimeout(() => {
      if (client.state === State.Connecting) {
        log(`ws auth timeout ${client.clientId}`);
        ws.close(CloseCode.AuthTimeout, 'auth_timeout');
      }
    }, settings.authTimeoutMs);
    authTimer.unref();

    ws.on('pong', () => {
      client.lastPongAt = Date.now();
      client.missedPongs = 0;
    });

    ws.on('message', (raw) => {
      client.counters.received += 1;

      const frame = parseClientFrame(raw, {
        maxBytes: settings.maxMessageBytes,
        maxTextLength: settings.maxTextLength,
      });

      if (frame instanceof InvalidFrame) {
        rejectFrame(client, frame);
        return;
      }

      // Everything before identification is refused, including a well-formed
      // chat message: the server has nothing to put in its "from" field yet.
      if (client.state === State.Connecting && frame.type !== 'hello') {
        rejectFrame(client, new InvalidFrame('not_identified', 'send hello before anything else'));
        return;
      }

      switch (frame.type) {
        case 'hello':
          handleHello(client, frame, authTimer);
          break;
        case 'message':
          handleMessage(client, frame);
          break;
        case 'subscribe':
          handleSubscribe(client, frame);
          break;
        default:
          broadcaster.sendTo(client, frames.pong({}));
      }
    });

    ws.on('close', (code, reason) => {
      clearTimeout(authTimer);
      const removed = registry.remove(client.clientId);
      log(
        `ws close ${client.clientId} code=${code} reason="${reason?.toString() || ''}" ` +
          `sent=${client.counters.sent} dropped=${client.counters.dropped} (${registry.size} active)`,
      );

      if (removed !== null && removed.name !== null) {
        broadcaster.broadcast(
          frames.presence({
            event: 'leave',
            clientId: client.clientId,
            name: client.name,
            total: registry.size,
          }),
        );
      }
    });

    // An error is almost always followed by a close, but not always: a reset
    // connection can land here alone, so the socket is closed explicitly.
    ws.on('error', (error) => {
      log(`ws error ${client.clientId}: ${error.message}`);
      ws.terminate();
    });
  });

  function handleHello(client, frame, authTimer) {
    if (client.state !== State.Connecting) {
      rejectFrame(client, new InvalidFrame('already_identified', 'hello was already accepted'));
      return;
    }

    if (frame.token !== settings.token) {
      client.counters.invalid += 1;
      log(`ws auth failed ${client.clientId}`);
      // No error counter grace here: a wrong credential is not a malformed
      // frame, and retrying on the same socket buys nothing.
      broadcaster.sendTo(client, frames.error({ code: 'unauthenticated', detail: 'invalid token' }));
      client.socket.close(CloseCode.Unauthenticated, 'unauthenticated');
      return;
    }

    clearTimeout(authTimer);
    client.name = frame.name ?? `client-${client.clientId}`;
    client.state = State.Active;

    log(`ws identified ${client.clientId} as "${client.name}"`);

    broadcaster.sendTo(
      client,
      frames.ready({
        client,
        topics: [...client.topics],
        peers: registry
          .active()
          .filter((peer) => peer.clientId !== client.clientId)
          .map((peer) => ({ clientId: peer.clientId, name: peer.name, state: peer.state })),
      }),
    );

    broadcaster.broadcast(
      frames.presence({
        event: 'join',
        clientId: client.clientId,
        name: client.name,
        total: registry.size,
      }),
      { exclude: client.clientId },
    );
  }

  // Requirement 7.2: the server processes the message and passes it to the
  // other connected clients. The sender gets an ack carrying the fan-out
  // result, so "nobody else is connected" and "delivered to three" are
  // distinguishable from the client side.
  function handleMessage(client, frame) {
    const result = broadcaster.broadcast(
      frames.message({ from: client.name, clientId: client.clientId, text: frame.text }),
      { exclude: client.clientId },
    );

    broadcaster.sendTo(client, frames.ack({ of: 'message', detail: result }));
  }

  function handleSubscribe(client, frame) {
    client.topics = new Set(frame.topics);
    broadcaster.sendTo(client, frames.ack({ of: 'subscribe', detail: { topics: [...client.topics] } }));
  }

  // Requirement 8: reacting to an invalid message. One bad frame is answered,
  // not punished; a client that keeps sending them is closed, because at that
  // point it is either broken or hostile and both cost the same.
  function rejectFrame(client, invalid) {
    client.counters.invalid += 1;
    broadcaster.sendTo(client, frames.error({ code: invalid.code, detail: invalid.detail }));

    if (client.counters.invalid >= settings.maxInvalidMessages) {
      log(`ws too many invalid frames from ${client.clientId}, closing`);
      client.socket.close(CloseCode.InvalidFrames, 'too_many_invalid_messages');
    }
  }

  // Requirement 8, last case: loss of a client. A process killed with -9 leaves
  // a socket in readyState OPEN on this side; only an unanswered ping reveals
  // it. terminate() is used rather than close(), because there is nobody left
  // to complete a closing handshake with.
  interval(() => {
    for (const client of registry.list()) {
      if (client.missedPongs >= settings.maxMissedPongs) {
        log(`ws heartbeat lost ${client.clientId}, terminating`);
        client.socket.terminate();
        continue;
      }

      client.missedPongs += 1;
      try {
        client.socket.ping();
      } catch {
        client.socket.terminate();
      }
    }
  }, settings.heartbeatIntervalMs);

  // The live view the dashboard draws: who is connected, how far behind each
  // one is, and what the policy has had to do about it.
  interval(() => {
    if (registry.size === 0) {
      return;
    }

    for (const client of registry.list()) {
      policy.observe(client);
    }

    broadcaster.broadcast(
      frames.stats({
        clients: registry.snapshot(),
        jobs: getJobs(),
        server: {
          rssMB: mb(process.memoryUsage.rss()),
          uptimeSec: Math.round(process.uptime()),
          policy: policy.snapshot(),
          broadcaster: broadcaster.snapshot(),
        },
      }),
    );
  }, settings.statsIntervalMs);

  function snapshot() {
    return {
      path: settings.path,
      clients: registry.snapshot(),
      policy: policy.snapshot(),
      broadcaster: broadcaster.snapshot(),
    };
  }

  async function close() {
    for (const timer of timers) {
      clearInterval(timer);
    }
    timers.clear();
    broadcaster.stop();

    for (const client of registry.list()) {
      client.socket.close(CloseCode.ServerShutdown, 'server_shutdown');
    }

    await new Promise((resolve) => wss.close(resolve));
  }

  return { wss, registry, broadcaster, policy, snapshot, close };
}

module.exports = { createWebSocketServer };
