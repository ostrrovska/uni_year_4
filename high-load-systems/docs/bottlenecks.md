# Bottleneck Analysis

Six predicted points of degradation, each in the required
**Component / Root Cause / Symptoms** form, with the mitigation and the lab that
delivers it.

These began as *hypotheses formed from the architecture*, not measurements. **Lab 5 has now
settled all six**, and each entry carries a `Measured (Lab 5)` verdict with the figure behind
it; the full workings are in [lab5-results.md](lab5-results.md). Four were confirmed, one was
confirmed with its expected symptom inverted, and one was confirmed in its symptom but not in
the mechanism it blamed — a prediction that turns out wrong being, as promised, a more useful
result than one never tested.

Ordered by expected time-to-failure: #1 and #3 are the two hot paths and will bite first.

---

## 1. Heartbeat ingest — telemetry insert storm

**Component / Operation / Query**
`POST /api/v1/nodes/{id}/heartbeat` → `INSERT INTO node_heartbeats`.
Load is *fleet size ÷ heartbeat interval*: 10 000 nodes at 10 s gives a sustained
**1 000 inserts/second**, before any burst.

**Root Cause**
Write amplification. Every insert writes a heap tuple, a WAL record, and one entry in
`ix_node_heartbeats_node_id_received_at`. The table grows without bound — at 1 000 rows/s
that is ~86 M rows/day — so the index outgrows `shared_buffers` and its upper pages stop
staying cached. Autovacuum, which must also keep the visibility map current, falls behind
a continuous insert stream and the table bloats. Checkpoints triggered by WAL volume
produce periodic I/O stalls.

**Symptoms**
- p99 write latency rises non-linearly while p50 stays flat — the tail is checkpoint and
  buffer-eviction stalls, not average slowness.
- Throughput plateaus while CPU is still available: the system is in I/O wait, not
  compute-bound.
- Disk usage grows faster than row count (bloat); `n_dead_tup` climbs steadily.
- Eventually connection-pool exhaustion, because each request holds its connection longer.

**Already mitigated**
`BIGINT` identity PK instead of UUIDv4, so inserts land on the rightmost B-tree page
instead of scattering across the whole index; exactly one index on the table; append-only,
never updated.

**Measured (Lab 5)** — **confirmed.** Scenario B, `load-tests/scenario-b-write.js`, 17 609
inserts into `node_heartbeats` in one 45 s window. Across the ladder p50 rose 22.3 → 422.0 ms
while p99 rose 147.3 → **5 534.6 ms**, a 13.1x tail against a 1.08x change in throughput
(241.7 → 261.7 req/s): the predicted shape exactly, a tail that grows while the median and the
throughput do not. Throughput plateaued at the *first* rung, 10 VUs, so every additional user
above that was queueing rather than working. What did **not** appear is the predicted I/O
signature — PostgreSQL's CPU never passed 29 % of its allowance and its buffer hit ratio stayed
at 100 %, because 17 609 rows is far too little to outgrow `shared_buffers`. The write
amplification argument is sound but needs a fleet, not a laptop, to bind.

**Next steps** — measured in **Lab 5** (Scenario B), fixed beyond it by monthly
`PARTITION BY RANGE (received_at)` so retention becomes `DROP PARTITION` instead of
`DELETE`; batching or a queue in front of the insert; tuned `autovacuum_vacuum_scale_factor`.

---

## 2. Hot-row update contention on `edge_nodes`

**Component / Operation / Query**
The `UPDATE edge_nodes SET last_heartbeat_at, current_load_percent, ... WHERE id = :id`
inside the same heartbeat transaction.

**Root Cause**
Lock contention plus MVCC churn. Each node's row is updated on every one of its own
heartbeats, and PostgreSQL implements `UPDATE` as insert-new-tuple plus mark-old-dead. A
row updated every 10 seconds produces 8 640 dead tuples per day. Retries or a
misconfigured agent sending faster than the interval serialise on the row lock, since
concurrent updates to the same row must queue. Worse, `ix_edge_nodes_status_last_heartbeat_at`
covers two of the mutated columns, so every update also writes the index.

