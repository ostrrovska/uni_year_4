import uuid

from httpx import AsyncClient

from tests.conftest import send_heartbeat


async def test_register_node_returns_location_and_provisioning_status(
    client: AsyncClient, region: dict
) -> None:
    response = await client.post(
        "/api/v1/nodes",
        json={
            "hostname": "edge-eu-01.cdn.net",
            "public_ipv4": "203.0.113.11",
            "region_code": region["code"],
            "capacity_mbps": 10000,
            "agent_version": "1.4.2",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "provisioning"
    assert body["region_code"] == region["code"]
    assert response.headers["Location"] == f"/api/v1/nodes/{body['id']}"


async def test_duplicate_hostname_is_rejected(client: AsyncClient, node: dict) -> None:
    response = await client.post(
        "/api/v1/nodes",
        json={
            "hostname": node["hostname"],
            "public_ipv4": "203.0.113.12",
            "region_code": node["region_code"],
            "capacity_mbps": 10000,
            "agent_version": "1.4.2",
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_unknown_region_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/nodes",
        json={
            "hostname": "edge-nowhere.cdn.net",
            "public_ipv4": "203.0.113.13",
            "region_code": "xx-nowhere",
            "capacity_mbps": 10000,
            "agent_version": "1.4.2",
        },
    )

    assert response.status_code == 404


async def test_heartbeat_promotes_node_to_healthy(client: AsyncClient, node: dict) -> None:
    accepted = await send_heartbeat(client, node["id"], cpu=15)

    assert accepted["status"] == "healthy"
    assert accepted["current_load_percent"] == 15
    assert accepted["next_heartbeat_in_seconds"] > 0

    stored = (await client.get(f"/api/v1/nodes/{node['id']}")).json()
    assert stored["status"] == "healthy"
    assert stored["last_heartbeat_at"] is not None


async def test_heartbeat_load_uses_the_worst_signal(client: AsyncClient, node: dict) -> None:
    # 9000 of 10000 Mbps is 90% utilisation, worse than the reported CPU.
    accepted = await send_heartbeat(client, node["id"], cpu=5, bandwidth=9000)

    assert accepted["current_load_percent"] == 90


async def test_overloaded_node_is_automatically_degraded(client: AsyncClient, node: dict) -> None:
    accepted = await send_heartbeat(client, node["id"], cpu=97)

    assert accepted["status"] == "degraded"


async def test_recovered_node_returns_to_healthy(client: AsyncClient, node: dict) -> None:
    await send_heartbeat(client, node["id"], cpu=97)
    accepted = await send_heartbeat(client, node["id"], cpu=12)

    assert accepted["status"] == "healthy"


async def test_draining_survives_a_healthy_heartbeat(client: AsyncClient, node: dict) -> None:
    await send_heartbeat(client, node["id"])
    drained = await client.patch(f"/api/v1/nodes/{node['id']}", json={"status": "draining"})
    assert drained.status_code == 200

    accepted = await send_heartbeat(client, node["id"], cpu=5)

    assert accepted["status"] == "draining"


async def test_illegal_status_transition_is_rejected(client: AsyncClient, node: dict) -> None:
    response = await client.patch(f"/api/v1/nodes/{node['id']}", json={"status": "draining"})

    assert response.status_code == 409
    assert "allowed_transitions" in response.json()


async def test_empty_patch_is_rejected(client: AsyncClient, node: dict) -> None:
    response = await client.patch(f"/api/v1/nodes/{node['id']}", json={})

    assert response.status_code == 422


async def test_heartbeat_for_unknown_node_is_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/nodes/{uuid.uuid4()}/heartbeat",
        json={
            "cpu_percent": 1,
            "memory_percent": 1,
            "bandwidth_out_mbps": 1,
            "active_connections": 1,
        },
    )

    assert response.status_code == 404


async def test_listing_is_paginated_and_filterable(client: AsyncClient, node: dict) -> None:
    listing = (await client.get("/api/v1/nodes?limit=1&offset=0")).json()

    assert listing["total"] == 1
    assert listing["limit"] == 1
    assert len(listing["items"]) == 1

    filtered = (await client.get("/api/v1/nodes?status=offline")).json()
    assert filtered["total"] == 0


async def test_page_size_is_capped(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nodes?limit=100000")

    assert response.status_code == 422


async def test_delete_node(client: AsyncClient, node: dict) -> None:
    assert (await client.delete(f"/api/v1/nodes/{node['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/nodes/{node['id']}")).status_code == 404
