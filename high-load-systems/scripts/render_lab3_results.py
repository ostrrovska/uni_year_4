"""Lab3 - turn docs/loadtest/*.json into docs/lab3-results.md.

Keeping the raw JSON and rendering the document from it means no number in the report is
typed by hand, and the whole thing can be regenerated on another machine after re-running
scripts/lab3_experiments.ps1.

    python -m scripts.render_lab3_results
"""

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.loadprobe import _markdown

RESULTS_DIR = Path("docs/loadtest")
OUTPUT = Path("docs/lab3-results.md")

# (heading, prose, label prefixes) - the order the document presents the experiments in.
SECTIONS: list[tuple[str, str, list[str]]] = [
    (
        "E1 - distribution per balancing algorithm",
        "Three identical instances, 32 virtual users, 20 s per algorithm. Round robin and "
        "least connections split the work evenly; weighted reproduces its configured 5:3:1 "
        "ratio exactly; ip hash sends everything to one peer because every request arrives "
        "from the same source address.",
        ["e1-round-robin", "e1-least-conn", "e1-weighted", "e1-ip-hash"],
    ),
    (
        "E2 - asymmetric load: round robin vs least connections",
        "One peer (api2) made slow three different ways, 64 virtual users, 30 s per run. "
        "`spin` burns CPU and blocks the event loop; `sleep` adds latency without consuming "
        "CPU; `cpuquota` gives the container a quarter of a CPU and touches no application "
        "code at all. Instance shares are shares of *completed* responses, so a saturated "
        "peer appears smaller than the third round robin actually dispatches to it.",
        [
            "e2-spin-round-robin",
            "e2-spin-least-conn",
            "e2-cpuquota-round-robin",
            "e2-cpuquota-least-conn",
            "e2-sleep-round-robin",
            "e2-sleep-least-conn",
        ],
    ),
    (
        "E3 - scale-out at 1, 2, 3 and 4 instances",
        "Round robin, 64 virtual users, 30 s per pool size, unused instances stopped. Four "
        "instances is the assignment's 3+ configuration, and the run that tests whether the "
        "three-instance result really did predict saturation at about four.",
        ["e3-pool1", "e3-pool2", "e3-pool3", "e3-pool4"],
    ),
    (
        "E4/E5 - node failure during a run",
        "api2 stopped ~14 s into a 40 s run and started again ~14 s later, through each "
        "balancer in turn.",
        ["e4-nginx-node-failure", "e5-haproxy-node-failure"],
    ),
    (
        "E7 - passive check tolerance under overload",
        "Two instances at 256 virtual users, the load at which a saturated peer starts "
        "resetting queued connections. Two independent trials of each setting.",
        [
            "e7-overload-maxfails1",
            "e7-overload-maxfails3",
            "e7-maxfails-1",
            "e7-maxfails-3",
        ],
    ),
    (
        "E8 - alive but unable to reach the database",
        "api2 pointed at a non-existent database host. Its process keeps listening and "
        "`GET /health` still answers 200, so no passive check can see a problem, while "
        "`GET /health/ready` answers 503.",
        ["e8-nginx-passive-only", "e8-haproxy-active-check"],
    ),
    (
        "E6 - instance recreated (null result)",
        "Docker returned the same address to the recreated container, so nginx's "
        "startup-only DNS resolution was never put to the test. Recorded as the null result "
        "it is.",
        ["e6-nginx-stale-dns", "e6-haproxy-resolvers", "e6-nginx-after-reload"],
    ),
]


