import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PageDep, SessionDep
from app.api.responses import problems
from app.core.pagination import Page
from app.models.enums import AssetStatus
from app.schemas.asset import (
    AssetCreate,
    AssetRead,
    AssetVersionPublish,
    AssetVersionPublished,
)
from app.schemas.distribution import DistributionPolicy, DistributionPolicyRead
from app.schemas.purge import PurgeRead
from app.services import assets as assets_service
from app.services import distribution as distribution_service

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", summary="List assets")
async def list_assets(
    session: SessionDep,
    page: PageDep,
    path_prefix: str | None = Query(None, examples=["/static/"]),
    asset_status: AssetStatus | None = Query(None, alias="status"),
) -> Page[AssetRead]:
    assets, total = await assets_service.list_assets(
        session, page=page, path_prefix=path_prefix, status=asset_status
    )
    return Page(
        items=[AssetRead.model_validate(asset) for asset in assets],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register an asset",
    responses=problems(409),
)
async def create_asset(payload: AssetCreate, session: SessionDep, response: Response) -> AssetRead:
    asset = await assets_service.create_asset(session, payload)
    response.headers["Location"] = f"/api/v1/assets/{asset.id}"
    return AssetRead.model_validate(asset)


@router.get("/{asset_id}", summary="Get one asset", responses=problems(404))
async def get_asset(asset_id: uuid.UUID, session: SessionDep) -> AssetRead:
    asset = await assets_service.get_asset(session, asset_id)
    return AssetRead.model_validate(asset)


@router.post(
    "/{asset_id}/versions",
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new version of an asset",
    responses=problems(404, 409),
)
async def publish_version(
    asset_id: uuid.UUID, payload: AssetVersionPublish, session: SessionDep
) -> AssetVersionPublished:
    """Publish new content under an existing path.

    One call produces three effects, atomically: the version is bumped, every replica
    of the old bytes is marked stale, and a purge campaign is opened against the nodes
    holding them. That chain is the reason this is a POST to a sub-collection rather
    than a PATCH on the asset — it creates a new version resource and a new purge.
    """
    outcome = await assets_service.publish_version(session, asset_id, payload)
    return AssetVersionPublished(
        asset=AssetRead.model_validate(outcome.asset),
        previous_version=outcome.previous_version,
        replicas_invalidated=outcome.replicas_invalidated,
        purge_event_id=outcome.purge_event.id,
    )


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Archive an asset and purge it from the edge",
    responses=problems(404),
)
async def archive_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    requested_by: str = Query(..., min_length=1, max_length=128),
) -> PurgeRead:
    """Archive the asset and return the purge campaign it triggered.

    202 with the purge event rather than a bare 204: removal from the edge is
    asynchronous, and the caller needs a handle to follow it to completion.
    """
    purge = await assets_service.archive_asset(session, asset_id, requested_by=requested_by)
    return PurgeRead.model_validate(purge)


@router.get(
    "/{asset_id}/distribution",
    summary="Get an asset's distribution policy",
    responses=problems(404),
)
async def get_distribution(asset_id: uuid.UUID, session: SessionDep) -> DistributionPolicyRead:
    rules = await distribution_service.get_policy(session, asset_id)
    return DistributionPolicyRead(rules=rules, unrestricted=not any(rule.enabled for rule in rules))


@router.put(
    "/{asset_id}/distribution",
    summary="Replace an asset's distribution policy",
    responses=problems(404, 422),
)
async def replace_distribution(
    asset_id: uuid.UUID, payload: DistributionPolicy, session: SessionDep
) -> DistributionPolicyRead:
    rules = await distribution_service.replace_policy(session, asset_id, payload)
    return DistributionPolicyRead(rules=rules, unrestricted=not any(rule.enabled for rule in rules))