**Symptoms**
- Lock waits visible in `pg_stat_activity` as `Lock | transactionid`.
- Heartbeat p99 degrades sharply for a *subset* of nodes — the busy ones — while the
  median is unaffected.
- Table bloat on a table that never grows in row count, with the fleet-wide read path
  (routing) slowing down as a side effect of scanning bloated pages.
- Rising `n_dead_tup` on `edge_nodes` with no corresponding row growth.

**Already mitigated**
One update per heartbeat inside a single transaction; no read-modify-write spanning
requests; no `SELECT ... FOR UPDATE` on this path.

**Measured (Lab 5)** — **confirmed, and the sharpest result in the lab.** Over one Scenario B
run `pg_stat_user_tables` recorded 17 609 updates to `edge_nodes` of which **0.0 % were HOT**,
leaving 2 994 dead tuples on a table whose row count never changed. Every single heartbeat
therefore rewrote `ix_edge_nodes_status_last_heartbeat_at`, which is precisely the index write
this entry names. The `fillfactor` change under *Next steps* is no longer a guess: it has a
measured 0 % HOT rate to improve on.

**Next steps** — quantified in **Lab 5**: lower `fillfactor` on `edge_nodes` to make HOT
updates likely (they avoid the index write entirely); more aggressive per-table autovacuum;
if it still binds, move the volatile columns to a narrow side table so the indexed columns
stop being rewritten.

---

## 3. Route resolution — uncached multi-table join on the read path

**Component / Operation / Query**
`GET /api/v1/routing/resolve` → the ranked candidate query:
`edge_nodes JOIN regions LEFT JOIN asset_replicas`, filtered on status, heartbeat
freshness, load and the distribution-rule subquery, then `ORDER BY score LIMIT n`.

**Root Cause**
Highest-frequency read in the system, and every call recomputes the same answer from the
same slowly-changing data. The `ORDER BY` is over a computed expression, so it cannot be
served directly from an index — PostgreSQL must evaluate the score for every eligible row
and sort. As the fleet grows, the eligible set grows with it, and this cost is paid per
client request rather than per change in the underlying data.

**Symptoms**
- Database CPU saturates before any application instance does — the classic signature of
  "scaling the wrong tier".
- Adding API instances (Lab 3) increases throughput sub-linearly, then not at all.
- p95/p99 latency degrade under concurrency while p50 looks acceptable, because sorts
  queue behind one another.
- `pg_stat_statements` shows this single query dominating total execution time.

**Already mitigated**
Ranking and truncation happen inside PostgreSQL, so the fleet is never materialised in
application memory and never sorted in Python. Query count is constant (2–3) regardless of
fleet size — there is no N+1. `(region_id, status)` and `(status, last_heartbeat_at)` keep
the eligible set index-selected rather than sequentially scanned.

**Measured (Lab 5)** — **confirmed, fixed by Lab 4, and the fix moved the bottleneck.**
Disabling the cache and running the identical 100 VU load cost 1 368.6 rows read from
PostgreSQL per request against 26.6 warm — a **98.1 % reduction** — for 200.7 req/s against
585.8, so caching the join is worth **2.92x the throughput**. But the expected *symptom*,
"database CPU saturates before any application instance does", is now **inverted**: at the top
of the ladder each API instance sits at **90 % of its own CPU allowance** while PostgreSQL never
passes **29 %** of its. With the join gone from the hot path, what remains is request parsing,
validation and JSON serialisation — CPU spent in Python, on the API tier. The prediction was
right about the uncached system and is wrong about the one that now exists, which is the normal
result of fixing a bottleneck and the reason a baseline is re-measured rather than inherited.

