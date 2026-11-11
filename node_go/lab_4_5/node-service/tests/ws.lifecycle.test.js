// WebSocket lifecycle tests, against a real server on an ephemeral port with
// real client sockets - the same approach the lab 4 API tests take, for the same
// reason: the parts being tested are the handshake, the ordering and the close
// codes, none of which exist below the socket.
//
// Timeouts in the configuration are cut down to tens of milliseconds, so the
// auth-timeout and heartbeat cases finish in a test run rather than in a minute.
const { after, afterEach, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const WebSocket = require('ws');

const { createWebSocketServer } = require('../src/realtime/ws-server');
const { CloseCode } = require('../src/realtime/ws-protocol');

const TOKEN = 'test-token';

function testConfig(overrides = {}) {
  return {
    ws: {
      path: '/ws',
      token: TOKEN,
      authTimeoutMs: 150,
      heartbeatIntervalMs: 60000,
      maxMissedPongs: 2,
      maxInvalidMessages: 3,
      maxMessageBytes: 2048,
      maxTextLength: 50,
      protection: true,
      softLimitBytes: 256 * 1024,
      hardLimitBytes: 4 * 1024 * 1024,
      slowGraceMs: 3000,
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
const open = new Set();

async function startServer(overrides = {}) {
  server = http.createServer((req, res) => res.end('ok'));
  hub = createWebSocketServer({ server, config: testConfig(overrides), log: () => {} });

  await new Promise((resolve) => server.listen(0, resolve));
  port = server.address().port;
}

before(() => startServer());

after(async () => {
  await hub.close();
  await new Promise((resolve) => server.close(resolve));
});

afterEach(async () => {
  for (const socket of open) {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.terminate();
    }
  }
  open.clear();

  // Give the server its close events before the next test counts clients.
  await new Promise((resolve) => setTimeout(resolve, 30));
});

// A tiny client: collects frames, and lets a test wait for the next frame of a
// given type instead of sleeping and hoping.
function connect(path = '/ws') {
  const socket = new WebSocket(`ws://127.0.0.1:${port}${path}`);
  open.add(socket);

  const frames = [];
  const waiters = [];

  socket.on('message', (raw) => {
    const frame = JSON.parse(raw.toString('utf8'));
    frames.push(frame);

    for (const waiter of [...waiters]) {
      if (waiter.type === frame.type) {
        waiters.splice(waiters.indexOf(waiter), 1);
        waiter.resolve(frame);
      }
    }
  });

  const client = {
    socket,
    frames,
    send: (object) => socket.send(JSON.stringify(object)),
    raw: (text) => socket.send(text),
    typesSeen: () => frames.map((frame) => frame.type),
    count: (type) => frames.filter((frame) => frame.type === type).length,

    next(type, timeoutMs = 2000) {
      const existing = frames.find((frame) => frame.type === type && !frame.__taken);
      if (existing !== undefined) {
        existing.__taken = true;
        return Promise.resolve(existing);
      }

      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`no "${type}" frame within ${timeoutMs} ms`)), timeoutMs);
        waiters.push({
          type,
          resolve: (frame) => {
            clearTimeout(timer);
            // Marked here as well as on the synchronous path, or a frame
            // awaited before it arrived would be handed out a second time.
            frame.__taken = true;
            resolve(frame);
          },
        });
      });
    },

    closed(timeoutMs = 2000) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`socket did not close within ${timeoutMs} ms`)), timeoutMs);
        socket.once('close', (code, reason) => {
          clearTimeout(timer);
          resolve({ code, reason: reason.toString() });
        });
      });
    },
  };

  return client;
}

async function identified(name = 'tester', topics = ['chat', 'presence', 'progress', 'chunks', 'stats']) {
  const client = connect();
  await client.next('welcome');
  client.send({ type: 'hello', name, token: TOKEN });
  const ready = await client.next('ready');
  client.send({ type: 'subscribe', topics });
  await client.next('ack');
  return { client, ready };
}

describe('connection', () => {
  it('registers the client and sends a welcome frame first', async () => {
    const client = connect();
    const welcome = await client.next('welcome');

    assert.equal(client.typesSeen()[0], 'welcome');
    assert.match(welcome.clientId, /^[0-9a-f-]{8}$/);
    assert.equal(welcome.authRequired, true);
    assert.equal(welcome.authTimeoutMs, 150);
    assert.equal(welcome.limits.maxTextLength, 50);

    assert.equal(hub.registry.size, 1);
    assert.equal(hub.registry.get(welcome.clientId).state, 'connecting');
  });

  it('answers 404 to an upgrade on another path', async () => {
    const client = connect('/not-ws');
    const error = await new Promise((resolve) => client.socket.once('error', resolve));
    assert.match(error.message, /404/);
  });
});

