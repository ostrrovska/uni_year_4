from fastapi import APIRouter, Response

from app.api.deps import CacheDep, SessionDep
from app.schemas.stats import NetworkStats
from app.services import stats as stats_service
from app.services.cache import CACHE_HEADER, CacheStatus

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/network", summary="Aggregate network topology and health")
async def network_stats(session: SessionDep, cache: CacheDep, response: Response) -> NetworkStats:
    """Snapshot of fleet, content and purge state.

    Several grouped aggregates over the largest tables, answering a question whose
    result changes slowly — the textbook profile for a cached read, which is what
    Lab 4 turns it into.
    """
    stats = await stats_service.network_stats(session)
    response.headers[CACHE_HEADER] = CacheStatus.MISS if cache.enabled else CacheStatus.BYPASS
    return stats
