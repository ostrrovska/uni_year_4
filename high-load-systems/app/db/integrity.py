from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError


@asynccontextmanager
async def translate_integrity_errors(session: AsyncSession, *, message: str) -> AsyncIterator[None]:
    """Turn a database uniqueness violation into a 409.

    Services still pre-check for duplicates to produce a helpful message, but a
    pre-check is not a lock: two instances can pass it simultaneously and only the
    database constraint decides the winner. Under concurrent load that race is the
    normal case, not an edge case, so the loser must get a clean 409 rather than a 500.
    """
    try:
        yield
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(message) from exc
