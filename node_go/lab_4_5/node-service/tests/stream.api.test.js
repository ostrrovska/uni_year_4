// API tests for the lab 5 endpoints, built the way the lab 4 ones are: the app
// is wired as in production and bound to an ephemeral port, so the whole chain -
// middleware, router, controller, service - is exercised over real HTTP.
//
// The dataset is a small temporary file rather than the 256 MB one, and the
// service is pointed at it through its configuration. That keeps the suite fast
// and makes it independent of whether the generator has been run.
const { after, before, beforeEach, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { createApp } = require('../src/app');
const { InMemoryItemRepository } = require('../src/repositories/in-memory.item.repository');
const { StreamJobService } = require('../src/services/stream.service');
const { RealtimeService } = require('../src/services/realtime.service');
const { LabDemoService } = require('../src/services/lab-demo.service');

let server;
let baseUrl;
let directory;
let streamService;
let settings;

function streamConfig(overrides = {}) {
  return {
    stream: {
      datasetFile: path.join(directory, 'events.ndjson'),
      outputDir: path.join(directory, 'out'),
      highWaterMark: 1024,
      slowDelayMs: 1,
      progressIntervalMs: 10,
      progressBytes: 1024,
      maxConcurrentJobs: 2,
      keepJobs: 20,
      ...overrides,
    },
  };
}

before(async () => {
  directory = await fsp.mkdtemp(path.join(os.tmpdir(), 'lab5-api-'));

  const lines = Array.from({ length: 200 }, (unused, index) =>
    JSON.stringify({
      ts: '2026-11-01T09:00:00.000Z',
      level: index % 3 === 0 ? 'error' : 'info',
      service: 'api',
      itemId: index,
      latencyMs: index,
      msg: 'item created',
    }),
  );
  await fsp.writeFile(path.join(directory, 'events.ndjson'), `${lines.join('\n')}\n`, 'utf8');

  settings = streamConfig();
  streamService = new StreamJobService({ config: settings, log: () => {} });

  const app = createApp({
    repository: new InMemoryItemRepository(),
    repositoryName: 'memory',
    logging: false,
    streamService,
    // No hub either, so the walkthrough tasks that need a socket report 503
    // instead of failing somewhere inside.
    labService: new LabDemoService({ config: settings, streamService, log: () => {} }),
    // No hub: an instance without the WebSocket module is exactly how the
    // "not enabled" branch gets reached.
    realtimeService: new RealtimeService(null),
  });

  server = app.listen(0);
  await new Promise((resolve, reject) => {
    server.once('listening', resolve);
    server.once('error', reject);
  });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await fsp.rm(directory, { recursive: true, force: true });
});

// Jobs are asynchronous, so most tests have to let the previous one finish
// before they count running jobs.
beforeEach(async () => {
  const deadline = Date.now() + 5000;
  while (streamService.running().length > 0 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
});

async function api(method, route, { body, contentType = 'application/json' } = {}) {
  const init = { method, headers: {} };

  if (body !== undefined) {
    init.headers['Content-Type'] = contentType;
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }

  const response = await fetch(`${baseUrl}${route}`, init);
  const text = await response.text();

  return {
    status: response.status,
    location: response.headers.get('location'),
    body: text === '' ? null : JSON.parse(text),
  };
}

async function waitForJob(jobId, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const { body } = await api('GET', `/api/stream/jobs/${jobId}`);
    if (body.state !== 'running') {
      return body;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }

  throw new Error(`job ${jobId} did not finish within ${timeoutMs} ms`);
}

describe('GET /api/stream/dataset', () => {
  it('describes the file the pipeline reads', async () => {
    const { status, body } = await api('GET', '/api/stream/dataset');

    assert.equal(status, 200);
    assert.equal(body.exists, true);
    assert.ok(body.bytes > 0);
    assert.equal(body.file, settings.stream.datasetFile);
  });
});

describe('POST /api/stream/jobs', () => {
  it('accepts a job and answers 202 with its location', async () => {
    const { status, location, body } = await api('POST', '/api/stream/jobs', {
      body: { mode: 'analyze', levels: ['error'] },
    });

    assert.equal(status, 202);
    assert.match(body.id, /^[0-9a-f]{8}$/);
    assert.equal(location, `/api/stream/jobs/${body.id}`);
    assert.equal(body.state, 'running');
    assert.equal(body.mode, 'analyze');

    const finished = await waitForJob(body.id);
    assert.equal(finished.state, 'done');
    assert.equal(finished.result.stats.linesIn, 200);
    assert.equal(finished.result.stats.linesOut, 67);
  });

  it('defaults to analyze through pipeline when the body is empty', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: {} });

    assert.equal(status, 202);
    assert.equal(body.mode, 'analyze');
    assert.equal(body.chain, 'pipeline');
    await waitForJob(body.id);
  });

  it('runs the chain with pipe() when asked', async () => {
    const { body } = await api('POST', '/api/stream/jobs', { body: { chain: 'pipe' } });
    const finished = await waitForJob(body.id);

    assert.equal(finished.chain, 'pipe');
    assert.equal(finished.result.mode, 'pipe');
  });

  it('rejects an unknown mode', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: { mode: 'magic' } });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_job');
    assert.match(body.message, /mode must be one of/);
  });

  it('rejects a highWaterMark outside the allowed range', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: { highWaterMark: 1 } });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_job');
    assert.match(body.message, /highWaterMark must be an integer/);
  });

  it('rejects an unknown level', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: { levels: ['panic'] } });

    assert.equal(status, 400);
    assert.match(body.message, /unknown levels: panic/);
  });

  it('rejects a body that is not an object', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: '[1,2,3]' });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_body');
  });

  it('rejects malformed JSON before any handler runs', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: '{ nope' });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_json');
  });

  it('rejects a request without the JSON content type', async () => {
    const { status, body } = await api('POST', '/api/stream/jobs', { body: '{}', contentType: 'text/plain' });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_content_type');
  });
});

