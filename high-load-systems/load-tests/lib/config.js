// Lab5
// Shared configuration for every scenario: the VU ladder, the warm-up/measure split and the
// threshold set that makes the measured sub-metrics exist at all.
//
// The single most important mechanic here is the warm-up split. A run is two k6 scenarios
// against the same code: `warmup` at 5 VUs, then `measure` at the target VU count, started
// after the warm-up has finished and tagged `phase:measure`. Clause 2.3 asks for a warm-up
// phase, and a warm-up that is *included* in the percentiles is worse than none - it mixes a
// cold SQLAlchemy pool, an empty asyncpg statement cache and an empty Redis into the numbers
// that are supposed to describe the warm system.
//
// k6 only materialises a sub-metric such as `http_req_duration{phase:measure}` if something
// references it, and a threshold is the only thing that does. So every sub-metric this lab
// reports is declared as a threshold below - the values are deliberately loose, because at
// 200 VUs degradation is the finding, not a failure. The orchestrator records a failed
// threshold (k6 exit code 99) rather than aborting on it.

import { STATUSES } from './metrics.js';

export const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080';
export const API = `${BASE_URL}/api/v1`;

// The ladder from clause 2.3. A flat run measures exactly one rung.
export const LADDER = [10, 25, 50, 100, 200];

export const STAGE = Number(__ENV.STAGE || 50);
export const WARMUP_VUS = Number(__ENV.WARMUP_VUS || 5);
export const WARMUP_SECONDS = Number(__ENV.WARMUP_SECONDS || 20);
export const MEASURE_SECONDS = Number(__ENV.MEASURE_SECONDS || 60);

// Named by the orchestrator so one summary file per (scenario, configuration, rung) lands in
// docs/loadtest/lab5/ without the renderer having to guess what a file holds.
export const LABEL = __ENV.LABEL || `run-${STAGE}vu`;
export const CONFIG = __ENV.CONFIG || 'default';
export const LIVE_STAGES = __ENV.LIVE_STAGES || '';
export const SUMMARY_DIR = __ENV.SUMMARY_DIR || 'docs/loadtest/lab5';

// Instance ids are fixed by docker-compose.lab3.yml. Enumerated rather than discovered because
// a per-instance sub-metric needs a threshold declared up front, before any response is seen.
export const INSTANCES = ['cdn-api-1', 'cdn-api-2', 'cdn-api-3', 'cdn-api-4'];
export const CACHE_OUTCOMES = ['HIT', 'MISS', 'BYPASS'];

export const TREND_STATS = ['count', 'min', 'avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'];

// A closed-loop user with no think time: this lab measures the system's ceiling, and a sleep
// between iterations would measure the ladder's arrival rate instead. Clause 2.6's comparisons
// only mean something if every run shares this choice.
export function flatScenarios(exec) {
  const measure = {
    executor: 'constant-vus',
    exec,
    vus: STAGE,
    duration: `${MEASURE_SECONDS}s`,
    // +5s so the warm-up's graceful stop cannot overlap the measured window.
    startTime: WARMUP_SECONDS ? `${WARMUP_SECONDS + 5}s` : '0s',
    tags: { phase: 'measure' },
    gracefulStop: '10s',
  };
  // WARMUP_SECONDS=0 drops the warm-up scenario rather than declaring a zero-length one, which
  // k6 rejects. Used by exactly one run: the cold-cache arm, where warming up would destroy
  // the condition being measured.
  if (!WARMUP_SECONDS) {
    return { measure };
  }
  return {
    measure,
    warmup: {
      executor: 'constant-vus',
      exec,
      vus: WARMUP_VUS,
      duration: `${WARMUP_SECONDS}s`,
      startTime: '0s',
      tags: { phase: 'warmup' },
      gracefulStop: '5s',
    },
  };
}

// The continuous ramp from clause 2.3, for the saturation *curve*. The flat runs above produce
// the table: a percentile taken across a ramp window averages several concurrencies together
// and is not a measurement of any of them.
export function rampScenarios(exec) {
  const stages = [{ duration: `${WARMUP_SECONDS}s`, target: WARMUP_VUS }];
  for (const target of LADDER) {
    stages.push({ duration: '10s', target });
    stages.push({ duration: `${MEASURE_SECONDS}s`, target });
  }
  stages.push({ duration: '10s', target: 0 });
  return {
    ramp: {
      executor: 'ramping-vus',
      exec,
      startVUs: WARMUP_VUS,
      stages,
      tags: { phase: 'measure' },
      gracefulRampDown: '10s',
    },
  };
}

// Lab5 - the live defence run only. LIVE_STAGES="10:15,50:15,100:15" builds a short ladder
// from an explicit list, so scripts/lab5_live.py can drive a ~55 s staircase through the same
// scenario file that produced the graded numbers. Without it the live button would either run
// one flat rung (not a ramp, so not a demonstration of clause 2.3) or the full five-rung ladder
// at 60 s a step, which nobody is going to watch during a defence.
export function stagedScenarios(exec, spec) {
  const stages = [];
  for (const chunk of spec.split(',')) {
    const [vus, seconds] = chunk.split(':').map(Number);
    if (!vus || !seconds) {
      continue;
    }
    // A 2 s approach to each level rather than a step: a vertical jump in a ramping-vus stage
    // list makes k6 start every new VU in the same instant, and the connection storm that
    // follows shows up as a latency spike that belongs to the generator, not the system.
    stages.push({ duration: '2s', target: vus });
    stages.push({ duration: `${seconds}s`, target: vus });
  }
  stages.push({ duration: '2s', target: 0 });
  return {
    measure: {
      executor: 'ramping-vus',
      exec,
      startVUs: 1,
      stages,
      tags: { phase: 'measure' },
      gracefulRampDown: '3s',
    },
  };
}

// Declared so the sub-metrics exist in the summary. Loose on purpose - see the header.
export function thresholds(extra = {}) {
  const base = {
    'http_req_duration{phase:measure}': ['max>=0'],
    'http_req_failed{phase:measure}': ['rate<=1'],
    'http_reqs{phase:measure}': ['count>=0'],
    'iteration_duration{phase:measure}': ['max>=0'],
    'req_ms{phase:measure}': ['max>=0'],
    'srv_ms{phase:measure}': ['max>=0'],
    'req_failed{phase:measure}': ['rate<=1'],
  };
  for (const id of INSTANCES) {
    base[`req_ms{phase:measure,instance:${id}}`] = ['max>=0'];
  }
  for (const outcome of CACHE_OUTCOMES) {
    base[`req_ms{phase:measure,cache:${outcome}}`] = ['max>=0'];
    base[`srv_ms{phase:measure,cache:${outcome}}`] = ['max>=0'];
  }
  for (const status of STATUSES) {
    base[`http_status{phase:measure,status:${status}}`] = ['count>=0'];
  }
  return Object.assign(base, extra);
}
