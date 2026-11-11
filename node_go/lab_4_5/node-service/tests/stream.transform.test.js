// Transform-layer tests. No file, no server, no socket: a Transform is an
// object that takes writes and emits reads, so every case here is a few writes
// and an assertion on what came out.
//
// Most of them are about chunk boundaries, because that is where a streaming
// implementation is actually wrong or right. A test that feeds one tidy chunk
// per line proves nothing a non-streaming version would fail.
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const { LineSplitTransform } = require('../src/streams/line-split.transform');
const { EventAnalyzerTransform, bucketOf } = require('../src/streams/event-analyzer.transform');

// Collects everything a transform emits for a given list of writes.
async function collect(transform, writes) {
  const out = [];
  transform.on('data', (chunk) => out.push(chunk));

  for (const write of writes) {
    transform.write(write);
  }
  transform.end();

  await new Promise((resolve, reject) => {
    transform.once('end', resolve);
    transform.once('error', reject);
  });

  return out;
}

function record(fields = {}) {
  return JSON.stringify({
    ts: '2026-11-01T09:00:00.000Z',
    level: 'info',
    service: 'api',
    itemId: 1,
    latencyMs: 10,
    msg: 'item created',
    ...fields,
  });
}

describe('LineSplitTransform', () => {
  it('emits whole lines from a single chunk', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('one\ntwo\nthree\n')]);
    assert.deepEqual(lines, ['one', 'two', 'three']);
  });

  it('joins a line that was split across two chunks', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('abc\nde'), Buffer.from('f\nghi\n')]);
    assert.deepEqual(lines, ['abc', 'def', 'ghi']);
  });

  it('joins a line split across many chunks, one byte at a time', async () => {
    const writes = [...'hello\nworld\n'].map((character) => Buffer.from(character));
    const lines = await collect(new LineSplitTransform(), writes);
    assert.deepEqual(lines, ['hello', 'world']);
  });

  it('survives a multi-byte character split between chunks', async () => {
    // "привіт" is two bytes per character; the split lands inside one of them.
    const buffer = Buffer.from('привіт\n', 'utf8');
    const cut = 5;
    assert.notEqual(buffer.subarray(0, cut).toString('utf8'), 'прив'.slice(0, 2));

    const lines = await collect(new LineSplitTransform(), [buffer.subarray(0, cut), buffer.subarray(cut)]);
    assert.deepEqual(lines, ['привіт']);
  });

  it('strips the carriage return of a CRLF file', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('a\r\nb\r\n')]);
    assert.deepEqual(lines, ['a', 'b']);
  });

  it('emits a trailing line that has no newline', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('a\nb')]);
    assert.deepEqual(lines, ['a', 'b']);
  });

  it('does not invent an empty line after a trailing newline', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('a\nb\n')]);
    assert.deepEqual(lines, ['a', 'b']);
  });

  it('keeps empty lines in the middle of the file', async () => {
    const lines = await collect(new LineSplitTransform(), [Buffer.from('a\n\nb\n')]);
    assert.deepEqual(lines, ['a', '', 'b']);
  });

  it('counts chunks and reports their sizes', async () => {
    const transform = new LineSplitTransform();
    await collect(transform, [Buffer.alloc(100, 0x61), Buffer.from('\n'), Buffer.alloc(40, 0x62), Buffer.from('\n')]);

    assert.equal(transform.chunkStats.chunksIn, 4);
    assert.equal(transform.chunkStats.bytesIn, 142);
    assert.equal(transform.chunkStats.maxChunk, 100);
    assert.equal(transform.chunkStats.minChunk, 1);
    assert.equal(transform.linesOut, 2);
  });

  it('fails instead of buffering a line without end', async () => {
    const transform = new LineSplitTransform({ maxLineBytes: 64 });
    transform.resume();

    await assert.rejects(
      new Promise((resolve, reject) => {
        transform.on('error', reject);
        transform.on('end', resolve);
        transform.write(Buffer.alloc(200, 0x61));
        transform.end();
      }),
      /line exceeds 64 bytes/,
    );
  });
});

