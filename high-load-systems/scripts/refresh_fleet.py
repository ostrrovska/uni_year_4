"""Simulate the edge agents that would report telemetry in a real deployment.

Every real edge node runs an agent that heartbeats continuously. A seeded database has
the nodes but not the agents, so after HEARTBEAT_STALE_AFTER_SECONDS the whole fleet
looks unreachable and `/routing/resolve` answers 503. That verdict is correct — the
missing piece is the agents, not the control plane.

The `agents` service in docker-compose.yml runs this in watch mode, which is what makes
the demo stack self-sustaining: nothing has to be refreshed by hand.

Heartbeats go through the real `record_heartbeat` service, so the same load derivation
and status transitions apply as for a genuine agent. Load values come from scripts.seed,
which keeps the fleet deterministic: edge-eu-central-03 stays at 91% and therefore stays
`degraded` and out of the routing pool, demonstrating automatic ejection.

    python -m scripts.refresh_fleet            # one round, then exit
    python -m scripts.refresh_fleet --watch 10 # run forever, like a real agent
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import async_session_factory, engine
from app.models.edge_node import EdgeNode
from app.schemas.node import HeartbeatReport
from app.services import nodes as nodes_service
from scripts.seed import NODES

_LOAD_BY_HOSTNAME = {hostname: load for hostname, _, _, load, _ in NODES}


async def refresh_once() -> tuple[int, int]:
    refreshed = 0
    skipped = 0

    async with async_session_factory() as session:
        nodes = (await session.scalars(select(EdgeNode))).all()
        for node in nodes:
            load = _LOAD_BY_HOSTNAME.get(node.hostname)
            if load is None:
                # Not a seeded node — leave whatever a real agent or a demo created.
                skipped += 1
                continue
            report = HeartbeatReport(
                reported_at=datetime.now(UTC),
                cpu_percent=load,
                # Kept below cpu_percent so the derived load is exactly the seeded
                # value — _derive_load_percent takes the worst of the three signals.
                memory_percent=max(0, load - 10),
                bandwidth_out_mbps=int(node.capacity_mbps * load / 100),
                active_connections=load * 120,
                cache_hit_ratio=0.9,
            )
            await nodes_service.record_heartbeat(session, node.id, report)
            refreshed += 1

    return refreshed, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--watch",
        type=int,
        metavar="SECONDS",
        help="Repeat forever at this interval instead of running once.",
    )
    args = parser.parse_args()

    try:
        while True:
            stamp = datetime.now(UTC).strftime("%H:%M:%S")
            try:
                refreshed, skipped = await refresh_once()
            except Exception as exc:
                # In watch mode a transient database outage must not end the simulation:
                # the readiness demonstration deliberately stops PostgreSQL, and real
                # edge agents likewise keep trying while the control plane is down.
                if args.watch is None:
                    raise
                print(f"[{stamp}] control plane unreachable ({type(exc).__name__}), retrying")
            else:
                note = f", {skipped} non-seeded node(s) left alone" if skipped else ""
                print(f"[{stamp}] refreshed {refreshed} node(s){note}", flush=True)

            if args.watch is None:
                return
            await asyncio.sleep(args.watch)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
