const { State } = require('./client-registry');
const { CloseCode } = require('./ws-protocol');

// Requirement 10: what to do when the server produces frames faster than a
// client reads them.
//
// The honest answer is that there is no way to make a slow client fast, so the
// only real choices are to drop something, to send less often, to send less, or
// to give up on the client. This file implements all four and decides between
// them per frame, because the right answer depends on what the frame means:
//
//   progress  - state. Only the newest value matters, so a superseded frame is
//               dropped and nothing is lost but a redraw.
//   stats     - state, same reasoning.
//   chunk     - a sample of the processed data. It is already a sample, so
//               thinning it further costs nothing a viewer can notice.
//   message   - history. Dropping a chat line loses information, so a backed-up
//               client gets them batched into one frame instead.
//   welcome, ready, ack, error, pong, job_done, job_error, job_aborted
//             - protocol. Dropping these breaks the client, so they are always
//               sent, and if that is impossible the connection is closed.
//
// The signal driving all of it is ws.bufferedAmount: bytes handed to send()
// that the kernel has not accepted yet. It is the WebSocket equivalent of
// writableLength in the stream experiment - the same question, one layer up.

const Action = {
  Send: 'send',
  Drop: 'drop',
  Batch: 'batch',
  Close: 'close',
};

const DROPPABLE = new Set(['progress', 'stats', 'chunk']);
const BATCHABLE = new Set(['message', 'presence']);

function classify(type) {
  if (DROPPABLE.has(type)) return 'state';
  if (BATCHABLE.has(type)) return 'history';
  return 'protocol';
}

class BackpressurePolicy {
  constructor({
    enabled = true,
    softLimitBytes = 256 * 1024,
    hardLimitBytes = 4 * 1024 * 1024,
    slowGraceMs = 3000,
    progressMinIntervalMs = 100,
  } = {}) {
    this.enabled = enabled;
    this.softLimitBytes = softLimitBytes;
    this.hardLimitBytes = hardLimitBytes;
    this.slowGraceMs = slowGraceMs;
    this.progressMinIntervalMs = progressMinIntervalMs;

    // Totals for the results table.
    this.counters = { sent: 0, dropped: 0, batched: 0, closed: 0, rateLimited: 0 };
  }

  // Updates the client state from the socket buffer. Called before every send
  // and by the stats timer, so a client that went quiet is still reclassified.
  //
  // The soft limit clears at half its value rather than at the limit itself:
  // without that hysteresis a client hovering around the threshold would
  // oscillate between active and slow on every frame.
  observe(client, now = Date.now()) {
    const buffered = client.socket?.bufferedAmount ?? 0;
    client.peakBufferedAmount = Math.max(client.peakBufferedAmount, buffered);

    if (buffered > this.softLimitBytes) {
      if (client.slowSince === null) {
        client.slowSince = now;
      }
      if (client.state === State.Active) {
        client.state = State.Slow;
      }
    } else if (buffered <= this.softLimitBytes / 2) {
      client.slowSince = null;
      if (client.state === State.Slow) {
        client.state = State.Active;
      }
    }

    if (buffered > this.hardLimitBytes) {
      if (client.hardSince === null) {
        client.hardSince = now;
      }
    } else {
      client.hardSince = null;
    }

    return buffered;
  }

  // The single decision point. Returns what to do and why, so the caller does
  // no policy thinking of its own and the reason can be logged and counted.
  decide(client, frame, now = Date.now()) {
    const buffered = this.observe(client, now);

    // A frame flagged final is the last of its kind for that job, so nothing
    // will supersede it and dropping it loses information. It is treated as
    // protocol regardless of its type.
    const kind = frame.final === true ? 'protocol' : classify(frame.type);

    // The control case of the experiment: with protection off the server keeps
    // calling send() no matter how far behind the client is, which is what lets
    // the report show unbounded growth instead of asserting it.
    if (!this.enabled) {
      this.counters.sent += 1;
      return { action: Action.Send, reason: 'protection_disabled', buffered, kind };
    }

    // Mechanism 3, second half: a client that has stayed past the hard limit
    // for the whole grace period is not going to recover. Keeping it would mean
    // holding megabytes of its unread frames in the server process.
    if (client.hardSince !== null && now - client.hardSince >= this.slowGraceMs) {
      this.counters.closed += 1;
      return {
        action: Action.Close,
        reason: 'over_hard_limit',
        code: CloseCode.TooSlow,
        detail: `bufferedAmount ${buffered} B stayed above ${this.hardLimitBytes} B for ${now - client.hardSince} ms`,
        buffered,
        kind,
      };
    }

    // Mechanism 2: rate limiting. Independent of how fast the pipeline runs, a
    // client gets at most one progress frame per interval.
    if (kind !== 'protocol' && frame.type === 'progress' && now - client.lastProgressSentAt < this.progressMinIntervalMs) {
      this.counters.dropped += 1;
      this.counters.rateLimited += 1;
      return { action: Action.Drop, reason: 'rate_limited', buffered, kind };
    }

    // Mechanisms 1 and 4: past the soft limit, state frames are dropped and
    // history frames are batched. Protocol frames are never touched.
    if (buffered > this.softLimitBytes) {
      if (kind === 'state') {
        this.counters.dropped += 1;
        return { action: Action.Drop, reason: 'slow_client', buffered, kind };
      }
      if (kind === 'history') {
        this.counters.batched += 1;
        return { action: Action.Batch, reason: 'slow_client', buffered, kind };
      }
    }

    // Mechanism 3, first half: the queue limit on the server side. Even a
    // protocol frame is refused once the buffer is past the hard limit, because
    // adding to it is exactly the unbounded accumulation being guarded against.
    if (buffered > this.hardLimitBytes && kind !== 'protocol') {
      this.counters.dropped += 1;
      return { action: Action.Drop, reason: 'over_hard_limit', buffered, kind };
    }

    if (frame.type === 'progress') {
      client.lastProgressSentAt = now;
    }

    this.counters.sent += 1;
    return { action: Action.Send, reason: 'ok', buffered, kind };
  }

  snapshot() {
    return {
      enabled: this.enabled,
      softLimitBytes: this.softLimitBytes,
      hardLimitBytes: this.hardLimitBytes,
      slowGraceMs: this.slowGraceMs,
      progressMinIntervalMs: this.progressMinIntervalMs,
      ...this.counters,
    };
  }
}

module.exports = { BackpressurePolicy, Action, classify, DROPPABLE, BATCHABLE };