describe('identification', () => {
  it('accepts a valid token and reports the state', async () => {
    const { client, ready } = await identified('alice');

    assert.equal(ready.name, 'alice');
    assert.equal(ready.state, 'active');
    assert.deepEqual(ready.peers, []);
    assert.equal(hub.registry.get(ready.clientId).state, 'active');
    assert.ok(client.count('welcome') === 1);
  });

  it('closes a connection that sends a wrong token', async () => {
    const client = connect();
    await client.next('welcome');
    client.send({ type: 'hello', name: 'intruder', token: 'wrong' });

    const error = await client.next('error');
    assert.equal(error.code, 'unauthenticated');

    const closed = await client.closed();
    assert.equal(closed.code, CloseCode.Unauthenticated);
    assert.equal(hub.registry.size, 0);
  });

  it('closes a connection that never identifies', async () => {
    const client = connect();
    await client.next('welcome');

    const closed = await client.closed();
    assert.equal(closed.code, CloseCode.AuthTimeout);
    assert.equal(closed.reason, 'auth_timeout');
  });

  it('refuses any other frame before hello', async () => {
    const client = connect();
    await client.next('welcome');
    client.send({ type: 'message', text: 'too early' });

    const error = await client.next('error');
    assert.equal(error.code, 'not_identified');
  });

  it('refuses a second hello', async () => {
    const { client } = await identified();
    client.send({ type: 'hello', name: 'again', token: TOKEN });

    const error = await client.next('error');
    assert.equal(error.code, 'already_identified');
  });

  it('lists the clients already present', async () => {
    const first = await identified('first');
    const second = await identified('second');

    assert.equal(second.ready.peers.length, 1);
    assert.equal(second.ready.peers[0].name, 'first');

    const presence = await first.client.next('presence');
    assert.equal(presence.event, 'join');
    assert.equal(presence.name, 'second');
    assert.equal(presence.total, 2);
  });
});

describe('message exchange', () => {
  it('delivers a message to the other clients and not to the sender', async () => {
    const alice = await identified('alice');
    const bob = await identified('bob');
    await alice.client.next('presence');

    alice.client.send({ type: 'message', text: 'hello bob' });

    const delivered = await bob.client.next('message');
    assert.equal(delivered.from, 'alice');
    assert.equal(delivered.text, 'hello bob');
    assert.equal(delivered.clientId, alice.ready.clientId);

    const ack = await alice.client.next('ack');
    assert.equal(ack.of, 'message');
    assert.equal(ack.detail.delivered, 1);

    // The sender must not see its own text echoed as a broadcast.
    assert.equal(alice.client.count('message'), 0);
  });

  it('acks with zero deliveries when nobody else is connected', async () => {
    const { client } = await identified();
    client.send({ type: 'message', text: 'anyone there' });

    const ack = await client.next('ack');
    assert.equal(ack.detail.targeted, 0);
    assert.equal(ack.detail.delivered, 0);
  });

  it('answers a ping with a pong', async () => {
    const { client } = await identified();
    client.send({ type: 'ping' });

    const pong = await client.next('pong');
    assert.ok(pong.at);
  });

  it('respects the topics a client subscribed to', async () => {
    // Subscribed to chat alone, so this client gets no presence frame either -
    // which is why there is nothing to wait for before the broadcast below.
    const chatOnly = await identified('chatty', ['chat']);
    const everything = await identified('nosy');

    // Progress belongs to a topic the first client did not take.
    hub.broadcaster.broadcast({ type: 'progress', jobId: 'x', processed: 1, total: 2, percent: 50 });

    await everything.client.next('progress');
    assert.equal(chatOnly.client.count('progress'), 0);
  });
});

