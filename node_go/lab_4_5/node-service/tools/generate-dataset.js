const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { once } = require('node:events');

const { config } = require('../src/config');
const { mb, BYTES_IN_MB } = require('../src/streams/metrics');

// Requirement 1: a test file far larger than any single buffer. 256 MB by
// default, which is well past the 2 MB a Buffer-based approach would be
// comfortable with and past the 16 MB default of most line readers.
//
// The generator is itself a backpressure demonstration, and the simplest one in
// the lab: it produces lines in a loop much faster than the disk accepts them,
// so it has to obey what write() returns. Ignoring that single boolean is all
// it would take to hold the whole file in memory while writing it - the same
// mistake scenario A of the backpressure experiment makes on the reading side.

const LEVELS = ['debug', 'info', 'info', 'info', 'warn', 'error'];
const SERVICES = ['api', 'worker', 'db', 'gateway'];
const ACTIONS = [
  'item created',
  'item updated',
  'item deleted',
  'item fetched',
  'validation rejected',
  'repository timeout',
  'cache miss',
  'name conflict',
];

// A deterministic generator, so two runs of the demo produce byte-identical
// files and the numbers in the report can be compared across runs.
function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function parseArgs(argv) {
  const args = {
    sizeMB: 256,
    out: config.stream.datasetFile,
    seed: 42,
    corruptEvery: 50000,
    highWaterMark: config.stream.highWaterMark,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split('=');
    const value = inlineValue ?? argv[index + 1];
    const consumeNext = inlineValue === undefined;

    switch (flag) {
      case '--size':
        args.sizeMB = Number(value);
        break;
      case '--out':
        args.out = path.resolve(value);
        break;
      case '--seed':
        args.seed = Number(value);
        break;
      case '--corrupt-every':
        args.corruptEvery = Number(value);
        break;
      case '--hwm':
        args.highWaterMark = Number(value);
        break;
      case '--help':
        printUsage();
        process.exit(0);
        break;
      default:
        throw new Error(`unknown argument "${argv[index]}"`);
    }

    if (consumeNext) {
      index += 1;
    }
  }

  if (!Number.isFinite(args.sizeMB) || args.sizeMB <= 0) {
    throw new Error(`--size must be a positive number of megabytes, got "${args.sizeMB}"`);
  }

  return args;
}

function printUsage() {
  console.log(`Usage: node tools/generate-dataset.js [options]

  --size <MB>            target file size, default 256
  --out <path>           output file, default ${config.stream.datasetFile}
  --seed <n>             LCG seed, default 42
  --corrupt-every <n>    write one unparsable line every n lines, default 50000
  --hwm <bytes>          write stream highWaterMark, default ${config.stream.highWaterMark}
`);
}

async function generate(args) {
  await fsp.mkdir(path.dirname(args.out), { recursive: true });

  const target = Math.round(args.sizeMB * BYTES_IN_MB);
  const random = lcg(args.seed);
  const stream = fs.createWriteStream(args.out, { highWaterMark: args.highWaterMark });

  const startedAt = process.hrtime.bigint();
  const byLevel = {};
  let peakRss = process.memoryUsage.rss();
  let written = 0;
  let lines = 0;
  let corrupt = 0;
  // One timestamp base plus a monotonically growing offset: the records look
  // like a log without calling Date twice per line.
  const base = Date.UTC(2026, 10, 1, 9, 0, 0);

  while (written < target) {
    // A batch, not a line, per loop turn: one write() per line would mean
    // several million calls and the measurement would be dominated by them.
    let batch = '';

    while (batch.length < 256 * 1024 && written + batch.length < target) {
      lines += 1;

      if (args.corruptEvery > 0 && lines % args.corruptEvery === 0) {
        corrupt += 1;
        batch += '{ this line is not valid json\n';
        continue;
      }

      const level = LEVELS[Math.floor(random() * LEVELS.length)];
      byLevel[level] = (byLevel[level] ?? 0) + 1;

      batch += `${JSON.stringify({
        ts: new Date(base + lines * 7).toISOString(),
        level,
        service: SERVICES[Math.floor(random() * SERVICES.length)],
        itemId: 1 + Math.floor(random() * 100000),
        latencyMs: Math.round(random() * 1500),
        msg: ACTIONS[Math.floor(random() * ACTIONS.length)],
      })}\n`;
    }

    written += Buffer.byteLength(batch);

    // The one line that keeps memory flat. Without the await, the loop would
    // queue every batch inside the stream and the process would hold the whole
    // file in RAM.
    if (!stream.write(batch)) {
      await once(stream, 'drain');
    }

    peakRss = Math.max(peakRss, process.memoryUsage.rss());
  }

  stream.end();
  await once(stream, 'finish');

  const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
  const size = (await fsp.stat(args.out)).size;

  return { size, lines, corrupt, byLevel, elapsedMs, peakRss };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  console.log(`generating ${args.sizeMB} MB into ${args.out} (seed ${args.seed})`);

  const result = await generate(args);

  console.log('');
  console.log(`file            ${args.out}`);
  console.log(`size            ${mb(result.size)} MB (${result.size} bytes)`);
  console.log(`lines           ${result.lines} (${result.corrupt} deliberately corrupt)`);
  console.log(`by level        ${JSON.stringify(result.byLevel)}`);
  console.log(`elapsed         ${Math.round(result.elapsedMs)} ms`);
  console.log(`throughput      ${(result.size / BYTES_IN_MB / (result.elapsedMs / 1000)).toFixed(1)} MB/s`);
  console.log(`peak RSS        ${mb(result.peakRss)} MB`);
  console.log('');
  console.log(`peak RSS is the point: ${mb(result.size)} MB were written while the process`);
  console.log(`held ${mb(result.peakRss)} MB, because write() was allowed to say "not yet".`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = { generate, parseArgs, lcg };
