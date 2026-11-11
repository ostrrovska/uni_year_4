// Lab5
// handleSummary(): turns one k6 run into one committed JSON summary.
//
// The contract is the repo's existing one, stated in scripts/render_lab4_results.py: the raw
// JSON is the record, the document is generated from it, and no number in the report is typed
// by hand. So this file is the only place a measured value is ever shaped, and the renderer
// downstream is not allowed to compute anything the instrument could have reported.
//
// Everything below reads the {phase:measure} sub-metrics only. The warm-up requests are in the
// run and in the raw dump, but they are not in the numbers.

import { CONFIG, LABEL, MEASURE_SECONDS, STAGE, SUMMARY_DIR, BASE_URL } from './config.js';

function trend(metrics, name) {
  const metric = metrics[name];
  if (!metric || !metric.values) {
    return null;
  }
  const v = metric.values;
  const block = {
    count: v.count === undefined ? null : v.count,
    min: round(v.min),
    mean: round(v.avg),
    p50: round(v.med),
    p90: round(v['p(90)']),
    p95: round(v['p(95)']),
    p99: round(v['p(99)']),
    max: round(v.max),
  };
  return block.count === 0 ? null : block;
}

function round(value) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return null;
  }
  return Math.round(value * 100) / 100;
}

function counter(metrics, name) {
  const metric = metrics[name];
  return metric && metric.values ? metric.values.count : 0;
}

// Sub-metric names are the metric plus a sorted tag set in braces, so they can be picked out of
// data.metrics by prefix rather than reconstructed - which keeps this working if k6 changes how
// it orders the tags.
function byTag(metrics, metric, tag, phase = 'phase:measure') {
  const out = {};
  const prefix = `${metric}{`;
  for (const name of Object.keys(metrics)) {
    if (!name.startsWith(prefix) || !name.includes(phase)) {
      continue;
    }
    const inner = name.slice(prefix.length, -1);
    const parts = inner.split(',');
    const hit = parts.find((p) => p.startsWith(`${tag}:`));
    if (!hit || parts.length !== 2) {
      continue;
    }
    const block = trend(metrics, name);
    if (block) {
      out[hit.slice(tag.length + 1)] = block;
    }
  }
  return out;
}

function statusCounts(metrics) {
  const out = {};
  for (const name of Object.keys(metrics)) {
    if (!name.startsWith('http_status{') || !name.includes('phase:measure')) {
      continue;
    }
    const inner = name.slice('http_status{'.length, -1);
    const status = inner.split(',').find((p) => p.startsWith('status:'));
    const count = counter(metrics, name);
    if (status && count > 0) {
      out[status.slice('status:'.length)] = count;
    }
  }
  return out;
}

