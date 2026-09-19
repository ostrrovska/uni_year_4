from fastapi import APIRouter, Query, Response

from app.api.deps import CacheDep, SessionDep
from app.api.responses import problems
from app.core.config import get_settings
from app.core.errors import UnprocessableError
from app.schemas.routing import RouteResolution
from app.services import routing as routing_service
from app.services.cache import CACHE_HEADER, CacheStatus

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get(
    "/resolve",
    summary="Resolve the best edge nodes for an asset",
    responses=problems(404, 422, 503),
)
async def resolve_route(
    session: SessionDep,
    cache: CacheDep,
    response: Response,
    path: str = Query(..., min_length=1, max_length=512, examples=["/static/app.bundle.js"]),
    client_region: str | None = Query(
        None, description="Region code of the requesting client, used for proximity scoring."
    ),
    limit: int | None = Query(None, ge=1, description="Number of candidates to return."),
) -> RouteResolution:
    """Return ranked edge nodes for a client to download an asset from.

    The read-intensive hot path of the whole system: every client download begins
    with one of these calls, while writes to the underlying data are comparatively
    rare. That ratio is what makes it the primary caching target in Lab 4, and the
    `X-Cache` header below is already wired to report where the answer came from.
    """
    settings = get_settings()
    if limit is None:
        limit = settings.routing_default_candidates
    elif limit > settings.routing_max_candidates:
        raise UnprocessableError(
            f"limit may not exceed {settings.routing_max_candidates}.",
            max_limit=settings.routing_max_candidates,
        )

    resolution = await routing_service.resolve_route(
        session, path=path, client_region_code=client_region, limit=limit
    )
    response.headers[CACHE_HEADER] = CacheStatus.MISS if cache.enabled else CacheStatus.BYPASS
    return resolution
