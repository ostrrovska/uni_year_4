const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const { config } = require('../src/config');
const { runBackpressureScenario } = require('../src/streams/pipeline.runner');
const { mb } = require('../src/streams/metrics');

// Requirement 5: the same file, the same slow consumer, three producers.
//
//   A  uncontrolled  write() is called for every chunk and its return value is
//                    ignored. Nothing ever pauses.
//   B  manual        false means pause, drain means resume - pipe() unrolled.
//   C  pipe          readable.pipe(slowWritable).
//
// A and C differ in exactly one respect, so the difference in the table has
// exactly one cause. B is in the middle because it shows that the mechanism is
// not magic: two event handlers are the whole of it.
//
// The claim under test is not "C is faster" - it is usually not, and the table
// says so. It is that A stores the entire file in the process while C stores
// one buffer, and that the wall clock is set by the consumer either way.

function parseArgs(argv) {
  const args = {
    input: config.stream.datasetFile,
    scenarios: ['uncontrolled', 'manual', 'pipe'],
    highWaterMark: config.stream.highWaterMark,
    delayMs: 2,
    bytes: null,
    abortRssMB: 2000,
    json: null,
    markdown: null,
    // Each scenario gets its own process by default. The operating system does
    // not hand RSS back when a buffer is freed, so after scenario A has held
    // 250 MB the next scenario starts from that high-water mark and its own
    // peak RSS says nothing. One process per scenario is the only way the RSS
    // column means what it claims.
    sameProcess: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const [flag, inlineValue] = argv[index].split('=');
    const value = inlineValue ?? argv[index + 1];
    const consumeNext = inlineValue === undefined;

    switch (flag) {
      case '--input': args.input = path.resolve(value); break;
      case '--scenarios': args.scenarios = value.split(','); break;
      case '--hwm': args.highWaterMark = Number(value); break;
      case '--delay-ms': args.delayMs = Number(value); break;
      case '--bytes': args.bytes = Number(value); break;
      case '--mb': args.bytes = Math.round(Number(value) * 1024 * 1024); break;
      case '--abort-rss-mb': args.abortRssMB = Number(value); break;
      case '--json': args.json = path.resolve(value); break;
      case '--markdown': args.markdown = path.resolve(value); break;
      case '--same-process':
        args.sameProcess = true;
        index -= consumeNext ? 1 : 0;
        break;
      case '--help':
        console.log(usage());
        process.exit(0);
        break;
      default:
        throw new Error(`unknown argument "${argv[index]}"`);
    }

    if (consumeNext) {
      index += 1;
    }
  }

  return args;
}

function usage() {
  return `Usage: node tools/backpressure-compare.js [options]

  --input <path>        input file, default the generated dataset
  --scenarios a,b,c     subset of uncontrolled,manual,pipe
  --hwm <bytes>         highWaterMark for both ends, default ${config.stream.highWaterMark}
  --delay-ms <ms>       slow consumer delay per chunk, default 2
  --mb <n>              read only the first n MB
  --abort-rss-mb <n>    stop scenario A if RSS passes this, default 2000
  --json <path>         also write the raw results
  --markdown <path>     also write the comparison table as markdown
  --same-process        run every scenario in this process (RSS column becomes
                        meaningless, kept for comparison)
`;
}

const TITLES = {
  uncontrolled: 'A - no flow control',
  manual: 'B - manual pause/drain',
  pipe: 'C - pipe()',
};

function table(results) {
  const header = [
    'scenario',
    'read, MB',
    'chunks',
    'time, ms',
    'MB/s',
    'peak buffered',
    'peak RSS, MB',
    'RSS growth, MB',
    'pauses',
  ];

  const body = results.map((result) => [
    TITLES[result.scenario],
    String(mb(result.bytesRead)),
    String(result.chunksWritten),
    String(result.elapsedMs),
    String(result.throughputMBps),
    `${result.peakBufferedMB} MB`,
    String(result.peakRssMB),
    String(result.rssGrowthMB),
    result.scenario === 'pipe' ? `${result.pausedSamples} samples paused` : String(result.pauses),
  ]);

  const widths = header.map((cell, column) => Math.max(cell.length, ...body.map((line) => line[column].length)));
  const line = (cells) => `| ${cells.map((cell, column) => cell.padEnd(widths[column])).join(' | ')} |`;

  return [
    line(header),
    `|${widths.map((width) => '-'.repeat(width + 2)).join('|')}|`,
    ...body.map(line),
  ].join('\n');
}

