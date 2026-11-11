// Lab5 - Scenario B, write-intensive (clause 2.1).
//
// The write hot path: POST /nodes/{id}/heartbeat is one INSERT into node_heartbeats plus one
// UPDATE of the node's own row, in a single transaction. That is bottleneck #1 (WAL and index
// write amplification on an append-only table) and bottleneck #2 (hot-row MVCC churn and row
// lock contention) in docs/bottlenecks.md, and this scenario exists to confirm or refute them.
//
// Two deliberate choices make it measure the write path and nothing else:
//
// 1. cpu_percent and memory_percent stay strictly below NODE_OVERLOAD_THRESHOLD_PERCENT (85),
//    so no heartbeat triggers a status transition. A transition would also invalidate the
//    route cache, which would turn this into a mixed cache-invalidation scenario and make the
//    p99 impossible to attribute.
// 2. Each VU owns one node (`__VU % nodeCount`) for 85 % of its iterations. Bottleneck #2 is
//    *per-row* lock contention, so the fleet-wide average hides it - the symptom predicted is
//    "p99 degrades for a subset of nodes while the median is unaffected". Pinning a VU to a
//    node is what lets the per-node tail be seen at all. The remaining 15 % is a replica
//    report (PUT, an upsert on a composite key) so the scenario is not a single statement.
//
//   k6 run load-tests/scenario-b-write.js -e STAGE=100 -e LABEL=b-100vu

import http from 'k6/http';
import { API, MEASURE_SECONDS, TREND_STATS, flatScenarios, rampScenarios, thresholds } from './lib/config.js';
import { record } from './lib/metrics.js';
import { discover } from './lib/setup.js';
import { emit } from './lib/summary.js';

const RAMP = __ENV.RAMP === '1';
const JSON_HEADERS = { 'Content-Type': 'application/json' };

export const options = {
  scenarios: RAMP ? rampScenarios('write') : flatScenarios('write'),
  thresholds: thresholds({
    'req_ms{phase:measure,op:heartbeat}': ['max>=0'],
    'req_ms{phase:measure,op:replica}': ['max>=0'],
    'srv_ms{phase:measure,op:heartbeat}': ['max>=0'],
  }),
  summaryTrendStats: TREND_STATS,
};

export function setup() {
  return discover();
}

export function write(data) {
  const node = data.nodeIds[__VU % data.nodeIds.length];

  if (Math.random() < 0.85) {
    const body = JSON.stringify({
      // Bounded at 80: below the 85 % overload threshold, so the node never changes status.
      cpu_percent: 10 + Math.floor(Math.random() * 70),
      memory_percent: 20 + Math.floor(Math.random() * 55),
      bandwidth_out_mbps: Math.floor(Math.random() * 20000),
      active_connections: Math.floor(Math.random() * 12000),
      cache_hit_ratio: Math.round(Math.random() * 1000) / 1000,
    });
    const res = http.post(`${API}/nodes/${node}/heartbeat`, body, {
      headers: JSON_HEADERS,
      tags: { op: 'heartbeat' },
    });
    record(res, { op: 'heartbeat' });
    return;
  }

  const asset = data.assetIds[Math.floor(Math.random() * data.assetIds.length)];
  const body = JSON.stringify({
    state: 'cached',
    cached_version: 1,
    bytes_cached: Math.floor(Math.random() * 90000000),
  });
  const res = http.put(`${API}/nodes/${node}/replicas/${asset}`, body, {
    headers: JSON_HEADERS,
    tags: { op: 'replica' },
  });
  record(res, { op: 'replica' });
}

export function handleSummary(data) {
  return emit(data, 'B-write', { measure_seconds: MEASURE_SECONDS, ramp: RAMP });
}
