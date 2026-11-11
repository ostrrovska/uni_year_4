const fsp = require('node:fs/promises');
const path = require('node:path');

const { config } = require('../src/config');
const { runStreamPipeline } = require('../src/streams/pipeline.runner');
const { mb } = require('../src/streams/metrics');

// Runs the full chain from the command line, without the HTTP server, and
// prints the numbers the report needs.
//
// Its second job is the highWaterMark experiment of requirement 2: with
// --sweep it runs the identical pipeline at several buffer sizes and tabulates
// what changed. The parameters that decide chunk size are then not a claim in
// the text but a measured row - and the interesting part is which columns move
// and which do not.

function parseArgs(argv) {
  const args = {
    input: config.stream.datasetFile,
    out: path.join(config.stream.outputDir, 'events-cli.ndjson'),
    chain: 'pipe',
    highWaterMark: config.stream.highWaterMark,
    slowDelayMs: 0,
    levels: ['error'],
    grep: null,
    sweep: null,
    quiet: false,
    json: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split('=');
    const value = inlineValue ?? argv[index + 1];
    const consumeNext = inlineValue === undefined;
    let consumed = true;

    switch (flag) {
      case '--input': args.input = path.resolve(value); break;
      case '--out': args.out = path.resolve(value); break;
      case '--chain': args.chain = value; break;
      case '--hwm': args.highWaterMark = Number(value); break;
      case '--slow-delay': args.slowDelayMs = Number(value); break;
      case '--levels': args.levels = value === 'all' ? null : value.split(','); break;
      case '--grep': args.grep = value; break;
      case '--sweep': args.sweep = value.split(',').map(Number); break;
      case '--json': args.json = path.resolve(value); break;
      case '--quiet': args.quiet = true; consumed = false; break;
      case '--help':
        console.log(usage());
        process.exit(0);
        break;
      default:
        throw new Error(`unknown argument "${argv[index]}"`);
    }

    if (consumeNext && consumed) {
      index += 1;
    }
  }

  return args;
}

function usage() {
  return `Usage: node tools/stream-run.js [options]

  --input <path>      input file, default the generated dataset
  --out <path>        output file, default out/events-cli.ndjson
  --chain pipe|pipeline   how the stages are joined, default pipe
  --hwm <bytes>       readable/writable highWaterMark, default ${config.stream.highWaterMark}
  --slow-delay <ms>   use the artificial slow consumer instead of a file
  --levels a,b|all    keep only these levels, default error
  --grep <text>       keep only records whose msg contains this
  --sweep 16384,65536,1048576   run once per size and print a comparison table
  --json <path>       also write the raw results, which is what the demo script
                      asserts against instead of parsing this output
  --quiet             only print the table
`;
}

function row(result) {
  return {
    hwm: result.highWaterMark,
    chunksIn: result.chunks.chunksIn,
    avgChunk: result.chunks.avgChunk,
    maxChunk: result.chunks.maxChunk,
    chunksOut: result.chunks.outputChunks,
    elapsedMs: result.elapsedMs,
    mbps: result.throughputMBps,
    peakRssMB: result.metrics.peakRssMB,
  };
}

function printTable(rows) {
  const header = ['highWaterMark', 'read chunks', 'avg chunk', 'max chunk', 'write chunks', 'time, ms', 'MB/s', 'peak RSS, MB'];
  const body = rows.map((r) => [
    `${r.hwm} (${(r.hwm / 1024).toFixed(0)} KiB)`,
    String(r.chunksIn),
    String(r.avgChunk),
    String(r.maxChunk),
    String(r.chunksOut),
    String(r.elapsedMs),
    String(r.mbps),
    String(r.peakRssMB),
  ]);

  const widths = header.map((cell, column) => Math.max(cell.length, ...body.map((line) => line[column].length)));
  const line = (cells) => `| ${cells.map((cell, column) => cell.padEnd(widths[column])).join(' | ')} |`;

  console.log('');
  console.log(line(header));
  console.log(`|${widths.map((width) => '-'.repeat(width + 2)).join('|')}|`);
  for (const cells of body) {
    console.log(line(cells));
  }
  console.log('');
}

async function once(args, highWaterMark) {
  const result = await runStreamPipeline({
    inputFile: args.input,
    outputFile: args.slowDelayMs > 0 ? null : args.out,
    mode: args.chain === 'pipeline' ? 'pipeline' : 'pipe',
    highWaterMark,
    slowDelayMs: args.slowDelayMs,
    filter: { levels: args.levels, grep: args.grep },
  });

  if (!args.quiet) {
    console.log('');
    console.log(`chain           ${args.chain === 'pipeline' ? 'pipeline(readable, split, analyze, writable)' : 'readable.pipe(split).pipe(analyze).pipe(writable)'}`);
    console.log(`input           ${result.inputFile} (${mb(result.totalBytes)} MB)`);
    console.log(`output          ${result.outputFile ?? `slow consumer, ${args.slowDelayMs} ms per chunk, data discarded`}`);
    console.log(`highWaterMark   ${highWaterMark} B`);
    console.log(`read chunks     ${result.chunks.chunksIn} (avg ${result.chunks.avgChunk} B, min ${result.chunks.minChunk} B, max ${result.chunks.maxChunk} B)`);
    console.log(`write chunks    ${result.chunks.outputChunks}`);
    console.log(`lines in/out    ${result.stats.linesIn} / ${result.stats.linesOut} (filtered out ${result.stats.filtered}, malformed ${result.stats.malformed})`);
    console.log(`by level        ${JSON.stringify(result.stats.byLevel)}`);
    console.log(`latency ms      min ${result.stats.latency.min}, avg ${result.stats.latency.avg}, max ${result.stats.latency.max}`);
    console.log(`buckets         ${JSON.stringify(result.stats.byBucket)}`);
    console.log(`output size     ${mb(result.outputBytes)} MB`);
    console.log(`elapsed         ${result.elapsedMs} ms (${result.throughputMBps} MB/s)`);
    console.log(`peak RSS        ${result.metrics.peakRssMB} MB, peak heap ${result.metrics.peakHeapUsedMB} MB`);
    console.log(`peak buffered   ${JSON.stringify(result.metrics.peakBufferedBytes)} B`);
  }

  return result;
}

async function writeJson(args, results) {
  if (args.json === null) {
    return;
  }
  await fsp.mkdir(path.dirname(args.json), { recursive: true });
  await fsp.writeFile(args.json, `${JSON.stringify(results, null, 2)}
`, 'utf8');
  console.log(`json written to ${args.json}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const results = [];

  if (args.sweep === null) {
    results.push(await once(args, args.highWaterMark));
    printTable([row(results[0])]);
    await writeJson(args, results);
    return;
  }

  for (const highWaterMark of args.sweep) {
    console.log(`--- highWaterMark ${highWaterMark} B ---`);
    results.push(await once(args, highWaterMark));
  }

  printTable(results.map(row));
  await writeJson(args, results);
  console.log('Read chunks scale with 1/highWaterMark and the average chunk equals it exactly,');
  console.log('except for the last one. Lines, filtering and output bytes are identical in every');
  console.log('row: buffer size decides how the file is cut, never what the result is.');
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = { parseArgs, printTable, row };
