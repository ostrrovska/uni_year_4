// Tests for requirement 10: what the server does when it produces frames
// faster than a client reads them.
//
// Two levels. The policy is tested directly with a fake socket, because every
// branch of it is a decision about a number and needs no network. The whole
// thing is then tested over a real socket with a client that stops reading, to
// show that bufferedAmount really does grow and that the policy really is
// consulted on the path a frame takes.
const { after, afterEach, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const WebSocket = require('ws');

const { BackpressurePolicy, Action, classify } = require('../src/realtime/backpressure-policy');
const { Broadcaster } = require('../src/realtime/broadcaster');
const { ClientRegistry, State } = require('../src/realtime/client-registry');
const { createWebSocketServer } = require('../src/realtime/ws-server');
const { CloseCode, frames } = require('../src/realtime/ws-protocol');

// Stands in for a ws socket: readyState OPEN, a settable bufferedAmount and a
// record of what was sent.
function fakeSocket(bufferedAmount = 0) {
  return {
    readyState: 1,
    bufferedAmount,
    sent: [],
    closed: null,
    terminated: false,
    send(data, callback) {
      this.sent.push(JSON.parse(data));
      if (callback) {
        callback();
      }
    },
    close(code, reason) {
      this.closed = { code, reason };
      this.readyState = 3;
    },
    terminate() {
      this.terminated = true;
      this.readyState = 3;
    },
  };
}

function registryWith(bufferedAmount = 0, state = State.Active) {
  const registry = new ClientRegistry();
  const socket = fakeSocket(bufferedAmount);
  const client = registry.add({ socket, remoteAddress: '127.0.0.1', userAgent: null, topics: ['chat', 'presence', 'progress', 'chunks', 'stats'] });
  client.state = state;
  client.name = 'fake';
  return { registry, client, socket };
}

describe('frame classification', () => {
  it('separates state, history and protocol frames', () => {
    assert.equal(classify('progress'), 'state');
    assert.equal(classify('stats'), 'state');
    assert.equal(classify('chunk'), 'state');
    assert.equal(classify('message'), 'history');
    assert.equal(classify('presence'), 'history');
    assert.equal(classify('welcome'), 'protocol');
    assert.equal(classify('ack'), 'protocol');
    assert.equal(classify('error'), 'protocol');
  });
});

describe('the policy below the soft limit', () => {
  it('sends everything', () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 1000, progressMinIntervalMs: 0 });
    const { client } = registryWith(500);

    for (const type of ['progress', 'chunk', 'message', 'ack']) {
      assert.equal(policy.decide(client, { type }).action, Action.Send, `${type} should be sent`);
    }
  });
});

describe('mechanism 1 and 4 - dropping and batching past the soft limit', () => {
  it('drops a progress frame and batches a message frame', () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 1000, hardLimitBytes: 100000, progressMinIntervalMs: 0 });
    const { client } = registryWith(2000);

    const progress = policy.decide(client, { type: 'progress' });
    assert.equal(progress.action, Action.Drop);
    assert.equal(progress.reason, 'slow_client');

    assert.equal(policy.decide(client, { type: 'chunk' }).action, Action.Drop);
    assert.equal(policy.decide(client, { type: 'message' }).action, Action.Batch);

    // A protocol frame is never sacrificed: dropping it would break the client.
    assert.equal(policy.decide(client, { type: 'ack' }).action, Action.Send);
    assert.equal(policy.decide(client, { type: 'error' }).action, Action.Send);
  });

  it('marks the client slow and then active again, with hysteresis', () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 1000, progressMinIntervalMs: 0 });
    const { client, socket } = registryWith(0);

    socket.bufferedAmount = 1500;
    policy.observe(client);
    assert.equal(client.state, State.Slow);
    assert.notEqual(client.slowSince, null);

    // Still above half the limit: the state must not flap back yet.
    socket.bufferedAmount = 800;
    policy.observe(client);
    assert.equal(client.state, State.Slow);

    socket.bufferedAmount = 400;
    policy.observe(client);
    assert.equal(client.state, State.Active);
    assert.equal(client.slowSince, null);
  });
});

