"""Lab5 - PostgreSQL's own counters, snapshotted around each run and reported as a delta.

This is the evidence the client cannot produce. k6 can say a request got slower; only the
database can say whether that is because it read more rows, waited on a lock, or was not
involved at all.

Three questions it answers, each tied to a clause:

* 2.6, caching impact - "зниження навантаження на СУБД" asks for the reduction in *database*
  load, not in response time. The measure is rows returned per request (pg_stat_database
  .tup_returned), because a read-only transaction is rolled back when its session closes, so
  xact_commit counts almost nothing on the read path and would say the cache changed nothing.
  Lab 4 made exactly this choice and documented it; this script keeps it.

* 2.5, primary bottleneck - pg_stat_statements attributes execution time to one query instead
  of reporting that "the database was busy". docs/bottlenecks.md #3 predicts the route
  resolution query will dominate total_exec_time; #1 predicts the heartbeat INSERT will.
  pg_stat_activity's wait events are how #2 (row lock contention on edge_nodes) shows itself:
  a Lock/transactionid wait is the signature, and nothing else produces it.

* 2.2, determinism - node_heartbeats grows all through a 50-minute matrix, so a late run is not
  measuring the same database as an early one unless something checks. The row count is
  recorded per run so the report can show the data was in fact identical, and the orchestrator
  truncates between phases.

Snapshots go through docker exec rather than a Python driver on purpose: psycopg is not a
dependency of this project, the port is published only for the test suite, and a one-shot psql
cannot hold a pooled connection open and perturb the very pool being measured.

    python -m scripts.pg_counters snapshot --out before.json
    python -m scripts.pg_counters delta --before before.json --after after.json \
        --requests 7696 --label a-warm-100vu --out docs/loadtest/lab5/a-warm-100vu-pg.json
"""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

CONTAINER = "cdn-control-plane-postgres-1"
DB = "cdn_control_plane"
USER = "cdn"

# One row, one dict. `-A -F|` keeps parsing trivial and avoids psql's aligned-output padding.
Q_DATABASE = """
SELECT xact_commit, xact_rollback, tup_returned, tup_fetched, tup_inserted, tup_updated,
       tup_deleted, blks_read, blks_hit, numbackends, deadlocks, temp_files
FROM pg_stat_database WHERE datname = current_database();
"""

Q_CONNECTIONS = """
SELECT count(*) FILTER (WHERE state = 'active'),
       count(*) FILTER (WHERE state = 'idle'),
       count(*) FILTER (WHERE state = 'idle in transaction'),
       count(*),
       (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')
FROM pg_stat_activity WHERE datname = current_database();
"""

# Wait events are instantaneous, not cumulative: a snapshot catches whatever is waiting at that
# moment. That is enough for bottleneck #2, where the question is whether Lock waits appear at
# all - but it is why the orchestrator samples this *during* a run, not only after it.
Q_WAITS = """
SELECT coalesce(wait_event_type, 'none'), coalesce(wait_event, 'none'), count(*)
FROM pg_stat_activity
WHERE datname = current_database() AND state = 'active'
GROUP BY 1, 2 ORDER BY 3 DESC;
"""

Q_STATEMENTS = """
SELECT calls, round(total_exec_time::numeric, 2), round(mean_exec_time::numeric, 3), rows,
       regexp_replace(left(query, 110), '\\s+', ' ', 'g')
FROM pg_stat_statements s
JOIN pg_database d ON d.oid = s.dbid
WHERE d.datname = current_database() AND query NOT LIKE '%pg_stat%'
ORDER BY total_exec_time DESC LIMIT 12;
"""

Q_TABLES = """
SELECT relname, n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_hot_upd, seq_scan, idx_scan
FROM pg_stat_user_tables ORDER BY n_tup_ins + n_tup_upd DESC;
"""

Q_HEARTBEAT_ROWS = "SELECT count(*) FROM node_heartbeats;"

CUMULATIVE = (
    "xact_commit",
    "xact_rollback",
    "tup_returned",
    "tup_fetched",
    "tup_inserted",
    "tup_updated",
    "tup_deleted",
    "blks_read",
    "blks_hit",
    "deadlocks",
    "temp_files",
)


def psql(sql: str, timeout: float = 30.0) -> list[list[str]]:
    """Run one statement and return its rows as lists of strings; [] on any failure."""
    try:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER,
                "psql",
                "-U",
                USER,
                "-d",
                DB,
                "-At",
                "-F",
                "|",
                "-c",
                " ".join(sql.split()),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if proc.returncode != 0:
        return []
    return [line.split("|") for line in proc.stdout.splitlines() if line.strip()]


