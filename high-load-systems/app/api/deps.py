from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, page_params
from app.db.session import get_session
from app.services.cache import CacheBackend, get_cache

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CacheDep = Annotated[CacheBackend, Depends(get_cache)]
PageDep = Annotated[PageParams, Depends(page_params)]
