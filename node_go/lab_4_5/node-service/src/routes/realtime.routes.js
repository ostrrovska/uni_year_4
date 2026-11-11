const express = require('express');
const { requireJsonBody, requireText } = require('../middleware/validation');

function createRealtimeRoutes(controller) {
  const router = express.Router();

  router.get('/clients', controller.clients);
  router.post('/broadcast', requireJsonBody, requireText, controller.notify);

  return router;
}

module.exports = { createRealtimeRoutes };
