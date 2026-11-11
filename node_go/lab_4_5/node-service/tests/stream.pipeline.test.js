// End-to-end tests of the full chain on a small temporary file:
// File -> Readable -> LineSplit -> EventAnalyzer -> Writable -> processed file.
//
// What they check is that the output file is exactly what the filter promised,
// that both ways of joining the stages give the same answer, that progress
// arrives while the run is still going, and that an abort actually stops it.
const { after, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { runStreamPipeline } = require('../src/streams/pipeline.runner');

const LINES = 500;

let directory;
let input;
let inputSize;
let expectedErrors;

function line(index) {
  // Every third record is an error, every 97th is unparsable: both counts are
  // then arithmetic rather than something the test has to measure.
  if (index % 97 === 0) {
    return '{ broken line';
  }

  return JSON.stringify({
    ts: new Date(Date.UTC(2026, 10, 1) + index * 1000).toISOString(),
    level: index % 3 === 0 ? 'error' : 'info',
    service: index % 2 === 0 ? 'api' : 'db',
    itemId: index,
    latencyMs: index,
    msg: index % 5 === 0 ? 'repository timeout' : 'item created',
  });
}

before(async () => {
  directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lab5-pipe-'));
  input = path.join(directory, 'events.ndjson');

  const body = Array.from({ length: LINES }, (unused, index) => line(index + 1)).join('\n');
  await fsp.writeFile(input, `${body}\n`, 'utf8');
  inputSize = (await fsp.stat(input)).size;

  expectedErrors = Array.from({ length: LINES }, (unused, index) => index + 1).filter(
    (index) => index % 97 !== 0 && index % 3 === 0,
  ).length;
});

after(async () => {
  await fsp.rm(directory, { recursive: true, force: true });
});

async function run(options = {}) {
  const output = path.join(directory, `out-${Math.random().toString(16).slice(2)}.ndjson`);
  const result = await runStreamPipeline({
    inputFile: input,
    outputFile: output,
    highWaterMark: 1024,
    ...options,
  });

  return { result, output, text: await fsp.readFile(output, 'utf8') };
}

describe('the full chain', () => {
  it('writes exactly the records the filter kept', async () => {
    const { result, text } = await run({ filter: { levels: ['error'] } });

    const lines = text.trim().split('\n');
    assert.equal(lines.length, expectedErrors);
    assert.equal(result.stats.linesOut, expectedErrors);

    for (const raw of lines) {
      assert.equal(JSON.parse(raw).level, 'error');
    }
  });

  it('reads the whole file in chunks no larger than the highWaterMark', async () => {
    const { result } = await run({ highWaterMark: 1024, filter: { levels: ['error'] } });

    assert.equal(result.chunks.bytesIn, inputSize);
    assert.ok(result.chunks.maxChunk <= 1024);
    assert.equal(result.chunks.chunksIn, Math.ceil(inputSize / 1024));
  });

  it('counts the malformed lines without failing', async () => {
    const { result } = await run();

    assert.equal(result.stats.malformed, Math.floor(LINES / 97));
    assert.equal(result.stats.linesIn, LINES);
  });

  it('gives the same answer through pipe() and through pipeline()', async () => {
    const piped = await run({ mode: 'pipe', filter: { levels: ['error'] } });
    const pipelined = await run({ mode: 'pipeline', filter: { levels: ['error'] } });

    assert.equal(piped.text, pipelined.text);
    assert.equal(piped.result.stats.linesOut, pipelined.result.stats.linesOut);
  });

  it('refuses a mode it does not implement', async () => {
    await assert.rejects(run({ mode: 'magic' }), /unknown mode "magic"/);
  });

  it('writes the output file where it was asked to, creating the directory', async () => {
    const nested = path.join(directory, 'deep', 'deeper', 'out.ndjson');
    const result = await runStreamPipeline({
      inputFile: input,
      outputFile: nested,
      highWaterMark: 1024,
    });

    assert.equal(result.outputFile, nested);
    assert.ok((await fsp.stat(nested)).size > 0);
  });
});

describe('progress reporting', () => {
  it('arrives during the run and ends at the full size', async () => {
    const seen = [];
    const { result } = await run({
      filter: { levels: ['error'] },
      progressIntervalMs: 0,
      progressBytes: 1,
      onProgress: (progress) => seen.push(progress),
    });

    assert.ok(seen.length > 1, `expected several progress events, got ${seen.length}`);

    // Monotonic, which is what lets a client treat it as a progress bar and not
    // as a jittery gauge.
    for (let index = 1; index < seen.length; index += 1) {
      assert.ok(
        seen[index].processed >= seen[index - 1].processed,
        `progress went backwards: ${seen[index - 1].processed} then ${seen[index].processed}`,
      );
    }

    const last = seen.at(-1);
    assert.equal(last.processed, inputSize);
    assert.equal(last.total, inputSize);
    assert.equal(last.percent, 100);
    assert.equal(last.linesOut, result.stats.linesOut);
  });

  it('marks the last frame final, so nothing may drop it', async () => {
    const seen = [];
    await run({ progressBytes: 1, progressIntervalMs: 0, onProgress: (progress) => seen.push(progress) });

    const last = seen.at(-1);
    assert.equal(last.final, true);
    assert.equal(last.percent, 100);

    // Only the last one: every earlier frame is superseded by the next, which
    // is what makes it droppable.
    assert.equal(seen.slice(0, -1).some((progress) => progress.final === true), false);
  });

  it('reads only the requested slice when bytes is given', async () => {
    const slice = 2048;
    const result = await runStreamPipeline({
      inputFile: input,
      outputFile: path.join(directory, 'slice.ndjson'),
      highWaterMark: 512,
      bytes: slice,
    });

    assert.equal(result.totalBytes, slice);
    assert.equal(result.chunks.bytesIn, slice);
    assert.equal(result.chunks.chunksIn, slice / 512);
    assert.ok(result.stats.linesIn > 0);
    assert.ok(result.stats.linesIn < LINES, 'a slice must not contain every line of the file');
  });

  it('carries the fields the assignment asks for', async () => {
    const seen = [];
    await run({ progressBytes: 1, progressIntervalMs: 0, onProgress: (progress) => seen.push(progress) });

    for (const key of ['processed', 'total', 'percent', 'rssMB', 'linesIn', 'linesOut']) {
      assert.ok(key in seen[0], `progress is missing "${key}"`);
    }
  });
});

describe('sampled chunks', () => {
  it('hands up batches of processed records', async () => {
    const batches = [];
    await run({
      filter: { levels: ['error'] },
      sampleEvery: 10,
      chunkBatch: 4,
      onChunk: (chunk) => batches.push(chunk),
    });

    assert.ok(batches.length > 1);
    assert.equal(batches[0].records.length, 4);
    assert.equal(batches[0].sampledEvery, 10);
    assert.deepEqual(
      batches.map((batch) => batch.seq),
      batches.map((unused, index) => index + 1),
    );

    for (const record of batches[0].records) {
      assert.equal(record.level, 'error');
      assert.ok('bucket' in record);
    }
  });

  it('stays silent when sampling is off', async () => {
    const batches = [];
    await run({ sampleEvery: 0, onChunk: (chunk) => batches.push(chunk) });
    assert.equal(batches.length, 0);
  });
});

describe('abort', () => {
  it('stops a pipeline() run with an AbortError', async () => {
    const controller = new AbortController();
    const promise = run({ mode: 'pipeline', signal: controller.signal, highWaterMark: 64 });
    controller.abort();

    await assert.rejects(promise, (error) => error.name === 'AbortError');
  });

  it('stops a pipe() run with an AbortError', async () => {
    const controller = new AbortController();
    const promise = run({ mode: 'pipe', signal: controller.signal, highWaterMark: 64 });
    controller.abort();

    await assert.rejects(promise, (error) => error.name === 'AbortError');
  });

  it('refuses to start when the signal is already aborted', async () => {
    await assert.rejects(
      run({ mode: 'pipe', signal: AbortSignal.abort() }),
      (error) => error.name === 'AbortError',
    );
  });
});

describe('the slow-consumer variant', () => {
  it('discards the data and reports what the consumer took', async () => {
    const result = await runStreamPipeline({
      inputFile: input,
      slowDelayMs: 1,
      highWaterMark: 1024,
      filter: { levels: ['error'] },
    });

    assert.equal(result.outputFile, null);
    assert.equal(result.sink.kind, 'slow');
    assert.ok(result.sink.chunksWritten > 0);
    assert.equal(result.stats.linesOut, expectedErrors);
  });
});
