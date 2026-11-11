import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep
from app.api.responses import problems
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.core.instance import get_instance_id
from app.db.session import release_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Report that the process is running and able to serve HTTP.

    Deliberately checks nothing else. A liveness probe that touches the database
    would make every instance restart when the database blips — turning a recoverable
    dependency failure into a fleet-wide outage.
    """
    return {
        "status": "ok",
        "instance_id": get_instance_id(),
        "app_version": get_settings().app_version,
    }


@router.get("/health/ready", summary="Readiness probe", responses=problems(503))
async def readiness(session: SessionDep) -> dict[str, str]:
    """Report whether this instance can actually serve traffic.

    This is the endpoint a load balancer polls (Lab 3): an instance whose database
    connection is broken must be taken out of the upstream pool rather than handed
    requests it can only fail.
    """
    try:
        await session.execute(text("SELECT 1"))
        # Released here rather than at the end of the request: this endpoint exists to prove
        # the instance can reach the database, and holding a pooled connection afterwards
        # would make a readiness probe compete with real traffic for the resource it is
        # reporting on.
        await release_connection(session)
    except Exception as exc:
        logger.warning("readiness.database_unreachable", extra={"error": str(exc)})
        raise ServiceUnavailableError("Database is not reachable from this instance.") from exc
    return {"status": "ready", "instance_id": get_instance_id()}
