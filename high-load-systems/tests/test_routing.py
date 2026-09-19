from httpx import AsyncClient

from tests.conftest import cache_replica, send_heartbeat

RESOLVE = "/api/v1/routing/resolve"


async def _register_node(
    client: AsyncClient, hostname: str, region_code: str, *, capacity: int = 10000
) -> dict:
    response = await client.post(
        "/api/v1/nodes",
        json={
            "hostname": hostname,
            "public_ipv4": "203.0.113.20",
            "region_code": region_code,
            "capacity_mbps": capacity,
            "agent_version": "1.4.2",
        },
    )
    assert response.status_code == 201
    return response.json()


async def _register_region(client: AsyncClient, code: str, continent: str) -> None:
    response = await client.post(
        "/api/v1/regions", json={"code": code, "name": code, "continent": continent}
    )
    assert response.status_code == 201


async def test_resolve_returns_the_warm_node_in_the_client_region(
    client: AsyncClient, region: dict, asset: dict
) -> None:
    await _register_region(client, "us-east", "North America")
    near = await _register_node(client, "edge-near.cdn.net", region["code"])
    far = await _register_node(client, "edge-far.cdn.net", "us-east")
    for edge in (near, far):
        await send_heartbeat(client, edge["id"], cpu=10)
        await cache_replica(client, edge["id"], asset["id"])

    response = await client.get(
        RESOLVE, params={"path": asset["origin_path"], "client_region": region["code"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["hostname"] == near["hostname"]
    assert body["candidates"][0]["cache_state"] == "warm"
    assert response.headers["X-Cache"] == "BYPASS"


async def test_warm_node_outranks_a_cold_one_in_the_same_region(
    client: AsyncClient, region: dict, asset: dict
) -> None:
    warm = await _register_node(client, "edge-warm.cdn.net", region["code"])
    cold = await _register_node(client, "edge-cold.cdn.net", region["code"])
    await send_heartbeat(client, warm["id"], cpu=40)
    await send_heartbeat(client, cold["id"], cpu=1)
    await cache_replica(client, warm["id"], asset["id"])

    body = (
        await client.get(
            RESOLVE, params={"path": asset["origin_path"], "client_region": region["code"]}
        )
    ).json()

    assert body["candidates"][0]["hostname"] == warm["hostname"]
    assert body["candidates"][1]["cache_state"] == "cold"


async def test_overloaded_node_is_excluded(client: AsyncClient, region: dict, asset: dict) -> None:
    hot = await _register_node(client, "edge-hot.cdn.net", region["code"])
    await send_heartbeat(client, hot["id"], cpu=95)
    await cache_replica(client, hot["id"], asset["id"])

    response = await client.get(RESOLVE, params={"path": asset["origin_path"]})

    assert response.status_code == 503


async def test_node_without_a_heartbeat_is_excluded(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await cache_replica(client, node["id"], asset["id"])

    response = await client.get(RESOLVE, params={"path": asset["origin_path"]})

    assert response.status_code == 503


async def test_replica_on_an_outdated_version_counts_as_cold(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"], version=1)
    await client.post(
        f"/api/v1/assets/{asset['id']}/versions",
        json={"content_hash": "b" * 64, "size_bytes": 2048, "requested_by": "ci"},
    )

    body = (await client.get(RESOLVE, params={"path": asset["origin_path"]})).json()

    assert body["version"] == 2
    assert body["candidates"][0]["cache_state"] == "cold"


async def test_distribution_policy_restricts_eligible_regions(
    client: AsyncClient, region: dict, asset: dict
) -> None:
    await _register_region(client, "us-east", "North America")
    allowed = await _register_node(client, "edge-eu.cdn.net", region["code"])
    blocked = await _register_node(client, "edge-us.cdn.net", "us-east")
    for edge in (allowed, blocked):
        await send_heartbeat(client, edge["id"])
        await cache_replica(client, edge["id"], asset["id"])

    policy = await client.put(
        f"/api/v1/assets/{asset['id']}/distribution",
        json={"rules": [{"region_code": region["code"], "priority": 10, "enabled": True}]},
    )
    assert policy.status_code == 200

    body = (await client.get(RESOLVE, params={"path": asset["origin_path"]})).json()

    hostnames = [candidate["hostname"] for candidate in body["candidates"]]
    assert hostnames == [allowed["hostname"]]


async def test_unknown_path_is_404(client: AsyncClient) -> None:
    response = await client.get(RESOLVE, params={"path": "/nope.js"})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_limit_above_the_configured_maximum_is_rejected(
    client: AsyncClient, asset: dict
) -> None:
    response = await client.get(RESOLVE, params={"path": asset["origin_path"], "limit": 99})

    assert response.status_code == 422
    assert response.json()["max_limit"] == 10
