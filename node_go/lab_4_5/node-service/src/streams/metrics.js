// Resource sampling for the backpressure experiment. The claim being tested -
// "the system must not accumulate data in memory without bound" - is only
// verifiable if memory is observed while the run is in progress; the number
// after the run has already collapsed back.
//
// Two things are watched: process RSS (what the operating system sees) and
// writableLength of the streams under test (how many bytes a stream is holding
// because its consumer has not taken them yet). The second is the one that
// explains the first.
const BYTES_IN_MB = 1024 * 1024;

function mb(bytes) {
  return Number((bytes / BYTES_IN_MB).toFixed(1));
}

class ResourceSampler {
  // watch: { label: stream } - any stream exposing writableLength.
  constructor({ intervalMs = 250, watch = {} } = {}) {
    this.intervalMs = intervalMs;
    this.watch = watch;
    this.samples = [];
    this.timer = null;
    this.startedAt = 0n;
    this.peak = { rss: 0, heapUsed: 0, buffered: {} };
    for (const label of Object.keys(watch)) {
      this.peak.buffered[label] = 0;
    }
  }

  start() {
    this.startedAt = process.hrtime.bigint();
    this.sample();
    this.timer = setInterval(() => this.sample(), this.intervalMs);
    // Without unref a forgotten sampler would keep the process alive after the
    // pipeline is done.
    this.timer.unref();
    return this;
  }

  sample() {
    const memory = process.memoryUsage();
    const buffered = {};

    for (const [label, stream] of Object.entries(this.watch)) {
      const length = stream?.writableLength ?? 0;
      buffered[label] = length;
      this.peak.buffered[label] = Math.max(this.peak.buffered[label] ?? 0, length);
    }

    this.peak.rss = Math.max(this.peak.rss, memory.rss);
    this.peak.heapUsed = Math.max(this.peak.heapUsed, memory.heapUsed);

    const sample = {
      t: this.startedAt === 0n ? 0 : Number(process.hrtime.bigint() - this.startedAt) / 1e6,
      rss: memory.rss,
      heapUsed: memory.heapUsed,
      external: memory.external,
      buffered,
    };

    this.samples.push(sample);
    return sample;
  }

  stop() {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.sample();
    return this.summary();
  }

  summary() {
    // The first sample is the baseline: in a long-running server process the
    // absolute RSS is mostly the interpreter and the HTTP stack, so only the
    // growth during the run says anything about the pipeline.
    const baselineRss = this.samples.length > 0 ? this.samples[0].rss : 0;

    return {
      intervalMs: this.intervalMs,
      sampleCount: this.samples.length,
      baselineRssMB: mb(baselineRss),
      rssGrowthMB: Number((mb(this.peak.rss) - mb(baselineRss)).toFixed(1)),
      peakRssMB: mb(this.peak.rss),
      peakHeapUsedMB: mb(this.peak.heapUsed),
      peakBufferedMB: Object.fromEntries(
        Object.entries(this.peak.buffered).map(([label, bytes]) => [label, mb(bytes)]),
      ),
      peakBufferedBytes: { ...this.peak.buffered },
      // Thinned out for the report: a 90 s run at 250 ms is 360 rows, and the
      // shape is visible in a dozen.
      series: thin(this.samples, 12),
    };
  }
}

function thin(samples, target) {
  if (samples.length <= target) {
    return samples;
  }
  const step = (samples.length - 1) / (target - 1);
  return Array.from({ length: target }, (unused, index) => samples[Math.round(index * step)]);
}

module.exports = { ResourceSampler, mb, thin, BYTES_IN_MB };
