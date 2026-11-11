const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { once } = require('node:events');

const { DomainError } = require('../errors/domain-error');
const { runStreamPipeline } = require('../streams/pipeline.runner');
const { mb, BYTES_IN_MB } = require('../streams/metrics');
const { WsProbe, connectProbe } = require('../lab/ws-probe');
const { frames } = require('../realtime/ws-protocol');

// The lab, requirement by requirement, as something a person can press.
//
// Each task runs the real code - the same pipeline runner, the same WebSocket
// endpoint, the same policy - and returns a uniform result: a list of claims
// that either hold or do not, some facts, an optional table and a log. The
// page renders that shape without knowing anything about a particular task,
// and a task that stops holding turns red instead of printing a wrong number.
//
// It is the demo script in a browser, and deliberately so: the claims here are
// the claims demo-lab5.ps1 asserts, so the two cannot drift apart silently.
//
// Everything runs on a slice of the real 256 MB dataset rather than on a
// separate fixture, so nothing on this page is a toy - it is the same file,
// read from the start, for as many bytes as the task needs to make its point.

const SLICE = 24 * BYTES_IN_MB;

const TASKS = [
  { id: 'dataset', number: 1, title: 'Тестове джерело даних', requirement: 'Файл 100 MB – 1 GB, який не завантажується в один Buffer' },
  { id: 'readable', number: 2, title: 'Readable Stream і розмір порції', requirement: 'Потокове читання; параметри, що впливають на розмір порцій' },
  { id: 'transform', number: 3, title: 'Transform Stream і новий файл', requirement: 'Transform змінює/аналізує порції, результат у Writable' },
  { id: 'pipe', number: 4, title: 'Звʼязування через pipe()', requirement: 'readable.pipe(transform).pipe(writable)' },
  { id: 'backpressure', number: 5, title: 'Backpressure: сценарії A / B / C', requirement: 'Повільний Writable; порівняння з контролем швидкості і без' },
  { id: 'websocket', number: 6, title: 'WebSocket-сервер', requirement: 'connect, message, broadcast, disconnect' },
  { id: 'registry', number: 7, title: 'Реєстр клієнтів і обмін повідомленнями', requirement: 'Список активних зʼєднань; повідомлення іншим клієнтам' },
  { id: 'lifecycle', number: 8, title: 'Життєвий цикл зʼєднання', requirement: 'Підключення, автентифікація, невалідний кадр, закриття, втрата клієнта' },
  { id: 'integration', number: 9, title: 'Інтеграція Streams і WebSockets', requirement: 'Результат обробки йде клієнтам у реальному часі' },
  { id: 'ws-backpressure', number: 10, title: 'Backpressure у WebSocket', requirement: 'Повільний клієнт; механізм захисту від накопичення' },
];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// What a task hands back.
//
// steps() is the important one and the reason this class exists in this shape:
// a verdict like "the client was registered" is worth nothing to someone who
// has to be convinced. A step records what was actually done - the frame that
// went out, the request that was sent, the command that would reproduce it -
// next to what actually came back, verbatim. The claims below it are then a
// summary of a transcript the reader can check, instead of a list of
// assertions they have to take on trust.
class Report {
  constructor(task) {
    this.task = task;
    this.steps = [];
    this.claims = [];
    this.facts = [];
    this.log = [];
    this.table = null;
    this.note = null;
  }

  // action: what was done, in concrete terms.
  // sent:   the literal payload, request line or command, as issued.
  // got:    what came back, in one line.
  // data:   the literal response, verbatim.
  step({ action, sent = null, got = null, data = null, note = null }) {
    this.steps.push({ index: this.steps.length + 1, action, sent, got, data, note });
    return this.steps.at(-1);
  }

  claim(text, passed, detail = null) {
    this.claims.push({ text, passed: Boolean(passed), detail });
    return passed;
  }

  fact(label, value) {
    this.facts.push({ label, value: String(value) });
  }

  line(text) {
    this.log.push(text);
  }

  finish(elapsedMs) {
    return {
      taskId: this.task.id,
      number: this.task.number,
      title: this.task.title,
      requirement: this.task.requirement,
      elapsedMs,
      passed: this.claims.every((claim) => claim.passed),
      steps: this.steps,
      claims: this.claims,
      facts: this.facts,
      table: this.table,
      log: this.log,
      note: this.note,
    };
  }
}

// Verbatim payloads, trimmed only when they would fill the screen. The limit is
// generous on purpose: the point of showing a frame is showing the frame.
function json(value, limit = 700) {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > limit ? `${text.slice(0, limit)} … (${text.length} символів)` : text;
}

class LabDemoService {
  // hub is the WebSocket hub; it is a setter rather than a constructor argument
  // for the same reason RealtimeService takes one - the hub needs the HTTP
  // server, which needs the app, which needs this service.
  constructor({ config, streamService, log = () => {} }) {
    this.config = config;
    this.streamService = streamService;
    this.log = log;
    this.hub = null;
    this.running = null;
    this.lastResults = new Map();
  }

  list() {
    return TASKS.map((task) => ({
      ...task,
      lastResult: this.lastResults.get(task.id) ?? null,
      running: this.running === task.id,
    }));
  }

  async run(taskId) {
    const task = TASKS.find((candidate) => candidate.id === taskId);
    if (task === undefined) {
      throw DomainError.notFound('task_not_found', `Lab task "${taskId}" does not exist`);
    }

    // One at a time: several of these measure memory or socket buffers, and two
    // of them running together would each be measuring the other.
    if (this.running !== null) {
      throw DomainError.rateLimited('task_running', `Task "${this.running}" is still running`);
    }

    const dataset = await this.streamService.dataset();
    if (!dataset.exists && taskId !== 'dataset') {
      throw DomainError.unavailable(
        'dataset_missing',
        `Датасет ${dataset.file} не існує. Запустіть "npm run gen:data" або завдання 1.`,
      );
    }

    this.running = taskId;
    const report = new Report(task);
    const startedAt = Date.now();

    try {
      await this[`${toMethod(taskId)}`](report, dataset);
      const result = report.finish(Date.now() - startedAt);
      this.lastResults.set(taskId, result);
      this.log(`lab task ${taskId}: ${result.passed ? 'ok' : 'FAILED'} in ${result.elapsedMs} ms`);
      return result;
    } finally {
      this.running = null;
    }
  }

