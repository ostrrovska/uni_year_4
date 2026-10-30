const express = require('express');
const { assertItemRepository } = require('./repositories/item.repository');
const { ItemService } = require('./services/item.service');
const { ItemController } = require('./controllers/item.controller');
const { HealthController } = require('./controllers/health.controller');
const { createItemRoutes } = require('./routes/item.routes');
const { createHealthRoutes } = require('./routes/health.routes');
const { requestLogger } = require('./middleware/request-logger');
const { errorHandler, notFoundHandler } = require('./middleware/error-handler');

// Composition root: the only function that knows which repository
// implementation is in use. Everything below it is wired through abstractions,
// so swapping the repository changes nothing but this call's argument.
//
// It returns the app without calling listen(), which is what lets the API tests
// bind an ephemeral port.
function createApp({ repository, repositoryName = 'unknown', logging = true }) {
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

  // Order matters: the catch-all runs after every route, the error handler last.
  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

module.exports = { createApp };
