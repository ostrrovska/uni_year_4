// API-layer tests. The app is wired exactly as in production and bound to an
// ephemeral port (listen(0)), so the whole chain - middleware, router,
// controller, service, repository - is exercised over real HTTP.
const { after, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');

const { createApp } = require('../src/app');
const { InMemoryItemRepository } = require('../src/repositories/in-memory.item.repository');

let server;
let baseUrl;

before(async () => {
  const app = createApp({
    repository: new InMemoryItemRepository(),
    repositoryName: 'memory',
    logging: false,
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
});

// Sends a request and decodes the response. A raw string body is passed through
// untouched, which is how the malformed-JSON case is built.
async function api(method, path, { body, contentType = 'application/json' } = {}) {
  const init = { method, headers: {} };

  if (body !== undefined) {
    init.headers['Content-Type'] = contentType;
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }

  const response = await fetch(`${baseUrl}${path}`, init);
  const text = await response.text();

  return {
    status: response.status,
    location: response.headers.get('location'),
    body: text === '' ? null : JSON.parse(text),
  };
}

describe('GET /health', () => {
  it('answers 200 and names the wired repository', async () => {
    const response = await api('GET', '/health');

    assert.equal(response.status, 200);
    assert.deepEqual(response.body, { status: 'ok', repository: 'memory' });
  });
});

describe('POST /api/items', () => {
  it('creates an item and answers 201 with the stored representation', async () => {
    const response = await api('POST', '/api/items', {
      body: { name: 'Keyboard', description: 'Mechanical' },
    });

    assert.equal(response.status, 201);
    assert.deepEqual(response.body, { id: 1, name: 'Keyboard', description: 'Mechanical' });
    assert.equal(response.location, '/api/items/1');
  });

  it('answers 400 when the required field is missing', async () => {
    const response = await api('POST', '/api/items', { body: { description: 'nameless' } });

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_item');
  });

  it('answers 400 when the name is empty', async () => {
    const response = await api('POST', '/api/items', { body: { name: '   ' } });

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_item');
  });

  it('answers 400 when the body is not valid JSON', async () => {
    const response = await api('POST', '/api/items', { body: '{ "name": ' });

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_json');
  });

  it('answers 400 when the content type is not JSON', async () => {
    const response = await api('POST', '/api/items', { body: 'name=Keyboard', contentType: 'text/plain' });

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_content_type');
  });

  it('answers 409 when the name is already taken, ignoring case', async () => {
    const response = await api('POST', '/api/items', { body: { name: 'KEYBOARD' } });

    assert.equal(response.status, 409);
    assert.equal(response.body.error, 'item_name_taken');
  });
});

describe('GET /api/items', () => {
  it('answers 200 with the list', async () => {
    const response = await api('GET', '/api/items');

    assert.equal(response.status, 200);
    assert.ok(Array.isArray(response.body));
    assert.deepEqual(response.body.map((item) => item.name), ['Keyboard']);
  });
});

describe('GET /api/items/:id', () => {
  it('answers 200 for an existing item', async () => {
    const response = await api('GET', '/api/items/1');

    assert.equal(response.status, 200);
    assert.equal(response.body.name, 'Keyboard');
  });

  it('answers 404 for a missing item', async () => {
    const response = await api('GET', '/api/items/9999');

    assert.equal(response.status, 404);
    assert.deepEqual(response.body, {
      error: 'item_not_found',
      message: 'Item with id 9999 was not found',
    });
  });

  // The id middleware rejects this before the controller runs, so neither the
  // Service nor the Repository is ever reached.
  it('answers 400 for an identifier that is not a number', async () => {
    const response = await api('GET', '/api/items/abc');

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_id');
  });

  it('answers 400 for a zero identifier', async () => {
    const response = await api('GET', '/api/items/0');

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_id');
  });
});

describe('PUT /api/items/:id', () => {
  it('answers 200 and returns the updated item', async () => {
    const response = await api('PUT', '/api/items/1', {
      body: { name: 'Keypad', description: 'Compact' },
    });

    assert.equal(response.status, 200);
    assert.deepEqual(response.body, { id: 1, name: 'Keypad', description: 'Compact' });
  });

  it('answers 404 for a missing item', async () => {
    const response = await api('PUT', '/api/items/9999', { body: { name: 'Ghost' } });

    assert.equal(response.status, 404);
    assert.equal(response.body.error, 'item_not_found');
  });

  it('answers 400 for an invalid identifier', async () => {
    const response = await api('PUT', '/api/items/abc', { body: { name: 'Ghost' } });

    assert.equal(response.status, 400);
    assert.equal(response.body.error, 'invalid_id');
  });
});

describe('DELETE /api/items/:id', () => {
  it('answers 204 with an empty body', async () => {
    const response = await api('DELETE', '/api/items/1');

    assert.equal(response.status, 204);
    assert.equal(response.body, null);
  });

  it('leaves the item gone, so a second read answers 404', async () => {
    const response = await api('GET', '/api/items/1');

    assert.equal(response.status, 404);
    assert.equal(response.body.error, 'item_not_found');
  });

  it('answers 404 when deleting an item that is already gone', async () => {
    const response = await api('DELETE', '/api/items/1');

    assert.equal(response.status, 404);
    assert.equal(response.body.error, 'item_not_found');
  });
});

describe('unknown routes', () => {
  it('answer 404 through the same centralized formatter', async () => {
    const response = await api('GET', '/api/nothing-here');

    assert.equal(response.status, 404);
    assert.equal(response.body.error, 'route_not_found');
  });
});

describe('error responses', () => {
  it('always carry an error code and a human-readable message', async () => {
    const failures = await Promise.all([
      api('GET', '/api/items/abc'),
      api('GET', '/api/items/9999'),
      api('POST', '/api/items', { body: {} }),
      api('GET', '/api/nothing-here'),
    ]);

    for (const response of failures) {
      assert.ok(response.status >= 400, `expected a failure status, got ${response.status}`);
      assert.equal(typeof response.body.error, 'string');
      assert.equal(typeof response.body.message, 'string');
      assert.ok(response.body.message.length > 0);
    }
  });
});
