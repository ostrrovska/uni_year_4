// Dashboard for the lab 5 service. Plain DOM and one WebSocket - no build step
// and no CDN, so the page works with the service and nothing else.
//
// It is the browser side of the same protocol the CLI client speaks: connect,
// wait for welcome, send hello, subscribe, then react to frames. Everything on
// screen is driven by frames arriving, never by polling, which is the point of
// the real-time module.

const $ = (id) => document.getElementById(id);
const MB = 1024 * 1024;

const state = {
  ws: null,
  clientId: null,
  jobId: null,
  frames: 0,
  chunkFrames: 0,
  // One series per scenario label, so compare mode draws three pairs of lines.
  series: new Map(),
  filters: new Set(),
  seenTypes: new Set(),
};

// Read from the stylesheet rather than repeated here, so the chart follows the
// theme instead of drifting from it.
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const SCENARIO_COLORS = {
  default: token('--accent'),
  uncontrolled: token('--bad'),
  manual: token('--warn'),
  pipe: token('--ok'),
};

const SCENARIO_TITLES = {
  default: 'поточна задача',
  uncontrolled: 'A — без контролю',
  manual: 'B — вручну',
  pipe: 'C — pipe()',
};

// ---------------------------------------------------------------------------
// logging and small helpers
// ---------------------------------------------------------------------------

function log(line, cls) {
  const element = $('log');
  const stamp = new Date().toLocaleTimeString('uk-UA');
  element.textContent += `${stamp}  ${line}\n`;

  // Keeping the whole session would make the node grow without bound - the same
  // mistake the backpressure experiment is about, one layer further out.
  const lines = element.textContent.split('\n');
  if (lines.length > 400) {
    element.textContent = lines.slice(-400).join('\n');
  }

  element.scrollTop = element.scrollHeight;
}

function chat(html, cls = '') {
  const box = $('chat');
  const row = document.createElement('div');
  row.className = cls;
  row.innerHTML = html;
  box.append(row);
  while (box.children.length > 120) {
    box.firstChild.remove();
  }
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
}

function setPill(text, cls) {
  const pill = $('conn-pill');
  pill.textContent = text;
  pill.className = `pill ${cls}`;
}

function topics() {
  return [...document.querySelectorAll('.topics input:checked')].map((input) => input.value);
}

// ---------------------------------------------------------------------------
// connection
// ---------------------------------------------------------------------------

function connect() {
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
  const ws = new WebSocket(url);
  state.ws = ws;

  setPill('підключення', 'pill-slow');
  log(`відкриваю ${url}`);

  ws.addEventListener('open', () => log('socket відкрито, чекаю welcome'));

  ws.addEventListener('message', (event) => {
    state.frames += 1;
    $('fact-frames').textContent = state.frames;

    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch {
      log('нерозбірний кадр');
      return;
    }

    if (!state.seenTypes.has(frame.type)) {
      state.seenTypes.add(frame.type);
      renderFilters();
    }

    if (state.filters.size === 0 || state.filters.has(frame.type)) {
      log(summarize(frame));
    }

    handle(frame);
  });

  ws.addEventListener('close', (event) => {
    setPill('офлайн', event.code === 1000 ? 'pill-off' : 'pill-bad');
    $('conn-detail').textContent = `закрито: ${event.code} ${event.reason || ''}`;
    log(`socket закрито, код ${event.code} ${event.reason || ''}`);
    chat(`з'єднання закрито сервером: <b>${event.code}</b> ${escapeHtml(event.reason || '')}`, 'err');
    toggleConnected(false);
    state.ws = null;
  });

  ws.addEventListener('error', () => log('помилка socket'));
}

function toggleConnected(connected) {
  $('connect').disabled = connected;
  $('disconnect').disabled = !connected;
  $('send').disabled = !connected;
  $('bad-json').disabled = !connected;
  $('bad-type').disabled = !connected;
}

function send(object) {
  if (state.ws?.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(object));
  }
}

// ---------------------------------------------------------------------------
// frame handling
// ---------------------------------------------------------------------------

function summarize(frame) {
  switch (frame.type) {
    case 'progress':
      return `progress ${frame.percent}%  ${frame.processed}/${frame.total}${frame.scenario ? `  [${frame.scenario}]` : ''}`;
    case 'chunk':
      return `chunk #${frame.seq}  ${frame.count} записів (кожен ${frame.sampledEvery}-й)`;
    case 'stats':
      return `stats  клієнтів ${frame.clients.total}, відкинуто ${frame.clients.totalDropped}, RSS ${frame.server.rssMB} MB`;
    case 'message':
      return `message від ${frame.from}: ${frame.text}`;
    case 'error':
      return `error ${frame.code}: ${frame.detail}`;
    case 'batch':
      return `batch з ${frame.count} кадрів`;
    default:
      return `${frame.type}  ${JSON.stringify(frame).slice(0, 160)}`;
  }
}

