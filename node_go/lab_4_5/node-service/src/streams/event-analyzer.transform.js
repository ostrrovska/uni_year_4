const { Transform } = require('node:stream');

// Second stage: one NDJSON line in, at most one enriched NDJSON line out.
//
// It does all three things the assignment lists as alternatives - it parses
// JSON records, filters them, and accumulates statistics - because they are the
// same single pass over the data. Filtering is what makes the output file
// smaller than the input, which is the visible proof that the stage is not a
// pass-through.
//
// A malformed line is counted, not thrown: one broken record in a 256 MB log
// must not destroy the whole run. Deciding that here, and not in the writable,
// is why "what counts as a usable record" stays one concept in one file.
const LEVELS = ['debug', 'info', 'warn', 'error'];

function bucketOf(latencyMs) {
  if (!Number.isFinite(latencyMs)) return 'unknown';
  if (latencyMs < 50) return 'fast';
  if (latencyMs < 250) return 'normal';
  if (latencyMs < 1000) return 'slow';
  return 'critical';
}

class EventAnalyzerTransform extends Transform {
  // levels: keep only these (null = keep all). grep: substring that must occur
  // in msg. minLatencyMs: drop anything faster than this.
  constructor({
    levels = null,
    grep = null,
    minLatencyMs = null,
    sampleMalformed = 5,
    // 0 disables sampling. Anything else emits every n-th surviving record as a
    // "sample" event, which is how processed data reaches the WebSocket clients
    // without this transform knowing that WebSocket exists.
    sampleEvery = 0,
    // Output is accumulated to roughly this size before being pushed. Without
    // it the writable side would receive one ~110-byte chunk per record: two
    // million writes for a 256 MB file, and an artificially slow consumer
    // charging its per-chunk delay two million times. Writing in buffer-sized
    // pieces is what a real file sink wants anyway.
    outputChunkBytes = 64 * 1024,
  } = {}) {
    super({ writableObjectMode: true, readableObjectMode: false, writableHighWaterMark: 256 });

    this.levels = levels === null ? null : new Set(levels);
    this.grep = grep === null || grep === '' ? null : String(grep);
    this.minLatencyMs = minLatencyMs;
    this.sampleMalformed = sampleMalformed;
    this.sampleEvery = sampleEvery;
    this.outputChunkBytes = outputChunkBytes;
    this.outputBuffer = '';
    this.chunksOut = 0;

    this.stats = {
      linesIn: 0,
      linesOut: 0,
      bytesOut: 0,
      malformed: 0,
      filtered: 0,
      byLevel: Object.fromEntries(LEVELS.map((level) => [level, 0])),
      byService: {},
      byBucket: {},
      latency: { min: Infinity, max: 0, sum: 0, count: 0 },
      malformedSamples: [],
    };
  }

  _transform(line, encoding, callback) {
    this.stats.linesIn += 1;

    if (line === '') {
      callback();
      return;
    }

    let record;
    try {
      record = JSON.parse(line);
    } catch {
      this.#countMalformed(line, 'not JSON');
      callback();
      return;
    }

    if (record === null || typeof record !== 'object' || Array.isArray(record)) {
      this.#countMalformed(line, 'not an object');
      callback();
      return;
    }

    // Statistics are collected over every well-formed record, before the
    // filter: the report needs to say how many errors the file holds, not how
    // many survived the filter.
    this.#observe(record);

    if (!this.#keep(record)) {
      this.stats.filtered += 1;
      callback();
      return;
    }

    const enriched = this.#enrich(record);
    const out = `${JSON.stringify(enriched)}\n`;
    this.stats.linesOut += 1;
    this.stats.bytesOut += Buffer.byteLength(out);

    if (this.sampleEvery > 0 && this.stats.linesOut % this.sampleEvery === 0) {
      this.emit('sample', enriched);
    }

    this.outputBuffer += out;

    if (this.outputBuffer.length < this.outputChunkBytes) {
      callback();
      return;
    }

    callback(null, this.#takeOutput());
  }

  // Averages and derived fields are computed once the last record is in, so no
  // consumer has to know how the accumulators are shaped.
  _flush(callback) {
    if (this.outputBuffer !== '') {
      this.push(this.#takeOutput());
    }

    const { latency } = this.stats;
    this.stats.latency = {
      min: latency.count === 0 ? 0 : latency.min,
      max: latency.max,
      avg: latency.count === 0 ? 0 : Number((latency.sum / latency.count).toFixed(2)),
      count: latency.count,
    };
    this.emit('stats', this.stats);
    callback();
  }

  #takeOutput() {
    const chunk = this.outputBuffer;
    this.outputBuffer = '';
    this.chunksOut += 1;
    return chunk;
  }

  #countMalformed(line, reason) {
    this.stats.malformed += 1;
    if (this.stats.malformedSamples.length < this.sampleMalformed) {
      this.stats.malformedSamples.push({ reason, preview: line.slice(0, 80) });
    }
  }

  #observe(record) {
    const level = typeof record.level === 'string' ? record.level : 'unknown';
    this.stats.byLevel[level] = (this.stats.byLevel[level] ?? 0) + 1;

    const service = typeof record.service === 'string' ? record.service : 'unknown';
    this.stats.byService[service] = (this.stats.byService[service] ?? 0) + 1;

    const bucket = bucketOf(record.latencyMs);
    this.stats.byBucket[bucket] = (this.stats.byBucket[bucket] ?? 0) + 1;

    if (Number.isFinite(record.latencyMs)) {
      const { latency } = this.stats;
      latency.min = Math.min(latency.min, record.latencyMs);
      latency.max = Math.max(latency.max, record.latencyMs);
      latency.sum += record.latencyMs;
      latency.count += 1;
    }
  }

  #keep(record) {
    if (this.levels !== null && !this.levels.has(record.level)) {
      return false;
    }
    if (this.grep !== null && !String(record.msg ?? '').includes(this.grep)) {
      return false;
    }
    if (this.minLatencyMs !== null && !(Number(record.latencyMs) >= this.minLatencyMs)) {
      return false;
    }
    return true;
  }

  #enrich(record) {
    return {
      seq: this.stats.linesOut + 1,
      ts: record.ts,
      level: record.level,
      service: record.service,
      itemId: record.itemId,
      latencyMs: record.latencyMs,
      bucket: bucketOf(record.latencyMs),
      msg: record.msg,
    };
  }
}

module.exports = { EventAnalyzerTransform, LEVELS, bucketOf };
