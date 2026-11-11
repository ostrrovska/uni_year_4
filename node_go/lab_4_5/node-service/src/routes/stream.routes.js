const express = require('express');
const { requireJsonBody, validateJobId, validateStreamJob } = require('../middleware/validation');

// Endpoints, methods, middleware order, controller binding. Nothing else, as in
// lab 4 - the job id check and the body check are registered here once and
// cover every route that needs them.
function createStreamRoutes(controller) {
  const router = express.Router();

  router.param('jobId', validateJobId);

  router.get('/dataset', controller.dataset);
  router.get('/jobs', controller.list);
  router.get('/jobs/:jobId', controller.getById);
  router.post('/jobs', requireJsonBody, validateStreamJob, controller.create);
  router.delete('/jobs/:jobId', controller.abort);

  return router;
}

module.exports = { createStreamRoutes };