describe('invalid messages', () => {
  it('answers a non-JSON frame with an error and keeps the connection', async () => {
    const { client } = await identified();
    client.raw('this is not json');

    const error = await client.next('error');
    assert.equal(error.code, 'invalid_json');
    assert.equal(client.socket.readyState, WebSocket.OPEN);
  });

  it('rejects a frame without a type', async () => {
    const { client } = await identified();
    client.send({ text: 'no type here' });

    assert.equal((await client.next('error')).code, 'missing_type');
  });

  it('rejects an unknown type', async () => {
    const { client } = await identified();
    client.send({ type: 'nonsense' });

    assert.equal((await client.next('error')).code, 'unknown_type');
  });

  it('rejects a message whose text is not a string', async () => {
    const { client } = await identified();
    client.send({ type: 'message', text: 42 });

    assert.equal((await client.next('error')).code, 'invalid_message');
  });

  it('rejects an empty message', async () => {
    const { client } = await identified();
    client.send({ type: 'message', text: '   ' });

    assert.equal((await client.next('error')).code, 'invalid_message');
  });

  it('rejects a message past the length limit', async () => {
    const { client } = await identified();
    client.send({ type: 'message', text: 'x'.repeat(51) });

    assert.equal((await client.next('error')).code, 'invalid_message');
  });

  it('rejects an unknown subscription topic', async () => {
    const { client } = await identified();
    client.send({ type: 'subscribe', topics: ['chat', 'secrets'] });

    assert.equal((await client.next('error')).code, 'invalid_subscribe');
  });

  it('closes a client that keeps sending invalid frames', async () => {
    const { client } = await identified();

    for (let index = 0; index < 3; index += 1) {
      client.raw('garbage');
    }

    const closed = await client.closed();
    assert.equal(closed.code, CloseCode.InvalidFrames);
    assert.equal(closed.reason, 'too_many_invalid_messages');
  });
});

describe('close', () => {
  it('unregisters the client and tells the others', async () => {
    const alice = await identified('alice');
    const bob = await identified('bob');
    await alice.client.next('presence');

    bob.client.socket.close(1000, 'bye');

    const presence = await alice.client.next('presence');
    assert.equal(presence.event, 'leave');
    assert.equal(presence.name, 'bob');
    assert.equal(presence.total, 1);
    assert.equal(hub.registry.size, 1);
  });

  it('forgets a client that vanished without a close handshake', async () => {
    const { client, ready } = await identified('ghost');
    assert.equal(hub.registry.size, 1);

    // What a killed process leaves behind: no close frame, just a dead socket.
    client.socket.terminate();

    await new Promise((resolve) => setTimeout(resolve, 100));
    assert.equal(hub.registry.get(ready.clientId), null);
    assert.equal(hub.registry.size, 0);
  });
});

describe('loss of a client', () => {
  it('terminates a socket that stops answering pings', async () => {
    // Its own server, because a 40 ms heartbeat would interfere with every
    // other test in this file.
    const ownServer = http.createServer();
    const ownHub = createWebSocketServer({
      server: ownServer,
      config: testConfig({ heartbeatIntervalMs: 40, maxMissedPongs: 1, authTimeoutMs: 2000 }),
      log: () => {},
    });

    await new Promise((resolve) => ownServer.listen(0, resolve));
    const ownPort = ownServer.address().port;

    const socket = new WebSocket(`ws://127.0.0.1:${ownPort}/ws`);
    await new Promise((resolve) => socket.once('open', resolve));

    // ws answers a ping automatically, so the test has to stop the socket from
    // reading at all - which is exactly what an unreachable client looks like.
    socket._socket.pause();

    // Asserted on the server, not on the client: a socket that is not reading
    // does not notice that the other end is gone either, so waiting for its
    // "close" event would wait for ever. That the server dropped the client is
    // the whole claim anyway.
    const deadline = Date.now() + 2000;
    while (ownHub.registry.size > 0 && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 20));
    }

    assert.equal(ownHub.registry.size, 0, 'the heartbeat should have dropped the silent client');

    socket.terminate();
    await ownHub.close();
    await new Promise((resolve) => ownServer.close(resolve));
  });
});

describe('the registry snapshot', () => {
  it('reports the fields the HTTP endpoint exposes', async () => {
    const { ready } = await identified('snapshot-test');
    const snapshot = hub.snapshot();

    assert.equal(snapshot.path, '/ws');
    assert.equal(snapshot.clients.total, 1);

    const client = snapshot.clients.clients[0];
    assert.equal(client.clientId, ready.clientId);
    assert.equal(client.name, 'snapshot-test');
    assert.equal(client.state, 'active');
    assert.ok(client.connectedAt);
    assert.ok(client.uptimeMs >= 0);
    assert.equal(client.bufferedAmount, 0);
    assert.ok(client.sent > 0);
    assert.equal(client.dropped, 0);
    assert.ok(Array.isArray(client.topics));

    // The socket must never leak into something that gets serialised.
    assert.equal('socket' in client, false);
  });
});