describe('GET /api/stream/jobs', () => {
  it('lists the jobs that have run', async () => {
    const { status, body } = await api('GET', '/api/stream/jobs');

    assert.equal(status, 200);
    assert.ok(Array.isArray(body));
    assert.ok(body.length > 0);
    assert.ok('state' in body[0]);

    // The AbortController must never reach the response.
    assert.equal('controller' in body[0], false);
  });

  it('answers 404 for an unknown job', async () => {
    const { status, body } = await api('GET', '/api/stream/jobs/deadbeef');

    assert.equal(status, 404);
    assert.equal(body.error, 'job_not_found');
  });

  it('answers 400 for a job id of the wrong shape', async () => {
    const { status, body } = await api('GET', '/api/stream/jobs/not-an-id');

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_job_id');
  });
});

describe('DELETE /api/stream/jobs/:jobId', () => {
  it('aborts a running job', async () => {
    const started = await api('POST', '/api/stream/jobs', {
      body: { mode: 'slow', slowDelayMs: 50, highWaterMark: 1024 },
    });

    const { status } = await api('DELETE', `/api/stream/jobs/${started.body.id}`);
    assert.equal(status, 204);

    const finished = await waitForJob(started.body.id);
    assert.equal(finished.state, 'aborted');
  });

  it('answers 409 when the job has already finished', async () => {
    const started = await api('POST', '/api/stream/jobs', { body: {} });
    await waitForJob(started.body.id);

    const { status, body } = await api('DELETE', `/api/stream/jobs/${started.body.id}`);
    assert.equal(status, 409);
    assert.equal(body.error, 'job_not_running');
  });

  it('answers 404 for an unknown job', async () => {
    const { status } = await api('DELETE', '/api/stream/jobs/deadbeef');
    assert.equal(status, 404);
  });
});