function series(results) {
  const lines = [];

  for (const result of results) {
    lines.push('');
    lines.push(`${TITLES[result.scenario]} - buffered bytes and RSS over time`);
    lines.push('');
    lines.push('| t, ms | buffered, MB | RSS, MB |');
    lines.push('|-------|--------------|---------|');
    for (const sample of result.metrics.series) {
      lines.push(`| ${Math.round(sample.t)} | ${mb(sample.buffered.sink ?? 0)} | ${mb(sample.rss)} |`);
    }
  }

  return lines.join('\n');
}

function runHere(args, scenario) {
  return runBackpressureScenario({
    inputFile: args.input,
    scenario,
    highWaterMark: args.highWaterMark,
    delayMs: args.delayMs,
    bytes: args.bytes,
    abortRssMB: args.abortRssMB,
  });
}

// Runs one scenario in a fresh process and reads its result back from a
// temporary file. Synchronous on purpose: the scenarios must not overlap, since
// they would then compete for the same disk and the same CPU.
function runInChild(args, scenario) {
  const out = path.join(os.tmpdir(), `lab5-bp-${scenario}-${process.pid}.json`);
  const argv = [
    __filename,
    '--same-process',
    '--input', args.input,
    '--scenarios', scenario,
    '--hwm', String(args.highWaterMark),
    '--delay-ms', String(args.delayMs),
    '--abort-rss-mb', String(args.abortRssMB),
    '--json', out,
  ];

  if (args.bytes !== null) {
    argv.push('--bytes', String(args.bytes));
  }

  execFileSync(process.execPath, argv, { stdio: 'ignore' });

  const results = JSON.parse(fs.readFileSync(out, 'utf8'));
  fs.rmSync(out, { force: true });
  return results[0];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const results = [];

  console.log(`input           ${args.input}`);
  console.log(`highWaterMark   ${args.highWaterMark} B`);
  console.log(`consumer delay  ${args.delayMs} ms per chunk`);
  console.log(`limit           ${args.bytes === null ? 'whole file' : `${mb(args.bytes)} MB`}`);

  const fork = !args.sameProcess && args.scenarios.length > 1;

  for (const scenario of args.scenarios) {
    console.log('');
    console.log(`running ${TITLES[scenario] ?? scenario}${fork ? ' in a child process' : ''} ...`);

    const result = fork ? runInChild(args, scenario) : await runHere(args, scenario);
    results.push(result);

    console.log(
      `  ${result.elapsedMs} ms, peak buffered ${result.peakBufferedMB} MB, ` +
        `peak RSS ${result.peakRssMB} MB (baseline ${result.baselineRssMB} MB)` +
        `${result.aborted ? ' - ABORTED on the RSS guard' : ''}`,
    );
  }

  const rendered = table(results);
  console.log('');
  console.log(rendered);
  console.log('');

  const bufferedSpread =
    Math.max(...results.map((r) => r.peakBufferedBytes)) /
    Math.max(1, Math.min(...results.map((r) => r.peakBufferedBytes)));
  console.log(`peak buffered differs by a factor of ${bufferedSpread.toFixed(0)} between the extremes,`);
  console.log('while the wall clock is set by the consumer and barely moves.');

  if (args.markdown !== null) {
    await fsp.mkdir(path.dirname(args.markdown), { recursive: true });
    await fsp.writeFile(
      args.markdown,
      [
        '# Backpressure comparison',
        '',
        `- input: \`${args.input}\``,
        `- highWaterMark: ${args.highWaterMark} B`,
        `- slow consumer: ${args.delayMs} ms per chunk`,
        `- limit: ${args.bytes === null ? 'whole file' : `${mb(args.bytes)} MB`}`,
        '',
        rendered,
        '',
        series(results),
        '',
      ].join('\n'),
      'utf8',
    );
    console.log(`markdown written to ${args.markdown}`);
  }

  if (args.json !== null) {
    await fsp.mkdir(path.dirname(args.json), { recursive: true });
    await fsp.writeFile(args.json, `${JSON.stringify(results, null, 2)}\n`, 'utf8');
    console.log(`json written to ${args.json}`);
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = { parseArgs, table, TITLES };
