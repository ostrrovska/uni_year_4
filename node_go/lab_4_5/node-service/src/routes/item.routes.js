const express = require('express');
const { validateId, requireJsonBody } = require('../middleware/validation');

// Router: endpoints, HTTP methods, middleware and the binding to controller
// methods. Nothing else - no parsing, no validation logic, no business rules.
function createItemRoutes(controller) {
  const router = express.Router();

  // Runs for every route below that carries :id, so GET, PUT and DELETE share
  // one id check instead of repeating it three times.
  router.param('id', validateId);

  router.get('/', controller.list);
  router.get('/:id', controller.getById);
  router.post('/', requireJsonBody, controller.create);
  router.put('/:id', requireJsonBody, controller.update);
  router.delete('/:id', controller.remove);

  return router;
}

module.exports = { createItemRoutes };
