const { EventEmitter } = require('node:events');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

const { DomainError } = require('../errors/domain-error');
const { runStreamPipeline, runBackpressureScenario } = require('../streams/pipeline.runner');
const { mb } = require('../streams/metrics');

// Business logic of the streaming module, in the same position ItemService
// occupies for the CRUD module: it knows about jobs, limits and the pipeline,
// and nothing about HTTP or WebSocket.
//
// Requirement 9 asks that processed chunks reach connected clients in real
// time. The decoupling that keeps the layering honest is here: the service
// emits events, and a separate bridge forwards them to the broadcaster. The
// service would behave identically with no WebSocket module present, and the
// WebSocket module works with no job ever started - which is what "separated
// responsibilities" has to mean in practice.
//
// Jobs run in the background and the HTTP call returns 202 immediately, because
// a 256 MB run takes longer than any sensible request timeout.
const MODES = {
  // Full chain into a real output file. chain=pipe uses the literal
  // readable.pipe(...).pipe(...) of requirement 4, chain=pipeline uses
  // stream.pipeline, which also forwards errors and destroys the stages.
  analyze: 'analyze',
  // Same chain, but the writable is the artificial slow consumer, so the run
  // shows backpressure holding a fast producer back.
  slow: 'slow',
  // The three-scenario comparison of requirement 5 in one job, so the
  // dashboard can draw the memory curves side by side.
  compare: 'compare',
};

const SCENARIO_ORDER = ['uncontrolled', 'manual', 'pipe'];

class StreamJobService extends EventEmitter {
  constructor({ config, log = () => {} }) {
    super();
    this.settings = config.stream;
    this.log = log;
    this.jobs = new Map();
    this.order = [];
  }

  async dataset() {
    const file = this.settings.datasetFile;

    try {
      const stat = await fsp.stat(file);
      return {
        file,
        exists: true,
        bytes: stat.size,
        sizeMB: mb(stat.size),
        modifiedAt: stat.mtime.toISOString(),
      };
    } catch (error) {
      if (error.code === 'ENOENT') {
        return { file, exists: false, bytes: 0, sizeMB: 0, modifiedAt: null };
      }
      // Anything else is an infrastructure failure and travels on untranslated,
      // exactly as in lab 4: the client learns 500, not a made-up 4xx.
      throw error;
    }
  }