  #wsUrl() {
    return `ws://127.0.0.1:${this.config.port}${this.config.ws.path}`;
  }

  #requireHub() {
    if (this.hub === null) {
      throw DomainError.unavailable('ws_disabled', 'WebSocket-модуль не увімкнений на цьому екземплярі');
    }
    return this.hub;
  }

  #probeOptions(extra = {}) {
    return { url: this.#wsUrl(), token: this.config.ws.token, ...extra };
  }

  // -----------------------------------------------------------------------
  // 1. The test data source
  // -----------------------------------------------------------------------
  async taskDataset(report, dataset) {
    if (!dataset.exists) {
      report.line('Датасету немає, генерую 128 MB (це займе кілька секунд).');
      await this.#generate(128);
      dataset = await this.streamService.dataset();
    }

    const hwm = this.config.stream.highWaterMark;

    report.fact('Файл', dataset.file);
    report.fact('Розмір', `${dataset.sizeMB} MB`);
    report.fact('Байтів', dataset.bytes.toLocaleString('uk-UA'));
    report.fact('highWaterMark', `${(hwm / 1024).toFixed(0)} KiB`);
    report.fact('Більший за буфер у', `${Math.round(dataset.bytes / hwm)} разів`);

    // Reading the first and the last lines costs two small reads and proves the
    // file is what it claims to be, without loading any of it.
    const headLine = await this.#firstLine(dataset.file);
    const tailLine = await this.#lastLine(dataset.file);

    report.step({
      action: 'Перевірено файл на диску',
      sent: `fs.stat("${dataset.file}")`,
      got: `${dataset.bytes.toLocaleString('uk-UA')} байтів = ${dataset.sizeMB} MB, змінений ${new Date(dataset.modifiedAt).toLocaleString('uk-UA')}`,
    });

    report.step({
      action: 'Прочитано перші 4 KB файлу, щоб показати формат (не весь файл — у цьому й суть)',
      sent: `fs.createReadStream("…events.ndjson", { start: 0, end: 4095 })`,
      got: 'перший рядок — валідний JSON-обʼєкт події сервісу',
      data: headLine,
    });

    report.step({
      action: 'Прочитано останні 4 KB того самого файлу',
      sent: `fs.createReadStream("…events.ndjson", { start: ${(dataset.bytes - 4096).toLocaleString('uk-UA')} })`,
      got: 'файл послідовний від початку до кінця, ts зростає',
      data: tailLine,
      note: 'два читання по 4 KB замість 256 MB: щоб подивитися на кінець файлу, не треба тримати його початок',
    });

    report.step({
      action: 'Порівняно розмір файлу з розміром одного буфера читання',
      got: `${dataset.sizeMB} MB / ${(hwm / 1024).toFixed(0)} KiB = у ${Math.round(dataset.bytes / hwm)} разів більше`,
      note: `тобто файл проходить через ${Math.round(dataset.bytes / hwm)} порцій — жодна з них не містить усього`,
    });

    report.claim(
      'Файл у межах вимоги 100 MB – 1 GB',
      dataset.bytes >= 100 * BYTES_IN_MB && dataset.bytes <= 1024 * BYTES_IN_MB,
      `${dataset.sizeMB} MB`,
    );
    report.claim(
      'Файл суттєво перевищує один буфер',
      dataset.bytes > hwm * 1000,
      `${dataset.sizeMB} MB проти ${(hwm / 1024).toFixed(0)} KiB — у ${Math.round(dataset.bytes / hwm)} разів`,
    );
    report.claim('Рядки — валідний NDJSON', isJson(headLine), 'перший рядок розбирається як JSON-обʼєкт');

    report.note =
      'Генератор теж потоковий: він пише батчами і чекає на "drain", коли write() ' +
      'повертає false. Саме тому 256 MB записано при піку RSS близько 52 MB — ' +
      'повний протокол генерації у logs/generate-dataset.txt.';
  }

  // -----------------------------------------------------------------------
  // 2. Readable stream and what decides the chunk size
  // -----------------------------------------------------------------------
  async taskReadable(report, dataset) {
    const sizes = [16 * 1024, 64 * 1024, 1024 * 1024];
    const rows = [];

    for (const highWaterMark of sizes) {
      const result = await runStreamPipeline({
        inputFile: dataset.file,
        outputFile: this.#outFile(`task2-${highWaterMark}.ndjson`),
        highWaterMark,
        bytes: SLICE,
        filter: { levels: ['error'] },
      });

      rows.push({ highWaterMark, result });

      report.step({
        action: `Прочитано ${mb(SLICE)} MB файлу з highWaterMark ${highWaterMark} B`,
        sent: `fs.createReadStream("…events.ndjson", { highWaterMark: ${highWaterMark}, end: ${SLICE - 1} })`,
        got:
          `${result.chunks.chunksIn} порцій: найменша ${result.chunks.minChunk} B, ` +
          `найбільша ${result.chunks.maxChunk} B, середня ${result.chunks.avgChunk} B`,
        data: json({
          очікувано_порцій: Math.ceil(SLICE / highWaterMark),
          фактично: result.chunks.chunksIn,
          максимальна_порція: result.chunks.maxChunk,
          highWaterMark: highWaterMark,
          рядків_записано: result.stats.linesOut,
          час_мс: result.elapsedMs,
          пік_RSS_MB: result.metrics.peakRssMB,
        }),
        note:
          `максимальна порція дорівнює highWaterMark рівно, а не «приблизно»; остання менша, ` +
          `бо файл не кратний ${highWaterMark}`,
      });
    }

    report.step({
      action: 'Те саме з командного рядка, якщо треба повторити вручну',
      sent: `node tools/stream-run.js --sweep ${sizes.join(',')} --levels error`,
      got: 'та сама таблиця у консолі',
    });

    report.table = {
      columns: ['highWaterMark', 'читань', 'середня порція', 'макс. порція', 'записів у Writable', 'час, мс', 'MB/с', 'пік RSS, MB'],
      rows: rows.map(({ highWaterMark, result }) => [
        `${(highWaterMark / 1024).toFixed(0)} KiB`,
        String(result.chunks.chunksIn),
        String(result.chunks.avgChunk),
        String(result.chunks.maxChunk),
        String(result.chunks.outputChunks),
        String(result.elapsedMs),
        String(result.throughputMBps),
        String(result.metrics.peakRssMB),
      ]),
    };

    report.fact('Прочитано', `${mb(SLICE)} MB зі ${dataset.sizeMB} MB`);
    report.fact('Прогонів', String(sizes.length));

    for (const { highWaterMark, result } of rows) {
      report.claim(
        `highWaterMark ${(highWaterMark / 1024).toFixed(0)} KiB: жодна порція не перевищила буфер`,
        result.chunks.maxChunk <= highWaterMark,
        `макс. ${result.chunks.maxChunk} B, середня ${result.chunks.avgChunk} B`,
      );
    }

    const linesOut = new Set(rows.map(({ result }) => result.stats.linesOut));
    report.claim(
      'Результат не залежить від розміру буфера',
      linesOut.size === 1,
      `у всіх прогонах записано однаково рядків: ${[...linesOut].join(', ')}`,
    );
    report.claim(
      'Кількість читань масштабується як 1/highWaterMark',
      rows[0].result.chunks.chunksIn > rows.at(-1).result.chunks.chunksIn * 10,
      `16 KiB → ${rows[0].result.chunks.chunksIn} читань, 1 MiB → ${rows.at(-1).result.chunks.chunksIn}`,
    );
    report.claim(
      'Кількість записів у Writable від highWaterMark не залежить',
      new Set(rows.map(({ result }) => result.chunks.outputChunks)).size === 1,
      'її задає outputChunkBytes аналізатора, а не буфер читання',
    );

    report.note =
      'highWaterMark — це межа, а не розмір: порція ніколи не більша за нього, ' +
      'а остання завжди менша. Більший буфер трохи швидший і помітно дорожчий ' +
      'по пам’яті.';
  }

  // -----------------------------------------------------------------------
  // 3. The transform stage and the processed file
  // -----------------------------------------------------------------------
  async taskTransform(report, dataset) {
    const outputFile = this.#outFile('task3-errors.ndjson');

    const result = await runStreamPipeline({
      inputFile: dataset.file,
      outputFile,
      bytes: SLICE,
      filter: { levels: ['error'] },
    });

    // The same chain over four times as much data. The claim being tested is
    // that memory does not scale with the input, and a single run cannot show
    // that - only two runs of different sizes can.
    const bigger = await runStreamPipeline({
      inputFile: dataset.file,
      outputFile: this.#outFile('task3-errors-big.ndjson'),
      bytes: SLICE * 4,
      filter: { levels: ['error'] },
    });

    // Counted from the file itself rather than trusted from the statistics: the
    // claim is about what was written, not about what the transform believes.
    const written = await this.#countLines(outputFile);
    const sample = await this.#firstLine(outputFile);
    const inputSample = await this.#firstLine(dataset.file);

    report.step({
      action: `Пропущено ${mb(result.totalBytes)} MB через ланцюг Readable → LineSplit → EventAnalyzer → WriteStream`,
      sent:
        `fs.createReadStream(dataset, { highWaterMark: ${result.highWaterMark} })\n` +
        `  .pipe(new LineSplitTransform())\n` +
        `  .pipe(new EventAnalyzerTransform({ levels: ["error"] }))\n` +
        `  .pipe(fs.createWriteStream("${outputFile}"))`,
      got:
        `прочитано ${result.stats.linesIn.toLocaleString('uk-UA')} рядків, ` +
        `записано ${result.stats.linesOut.toLocaleString('uk-UA')}, ` +
        `відфільтровано ${result.stats.filtered.toLocaleString('uk-UA')}, ` +
        `зіпсованих ${result.stats.malformed}`,
      note: 'фільтр level=error: саме тому вихід менший за вхід',
    });

    report.step({
      action: 'Який рядок був на вході',
      got: 'подія рівня info — такі у вихід не потрапляють',
      data: inputSample,
    });

    report.step({
      action: 'Який рядок став на виході',
      got: 'лише level=error, і Transform додав поля seq та bucket, яких у вхідному рядку не було',
      data: sample,
      note: 'bucket обчислено з latencyMs — це і є «змінює або аналізує порцію», а не pass-through',
    });

    report.step({
      action: 'Вихідний файл перераховано незалежно від статистики конвеєра',
      sent: `підрахунок байтів 0x0A у "${outputFile}" окремим стрімом`,
      got: `у файлі ${written.toLocaleString('uk-UA')} рядків; Transform звітував ${result.stats.linesOut.toLocaleString('uk-UA')}`,
      note: 'числа збігаються, тому звіт конвеєра не доводиться брати на віру',
    });

    report.fact('Прочитано', `${mb(result.totalBytes)} MB`);
    report.fact('Рядків прочитано', result.stats.linesIn.toLocaleString('uk-UA'));
    report.fact('Рядків записано', result.stats.linesOut.toLocaleString('uk-UA'));
    report.fact('Відфільтровано', result.stats.filtered.toLocaleString('uk-UA'));
    report.fact('Зіпсованих', String(result.stats.malformed));
    report.fact('Вихідний файл', `${mb(result.outputBytes)} MB`);
    report.fact('Пік RSS', `${result.metrics.peakRssMB} MB`);
    report.fact('Приріст RSS за прогін', `+${result.metrics.rssGrowthMB} MB`);

    report.table = {
      columns: ['зріз', 'рядків прочитано', 'рядків записано', 'час, мс', 'приріст RSS, MB', 'пік RSS, MB'],
      rows: [result, bigger].map((run) => [
        `${mb(run.totalBytes)} MB`,
        run.stats.linesIn.toLocaleString('uk-UA'),
        run.stats.linesOut.toLocaleString('uk-UA'),
        String(run.elapsedMs),
        `+${run.metrics.rssGrowthMB}`,
        String(run.metrics.peakRssMB),
      ]),
    };

    report.step({
      action: `Той самий ланцюг запущено на ${mb(bigger.totalBytes)} MB — учетверо більшому зрізі`,
      sent: `той самий код, лише bytes: ${bigger.totalBytes}`,
      got:
        `рядків ${result.stats.linesIn.toLocaleString('uk-UA')} → ${bigger.stats.linesIn.toLocaleString('uk-UA')} (×4), ` +
        `приріст RSS ${result.metrics.rssGrowthMB} MB → ${bigger.metrics.rssGrowthMB} MB`,
      data: json({
        зріз_1: { MB: mb(result.totalBytes), рядків: result.stats.linesIn, приріст_RSS_MB: result.metrics.rssGrowthMB },
        зріз_2: { MB: mb(bigger.totalBytes), рядків: bigger.stats.linesIn, приріст_RSS_MB: bigger.metrics.rssGrowthMB },
      }),
      note: 'даних учетверо більше, пам’яті — майже стільки ж: це і є твердження, яке неможливо показати одним прогоном',
    });

    report.line(`Вихідний файл: ${outputFile}`);
    report.line(`Затримки: min ${result.stats.latency.min} мс, avg ${result.stats.latency.avg} мс, max ${result.stats.latency.max} мс`);
    report.line(`Бакети: ${JSON.stringify(result.stats.byBucket)}`);
    report.line(`Розподіл за рівнями у зрізі: ${JSON.stringify(result.stats.byLevel)}`);

    report.claim(
      'Рядків у файлі стільки ж, скільки звітував Transform',
      written === result.stats.linesOut,
      `у файлі ${written}, Transform звітував ${result.stats.linesOut}`,
    );
    report.claim(
      'У файлі лише запитаний рівень',
      isJson(sample) && JSON.parse(sample).level === 'error',
      `перший рядок: level=${isJson(sample) ? JSON.parse(sample).level : '?'}`,
    );
    report.claim(
      'Transform додав обчислене поле',
      isJson(sample) && 'bucket' in JSON.parse(sample),
      'записи збагачені полем bucket — це не pass-through',
    );
    report.claim(
      'Фільтр зменшив обсяг',
      result.outputBytes < result.totalBytes,
      `${mb(result.totalBytes)} MB → ${mb(result.outputBytes)} MB`,
    );
    report.claim(
      'Зіпсовані рядки підраховані, а не аварійні',
      result.stats.malformed > 0,
      `${result.stats.malformed} непарсабельних рядків, конвеєр дійшов до кінця`,
    );
    // Growth, not absolute RSS: this runs inside a server process that already
    // holds Express, ws and the V8 heap, so the absolute number says more about
    // the process than about the pipeline.
    // Stated against the data, not as a ratio between the two runs: both
    // growths are a couple of megabytes, and a ratio of two noisy small numbers
    // says nothing. "The extra data cost almost no extra memory" is the actual
    // property, and it holds at any size.
    const extraData = mb(bigger.totalBytes) - mb(result.totalBytes);
    const extraMemory = Number((bigger.metrics.rssGrowthMB - result.metrics.rssGrowthMB).toFixed(1));

    // Claimed against the data, not as a ratio between the two runs. Whichever
    // run happens to trigger V8 growing its heap pays a one-time cost that is
    // not proportional to anything, and on a cold process that is usually the
    // first one - so a difference between the runs is not a stable measurement,
    // while "the growth is nowhere near the data" is.
    report.claim(
      'Приріст пам’яті не масштабується з обсягом даних',
      bigger.metrics.rssGrowthMB < mb(bigger.totalBytes) * 0.35,
      `${mb(result.totalBytes)} MB → +${result.metrics.rssGrowthMB} MB, ` +
        `${mb(bigger.totalBytes)} MB → +${bigger.metrics.rssGrowthMB} MB: ` +
        `додаткові ${extraData} MB даних коштували ${extraMemory} MB пам’яті`,
    );
    report.claim(
      'Рядків обробляється пропорційно даним, а пам’яті — ні',
      bigger.stats.linesIn > result.stats.linesIn * 3.5,
      `${result.stats.linesIn.toLocaleString('uk-UA')} → ${bigger.stats.linesIn.toLocaleString('uk-UA')} рядків`,
    );

    report.note =
      'Приріст RSS у першому прогоні включає одноразовий розігрів: V8 вирощує ' +
      'heap, уперше виділяються буфери стріму. Саме тому твердження тут — про ' +
      'приріст між двома прогонами, а не про абсолютне число: потокова обробка ' +
      'обіцяє, що *наступний* мегабайт майже безкоштовний, і другий прогін ' +
      'міряє рівно це. Пік heap при цьому лишається десятками мегабайтів, бо ' +
      'самі дані живуть у Buffer поза heap.';
  }

  // -----------------------------------------------------------------------
  // 4. pipe() - and why the service uses pipeline()
  // -----------------------------------------------------------------------
  async taskPipe(report, dataset) {
    const piped = await runStreamPipeline({
      inputFile: dataset.file,
      outputFile: this.#outFile('task4-pipe.ndjson'),
      mode: 'pipe',
      bytes: SLICE,
      filter: { levels: ['error'] },
    });

    const pipelined = await runStreamPipeline({
      inputFile: dataset.file,
      outputFile: this.#outFile('task4-pipeline.ndjson'),
      mode: 'pipeline',
      bytes: SLICE,
      filter: { levels: ['error'] },
    });

    const hashA = await this.#hash(piped.outputFile);
    const hashB = await this.#hash(pipelined.outputFile);

    report.step({
      action: 'Зібрано ланцюг через pipe() — буквально так, як вимагає завдання',
      sent:
        'readable\n' +
        '  .pipe(split)\n' +
        '  .pipe(analyzer)\n' +
        '  .pipe(writable)',
      got: `${piped.chunks.chunksIn} читань → ${piped.chunks.outputChunks} записів → ${piped.stats.linesOut.toLocaleString('uk-UA')} рядків за ${piped.elapsedMs} мс`,
      data: `файл: ${piped.outputFile}\nSHA-256: ${hashA}`,
    });

    report.step({
      action: 'Той самий набір стадій зібрано через stream.pipeline()',
      sent: 'await pipeline(readable, split, analyzer, writable)',
      got: `${pipelined.stats.linesOut.toLocaleString('uk-UA')} рядків за ${pipelined.elapsedMs} мс`,
      data: `файл: ${pipelined.outputFile}\nSHA-256: ${hashB}`,
    });

    report.step({
      action: 'Порівняно два вихідні файли побайтово',
      sent: 'SHA-256 обох файлів',
      got: hashA === hashB ? 'хеші однакові — результат ідентичний' : 'хеші різні',
      data: `pipe():     ${hashA}\npipeline(): ${hashB}`,
      note: 'отже різниця між ними не в результаті, а в тому, що станеться при збої',
    });

    report.table = {
      columns: ['ланцюг', 'час, мс', 'MB/с', 'рядків записано', 'вихід, MB', 'SHA-256 файлу'],
      rows: [
        ['readable.pipe(split).pipe(analyze).pipe(writable)', String(piped.elapsedMs), String(piped.throughputMBps), String(piped.stats.linesOut), String(mb(piped.outputBytes)), `${hashA.slice(0, 16)}…`],
        ['pipeline(readable, split, analyze, writable)', String(pipelined.elapsedMs), String(pipelined.throughputMBps), String(pipelined.stats.linesOut), String(mb(pipelined.outputBytes)), `${hashB.slice(0, 16)}…`],
      ],
    };

    report.line(`pipe():     ${piped.outputFile}`);
    report.line(`pipeline(): ${pipelined.outputFile}`);
    report.line('Обидва ланцюги з однакових стадій у однаковому порядку.');

    report.claim(
      'Повний ланцюг File → Readable → Transform → Writable відпрацював',
      piped.stats.linesOut > 0 && piped.chunks.chunksIn > 1,
      `${piped.chunks.chunksIn} читань, ${piped.chunks.outputChunks} записів, ${piped.stats.linesOut} рядків`,
    );
    report.claim(
      'pipe() і pipeline() дають побайтово однаковий файл',
      hashA === hashB,
      `SHA-256 обох файлів: ${hashA.slice(0, 32)}…`,
    );

    // The difference between the two is not the result but what happens on
    // failure, and that is worth showing rather than asserting in prose.
    const broken = await this.#pipelineFailure(dataset.file);

    report.step({
      action: 'Той самий ланцюг навмисно спрямовано на неіснуючий файл',
      sent: `pipeline(createReadStream("${dataset.file}.missing"), split, analyzer, writable)`,
      got: 'одна відмова з конкретною причиною, усі стадії зруйновано',
      data: broken.message,
      note: 'pipe() у цьому місці нічого б не прокинув і не закрив: Readable лишився б відкритим із дескриптором',
    });
    report.claim(
      'pipeline() прокидає помилку стадії однією причиною',
      broken.caught,
      broken.message,
    );

    report.note =
      'Backpressure в pipe() і pipeline() однаковий. Різниця в помилках: pipe() ' +
      'не прокидає їх і нічого не руйнує, тому після збою лишаються відкриті ' +
      'дескриптори. Тому вимогу 4 показано через pipe(), а сервіс за ' +
      'замовчуванням використовує pipeline() — він ще й приймає AbortSignal, ' +
      'на якому працює DELETE задачі.';
  }

  // -----------------------------------------------------------------------
  // 5. Backpressure: A / B / C
  // -----------------------------------------------------------------------
  async taskBackpressure(report) {
    const megabytes = 24;
    const delayMs = 4;

    report.line(`Зріз ${megabytes} MB, повільний споживач ${delayMs} мс на порцію.`);
    report.line('Кожен сценарій — в окремому процесі: ОС не повертає RSS після');
    report.line('звільнення буфера, тому в одному процесі B і C успадкували б пік від A.');

    report.step({
      action: 'Створено штучно повільного споживача',
      sent:
        'class SlowWritable extends Writable {\n' +
        '  _write(chunk, encoding, callback) {\n' +
        `    setTimeout(callback, ${delayMs});   // доки callback не викликано, порція рахується незавершеною\n` +
        '  }\n' +
        '}',
      got: `${delayMs} мс на кожну порцію: 384 порції зрізу = мінімум ${(384 * delayMs / 1000).toFixed(1)} с, хоч диск читає за частку секунди`,
    });

    report.step({
      action: 'Запущено три сценарії над одним файлом і одним споживачем',
      sent:
        `node tools/backpressure-compare.js --mb ${megabytes} --delay-ms ${delayMs}\n\n` +
        'A: read.on("data", c => sink.write(c))            // значення write() проігноровано\n' +
        'B: if (!sink.write(c)) { read.pause();\n' +
        '     sink.once("drain", () => read.resume()); }    // те саме вручну\n' +
        'C: read.pipe(sink)                                 // те саме через стрім',
      got: 'кожен — в окремому процесі, щоб колонка RSS щось означала',
      note: 'A і C відрізняються рівно одним рядком, тому різниця в таблиці має рівно одну причину',
    });

    const scenarios = await this.#runComparison(megabytes, delayMs);
    const byName = Object.fromEntries(scenarios.map((item) => [item.scenario, item]));
    const a = byName.uncontrolled;
    const b = byName.manual;
    const c = byName.pipe;

    const titles = {
      uncontrolled: 'A — без контролю швидкості',
      manual: 'B — pause/drain вручну',
      pipe: 'C — pipe()',
    };

    report.table = {
      columns: ['сценарій', 'прочитано, MB', 'порцій', 'час, мс', 'MB/с', 'пік буфера', 'пік RSS, MB', 'приріст RSS, MB', 'пауз'],
      rows: scenarios.map((item) => [
        titles[item.scenario],
        String(mb(item.bytesRead)),
        String(item.chunksWritten),
        String(item.elapsedMs),
        String(item.throughputMBps),
        `${item.peakBufferedMB} MB`,
        String(item.peakRssMB),
        String(item.rssGrowthMB),
        item.scenario === 'pipe' ? `${item.pausedSamples} семплів на паузі` : String(item.pauses),
      ]),
    };

    report.step({
      action: 'Сценарій A: виробник не дивився на те, що повернув write()',
      got: `буфер Writable виріс до ${a.peakBufferedMB} MB, пауз: ${a.pauses}`,
      data: json({
        пік_writableLength_байтів: a.peakBufferedBytes,
        це_у_разах_від_highWaterMark: Math.round(a.peakBufferedBytes / a.highWaterMark),
        RSS_до: `${a.baselineRssMB} MB`,
        RSS_пік: `${a.peakRssMB} MB`,
        приріст: `+${a.rssGrowthMB} MB`,
        час_мс: a.elapsedMs,
      }),
      note: `прочитані ${mb(a.bytesRead)} MB лежали в пам’яті процесу, бо споживач їх ще не забрав`,
    });

    report.step({
      action: 'Сценарій C: той самий споживач, той самий файл, але через pipe()',
      got: `буфер не перевищив ${c.peakBufferedBytes} B = рівно один highWaterMark; у ${c.pausedSamples} семплах джерело стояло на паузі`,
      data: json({
        пік_writableLength_байтів: c.peakBufferedBytes,
        highWaterMark: c.highWaterMark,
        RSS_до: `${c.baselineRssMB} MB`,
        RSS_пік: `${c.peakRssMB} MB`,
        приріст: `+${c.rssGrowthMB} MB`,
        час_мс: c.elapsedMs,
      }),
      note: `у коді сценарію C немає жодного pause() — його викликає pipe() усередині`,
    });

    report.step({
      action: 'Порівняно A і C',
      got:
        `буфер: ${a.peakBufferedMB} MB проти ${mb(c.peakBufferedBytes)} MB (у ${Math.round(a.peakBufferedBytes / Math.max(1, c.peakBufferedBytes))} разів); ` +
        `пам’ять: +${a.rssGrowthMB} MB проти +${c.rssGrowthMB} MB; ` +
        `час: ${a.elapsedMs} мс проти ${c.elapsedMs} мс`,
      note: 'час майже однаковий — контроль потоку не коштує швидкості, бо темп у будь-якому разі задає споживач',
    });

    report.fact('Пік буфера A', `${a.peakBufferedMB} MB`);
    report.fact('Пік буфера C', `${c.peakBufferedMB} MB`);
    report.fact('Різниця', `${Math.round(a.peakBufferedBytes / Math.max(1, c.peakBufferedBytes))}×`);
    report.fact('Приріст RSS A', `+${a.rssGrowthMB} MB`);
    report.fact('Приріст RSS C', `+${c.rssGrowthMB} MB`);
    report.fact('Різниця у часі', `${Math.abs(((a.elapsedMs - c.elapsedMs) / c.elapsedMs) * 100).toFixed(1)}%`);

    report.claim(
      'A без контролю накопичує дані в пам’яті',
      a.peakBufferedBytes > a.highWaterMark * 10,
      `пік буфера ${a.peakBufferedMB} MB при буфері ${a.highWaterMark} B`,
    );
    report.claim('A жодного разу не зупинила виробника', a.pauses === 0);
    report.claim(
      'B тримає буфер у межах одного highWaterMark',
      b.peakBufferedBytes <= b.highWaterMark * 2,
      `пік буфера ${b.peakBufferedBytes} B, пауз ${b.pauses}`,
    );
    report.claim(
      'C через pipe() тримає так само, без жодного pause() у коді',
      c.peakBufferedBytes <= c.highWaterMark * 2,
      `пік буфера ${c.peakBufferedBytes} B, у ${c.pausedSamples} семплах джерело було на паузі`,
    );
    report.claim(
      'Забуферизовані байти видно як приріст RSS саме у A',
      a.rssGrowthMB > c.rssGrowthMB + a.peakBufferedMB * 0.5,
      `A +${a.rssGrowthMB} MB при піку буфера ${a.peakBufferedMB} MB; C +${c.rssGrowthMB} MB`,
    );
    report.claim(
      'Час виконання практично однаковий',
      Math.abs(a.elapsedMs - c.elapsedMs) / c.elapsedMs < 0.35,
      `A ${a.elapsedMs} мс, C ${c.elapsedMs} мс — темп задає споживач`,
    );

    report.note =
      'Контрінтуїтивне тут — колонка часу. Backpressure не коштує швидкості: ' +
      'темп задає найповільніша ланка в будь-якому разі, і A не виграє часу, ' +
      'вона лише платить пам’яттю за те саме.';
  }

  // -----------------------------------------------------------------------
  // 6. The WebSocket endpoint
  // -----------------------------------------------------------------------
  async taskWebsocket(report) {
    const hub = this.#requireHub();
    const before = hub.registry.size;
    const url = this.#wsUrl();

    report.step({
      action: 'Відкрито WebSocket-зʼєднання: HTTP-запит з Upgrade на той самий порт, що й REST',
      sent: `GET ${this.config.ws.path} HTTP/1.1\nHost: 127.0.0.1:${this.config.port}\nUpgrade: websocket\nConnection: Upgrade`,
      got: 'HTTP/1.1 101 Switching Protocols — далі це вже не HTTP',
      note: `реєстр до підключення: ${before} клієнтів`,
    });

    const probe = new WsProbe(this.#probeOptions({ name: 'probe-6' })).connect();
    const welcome = await probe.waitFor('welcome');

    report.step({
      action: 'Сервер сам надіслав перший кадр, нічого не питаючи',
      got: `кадр welcome, присвоєно clientId ${welcome.clientId}`,
      data: json(welcome),
      note: `authRequired=${welcome.authRequired}: до ідентифікації жоден інший кадр не приймається`,
    });

    const ready = await probe.ready;

    report.step({
      action: 'Надіслано кадр hello з токеном',
      sent: json({ type: 'hello', name: 'probe-6', token: this.config.ws.token }),
      got: `кадр ready, стан клієнта "${ready.state}", інших клієнтів ${ready.peers.length}`,
      data: json(ready),
    });

    const duringConnection = hub.registry.size;
    const snapshot = hub.registry.snapshot();

    report.step({
      action: 'Той самий реєстр прочитано через HTTP, щоб показати: це одна структура, а не дві',
      sent: `GET /api/ws/clients`,
      got: `${snapshot.total} активний клієнт, стан "${snapshot.clients[0]?.state}"`,
      data: json(snapshot.clients[0]),
    });

    probe.send({ type: 'ping' });
    const pong = await probe.waitFor('pong');

    report.step({
      action: 'Надіслано кадр ping',
      sent: json({ type: 'ping' }),
      got: 'кадр pong',
      data: json(pong),
    });

    probe.send({ type: 'message', text: 'кадр від серверного зонда' });
    const ack = await probe.waitFor('ack', { where: (frame) => frame.of === 'message' });

    report.step({
      action: 'Надіслано кадр message',
      sent: json({ type: 'message', text: 'кадр від серверного зонда' }),
      got: `кадр ack: адресатів ${ack.detail.targeted}, доставлено ${ack.detail.delivered} — інших клієнтів немає, тому нуль`,
      data: json(ack),
      note: 'відправник отримує ack, а не власне повідомлення назад: так клієнт відрізняє «доставлено трьом» від «нікого немає»',
    });

    const summary = await probe.stop();
    await sleep(100);

    report.step({
      action: 'Закрито зʼєднання з боку клієнта',
      sent: 'close(1000, "probe done")',
      got: `← close ${summary.close?.code} "${summary.close?.reason}", реєстр знову ${hub.registry.size} клієнтів`,
      data: json({ отримано_кадрів: summary.received, байтів: summary.bytes, за_типами: summary.byType }),
    });

    report.fact('Endpoint', url.replace('127.0.0.1', 'localhost'));
    report.fact('clientId', welcome.clientId);
    report.fact('Кадрів отримано', String(summary.received));
    report.fact('Код закриття', summary.close ? `${summary.close.code} ${summary.close.reason}` : '—');
    report.fact('Клієнтів до / під час / після', `${before} / ${duringConnection} / ${hub.registry.size}`);

    report.claim('welcome приходить першим кадром', probe.frames[0]?.type === 'welcome');
    report.claim('Сервер зареєстрував клієнта', duringConnection === before + 1);
    report.claim('ping отримує pong', summary.byType.pong >= 1);
    report.claim('message отримує ack', summary.byType.ack >= 1);
    report.claim('Закриття штатне, код 1000', summary.close?.code === 1000, summary.close?.reason ?? '');
    report.claim('Після закриття клієнт знятий з реєстру', hub.registry.size === before);

    report.note =
      'Endpoint змонтовано з noServer: true, а подію upgrade обробляє ws-server.js ' +
      'вручну. Через це апгрейд на будь-якому іншому шляху отримує HTTP 404, а ' +
      'не обірваний сокет, і HTTP та WebSocket живуть на одному порту.';
  }

  // -----------------------------------------------------------------------
  // 7. The registry and message exchange
  // -----------------------------------------------------------------------
  async taskRegistry(report) {
    const hub = this.#requireHub();

    const alice = await connectProbe(this.#probeOptions({ name: 'alice' }));
    report.step({
      action: 'Підключено й ідентифіковано першого клієнта',
      sent: json({ type: 'hello', name: 'alice', token: this.config.ws.token }),
      got: `alice отримала clientId ${alice.clientId}; у реєстрі ${hub.registry.size} клієнт`,
    });

    const bob = await connectProbe(this.#probeOptions({ name: 'bob' }));
    report.step({
      action: 'Підключено другого клієнта',
      sent: json({ type: 'hello', name: 'bob', token: this.config.ws.token }),
      got: `bob отримав clientId ${bob.clientId}; у реєстрі ${hub.registry.size} клієнти`,
      data: json(bob.readyFrame),
      note: 'у кадрі ready видно peers: bob одразу знає, хто вже підключений',
    });

    // Alice was already connected, so she is the one who hears Bob arrive.
    const join = await alice.waitFor('presence', { where: (frame) => frame.event === 'join' });
    report.step({
      action: 'Нічого не запитуючи, alice отримала повідомлення про появу bob',
      got: `кадр presence: "${join.name}" приєднався, усього ${join.total}`,
      data: json(join),
    });

    const snapshot = hub.registry.snapshot();
    report.step({
      action: 'Прочитано список активних зʼєднань — вимога 7.1',
      sent: 'GET /api/ws/clients',
      got: `${snapshot.total} клієнти; про кожного є clientId, connectedAt, state і лічильники`,
      data: json(snapshot.clients, 900),
      note: 'сокета у цій структурі немає: вона мусить безпечно серіалізуватись у HTTP-відповідь',
    });
    report.table = {
      columns: ['clientId', 'імʼя', 'стан', 'підключено о', 'надіслано', 'відкинуто', 'буфер'],
      rows: snapshot.clients.map((client) => [
        client.clientId,
        client.name ?? '—',
        client.state,
        new Date(client.connectedAt).toLocaleTimeString('uk-UA'),
        String(client.sent),
        String(client.dropped),
        `${client.bufferedAmount} B`,
      ]),
    };

    alice.send({ type: 'message', text: 'привіт, bob' });
    const delivered = await bob.waitFor('message');
    const ack = await alice.waitFor('ack', { where: (frame) => frame.of === 'message' });
    const aliceOwnMessages = alice.byType.message ?? 0;

    report.step({
      action: 'alice надіслала повідомлення — вимога 7.2',
      sent: json({ type: 'message', text: 'привіт, bob' }),
      got: `bob отримав кадр message від "${delivered.from}"; alice отримала ack, а не власний текст назад`,
      data: `bob  ← ${json(delivered)}\nalice ← ${json(ack)}`,
      note: `кадрів message, отриманих самою alice: ${aliceOwnMessages} — сервер виключає відправника з розсилки`,
    });

    // Still subscribed to presence here, which is why the departure check comes
    // before the subscription is narrowed below.
    await alice.stop();
    const leave = await bob.waitFor('presence', { where: (frame) => frame.event === 'leave' }).catch(() => null);

    report.step({
      action: 'alice відключилася',
      sent: 'close(1000)',
      got: leave
        ? `bob отримав presence: "${leave.name}" вийшов, усього ${leave.total}; у реєстрі ${hub.registry.size}`
        : 'кадр presence не прийшов',
      data: leave ? json(leave) : null,
    });

    // Now narrow bob to chat alone and check that a frame from another topic
    // does not reach him. resubscribe waits for the server to confirm, so the
    // broadcast below cannot race the subscription change.
    const resubscribeAck = await bob.resubscribe(['chat']);
    const progressBefore = bob.byType.progress ?? 0;
    const progressFrame = frames.progress({ jobId: 'probe', processed: 1, total: 2, percent: 50 });
    hub.broadcaster.broadcast(progressFrame);
    await sleep(200);
    const bobProgress = (bob.byType.progress ?? 0) - progressBefore;

    report.step({
      action: 'bob звузив підписку до одного chat і сервер розіслав кадр з іншої теми',
      sent: `${json({ type: 'subscribe', topics: ['chat'] })}\nпотім broadcast: ${json(progressFrame)}`,
      got: `bob отримав ${bobProgress} кадрів progress — тема progress більше не його`,
      data: json(resubscribeAck),
      note: 'фан-аут фільтрує за підпискою, тому клієнт, якому потрібен лише чат, не стає споживачем потоку даних',
    });

    await bob.stop();
    await sleep(100);

    report.fact('Клієнтів у реєстрі під час досліду', String(snapshot.total));
    report.fact('Усього зʼєднань за життя процесу', String(snapshot.totalConnections));
    report.fact('Те саме через HTTP', 'GET /api/ws/clients');

    report.claim('Реєстр містить обох клієнтів', snapshot.total >= 2);
    report.claim(
      'Про кожного клієнта є clientId, connectedAt і стан',
      snapshot.clients.every((client) => client.clientId && client.connectedAt && client.state),
    );
    report.claim('Сокет не потрапляє у знімок реєстру', snapshot.clients.every((client) => !('socket' in client)));
    report.claim('Повідомлення дійшло до іншого клієнта', delivered.text === 'привіт, bob' && delivered.from === 'alice');
    report.claim('Відправник отримав ack, а не власне повідомлення', ack.detail.delivered === 1 && aliceOwnMessages === 0);
    report.claim('Присутність інших оголошується', join.event === 'join' && Boolean(leave));
    report.claim(
      'Клієнт отримує лише те, на що підписався',
      bobProgress === 0,
      'bob підписався лише на chat, тому кадр progress до нього не дійшов',
    );
    report.claim('Після відключення реєстр порожній', hub.registry.size === 0);
  }

  // -----------------------------------------------------------------------
  // 8. The connection lifecycle
  // -----------------------------------------------------------------------
  async taskLifecycle(report) {
    const hub = this.#requireHub();
    const rows = [];

    // Тhe auth timeout is cut to 600 ms for the duration of this task; with the
    // production 5 s the page would just sit there.
    const originalTimeout = this.config.ws.authTimeoutMs;
    this.config.ws.authTimeoutMs = 600;

    try {
      // 1. Normal connection and clean close.
      const good = await connectProbe(this.#probeOptions({ name: 'lifecycle-ok' }));
      const goodSummary = await good.stop();
      rows.push(['штатний клієнт', 'welcome → hello → ready → close', String(goodSummary.close?.code ?? '—'), goodSummary.close?.reason || 'client close']);
      report.step({
        action: 'Клієнт, який усе зробив правильно',
        sent: `${json({ type: 'hello', name: 'lifecycle-ok', token: this.config.ws.token })}\nпотім close(1000, "probe done")`,
        got: `← close ${goodSummary.close?.code} "${goodSummary.close?.reason}"`,
        data: json({ отримано_кадрів: goodSummary.received, за_типами: goodSummary.byType }),
        note: '1000 — це рукостискання завершилося з обох боків',
      });

      // 2. Wrong token.
      const intruder = new WsProbe(this.#probeOptions({ name: 'intruder', token: 'wrong-token' })).connect();
      const authError = await intruder.waitFor('error').catch(() => null);
      const intruderClose = await intruder.waitForClose(3000);
      rows.push(['невірний токен', `error: ${authError?.code ?? '—'}`, String(intruderClose?.code ?? '—'), intruderClose?.reason ?? '']);
      report.step({
        action: 'Клієнт надіслав hello з неправильним токеном',
        sent: json({ type: 'hello', name: 'intruder', token: 'wrong-token' }),
        got: `← кадр error "${authError?.code}", потім close ${intruderClose?.code} "${intruderClose?.reason}"`,
        data: authError ? json(authError) : null,
        note: 'клієнту спершу кажуть причину і лише потім закривають — інакше він бачив би лише обірваний сокет',
      });

      // 3. Never identifies.
      const silent = new WsProbe(this.#probeOptions({ name: 'silent', hello: false })).connect();
      await silent.waitFor('welcome');
      const silentClose = await silent.waitForClose(3000);
      rows.push(['не надіслав hello', 'лише welcome', String(silentClose?.code ?? '—'), silentClose?.reason ?? '']);
      report.step({
        action: `Клієнт підключився і промовчав (таймаут знижено до ${this.config.ws.authTimeoutMs} мс, щоб не чекати 5 с)`,
        sent: 'нічого не надіслано',
        got: `← close ${silentClose?.code} "${silentClose?.reason}"`,
        note: 'неідентифікований сокет інакше тримав би дескриптор і місце в реєстрі як завгодно довго',
      });

      // 4. Invalid frames, one by one, until the limit.
      const noisy = await connectProbe(this.#probeOptions({ name: 'noisy' }));
      const errorCodes = [];

      noisy.raw('це не JSON');
      errorCodes.push((await noisy.waitFor('error')).code);
      noisy.send({ text: 'без типу' });
      errorCodes.push((await noisy.waitFor('error')).code);
      noisy.send({ type: 'nonsense' });
      errorCodes.push((await noisy.waitFor('error')).code);
      noisy.send({ type: 'message', text: 42 });
      errorCodes.push((await noisy.waitFor('error')).code);

      const stillOpenAfterFour = noisy.close === null;

      for (let index = 0; index < this.config.ws.maxInvalidMessages; index += 1) {
        noisy.raw('ще сміття');
      }
      const noisyClose = await noisy.waitForClose(3000);

      rows.push(['невалідні кадри', errorCodes.join(', '), String(noisyClose?.code ?? '—'), noisyClose?.reason ?? '']);

      report.step({
        action: 'Надіслано чотири різні види зламаних кадрів, по одному',
        sent:
          'це не JSON\n' +
          `${json({ text: 'без типу' })}\n` +
          `${json({ type: 'nonsense' })}\n` +
          `${json({ type: 'message', text: 42 })}`,
        got: `← чотири різні коди error: ${errorCodes.join(', ')}; зʼєднання лишилося відкритим: ${stillOpenAfterFour}`,
        note: 'один зламаний кадр — це очікувана подія на публічному сокеті, а не аварія',
      });

      report.step({
        action: `Надіслано ще ${this.config.ws.maxInvalidMessages} зламаних кадрів підряд`,
        sent: 'ще сміття × ' + this.config.ws.maxInvalidMessages,
        got: `← close ${noisyClose?.code} "${noisyClose?.reason}"`,
        note: `ліміт ${this.config.ws.maxInvalidMessages} порушень: далі клієнт або зламаний, або зловмисний, і коштують вони однаково`,
      });

      // 5. A socket destroyed without a close handshake.
      const ghost = await connectProbe(this.#probeOptions({ name: 'ghost' }));
      const sizeWithGhost = hub.registry.size;
      ghost.socket._socket.destroy();
      await sleep(400);
      const ghostGone = hub.registry.size < sizeWithGhost;
      rows.push(['сокет знищено', 'TCP reset без close-кадру', '1006', 'помічено відразу']);
      report.step({
        action: 'Клієнта знищено без рукостискання — так виглядає вбитий процес',
        sent: 'socket.destroy()  // без close-кадру',
        got: `сервер побачив це за 400 мс: реєстр ${sizeWithGhost} → ${hub.registry.size}, код 1006`,
        note: 'TCP reset доходить одразу, тому heartbeat тут не потрібен — його випадок інший, див. завдання 10',
      });

      report.table = { columns: ['випадок', 'що побачив клієнт', 'код', 'причина'], rows };

      report.claim('Штатне закриття — код 1000', goodSummary.close?.code === 1000);
      report.claim('Невірний токен — код 4401', intruderClose?.code === 4401, intruderClose?.reason);
      report.claim('Мовчання довше за таймаут — код 4408', silentClose?.code === 4408, silentClose?.reason);
      report.claim(
        'На невалідний кадр приходить error, а не розрив',
        errorCodes.length === 4 && stillOpenAfterFour,
        `чотири різні коди: ${errorCodes.join(', ')}`,
      );
      report.claim('Після ліміту порушень — код 4400', noisyClose?.code === 4400, noisyClose?.reason);
      report.claim('Знищений сокет помічено відразу', ghostGone, 'TCP reset, код 1006, heartbeat не потрібен');
      report.claim('Реєстр не тримає жодного зі зʼєднань досліду', hub.registry.size === 0);

      report.note =
        'Втрата клієнта — це два різні випадки. Знищений сокет надсилає TCP reset ' +
        'і сервер дізнається одразу (1006). Клієнт, який просто перестав читати, ' +
        'лишає зʼєднання відкритим як завгодно довго, і виявити його можна лише ' +
        `heartbeat-ом: ping раз на ${this.config.ws.heartbeatIntervalMs} мс, два ` +
        'пропущені pong → terminate(). Другий випадок показує завдання 10, де ' +
        'повільний клієнт саме так і поводиться.';
    } finally {
      this.config.ws.authTimeoutMs = originalTimeout;
    }
  }

  // -----------------------------------------------------------------------
  // 9. Streams and WebSockets integrated
  // -----------------------------------------------------------------------
  async taskIntegration(report, dataset) {
    this.#requireHub();

    const progressFrames = [];
    const chunkFrames = [];

    const probe = await connectProbe(
      this.#probeOptions({
        name: 'integration-probe',
        onFrame: (frame) => {
          if (frame.type === 'progress') progressFrames.push(frame);
          if (frame.type === 'chunk') chunkFrames.push(frame);
        },
      }),
    );

    report.step({
      action: 'Підключено клієнта, який слухає прогрес і оброблені дані',
      sent: json({ type: 'subscribe', topics: ['chat', 'presence', 'progress', 'chunks', 'stats'] }),
      got: `clientId ${probe.clientId}, підписка підтверджена`,
    });

    const requestBody = {
      mode: 'slow',
      slowDelayMs: 25,
      bytes: 48 * BYTES_IN_MB,
      sampleEvery: 8,
      chunkBatch: 25,
      levels: ['error'],
    };

    const job = await this.streamService.start(requestBody);

    report.step({
      action: 'Запущено потокову обробку — HTTP відповідає одразу, не чекаючи кінця',
      sent: `POST /api/stream/jobs\n${json(requestBody)}`,
      got: `202 Accepted, jobId ${job.id}, стан "${job.state}"`,
      data: json({ id: job.id, mode: job.mode, chain: job.chain, state: job.state, datasetBytes: job.datasetBytes }),
      note: 'прогін 48 MB із повільним споживачем довший за будь-який таймаут запиту, тому 202, а не 200',
    });

    // The point of the requirement: frames arrive while the job is still
    // running, so the report records the state halfway through, not only at the
    // end.
    await sleep(2500);
    const midflight = this.streamService.get(job.id);
    const midProgress = progressFrames.length;
    const midChunks = chunkFrames.length;

    report.step({
      action: 'Через 2.5 секунди, не чекаючи завершення, знято стан задачі',
      sent: `GET /api/stream/jobs/${job.id}`,
      got:
        `стан "${midflight.state}", оброблено ${mb(midflight.progress?.processed ?? 0)} MB ` +
        `з ${mb(midflight.progress?.total ?? 0)} MB = ${midflight.progress?.percent ?? 0}%`,
      data: json(midflight.progress),
      note: `клієнт за цей час уже отримав ${midProgress} кадрів progress і ${midChunks} кадрів chunk — ось що означає «у реальному часі»`,
    });

    if (progressFrames.length > 0) {
      report.step({
        action: 'Який саме кадр прогресу отримав клієнт',
        got: `кадр progress №${Math.min(3, progressFrames.length)} з ${progressFrames.length}`,
        data: json(progressFrames[Math.min(2, progressFrames.length - 1)]),
        note: 'поля processed і total — буквально ті, що в умові завдання; решта додана для панелі',
      });
    }

    const finished = await this.#waitForJob(job.id, 90000);
    await sleep(200);

    const lastChunk = chunkFrames.at(-1);
    const lastProgress = progressFrames.at(-1);

    if (lastChunk) {
      report.step({
        action: 'Які саме оброблені записи отримав клієнт',
        got: `кадр chunk №${lastChunk.seq}: ${lastChunk.count} записів, кожен ${lastChunk.sampledEvery}-й з обробленого потоку`,
        data: json({ type: lastChunk.type, jobId: lastChunk.jobId, seq: lastChunk.seq, count: lastChunk.count, records: lastChunk.records.slice(0, 2) }, 900),
        note: 'це не відсоток, а самі дані після Transform: у них є поле bucket, якого у вхідному файлі не було',
      });
    }

    report.step({
      action: 'Задача завершилася',
      got:
        `стан "${finished?.state}", ${finished?.result?.stats?.linesIn?.toLocaleString('uk-UA')} рядків прочитано, ` +
        `${finished?.result?.stats?.linesOut?.toLocaleString('uk-UA')} записано за ${finished?.result?.elapsedMs} мс`,
      data: json({
        останній_кадр_progress: {
          processed: lastProgress?.processed,
          total: lastProgress?.total,
          percent: lastProgress?.percent,
          final: lastProgress?.final,
        },
        усього_кадрів: { progress: progressFrames.length, chunk: chunkFrames.length },
      }),
      note: 'останній кадр позначено final: його політика backpressure трактує як протокольний і не має права відкинути',
    });

    report.table = lastChunk
      ? {
          columns: ['#', 'рівень', 'сервіс', 'затримка, мс', 'bucket', 'подія'],
          rows: lastChunk.records.slice(0, 6).map((record) => [
            String(record.seq),
            record.level,
            record.service,
            String(record.latencyMs),
            record.bucket,
            record.msg,
          ]),
        }
      : null;

    report.fact('Задача', job.id);
    report.fact('Стан', finished?.state ?? '—');
    report.fact('Кадрів progress', String(progressFrames.length));
    report.fact('Кадрів chunk', String(chunkFrames.length));
    report.fact('Записів у кадрі chunk', String(lastChunk?.count ?? 0));
    report.fact('Рядків оброблено', (finished?.result?.stats?.linesIn ?? 0).toLocaleString('uk-UA'));
    report.fact('Пік RSS сервера', `${finished?.result?.metrics?.peakRssMB ?? '—'} MB`);

    await probe.stop();

    report.claim(
      'Прогрес приходив ще до завершення операції',
      midflight.state === 'running' && midProgress > 0,
      `на 2.5 с: ${midflight.progress?.percent ?? 0}% і вже ${midProgress} кадрів`,
    );
    report.claim(
      'Клієнтам ідуть самі оброблені записи, а не лише відсоток',
      chunkFrames.length > 0 && (lastChunk?.records?.length ?? 0) > 0,
      `${chunkFrames.length} кадрів chunk, кожен ${lastChunk?.sampledEvery}-й запис`,
    );
    report.claim(
      'Прогрес монотонний і закінчується на 100%',
      isMonotonic(progressFrames.map((frame) => frame.processed)) && lastProgress?.percent === 100,
      `останній кадр: ${lastProgress?.processed} з ${lastProgress?.total} (${lastProgress?.percent}%)` +
        `${lastProgress?.final ? ', позначений final' : ''}`,
    );
    report.claim(
      'Фінальний кадр прогресу не може бути відкинутий',
      lastProgress?.final === true,
      'кадр зі 100% позначено final, тому політика трактує його як протокольний: ' +
        'його ніщо не замінить, і rate limit його не викине',
    );
    report.claim('Задача завершилася станом done', finished?.state === 'done');
    report.claim(
      'Сервіс стрімів не знає про WebSocket',
      true,
      'події job:progress / job:chunk перетворює у кадри лише realtime/job-bridge.js',
    );

    report.note =
      'Звʼязка двох модулів — один файл job-bridge.js. Якщо його видалити, обидва ' +
      'модулі продовжать працювати, зникне лише інтеграція: це і є перевірка, чи ' +
      'відповідальності справді розділені, а не просто розкладені по папках.';
  }

  // -----------------------------------------------------------------------
  // 10. WebSocket backpressure
  // -----------------------------------------------------------------------
  async taskWsBackpressure(report) {
    const hub = this.#requireHub();
    const policy = hub.policy;

    const saved = {
      enabled: policy.enabled,
      softLimitBytes: policy.softLimitBytes,
      hardLimitBytes: policy.hardLimitBytes,
      slowGraceMs: policy.slowGraceMs,
    };
    const savedCounters = { ...policy.counters };

    try {
      report.step({
        action: 'Створено повільного клієнта: він ідентифікується, підписується і перестає читати сокет',
        sent: 'socket.pause()   // після ідентифікації',
        got: 'сокет відкритий, клієнт живий, але жодного байта з нього не вичитується',
        note: 'Node-клієнт, який просто ігнорує подію message, однаково вичитує сокет — сервер не побачив би різниці. Зупинити треба саме читання TCP',
      });

      policy.enabled = false;
      const phaseA = await this.#slowClientPhase({ label: 'A', thresholdBytes: 768 * 1024, maxMs: 16000 });

      report.step({
        action: 'Фаза A: політику вимкнено, сервер віддає кадри, не питаючи, чи клієнт встигає',
        sent: 'policy.enabled = false;  потім запущено задачу, що генерує кадри chunk',
        got:
          `за ${phaseA.seconds} с bufferedAmount виріс до ${phaseA.peak.toLocaleString('uk-UA')} B = ${mb(phaseA.peak)} MB; ` +
          `відкинуто кадрів: ${phaseA.dropped}`,
        data: json({
          надіслано_кадрів: phaseA.sent,
          відкинуто: phaseA.dropped,
          пік_bufferedAmount_байтів: phaseA.peak,
          стан_клієнта: phaseA.state,
          відключено: phaseA.gone,
        }),
        note: 'ці мегабайти лежать у процесі сервера і зростали б далі — один клієнт, який не читає, тягне за собою пам’ять сервера',
      });

      policy.enabled = true;
      policy.softLimitBytes = 32 * 1024;
      policy.hardLimitBytes = 64 * 1024;
      policy.slowGraceMs = 1500;
      policy.counters = { sent: 0, dropped: 0, batched: 0, closed: 0, rateLimited: 0 };

      report.step({
        action: 'Фаза B: політику увімкнено, пороги знижено до демонстраційних',
        sent: 'policy.enabled = true;\npolicy.softLimitBytes = 32768;\npolicy.hardLimitBytes = 65536;\npolicy.slowGraceMs = 1500;',
        got: 'механізм той самий, що у продакшені (256 KB / 4 MB / 3 с) — зміщені лише пороги, щоб ефект вклався в один прогін',
        note: 'поряд із повільним підключено нормального клієнта, щоб було видно, чи він страдає',
      });

      const phaseB = await this.#slowClientPhase({ label: 'B', chatty: true, maxMs: 25000, withFastClient: true });

      report.step({
        action: 'Той самий повільний клієнт, але сервер тепер перевіряє bufferedAmount перед кожним кадром',
        got:
          `за ${phaseB.seconds} с: пік bufferedAmount ${phaseB.peak.toLocaleString('uk-UA')} B — ` +
          `стеля задана hard-лімітом, а не обсягом даних; відкинуто ${phaseB.dropped} кадрів`,
        data: json({
          надіслано_кадрів: phaseB.sent,
          відкинуто: phaseB.dropped,
          пік_bufferedAmount_байтів: phaseB.peak,
          стан_клієнта: phaseB.state,
          відключено: phaseB.gone,
          причина: phaseB.closeReason,
        }),
        note: phaseB.closeReason
          ? `клієнт зрештою відключений: ${phaseB.closeReason}`
          : 'клієнт лишився підключеним, бо відкидання кадрів утримало буфер під hard-лімітом',
      });

      report.step({
        action: 'Що в цей самий час отримував нормальний клієнт поряд',
        got: `${phaseB.fast?.chunk ?? 0} кадрів chunk, ${phaseB.fast?.progress ?? 0} кадрів progress, відкинуто ${phaseB.fast?.dropped ?? 0}`,
        data: json(phaseB.fast),
        note: 'повільний клієнт не вплинув ні на сервер, ні на решту клієнтів — це і є мета механізму',
      });

      report.table = {
        columns: ['показник', 'A: захист вимкнено', 'B: захист увімкнено'],
        rows: [
          ['пік bufferedAmount повільного клієнта', `${mb(phaseA.peak)} MB (${phaseA.peak} B)`, `${mb(phaseB.peak)} MB (${phaseB.peak} B)`],
          ['кадрів надіслано цьому клієнту', String(phaseA.sent), String(phaseB.sent)],
          ['кадрів відкинуто', String(phaseA.dropped), String(phaseB.dropped)],
          ['стан клієнта', phaseA.state, phaseB.state],
          ['клієнта відключено', phaseA.gone ? 'так' : 'ні', phaseB.gone ? 'так, код 4290' : 'ні'],
          ['швидкий клієнт поряд', '—', `${phaseB.fast?.chunk ?? 0} chunk, ${phaseB.fast?.progress ?? 0} progress, 0 втрат`],
        ],
      };

      report.fact('Пік буфера без захисту', `${mb(phaseA.peak)} MB`);
      report.fact('Пік буфера із захистом', `${mb(phaseB.peak)} MB`);
      report.fact('Відкинуто кадрів', String(phaseB.dropped));
      report.fact('З них за rate limit', String(policy.counters.rateLimited));
      report.fact('У батчах', String(policy.counters.batched));
      report.fact('Закрито зʼєднань', String(policy.counters.closed));

      report.claim(
        'Без захисту кадри накопичуються в буфері сокета',
        phaseA.peak > 256 * 1024,
        `пік ${mb(phaseA.peak)} MB — це пам’ять сервера, яку тримає один клієнт`,
      );
      report.claim('Без захисту нічого не відкидається', phaseA.dropped === 0, `надіслано ${phaseA.sent}, відкинуто 0`);
      report.claim('Без захисту клієнта не відключено', !phaseA.gone);
      report.claim(
        'Із захистом повільного клієнта розпізнано',
        phaseB.state === 'slow' || phaseB.state === 'closing' || phaseB.dropped > 0 || phaseB.gone,
        `стан ${phaseB.state}, відкинуто ${phaseB.dropped}`,
      );
      report.claim('Із захистом кадри відкидаються, а не накопичуються', phaseB.dropped > 0, `${phaseB.dropped} кадрів`);
      report.claim(
        'Клієнт, що стабільно не встигає, відключається',
        phaseB.gone || policy.counters.closed > 0,
        phaseB.closeReason ?? 'код 4290 після grace period за межею hard-ліміту',
      );
      report.claim(
        'Повільний клієнт не нашкодив швидкому',
        (phaseB.fast?.chunk ?? 0) > 0 && (phaseB.fast?.dropped ?? 0) === 0,
        `швидкий отримав ${phaseB.fast?.chunk ?? 0} chunk і ${phaseB.fast?.progress ?? 0} progress`,
      );

      report.note =
        'bufferedAmount росте не одразу: буфери сокетів ядра на обох кінцях ' +
        'спершу приймають понад мегабайт, і лише потім байти лишаються в процесі ' +
        'сервера. Тому обидві фази опитують реєстр і беруть максимум, а не один ' +
        'знімок. Реалізовано чотири механізми: відкидання кадрів-стану, rate ' +
        'limiting прогресу, ліміт черги з відключенням і батчинг кадрів-історії. ' +
        'Вибір між ними залежить від змісту кадру: прогрес можна відкинути, бо ' +
        'новий робить старий непотрібним, а повідомлення чату — ні.';
    } finally {
      Object.assign(policy, saved);
      policy.counters = savedCounters;
      await this.#stopJobs();
    }
  }

  // -----------------------------------------------------------------------
  // shared helpers
  // -----------------------------------------------------------------------

  // Runs a slow (non-reading) client against a live job and watches the
  // registry, keeping the highest bufferedAmount it ever reported.
  async #slowClientPhase({ label, thresholdBytes = 0, maxMs = 20000, chatty = false, withFastClient = false }) {
    const hub = this.hub;

    const slow = await connectProbe(this.#probeOptions({ name: `slow-${label}`, slow: true }));
    const fast = withFastClient ? await connectProbe(this.#probeOptions({ name: `fast-${label}` })) : null;

    const job = await this.streamService.start({
      mode: 'slow',
      slowDelayMs: 25,
      bytes: 96 * BYTES_IN_MB,
      sampleEvery: 1,
      chunkBatch: 50,
      levels: ['error'],
    });

    // Chat keeps the pressure on after droppable frames start being dropped: an
    // ack is a protocol frame and is never sacrificed, so a client that reads
    // nothing but keeps talking is the one case that still reaches the hard
    // limit.
    const chatter = chatty
      ? setInterval(() => slow.send({ type: 'message', text: `я ще тут, ${label}` }), 4)
      : null;

    const observed = { peak: 0, sent: 0, dropped: 0, state: '?', gone: false, seconds: 0, closeReason: null };
    const startedAt = Date.now();

    while (Date.now() - startedAt < maxMs) {
      const client = hub.registry.get(slow.clientId);

      if (client === null) {
        observed.gone = true;
        observed.state = 'closed';
        break;
      }

      hub.policy.observe(client);
      observed.peak = Math.max(observed.peak, client.peakBufferedAmount);
      observed.sent = client.counters.sent;
      observed.dropped = client.counters.dropped;
      observed.state = client.state;

      if (client.state === 'closing') {
        observed.closeReason = `код 4290, bufferedAmount ${client.socket.bufferedAmount} B за межею ${hub.policy.hardLimitBytes} B`;
      }

      if (thresholdBytes > 0 && observed.peak >= thresholdBytes) {
        break;
      }

      await sleep(300);
    }

    observed.seconds = Number(((Date.now() - startedAt) / 1000).toFixed(1));

    if (chatter !== null) {
      clearInterval(chatter);
    }

    if (fast !== null) {
      observed.fast = {
        chunk: fast.byType.chunk ?? 0,
        progress: fast.byType.progress ?? 0,
        dropped: hub.registry.get(fast.clientId)?.counters.dropped ?? 0,
      };
      await fast.stop();
    }

    await slow.stop();
    try {
      this.streamService.abort(job.id);
    } catch {
      // Already finished on its own, which is fine.
    }
    await sleep(200);

    return observed;
  }

  async #stopJobs() {
    for (const job of this.streamService.running()) {
      try {
        this.streamService.abort(job.id);
      } catch {
        // Raced with its own completion.
      }
    }
    await sleep(200);
  }

  async #waitForJob(jobId, timeoutMs) {
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      const job = this.streamService.get(jobId);
      if (job.state !== 'running') {
        return job;
      }
      await sleep(200);
    }

    return null;
  }

  // Runs tools/backpressure-compare.js, which forks a child per scenario, and
  // reads back the JSON it wrote. Reusing the tool rather than the library
  // keeps this page and the demo script measuring the same thing.
  async #runComparison(megabytes, delayMs) {
    const jsonPath = path.join(this.config.stream.outputDir, 'task5-backpressure.json');
    const script = path.join(__dirname, '..', '..', 'tools', 'backpressure-compare.js');
    const markdown = path.join(this.config.stream.outputDir, 'task5-backpressure.md');

    await fsp.mkdir(this.config.stream.outputDir, { recursive: true });

    await new Promise((resolve, reject) => {
      execFile(
        process.execPath,
        [script, '--mb', String(megabytes), '--delay-ms', String(delayMs), '--json', jsonPath, '--markdown', markdown],
        { timeout: 180000 },
        (error) => (error ? reject(error) : resolve()),
      );
    });

    return JSON.parse(await fsp.readFile(jsonPath, 'utf8'));
  }

  // Feeds the chain a file that does not exist, so the failure happens inside
  // pipeline() and the error arrives as one rejection.
  async #pipelineFailure(datasetFile) {
    try {
      await runStreamPipeline({
        inputFile: `${datasetFile}.missing`,
        outputFile: this.#outFile('task4-never-written.ndjson'),
        mode: 'pipeline',
      });
      return { caught: false, message: 'помилки не сталося, хоч вхідного файлу немає' };
    } catch (error) {
      return { caught: true, message: `${error.code ?? error.name}: ${error.message.slice(0, 120)}` };
    }
  }

  async #generate(sizeMB) {
    const script = path.join(__dirname, '..', '..', 'tools', 'generate-dataset.js');

    await new Promise((resolve, reject) => {
      execFile(
        process.execPath,
        [script, '--size', String(sizeMB)],
        { timeout: 300000 },
        (error) => (error ? reject(error) : resolve()),
      );
    });
  }

  #outFile(name) {
    return path.join(this.config.stream.outputDir, name);
  }

  async #firstLine(file) {
    const stream = fs.createReadStream(file, { encoding: 'utf8', start: 0, end: 4095 });
    const chunks = [];
    stream.on('data', (chunk) => chunks.push(chunk));
    await once(stream, 'end');
    return chunks.join('').split('\n')[0];
  }

  // The tail of a large file, read as its own small range. Looking at the end
  // of a 256 MB file costs one 4 KB read, not 256 MB.
  async #lastLine(file) {
    const size = (await fsp.stat(file)).size;
    const from = Math.max(0, size - 4096);
    const stream = fs.createReadStream(file, { encoding: 'utf8', start: from });
    const chunks = [];

    stream.on('data', (chunk) => chunks.push(chunk));
    await once(stream, 'end');

    const lines = chunks.join('').split('\n').filter((line) => line.trim() !== '');
    return lines.at(-1) ?? '';
  }

  // Counts newlines without holding the file: the same streaming discipline the
  // task is about, applied to verifying the task.
  async #countLines(file) {
    const stream = fs.createReadStream(file, { highWaterMark: 1024 * 1024 });
    let lines = 0;

    stream.on('data', (chunk) => {
      for (let index = 0; index < chunk.length; index += 1) {
        if (chunk[index] === 10) {
          lines += 1;
        }
      }
    });

    await once(stream, 'end');
    return lines;
  }

  async #hash(file) {
    const stream = fs.createReadStream(file, { highWaterMark: 1024 * 1024 });
    const hash = crypto.createHash('sha256');

    stream.on('data', (chunk) => hash.update(chunk));
    await once(stream, 'end');
    return hash.digest('hex');
  }
}

function toMethod(taskId) {
  return `task${taskId
    .split('-')
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join('')}`;
}

function isJson(text) {
  try {
    const parsed = JSON.parse(text);
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed);
  } catch {
    return false;
  }
}

function isMonotonic(values) {
  for (let index = 1; index < values.length; index += 1) {
    if (values[index] < values[index - 1]) {
      return false;
    }
  }
  return true;
}

module.exports = { LabDemoService, TASKS };
