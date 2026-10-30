const express = require('express');

function createHealthRoutes(controller) {
  const router = express.Router();

  router.get('/', controller.check);

  return router;
}

module.exports = { createHealthRoutes };
