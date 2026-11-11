// Lab5
// Custom metrics and the one function every scenario calls after a request.
//
// Why custom trends at all, when k6 already has http_req_duration: the two breakdowns this lab
// needs - per API instance and per cache outcome - are only knowable from the *response*
// (X-Instance-ID, X-Cache), and a k6 request tag has to be decided before the request is sent.
// So the breakdown is recorded into a tagged custom trend afterwards. Scenario-level tags such
// as phase:measure still apply, which is what makes req_ms{phase:measure,instance:cdn-api-2}
// a usable sub-metric.
//
// srv_ms is the server's own X-Response-Time-ms. Keeping both matters for the defence: req_ms
// includes the balancer and the host network stack, srv_ms does not, so their difference is
// the queueing that happens outside the application - and at saturation that difference is the
// larger of the two.

import { Counter, Rate, Trend } from 'k6/metrics';

export const reqMs = new Trend('req_ms', true);
export const srvMs = new Trend('srv_ms', true);
export const httpStatus = new Counter('http_status');
export const failed = new Rate('req_failed');

// Statuses worth a sub-metric of their own. 503 and 500 are the two the architecture predicts
// under pool exhaustion (docs/bottlenecks.md #4); 502/504 would mean the balancer gave up.
export const STATUSES = [0, 200, 201, 202, 204, 400, 404, 422, 500, 502, 503, 504];

export function record(res, extraTags = {}) {
  const instance = res.headers['X-Instance-Id'] || res.headers['X-Instance-ID'] || 'unknown';
  const cache = res.headers['X-Cache'] || 'NONE';
  const tags = Object.assign({ instance, cache }, extraTags);

  reqMs.add(res.timings.duration, tags);
  const server = Number(res.headers['X-Response-Time-Ms'] || res.headers['X-Response-Time-ms']);
  if (!Number.isNaN(server) && server > 0) {
    srvMs.add(server, tags);
  }
  httpStatus.add(1, Object.assign({ status: String(res.status) }, extraTags));
  // A 0 status is a transport failure (connection refused, timeout) rather than an HTTP answer,
  // and must count as an error even though it carries no status code.
  failed.add(res.status === 0 || res.status >= 400, extraTags);
  return { instance, cache };
}
