import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.pagination import PageParams
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.edge_node import EdgeNode
from app.models.enums import NodeStatus, PurgeResult, PurgeScope, PurgeStatus, ReplicaState
from app.models.purge_acknowledgement import PurgeAcknowledgement
from app.models.purge_event import PurgeEvent
from app.schemas.purge import PurgeAcknowledge, PurgeCreate
from app.services import regions as regions_service


async def _resolve_target_node_ids(
    session: AsyncSession,
    *,
    scope: PurgeScope,
    asset_id: uuid.UUID | None,
    region_id: uuid.UUID | None,
) -> Sequence[uuid.UUID]:
    """Materialise the set of nodes a purge is expected to reach.

    Offline nodes are excluded on purpose. Including them would make the target count
    unreachable and leave every purge permanently in progress, since a node that is
    down cannot acknowledge anything. A node that comes back does so with an empty
    or revalidated cache, which is the same end state the purge was after.
    """
    if scope is PurgeScope.ASSET:
        statement = (
            select(AssetReplica.node_id)
            .join(EdgeNode, EdgeNode.id == AssetReplica.node_id)
            .where(AssetReplica.asset_id == asset_id, EdgeNode.status != NodeStatus.OFFLINE)
        )
    elif scope is PurgeScope.REGION:
        statement = select(EdgeNode.id).where(
            EdgeNode.region_id == region_id, EdgeNode.status != NodeStatus.OFFLINE
        )
    else:
        statement = select(EdgeNode.id).where(EdgeNode.status != NodeStatus.OFFLINE)

    return (await session.scalars(statement)).all()


async def open_asset_purge(
    session: AsyncSession, asset: Asset, *, requested_by: str, reason: str | None
) -> PurgeEvent:
    """Create the purge that a content change implies. Does not commit.

    Callers mutating an asset are already inside a transaction; the purge has to land
    atomically with the version bump, otherwise a crash between the two would leave
    stale bytes on the edge with no record that they need removing.
    """
    target_node_ids = await _resolve_target_node_ids(
        session, scope=PurgeScope.ASSET, asset_id=asset.id, region_id=None
    )
    purge = PurgeEvent(
        scope=PurgeScope.ASSET,
        asset_id=asset.id,
        path_pattern=asset.origin_path,
        requested_by=requested_by,
        reason=reason,
        target_node_count=len(target_node_ids),
        status=PurgeStatus.COMPLETED if not target_node_ids else PurgeStatus.IN_PROGRESS,
        completed_at=datetime.now(UTC) if not target_node_ids else None,
    )
    session.add(purge)
    return purge


async def create_purge(session: AsyncSession, payload: PurgeCreate) -> PurgeEvent:
    asset_id: uuid.UUID | None = None
    region_id: uuid.UUID | None = None

    if payload.scope is PurgeScope.ASSET:
        asset_id = await session.scalar(select(Asset.id).where(Asset.id == payload.asset_id))
        if asset_id is None:
            raise NotFoundError(f"No asset with id '{payload.asset_id}'.")
    elif payload.scope is PurgeScope.REGION:
        region = await regions_service.get_region_by_code(session, payload.region_code or "")
        region_id = region.id

    target_node_ids = await _resolve_target_node_ids(
        session, scope=payload.scope, asset_id=asset_id, region_id=region_id
    )

    purge = PurgeEvent(
        scope=payload.scope,
        asset_id=asset_id,
        region_id=region_id,
        path_pattern=payload.path_pattern,
        requested_by=payload.requested_by,
        reason=payload.reason,
        target_node_count=len(target_node_ids),
        status=PurgeStatus.COMPLETED if not target_node_ids else PurgeStatus.IN_PROGRESS,
        completed_at=datetime.now(UTC) if not target_node_ids else None,
    )
    session.add(purge)
    await session.commit()
    await session.refresh(purge)
    return purge


def _apply_filters(statement: Select, *, status: PurgeStatus | None) -> Select:
    if status is not None:
        statement = statement.where(PurgeEvent.status == status)
    return statement


async def list_purges(
    session: AsyncSession, *, page: PageParams, status: PurgeStatus | None = None
) -> tuple[Sequence[PurgeEvent], int]:
    total = await session.scalar(
        _apply_filters(select(func.count()).select_from(PurgeEvent), status=status)
    )
    events = (
        await session.scalars(
            _apply_filters(select(PurgeEvent), status=status)
            .order_by(PurgeEvent.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return events, total or 0


async def get_purge(session: AsyncSession, purge_id: uuid.UUID) -> PurgeEvent:
    purge = await session.get(PurgeEvent, purge_id)
    if purge is None:
        raise NotFoundError(f"No purge event with id '{purge_id}'.")
    return purge


async def acknowledge(
    session: AsyncSession, purge_id: uuid.UUID, payload: PurgeAcknowledge
) -> PurgeEvent:
    """Record one node's confirmation and advance the campaign.

    The tally is incremented with a SQL expression rather than read-modify-write in
    Python: two instances acknowledging different nodes at the same moment would
    otherwise both read the same count and one increment would be lost.
    """
    purge = await get_purge(session, purge_id)

    node_exists = await session.scalar(select(EdgeNode.id).where(EdgeNode.id == payload.node_id))
    if node_exists is None:
        raise NotFoundError(f"No edge node with id '{payload.node_id}'.")

    insert_ack = (
        pg_insert(PurgeAcknowledgement)
        .values(
            purge_event_id=purge_id,
            node_id=payload.node_id,
            result=payload.result,
            detail=payload.detail,
        )
        .on_conflict_do_nothing(index_elements=["purge_event_id", "node_id"])
    )
    newly_recorded = (await session.execute(insert_ack)).rowcount == 1

    if newly_recorded:
        await session.execute(
            update(PurgeEvent)
            .where(
                PurgeEvent.id == purge_id,
                PurgeEvent.acknowledged_count < PurgeEvent.target_node_count,
            )
            .values(acknowledged_count=PurgeEvent.acknowledged_count + 1)
        )

        if payload.result is PurgeResult.PURGED and purge.asset_id is not None:
            await session.execute(
                update(AssetReplica)
                .where(
                    AssetReplica.asset_id == purge.asset_id,
                    AssetReplica.node_id == payload.node_id,
                )
                .values(state=ReplicaState.PURGED, cached_version=None, bytes_cached=0)
            )

    await session.refresh(purge)

    if purge.status is not PurgeStatus.COMPLETED and (
        purge.acknowledged_count >= purge.target_node_count
    ):
        failed = await session.scalar(
            select(func.count())
            .select_from(PurgeAcknowledgement)
            .where(
                PurgeAcknowledgement.purge_event_id == purge_id,
                PurgeAcknowledgement.result != PurgeResult.PURGED,
            )
        )
        # Two instances can reach this point for the last two acknowledgements at once
        # and both write the terminal status. The write is idempotent, so the race is
        # harmless and does not justify taking a lock on the hot acknowledgement path.
        purge.status = PurgeStatus.PARTIALLY_FAILED if failed else PurgeStatus.COMPLETED
        purge.completed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(purge)
    return purge