describe('mechanism 2 - rate limiting', () => {
  it('allows one progress frame per interval and drops the rest', () => {
    const policy = new BackpressurePolicy({ progressMinIntervalMs: 100 });
    const { client } = registryWith(0);

    const now = 1_000_000;
    assert.equal(policy.decide(client, { type: 'progress' }, now).action, Action.Send);

    const tooSoon = policy.decide(client, { type: 'progress' }, now + 50);
    assert.equal(tooSoon.action, Action.Drop);
    assert.equal(tooSoon.reason, 'rate_limited');

    assert.equal(policy.decide(client, { type: 'progress' }, now + 150).action, Action.Send);
    assert.equal(policy.counters.rateLimited, 1);
  });

  it('does not rate-limit anything else', () => {
    const policy = new BackpressurePolicy({ progressMinIntervalMs: 1000 });
    const { client } = registryWith(0);

    const now = 1_000_000;
    assert.equal(policy.decide(client, { type: 'chunk' }, now).action, Action.Send);
    assert.equal(policy.decide(client, { type: 'chunk' }, now + 1).action, Action.Send);
  });
});

describe('frames flagged final', () => {
  it('are never rate-limited away', () => {
    const policy = new BackpressurePolicy({ progressMinIntervalMs: 1000 });
    const { client } = registryWith(0);

    const now = 1_000_000;
    assert.equal(policy.decide(client, { type: 'progress' }, now).action, Action.Send);
    assert.equal(policy.decide(client, { type: 'progress' }, now + 1).action, Action.Drop);

    // Nothing supersedes the last progress frame of a job, so dropping it would
    // leave the client showing 99.9% for ever.
    const final = policy.decide(client, { type: 'progress', final: true }, now + 2);
    assert.equal(final.action, Action.Send);
    assert.equal(final.kind, 'protocol');
  });

  it('are not dropped for a slow client either', () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 1000, hardLimitBytes: 1_000_000, progressMinIntervalMs: 0 });
    const { client } = registryWith(5000);

    assert.equal(policy.decide(client, { type: 'progress' }).action, Action.Drop);
    assert.equal(policy.decide(client, { type: 'progress', final: true }).action, Action.Send);
  });
});

describe('mechanism 3 - queue limit and termination', () => {
  it('waits out the grace period before giving up on the client', () => {
    const policy = new BackpressurePolicy({
      softLimitBytes: 1000,
      hardLimitBytes: 10000,
      slowGraceMs: 500,
      progressMinIntervalMs: 0,
    });
    const { client } = registryWith(20000);

    const now = 1_000_000;
    // Over the hard limit, but only just now: a burst must not cost a client
    // its connection.
    const first = policy.decide(client, { type: 'ack' }, now);
    assert.equal(first.action, Action.Send);

    const during = policy.decide(client, { type: 'ack' }, now + 400);
    assert.equal(during.action, Action.Send);

    const after = policy.decide(client, { type: 'ack' }, now + 600);
    assert.equal(after.action, Action.Close);
    assert.equal(after.code, CloseCode.TooSlow);
    assert.match(after.detail, /stayed above 10000 B/);
  });

  it('forgets the hard limit once the client catches up', () => {
    const policy = new BackpressurePolicy({ hardLimitBytes: 10000, slowGraceMs: 100, progressMinIntervalMs: 0 });
    const { client, socket } = registryWith(20000);

    policy.observe(client, 1000);
    assert.notEqual(client.hardSince, null);

    socket.bufferedAmount = 0;
    policy.observe(client, 1200);
    assert.equal(client.hardSince, null);
    assert.equal(policy.decide(client, { type: 'ack' }, 5000).action, Action.Send);
  });
});

describe('the policy switched off', () => {
  it('sends every frame no matter how far behind the client is', () => {
    const policy = new BackpressurePolicy({ enabled: false, softLimitBytes: 10, hardLimitBytes: 20, slowGraceMs: 0 });
    const { client } = registryWith(50 * 1024 * 1024);

    for (const type of ['progress', 'chunk', 'message']) {
      const decision = policy.decide(client, { type });
      assert.equal(decision.action, Action.Send);
      assert.equal(decision.reason, 'protection_disabled');
    }

    assert.equal(policy.counters.dropped, 0);
    assert.equal(policy.counters.closed, 0);
  });
});

