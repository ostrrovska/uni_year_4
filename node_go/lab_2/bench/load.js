import http from 'k6/http';
import { check } from 'k6';
import { box, markdownRow, ms, output, runtimeOf, trend, workloadOf, dim } from './summary.js';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';
const ENDPOINT = __ENV.ENDPOINT || '/io';
const VUS = Number(__ENV.VUS || 50);
const DURATION = __ENV.DURATION || '30s';

export const options = {
  vus: VUS,
  duration: DURATION,
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const res = http.get(`${BASE_URL}${ENDPOINT}`);
  check(res, { 'status is 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  const runtime = runtimeOf(BASE_URL);
  const workload = workloadOf(ENDPOINT);
  const duration = trend(data, 'http_req_duration');
  const reqs = data.metrics.http_reqs ? data.metrics.http_reqs.values : {};
  const failedRate = data.metrics.http_req_failed
    ? data.metrics.http_req_failed.values.rate * 100
    : 0;

  const row = markdownRow([
    workload,
    runtime,
    reqs.rate ? reqs.rate.toFixed(1) : '—',
    ms(duration.avg),
    ms(duration['p(95)']),
    ms(duration['p(99)']),
    '',
    '',
  ]);

  const table = box(`${runtime}  ·  ${ENDPOINT}  ·  ${VUS} VU  ·  ${DURATION}`, [
    ['Запитів усього', String(reqs.count || 0)],
    ['RPS', reqs.rate ? reqs.rate.toFixed(1) : '—'],
    ['Помилок, %', failedRate.toFixed(2)],
    null,
    ['Затримка avg, мс', ms(duration.avg)],
    ['Затримка med, мс', ms(duration.med)],
    ['Затримка p95, мс', ms(duration['p(95)'])],
    ['Затримка p99, мс', ms(duration['p(99)'])],
    ['Затримка max, мс', ms(duration.max)],
  ], [
    dim('рядок для таблиці 2 у RESULTS.md (CPU та RAM — з monitor.ps1):'),
    row,
  ]);

  return output(table, data, { kind: 'load', runtime, workload, endpoint: ENDPOINT, vus: VUS, duration: DURATION, row });
}
