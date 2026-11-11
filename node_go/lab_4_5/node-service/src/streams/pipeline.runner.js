const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { pipeline } = require('node:stream/promises');

const { LineSplitTransform } = require('./line-split.transform');
const { EventAnalyzerTransform } = require('./event-analyzer.transform');
const { SlowWritable } = require('./slow-writable');
const { ResourceSampler, mb, BYTES_IN_MB } = require('./metrics');


function throughput(bytes, elapsedMs) {
  return elapsedMs === 0 ? 0 : Number((bytes / BYTES_IN_MB / (elapsedMs / 1000)).toFixed(2));
}

function abortError() {
  const error = new Error('stream job aborted');
  error.name = 'AbortError';
  return error;
}


function runPipeChain(stages, signal) {
  return new Promise((resolve, reject) => {
    let settled = false;

    const finish = (error) => {
      if (settled) {
        return;
      }
      settled = true;
      if (error) {
        for (const stage of stages) {
          stage.destroy();
        }
        reject(error);
        return;
      }
      resolve();
    };

    for (const stage of stages) {
      stage.on('error', finish);
    }

    const last = stages.reduce((upstream, downstream) => upstream.pipe(downstream));
    last.on('finish', () => finish());

    if (signal) {
      if (signal.aborted) {
        finish(abortError());
        return;
      }
      signal.addEventListener('abort', () => finish(abortError()), { once: true });
    }
  });
}

async function runStreamPipeline({
  inputFile,
  outputFile = null,
  mode = 'pipeline',
  highWaterMark = 64 * 1024,
  slowDelayMs = 0,
  bytes = null,
  filter = {},
  signal = null,
  onProgress = null,
  onChunk = null,
  sampleEvery = 0,
  chunkBatch = 25,
  progressIntervalMs = 100,
  progressBytes = 4 * 1024 * 1024,
  sampleIntervalMs = 250,
}) {
  if (mode !== 'pipe' && mode !== 'pipeline') {
    throw new Error(`unknown mode "${mode}", expected "pipe" or "pipeline"`);
  }

  const size = (await fsp.stat(inputFile)).size;
  const total = bytes === null ? size : Math.min(bytes, size);

  const readable =
    bytes === null
      ? fs.createReadStream(inputFile, { highWaterMark })
      : fs.createReadStream(inputFile, { highWaterMark, start: 0, end: total - 1 });
  const split = new LineSplitTransform({ highWaterMark });
  const analyzer = new EventAnalyzerTransform({ ...filter, sampleEvery: onChunk === null ? 0 : sampleEvery });

  if (slowDelayMs === 0) {
    await fsp.mkdir(path.dirname(outputFile), { recursive: true });
  }

  const sink =
    slowDelayMs > 0
      ? new SlowWritable({ delayMs: slowDelayMs, highWaterMark })
      : fs.createWriteStream(outputFile, { highWaterMark });

  const sampler = new ResourceSampler({
    intervalMs: sampleIntervalMs,
    watch: { split, analyzer, sink },
  }).start();

  const startedAt = process.hrtime.bigint();
  let lastProgressAt = 0;
  let lastProgressBytes = 0;

  const elapsed = () => Number(process.hrtime.bigint() - startedAt) / 1e6;

  const snapshot = (processed) => {
    const elapsedMs = elapsed();
    return {
      processed,
      total,
      percent: total === 0 ? 100 : Number(((processed / total) * 100).toFixed(2)),
      elapsedMs: Math.round(elapsedMs),
      throughputMBps: throughput(processed, elapsedMs),
      linesIn: analyzer.stats.linesIn,
      linesOut: analyzer.stats.linesOut,
      malformed: analyzer.stats.malformed,
      chunksIn: split.chunksIn,
      rssMB: mb(process.memoryUsage.rss()),
      bufferedBytes: sink.writableLength,
    };
  };

  // Progress is emitted on whichever limit is reached first: the time one keeps
  // a slow run informative, the byte one keeps a fast run from emitting
  // thousands of frames a second.
  if (onProgress) {
    split.on('bytes', (bytes) => {
      const now = elapsed();
      if (now - lastProgressAt < progressIntervalMs && bytes - lastProgressBytes < progressBytes) {
        return;
      }
      lastProgressAt = now;
      lastProgressBytes = bytes;
      onProgress(snapshot(bytes));
    });
  }

  // Sampled records are grouped before being handed up: one frame carrying
  // twenty records costs one send() instead of twenty, and the consumer gets
  // the same data. The grouping belongs here rather than in the analyzer, which
  // has no reason to know that anything downstream prefers batches.
  if (onChunk !== null && sampleEvery > 0) {
    let pending = [];
    let seq = 0;

    analyzer.on('sample', (record) => {
      pending.push(record);
      if (pending.length >= chunkBatch) {
        seq += 1;
        onChunk({ seq, sampledEvery: sampleEvery, records: pending });
        pending = [];
      }
    });

    analyzer.on('stats', () => {
      if (pending.length > 0) {
        seq += 1;
        onChunk({ seq, sampledEvery: sampleEvery, records: pending });
        pending = [];
      }
    });
  }

  const stages = [readable, split, analyzer, sink];

  try {
    if (mode === 'pipe') {
      await runPipeChain(stages, signal);
    } else {
      // stream.pipeline rejects a null signal rather than ignoring it, and
      // reads a second argument of undefined as another stream, so the options
      // object has to be left off entirely when there is no signal.
      await (signal === null ? pipeline(stages) : pipeline(stages, { signal }));
    }
  } finally {
    sampler.stop();
  }

  const elapsedMs = Math.round(elapsed());

  // Marked final, and that mark matters: a progress frame is normally
  // droppable, because a newer one supersedes it. Nothing supersedes this one,
  // so the WebSocket policy must not rate-limit it away and leave a client
  // showing 99.9% for ever.
  if (onProgress) {
    onProgress({ ...snapshot(split.bytesIn), percent: 100, final: true });
  }

  return {
    mode,
    inputFile,
    outputFile: slowDelayMs > 0 ? null : outputFile,
    slowDelayMs,
    highWaterMark,
    totalBytes: total,
    outputBytes: analyzer.stats.bytesOut,
    elapsedMs,
    throughputMBps: throughput(total, elapsedMs),
    chunks: { ...split.chunkStats, outputChunks: analyzer.chunksOut },
    stats: analyzer.stats,
    sink:
      slowDelayMs > 0
        ? { kind: 'slow', chunksWritten: sink.chunksWritten, bytesWritten: sink.bytesWritten }
        : { kind: 'file', path: outputFile },
    metrics: sampler.summary(),
  };
}

