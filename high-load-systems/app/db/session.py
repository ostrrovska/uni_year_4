from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Pool sizing is configuration, not a constant: the effective limit on the database
# is (pool_size + max_overflow) x number of API instances, and that product is the
# first thing to collide with PostgreSQL's max_connections once the service tier is
# scaled out. See docs/bottlenecks.md, bottleneck #4.
engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield a request-scoped async session.

    Transaction boundaries are left to the services: they commit explicitly, so a
    reader can see where a unit of work ends instead of inferring it from the
    dependency. Anything that escapes as an exception is rolled back here.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