function handle(frame) {
  switch (frame.type) {
    case 'welcome':
      state.clientId = frame.clientId;
      $('fact-id').textContent = frame.clientId;
      $('fact-state').textContent = 'connecting';
      $('policy').textContent =
        `політика: soft ${(frame.limits.softLimitBytes / 1024).toFixed(0)} KB, ` +
        `hard ${(frame.limits.hardLimitBytes / MB).toFixed(1)} MB, ` +
        `захист ${frame.limits.protection ? 'увімкнено' : 'ВИКЛЮЧЕНО'}`;
      send({ type: 'hello', name: $('name').value, token: $('token').value });
      break;

    case 'ready':
      setPill('онлайн', 'pill-on');
      $('conn-detail').textContent = `${frame.name} · ${frame.peers.length} інших клієнтів`;
      $('fact-state').textContent = frame.state;
      $('fact-since').textContent = new Date(frame.connectedAt).toLocaleTimeString('uk-UA');
      toggleConnected(true);
      send({ type: 'subscribe', topics: topics() });
      chat(`ідентифіковано як <span class="from">${escapeHtml(frame.name)}</span>, інших клієнтів: ${frame.peers.length}`, 'sys');
      break;

    case 'presence':
      chat(`<span class="from">${escapeHtml(frame.name ?? frame.clientId)}</span> ${frame.event === 'join' ? "приєднався" : "вийшов"} · усього ${frame.total}`, 'sys');
      break;

    case 'message':
      chat(`<span class="from">${escapeHtml(frame.from)}</span>: ${escapeHtml(frame.text)}`);
      break;

    case 'ack':
      if (frame.of === 'message' && frame.detail) {
        chat(`ack: доставлено ${frame.detail.delivered}, у батчі ${frame.detail.batched}, відкинуто ${frame.detail.dropped}`, 'sys');
      }
      break;

    case 'batch':
      for (const inner of frame.frames) {
        handle(inner);
      }
      break;

    case 'error':
      chat(`помилка ${escapeHtml(frame.code)}: ${escapeHtml(frame.detail ?? '')}`, 'err');
      break;

    case 'job_started':
      state.jobId = frame.jobId;
      state.series.clear();
      $('abort').disabled = false;
      chat(`задача ${frame.jobId} запущена (${frame.mode}, ${frame.chain})`, 'sys');
      break;

    case 'progress':
      onProgress(frame);
      break;

    case 'chunk':
      onChunk(frame);
      break;

    case 'stats':
      onStats(frame);
      break;

    case 'job_done':
    case 'job_error':
    case 'job_aborted':
      onJobEnd(frame);
      break;

    default:
      break;
  }
}

function onProgress(frame) {
  const percent = Math.min(100, frame.percent ?? 0);
  $('bar').style.width = `${percent}%`;
  $('bar-label').textContent = `${percent.toFixed(1)}%${frame.scenario ? ` · ${SCENARIO_TITLES[frame.scenario] ?? frame.scenario}` : ''}`;

  $('m-processed').textContent = (frame.processed / MB).toFixed(1);
  $('m-speed').textContent = frame.throughputMBps ?? '—';
  $('m-in').textContent = frame.linesIn ?? '—';
  $('m-out').textContent = frame.linesOut ?? '—';
  $('m-bad').textContent = frame.malformed ?? '—';
  $('m-rss').textContent = frame.rssMB ?? '—';
  $('m-buf').textContent = ((frame.bufferedBytes ?? frame.bufferedMB * MB ?? 0) / 1024).toFixed(0);
  $('m-time').textContent = ((frame.elapsedMs ?? 0) / 1000).toFixed(1);

  const key = frame.scenario ?? 'default';
  if (!state.series.has(key)) {
    state.series.set(key, []);
  }

  const points = state.series.get(key);
  points.push({
    t: frame.elapsedMs ?? 0,
    rss: frame.rssMB ?? 0,
    buffered: (frame.bufferedBytes ?? 0) / MB || frame.bufferedMB || 0,
  });

  // The chart is a picture of a trend, not a data store: a cap here keeps a
  // minute-long run from growing the array for ever.
  if (points.length > 400) {
    points.shift();
  }

  drawChart();
}

