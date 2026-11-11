// Transport-agnostic error raised by the Service layer. It carries a kind and a
// machine-readable code; turning a kind into an HTTP status is the HTTP layer's
// job, which is why nothing here mentions a status code.
const Kind = {
  Validation: 'validation',
  NotFound: 'not_found',
  Conflict: 'conflict',
  // Added in lab 5. A stream job can be refused because the dataset has not
  // been generated yet (unavailable) or because the per-process job limit is
  // already reached (rate_limited) - neither is a bad request, and neither is a
  // server fault, so they needed kinds of their own.
  RateLimited: 'rate_limited',
  Unavailable: 'unavailable',
};

class DomainError extends Error {
  constructor(kind, code, message) {
    super(message);
    this.name = 'DomainError';
    this.kind = kind;
    this.code = code;
  }

  static validation(code, message) {
    return new DomainError(Kind.Validation, code, message);
  }

  static notFound(code, message) {
    return new DomainError(Kind.NotFound, code, message);
  }

  static conflict(code, message) {
    return new DomainError(Kind.Conflict, code, message);
  }

  static rateLimited(code, message) {
    return new DomainError(Kind.RateLimited, code, message);
  }

  static unavailable(code, message) {
    return new DomainError(Kind.Unavailable, code, message);
  }
}

module.exports = { DomainError, Kind };
