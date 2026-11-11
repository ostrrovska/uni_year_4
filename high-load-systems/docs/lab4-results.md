<!-- Lab4 -->
# Lab 4 — raw measurements

Produced by `scripts/lab4_experiments.ps1` and rendered by
`python -m scripts.render_lab4_results`.

> **Note on provenance.** The raw JSON under `docs/loadtest/` was lost when the working tree
> was reset (the Lab 3/4 work had not been committed). The figures below are the recorded
> results of those runs, preserved in `docs/context/11-lab4-caching.md` and
> `docs/context/12-defence-lab3-lab4.md`. Re-run `./scripts/lab4_experiments.ps1` to regenerate
> the JSON and this file from a live stack — the numbers will differ slightly, because they
> describe the machine that produced them.

## Environment

| | |
|---|---|
| Host | Windows 10, Docker Desktop 29.7.2 |
| Stack | 3 API instances behind nginx `:8080`, Redis 7-alpine, PostgreSQL 16 |
| Cache | `allkeys-lru`, 256 MB, no persistence; route TTL 10 s, stats TTL 30 s |
| Endpoint | `GET /api/v1/routing/resolve?path=/static/app.bundle.js&client_region=eu-central` |

## C1 — cold vs hot, one request each

A flushed cache, one request, then twenty more. Server-side timing from the
`X-Response-Time-ms` header, so it excludes the client and the balancer.

| | Outcome | Server time | Served by |
|---|---|---|---|
| Cold (first request) | `MISS` | **109.11 ms** | one instance |
| Hot (mean of 20) | `HIT` | **2.20 ms** | **all three instances** |

**≈ 50× faster on a hit.** The third column is the point of the lab: the entry was stored by one
instance and served by the others, which is what makes the cache *distributed* rather than
per-process.

## C2 — sustained load, cache off vs on

Same 64 virtual users, same endpoint, 30 s each. The only difference is `CACHE_ENABLED`.

| Run | RPS | p50 ms | p99 ms | Hit ratio | Errors |
|---|---|---|---|---|---|
| `c2-cache-off` | 240.7 | 224.6 | 708 | — | 0 |
| `c2-cache-on` | **346.3** | **98.1** | 911 | 99.9 % | 0 |

+43.9 % throughput, 2.3× lower median. The p99 rose because the same 64 users now push 44 % more
requests through the same three single-worker instances — the tail is measured at a higher load
point, not made worse.

PostgreSQL's own counters over each run — the measure of the database actually being offloaded,
rather than of the API merely looking faster. Rows returned rather than transactions committed:
a read-only transaction is rolled back when its session closes, so `xact_commit` mostly counts
the agent simulator's heartbeats and says nothing about the read path.

| | Rows returned per request | PostgreSQL CPU |
|---|---|---|
| Cache off | **798** | 43.9 % |
| Cache on | **4.1** | **6.5 %** |

**99.5 % fewer rows read per request**, database CPU down 6.7×.

## C4 — invalidation after a mutation

Asserted by the experiment script, not eyeballed: it fails if the read after the publish is
anything other than a `MISS`, or if it does not carry the new version.

| Step | `X-Cache` | Version |
|---|---|---|
| 1. resolve | `MISS` | v1 |
| 2. resolve again | `HIT` | v1 |
| 3. `POST /assets/{id}/versions` | — | — |
| 4. resolve | **`MISS`** | **v2** |
| 5. resolve again | `HIT` | v2 |

## C5 — graceful degradation when Redis stops

`docker compose stop redis` with traffic flowing.

| | Value |
|---|---|
| Time until every instance reported `BYPASS` | **824 ms** |
| HTTP statuses while Redis was down | 200, all of them |
| Errors during a 15 s load run with Redis down | **0** |
| Throughput with Redis down | 226 req/s (the uncached baseline) |
| First read after Redis returned | `MISS` |
| Next read | `HIT` |

Not a single failed request. The circuit breaker is what makes this *graceful* rather than
merely survivable: without it every request would pay the socket timeout, so the fallback would
be functional but an order of magnitude slower.

## C6 — TTL trade-off

A longer TTL buys hit ratio and spends freshness. The shipped value is 10 s because that is one
heartbeat interval, not because of what this table says — but the table makes the cost of the
choice explicit.

| Route TTL | Hit ratio | Worst-case staleness of the fleet view |
|---|---|---|
| 10 s | 99.8 % | up to 10 s |
| 60 s | 100.0 % | up to 60 s |

Six times the TTL buys 0.2 percentage points, so the short TTL costs nothing.

## C7 — stampede on a cold key

64 virtual users against one freshly flushed key.

| | Value |
|---|---|
| Concurrency | 64 |
| MISS | **3** — one per instance |
| Hit ratio | 99.9 % |

The herd is bounded here by a 10 s TTL and a ~2 ms loader, so it is measured and accepted rather
than mitigated — see the README for the condition under which a single-flight lock would earn
its place.
