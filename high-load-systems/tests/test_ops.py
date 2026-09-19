from httpx import AsyncClient


async def test_liveness_reports_instance(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_checks_the_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_every_response_carries_correlation_headers(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers["X-Instance-ID"]
    assert response.headers["X-Request-ID"]
    assert float(response.headers["X-Response-Time-ms"]) >= 0


async def test_incoming_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-me"})

    assert response.headers["X-Request-ID"] == "trace-me"


async def test_unknown_route_returns_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["instance"] == "/api/v1/nope"
