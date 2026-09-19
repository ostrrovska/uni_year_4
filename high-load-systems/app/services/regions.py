from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.integrity import translate_integrity_errors
from app.models.region import Region
from app.schemas.region import RegionCreate


async def list_regions(session: AsyncSession) -> Sequence[Region]:
    return (await session.scalars(select(Region).order_by(Region.code))).all()


async def get_region_by_code(session: AsyncSession, code: str) -> Region:
    region = await session.scalar(select(Region).where(Region.code == code))
    if region is None:
        raise NotFoundError(f"No region registered with code '{code}'.")
    return region


async def create_region(session: AsyncSession, payload: RegionCreate) -> Region:
    duplicate = await session.scalar(select(Region.id).where(Region.code == payload.code))
    if duplicate is not None:
        raise ConflictError(f"Region '{payload.code}' already exists.")

    region = Region(code=payload.code, name=payload.name, continent=payload.continent)
    session.add(region)
    async with translate_integrity_errors(
        session, message=f"Region '{payload.code}' already exists."
    ):
        await session.commit()
    await session.refresh(region)
    return region
