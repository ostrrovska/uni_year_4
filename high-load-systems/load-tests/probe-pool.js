// Lab5 - the control pair, and the generator calibration (clauses 2.2 and 2.5).
//
// Two jobs, one script, because they are the same two endpoints.
//
// 1. CALIBRATION, as a ladder of three targets rather than one number. Lab 3 learned why the
//    hard way: the old Python probe topped out near 115 req/s per process and reported that as
//    the system's limit, and docs/context/10 records the lesson as "calibrate the generator
//    before trusting any throughput number".
//
//      -e PROBE=lb      GET /lb-health   a static 200 from nginx that never touches the pool.
//                                        This is the ceiling of k6 + the host loopback +
//                                        the balancer, with no application in the path at all.
//      -e PROBE=health  GET /health      returns a dict; no database, no cache, no business
//                                        logic. The application tier's own ceiling.
//      (default)        both health paths the control pair below.
//
//    The three together attribute the ceiling instead of asserting it: if PROBE=lb is far
//    above PROBE=health, the application tier is the limit and the measurements are the
//    system's. If the two are close, k6 or the balancer is the limit and nothing downstream
//    can be believed.
//
// 2. THE POOL CONTROL PAIR (default). /health and /health/ready differ by exactly one thing:
//    readiness acquires a connection from the SQLAlchemy pool and runs `SELECT 1`. So
//    p95(ready) - p95(live) isolates pool-acquire latency from everything else - request
//    parsing, routing, serialisation, the balancer, the network. It is the direct measurement
//    of bottleneck #4, whose predicted signature is "latency rises while database CPU falls",
//    and a `SELECT 1` is too cheap for the query itself to be the explanation.
//
//    Run the same ladder against docker-compose.lab5-pool2.yml and the gap appears decades
//    earlier, which is what turns the mechanism from an assertion into a demonstration.
//
//   k6 run load-tests/probe-pool.js -e PROBE=health -e STAGE=200 -e LABEL=calib-200vu
//   k6 run load-tests/probe-pool.js -e STAGE=100 -e LABEL=pool-default-100vu

import http from 'k6/http';
import { BASE_URL, MEASURE_SECONDS, TREND_STATS, flatScenarios, thresholds } from './lib/config.js';
import { record } from './lib/metrics.js';
import { emit } from './lib/summary.js';

const PROBE = __ENV.PROBE || 'pair';

export const options = {
  scenarios: flatScenarios('probe'),
  thresholds: thresholds({
    'req_ms{phase:measure,op:lbhealth}': ['max>=0'],
    'req_ms{phase:measure,op:live}': ['max>=0'],
    'req_ms{phase:measure,op:ready}': ['max>=0'],
    'srv_ms{phase:measure,op:live}': ['max>=0'],
    'srv_ms{phase:measure,op:ready}': ['max>=0'],
  }),
  summaryTrendStats: TREND_STATS,
};

export function probe() {
  if (PROBE === 'lb') {
    const stat = http.get(`${BASE_URL}/lb-health`, { tags: { op: 'lbhealth' } });
    record(stat, { op: 'lbhealth' });
    return;
  }
  if (PROBE === 'health') {
    const only = http.get(`${BASE_URL}/health`, { tags: { op: 'live' } });
    record(only, { op: 'live' });
    return;
  }

  // Strict alternation: exactly one endpoint per iteration, so each sees half the offered load
  // and the two samples are the same size. An earlier version sent /health and then
  // /health/ready in the same iteration, which gave readiness twice the request count and
  // therefore a different offered load from the endpoint it was being compared against - the
  // one thing this pair exists to hold constant.
  //
  // Alternating within one scenario rather than running two scenarios side by side, because
  // both endpoints must see the same instant, the same queue depth and the same pool state,
  // or their difference is not attributable to the pool.
  if (__ITER % 2 === 0) {
    const live = http.get(`${BASE_URL}/health`, { tags: { op: 'live' } });
    record(live, { op: 'live' });
    return;
  }
  const ready = http.get(`${BASE_URL}/health/ready`, { tags: { op: 'ready' } });
  record(ready, { op: 'ready' });
}

export function handleSummary(data) {
  const scenario = PROBE === 'pair' ? 'D-pool-probe' : 'calibration';
  return emit(data, scenario, {
    measure_seconds: MEASURE_SECONDS,
    probe: PROBE,
  });
}
