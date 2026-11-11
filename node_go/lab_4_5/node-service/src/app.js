const path = require('node:path');
const express = require('express');
const { assertItemRepository } = require('./repositories/item.repository');
const { ItemService } = require('./services/item.service');
const { ItemController } = require('./controllers/item.controller');
const { HealthController } = require('./controllers/health.controller');
const { StreamController } = require('./controllers/stream.controller');
const { RealtimeController } = require('./controllers/realtime.controller');
const { LabController } = require('./controllers/lab.controller');
const { createItemRoutes } = require('./routes/item.routes');
const { createHealthRoutes } = require('./routes/health.routes');
const { createStreamRoutes } = require('./routes/stream.routes');
const { createRealtimeRoutes } = require('./routes/realtime.routes');
const { createLabRoutes } = require('./routes/lab.routes');
const { requestLogger } = require('./middleware/request-logger');
const { errorHandler, notFoundHandler } = require('./middleware/error-handler');

// Composition root: the only function that knows which repository
// implementation is in use. Everything below it is wired through abstractions,
// so swapping the repository changes nothing but this call's argument.
//
// It returns the app without calling listen(), which is what lets the API tests
// bind an ephemeral port.
//
// Lab 5 added two optional modules. They are parameters rather than imports
// with side effects, which is why the lab 4 tests still build an app with the
// CRUD module alone and get 404 on everything else - and why the WebSocket
// tests can build one with the realtime module and no dataset on disk.
function createApp({
  repository,
  repositoryName = 'unknown',
  logging = true,
  streamService = null,
  realtimeService = null,
  labService = null,
  serveStatic = true,
}) {
  assertItemRepository(repository);

  const service = new ItemService(repository);
  const itemController = new ItemController(service);
  const healthController = new HealthController(repositoryName);

  const app = express();
  app.disable('x-powered-by');

  if (logging) {
    app.use(requestLogger);
  }
  app.use(express.json());

  app.use('/health', createHealthRoutes(healthController));
  app.use('/api/items', createItemRoutes(itemController));

  if (streamService !== null) {
    app.use('/api/stream', createStreamRoutes(new StreamController(streamService)));
  }

  if (realtimeService !== null) {
    app.use('/api/ws', createRealtimeRoutes(new RealtimeController(realtimeService)));
  }

  // The requirement-by-requirement walkthrough that /tasks.html drives.
  if (labService !== null) {
    app.use('/api/lab', createLabRoutes(new LabController(labService)));
  }

  // The dashboard. Static files come last among the handlers so no route is
  // ever shadowed by a file of the same name.
  if (serveStatic) {
    app.use(express.static(path.join(__dirname, '..', 'public')));
  }

  // Order matters: the catch-all runs after every route, the error handler last.
  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

module.exports = { createApp };
