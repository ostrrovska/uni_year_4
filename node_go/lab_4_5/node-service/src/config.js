const path = require('node:path');

// Lab 4 read its three env vars inline in server.js. Lab 5 adds stream and
// WebSocket knobs, and the demo script drives most of them, so the whole
// surface is collected here: one place to read when asking "what is tunable",
// and one place that applies defaults and bounds.
const SERVICE_ROOT = path.join(__dirname, '..');
const LAB_ROOT = path.join(SERVICE_ROOT, '..');

function str(name, fallback) {
  const raw = process.env[name];
  return raw === undefined || raw === '' ? fallback : raw;
}

// Rejects the value instead of silently falling back: a typo in a demo
// parameter that halves the buffer size would otherwise be invisible.
function int(name, fallback, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') {
    return fallback;
  }

  const value = Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be an integer in [${min}, ${max}], got "${raw}"`);
  }

  return value;
}

function bool(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') {
    return fallback;
  }
  return raw === '1' || raw.toLowerCase() === 'true';
}

const KiB = 1024;
const MiB = 1024 * KiB;

const config = {
  port: int('PORT', 3100, { min: 0, max: 65535 }),

  // Lab 4 settings, unchanged in meaning.
  repository: {
    kind: str('ITEM_REPO', 'memory'),
    dataFile: str('ITEM_DATA_FILE', path.join(LAB_ROOT, 'data', 'items.json')),
  },

  stream: {
    datasetFile: str('STREAM_DATASET', path.join(LAB_ROOT, 'data', 'events.ndjson')),
    outputDir: str('STREAM_OUT_DIR', path.join(LAB_ROOT, 'out')),

    // Node's own default for fs streams. Everything about chunk size follows
    // from this number, which is why the demo varies it explicitly.
    highWaterMark: int('STREAM_HWM', 64 * KiB, { min: 1 * KiB, max: 16 * MiB }),

    // Per-chunk delay of the artificial slow consumer.
    slowDelayMs: int('STREAM_SLOW_DELAY_MS', 2, { min: 0, max: 5000 }),

    // Progress is emitted on whichever of the two fires first, so a fast run
    // still reports often enough and a slow one does not flood the socket.
    progressIntervalMs: int('STREAM_PROGRESS_MS', 100, { min: 10, max: 10000 }),
    progressBytes: int('STREAM_PROGRESS_BYTES', 4 * MiB, { min: 64 * KiB }),

    maxConcurrentJobs: int('STREAM_MAX_JOBS', 2, { min: 1, max: 16 }),
    keepJobs: int('STREAM_KEEP_JOBS', 20, { min: 1, max: 500 }),
  },

  ws: {
    path: str('WS_PATH', '/ws'),

    // Shared secret for the identification step. A real service would verify a
    // signed token; the lab only needs a value that can be got wrong on purpose.
    token: str('WS_TOKEN', 'lab5'),
    authTimeoutMs: int('WS_AUTH_TIMEOUT_MS', 5000, { min: 100, max: 120000 }),

    // Heartbeat: a client whose process was killed leaves a socket that looks
    // open until a ping goes unanswered twice.
    heartbeatIntervalMs: int('WS_HEARTBEAT_MS', 15000, { min: 200, max: 120000 }),
    maxMissedPongs: int('WS_MAX_MISSED_PONGS', 2, { min: 1, max: 10 }),

    maxInvalidMessages: int('WS_MAX_INVALID', 5, { min: 1, max: 100 }),
    maxMessageBytes: int('WS_MAX_MESSAGE_BYTES', 16 * KiB, { min: 256 }),
    maxTextLength: int('WS_MAX_TEXT', 2000, { min: 1 }),

    // Backpressure policy. soft: stop sending droppable frames; hard + grace:
    // the connection is beyond saving and gets closed.
    protection: bool('WS_PROTECTION', true),
    softLimitBytes: int('WS_SOFT_LIMIT', 256 * KiB, { min: 1 * KiB }),
    hardLimitBytes: int('WS_HARD_LIMIT', 4 * MiB, { min: 16 * KiB }),
    slowGraceMs: int('WS_SLOW_GRACE_MS', 3000, { min: 100, max: 120000 }),
    progressMinIntervalMs: int('WS_PROGRESS_MIN_MS', 100, { min: 0, max: 10000 }),
    batchWindowMs: int('WS_BATCH_WINDOW_MS', 50, { min: 0, max: 5000 }),
    statsIntervalMs: int('WS_STATS_MS', 500, { min: 50, max: 60000 }),
  },
};

module.exports = { config, SERVICE_ROOT, LAB_ROOT, KiB, MiB };
