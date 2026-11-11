// Lab5 - the open-model twin of Scenario A: the coordinated-omission exhibit (clause 4).
//
// Every other run in this lab is a *closed* model: a fixed number of VUs, each sending its
// next request only after the previous one answered. That is the right model for a ladder -
// "200 concurrent users" is a meaningful statement about a system - but it has one property
// that must be said out loud at the defence: when the system slows down, a closed-loop
// generator slows down with it. It stops issuing requests, so the requests that *would* have
// been delayed are never sent, and never measured. The latency distribution it reports is
// conditioned on the system's own health. That is coordinated omission.
//
// This script is the control. `constant-arrival-rate` keeps issuing at a fixed target RPS
// whether or not the system keeps up, allocating more VUs from `maxVUs` as responses slow,
// and reports `dropped_iterations` when even that runs out. Run it at the throughput the
// closed-model ladder found at saturation, and the p99 is materially worse for the same
// nominal load - the open model counts the queueing that the closed model omitted.
//
//   k6 run load-tests/arrival-rate.js -e TARGET_RPS=260 -e LABEL=open-260rps

import http from 'k6/http';
import { API, MEASURE_SECONDS, TREND_STATS, WARMUP_SECONDS, WARMUP_VUS, thresholds } from './lib/config.js';
import { record } from './lib/metrics.js';
import { discover } from './lib/setup.js';
import { emit } from './lib/summary.js';

const TARGET_RPS = Number(__ENV.TARGET_RPS || 200);
// Generously above the closed-model VU count: the executor must never be the thing that
// limits the arrival rate, otherwise it silently becomes a closed model again and the whole
// comparison is void. dropped_iterations in the summary is the check on that.
const MAX_VUS = Number(__ENV.MAX_VUS || 800);

export const options = {
  scenarios: {
    warmup: {
      executor: 'constant-arrival-rate',
      exec: 'open',
      rate: Math.max(10, Math.round(TARGET_RPS / 10)),
      timeUnit: '1s',
      duration: `${WARMUP_SECONDS}s`,
      preAllocatedVUs: WARMUP_VUS * 4,
      maxVUs: MAX_VUS,
      startTime: '0s',
      tags: { phase: 'warmup' },
    },
    measure: {
      executor: 'constant-arrival-rate',
      exec: 'open',
      rate: TARGET_RPS,
      timeUnit: '1s',
      duration: `${MEASURE_SECONDS}s`,
      preAllocatedVUs: Math.min(MAX_VUS, TARGET_RPS),
      maxVUs: MAX_VUS,
      startTime: `${WARMUP_SECONDS + 5}s`,
      tags: { phase: 'measure' },
    },
  },
  thresholds: thresholds({
    'req_ms{phase:measure,op:resolve}': ['max>=0'],
  }),
  summaryTrendStats: TREND_STATS,
};

export function setup() {
  return discover();
}

export function open(data) {
  const path = data.paths[Math.floor(Math.random() * data.paths.length)];
  const region = data.regions[Math.floor(Math.random() * data.regions.length)];
  const res = http.get(
    `${API}/routing/resolve?path=${encodeURIComponent(path)}&client_region=${region}`,
    { tags: { op: 'resolve' } },
  );
  record(res, { op: 'resolve' });
}

export function handleSummary(data) {
  const dropped = data.metrics.dropped_iterations;
  return emit(data, 'E-open-model', {
    measure_seconds: MEASURE_SECONDS,
    target_rps: TARGET_RPS,
    max_vus: MAX_VUS,
    dropped_iterations: dropped && dropped.values ? dropped.values.count : 0,
  });
}
