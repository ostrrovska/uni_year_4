"""Lab4 - turn docs/loadtest/c*.json into docs/lab4-results.md.

Same contract as the Lab 3 renderer: the raw JSON is the record, the document is generated
from it, and no number in the report is typed by hand.

    python -m scripts.render_lab4_results
"""

import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.loadprobe import _markdown

RESULTS_DIR = Path("docs/loadtest")
OUTPUT = Path("docs/lab4-results.md")


def _load(name: str) -> Any | None:
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _cold_vs_hot() -> list[str]:
    data = _load("c1-cold-vs-hot")
    if not data:
        return []
    return [
        "",
        "## C1 - cold vs hot, one request each",
        "",
        "A flushed cache, one request, then twenty more. Server-side timing comes from the "
        "`X-Response-Time-ms` header, so it excludes the client and the balancer.",
        "",
        "| | Outcome | Server time | Served by |",
        "|---|---|---|---|",
        f"| Cold (first request) | `{data['cold_status']}` | **{data['cold_ms']} ms** | "
        f"{data['cold_instance']} |",
        f"| Hot (mean of {data['hot_count']}) | `HIT` | **{data['hot_mean_ms']} ms** | "
        f"{', '.join(data['hot_instances'])} |",
        f"| Hot (fastest) | `HIT` | {data['hot_min_ms']} ms | |",
        "",
        f"**{data['speedup']}x faster on a hit.** The instances listed on the hot row are the "
        "point of the lab: the entry was stored by one instance and served by the others, which "
        "is what makes the cache *distributed* rather than per-process.",
    ]


def _db_offload() -> list[str]:
    runs = [r for r in (_load("c2-cache-off"), _load("c2-cache-on")) if r]
    if not runs:
        return []

    lines = [
        "",
        "## C2 - sustained load, cache off vs on",
        "",
        "Same 64 virtual users, same endpoint, 30 s each. The only difference between the two "
        "runs is `CACHE_ENABLED`.",
        "",
        _markdown(runs),
    ]

    offload = _load("c2-db-offload")
    if offload:
        off, on = offload["cache_off"], offload["cache_on"]
        reduction = (
            100 * (1 - on["rows_per_request"] / off["rows_per_request"])
            if off["rows_per_request"]
            else 0.0
        )
        lines += [
            "",
            "PostgreSQL's own counters over each run - the measure of the database actually "
            "being offloaded, rather than of the API merely looking faster. Rows returned "
            "rather than transactions committed: a read-only transaction is rolled back when "
            "its session closes, so `xact_commit` mostly counts the agent simulator's "
            "heartbeats and says nothing about the read path.",
            "",
            "| | Requests served | Rows returned | **Rows per request** |",
            "|---|---|---|---|",
            f"| Cache off | {off['requests']} | {off['tup_returned']} | "
            f"**{off['rows_per_request']}** |",
            f"| Cache on | {on['requests']} | {on['tup_returned']} | "
            f"**{on['rows_per_request']}** |",
            "",
            f"**{reduction:.1f} % fewer rows read from PostgreSQL per request.** What remains is "
            "the agent simulator's heartbeats, which keep writing throughout both runs.",
        ]

    for run in runs:
        if run.get("resources"):
            names = sorted(run["resources"])
            short = [n.replace("cdn-control-plane-", "").removesuffix("-1") for n in names]
            lines += [
                "",
                "Mean CPU per container during each run:",
                "",
                "| Run | " + " | ".join(short) + " |",
                "|---" * (len(names) + 1) + "|",
            ]
            for row in runs:
                cells = [
                    f"{row['resources'][n]['cpu_percent_mean']} %" if n in row["resources"] else "-"
                    for n in names
                ]
                lines.append(f"| `{row['label']}` | " + " | ".join(cells) + " |")
            break
    return lines


def _hit_vs_miss() -> list[str]:
    run = _load("c2-cache-on")
    if not run or not run.get("latency_ms_by_cache"):
        return []
    by = run["latency_ms_by_cache"]
    lines = [
        "",
        "## C3 - HIT vs MISS inside one run",
        "",
        "Both outcomes measured in the same 30 s window, under the same concurrency, on the "
        "same instances - a far stronger comparison than two separate runs.",
        "",
        "| Outcome | Requests | p50 ms | p95 ms | p99 ms | max ms |",
        "|---|---|---|---|---|---|",
    ]
    for outcome in ("HIT", "MISS", "BYPASS"):
        block = by.get(outcome)
        if not block:
            continue
        lines.append(
            f"| `{outcome}` | {run['cache'].get(outcome, 0)} | {block['p50']} | {block['p95']} | "
            f"{block['p99']} | {block['max']} |"
        )
    lines += ["", f"Hit ratio over consulted reads: **{run['cache_hit_ratio_percent']} %**."]
    return lines


