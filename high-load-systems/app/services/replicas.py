import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, UnprocessableError
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.edge_node import EdgeNode
from app.models.enums import ReplicaState


async def list_replicas_for_node(
    session: AsyncSession, node_id: uuid.UUID
) -> Sequence[AssetReplica]:
    return (
        await session.scalars(
            select(AssetReplica)
            .where(AssetReplica.node_id == node_id)
            .order_by(AssetReplica.asset_id)
        )
    ).all()


async def report_replica(
    session: AsyncSession,
    node_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    state: ReplicaState,
    cached_version: int | None,
    bytes_cached: int,
) -> AssetReplica:
    """Upsert what a node reports holding for one asset.

    Written as a single INSERT ... ON CONFLICT DO UPDATE because agents report
    continuously and concurrently: a select-then-insert would race with itself and
    fail on the primary key under any real reporting rate.
    """
    node_exists = await session.scalar(select(EdgeNode.id).where(EdgeNode.id == node_id))
    if node_exists is None:
        raise NotFoundError(f"No edge node with id '{node_id}'.")

    asset = await session.scalar(select(Asset).where(Asset.id == asset_id))
    if asset is None:
        raise NotFoundError(f"No asset with id '{asset_id}'.")

    if state is ReplicaState.CACHED and cached_version is None:
        raise UnprocessableError("cached_version is required when state is 'cached'.")
    if cached_version is not None and cached_version > asset.version:
        raise UnprocessableError(
            f"Reported version {cached_version} is ahead of the published version "
            f"{asset.version} for this asset.",
        )

    now = datetime.now(UTC)
    values = {
        "node_id": node_id,
        "asset_id": asset_id,
        "state": state,
        "cached_version": cached_version,
        "bytes_cached": bytes_cached,
        "last_verified_at": now,
        "updated_at": now,
    }
    statement = (
        pg_insert(AssetReplica)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["node_id", "asset_id"],
            set_={
                "state": state,
                "cached_version": cached_version,
                "bytes_cached": bytes_cached,
                "last_verified_at": now,
                "updated_at": now,
            },
        )
        .returning(AssetReplica)
    )
    replica = (await session.execute(statement)).scalar_one()
    await session.commit()
    return replica