**Next steps** — this is the **Lab 4** headline target. Read/write ratio is heavily skewed
(routes are read per download; the underlying fleet state changes per heartbeat and per
release), and a few seconds of staleness is acceptable because the fallback — being sent to
a slightly sub-optimal node — is harmless. Cache-aside on Redis with the key
`cdn:v1:route:{path}:{params_hash}` and a TTL bounded by the asset's `cache_ttl_seconds`,
invalidated on version publish, purge and node status change. The seam is already in the
code: `CacheBackend`, `cache_key()` and the `X-Cache` header.

---

## 4. Connection pool exhaustion

**Component / Operation / Query**
The SQLAlchemy async pool in every API instance — `DB_POOL_SIZE` + `DB_MAX_OVERFLOW`,
against PostgreSQL's `max_connections`.

**Root Cause**
Arithmetic that only becomes visible after horizontal scaling. Each instance opens up to
`pool_size + max_overflow` = 20 connections; PostgreSQL defaults to `max_connections = 100`
and each backend costs several MB of RAM. Three instances is 60 connections — fine. Eight
instances is 160, and the database starts refusing connections. Below that ceiling there is
a second effect: once every pooled connection is busy, requests queue for
`DB_POOL_TIMEOUT` seconds *before* doing any work, so latency rises with no matching rise
in database load. The async runtime makes this easy to miss — the event loop happily
accepts thousands of concurrent requests that then all block on the same 20 connections.

**Symptoms**
- `TimeoutError: QueuePool limit ... reached` in logs, surfacing to clients as 500s or 503s.
- Latency rises while database CPU *falls* — the giveaway that the wait is in the pool, not
  in the query.
- `FATAL: sorry, too many clients already` once the server-side ceiling is hit.
- Throughput flat under increasing VUs, error rate climbing — the textbook saturation knee.

**Already mitigated**
Pool parameters are environment variables, not constants, so the product
`(pool_size + max_overflow) x instances` can be tuned without a rebuild. `pool_pre_ping`
discards connections broken by a database restart instead of handing them to a request —
verified: the API recovered automatically from `docker compose restart postgres`.

**Measured (Lab 5)** — **confirmed, and this is the primary bottleneck of the shipped
configuration.** `load-tests/probe-pool.js` alternates `/health` against `/health/ready`, which
differ by exactly one pooled `SELECT 1`, so their p95 difference is pool-acquire wait with
everything else subtracted out. On the shipped 10+10 pool that difference grew 19.1 → **1 384.5
ms** between 10 and 200 VUs, while `/health` — which never touches the pool — stayed flat at
33.2 → 88.2 ms. On a 2+0 pool it reached 1 758.5 ms. The predicted exception appeared verbatim
in the instance logs at saturation:
`QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 10.00`,
surfacing to clients as the 14 HTTP 500s in Scenario B and 44 in Scenario C at 200 VUs. The
predicted giveaway held too — latency rose in the pooled path while database CPU *fell*.
`max_connections` was never approached: 31 connections at three instances against a ceiling of
100, so the wall is the per-instance pool, not the server.

**Next steps** — **Lab 3** raises the question when the instance count goes up; **Lab 5**
measures the knee and derives the correct per-instance pool size. Beyond that, PgBouncer in
transaction mode decouples instance count from server connection count entirely.

---

## 5. Synchronous purge fan-out inside the HTTP request

**Component / Operation / Query**
`POST /api/v1/purges` and `POST /api/v1/assets/{id}/versions` → `_resolve_target_node_ids`,
which enumerates every targeted node inside the request that triggered it.

**Root Cause**
Work proportional to fleet size executed in a request that should be O(1). A global purge
across 10 000 nodes scans the whole fleet; an asset purge scans every replica of that asset.
Both run inside the caller's transaction, holding a connection and — because the version
publish path takes `SELECT ... FOR UPDATE` on the asset — holding a row lock for the whole
duration. In an async runtime the damage spreads: a long-running await inside one request
delays every other request sharing that event loop, so a single large purge degrades
unrelated endpoints on the same instance.

