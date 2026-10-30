const { DomainError } = require('../errors/domain-error');

// The single place that knows HTTP status codes. Service and Repository raise
// errors in their own vocabulary; the mapping happens here, so no endpoint ever
// builds an error response of its own.
const KIND_TO_STATUS = {
  validation: 400,
  not_found: 404,
  conflict: 409,
};

// Reached when no route matched. Expressed as a DomainError so the single
// formatter below produces the body.
function notFoundHandler(req, res, next) {
  next(DomainError.notFound('route_not_found', `No route for ${req.method} ${req.originalUrl}`));
}

// Four parameters are what mark this as Express's error-handling middleware.
// Removing "next" would turn it back into an ordinary one.
function errorHandler(err, req, res, next) {
  if (res.headersSent) {
    next(err);
    return;
  }

  if (err instanceof DomainError) {
    res.status(KIND_TO_STATUS[err.kind] ?? 500).json({ error: err.code, message: err.message });
    return;
  }

  // express.json() rejects a malformed payload before any handler runs.
  if (err instanceof SyntaxError && err.type === 'entity.parse.failed') {
    res.status(400).json({ error: 'invalid_json', message: 'Request body is not valid JSON' });
    return;
  }

  // Anything unrecognised is an infrastructure failure: logged in full, while
  // the client is told only that the server failed.
  console.error(`unhandled error on ${req.method} ${req.originalUrl}:`, err.message);
  res.status(500).json({ error: 'internal_error', message: 'Internal server error' });
}

module.exports = { errorHandler, notFoundHandler, KIND_TO_STATUS };
