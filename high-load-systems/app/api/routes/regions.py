from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep
from app.api.responses import problems
from app.schemas.region import RegionCreate, RegionRead
from app.services import regions as regions_service

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", summary="List regions")
async def list_regions(session: SessionDep) -> list[RegionRead]:
    regions = await regions_service.list_regions(session)
    return [RegionRead.model_validate(region) for region in regions]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a region",
    responses=problems(409),
)
async def create_region(
    payload: RegionCreate, session: SessionDep, response: Response
) -> RegionRead:
    region = await regions_service.create_region(session, payload)
    response.headers["Location"] = f"/api/v1/regions/{region.id}"
    return RegionRead.model_validate(region)