**Symptoms**
- Request timeouts on release, precisely when a CI pipeline is waiting on the response.
- Head-of-line blocking: unrelated endpoints on the same instance slow down for the
  duration, visible as a synchronised latency spike across all paths served by that
  instance.
- Lock waits on `assets` for any concurrent publish of the same asset.
- Load-test error rate spiking in Scenario C while Scenarios A and B look healthy.

**Already mitigated**
Target resolution is a single `SELECT` returning ids, not a per-node round trip. Offline
nodes are excluded, so the target set is as small as correctness allows. The whole
operation is one transaction, so a failure leaves no half-invalidated state.

**Measured (Lab 5)** — **not confirmed at this scale, and the errors that looked like it were
the measurement.** Scenario C does error more than the others, but neither kind of error is the
fan-out. The 503s came from the harness: `lab5_run.ps1` stops the `agents` service so its
heartbeats are not uncontrolled write load, nothing then refreshes `edge_nodes.last_heartbeat_at`,
and the fleet ages past the 120 s staleness cutoff *while the run is in progress*. Proven
directly — with the last heartbeat 119 s back the resolve answers 200, at 121 s it answers 503,
and with `HEARTBEAT_STALE_AFTER_SECONDS` raised the same 25 VU run produced **zero** errors
instead of 175. The 500s are pool timeouts, which is entry #4 above. The predicted O(fleet) work
is real and measurable — 22 345 `asset_replicas` updates for 1 949 publishes, **11.5 rows
rewritten inside each request**, and the asset `SELECT … FOR UPDATE` was the largest single
statement in the run at 15.6 ms mean under contention — it is simply cheap at a 12-node fleet.
The prediction is about 10 000 nodes and remains untested rather than wrong.

**Next steps** — a **later lab**: the API records the purge intent and returns 202
immediately, a broker (RabbitMQ/Kafka) carries the fan-out, and workers materialise targets
and dispatch. The API contract already anticipates this — `POST /purges` returns **202
Accepted**, not 201, precisely because completion is asynchronous.

---

## 6. Unbounded result sets and missing indexes on new access paths

**Component / Operation / Query**
Collection endpoints: `GET /nodes`, `GET /assets`, `GET /purges`, plus
`GET /stats/network`.

**Root Cause**
Two related failure modes. First, an unbounded list endpoint against a large table
serialises the whole table into memory — one request can exhaust an instance. Second, the
`COUNT(*)` accompanying each paginated response is itself a full scan in PostgreSQL, and
deep `OFFSET` pagination degrades linearly because the database must walk and discard every
skipped row. `GET /stats/network` is worse by construction: four grouped aggregates over
the fleet and replica tables, none of which can use an index to avoid reading the rows.

**Symptoms**
- Memory spikes and OOM-killed containers on a single large request.
- Sequential scans in `EXPLAIN` on tables that have indexes, because the filter column is
  not among them.
- Page 1 fast, page 500 slow — the signature of `OFFSET` pagination.
- `/stats/network` latency growing linearly with fleet size while every other endpoint
  stays flat.

**Already mitigated**
Pagination is mandatory, not optional: `page_params` caps `limit` at 200 as a hard ceiling
the caller cannot raise, and every collection endpoint uses it. Filters are restricted to
indexed columns. Routing returns at most `ROUTING_MAX_CANDIDATES` rows.

**Measured (Lab 5)** — **confirmed for the unbounded list, refuted for the aggregate.** In one
200 VU Scenario A run, measured side by side in the same window: the paginated catalogue read
`GET /assets` was the **slowest** operation in the scenario at p50 468.0 ms / p99 2 102.8 ms —
slower than `/routing/resolve` at p50 300.3 ms despite being by far the simpler query, because
its mandatory `COUNT(*)` is a full scan. `GET /stats/network`, six grouped aggregates and by
construction the heaviest read in the system, was the **fastest** at p50 293.4 ms. Lab 4 caches
one and not the other, and that is the entire difference. The "grows with fleet size" half of
this entry is untested: the fleet is 12 nodes and fixed.

