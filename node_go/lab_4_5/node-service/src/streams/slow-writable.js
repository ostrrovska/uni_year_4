const { Writable } = require('node:stream');

// The artificial slow consumer of experiment 5.1. It accepts a chunk and only
// calls back after `delayMs`, which is the one hook a Writable has for saying
// "not yet": until the callback runs, the stream counts the chunk as pending,
// its internal buffer keeps growing, and write() starts returning false.
//
// It deliberately discards the data. The experiment is about where the bytes
// pile up while waiting, not about what is finally done with them - and a real
// file sink would add disk timing noise to the measurement.
class SlowWritable extends Writable {
  constructor({ delayMs = 2, highWaterMark } = {}) {
    super({ highWaterMark, decodeStrings: true });

    this.delayMs = delayMs;
    this.chunksWritten = 0;
    this.bytesWritten = 0;
    this.peakBuffered = 0;
  }

  _write(chunk, encoding, callback) {
    this.chunksWritten += 1;
    this.bytesWritten += chunk.length;
    // Sampled here as well as by the sampler timer: the true peak can sit
    // between two 250 ms samples.
    this.peakBuffered = Math.max(this.peakBuffered, this.writableLength);

    if (this.delayMs === 0) {
      setImmediate(callback);
      return;
    }

    setTimeout(callback, this.delayMs);
  }
}

module.exports = { SlowWritable };