export function buildSummary(data, scenario, extra = {}) {
  const m = data.metrics;
  const requests = counter(m, 'http_reqs{phase:measure}');
  // A k6 Rate counts its TRUTHY adds in `passes`. req_failed adds `true` on a failure, so
  // `passes` is the error count and `fails` is the success count - the names mean the opposite
  // of what this metric measures. Getting this backwards reported 0.15 % errors on a run where
  // 99.8 % of the responses were 502s, which is how it was found.
  const failedRate = m['req_failed{phase:measure}'];
  const rate = failedRate && failedRate.values ? failedRate.values : {};
  const errors = rate.passes || 0;
  const observed = (rate.passes || 0) + (rate.fails || 0);

  const latency = trend(m, 'req_ms{phase:measure}');
  const byCache = byTag(m, 'req_ms', 'cache');
  const hits = byCache.HIT ? byCache.HIT.count : 0;
  const misses = byCache.MISS ? byCache.MISS.count : 0;
  const consulted = hits + misses;

  const instances = {};
  const latencyByInstance = byTag(m, 'req_ms', 'instance');
  for (const [id, block] of Object.entries(latencyByInstance)) {
    instances[id] = block.count;
  }

  const summary = {
    label: LABEL,
    config: CONFIG,
    scenario,
    stage_vus: STAGE,
    measure_seconds: MEASURE_SECONDS,
    base_url: BASE_URL,
    generated_at: new Date().toISOString(),
    k6_run_duration_ms: data.state ? data.state.testRunDurationMs : null,
    requests,
    errors,
    // Over the observed requests rather than over `requests`: a transport failure never reaches
    // http_reqs, so dividing by http_reqs would understate the error rate exactly when it
    // matters most.
    error_rate_percent: observed ? round((100 * errors) / observed) : 0,
    rps: MEASURE_SECONDS ? round(requests / MEASURE_SECONDS) : null,
    latency_ms: latency,
    // One Scenario C iteration is seven HTTP requests, so a per-request percentile describes
    // the slowest single call rather than the slowest release - which is the number the
    // business cares about and the one the scenario exists to produce. k6 measures it as
    // iteration_duration; the threshold in lib/config.js is what makes the sub-metric exist.
    iteration_ms: trend(m, 'iteration_duration{phase:measure}'),
    server_ms: trend(m, 'srv_ms{phase:measure}'),
    status_counts: statusCounts(m),
    instances,
    instance_share_percent: sharePercent(instances),
    latency_ms_by_instance: latencyByInstance,
    cache: { HIT: hits, MISS: misses, BYPASS: byCache.BYPASS ? byCache.BYPASS.count : 0 },
    cache_hit_ratio_percent: consulted ? round((100 * hits) / consulted) : null,
    latency_ms_by_cache: byCache,
    server_ms_by_cache: byTag(m, 'srv_ms', 'cache'),
    // The per-operation split. For probe-pool.js this is the measurement: the difference
    // between op:ready and op:live is pool-acquire latency with everything else subtracted
    // out. For Scenario C it says which of the five steps in the workflow owns the tail.
    latency_ms_by_op: byTag(m, 'req_ms', 'op'),
    server_ms_by_op: byTag(m, 'srv_ms', 'op'),
    requests_by_op: opCounts(byTag(m, 'req_ms', 'op')),
    thresholds_failed: failedThresholds(m),
  };
  return Object.assign(summary, extra);
}

function opCounts(blocks) {
  const out = {};
  for (const [op, block] of Object.entries(blocks)) {
    out[op] = block.count;
  }
  return out;
}

function sharePercent(counts) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const out = {};
  for (const [id, n] of Object.entries(counts)) {
    out[id] = total ? round((100 * n) / total) : 0;
  }
  return out;
}

function failedThresholds(metrics) {
  const out = [];
  for (const [name, metric] of Object.entries(metrics)) {
    if (!metric.thresholds) {
      continue;
    }
    for (const [expr, result] of Object.entries(metric.thresholds)) {
      if (result && result.ok === false) {
        out.push(`${name} ${expr}`);
      }
    }
  }
  return out;
}

// A short ASCII block on stdout as well as the file: the orchestrator echoes it during a
// 50-minute matrix so a run that went wrong is visible while it is still cheap to stop.
function stdout(summary) {
  const l = summary.latency_ms || {};
  return [
    '',
    `  ${summary.scenario} | ${summary.config} | ${summary.stage_vus} VUs`,
    `  requests ${summary.requests}  rps ${summary.rps}  errors ${summary.errors}` +
      ` (${summary.error_rate_percent} %)`,
    `  p50 ${l.p50} ms  p95 ${l.p95} ms  p99 ${l.p99} ms  max ${l.max} ms`,
    `  cache HIT ${summary.cache.HIT} / MISS ${summary.cache.MISS} / BYPASS ${summary.cache.BYPASS}`,
    `  instances ${JSON.stringify(summary.instance_share_percent)}`,
    '',
  ].join('\n');
}

export function emit(data, scenario, extra = {}) {
  const summary = buildSummary(data, scenario, extra);
  const out = {};
  out[`${SUMMARY_DIR}/${LABEL}.json`] = JSON.stringify(summary, null, 2);
  out.stdout = stdout(summary);
  return out;
}
