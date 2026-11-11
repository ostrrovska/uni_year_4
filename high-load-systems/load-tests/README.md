<!-- Lab5 -->
# Load tests

k6 scripts for Lab 5. Three business scenarios, a control pair that isolates the connection
pool, and an open-model twin that measures what the closed model omits.

Measured results: [../docs/lab5-results.md](../docs/lab5-results.md) ·
charts: `http://localhost:8080/lab5-report.html`

```
load-tests/
  lib/config.js            the VU ladder, the warm-up/measure split, the threshold set
  lib/metrics.js           custom trends and the one function every scenario calls per request
  lib/setup.js             one-time discovery of the seeded ids, run in k6's setup()
  lib/summary.js           handleSummary() -> one committed JSON per run
  scenario-a-read.js       read-intensive
  scenario-b-write.js      write-intensive
  scenario-c-workflow.js   complex end-to-end workflow
  probe-pool.js            /health vs /health/ready, and the generator calibration
  arrival-rate.js          open model, for the coordinated-omission comparison
  results/                 raw k6 dumps and intermediate snapshots - git-ignored
```

## Running them

Everything, including the two control experiments and the renderer, in one command:

```powershell
./scripts/lab5_run.ps1                      # the whole matrix, about 70 minutes
./scripts/lab5_run.ps1 -Only scaling        # one phase; every phase is independent
./scripts/lab5_run.ps1 -Only matrix -MeasureSeconds 30
```

One script by hand:

```powershell
k6 run load-tests/scenario-a-read.js -e STAGE=100 -e LABEL=a-warm-100vu
k6 run load-tests/scenario-a-read.js -e RAMP=1 -e LABEL=a-ramp --out csv=load-tests/results/a-ramp.csv
k6 run load-tests/probe-pool.js -e PROBE=lb -e STAGE=200 -e LABEL=calib-lb-200vu
```

| Variable | Default | What it does |
|---|---|---|
| `BASE_URL` | `http://127.0.0.1:8080` | the balancer; no instance port is published |
| `STAGE` | `50` | the VU count of the measured window in a flat run |
| `WARMUP_SECONDS` | `20` | `0` removes the warm-up scenario entirely (the cold-cache arm) |
| `MEASURE_SECONDS` | `60` | the measured window |
| `LABEL` | `run-<n>vu` | names the summary file under `docs/loadtest/lab5/` |
| `CONFIG` | `default` | free-text note of the configuration under test |
| `RAMP` | unset | `1` runs the whole ladder as one continuous ramp |
| `LIVE_STAGES` | unset | `10:15,50:15,100:15` - the short ladder behind the defence page's button |
| `PROBE` | `pair` | `lb` or `health` switch `probe-pool.js` into calibration mode |
| `TARGET_RPS` | `200` | the arrival rate for `arrival-rate.js` |

## Baseline Environment Specification

Pinned by `docker-compose.lab5.yml` so two runs an hour apart are comparable. Until that file
existed no compose file in this repo set a single CPU or memory limit, and every container took
whatever the host had spare at that instant - fine for a functional demo, fatal for a baseline.

| Component | CPUs | Memory | Notes |
|---|---|---|---|
| `postgres` | 2.0 | 1 GiB | `max_connections=100`, `shared_buffers=256MB`, `pg_stat_statements` |
| `api1` `api2` `api3` | 0.75 each | 384 MiB | one uvicorn worker each, so one event loop each |
| `redis` | 0.5 | 320 MiB | `allkeys-lru`, 256 MB maxmemory, no persistence |
| `lb` (nginx) | 0.5 | 128 MiB | one worker; `pools/3-lab5.conf`, round-robin |
| `haproxy` | 0.25 | 128 MiB | idle during Lab 5 |
| `agents` | 0.25 | 256 MiB | **stopped for every measured run** - see determinism below |

The engine is allocated 12 CPUs and 3.75 GB in total. PostgreSQL gets the largest share
deliberately: bottlenecks #1, #2 and #3 in [../docs/bottlenecks.md](../docs/bottlenecks.md) all
live there, and a baseline in which the database happened to have spare capacity would refute
nothing. `api` and `api4` are scaled to zero, because `docker-compose.lab3.yml` adds the named
pool without disabling the base `api` service and a stray fifth container holding a connection
pool is dead weight that varies between runs.