**Next steps** — `/stats/network` is the second **Lab 4** caching target: expensive,
read-often, and tolerant of seconds-old data. If deep pagination becomes real, keyset
pagination (`WHERE id > :last_seen`) replaces `OFFSET`, and the exact `COUNT(*)` gives way
to an estimate from `pg_class.reltuples`.

---

## Summary

| # | Component | Root cause | Verdict after Lab 5 | The number |
|---|---|---|---|---|
| 1 | `node_heartbeats` insert storm | WAL + index write amplification | **confirmed** (tail only) | p99 147 -> 5 535 ms for 1.08x the throughput |
| 2 | `edge_nodes` hot-row update | Row lock contention, MVCC churn | **confirmed** | **0.0 %** of 17 609 updates were HOT |
| 3 | `/routing/resolve` join | Uncached recomputation | **confirmed, fixed, symptom inverted** | -98.1 % rows read; API tier now 90 % busy vs PG 29 % |
| 4 | Connection pool | `(pool + overflow) x instances` | **confirmed - the primary bottleneck** | 1 384 ms of p95 attributable to pool acquire at 200 VUs |
| 5 | Synchronous purge fan-out | O(fleet) work inside one request | **symptom confirmed, mechanism not the cause** | 11.5 replica rows per publish, but the errors were stale replicas and pool timeouts |
| 6 | Unbounded reads / aggregates | Full scans, `COUNT(*)` | **confirmed for the list, refuted for the aggregate** | catalogue p50 468 ms, cached `/stats/network` p50 293 ms |

A seventh, which no entry predicted and which is the most actionable of the set: **nginx's
passive health check ejects healthy backends when the application answers 503**, because
`proxy.conf` lists `http_503` in `proxy_next_upstream` while `pools/3.conf` ejects a peer after
three failures in five seconds. The first Lab 5 run returned **20 831 of 20 866 responses as
HTTP 502 in 0.000 s at only 10 VUs**, and no application latency was sampled at all. An
application-level 503 means *this request cannot be served now*; a connection reset means *this
backend is dead*. Sharing one failure counter between them turns a partial, recoverable overload
into a total outage, and does it fastest exactly when the system is already under stress.

## What was done about all this

| # | Fix | State |
|---|---|---|
| 2 | `fillfactor=70` and tighter autovacuum on `edge_nodes`, so HOT updates become possible | migration `8e41b7c90d52` ships, **not applied** |
| 4 | `release_connection()` — hand the pooled connection back before the response is serialised | ships behind `DB_RELEASE_EARLY`, **off by default** |
| 5 | `HEARTBEAT_STALE_AFTER_SECONDS` raised for load runs, so the fleet cannot age out mid-measurement | in `docker-compose.lab5.yml`, **at the stack default** |
| 7 | `http_503` removed from `proxy_next_upstream`, so an application 503 no longer ejects a peer | **applied**, verified with 200 consecutive legitimate 503s and zero 502s |
| — | balancer healthcheck uses `127.0.0.1` rather than `localhost`, which resolved to `::1` | **applied**, the container now reports healthy |

The first three are deliberately not defaults. Every row of the Lab 5 matrix was measured on one
configuration, and enabling a fix changes the system the baseline describes — so they ship as a
migration and two switches, each one command away from being turned on and re-measured.

**The through-line:** the write path is limited by *physics* — every heartbeat must
eventually reach disk, so it can only be made cheaper, never free. The read path is limited
by *repetition* — the same answer recomputed for every client — so it can be made nearly
free with a cache. That asymmetry is why Lab 4 targets reads and Lab 5 measures writes.
