import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PageDep, SessionDep
from app.api.responses import problems
from app.core.pagination import Page
from app.models.enums import PurgeStatus
from app.schemas.purge import PurgeAcknowledge, PurgeCreate, PurgeRead
from app.services import purges as purges_service

router = APIRouter(prefix="/purges", tags=["purges"])


@router.get("", summary="List purge campaigns")
async def list_purges(
    session: SessionDep,
    page: PageDep,
    purge_status: PurgeStatus | None = Query(None, alias="status"),
) -> Page[PurgeRead]:
    events, total = await purges_service.list_purges(session, page=page, status=purge_status)
    return Page(
        items=[PurgeRead.model_validate(event) for event in events],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Broadcast a cache invalidation",
    responses=problems(404, 422),
)
async def create_purge(payload: PurgeCreate, session: SessionDep, response: Response) -> PurgeRead:
    """Open a purge campaign against the nodes in scope.

    202, not 201: the campaign record is created synchronously, but the invalidation
    itself only completes when the targeted nodes acknowledge it. Returning 201 would
    claim the content is already gone from the edge.
    """
    purge = await purges_service.create_purge(session, payload)
    response.headers["Location"] = f"/api/v1/purges/{purge.id}"
    return PurgeRead.model_validate(purge)


@router.get("/{purge_id}", summary="Get purge progress", responses=problems(404))
async def get_purge(purge_id: uuid.UUID, session: SessionDep) -> PurgeRead:
    purge = await purges_service.get_purge(session, purge_id)
    return PurgeRead.model_validate(purge)


@router.post(
    "/{purge_id}/acknowledgements",
    summary="Acknowledge a purge from an edge node",
    responses=problems(404),
)
async def acknowledge_purge(
    purge_id: uuid.UUID, payload: PurgeAcknowledge, session: SessionDep
) -> PurgeRead:
    """Record that one node has acted on the purge.

    Idempotent by primary key: an agent retrying after a timeout re-sends the same
    acknowledgement without inflating the campaign's progress counter.
    """
    purge = await purges_service.acknowledge(session, purge_id, payload)
    return PurgeRead.model_validate(purge)
