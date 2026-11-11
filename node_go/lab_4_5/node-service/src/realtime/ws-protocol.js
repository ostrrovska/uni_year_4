// The wire format, in one file. Every frame is a JSON object with a "type"
// discriminator, in both directions.
//
// Keeping parsing, validation and frame construction together is the same
// decision as models/item.js in lab 4: the shape of a message is one concept,
// so the server, the browser page and the tests cannot disagree about it. The
// ws-server only decides what to do with a frame, never what a frame looks
// like.
//
// Validation returns a reason instead of throwing. An invalid frame from a
// client is an expected event on a public socket, not an exceptional one: the
// server answers with an error frame and keeps the connection, and only a
// client that keeps doing it gets closed.

// Frames a client may send.
const CLIENT_TYPES = ['hello', 'message', 'ping', 'subscribe'];

// Topics a client can subscribe to. "chat" and "presence" are on by default;
// the data firehose is opt-in, so a client that only wants to chat never
// becomes a slow consumer of progress frames.
const TOPICS = ['chat', 'presence', 'progress', 'chunks', 'stats'];
const DEFAULT_TOPICS = ['chat', 'presence'];

class InvalidFrame {
  constructor(code, detail) {
    this.code = code;
    this.detail = detail;
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// raw is whatever ws handed us: a Buffer for a text frame, or binary data.
function parseClientFrame(raw, { maxBytes = 16 * 1024, maxTextLength = 2000 } = {}) {
  if (raw.length > maxBytes) {
    return new InvalidFrame('frame_too_large', `frame exceeds ${maxBytes} bytes`);
  }

  let parsed;
  try {
    parsed = JSON.parse(raw.toString('utf8'));
  } catch {
    return new InvalidFrame('invalid_json', 'frame is not valid JSON');
  }

  if (!isPlainObject(parsed)) {
    return new InvalidFrame('invalid_frame', 'frame must be a JSON object');
  }

  if (typeof parsed.type !== 'string') {
    return new InvalidFrame('missing_type', 'frame must carry a string "type"');
  }

  if (!CLIENT_TYPES.includes(parsed.type)) {
    return new InvalidFrame('unknown_type', `unknown type "${parsed.type}", expected one of ${CLIENT_TYPES.join(', ')}`);
  }

  switch (parsed.type) {
    case 'hello': {
      if (typeof parsed.token !== 'string') {
        return new InvalidFrame('invalid_hello', 'hello requires a string "token"');
      }
      if (parsed.name !== undefined && typeof parsed.name !== 'string') {
        return new InvalidFrame('invalid_hello', 'hello "name" must be a string when present');
      }
      const name = (parsed.name ?? '').trim().slice(0, 40);
      return { type: 'hello', token: parsed.token, name: name === '' ? null : name };
    }

    case 'message': {
      if (typeof parsed.text !== 'string') {
        return new InvalidFrame('invalid_message', 'message requires a string "text"');
      }
      const text = parsed.text.trim();
      if (text === '') {
        return new InvalidFrame('invalid_message', 'message "text" must not be empty');
      }
      if (text.length > maxTextLength) {
        return new InvalidFrame('invalid_message', `message "text" must be at most ${maxTextLength} characters`);
      }
      return { type: 'message', text };
    }

    case 'subscribe': {
      if (!Array.isArray(parsed.topics)) {
        return new InvalidFrame('invalid_subscribe', 'subscribe requires a "topics" array');
      }
      const unknown = parsed.topics.filter((topic) => !TOPICS.includes(topic));
      if (unknown.length > 0) {
        return new InvalidFrame('invalid_subscribe', `unknown topics: ${unknown.join(', ')}`);
      }
      return { type: 'subscribe', topics: [...new Set(parsed.topics)] };
    }

    default:
      return { type: 'ping' };
  }
}

// Server frames. Built by factories rather than inline object literals so that
// adding a field never means hunting through ws-server.js for every place a
// frame of that type is produced.
const frames = {
  welcome: ({ clientId, authRequired, authTimeoutMs, serverTime, limits }) => ({
    type: 'welcome',
    clientId,
    authRequired,
    authTimeoutMs,
    serverTime,
    limits,
  }),

  ready: ({ client, peers, topics }) => ({
    type: 'ready',
    clientId: client.clientId,
    name: client.name,
    connectedAt: client.connectedAt,
    state: client.state,
    topics,
    peers,
  }),

  ack: ({ of, at = new Date().toISOString(), detail = null }) => ({ type: 'ack', of, at, detail }),

  message: ({ from, clientId, text, at = new Date().toISOString() }) => ({
    type: 'message',
    from,
    clientId,
    text,
    at,
  }),

  presence: ({ event, clientId, name, total, at = new Date().toISOString() }) => ({
    type: 'presence',
    event,
    clientId,
    name,
    total,
    at,
  }),

  // Requirement 9 in its literal form: the processed chunks themselves reach
  // the clients, not only a percentage. A sample rather than everything,
  // because a 256 MB file would otherwise be pushed through the socket twice.
  chunk: ({ jobId, seq, sampledEvery, records }) => ({
    type: 'chunk',
    jobId,
    seq,
    sampledEvery,
    count: records.length,
    records,
  }),

  progress: ({ jobId, processed, total, percent, ...rest }) => ({
    type: 'progress',
    jobId,
    processed,
    total,
    percent,
    ...rest,
  }),

  jobEvent: ({ event, jobId, payload }) => ({ type: event, jobId, ...payload }),

  stats: ({ clients, jobs, server, at = new Date().toISOString() }) => ({
    type: 'stats',
    clients,
    jobs,
    server,
    at,
  }),

  batch: ({ frames: batched }) => ({ type: 'batch', count: batched.length, frames: batched }),

  error: ({ code, detail }) => ({ type: 'error', code, detail, at: new Date().toISOString() }),

  pong: ({ at = new Date().toISOString() }) => ({ type: 'pong', at }),
};

// Close codes. 1000 and 1013 are standard; the 4xxx range is reserved for the
// application, and these mirror the HTTP codes of the same meaning so the
// reason a socket closed is readable without a lookup table.
const CloseCode = {
  Normal: 1000,
  TryAgainLater: 1013,
  InvalidFrames: 4400,
  Unauthenticated: 4401,
  AuthTimeout: 4408,
  TooSlow: 4290,
  ServerShutdown: 4503,
};

module.exports = {
  CLIENT_TYPES,
  TOPICS,
  DEFAULT_TOPICS,
  CloseCode,
  InvalidFrame,
  parseClientFrame,
  frames,
};