describe('the concurrency limit', () => {
  it('answers 429 once too many jobs are running', async () => {
    const options = { body: { mode: 'slow', slowDelayMs: 50 } };
    const first = await api('POST', '/api/stream/jobs', options);
    const second = await api('POST', '/api/stream/jobs', options);
    const third = await api('POST', '/api/stream/jobs', options);

    assert.equal(first.status, 202);
    assert.equal(second.status, 202);
    assert.equal(third.status, 429);
    assert.equal(third.body.error, 'too_many_jobs');

    await api('DELETE', `/api/stream/jobs/${first.body.id}`);
    await api('DELETE', `/api/stream/jobs/${second.body.id}`);
  });
});

describe('a missing dataset', () => {
  it('answers 503 rather than failing inside the pipeline', async () => {
    const service = new StreamJobService({
      config: streamConfig({ datasetFile: path.join(directory, 'nothing-here.ndjson') }),
      log: () => {},
    });

    const app = createApp({
      repository: new InMemoryItemRepository(),
      logging: false,
      streamService: service,
    });

    const own = app.listen(0);
    await new Promise((resolve) => own.once('listening', resolve));

    const response = await fetch(`http://127.0.0.1:${own.address().port}/api/stream/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });

    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, 'dataset_missing');

    await new Promise((resolve) => own.close(resolve));
  });
});

describe('GET /api/ws/clients', () => {
  it('answers 503 when the WebSocket module is not enabled', async () => {
    const { status, body } = await api('GET', '/api/ws/clients');

    assert.equal(status, 503);
    assert.equal(body.error, 'ws_disabled');
  });

  it('validates the broadcast body before reaching the module', async () => {
    const { status, body } = await api('POST', '/api/ws/broadcast', { body: { text: '' } });

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_text');
  });
});

describe('GET /api/lab/tasks', () => {
  it('lists the ten requirements in order', async () => {
    const { status, body } = await api('GET', '/api/lab/tasks');

    assert.equal(status, 200);
    assert.equal(body.length, 10);
    assert.deepEqual(body.map((task) => task.number), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    assert.equal(body[0].id, 'dataset');
    assert.equal(body[0].lastResult, null);
    assert.ok(body.every((task) => task.title && task.requirement));
  });

  it('runs a task that needs no socket and reports its claims', async () => {
    const { status, body } = await api('POST', '/api/lab/tasks/dataset/run');

    assert.equal(status, 200);
    assert.equal(body.taskId, 'dataset');
    assert.ok(body.claims.length > 0);
    assert.ok(body.claims.every((claim) => typeof claim.passed === 'boolean'));
    assert.ok(Array.isArray(body.facts));
    assert.equal(typeof body.passed, 'boolean');
  });

  it('answers 503 for a task that needs the WebSocket module', async () => {
    const { status, body } = await api('POST', '/api/lab/tasks/websocket/run');

    assert.equal(status, 503);
    assert.equal(body.error, 'ws_disabled');
  });

  it('answers 404 for an unknown task', async () => {
    const { status, body } = await api('POST', '/api/lab/tasks/nonsense/run');

    assert.equal(status, 404);
    assert.equal(body.error, 'task_not_found');
  });

  it('answers 400 for a task id of the wrong shape', async () => {
    const { status, body } = await api('POST', '/api/lab/tasks/NOT_AN_ID/run');

    assert.equal(status, 400);
    assert.equal(body.error, 'invalid_task_id');
  });
});

describe('the lab 4 endpoints', () => {
  it('still work beside the new ones', async () => {
    const health = await api('GET', '/health');
    assert.equal(health.status, 200);
    assert.equal(health.body.status, 'ok');

    const created = await api('POST', '/api/items', { body: { name: 'still here' } });
    assert.equal(created.status, 201);

    const listed = await api('GET', '/api/items');
    assert.equal(listed.status, 200);
    assert.equal(listed.body.length, 1);
  });

  it('still answer 404 with the same shape for an unknown route', async () => {
    const { status, body } = await api('GET', '/api/nothing');

    assert.equal(status, 404);
    assert.equal(body.error, 'route_not_found');
  });
});