describe('the broadcaster queue limit', () => {
  it('keeps the newest frames and counts the ones it threw away', async () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 100, hardLimitBytes: 1_000_000, progressMinIntervalMs: 0 });
    const { registry, client } = registryWith(500);
    const broadcaster = new Broadcaster({ registry, policy, batchWindowMs: 10, maxQueuedFrames: 3 });

    for (let index = 1; index <= 10; index += 1) {
      broadcaster.sendTo(client, frames.message({ from: 'x', clientId: 'x', text: `m${index}` }));
    }

    assert.equal(broadcaster.snapshot().queued, 3);
    assert.equal(client.counters.dropped, 7);

    broadcaster.flush();
    broadcaster.stop();

    const sent = client.socket.sent.at(-1);
    assert.equal(sent.type, 'batch');
    assert.equal(sent.count, 3);
    assert.deepEqual(sent.frames.map((frame) => frame.text), ['m8', 'm9', 'm10']);
  });

  it('sends a single queued frame as itself rather than a batch of one', () => {
    const policy = new BackpressurePolicy({ softLimitBytes: 100, hardLimitBytes: 1_000_000, progressMinIntervalMs: 0 });
    const { registry, client } = registryWith(500);
    const broadcaster = new Broadcaster({ registry, policy, batchWindowMs: 10 });

    broadcaster.sendTo(client, frames.message({ from: 'x', clientId: 'x', text: 'only' }));
    broadcaster.flush();
    broadcaster.stop();

    assert.equal(client.socket.sent.at(-1).type, 'message');
  });

  it('closes the socket when the policy says to, after telling the client why', () => {
    const policy = new BackpressurePolicy({ hardLimitBytes: 100, slowGraceMs: 0, progressMinIntervalMs: 0 });
    const { registry, client } = registryWith(5000);
    const broadcaster = new Broadcaster({ registry, policy, batchWindowMs: 10 });

    const decision = broadcaster.sendTo(client, frames.progress({ jobId: 'j', processed: 1, total: 2, percent: 50 }));

    assert.equal(decision.action, Action.Close);
    assert.equal(client.socket.closed.code, CloseCode.TooSlow);
    assert.equal(client.socket.sent.at(-1).type, 'error');
    assert.equal(client.state, State.Closing);
  });

  it('refuses to send to a socket that is not open', () => {
    const policy = new BackpressurePolicy();
    const { registry, client } = registryWith(0);
    const broadcaster = new Broadcaster({ registry, policy });

    client.socket.readyState = 3;
    const decision = broadcaster.sendTo(client, frames.pong({}));

    assert.equal(decision.action, Action.Drop);
    assert.equal(decision.reason, 'socket_not_open');
  });
});

// ---------------------------------------------------------------------------
// over a real socket
// ---------------------------------------------------------------------------

const TOKEN = 'test-token';

function config(overrides = {}) {
  return {
    ws: {
      path: '/ws',
      token: TOKEN,
      authTimeoutMs: 2000,
      heartbeatIntervalMs: 60000,
      maxMissedPongs: 2,
      maxInvalidMessages: 10,
      maxMessageBytes: 4096,
      maxTextLength: 200,
      protection: true,
      softLimitBytes: 8 * 1024,
      hardLimitBytes: 32 * 1024,
      slowGraceMs: 200,
      progressMinIntervalMs: 0,
      batchWindowMs: 10,
      statsIntervalMs: 60000,
      ...overrides,
    },
  };
}

let server;
let hub;
let port;
const sockets = new Set();

async function start(overrides) {
  server = http.createServer();
  hub = createWebSocketServer({ server, config: config(overrides), log: () => {} });
  await new Promise((resolve) => server.listen(0, resolve));
  port = server.address().port;
}

async function stop() {
  for (const socket of sockets) {
    socket.terminate();
  }
  sockets.clear();
  await hub.close();
  await new Promise((resolve) => server.close(resolve));
}

// Identifies, subscribes, then stops reading its socket. A Node client that
// merely ignores "message" still drains the connection, so the only way to look
// slow from the outside is to stop reading at the socket.
async function slowClient() {
  const socket = new WebSocket(`ws://127.0.0.1:${port}/ws`);
  sockets.add(socket);

  // The listener goes on before the socket is open. The server sends welcome
  // the moment the handshake completes, so a handler attached after waiting for
  // "open" can miss it and then wait for ever.
  const ready = await new Promise((resolve) => {
    socket.on('message', (raw) => {
      const frame = JSON.parse(raw.toString('utf8'));
      if (frame.type === 'welcome') {
        socket.send(JSON.stringify({ type: 'hello', name: 'slow', token: TOKEN }));
      }
      if (frame.type === 'ready') {
        resolve(frame);
      }
    });
  });

  socket.send(JSON.stringify({ type: 'subscribe', topics: ['chat', 'progress', 'chunks'] }));
  await new Promise((resolve) => setTimeout(resolve, 30));
  socket._socket.pause();

  return { socket, clientId: ready.clientId };
}

