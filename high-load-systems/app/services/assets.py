import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.db.integrity import translate_integrity_errors
from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.enums import AssetStatus, ReplicaState
from app.models.purge_event import PurgeEvent
from app.schemas.asset import AssetCreate, AssetVersionPublish
from app.services import purges as purges_service


@dataclass(frozen=True, slots=True)
class VersionPublishOutcome:
    asset: Asset
    previous_version: int
    replicas_invalidated: int
    purge_event: PurgeEvent


def _apply_filters(
    statement: Select, *, path_prefix: str | None, status: AssetStatus | None
) -> Select:
    if path_prefix is not None:
        statement = statement.where(Asset.origin_path.startswith(path_prefix))
    if status is not None:
        statement = statement.where(Asset.status == status)
    return statement


async def list_assets(
    session: AsyncSession,
    *,
    page: PageParams,
    path_prefix: str | None = None,
    status: AssetStatus | None = None,
) -> tuple[Sequence[Asset], int]:
    total = await session.scalar(
        _apply_filters(
            select(func.count()).select_from(Asset), path_prefix=path_prefix, status=status
        )
    )
    assets = (
        await session.scalars(
            _apply_filters(select(Asset), path_prefix=path_prefix, status=status)
            .order_by(Asset.origin_path)
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return assets, total or 0


async def get_asset(session: AsyncSession, asset_id: uuid.UUID) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"No asset with id '{asset_id}'.")
    return asset


async def create_asset(session: AsyncSession, payload: AssetCreate) -> Asset:
    duplicate = await session.scalar(
        select(Asset.id).where(Asset.origin_path == payload.origin_path)
    )
    if duplicate is not None:
        raise ConflictError(
            f"An asset is already registered at '{payload.origin_path}'. "
            "Publish a new version instead of creating a second record."
        )

    asset = Asset(
        origin_path=payload.origin_path,
        content_hash=payload.content_hash,
        size_bytes=payload.size_bytes,
        content_type=payload.content_type,
        cache_ttl_seconds=payload.cache_ttl_seconds,
        version=1,
        status=AssetStatus.PUBLISHED if payload.publish else AssetStatus.DRAFT,
    )
    session.add(asset)
    async with translate_integrity_errors(
        session, message=f"An asset is already registered at '{payload.origin_path}'."
    ):
        await session.commit()
    await session.refresh(asset)
    return asset


async def publish_version(
    session: AsyncSession, asset_id: uuid.UUID, payload: AssetVersionPublish
) -> VersionPublishOutcome:
    """Publish new bytes under an existing path and invalidate what the edge holds.

    The row is locked for the duration: two CI pipelines publishing concurrently would
    otherwise both read version N and both write N+1, losing one release and leaving
    replicas pinned to a version that no longer describes the content.

    Version bump, replica invalidation and purge creation are one transaction. Any
    partial outcome would mean edge nodes serving bytes the control plane believes
    are gone.
    """
    asset = await session.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise NotFoundError(f"No asset with id '{asset_id}'.")
    if asset.status is AssetStatus.ARCHIVED:
        raise ConflictError("Cannot publish a new version of an archived asset.")
    if asset.content_hash == payload.content_hash:
        raise ConflictError(
            "Content hash is identical to the current version — nothing to publish."
        )

    previous_version = asset.version
    asset.version = previous_version + 1
    asset.content_hash = payload.content_hash
    asset.size_bytes = payload.size_bytes
    asset.status = AssetStatus.PUBLISHED
    if payload.cache_ttl_seconds is not None:
        asset.cache_ttl_seconds = payload.cache_ttl_seconds

    invalidated = await _invalidate_replicas(session, asset.id)
    purge = await purges_service.open_asset_purge(
        session,
        asset,
        requested_by=payload.requested_by,
        reason=payload.reason or f"version {previous_version} -> {asset.version}",
    )

    await session.commit()
    await session.refresh(asset)
    await session.refresh(purge)
    return VersionPublishOutcome(
        asset=asset,
        previous_version=previous_version,
        replicas_invalidated=invalidated,
        purge_event=purge,
    )


async def archive_asset(
    session: AsyncSession, asset_id: uuid.UUID, *, requested_by: str
) -> PurgeEvent:
    """Retire an asset and order its removal from every edge node holding it.

    The record is archived rather than deleted: purge acknowledgements, replica
    history and audit trails all reference it, and a hard delete would cascade that
    evidence away exactly when someone needs it.
    """
    asset = await session.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise NotFoundError(f"No asset with id '{asset_id}'.")

    already_archived = asset.status is AssetStatus.ARCHIVED
    asset.status = AssetStatus.ARCHIVED
    await _invalidate_replicas(session, asset.id)
    purge = await purges_service.open_asset_purge(
        session,
        asset,
        requested_by=requested_by,
        reason="asset archived" if not already_archived else "re-issued archive purge",
    )

    await session.commit()
    await session.refresh(purge)
    return purge


async def _invalidate_replicas(session: AsyncSession, asset_id: uuid.UUID) -> int:
    result = await session.execute(
        update(AssetReplica)
        .where(AssetReplica.asset_id == asset_id, AssetReplica.state != ReplicaState.PURGED)
        .values(state=ReplicaState.STALE)
    )
    return result.rowcount