Connection pool: `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=10`, `DB_POOL_TIMEOUT=10s` per instance, so
60 connections against `max_connections=100` at three instances.
`docker-compose.lab5-pool2.yml` drops that to 2+0 for the exhaustion experiment, and
`docker-compose.lab5-nocache.yml` disables the cache for the scale-out and cache-off arms.

### Isolating the load generator

k6 runs **natively on the host and is never containerised**. That is how clause 2.2's isolation
requirement is met: the SUT's share of the machine is fixed by container limits, and the
generator cannot consume any of it. It does still share the host's 12 cores, which is why
`probe-pool.js -e PROBE=lb` is the first thing every matrix measures - a static 200 from nginx
with no application in the path, so the generator's own ceiling is a measured number rather than
an assumption.

## Design decisions

**Three states for the cache, not two.** *Disabled* never pays the Redis round trip; *cold* pays
it and misses. Reporting only disabled-against-warm charges the round-trip cost to the wrong
side of the comparison.

**A warm-up that is excluded, not merely performed.** The warm-up is a separate k6 scenario
tagged `phase:warmup`; every threshold and every reported figure reads the `phase:measure`
sub-metric. A warm-up included in the percentiles is worse than none, because it mixes a cold
SQLAlchemy pool, an empty asyncpg statement cache and an empty Redis into numbers that are
supposed to describe the warm system.

**Thresholds exist to create sub-metrics, not to gate.** k6 only materialises
`req_ms{phase:measure,instance:cdn-api-2}` if something references it, and a threshold is the
only thing that does. So every sub-metric this lab reports is declared as a threshold with a
deliberately trivial bound - at 200 VUs degradation is the finding, not a failure. The
orchestrator treats k6's exit code 99 as information and any other non-zero code as an error.

**Flat runs for the table, one continuous ramp for the curve.** A percentile taken across a ramp
window is computed over several concurrencies at once and describes none of them. The ramp runs
emit `--out csv` and the renderer reduces it to a per-second timeline, because Lab 3's worst
defect was invisible in the aggregate - zero errors, plausible RPS - and obvious second by
second.

**Entity ids come from `setup()`, and are then filtered by probing.** `scripts/seed.py` is
deterministic, so the ids are stable; fetching them costs one request outside the measured
window and keeps the suite correct as the seed set changes. The probe is the part that matters:
two kinds of asset in this database do not resolve - one pinned by a distribution rule to
another region, and one left behind by an earlier demo with no replicas anywhere - and both
answer 503. That is correct behaviour and useless load, and worse than useless because
`proxy.conf` counts a 503 as an upstream failure. The first smoke run found 24 assets where
`seed.py` creates 8.

## Determinism

Three rules the orchestrator enforces. Each is a documented past mistake in this repository
rather than a precaution.

1. **The `agents` service is stopped for every measured run.** It heartbeats all 12 seeded nodes
   every 10 s, which is uncontrolled write load against the tables Scenario B measures and
   pollutes the `pg_stat_database` deltas the cache experiment depends on. The one-shot
   `refresh` service runs immediately before each run instead, so the fleet is fresh for the
   whole window with no concurrent writer.
2. **The cache is off *and asserted off* in the scale-out arm.** `docs/context/10` records a
   four-instance run accidentally executed on the Lab 4 stack in which one cached instance
   (287.9 req/s, 99 % hit ratio) beat four uncached ones (284.0) and the conclusion came out
   backwards. The phase aborts if a single `X-Cache: HIT` appears.
3. **`node_heartbeats` is levelled between phases.** It is append-only and grows all through a
   70-minute matrix, so without this a late run is not measuring the same database as an early
   one. The row count is recorded per run so the report can show the data really was identical.
   `-KeepHistory` opts out.

## What the figures are not

They are measurements of this stack on one laptop, with everything on one machine and the load
generator sharing its cores. The *absolute* throughput would not survive a move to real
hardware. What does travel is the shape: which scenario saturates first, the ratio between p50
and p99 past the knee, the scalability efficiency factor, and the share of p95 attributable to
pool acquisition - all of which are properties of the architecture rather than of the host.
Lab 3 measured 71 % efficiency at three instances with an entirely different instrument on the
same architecture, and Lab 5 lands in the same place.
