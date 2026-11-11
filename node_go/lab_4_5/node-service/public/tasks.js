// The walkthrough page: ten cards, one per requirement of the lab, each with a
// button that runs the real thing on the server and renders what came back.
//
// It knows nothing about any particular task. The server returns a uniform
// shape - claims, facts, an optional table, a log and a note - so adding a task
// means adding it in lab-demo.service.js and nothing here.

const $ = (id) => document.getElementById(id);

// How long the "running" state stays on screen at a minimum.
const MIN_VISIBLE_MS = 450;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function atLeast(startedAt, ms) {
  const elapsed = Date.now() - startedAt;
  return elapsed >= ms ? Promise.resolve() : sleep(ms - elapsed);
}

const state = {
  tasks: [],
  cards: new Map(),
  results: new Map(),
  busy: false,
};

async function loadTasks() {
  const response = await fetch('/api/lab/tasks');

  if (!response.ok) {
    $('loading').textContent = `не вдалося отримати список завдань: HTTP ${response.status}`;
    return;
  }

  state.tasks = await response.json();
  $('loading').remove();

  for (const task of state.tasks) {
    render(task);
  }

  // Deliberately not rendering task.lastResult, although the server still has
  // it: a card that already shows a result makes pressing the button look like
  // it changed nothing. Every result on this page is one the viewer produced.
  updateScore();
}

function render(task) {
  const card = $('task-template').content.firstElementChild.cloneNode(true);

  card.dataset.taskId = task.id;
  card.querySelector('.task-number').textContent = task.number;
  card.querySelector('h2').textContent = task.title;
  card.querySelector('.task-requirement').textContent = task.requirement;
  card.querySelector('.task-run').addEventListener('click', () => runTask(task.id));

  $('tasks').append(card);
  state.cards.set(task.id, card);
}

function setStatus(taskId, text, kind) {
  const pill = state.cards.get(taskId).querySelector('.task-status');
  pill.textContent = text;
  pill.className = `pill task-status pill-${kind}`;
}

async function runTask(taskId) {
  if (state.busy) {
    return;
  }

  // One at a time, enforced on the server as well: several tasks measure memory
  // or socket buffers, and two at once would each be measuring the other.
  state.busy = true;
  const card = state.cards.get(taskId);
  const button = card.querySelector('.task-run');

  // The previous result goes away before the new run starts. Otherwise a task
  // that finishes in 80 ms looks like a card that never changed.
  card.querySelector('.task-result').hidden = true;
  state.results.delete(taskId);
  updateScore();

  button.disabled = true;
  button.textContent = 'виконується…';
  card.classList.add('running');
  setStatus(taskId, 'виконується', 'running');
  card.querySelector('.task-timing').textContent = '';
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });

  const startedAt = Date.now();

  try {
    const response = await fetch(`/api/lab/tasks/${taskId}/run`, { method: 'POST' });
    const payload = await response.json();

    // Five of the ten tasks genuinely finish in under a tenth of a second. The
    // floor is not fake work - the work is already done - it is there so the
    // running state is on screen long enough to be seen at all.
    await atLeast(startedAt, MIN_VISIBLE_MS);

    if (!response.ok) {
      setStatus(taskId, `помилка ${response.status}`, 'bad');
      showError(taskId, payload);
      return;
    }

    showResult(taskId, payload);
  } catch (error) {
    await atLeast(startedAt, MIN_VISIBLE_MS);
    setStatus(taskId, 'не вдалося', 'bad');
    showError(taskId, { error: 'network', message: error.message });
  } finally {
    button.disabled = false;
    button.textContent = 'Запустити знову';
    card.classList.remove('running');
    state.busy = false;
    updateScore();
  }
}

function showError(taskId, payload) {
  const card = state.cards.get(taskId);
  const result = card.querySelector('.task-result');

  result.hidden = false;
  card.querySelector('.task-timing').textContent = '';
  card.querySelector('.claims').innerHTML =
    `<li class="claim claim-fail"><span>✕</span><div><b>${escapeHtml(payload.error ?? 'error')}</b>` +
    `<em>${escapeHtml(payload.message ?? '')}</em></div></li>`;
  card.querySelector('.steps').innerHTML = '';
  card.querySelector('.task-facts').innerHTML = '';
  card.querySelector('.task-table').innerHTML = '';
  card.querySelector('.task-log').hidden = true;
  card.querySelector('.task-note').textContent = '';
}