function onChunk(frame) {
  state.chunkFrames += 1;
  $('chunk-stats').textContent = `кадрів chunk: ${state.chunkFrames}, у останньому ${frame.count} записів`;

  const body = $('records');
  body.innerHTML = frame.records
    .slice(-8)
    .map(
      (record) => `<tr>
        <td>${record.seq}</td>
        <td class="level-${escapeHtml(record.level)}">${escapeHtml(record.level)}</td>
        <td>${escapeHtml(record.service)}</td>
        <td>${record.latencyMs}</td>
        <td>${escapeHtml(record.bucket)}</td>
        <td>${escapeHtml(record.msg)}</td>
      </tr>`,
    )
    .join('');
}

function onStats(frame) {
  const rows = frame.clients.clients;
  const body = $('clients');

  body.innerHTML =
    rows.length === 0
      ? '<tr><td colspan="6" class="muted">немає даних</td></tr>'
      : rows
          .map(
            (client) => `<tr>
              <td>${escapeHtml(client.name ?? client.clientId)}${client.clientId === state.clientId ? ' *' : ''}</td>
              <td class="state-${escapeHtml(client.state)}">${escapeHtml(client.state)}</td>
              <td>${(client.bufferedAmount / 1024).toFixed(0)} KB</td>
              <td>${(client.peakBufferedAmount / 1024).toFixed(0)} KB</td>
              <td>${client.sent}</td>
              <td>${client.dropped}</td>
            </tr>`,
          )
          .join('');

  const policy = frame.server.policy;
  $('policy').textContent =
    `політика: ${policy.enabled ? 'увімкнено' : 'ВИКЛЮЧЕНО'} · soft ${(policy.softLimitBytes / 1024).toFixed(0)} KB · ` +
    `hard ${(policy.hardLimitBytes / MB).toFixed(1)} MB · надіслано ${policy.sent} · ` +
    `відкинуто ${policy.dropped} (з них за rate limit ${policy.rateLimited}) · батчів ${policy.batched} · закрито ${policy.closed}`;
}

function onJobEnd(frame) {
  $('abort').disabled = true;
  $('start').disabled = false;

  if (frame.type === 'job_error') {
    chat(`задача ${frame.jobId} впала: ${escapeHtml(frame.error?.message ?? '')}`, 'err');
    return;
  }

  if (frame.type === 'job_aborted') {
    chat(`задача ${frame.jobId} перервана`, 'sys');
    return;
  }

  $('bar').style.width = '100%';
  $('bar-label').textContent = '100%';

  const result = frame.result ?? {};

  if (Array.isArray(result.scenarios) && result.scenarios.length > 0) {
    // compare mode: the exact numbers that go into the report table.
    for (const scenario of result.scenarios) {
      chat(
        `${SCENARIO_TITLES[scenario.scenario] ?? scenario.scenario}: ` +
          `${scenario.elapsedMs} мс, пік буфера ${scenario.peakBufferedMB} MB, ` +
          `приріст RSS ${scenario.rssGrowthMB} MB, пауз ${scenario.pauses}`,
        'sys',
      );

      state.series.set(
        scenario.scenario,
        scenario.series.map((sample) => ({ t: sample.t, rss: sample.rssMB, buffered: sample.bufferedMB })),
      );
    }
    drawChart();
    return;
  }

  const stats = result.stats ?? {};
  chat(
    `задача ${frame.jobId} завершена за ${result.elapsedMs} мс: ` +
      `${stats.linesIn} рядків прочитано, ${stats.linesOut} записано, ` +
      `${stats.malformed} зіпсованих, пік RSS ${result.metrics?.peakRssMB} MB`,
    'sys',
  );
}

// ---------------------------------------------------------------------------
// chart
// ---------------------------------------------------------------------------

function drawChart() {
  const svg = $('chart');
  const width = 600;
  const height = 220;
  const pad = { top: 12, right: 12, bottom: 20, left: 34 };

  const all = [...state.series.values()].flat();
  if (all.length < 2) {
    svg.innerHTML =
      `<text x="300" y="110" fill="${token('--muted')}" font-size="12" text-anchor="middle">немає даних</text>`;
    $('chart-legend').innerHTML = '';
    return;
  }

  const maxT = Math.max(...all.map((point) => point.t), 1);
  const maxY = Math.max(...all.map((point) => Math.max(point.rss, point.buffered)), 1) * 1.1;

  const x = (t) => pad.left + (t / maxT) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - (value / maxY) * (height - pad.top - pad.bottom);

  const parts = [];

  // Grid and the y axis in MB. Four lines are enough to read a value off.
  for (let step = 0; step <= 4; step += 1) {
    const value = (maxY / 4) * step;
    const yy = y(value);
    parts.push(`<line x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}" stroke="${token('--line')}" stroke-width="1"/>`);
    parts.push(`<text x="${pad.left - 5}" y="${yy + 3.5}" fill="${token('--muted')}" font-size="9" text-anchor="end">${value.toFixed(0)}</text>`);
  }

  parts.push(`<text x="${width - pad.right}" y="${height - 6}" fill="${token('--muted')}" font-size="9" text-anchor="end">${(maxT / 1000).toFixed(1)} с</text>`);
  parts.push(`<text x="${pad.left}" y="${height - 6}" fill="${token('--muted')}" font-size="9">0 с</text>`);

  const legend = [];

  for (const [key, points] of state.series) {
    const color = SCENARIO_COLORS[key] ?? SCENARIO_COLORS.default;
    const line = (field, dash) =>
      `<polyline fill="none" stroke="${color}" stroke-width="1.8" ${dash}
        points="${points.map((point) => `${x(point.t).toFixed(1)},${y(point[field]).toFixed(1)}`).join(' ')}"/>`;

    parts.push(line('rss', ''));
    parts.push(line('buffered', 'stroke-dasharray="4 3" stroke-opacity="0.95"'));

    legend.push(
      `<span><i style="background:${color}"></i>${SCENARIO_TITLES[key] ?? key}: RSS — суцільна, буфер — пунктир</span>`,
    );
  }

  svg.innerHTML = parts.join('');
  $('chart-legend').innerHTML = legend.join('');
}

