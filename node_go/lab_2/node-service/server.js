const http = require('http');

const PORT = 3000;
const IO_DELAY_MS = 100;
const CPU_CHUNKS = 4;
const CPU_ITERATIONS = 50_000_000;

const items = [];
let nextId = 1;

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';

    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1e6) {
        req.destroy();
        reject(new Error('Request body too large'));
      }
    });

    req.on('end', () => {
      if (!body) {
        resolve({});
        return;
      }

      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(new Error('Invalid JSON'));
      }
    });

    req.on('error', reject);
  });
}

function findItem(id) {
  return items.find((item) => item.id === Number(id));
}

function queryInt(url, key, fallback) {
  const value = Number(url.searchParams.get(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

// The return value is used by the caller so V8 cannot eliminate the loop.
function burn(iterations) {
  let sum = 0;
  for (let i = 0; i < iterations; i++) {
    sum += i;
  }
  return sum;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const pathname = url.pathname;

  if (req.method === 'GET' && pathname === '/health') {
    sendJson(res, 200, { status: 'ok' });
    return;
  }

  if (req.method === 'GET' && pathname === '/io') {
    const delayMs = queryInt(url, 'ms', IO_DELAY_MS);
    const startedAt = Date.now();

    await new Promise((resolve) => setTimeout(resolve, delayMs));

    sendJson(res, 200, {
      endpoint: 'io',
      delayMs,
      elapsedMs: Date.now() - startedAt,
    });
    return;
  }

  if (req.method === 'GET' && pathname === '/cpu') {
    const chunks = queryInt(url, 'chunks', CPU_CHUNKS);
    const iterations = queryInt(url, 'n', CPU_ITERATIONS);
    const startedAt = Date.now();

    let checksum = 0;
    for (let chunk = 0; chunk < chunks; chunk++) {
      checksum += burn(iterations);
    }

    sendJson(res, 200, {
      endpoint: 'cpu',
      mode: 'sequential',
      chunks,
      iterationsPerChunk: iterations,
      checksum,
      elapsedMs: Date.now() - startedAt,
    });
    return;
  }

  if (req.method === 'GET' && pathname === '/items') {
    sendJson(res, 200, items);
    return;
  }

  const itemsMatch = /^\/items\/(\d+)$/.exec(pathname);

  if (req.method === 'GET' && itemsMatch) {
    const item = findItem(itemsMatch[1]);
    if (!item) {
      sendJson(res, 404, { error: 'Item not found' });
      return;
    }
    sendJson(res, 200, item);
    return;
  }

  if (req.method === 'POST' && pathname === '/items') {
    try {
      const data = await parseBody(req);
      if (!data || typeof data.name !== 'string' || !data.name.trim()) {
        sendJson(res, 400, { error: 'Name is required' });
        return;
      }

      const item = {
        id: nextId++,
        name: data.name.trim(),
        description: typeof data.description === 'string' ? data.description : '',
      };

      items.push(item);
      sendJson(res, 201, item);
    } catch (error) {
      sendJson(res, 400, { error: error.message || 'Invalid request body' });
    }
    return;
  }

  if (req.method === 'PUT' && itemsMatch) {
    try {
      const item = findItem(itemsMatch[1]);
      if (!item) {
        sendJson(res, 404, { error: 'Item not found' });
        return;
      }

      const data = await parseBody(req);
      if (!data || typeof data.name !== 'string' || !data.name.trim()) {
        sendJson(res, 400, { error: 'Name is required' });
        return;
      }

      item.name = data.name.trim();
      item.description = typeof data.description === 'string' ? data.description : item.description;
      sendJson(res, 200, item);
    } catch (error) {
      sendJson(res, 400, { error: error.message || 'Invalid request body' });
    }
    return;
  }

  if (req.method === 'DELETE' && itemsMatch) {
    const itemIndex = items.findIndex((item) => item.id === Number(itemsMatch[1]));
    if (itemIndex === -1) {
      sendJson(res, 404, { error: 'Item not found' });
      return;
    }

    items.splice(itemIndex, 1);
    res.writeHead(204);
    res.end();
    return;
  }

  sendJson(res, 404, { error: 'Not found' });
});

server.listen(PORT, () => {
  console.log(`Node service running on http://localhost:${PORT}`);
  console.log(`  pid=${process.pid}`);
});
