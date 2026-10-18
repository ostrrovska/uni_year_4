const { DomainError } = require('../errors/domain-error');

// Middleware 2: validation shared by several endpoints. It runs before any
// controller, so a malformed request never reaches the Service or the
// Repository - and the parsed id is handed on, so no controller repeats it.

// Accepts only a positive decimal integer. Registered once as
// router.param('id', validateId), so it covers GET, PUT and DELETE /:id.
function validateId(req, res, next, value) {
  if (!/^[1-9]\d*$/.test(value)) {
    next(DomainError.validation('invalid_id', `Item id must be a positive integer, got "${value}"`));
    return;
  }

  req.itemId = Number(value);
  next();
}

// Guards the write endpoints: JSON content type and a JSON object as the body.
// Malformed JSON never gets this far - express.json() rejects it earlier and
// the error handler turns that into 400 invalid_json.
function requireJsonBody(req, res, next) {
  if (!req.is('application/json')) {
    next(DomainError.validation('invalid_content_type', 'Content-Type must be application/json'));
    return;
  }

  if (!req.body || typeof req.body !== 'object' || Array.isArray(req.body)) {
    next(DomainError.validation('invalid_body', 'Request body must be a JSON object'));
    return;
  }

  next();
}

module.exports = { validateId, requireJsonBody };