  list() {
    return this.order.map((id) => this.#view(this.jobs.get(id)));
  }

  get(jobId) {
    const job = this.jobs.get(jobId);
    if (job === undefined) {
      throw DomainError.notFound('job_not_found', `Stream job "${jobId}" was not found`);
    }
    return this.#view(job);
  }

  running() {
    return [...this.jobs.values()].filter((job) => job.state === 'running');
  }

  async start(options = {}) {
    const dataset = await this.dataset();
    if (!dataset.exists) {
      throw DomainError.unavailable(
        'dataset_missing',
        `Test dataset ${dataset.file} does not exist, run "npm run gen:data" first`,
      );
    }

    if (this.running().length >= this.settings.maxConcurrentJobs) {
      throw DomainError.rateLimited(
        'too_many_jobs',
        `At most ${this.settings.maxConcurrentJobs} stream jobs may run at once`,
      );
    }

    const mode = options.mode ?? 'analyze';
    if (!(mode in MODES)) {
      throw DomainError.validation('invalid_mode', `Unknown mode "${mode}", expected one of ${Object.keys(MODES).join(', ')}`);
    }

    const job = {
      id: crypto.randomUUID().slice(0, 8),
      mode,
      chain: options.chain ?? 'pipeline',
      state: 'running',
      startedAt: new Date().toISOString(),
      finishedAt: null,
      controller: new AbortController(),
      options: {
        highWaterMark: options.highWaterMark ?? this.settings.highWaterMark,
        slowDelayMs: options.slowDelayMs ?? this.settings.slowDelayMs,
        levels: options.levels ?? null,
        grep: options.grep ?? null,
        minLatencyMs: options.minLatencyMs ?? null,
        bytes: options.bytes ?? null,
        delayMs: options.delayMs ?? this.settings.slowDelayMs,
        // Requirement 9: every n-th processed record is forwarded to the
        // subscribed clients. 0 means progress only.
        sampleEvery: options.sampleEvery ?? 0,
        chunkBatch: options.chunkBatch ?? 25,
      },
      datasetBytes: dataset.bytes,
      progress: null,
      result: null,
      error: null,
      scenarios: [],
    };

    this.jobs.set(job.id, job);
    this.order.push(job.id);
    this.#prune();

    this.emit('job:started', { job: this.#view(job) });
    this.log(`stream job ${job.id} started (mode=${job.mode}, chain=${job.chain})`);

    // Deliberately not awaited: the caller gets its 202 while the pipeline
    // runs. Every failure path inside ends up on the job record and in an
    // event, so nothing is swallowed.
    this.#run(job);

    return this.#view(job);
  }

  abort(jobId) {
    const job = this.jobs.get(jobId);
    if (job === undefined) {
      throw DomainError.notFound('job_not_found', `Stream job "${jobId}" was not found`);
    }
    if (job.state !== 'running') {
      throw DomainError.conflict('job_not_running', `Stream job "${jobId}" is ${job.state}`);
    }

    job.controller.abort();
    return this.#view(job);
  }

  async #run(job) {
    try {
      const result = job.mode === 'compare' ? await this.#runCompare(job) : await this.#runPipeline(job);

      job.state = 'done';
      job.finishedAt = new Date().toISOString();
      job.result = result;
      this.emit('job:done', { job: this.#view(job) });
      this.log(`stream job ${job.id} done in ${result.elapsedMs ?? 0} ms`);
    } catch (error) {
      job.finishedAt = new Date().toISOString();

      if (error.name === 'AbortError') {
        job.state = 'aborted';
        this.emit('job:aborted', { job: this.#view(job) });
        this.log(`stream job ${job.id} aborted`);
        return;
      }

      job.state = 'failed';
      job.error = { message: error.message, code: error.code ?? null };
      this.emit('job:error', { job: this.#view(job) });
      this.log(`stream job ${job.id} failed: ${error.message}`);
    }
  }

  async #runPipeline(job) {
    const slow = job.mode === 'slow';
    const outputFile = slow
      ? null
      : path.join(this.settings.outputDir, `events-${job.id}.ndjson`);

    return runStreamPipeline({
      inputFile: this.settings.datasetFile,
      outputFile,
      mode: job.chain === 'pipe' ? 'pipe' : 'pipeline',
      highWaterMark: job.options.highWaterMark,
      slowDelayMs: slow ? job.options.slowDelayMs : 0,
      bytes: job.options.bytes,
      filter: {
        levels: job.options.levels,
        grep: job.options.grep,
        minLatencyMs: job.options.minLatencyMs,
      },
      signal: job.controller.signal,
      progressIntervalMs: this.settings.progressIntervalMs,
      progressBytes: this.settings.progressBytes,
      sampleEvery: job.options.sampleEvery,
      chunkBatch: job.options.chunkBatch,
      onProgress: (progress) => {
        job.progress = progress;
        this.emit('job:progress', { jobId: job.id, mode: job.mode, ...progress });
      },
      onChunk:
        job.options.sampleEvery > 0
          ? (chunk) => this.emit('job:chunk', { jobId: job.id, ...chunk })
          : null,
    });
  }

  // The three scenarios run one after the other in the same process, so the RSS
  // baseline is comparable; running them in parallel would mean each one
  // measuring the others.
  async #runCompare(job) {
    const startedAt = Date.now();
    const results = [];

    for (const scenario of SCENARIO_ORDER) {
      if (job.controller.signal.aborted) {
        const error = new Error('stream job aborted');
        error.name = 'AbortError';
        throw error;
      }

      const result = await runBackpressureScenario({
        inputFile: this.settings.datasetFile,
        scenario,
        highWaterMark: job.options.highWaterMark,
        delayMs: job.options.delayMs,
        bytes: job.options.bytes,
        onSample: (sample) => {
          const progress = {
            processed: sample.bytesRead,
            total: job.options.bytes ?? job.datasetBytes,
            percent: Number(((sample.bytesRead / (job.options.bytes ?? job.datasetBytes)) * 100).toFixed(2)),
            scenario: sample.scenario,
            rssMB: sample.rssMB,
            bufferedMB: sample.bufferedMB,
            bufferedBytes: sample.bufferedBytes,
            elapsedMs: sample.t,
            paused: sample.paused,
          };
          job.progress = progress;
          this.emit('job:progress', { jobId: job.id, mode: job.mode, ...progress });
        },
      });

      results.push(result);
      job.scenarios = results.map(summarizeScenario);
      this.emit('job:scenario', { jobId: job.id, scenario: summarizeScenario(result) });
    }

    return { elapsedMs: Date.now() - startedAt, scenarios: results.map(summarizeScenario) };
  }

  // Keeps the registry from growing for the lifetime of the process while still
  // leaving the recent history readable over HTTP.
  #prune() {
    while (this.order.length > this.settings.keepJobs) {
      const oldest = this.order.find((id) => this.jobs.get(id)?.state !== 'running');
      if (oldest === undefined) {
        return;
      }
      this.order.splice(this.order.indexOf(oldest), 1);
      this.jobs.delete(oldest);
    }
  }

  // The AbortController and the raw sample arrays stay inside the service: a
  // view is what the HTTP layer and the WebSocket frames are allowed to see.
  #view(job) {
    if (job === undefined) {
      return null;
    }

    return {
      id: job.id,
      mode: job.mode,
      chain: job.chain,
      state: job.state,
      startedAt: job.startedAt,
      finishedAt: job.finishedAt,
      options: job.options,
      datasetBytes: job.datasetBytes,
      progress: job.progress,
      scenarios: job.scenarios,
      result: job.result,
      error: job.error,
    };
  }
}

function summarizeScenario(result) {
  return {
    scenario: result.scenario,
    label: result.label,
    highWaterMark: result.highWaterMark,
    delayMs: result.delayMs,
    bytesRead: result.bytesRead,
    chunks: result.chunksWritten,
    elapsedMs: result.elapsedMs,
    throughputMBps: result.throughputMBps,
    baselineRssMB: result.baselineRssMB,
    peakRssMB: result.peakRssMB,
    rssGrowthMB: result.rssGrowthMB,
    peakBufferedMB: result.peakBufferedMB,
    peakBufferedBytes: result.peakBufferedBytes,
    pauses: result.pauses,
    pausedSamples: result.pausedSamples,
    sampleCount: result.sampleCount,
    aborted: result.aborted,
    series: result.metrics.series.map((sample) => ({
      t: Math.round(sample.t),
      rssMB: mb(sample.rss),
      bufferedMB: mb(sample.buffered.sink ?? 0),
    })),
  };
}

module.exports = { StreamJobService, MODES, SCENARIO_ORDER, summarizeScenario };
