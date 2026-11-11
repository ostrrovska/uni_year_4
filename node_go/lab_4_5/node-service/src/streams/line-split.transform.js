const { Transform } = require('node:stream');
const { StringDecoder } = require('node:string_decoder');

// First stage of the chain: byte chunks in, whole lines out.
//
// It exists because a Readable gives no guarantee about where a chunk ends. A
// 64 KiB read lands wherever 64 KiB happens to land - almost always in the
// middle of a line, and sometimes in the middle of a multi-byte character. A
// transform that tried to JSON.parse a raw chunk would fail on nearly every
// one of them. So this stage keeps two pieces of state: the decoder, which
// holds back an incomplete UTF-8 sequence until its remaining bytes arrive,
// and `tail`, which holds the unterminated last line until its newline arrives.
//
// The writable side stays in byte mode, the readable side is objectMode because
// it emits strings of arbitrary length that must not be concatenated by the
// stream machinery.
class LineSplitTransform extends Transform {
  constructor({ highWaterMark, maxLineBytes = 1024 * 1024 } = {}) {
    super({
      readableObjectMode: true,
      // Byte budget on the input side, object count on the output side. Passing
      // one `highWaterMark` would mean "16 lines" on both, which is not what
      // the chunk-size experiment is about.
      writableHighWaterMark: highWaterMark,
      readableHighWaterMark: 256,
    });

    this.decoder = new StringDecoder('utf8');
    this.tail = '';
    this.maxLineBytes = maxLineBytes;

    this.bytesIn = 0;
    this.linesOut = 0;
    this.chunksIn = 0;
    this.minChunk = Infinity;
    this.maxChunk = 0;
  }

  _transform(chunk, encoding, callback) {
    this.bytesIn += chunk.length;
    this.chunksIn += 1;
    this.minChunk = Math.min(this.minChunk, chunk.length);
    this.maxChunk = Math.max(this.maxChunk, chunk.length);

    // Lets the runner report progress without attaching a second "data"
    // listener to the readable, which would interfere with pipe().
    this.emit('bytes', this.bytesIn);

    const text = this.decoder.write(chunk);
    let start = 0;
    let index = text.indexOf('\n');

    while (index !== -1) {
      // Only the first line of a chunk can have a tail from the previous one.
      const line = this.tail === '' ? text.slice(start, index) : this.tail + text.slice(start, index);
      this.tail = '';
      this.#pushLine(line);
      start = index + 1;
      index = text.indexOf('\n', start);
    }

    this.tail += text.slice(start);

    // A file with no newline at all would otherwise grow `tail` until the
    // process dies - the very failure mode streaming is supposed to avoid.
    if (Buffer.byteLength(this.tail) > this.maxLineBytes) {
      callback(new Error(`line exceeds ${this.maxLineBytes} bytes without a newline`));
      return;
    }

    callback();
  }

  // Everything still held back when the source ends: the unterminated last
  // line plus whatever the decoder was waiting on.
  _flush(callback) {
    const rest = this.tail + this.decoder.end();
    this.tail = '';
    if (rest !== '') {
      this.#pushLine(rest);
    }
    callback();
  }

  // CRLF files would otherwise hand a stray \r to JSON.parse.
  #pushLine(line) {
    this.linesOut += 1;
    this.push(line.endsWith('\r') ? line.slice(0, -1) : line);
  }

  get chunkStats() {
    return {
      chunksIn: this.chunksIn,
      bytesIn: this.bytesIn,
      avgChunk: this.chunksIn === 0 ? 0 : Math.round(this.bytesIn / this.chunksIn),
      minChunk: this.chunksIn === 0 ? 0 : this.minChunk,
      maxChunk: this.maxChunk,
    };
  }
}

module.exports = { LineSplitTransform };