function bigChunk(jobId) {
  return frames.chunk({
    jobId,
    seq: 1,
    sampledEvery: 1,
    // Roughly 8 KB per frame, so a few of them pass any socket buffer.
    records: Array.from({ length: 40 }, (unused, index) => ({
      seq: index,
      ts: '2026-11-01T09:00:00.000Z',
      level: 'error',
      service: 'api',
      itemId: index,
      latencyMs: index,
      bucket: 'fast',
      msg: 'repository timeout, padded so the frame is worth measuring'.repeat(2),
    })),
  });
}

describe('a client that stops reading', () => {
  before(() => start());
  after(() => stop());

  it('makes bufferedAmount grow, gets its state changed and its frames dropped', async () => {
    const { clientId } = await slowClient();
    const client = hub.registry.get(clientId);

    // Enough volume to overrun the socket buffers of both ends. Until they are
    // full, bufferedAmount stays at zero however slow the client is - which is
    // itself worth knowing when reading the numbers in the report.
    for (let index = 0; index < 400; index += 1) {
      hub.broadcaster.sendTo(client, bigChunk('job-1'));
    }

    await new Promise((resolve) => setTimeout(resolve, 100));

    assert.ok(client.peakBufferedAmount > 8 * 1024, `peak bufferedAmount was ${client.peakBufferedAmount} B`);
    assert.ok(client.counters.dropped > 0, 'frames should have been dropped for a slow client');
    assert.ok(
      client.counters.dropped + client.counters.sent >= 400,
      'every produced frame must be either sent or counted as dropped',
    );
  });
});

describe('a slow client that stays past the hard limit', () => {
  before(() => start({ softLimitBytes: 4 * 1024, hardLimitBytes: 16 * 1024, slowGraceMs: 50 }));
  after(() => stop());

  it('is closed with the too-slow code', async () => {
    const { clientId } = await slowClient();
    const client = hub.registry.get(clientId);

    // Protocol frames are never dropped, so they are what eventually pushes a
    // non-reading client past the hard limit - a chat ack would do the same.
    //
    // The padding is large and the loop tight on purpose. bufferedAmount only
    // starts rising once the socket buffers at both ends are full, and on a
    // loaded machine those can absorb a megabyte or two; small frames sent
    // slowly make this test depend on how busy the host is.
    const padding = 'x'.repeat(100 * 1024);
    const deadline = Date.now() + 15000;

    while (hub.policy.counters.closed === 0 && Date.now() < deadline) {
      hub.broadcaster.sendTo(client, frames.ack({ of: 'message', detail: { padding } }));
      await new Promise((resolve) => setImmediate(resolve));
    }

    assert.ok(client.peakBufferedAmount > 16 * 1024, `peak bufferedAmount was ${client.peakBufferedAmount} B`);
    assert.ok(hub.policy.counters.closed > 0, 'the policy should have recorded a termination');
    assert.equal(client.state, 'closing');
  });
});

describe('with protection disabled', () => {
  before(() => start({ protection: false, softLimitBytes: 1024, hardLimitBytes: 4096, slowGraceMs: 0 }));
  after(() => stop());

  it('keeps sending and never drops, so the buffer grows unbounded', async () => {
    const { clientId } = await slowClient();
    const client = hub.registry.get(clientId);

    for (let index = 0; index < 400; index += 1) {
      hub.broadcaster.sendTo(client, bigChunk('job-2'));
    }

    await new Promise((resolve) => setTimeout(resolve, 100));

    assert.equal(client.counters.dropped, 0, 'nothing may be dropped with the policy off');
    assert.equal(hub.policy.counters.closed, 0, 'nobody may be closed with the policy off');

    // The frames the client has not read are now held in the server process,
    // which is the failure this whole mechanism exists to prevent.
    assert.ok(
      client.peakBufferedAmount > 32 * 1024,
      `expected a large backlog, peak bufferedAmount was ${client.peakBufferedAmount} B`,
    );
  });
});
