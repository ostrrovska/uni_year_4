"""Lab5 - sample per-container CPU and memory for the duration of one load-test run.

Clause 2.2 asks for the test environment's resources to be recorded, and clause 2.5 asks which
component is the bottleneck. Neither can be answered from the client side: k6 knows only that
requests got slower. This sampler is the other half of the evidence - it says *which container
was out of CPU* at the moment the latency rose, which is the difference between "the system
saturated" and "PostgreSQL saturated while the API tier still had headroom".

docker stats --no-stream per tick rather than the streaming form: the streaming output is a
redrawn terminal frame with cursor-control escapes, and parsing it reliably on Windows is not
worth the saved process spawns at a 1 s interval.

Every row is flushed as it is written. A sampler whose data only exists in a buffer is useless
precisely in the case it is needed - a run that ended in an OOM kill or a Ctrl+C.

The final --summary JSON also records each container's OOMKilled flag and restart count. A run
during which a container was OOM-killed is void, not a finding, and the orchestrator has to be
able to tell the difference without a human reading scrollback.

    python -m scripts.sample_docker_stats --out load-tests/results/a-100vu.csv
        --summary docs/loadtest/lab5/a-100vu-resources.json --stop-file .stop --interval 1
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# The containers of this stack. Named rather than discovered so a stray container from another
# project on the same engine cannot appear in a baseline table.
DEFAULT_CONTAINERS = (
    "cdn-control-plane-postgres-1",
    "cdn-control-plane-redis-1",
    "cdn-control-plane-api1-1",
    "cdn-control-plane-api2-1",
    "cdn-control-plane-api3-1",
    "cdn-control-plane-lb-1",
)

CSV_HEADER = (
    "ts,elapsed_s,container,cpu_percent,mem_used_mib,mem_limit_mib,mem_percent,"
    "net_rx_mb,net_tx_mb,pids\n"
)

_SIZE = re.compile(r"^([0-9.]+)\s*([KMGT]?i?B)$", re.IGNORECASE)
_UNITS = {
    "b": 1 / 1024**2,
    "kb": 1 / 1024,
    "kib": 1 / 1024,
    "mb": 1.0,
    "mib": 1.0,
    "gb": 1024.0,
    "gib": 1024.0,
    "tb": 1024.0**2,
    "tib": 1024.0**2,
}


def _mib(text: str) -> float | None:
    """Parse a docker size such as 41.2MiB into MiB."""
    match = _SIZE.match(text.strip())
    if not match:
        return None
    value, unit = match.groups()
    factor = _UNITS.get(unit.lower())
    return round(float(value) * factor, 3) if factor else None


def _percent(text: str) -> float | None:
    try:
        return float(text.strip().rstrip("%"))
    except ValueError:
        return None


def _split_pair(text: str) -> tuple[str, str]:
    parts = text.split("/")
    return (parts[0], parts[1]) if len(parts) == 2 else (text, "")


def sample(containers: list[str]) -> list[dict]:
    """One docker stats tick. Returns [] on any failure rather than raising.

    A failed tick must not end the run: the sampler outliving the load test is the whole point,
    and a container restarting mid-run makes docker stats fail for exactly one tick.
    """
    try:
        proc = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []

    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        used, limit = _split_pair(raw.get("MemUsage", ""))
        rx, tx = _split_pair(raw.get("NetIO", ""))
        rows.append(
            {
                "container": raw.get("Name", "?"),
                "cpu_percent": _percent(raw.get("CPUPerc", "")),
                "mem_used_mib": _mib(used),
                "mem_limit_mib": _mib(limit),
                "mem_percent": _percent(raw.get("MemPerc", "")),
                "net_rx_mb": _mib(rx),
                "net_tx_mb": _mib(tx),
                "pids": raw.get("PIDs", ""),
            }
        )
    return rows


def inspect(containers: list[str]) -> dict:
    """OOMKilled / restart count / applied limits, straight from the engine.

    The limits are read back rather than copied from docker-compose.lab5.yml: the baseline card
    must state what the containers actually ran with, not what a file asked for.
    """
    out = {}
    for name in containers:
        try:
            proc = subprocess.run(
                ["docker", "inspect", name],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if proc.returncode != 0:
                continue
            info = json.loads(proc.stdout)[0]
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, IndexError):
            continue
        state = info.get("State", {})
        host = info.get("HostConfig", {})
        nano = host.get("NanoCpus") or 0
        quota, period = host.get("CpuQuota") or 0, host.get("CpuPeriod") or 0
        cpus = nano / 1e9 if nano else (quota / period if quota and period else None)
        out[name] = {
            "oom_killed": bool(state.get("OOMKilled")),
            "restart_count": info.get("RestartCount", 0),
            "status": state.get("Status"),
            "cpu_limit": round(cpus, 3) if cpus else None,
            "mem_limit_mib": round((host.get("Memory") or 0) / 1024**2, 1) or None,
        }
    return out


def _write_summary(
    path: Path, label: str, series: dict, containers: list[str], ticks: int, started: float
) -> None:
    def stat(rows: list[dict], key: str, fn) -> float | None:
        values = [r[key] for r in rows if r.get(key) is not None]
        return round(fn(values), 2) if values else None

    resources = {}
    for name, rows in series.items():
        resources[name] = {
            "samples": len(rows),
            "cpu_percent_mean": stat(rows, "cpu_percent", lambda v: sum(v) / len(v)),
            "cpu_percent_max": stat(rows, "cpu_percent", max),
            "mem_used_mib_mean": stat(rows, "mem_used_mib", lambda v: sum(v) / len(v)),
            "mem_used_mib_max": stat(rows, "mem_used_mib", max),
            "mem_percent_max": stat(rows, "mem_percent", max),
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "label": label,
                "ticks": ticks,
                "duration_s": round(time.monotonic() - started, 2),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "resources": resources,
                "containers": inspect(containers),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample docker stats during one load-test run.")
    parser.add_argument("--out", required=True, help="CSV path, one row per container per tick")
    parser.add_argument("--summary", help="JSON path for the per-container aggregate")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=900.0, help="hard stop, seconds")
    parser.add_argument("--stop-file", help="exit cleanly as soon as this file appears")
    parser.add_argument("--container", action="append", dest="containers")
    parser.add_argument("--label", default="run")
    args = parser.parse_args()

    containers = args.containers or list(DEFAULT_CONTAINERS)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stop = Path(args.stop_file) if args.stop_file else None
    if stop and stop.exists():
        stop.unlink()

    series: dict[str, list[dict]] = {}
    started = time.monotonic()
    ticks = 0

    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(CSV_HEADER)
        while True:
            if stop and stop.exists():
                break
            if time.monotonic() - started >= args.duration:
                break
            tick_started = time.monotonic()
            elapsed = round(tick_started - started, 2)
            stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
            for row in sample(containers):
                handle.write(
                    "{ts},{el},{c},{cpu},{mu},{ml},{mp},{rx},{tx},{pids}\n".format(
                        ts=stamp,
                        el=elapsed,
                        c=row["container"],
                        cpu="" if row["cpu_percent"] is None else row["cpu_percent"],
                        mu="" if row["mem_used_mib"] is None else row["mem_used_mib"],
                        ml="" if row["mem_limit_mib"] is None else row["mem_limit_mib"],
                        mp="" if row["mem_percent"] is None else row["mem_percent"],
                        rx="" if row["net_rx_mb"] is None else row["net_rx_mb"],
                        tx="" if row["net_tx_mb"] is None else row["net_tx_mb"],
                        pids=row["pids"],
                    )
                )
                series.setdefault(row["container"], []).append(row)
            handle.flush()
            ticks += 1
            # Sleep the remainder of the interval, not the whole interval: a docker stats call
            # costs ~1 s on Windows, so sleeping a full second would halve the sample rate.
            rest = args.interval - (time.monotonic() - tick_started)
            if rest > 0:
                time.sleep(rest)

    if args.summary:
        _write_summary(Path(args.summary), args.label, series, containers, ticks, started)
    print(f"sampled {ticks} tick(s) over {len(series)} container(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
