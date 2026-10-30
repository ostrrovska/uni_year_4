import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { box, counter, green, markdownRow, ms, output, red, runtimeOf, shortNum, trend, dim } from './summary.js';

// One heavy /cpu request starts at t=1s while /health is polled steadily.
// On Node the /health latencies jump to the full duration of the /cpu loop,
// because both share a single event loop. On Go they stay flat.

const BASE_URL = __ENV.BASE_URL || 'http://localhost:3000';
const CPU_PATH = __ENV.CPU_PATH || '/cpu';
const CPU_ITERATIONS = __ENV.CPU_N || '2000000000';

// A healthy probe answers in about a millisecond, so anything past this is the
// probe waiting behind the CPU loop rather than normal jitter.
const SLOW_PROBE_MS = 100;

const healthLatency = new Trend('health_latency_ms', true);
const cpuDuration = new Trend('cpu_duration_ms', true);
const slowProbes = new Counter('health_probes_slow');

export const options = {
  scenarios: {
    health_probe: {
      executor: 'constant-arrival-rate',
      rate: 10,
      timeUnit: '1s',
      duration: '10s',
      preAllocatedVUs: 20,
      exec: 'healthRequest',
    },
    cpu_burst: {
      executor: 'shared-iterations',
      vus: 1,
      iterations: 1,
      startTime: '1s',
      exec: 'cpuRequest',
    },
  },
  // 'count' is not a default stat, but the summary reports how many probes ran.
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max', 'count'],
};

export function cpuRequest() {
  const res = http.get(`${BASE_URL}${CPU_PATH}?n=${CPU_ITERATIONS}`);
  cpuDuration.add(res.timings.duration);
  console.log(`>>> CPU ${CPU_PATH} finished in ${res.timings.duration.toFixed(0)} ms`);
}

export function healthRequest() {
  const res = http.get(`${BASE_URL}/health`);
  healthLatency.add(res.timings.duration);
  if (res.timings.duration > SLOW_PROBE_MS) {
    slowProbes.add(1);
  }
  console.log(`health: ${res.timings.duration.toFixed(0)} ms`);
}

export function handleSummary(data) {
  const runtime = runtimeOf(BASE_URL);
  const health = trend(data, 'health_latency_ms');
  const cpu = trend(data, 'cpu_duration_ms');
  const probes = health.count || 0;
  const slow = counter(data, 'health_probes_slow');

  const blocked = health.max > SLOW_PROBE_MS;
  const verdict = blocked
    ? red(`event loop заблоковано: ${slow} з ${probes} проб чекали, найдовша — ${ms(health.max)} мс`)
    : green(`блокування немає: усі ${probes} проб відповіли швидше за ${SLOW_PROBE_MS} мс`);

  const row = markdownRow([
    runtime,
    `\`${CPU_PATH}\``,
    ms(cpu.max),
    ms(health.avg),
    ms(health['p(95)']),
    ms(health.max),
  ]);

  const table = box(`${runtime}  ·  ${CPU_PATH}  ·  n=${shortNum(CPU_ITERATIONS)}  ·  /health 10/с`, [
    ['Тривалість CPU-запиту, мс', ms(cpu.max)],
    null,
    ['/health avg, мс', ms(health.avg)],
    ['/health med, мс', ms(health.med)],
    ['/health p95, мс', ms(health['p(95)'])],
    ['/health max, мс', ms(health.max)],
    null,
    [`Проб повільніше за ${SLOW_PROBE_MS} мс`, `${slow} з ${probes}`],
  ], [
    verdict,
    '',
    dim('рядок для таблиці 1 у RESULTS.md:'),
    row,
  ]);

  return output(table, data, { kind: 'blocking', runtime, cpuPath: CPU_PATH, iterations: CPU_ITERATIONS, row });
}