const SCENARIOS = {
  // Reads as fast as the disk allows and never looks at what write() returned.
  // Every chunk the consumer has not finished with stays in the writable
  // internal buffer, so the buffer grows to the size of the whole file.
  uncontrolled: 'A',
  // What pipe() does internally, written out: false means stop, drain means go.
  manual: 'B',
  // The same thing through the stream machinery.
  pipe: 'C',
};

async function runBackpressureScenario({
  inputFile,
  scenario,
  highWaterMark = 64 * 1024,
  delayMs = 2,
  bytes = null,
  abortRssMB = 2000,
  sampleIntervalMs = 250,
  onSample = null,
}) {
  if (!(scenario in SCENARIOS)) {
    throw new Error(`unknown scenario "${scenario}", expected one of ${Object.keys(SCENARIOS).join(', ')}`);
  }

  const size = (await fsp.stat(inputFile)).size;
  const limit = bytes === null ? size : Math.min(bytes, size);

  const readable = fs.createReadStream(inputFile, { highWaterMark, start: 0, end: limit - 1 });
  const sink = new SlowWritable({ delayMs, highWaterMark });

  const baselineRss = process.memoryUsage.rss();
  const sampler = new ResourceSampler({ intervalMs: sampleIntervalMs, watch: { sink } });

  let pauses = 0;
  let pausedSamples = 0;
  let aborted = false;
  let bytesRead = 0;
  let chunksRead = 0;

  const startedAt = process.hrtime.bigint();
  const elapsed = () => Number(process.hrtime.bigint() - startedAt) / 1e6;

  // Sampling and the paused-state census share one timer, so the two columns of
  // the results table are taken at the same instants.
  const takeSample = sampler.sample.bind(sampler);
  sampler.sample = () => {
    const sample = takeSample();
    if (readable.isPaused()) {
      pausedSamples += 1;
    }
    if (onSample) {
      onSample({
        scenario,
        t: Math.round(sample.t),
        rssMB: mb(sample.rss),
        bufferedBytes: sample.buffered.sink ?? 0,
        bufferedMB: mb(sample.buffered.sink ?? 0),
        bytesRead,
        chunksWritten: sink.chunksWritten,
        paused: readable.isPaused(),
      });
    }
    return sample;
  };
  sampler.start();

  await new Promise((resolve, reject) => {
    let settled = false;
    const done = (error) => {
      if (settled) {
        return;
      }
      settled = true;
      if (error) {
        reject(error);
        return;
      }
      resolve();
    };

    readable.on('error', done);
    sink.on('error', done);
    sink.on('finish', () => done());

    if (scenario === 'pipe') {
      readable.pipe(sink);
      return;
    }

    readable.on('data', (chunk) => {
      bytesRead += chunk.length;
      chunksRead += 1;

      const accepted = sink.write(chunk);

      if (scenario === 'manual' && !accepted) {
        pauses += 1;
        readable.pause();
        sink.once('drain', () => readable.resume());
      }


      if (scenario === 'uncontrolled' && chunksRead % 32 === 0) {
        if (process.memoryUsage.rss() / BYTES_IN_MB > abortRssMB) {
          aborted = true;
          readable.destroy();
          sink.destroy();
          done();
        }
      }
    });

    readable.on('end', () => sink.end());
  });

  sampler.stop();
  const elapsedMs = Math.round(elapsed());
  const summary = sampler.summary();
  const peakBuffered = Math.max(sink.peakBuffered, sampler.peak.buffered.sink ?? 0);

  return {
    scenario,
    label: SCENARIOS[scenario],
    highWaterMark,
    delayMs,
    bytesTarget: limit,
    bytesRead: scenario === 'pipe' ? sink.bytesWritten : bytesRead,
    chunksRead: scenario === 'pipe' ? sink.chunksWritten : chunksRead,
    chunksWritten: sink.chunksWritten,
    elapsedMs,
    throughputMBps: throughput(sink.bytesWritten, elapsedMs),
    baselineRssMB: mb(baselineRss),
    peakRssMB: summary.peakRssMB,
    rssGrowthMB: Number((summary.peakRssMB - mb(baselineRss)).toFixed(1)),
    peakBufferedBytes: peakBuffered,
    peakBufferedMB: mb(peakBuffered),
    pauses,
    pausedSamples,
    sampleCount: sampler.samples.length,
    aborted,
    metrics: summary,
  };
}

module.exports = { runStreamPipeline, runBackpressureScenario, SCENARIOS, throughput };