def _int(text: str) -> int:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _float(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def ensure_extension() -> bool:
    """pg_stat_statements is preloaded by docker-compose.lab5.yml but still needs CREATE
    EXTENSION once per database. Idempotent, so the orchestrator can call it every run."""
    psql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")
    return bool(psql("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';"))


def reset_statements() -> None:
    psql("SELECT pg_stat_statements_reset();")


def snapshot() -> dict:
    rows = psql(Q_DATABASE)
    database = {}
    if rows:
        keys = [
            "xact_commit",
            "xact_rollback",
            "tup_returned",
            "tup_fetched",
            "tup_inserted",
            "tup_updated",
            "tup_deleted",
            "blks_read",
            "blks_hit",
            "numbackends",
            "deadlocks",
            "temp_files",
        ]
        database = {k: _int(v) for k, v in zip(keys, rows[0], strict=False)}

    conns = psql(Q_CONNECTIONS)
    connections = {}
    if conns:
        keys = ["active", "idle", "idle_in_transaction", "total", "max_connections"]
        connections = {k: _int(v) for k, v in zip(keys, conns[0], strict=False)}

    statements = [
        {
            "calls": _int(r[0]),
            "total_exec_ms": _float(r[1]),
            "mean_exec_ms": _float(r[2]),
            "rows": _int(r[3]),
            "query": r[4] if len(r) > 4 else "",
        }
        for r in psql(Q_STATEMENTS)
        if len(r) >= 4
    ]

    tables = {
        r[0]: {
            "live": _int(r[1]),
            "dead": _int(r[2]),
            "ins": _int(r[3]),
            "upd": _int(r[4]),
            "hot_upd": _int(r[5]),
            "seq_scan": _int(r[6]),
            "idx_scan": _int(r[7]),
        }
        for r in psql(Q_TABLES)
        if len(r) >= 8
    }

    waits = [
        {"type": r[0], "event": r[1], "backends": _int(r[2])} for r in psql(Q_WAITS) if len(r) >= 3
    ]

    hb = psql(Q_HEARTBEAT_ROWS)
    return {
        "taken_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "database": database,
        "connections": connections,
        "statements": statements,
        "tables": tables,
        "waits": waits,
        "node_heartbeat_rows": _int(hb[0][0]) if hb else None,
    }


def delta(before: dict, after: dict, requests: int | None, label: str) -> dict:
    db_before, db_after = before.get("database", {}), after.get("database", {})
    diff = {k: db_after.get(k, 0) - db_before.get(k, 0) for k in CUMULATIVE}

    reads = diff["blks_hit"] + diff["blks_read"]
    out = {
        "label": label,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "requests": requests,
        "window_seconds": _window(before, after),
        "database_delta": diff,
        # The headline for clause 2.6. Rows returned per request is the measure of the database
        # actually being offloaded rather than of the API merely looking faster.
        "rows_per_request": round(diff["tup_returned"] / requests, 2) if requests else None,
        "tuples_inserted_per_request": round(diff["tup_inserted"] / requests, 3)
        if requests
        else None,
        "tuples_updated_per_request": round(diff["tup_updated"] / requests, 3)
        if requests
        else None,
        # Cache hit ratio of PostgreSQL's own shared buffers - not to be confused with the Redis
        # hit ratio. A fall here while Redis' rises is the clearest single sign the right tier
        # absorbed the load.
        "buffer_hit_percent": round(100 * diff["blks_hit"] / reads, 2) if reads else None,
        "connections_before": before.get("connections", {}),
        "connections_after": after.get("connections", {}),
        "waits_during": after.get("waits", []),
        "node_heartbeat_rows_before": before.get("node_heartbeat_rows"),
        "node_heartbeat_rows_after": after.get("node_heartbeat_rows"),
        "top_statements": after.get("statements", []),
        "table_delta": _table_delta(before.get("tables", {}), after.get("tables", {})),
    }
    return out


def _window(before: dict, after: dict) -> float | None:
    try:
        start = datetime.fromisoformat(before["taken_at"])
        end = datetime.fromisoformat(after["taken_at"])
    except (KeyError, ValueError):
        return None
    return round((end - start).total_seconds(), 2)


def _table_delta(before: dict, after: dict) -> dict:
    out = {}
    for name, now in after.items():
        was = before.get(name, {})
        row = {k: now.get(k, 0) - was.get(k, 0) for k in ("ins", "upd", "seq_scan", "idx_scan")}
        row["hot_upd"] = now.get("hot_upd", 0) - was.get("hot_upd", 0)
        # HOT updates avoid rewriting every index on the table, so the share of updates that
        # were HOT is the direct measure of bottleneck #2's "Already mitigated / Next steps"
        # argument about fillfactor on edge_nodes.
        row["hot_update_percent"] = (
            round(100 * row["hot_upd"] / row["upd"], 1) if row["upd"] else None
        )
        row["dead_tuples_now"] = now.get("dead", 0)
        row["live_tuples_now"] = now.get("live", 0)
        if any(row[k] for k in ("ins", "upd", "seq_scan", "idx_scan")):
            out[name] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot or diff PostgreSQL counters.")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="write one snapshot")
    snap.add_argument("--out", required=True)
    snap.add_argument("--reset-statements", action="store_true")

    diff = sub.add_parser("delta", help="diff two snapshots into a run report")
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    diff.add_argument("--out", required=True)
    diff.add_argument("--requests", type=int)
    diff.add_argument("--label", default="run")

    sub.add_parser("check", help="verify pg_stat_statements is available")

    args = parser.parse_args()

    if args.command == "check":
        ok = ensure_extension()
        print("pg_stat_statements: " + ("available" if ok else "MISSING"))
        return 0 if ok else 1

    if args.command == "snapshot":
        ensure_extension()
        if args.reset_statements:
            reset_statements()
        data = snapshot()
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"snapshot -> {path}")
        return 0

    before = json.loads(Path(args.before).read_text(encoding="utf-8-sig"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8-sig"))
    report = delta(before, after, args.requests, args.label)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"delta -> {path} (rows/request {report['rows_per_request']}, "
        f"buffer hit {report['buffer_hit_percent']} %)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