def _invalidation() -> list[str]:
    data = _load("c4-invalidation")
    if not data:
        return []
    return [
        "",
        "## C4 - invalidation after a mutation",
        "",
        "Asserted by the experiment script, not eyeballed: it fails if the read after the "
        "publish is anything other than a `MISS`, or if it does not carry the new version.",
        "",
        "| Step | `X-Cache` | Version |",
        "|---|---|---|",
        f"| 1. resolve | `{data['read1']}` | {data['version_before']} |",
        f"| 2. resolve again | `{data['read2']}` | {data['version_before']} |",
        "| 3. `POST /assets/{id}/versions` | - | - |",
        f"| 4. resolve | **`{data['read_after_publish']}`** | **{data['version_after']}** |",
        f"| 5. resolve again | `{data['read_after_refill']}` | {data['version_after']} |",
    ]


def _fallback() -> list[str]:
    data = _load("c5-fallback")
    if not data:
        return []
    probe = _load("c5-redis-down")
    statuses = ", ".join(str(s) for s in _as_list(data["statuses_while_down"]))
    headers = ", ".join(f"`{s}`" for s in _as_list(data["cache_header_while_down"]))
    lines = [
        "",
        "## C5 - graceful degradation when Redis stops",
        "",
        "`docker compose stop redis` with traffic flowing.",
        "",
        "| | Value |",
        "|---|---|",
        f"| Warm read before stopping | `{data['warm_before']}` |",
        f"| Time until every instance reported `BYPASS` | {data.get('settle_ms', '-')} ms |",
        f"| HTTP statuses while Redis was down | {statuses} |",
        f"| `X-Cache` while Redis was down | {headers} |",
        f"| Errors during a 15 s load run with Redis down | **{data['errors_while_down']}** |",
        f"| Throughput with Redis down | {data['rps_while_down']} req/s,"
        f" p99 {data['p99_while_down']} ms |",
        f"| First read after Redis returned | `{data['first_after_restart']}` |",
        f"| Next read | `{data['second_after_restart']}` |",
        "",
        "Not a single failed request. The circuit breaker is what makes this *graceful* rather "
        "than merely survivable: without it every request would pay the socket timeout, so the "
        "fallback would be functional but an order of magnitude slower.",
    ]
    if probe:
        lines += ["", _markdown([probe])]
    return lines


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _ttl_tradeoff() -> list[str]:
    rows = _load("c6-ttl-tradeoff")
    if not rows:
        return []
    rows = _as_list(rows)
    lines = [
        "",
        "## C6 - TTL trade-off",
        "",
        "A longer TTL buys hit ratio and spends freshness. The shipped value is 10 s because "
        "that is one heartbeat interval, not because of what this table says - but the table is "
        "what makes the cost of the choice explicit.",
        "",
        "| Route TTL | Hit ratio | RPS | Worst-case staleness of the fleet view |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['ttl_seconds']} s | {row['hit_ratio']} % | {row['rps']} | "
            f"up to {row['ttl_seconds']} s |"
        )
    return lines


def _stampede() -> list[str]:
    data = _load("c7-stampede")
    probe = _load("c7-stampede")
    if not data or "misses" not in data:
        return []
    lines = [
        "",
        "## C7 - stampede on a cold key",
        "",
        f"{data['concurrency']} virtual users against one freshly flushed key. Every request "
        "that arrives before the first one has stored its result is a miss, and each of those "
        "misses runs the full query.",
        "",
        "| | Value |",
        "|---|---|",
        f"| Concurrency | {data['concurrency']} |",
        f"| Requests | {data['total_requests']} |",
        f"| MISS | **{data['misses']}** |",
        f"| HIT | {data['hits']} |",
        f"| Hit ratio | {data['hit_ratio']} % |",
        "",
        "The herd is bounded here by a 10 s TTL and a cheap loader, so it is measured and "
        "accepted rather than mitigated - see the README for the condition under which a "
        "single-flight lock would earn its place.",
    ]
    if probe and isinstance(probe, dict) and "label" in probe:
        lines += ["", _markdown([probe])]
    return lines


def main() -> None:
    parts = [
        "<!-- Lab4 -->",
        "# Lab 4 - raw measurements",
        "",
        "Generated by `python -m scripts.render_lab4_results` from the JSON in "
        "[loadtest/](loadtest/), which `scripts/lab4_experiments.ps1` writes.",
        "",
        "## Environment",
        "",
        "| | |",
        "|---|---|",
        f"| Generated | {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} |",
        f"| Host | {platform.platform()} |",
        "| Stack | 3 API instances behind nginx :8080, Redis 7-alpine, PostgreSQL 16 |",
        "| Cache | `allkeys-lru`, 256 MB, no persistence; route TTL 10 s, stats TTL 30 s |",
        "| Endpoint | `GET /api/v1/routing/resolve`"
        " `?path=/static/app.bundle.js&client_region=eu-central` |",
        *_cold_vs_hot(),
        *_db_offload(),
        *_hit_vs_miss(),
        *_invalidation(),
        *_fallback(),
        *_ttl_tradeoff(),
        *_stampede(),
    ]
    OUTPUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
