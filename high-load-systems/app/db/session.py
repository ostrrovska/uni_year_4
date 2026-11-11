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


async def release_connection(session: AsyncSession) -> None:
    """Hand this request's database connection back to the pool before the response is built.

    A read-only handler never commits, so its transaction stays open and SQLAlchemy keeps the
    connection checked out until the session closes - which, with a FastAPI `yield` dependency,
    happens *after* the response has been serialised. The connection is therefore held for the
    whole of the JSON serialisation, which touches no database at all.

    Lab 5 measured what that costs. At 200 virtual users the pool-attributable share of p95 was
    1384 ms while PostgreSQL sat at 29 % of its CPU limit and only 31 of 100 server connections
    were in use: the database was idle and the pool was empty, because connections were being
    held by application work rather than by queries. Enlarging the pool cannot fix that; holding
    connections for less time can.

    Call this once the last query of a read path has returned and before the response model is
    assembled. `expire_on_commit=False` on the sessionmaker is what makes it safe - objects
    already loaded stay usable afterwards.

    `DB_RELEASE_EARLY=false` turns it off, which is how the two arms of the experiment are run
    against the same host within the same minutes. The commit is not free - it is a round trip
    to PostgreSQL that a read path would not otherwise make - so whether it pays depends on
    whether the pool or the round trip is the scarcer thing at that load.
    """
    if not settings.db_release_early:
        return
    await session.commit()


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
