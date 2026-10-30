// Transport-agnostic error raised by the Service layer. It carries a kind and a
// machine-readable code; turning a kind into an HTTP status is the HTTP layer's
// job, which is why nothing here mentions a status code.
const Kind = {
  Validation: 'validation',
  NotFound: 'not_found',
  Conflict: 'conflict',
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
}

module.exports = { DomainError, Kind };
