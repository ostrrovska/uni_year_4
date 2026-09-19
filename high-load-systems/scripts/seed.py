"""Populate a deterministic demo dataset.

Every identifier is derived with UUIDv5 from a fixed namespace, so the script is
idempotent and the same entity always gets the same id on every machine. That is what
lets load-test scripts (Lab 5) address seeded entities by literal id, and what makes
a "1 instance vs 3 instances" comparison run against identical data.

Re-run it to refresh telemetry after the stack has been idle:
    docker compose run --rm seed
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory, engine
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.distribution_rule import DistributionRule
from app.models.edge_node import EdgeNode
from app.models.enums import AssetStatus, NodeStatus, ReplicaState
from app.models.node_heartbeat import NodeHeartbeat
from app.models.region import Region

SEED_NAMESPACE = uuid.UUID("6f1d5a2e-3b47-5c88-9e10-2a4d7c6b8f31")


def seed_id(kind: str, name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, f"{kind}:{name}")


REGIONS = [
    ("eu-central", "Frankfurt", "Europe"),
    ("eu-west", "Dublin", "Europe"),
    ("us-east", "Virginia", "North America"),
    ("us-west", "Oregon", "North America"),
    ("ap-southeast", "Singapore", "Asia"),
    ("sa-east", "Sao Paulo", "South America"),
]

# (hostname, region, capacity Mbps, load %, status)
NODES = [
    ("edge-eu-central-01", "eu-central", 40_000, 22, NodeStatus.HEALTHY),
    ("edge-eu-central-02", "eu-central", 40_000, 57, NodeStatus.HEALTHY),
    ("edge-eu-central-03", "eu-central", 10_000, 91, NodeStatus.DEGRADED),
    ("edge-eu-west-01", "eu-west", 25_000, 34, NodeStatus.HEALTHY),
    ("edge-eu-west-02", "eu-west", 25_000, 12, NodeStatus.HEALTHY),
    ("edge-us-east-01", "us-east", 60_000, 44, NodeStatus.HEALTHY),
    ("edge-us-east-02", "us-east", 60_000, 68, NodeStatus.HEALTHY),
    ("edge-us-west-01", "us-west", 30_000, 19, NodeStatus.HEALTHY),
    ("edge-us-west-02", "us-west", 30_000, 0, NodeStatus.DRAINING),
    ("edge-ap-southeast-01", "ap-southeast", 20_000, 51, NodeStatus.HEALTHY),
    ("edge-ap-southeast-02", "ap-southeast", 20_000, 73, NodeStatus.HEALTHY),
    ("edge-sa-east-01", "sa-east", 15_000, 8, NodeStatus.HEALTHY),
]

# (origin path, content type, size, TTL, regions the asset is pinned to)
ASSETS = [
    ("/static/app.bundle.js", "application/javascript", 842_113, 3600, []),
    ("/static/vendor.bundle.js", "application/javascript", 1_904_552, 86400, []),
    ("/static/theme.css", "text/css", 128_940, 86400, []),
    ("/media/hero-video.mp4", "video/mp4", 48_221_744, 604800, []),
    ("/media/product-catalog.json", "application/json", 2_048_119, 300, []),
    ("/downloads/installer-win-x64.msi", "application/octet-stream", 92_113_408, 604800, []),
    (
        "/downloads/patch-eu-2026.bin",
        "application/octet-stream",
        18_772_004,
        604800,
        ["eu-central", "eu-west"],
    ),
    (
        "/downloads/patch-apac-2026.bin",
        "application/octet-stream",
        17_003_221,
        604800,
        ["ap-southeast"],
    ),
]


def content_hash(seed: str) -> str:
    """Stable 64-hex-character stand-in for a real artifact digest."""
    return uuid.uuid5(SEED_NAMESPACE, f"hash:{seed}").hex * 2


async def _upsert(session: AsyncSession, model: type, rows: list[dict], pk: list[str]) -> None:
    if not rows:
        return
    updatable = [column for column in rows[0] if column not in pk]
    statement = pg_insert(model).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=pk,
            set_={column: statement.excluded[column] for column in updatable},
        )
    )


async def seed() -> None:
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        await _upsert(
            session,
            Region,
            [
                {"id": seed_id("region", code), "code": code, "name": name, "continent": continent}
                for code, name, continent in REGIONS
            ],
            pk=["id"],
        )

        await _upsert(
            session,
            EdgeNode,
            [
                {
                    "id": seed_id("node", hostname),
                    "hostname": hostname,
                    "public_ipv4": f"203.0.113.{index + 10}",
                    "region_id": seed_id("region", region),
                    "capacity_mbps": capacity,
                    "status": status,
                    "agent_version": "1.4.2",
                    "last_heartbeat_at": now,
                    "current_load_percent": load,
                    "active_connections": load * 120,
                    "cache_hit_ratio": round(0.80 + (index % 15) / 100, 4),
                    "updated_at": now,
                }
                for index, (hostname, region, capacity, load, status) in enumerate(NODES)
            ],
            pk=["id"],
        )

        await _upsert(
            session,
            Asset,
            [
                {
                    "id": seed_id("asset", path),
                    "origin_path": path,
                    "content_hash": content_hash(path),
                    "size_bytes": size,
                    "content_type": content_type,
                    "version": 1,
                    "cache_ttl_seconds": ttl,
                    "status": AssetStatus.PUBLISHED,
                    "updated_at": now,
                }
                for path, content_type, size, ttl, _ in ASSETS
            ],
            pk=["id"],
        )

        await _upsert(
            session,
            DistributionRule,
            [
                {
                    "id": seed_id("rule", f"{path}:{region}"),
                    "asset_id": seed_id("asset", path),
                    "region_id": seed_id("region", region),
                    "priority": 100,
                    "enabled": True,
                }
                for path, _, _, _, pinned_regions in ASSETS
                for region in pinned_regions
            ],
            pk=["id"],
        )

        replica_rows = []
        for path, _, size, _, pinned_regions in ASSETS:
            for hostname, region, _, _, status in NODES:
                if pinned_regions and region not in pinned_regions:
                    continue
                if status is NodeStatus.DRAINING:
                    continue
                replica_rows.append(
                    {
                        "node_id": seed_id("node", hostname),
                        "asset_id": seed_id("asset", path),
                        "state": ReplicaState.CACHED,
                        "cached_version": 1,
                        "bytes_cached": size,
                        "last_verified_at": now,
                        "updated_at": now,
                    }
                )
        await _upsert(session, AssetReplica, replica_rows, pk=["node_id", "asset_id"])

        # A short telemetry history so the heartbeat table is not empty on a fresh stack.
        session.add_all(
            [
                NodeHeartbeat(
                    node_id=seed_id("node", hostname),
                    reported_at=now - timedelta(seconds=10 * age),
                    received_at=now - timedelta(seconds=10 * age),
                    cpu_percent=max(0, min(100, load - age)),
                    memory_percent=max(0, min(100, load // 2 + 20)),
                    bandwidth_out_mbps=int(capacity * load / 100),
                    active_connections=load * 120,
                    cache_hit_ratio=None,
                )
                for hostname, _, capacity, load, _ in NODES
                for age in range(3)
            ]
        )

        await session.commit()

    await engine.dispose()

    print(
        f"Seeded {len(REGIONS)} regions, {len(NODES)} nodes, {len(ASSETS)} assets, "
        f"{len(replica_rows)} replicas."
    )


if __name__ == "__main__":
    asyncio.run(seed())