def _load(name: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _docker_version() -> str:
    try:
        out = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=15, check=False
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _resource_table(results: list[dict[str, Any]]) -> list[str]:
    rows = [r for r in results if r.get("resources")]
    if not rows:
        return []
    names = sorted({name for r in rows for name in r["resources"]})
    short = [n.replace("cdn-control-plane-", "").removesuffix("-1") for n in names]
    lines = [
        "",
        "Mean CPU per container while the run was in flight (`docker stats`):",
        "",
        "| Run | " + " | ".join(short) + " |",
        "|---" * (len(names) + 1) + "|",
    ]
    for r in rows:
        cells = []
        for name in names:
            entry = r["resources"].get(name)
            cells.append(f"{entry['cpu_percent_mean']} %" if entry else "-")
        lines.append(f"| `{r['label']}` | " + " | ".join(cells) + " |")
    return lines


def _scaling_table() -> list[str]:
    pools = [(n, _load(f"e3-pool{n}")) for n in (1, 2, 3, 4)]
    pools = [(n, r) for n, r in pools if r]
    if not pools:
        return []

    connections = _load("e3-db-connections") or {}
    baseline = pools[0][1]["rps"]
    lines = [
        "",
        "Scaling efficiency and the database connections it costs:",
        "",
        "| Instances | RPS | Speed-up | Efficiency | p50 ms | p99 ms | PG idle | PG peak |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for count, result in pools:
        conn = connections.get(f"pool{count}", {})
        speedup = result["rps"] / baseline
        lines.append(
            f"| {count} | {result['rps']} | {speedup:.2f}x | {100 * speedup / count:.0f} % | "
            f"{result['latency_ms']['p50']} | {result['latency_ms']['p99']} | "
            f"{conn.get('idle', '-')} | {conn.get('peak', '-')} |"
        )
    return lines


def _failure_timelines() -> list[str]:
    lines: list[str] = []
    for name in ("e4-nginx-node-failure", "e5-haproxy-node-failure"):
        result = _load(name)
        if not result:
            continue
        timeline = result["timeline"]
        absent = [b["t"] for b in timeline if "cdn-api-2" not in b["instances"]]
        errored = [(b["t"], b["errors"]) for b in timeline if b["errors"]]
        lines += [
            "",
            f"**{name}** - {result['requests']} requests, **{result['errors']} client-visible "
            f"errors**. api2 missing from the pool for seconds "
            f"{min(absent) if absent else '-'}-{max(absent) if absent else '-'} "
            f"({len(absent)} s). Seconds containing an error: "
            f"{errored if errored else 'none'}.",
            "",
            "| t (s) | RPS | errors | p99 ms | instances answering |",
            "|---|---|---|---|---|",
        ]
        window = range(max(0, min(absent) - 2), min(absent) + 3) if absent else range(0, 5)
        tail = range(max(absent) - 1, max(absent) + 4) if absent else range(0, 0)
        for bucket in timeline:
            if bucket["t"] in window or bucket["t"] in tail:
                shown = ", ".join(f"{k}={v}" for k, v in bucket["instances"].items())
                lines.append(
                    f"| {bucket['t']} | {bucket['rps']} | {bucket['errors']} | "
                    f"{bucket['p99_ms']} | {shown} |"
                )
    return lines


def _ip_hash_table() -> list[str]:
    rows = _load("e1-ip-hash-sources")
    if not rows:
        return []
    lines = [
        "",
        "ip hash from distinct source addresses. nginx hashes only the first three octets, so "
        "the probes sit in different /24s:",
        "",
        "| Source address | Instance |",
        "|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['source_ip']} | {row['instance']} |")
    return lines


def main() -> None:
    calibration = [
        "",
        "## Load generator calibration",
        "",
        "A load test is only as trustworthy as its generator. One Python process driving httpx "
        "tops out well below what three API instances can serve, so every run below is spread "
        "over several processes. Measured against `GET /health`, the cheapest endpoint in the "
        "API, at a fixed 64 virtual users:",
        "",
        "| Processes | VUs total | RPS |",
        "|---|---|---|",
        "| 1 | 64 | 115.1 |",
        "| 2 | 64 | 228.1 |",
        "| 4 | 64 | 383.3 |",
        "",
        "Regenerate with `python -m scripts.loadprobe --calibrate`. A single-process probe "
        "would have reported ~110 req/s as the system's throughput and made the scale-out "
        "experiment meaningless.",
    ]

    parts = [
        "<!-- Lab3 -->",
        "# Lab 3 - raw measurements",
        "",
        "Generated by `python -m scripts.render_lab3_results` from the JSON in "
        "[loadtest/](loadtest/), which `scripts/lab3_experiments.ps1` writes. Nothing here is "
        "typed by hand.",
        "",
        "## Environment",
        "",
        "| | |",
        "|---|---|",
        f"| Generated | {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} |",
        f"| Host | {platform.platform()} |",
        f"| Python | {platform.python_version()} |",
        f"| Docker | {_docker_version()} |",
        "| Balancers | nginx 1.27-alpine (`worker_processes 1`), haproxy 3.0-alpine |",
        "| Pool | api1/api2/api3, one uvicorn worker each, shared PostgreSQL 16 |",
        "| Endpoint | `GET /api/v1/routing/resolve`"
        " `?path=/static/app.bundle.js&client_region=eu-central` |",
        *calibration,
    ]

    for heading, prose, labels in SECTIONS:
        results = [r for r in (_load(label) for label in labels) if r]
        if not results:
            continue
        parts += ["", f"## {heading}", "", prose, "", _markdown(results)]
        parts += _resource_table(results)
        if heading.startswith("E1 "):
            parts += _ip_hash_table()
        if heading.startswith("E3 "):
            parts += _scaling_table()
        if heading.startswith("E4/E5"):
            parts += _failure_timelines()

    OUTPUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
