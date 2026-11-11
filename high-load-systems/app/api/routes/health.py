import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep
from app.api.responses import problems
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.core.instance import get_instance_id

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
        "version": get_settings().app_version,
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
    except Exception as exc:
        logger.warning("readiness.database_unreachable", extra={"error": str(exc)})
        raise ServiceUnavailableError("Database is not reachable from this instance.") from exc
    return {"status": "ready", "instance_id": get_instance_id()}


# DevOps Lab5
@router.get("/version", summary="Build identity of this instance")
async def version() -> dict[str, str]:
    """Report which build is serving, so a GitOps rollout can be verified from outside.

    Under Argo CD nobody runs `helm upgrade`: the image tag changes in Git and the
    cluster converges on its own. That makes "did the new version actually land?" a
    question about the running pods rather than about the command that was typed, and
    this endpoint is the answer. It reads the two values baked into the image by
    docker/Dockerfile, so a pod can only report the build it was made from.
    """
    settings = get_settings()
    return {
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "instance_id": get_instance_id(),
        "app_env": settings.app_env,
    }
