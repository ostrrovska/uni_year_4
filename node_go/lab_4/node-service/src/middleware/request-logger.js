// Middleware 1: one line per finished request - method, path, status code and
// duration. Registered first so it measures the whole chain, including the
// error handler.
function requestLogger(req, res, next) {
  const startedAt = process.hrtime.bigint();

  // "finish" fires once the response has been handed to the socket, which is
  // the only moment the final status code is known.
  res.on('finish', () => {
    const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
    console.log(`${req.method} ${req.originalUrl} ${res.statusCode} ${Math.round(elapsedMs)}ms`);
  });

  next();
}

module.exports = { requestLogger };