describe('EventAnalyzerTransform', () => {
  it('passes every record through when no filter is set', async () => {
    const analyzer = new EventAnalyzerTransform({ outputChunkBytes: 1 });
    const out = await collect(analyzer, [record(), record({ level: 'error' })]);

    assert.equal(analyzer.stats.linesIn, 2);
    assert.equal(analyzer.stats.linesOut, 2);
    assert.equal(out.join('').trim().split('\n').length, 2);
  });

  it('keeps only the requested levels and counts the rest as filtered', async () => {
    const analyzer = new EventAnalyzerTransform({ levels: ['error'], outputChunkBytes: 1 });
    const out = await collect(analyzer, [record(), record({ level: 'error' }), record({ level: 'warn' })]);

    assert.equal(analyzer.stats.linesOut, 1);
    assert.equal(analyzer.stats.filtered, 2);
    assert.equal(JSON.parse(out.join('')).level, 'error');
  });

  it('filters by substring of the message', async () => {
    const analyzer = new EventAnalyzerTransform({ grep: 'timeout', outputChunkBytes: 1 });
    await collect(analyzer, [record({ msg: 'repository timeout' }), record({ msg: 'item created' })]);

    assert.equal(analyzer.stats.linesOut, 1);
  });

  it('filters by minimum latency', async () => {
    const analyzer = new EventAnalyzerTransform({ minLatencyMs: 500, outputChunkBytes: 1 });
    await collect(analyzer, [record({ latencyMs: 100 }), record({ latencyMs: 900 })]);

    assert.equal(analyzer.stats.linesOut, 1);
  });

  it('counts a malformed line and keeps processing', async () => {
    const analyzer = new EventAnalyzerTransform({ outputChunkBytes: 1 });
    await collect(analyzer, ['{ not json', record(), '[1,2,3]', record()]);

    assert.equal(analyzer.stats.malformed, 2);
    assert.equal(analyzer.stats.linesOut, 2);
    assert.equal(analyzer.stats.malformedSamples.length, 2);
  });

  it('collects statistics over every well-formed record, filter or not', async () => {
    const analyzer = new EventAnalyzerTransform({ levels: ['error'], outputChunkBytes: 1 });
    await collect(analyzer, [
      record({ level: 'info', service: 'api', latencyMs: 10 }),
      record({ level: 'error', service: 'db', latencyMs: 1200 }),
      record({ level: 'warn', service: 'db', latencyMs: 500 }),
    ]);

    assert.equal(analyzer.stats.byLevel.info, 1);
    assert.equal(analyzer.stats.byLevel.error, 1);
    assert.equal(analyzer.stats.byService.db, 2);
    assert.deepEqual(analyzer.stats.latency, { min: 10, max: 1200, avg: 570, count: 3 });
  });

  it('enriches each surviving record with a latency bucket', async () => {
    const analyzer = new EventAnalyzerTransform({ outputChunkBytes: 1 });
    const out = await collect(analyzer, [record({ latencyMs: 2000 })]);
    const parsed = JSON.parse(out.join(''));

    assert.equal(parsed.bucket, 'critical');
    assert.equal(parsed.seq, 1);
  });

  it('groups output into chunks of about the requested size', async () => {
    const analyzer = new EventAnalyzerTransform({ outputChunkBytes: 400 });
    const writes = Array.from({ length: 20 }, (unused, index) => record({ itemId: index }));
    const out = await collect(analyzer, writes);

    assert.ok(out.length < 20, `expected fewer than 20 chunks, got ${out.length}`);
    assert.equal(out.join('').trim().split('\n').length, 20);
    for (const chunk of out.slice(0, -1)) {
      assert.ok(chunk.length >= 400, `chunk of ${chunk.length} B is below the 400 B target`);
    }
  });

  it('emits every n-th surviving record as a sample', async () => {
    const analyzer = new EventAnalyzerTransform({ sampleEvery: 3, outputChunkBytes: 1 });
    const samples = [];
    analyzer.on('sample', (sample) => samples.push(sample));

    await collect(analyzer, Array.from({ length: 10 }, (unused, index) => record({ itemId: index })));

    assert.deepEqual(samples.map((sample) => sample.seq), [3, 6, 9]);
  });

  it('emits the final statistics once, on flush', async () => {
    const analyzer = new EventAnalyzerTransform({ outputChunkBytes: 1 });
    const seen = [];
    analyzer.on('stats', (stats) => seen.push(stats));

    await collect(analyzer, [record()]);

    assert.equal(seen.length, 1);
    assert.equal(seen[0].linesIn, 1);
  });
});

describe('bucketOf', () => {
  it('maps latency to a named band', () => {
    assert.equal(bucketOf(10), 'fast');
    assert.equal(bucketOf(100), 'normal');
    assert.equal(bucketOf(600), 'slow');
    assert.equal(bucketOf(5000), 'critical');
    assert.equal(bucketOf(undefined), 'unknown');
  });
});