function showResult(taskId, result) {
  const card = state.cards.get(taskId);
  const box = card.querySelector('.task-result');
  const passed = result.claims.filter((claim) => claim.passed).length;

  state.results.set(taskId, result);
  box.hidden = false;

  setStatus(
    taskId,
    result.passed ? `${passed} / ${result.claims.length} перевірок` : `${passed} / ${result.claims.length} — є провал`,
    result.passed ? 'on' : 'bad',
  );
  card.querySelector('.task-timing').textContent = `${(result.elapsedMs / 1000).toFixed(1)} с`;

  // The transcript first, because it is the evidence. A verdict is only worth
  // something to someone who can see what produced it.
  card.querySelector('.steps').innerHTML = (result.steps ?? [])
    .map(
      (step) => `<li class="step">
        <div class="step-action">${escapeHtml(step.action)}</div>
        ${step.sent ? `<div class="step-io step-sent"><span>надіслано</span><pre>${escapeHtml(step.sent)}</pre></div>` : ''}
        ${step.got ? `<div class="step-got-line">${escapeHtml(step.got)}</div>` : ''}
        ${step.data ? `<div class="step-io step-got"><span>отримано</span><pre>${escapeHtml(step.data)}</pre></div>` : ''}
        ${step.note ? `<div class="step-note">${escapeHtml(step.note)}</div>` : ''}
      </li>`,
    )
    .join('');

  card.querySelector('.claims').innerHTML = result.claims
    .map(
      (claim) => `<li class="claim ${claim.passed ? 'claim-ok' : 'claim-fail'}">
        <span>${claim.passed ? '✓' : '✕'}</span>
        <div><b>${escapeHtml(claim.text)}</b>${claim.detail ? `<em>${escapeHtml(claim.detail)}</em>` : ''}</div>
      </li>`,
    )
    .join('');

  card.querySelector('.task-facts').innerHTML = result.facts
    .map(
      (fact) => `<div class="tile tile-wide">
        <span>${escapeHtml(fact.value)}</span>
        <label>${escapeHtml(fact.label)}</label>
      </div>`,
    )
    .join('');

  card.querySelector('.task-table').innerHTML = result.table
    ? `<table>
        <thead><tr>${result.table.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead>
        <tbody>${result.table.rows
          .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`)
          .join('')}</tbody>
      </table>`
    : '';

  const log = card.querySelector('.task-log');
  log.hidden = result.log.length === 0;
  log.textContent = result.log.join('\n');

  card.querySelector('.task-note').textContent = result.note ?? '';

  // A section with an empty body would otherwise leave a dangling heading.
  for (const [selector, filled] of [
    ['.steps', (result.steps ?? []).length > 0],
    ['.task-facts', result.facts.length > 0 || Boolean(result.table)],
    ['.claims', result.claims.length > 0],
  ]) {
    const heading = card.querySelector(selector).previousElementSibling;
    if (heading && heading.classList.contains('section-title')) {
      heading.hidden = !filled;
    }
  }
}

function updateScore() {
  const done = [...state.results.values()];
  const passed = done.filter((result) => result.passed).length;
  const pill = $('score');

  pill.textContent = `${passed} / ${state.tasks.length} виконано`;
  pill.className = `pill pill-${passed === state.tasks.length && state.tasks.length > 0 ? 'on' : passed === done.length ? 'off' : 'bad'}`;
}

async function runAll() {
  const button = $('run-all');
  button.disabled = true;

  try {
    for (const task of state.tasks) {
      await runTask(task.id);
      await sleep(250);
    }
  } finally {
    button.disabled = false;
  }
}

function reset() {
  state.results.clear();

  for (const [taskId, card] of state.cards) {
    card.querySelector('.task-result').hidden = true;
    card.querySelector('.task-timing').textContent = '';
    card.querySelector('.task-run').textContent = 'Запустити';
    card.classList.remove('running');
    setStatus(taskId, 'не запускалось', 'off');
  }

  updateScore();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
}

$('run-all').addEventListener('click', runAll);
$('reset').addEventListener('click', reset);

loadTasks();
