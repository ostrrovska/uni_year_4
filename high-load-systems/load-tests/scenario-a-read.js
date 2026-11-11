// Lab5 - Scenario A, read-intensive (clause 2.1).
//
// The read side of the system as docs/architecture.md describes it: every client download
// begins with a route resolution, the catalogue is browsed far less often, and the network
// overview is a dashboard poll. The 80/12/8 mix is that ratio, not an arbitrary weighting.
//
// Resource profile, which is the point of the clause: /routing/resolve is a multi-table join
// whose ORDER BY is over a computed score, so it cannot be served from an index - it is the
// Lab 4 cache target and bottleneck #3. /stats/network is six grouped aggregates, also cached.
// GET /assets is a paginated scan with a COUNT(*), and is deliberately *not* cached, so this
// scenario keeps a real database floor under it even with a warm Redis. That floor is what
// makes the cache comparison in clause 2.6 honest: a scenario that caches to zero would show
// an infinite speed-up and measure nothing.
//
// The key space is bounded on purpose: 6 unpinned assets x 6 client regions = 36 route keys.
// Unbounded paths would never produce a warm cache, and a single hot key would measure Redis
// rather than the cache layer.
//
//   k6 run load-tests/scenario-a-read.js -e STAGE=100 -e LABEL=a-warm-100vu

import http from 'k6/http';
import {
  API, LIVE_STAGES, MEASURE_SECONDS, TREND_STATS,
  flatScenarios, rampScenarios, stagedScenarios, thresholds,
} from './lib/config.js';
import { record } from './lib/metrics.js';
import { discover } from './lib/setup.js';
import { emit } from './lib/summary.js';

const RAMP = __ENV.RAMP === '1';

export const options = {
  scenarios: LIVE_STAGES
    ? stagedScenarios('read', LIVE_STAGES)
    : RAMP
      ? rampScenarios('read')
      : flatScenarios('read'),
  thresholds: thresholds({
    'req_ms{phase:measure,op:resolve}': ['max>=0'],
    'req_ms{phase:measure,op:catalogue}': ['max>=0'],
    'req_ms{phase:measure,op:stats}': ['max>=0'],
    'srv_ms{phase:measure,op:resolve}': ['max>=0'],
  }),
  summaryTrendStats: TREND_STATS,
  // No connection reuse limit and no think time: this measures the ceiling, and a sleep would
  // measure the ladder's arrival rate instead. See lib/config.js.
  discardResponseBodies: false,
  noConnectionReuse: false,
};

export function setup() {
  return discover();
}

export function read(data) {
  const roll = Math.random();
  if (roll < 0.8) {
    const path = data.paths[Math.floor(Math.random() * data.paths.length)];
    const region = data.regions[Math.floor(Math.random() * data.regions.length)];
    const res = http.get(
      `${API}/routing/resolve?path=${encodeURIComponent(path)}&client_region=${region}`,
      { tags: { op: 'resolve' } },
    );
    record(res, { op: 'resolve' });
    return;
  }
  if (roll < 0.92) {
    const res = http.get(`${API}/assets?limit=20`, { tags: { op: 'catalogue' } });
    record(res, { op: 'catalogue' });
    return;
  }
  const res = http.get(`${API}/stats/network`, { tags: { op: 'stats' } });
  record(res, { op: 'stats' });
}

export function handleSummary(data) {
  return emit(data, 'A-read', { measure_seconds: MEASURE_SECONDS, ramp: RAMP });
}
