// Lab5 - Scenario C, complex end-to-end workflow (clause 2.1).
//
// One iteration is one release of one asset, exactly as docs/architecture.md's "release storm"
// describes it: read the current route, publish new bytes, watch the purge the publish opened,
// acknowledge it from several edge nodes, then read the fleet-wide overview.
//
//   1. GET  /routing/resolve                    read (cached)
//   2. POST /assets/{id}/versions               the business transaction: bumps the version,
//                                               marks every replica stale, opens a purge, and
//                                               takes SELECT ... FOR UPDATE on the asset row
//   3. GET  /purges/{id}                        read the state the write produced
//   4. POST /purges/{id}/acknowledgements  x3   writes, idempotent by composite key
//   5. GET  /stats/network                      six grouped aggregates over the whole fleet
//
// This is the scenario docs/bottlenecks.md #5 predicts will break first: the purge fan-out
// enumerates every targeted node *inside* the request, holding a connection and a row lock for
// the whole duration, and in an async runtime one long await delays every other request on
// that event loop. The prediction is literally "error rate spiking in Scenario C while
// Scenarios A and B look healthy" - so a 200 VU run here is the test of that sentence.
//
// VUs are spread over the assets by `__VU % assetCount`, which with 8 assets means real
// contention on the same row at the upper rungs. That is intentional: spreading the load so
// thinly that no two VUs ever publish the same asset would remove the lock contention the
// clause asks to be measured.
//
//   k6 run load-tests/scenario-c-workflow.js -e STAGE=50 -e LABEL=c-50vu

import http from 'k6/http';
import { check } from 'k6';
import { API, MEASURE_SECONDS, TREND_STATS, flatScenarios, rampScenarios, thresholds } from './lib/config.js';
import { record } from './lib/metrics.js';
import { discover } from './lib/setup.js';
import { emit } from './lib/summary.js';

const RAMP = __ENV.RAMP === '1';
const JSON_HEADERS = { 'Content-Type': 'application/json' };
const ACKS_PER_RELEASE = 3;

export const options = {
  scenarios: RAMP ? rampScenarios('workflow') : flatScenarios('workflow'),
  thresholds: thresholds({
    'req_ms{phase:measure,op:resolve}': ['max>=0'],
    'req_ms{phase:measure,op:publish}': ['max>=0'],
    'req_ms{phase:measure,op:purge-read}': ['max>=0'],
    'req_ms{phase:measure,op:ack}': ['max>=0'],
    'req_ms{phase:measure,op:stats}': ['max>=0'],
    'srv_ms{phase:measure,op:publish}': ['max>=0'],
    'iteration_duration{phase:measure}': ['max>=0'],
  }),
  summaryTrendStats: TREND_STATS,
};

export function setup() {
  return discover();
}

// A 64-hex-character digest, unique per (VU, iteration), because the API treats an unchanged
// content_hash as a no-op and the workflow has to produce a real version bump every time.
function digest() {
  const seed = `${__VU}-${__ITER}-${Date.now()}`;
  let hex = '';
  let h = 2166136261;
  while (hex.length < 64) {
    for (let i = 0; i < seed.length; i += 1) {
      h = (h ^ seed.charCodeAt(i)) * 16777619;
      h >>>= 0;
    }
    h = (h + hex.length + 1) >>> 0;
    hex += h.toString(16).padStart(8, '0');
  }
  return hex.slice(0, 64);
}

export function workflow(data) {
  const assetId = data.assetIds[__VU % data.assetIds.length];
  const region = data.regions[__VU % data.regions.length];
  const path = data.paths[__VU % data.paths.length];

  // 1. read
  const resolved = http.get(
    `${API}/routing/resolve?path=${encodeURIComponent(path)}&client_region=${region}`,
    { tags: { op: 'resolve' } },
  );
  record(resolved, { op: 'resolve' });

  // 2. the business transaction
  const publish = http.post(
    `${API}/assets/${assetId}/versions`,
    JSON.stringify({
      content_hash: digest(),
      size_bytes: 1000000 + Math.floor(Math.random() * 9000000),
      requested_by: 'lab5-loadtest',
      reason: 'scenario C release',
    }),
    { headers: JSON_HEADERS, tags: { op: 'publish' } },
  );
  record(publish, { op: 'publish' });
  const ok = check(publish, { 'publish created a version': (r) => r.status === 201 });
  if (!ok) {
    // A failed publish has no purge to follow. Returning keeps the remaining steps' latency
    // honest instead of recording a 404 chain that would flatter the p99.
    return;
  }

  const purgeId = publish.json('purge_event_id');
  if (!purgeId) {
    return;
  }

  // 3. read the state the write produced
  const progress = http.get(`${API}/purges/${purgeId}`, { tags: { op: 'purge-read' } });
  record(progress, { op: 'purge-read' });

  // 4. acknowledge from several nodes
  for (let i = 0; i < ACKS_PER_RELEASE; i += 1) {
    const node = data.nodeIds[(__VU + i) % data.nodeIds.length];
    const ack = http.post(
      `${API}/purges/${purgeId}/acknowledgements`,
      JSON.stringify({ node_id: node, result: 'purged' }),
      { headers: JSON_HEADERS, tags: { op: 'ack' } },
    );
    record(ack, { op: 'ack' });
  }

  // 5. the aggregate read
  const stats = http.get(`${API}/stats/network`, { tags: { op: 'stats' } });
  record(stats, { op: 'stats' });
}

export function handleSummary(data) {
  return emit(data, 'C-workflow', {
    measure_seconds: MEASURE_SECONDS,
    ramp: RAMP,
    acks_per_release: ACKS_PER_RELEASE,
  });
}
