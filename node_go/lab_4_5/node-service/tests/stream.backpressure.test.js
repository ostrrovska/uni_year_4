// Backpressure tests. The claim of requirement 5 - that the system must not
// accumulate data without bound when the consumer is slower than the producer -
// is a property of the running pipeline, so it is asserted on the running
// pipeline rather than described in prose.
//
// Everything here uses small files and millisecond delays: the mechanism does
// not care about scale, and the report has the 256 MB numbers.
const { after, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { SlowWritable } = require('../src/streams/slow-writable');
const { runBackpressureScenario } = require('../src/streams/pipeline.runner');

const HWM = 4096;
const CHUNKS = 64;

let directory;
let input;

before(async () => {
  directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lab5-bp-'));
  input = path.join(directory, 'input.bin');
  // Exactly CHUNKS reads at the highWaterMark used below, so the expected chunk
  // count is a number and not an estimate.
  await fsp.writeFile(input, Buffer.alloc(HWM * CHUNKS, 0x61));
});

after(async () => {
  await fsp.rm(directory, { recursive: true, force: true });
});

describe('SlowWritable', () => {
  it('reports false once its buffer has reached the highWaterMark', () => {
    const sink = new SlowWritable({ delayMs: 50, highWaterMark: HWM });

    // A chunk being processed still counts towards writableLength until its
    // callback runs, so a single write of exactly highWaterMark bytes already
    // gets a false back. Half of one does not.
    assert.equal(sink.write(Buffer.alloc(HWM / 2)), true);
    assert.equal(sink.writableLength, HWM / 2);

    assert.equal(sink.write(Buffer.alloc(HWM / 2)), false);
    assert.equal(sink.writableLength, HWM);

    sink.destroy();
  });

  it('drains and then accepts writes again', async () => {
    const sink = new SlowWritable({ delayMs: 1, highWaterMark: HWM });

    assert.equal(sink.write(Buffer.alloc(HWM)), false);

    await new Promise((resolve) => sink.once('drain', resolve));

    assert.equal(sink.writableLength, 0);
    assert.equal(sink.write(Buffer.alloc(HWM / 2)), true);
    sink.destroy();
  });
});

describe('scenario A - no flow control', () => {
  it('accumulates the whole file in the writable buffer', async () => {
    const result = await runBackpressureScenario({
      inputFile: input,
      scenario: 'uncontrolled',
      highWaterMark: HWM,
      delayMs: 1,
      sampleIntervalMs: 20,
    });

    assert.equal(result.chunksRead, CHUNKS);
    assert.equal(result.pauses, 0, 'the uncontrolled producer must never pause');

    // Everything read before the consumer caught up is sitting in memory. The
    // threshold is deliberately loose - the exact peak depends on timing - but
    // it is far above one buffer, which is the whole point.
    assert.ok(
      result.peakBufferedBytes > HWM * 10,
      `expected the buffer to grow past ${HWM * 10} B, peaked at ${result.peakBufferedBytes} B`,
    );
  });
});

describe('scenario B - manual pause and drain', () => {
  it('pauses the source and keeps the buffer at about one highWaterMark', async () => {
    const result = await runBackpressureScenario({
      inputFile: input,
      scenario: 'manual',
      highWaterMark: HWM,
      delayMs: 1,
      sampleIntervalMs: 20,
    });

    assert.equal(result.chunksRead, CHUNKS);
    assert.ok(result.pauses > 0, 'the producer must have been paused at least once');
    assert.ok(
      result.peakBufferedBytes <= HWM * 2,
      `expected at most ${HWM * 2} B buffered, peaked at ${result.peakBufferedBytes} B`,
    );
  });
});

describe('scenario C - pipe()', () => {
  it('keeps the buffer bounded without any explicit pause call', async () => {
    const result = await runBackpressureScenario({
      inputFile: input,
      scenario: 'pipe',
      highWaterMark: HWM,
      delayMs: 1,
      sampleIntervalMs: 20,
    });

    assert.equal(result.chunksWritten, CHUNKS);
    assert.ok(
      result.peakBufferedBytes <= HWM * 2,
      `expected at most ${HWM * 2} B buffered, peaked at ${result.peakBufferedBytes} B`,
    );
    assert.ok(result.pausedSamples > 0, 'pipe() must have been observed holding the source paused');
  });
});

describe('the three scenarios compared', () => {
  it('differ by orders of magnitude in buffering and hardly at all in time', async () => {
    const options = { inputFile: input, highWaterMark: HWM, delayMs: 2, sampleIntervalMs: 20 };

    const uncontrolled = await runBackpressureScenario({ ...options, scenario: 'uncontrolled' });
    const piped = await runBackpressureScenario({ ...options, scenario: 'pipe' });

    assert.ok(
      uncontrolled.peakBufferedBytes > piped.peakBufferedBytes * 10,
      `A buffered ${uncontrolled.peakBufferedBytes} B, C buffered ${piped.peakBufferedBytes} B`,
    );

    // The consumer sets the pace in both cases: CHUNKS chunks at delayMs each
    // is the floor, and neither scenario can beat it.
    const floor = CHUNKS * 2;
    assert.ok(uncontrolled.elapsedMs >= floor * 0.5, `A finished in ${uncontrolled.elapsedMs} ms`);
    assert.ok(piped.elapsedMs >= floor * 0.5, `C finished in ${piped.elapsedMs} ms`);
  });

  it('refuses an unknown scenario name', async () => {
    await assert.rejects(
      runBackpressureScenario({ inputFile: input, scenario: 'whatever' }),
      /unknown scenario "whatever"/,
    );
  });
});

describe('the RSS guard of scenario A', () => {
  it('stops the run instead of letting the process grow unchecked', async () => {
    const result = await runBackpressureScenario({
      inputFile: input,
      scenario: 'uncontrolled',
      highWaterMark: HWM,
      delayMs: 5,
      // Below anything a Node process can run at, so the guard trips on the
      // first check rather than depending on how much the machine has free.
      abortRssMB: 1,
      sampleIntervalMs: 20,
    });

    assert.equal(result.aborted, true);
    assert.ok(result.chunksRead < CHUNKS, 'the run should have stopped before reading everything');
  });
});

describe('the fixture', () => {
  it('is the size the chunk arithmetic assumes', () => {
    assert.equal(fs.statSync(input).size, HWM * CHUNKS);
  });
});
