const express = require('express');
const { validateTaskId } = require('../middleware/validation');

function createLabRoutes(controller) {
  const router = express.Router();

  router.param('taskId', validateTaskId);

  router.get('/tasks', controller.list);
  router.post('/tasks/:taskId/run', controller.run);

  return router;
}

module.exports = { createLabRoutes };