// ---------------------------------------------------------------------------
// log filters
// ---------------------------------------------------------------------------

function renderFilters() {
  const container = $('filters');
  container.innerHTML = '';

  for (const type of [...state.seenTypes].sort()) {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = state.filters.size === 0 || state.filters.has(type);
    input.addEventListener('change', () => {
      // An empty filter set means "everything", so the first unticked box has to
      // seed the set with all the other types.
      if (state.filters.size === 0) {
        for (const seen of state.seenTypes) {
          state.filters.add(seen);
        }
      }
      if (input.checked) {
        state.filters.add(type);
      } else {
        state.filters.delete(type);
      }
    });

    label.append(input, document.createTextNode(` ${type}`));
    container.append(label);
  }
}

// ---------------------------------------------------------------------------
// stream job controls
// ---------------------------------------------------------------------------

async function startJob() {
  const levels = $('levels').value;
  const body = {
    mode: $('mode').value,
    chain: $('chain').value,
    highWaterMark: Number($('hwm').value),
    slowDelayMs: Number($('delay').value),
    delayMs: Number($('delay').value),
    sampleEvery: Number($('sample').value),
  };

  if (levels !== 'all') {
    body.levels = levels.split(',');
  }

  $('start').disabled = true;
  state.series.clear();
  drawChart();

  const response = await fetch('/api/stream/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const payload = await response.json();

  if (!response.ok) {
    chat(`сервер відмовив (${response.status}): ${escapeHtml(payload.message ?? payload.error)}`, 'err');
    $('start').disabled = false;
    return;
  }

  state.jobId = payload.id;
  $('abort').disabled = false;
  log(`POST /api/stream/jobs → 202, job ${payload.id}`);
}

async function abortJob() {
  if (state.jobId === null) {
    return;
  }
  const response = await fetch(`/api/stream/jobs/${state.jobId}`, { method: 'DELETE' });
  log(`DELETE /api/stream/jobs/${state.jobId} → ${response.status}`);
}

async function loadDataset() {
  try {
    const response = await fetch('/api/stream/dataset');
    const dataset = await response.json();
    $('dataset').textContent = dataset.exists
      ? `датасет: ${dataset.sizeMB} MB`
      : 'датасет не згенерований — запустіть npm run gen:data';
    $('start').disabled = !dataset.exists;
  } catch {
    $('dataset').textContent = 'датасет: невідомо';
  }
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

$('port').textContent = location.port || '80';
$('connect').addEventListener('click', connect);
$('disconnect').addEventListener('click', () => state.ws?.close(1000, 'user'));
$('send').addEventListener('click', () => {
  const text = $('text').value.trim();
  if (text !== '') {
    send({ type: 'message', text });
    chat(`<span class="from">я</span>: ${escapeHtml(text)}`);
    $('text').value = '';
  }
});
$('text').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    $('send').click();
  }
});

// Requirement 8: the server must react to an invalid message. These two buttons
// are how that is shown without a debugger.
$('bad-json').addEventListener('click', () => state.ws?.send('це не JSON'));
$('bad-type').addEventListener('click', () => send({ type: 'nonsense', payload: 1 }));

$('start').addEventListener('click', startJob);
$('abort').addEventListener('click', abortJob);

document.querySelectorAll('.topics input').forEach((input) =>
  input.addEventListener('change', () => {
    if (state.ws?.readyState === WebSocket.OPEN) {
      send({ type: 'subscribe', topics: topics() });
    }
  }),
);

loadDataset();
drawChart();
