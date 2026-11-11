const http = require('node:http');
const { config } = require('./config');
const { createApp } = require('./app');
const { InMemoryItemRepository } = require('./repositories/in-memory.item.repository');
const { FileItemRepository } = require('./repositories/file.item.repository');
const { StreamJobService } = require('./services/stream.service');
const { RealtimeService } = require('./services/realtime.service');
const { createWebSocketServer } = require('./realtime/ws-server');
const { attachJobBridge } = require('./realtime/job-bridge');
const { LabDemoService } = require('./services/lab-demo.service');

// The single decision that picks a DataStore. Service, Controller and Router
// code is byte-identical in both modes.
function createRepository(kind) {
  switch (kind) {
    case 'memory':
      return new InMemoryItemRepository();
    case 'file':
      return new FileItemRepository(config.repository.dataFile);
    default:
      throw new Error(`unknown ITEM_REPO "${kind}", expected "memory" or "file"`);
  }
}

// Lab 4 ended with app.listen(PORT). A WebSocket server needs the HTTP server
// object itself, because the handshake is an HTTP request with an Upgrade
// header - the same port, the same server, a different protocol after the
// handshake. So the server is created explicitly and the app is passed to it as
// its request handler.
function createServer() {
  const streamService = new StreamJobService({ config, log: console.log });

  // The HTTP app is built first with a RealtimeService that has no hub yet,
  // because the hub needs the server, the server needs the app, and the app
  // needs the service. The hub is injected once all three exist; until then
  // /api/ws answers 503 rather than crashing.
  const realtimeService = new RealtimeService(null);

  // Drives the walkthrough page. It opens real clients against our own
  // WebSocket endpoint, so like the hub it can only be wired up once the
  // server exists.
  const labService = new LabDemoService({ config, streamService, log: console.log });

  const app = createApp({
    repository: createRepository(config.repository.kind),
    repositoryName: config.repository.kind,
    streamService,
    realtimeService,
    labService,
  });

  const server = http.createServer(app);

  const hub = createWebSocketServer({
    server,
    config,
    log: console.log,
    getJobs: () => streamService.list().slice(-5),
  });

  realtimeService.hub = hub;
  labService.hub = hub;

  // The one line that connects the two modules of this lab.
  attachJobBridge({ service: streamService, broadcaster: hub.broadcaster, log: console.log });

  return { server, hub, streamService, labService };
}

function main() {
  const { server, hub } = createServer();

  server.listen(config.port, () => {
    console.log(`Node service running on http://localhost:${config.port} (repository: ${config.repository.kind})`);
    console.log(`Dashboard             http://localhost:${config.port}/`);
    console.log(`Lab walkthrough       http://localhost:${config.port}/tasks.html`);
    console.log(`WebSocket endpoint    ws://localhost:${config.port}${config.ws.path} (token "${config.ws.token}")`);
    console.log(`Stream dataset        ${config.stream.datasetFile}`);
    console.log(`Backpressure guard    soft ${config.ws.softLimitBytes} B, hard ${config.ws.hardLimitBytes} B, protection ${config.ws.protection ? 'on' : 'off'}`);
    if (config.repository.kind === 'file') {
      console.log(`Data store: ${config.repository.dataFile}`);
    }
  });

  // Open WebSocket connections keep the process alive indefinitely, so Ctrl+C
  // has to close them explicitly or the demo script would have to kill it.
  const shutdown = async (signal) => {
    console.log(`${signal} received, shutting down`);
    await hub.close();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000).unref();
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

if (require.main === module) {
  main();
}

module.exports = { createServer, createRepository };
