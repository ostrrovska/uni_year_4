import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PageDep, SessionDep
from app.api.responses import problems
from app.core.config import get_settings
from app.core.pagination import Page
from app.models.enums import NodeStatus
from app.schemas.node import (
    HeartbeatAccepted,
    HeartbeatReport,
    NodeRead,
    NodeRegister,
    NodeUpdate,
)
from app.schemas.replica import ReplicaRead, ReplicaReport
from app.services import nodes as nodes_service
from app.services import replicas as replicas_service

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", summary="List edge nodes")
async def list_nodes(
    session: SessionDep,
    page: PageDep,
    region: str | None = Query(None, description="Filter by region code."),
    node_status: NodeStatus | None = Query(None, alias="status"),
) -> Page[NodeRead]:
    rows, total = await nodes_service.list_nodes(
        session, page=page, region_code=region, status=node_status
    )
    return Page(
        items=[NodeRead.from_model(node, region_code) for node, region_code in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register an edge node",
    responses=problems(404, 409),
)
async def register_node(payload: NodeRegister, session: SessionDep, response: Response) -> NodeRead:
    node, region_code = await nodes_service.register_node(session, payload)
    response.headers["Location"] = f"/api/v1/nodes/{node.id}"
    return NodeRead.from_model(node, region_code)


@router.get("/{node_id}", summary="Get one edge node", responses=problems(404))
async def get_node(node_id: uuid.UUID, session: SessionDep) -> NodeRead:
    node, region_code = await nodes_service.get_node(session, node_id)
    return NodeRead.from_model(node, region_code)


@router.patch(
    "/{node_id}",
    summary="Update node status or capacity",
    responses=problems(404, 409, 422),
)
async def update_node(node_id: uuid.UUID, payload: NodeUpdate, session: SessionDep) -> NodeRead:
    node, region_code = await nodes_service.update_node(session, node_id, payload)
    return NodeRead.from_model(node, region_code)


@router.delete(
    "/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decommission an edge node",
    responses=problems(404),
)
async def delete_node(node_id: uuid.UUID, session: SessionDep) -> None:
    await nodes_service.delete_node(session, node_id)


@router.post(
    "/{node_id}/heartbeat",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Report node telemetry",
    responses=problems(404),
)
async def report_heartbeat(
    node_id: uuid.UUID, payload: HeartbeatReport, session: SessionDep
) -> HeartbeatAccepted:
    """Ingest one telemetry sample.

    Answers 202 rather than 200: the sample is recorded, but the fleet-wide
    consequences of it — routing weights, purge targeting — are observed by other
    endpoints, not computed and returned here.
    """
    node, received_at = await nodes_service.record_heartbeat(session, node_id, payload)
    return HeartbeatAccepted(
        node_id=node.id,
        status=node.status,
        current_load_percent=node.current_load_percent,
        received_at=received_at,
        next_heartbeat_in_seconds=get_settings().heartbeat_interval_seconds,
    )


@router.get(
    "/{node_id}/replicas",
    summary="List content cached on a node",
    responses=problems(404),
)
async def list_replicas(node_id: uuid.UUID, session: SessionDep) -> list[ReplicaRead]:
    await nodes_service.get_node(session, node_id)
    replicas = await replicas_service.list_replicas_for_node(session, node_id)
    return [ReplicaRead.model_validate(replica) for replica in replicas]


@router.put(
    "/{node_id}/replicas/{asset_id}",
    summary="Report cache state for one asset",
    responses=problems(404, 422),
)
async def report_replica(
    node_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: ReplicaReport,
    session: SessionDep,
) -> ReplicaRead:
    """Declare what this node holds for one asset.

    PUT, because an agent reports the full current state of one replica and repeating
    the same report must not change the outcome.
    """
    replica = await replicas_service.report_replica(
        session,
        node_id,
        asset_id,
        state=payload.state,
        cached_version=payload.cached_version,
        bytes_cached=payload.bytes_cached,
    )
    return ReplicaRead.model_validate(replica)
