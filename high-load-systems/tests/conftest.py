import os
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models import *  # noqa: F403  (import side effect: registers every model on Base.metadata)

# Tests run against a real PostgreSQL instance rather than SQLite: the schema relies on
# native enum types, INET and INSERT ... ON CONFLICT, so a suite running on a different
# engine would prove very little about the code that actually ships.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://cdn:cdn@localhost:5434/cdn_control_plane_test",
)


async def _ensure_database_exists(url: str) -> None:
    base_url, _, database = url.rpartition("/")
    admin_engine = create_async_engine(f"{base_url}/postgres", isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
        )
        if not exists:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    await admin_engine.dispose()


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine]:
    await _ensure_database_exists(TEST_DATABASE_URL)
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Give each test an empty database.

    Truncating between tests keeps them order-independent, which matters because
    several of them assert on aggregate counts across the whole fleet.
    """
    async with engine.begin() as connection:
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        await connection.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest.fixture
async def region(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/regions",
        json={"code": "eu-central", "name": "Frankfurt", "continent": "Europe"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
async def node(client: AsyncClient, region: dict) -> dict:
    response = await client.post(
        "/api/v1/nodes",
        json={
            "hostname": f"edge-{uuid.uuid4().hex[:8]}.cdn.net",
            "public_ipv4": "203.0.113.10",
            "region_code": region["code"],
            "capacity_mbps": 10000,
            "agent_version": "1.4.2",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
async def asset(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/assets",
        json={
            "origin_path": "/static/app.bundle.js",
            "content_hash": "a" * 64,
            "size_bytes": 1024,
            "content_type": "application/javascript",
        },
    )
    assert response.status_code == 201
    return response.json()


async def send_heartbeat(
    client: AsyncClient, node_id: str, *, cpu: int = 10, bandwidth: int = 100
) -> dict:
    """Report telemetry so the node becomes eligible for routing."""
    response = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        json={
            "cpu_percent": cpu,
            "memory_percent": 5,
            "bandwidth_out_mbps": bandwidth,
            "active_connections": 10,
        },
    )
    assert response.status_code == 202
    return response.json()


async def cache_replica(
    client: AsyncClient, node_id: str, asset_id: str, *, version: int = 1
) -> None:
    response = await client.put(
        f"/api/v1/nodes/{node_id}/replicas/{asset_id}",
        json={"state": "cached", "cached_version": version, "bytes_cached": 1024},
    )
    assert response.status_code == 200
