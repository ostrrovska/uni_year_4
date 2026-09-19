from httpx import AsyncClient

from tests.conftest import cache_replica, send_heartbeat


async def test_duplicate_origin_path_is_rejected(client: AsyncClient, asset: dict) -> None:
    response = await client.post(
        "/api/v1/assets",
        json={
            "origin_path": asset["origin_path"],
            "content_hash": "c" * 64,
            "size_bytes": 10,
            "content_type": "application/javascript",
        },
    )

    assert response.status_code == 409


async def test_publishing_a_version_invalidates_replicas_and_opens_a_purge(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"])

    response = await client.post(
        f"/api/v1/assets/{asset['id']}/versions",
        json={"content_hash": "b" * 64, "size_bytes": 2048, "requested_by": "ci-pipeline"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["previous_version"] == 1
    assert body["asset"]["version"] == 2
    assert body["replicas_invalidated"] == 1

    purge = (await client.get(f"/api/v1/purges/{body['purge_event_id']}")).json()
    assert purge["status"] == "in_progress"
    assert purge["target_node_count"] == 1
    assert purge["acknowledged_count"] == 0

    replicas = (await client.get(f"/api/v1/nodes/{node['id']}/replicas")).json()
    assert replicas[0]["state"] == "stale"


async def test_republishing_identical_content_is_rejected(client: AsyncClient, asset: dict) -> None:
    response = await client.post(
        f"/api/v1/assets/{asset['id']}/versions",
        json={
            "content_hash": asset["content_hash"],
            "size_bytes": asset["size_bytes"],
            "requested_by": "ci-pipeline",
        },
    )

    assert response.status_code == 409


async def test_acknowledging_a_purge_completes_it(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"])
    published = (
        await client.post(
            f"/api/v1/assets/{asset['id']}/versions",
            json={"content_hash": "b" * 64, "size_bytes": 2048, "requested_by": "ci"},
        )
    ).json()

    response = await client.post(
        f"/api/v1/purges/{published['purge_event_id']}/acknowledgements",
        json={"node_id": node["id"], "result": "purged"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["acknowledged_count"] == 1
    assert body["status"] == "completed"
    assert body["completed_at"] is not None

    replicas = (await client.get(f"/api/v1/nodes/{node['id']}/replicas")).json()
    assert replicas[0]["state"] == "purged"


async def test_repeated_acknowledgement_does_not_inflate_the_tally(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"])
    published = (
        await client.post(
            f"/api/v1/assets/{asset['id']}/versions",
            json={"content_hash": "b" * 64, "size_bytes": 2048, "requested_by": "ci"},
        )
    ).json()
    url = f"/api/v1/purges/{published['purge_event_id']}/acknowledgements"
    payload = {"node_id": node["id"], "result": "purged"}

    await client.post(url, json=payload)
    second = await client.post(url, json=payload)

    assert second.status_code == 200
    assert second.json()["acknowledged_count"] == 1


async def test_failed_acknowledgement_marks_the_purge_partially_failed(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"])
    published = (
        await client.post(
            f"/api/v1/assets/{asset['id']}/versions",
            json={"content_hash": "b" * 64, "size_bytes": 2048, "requested_by": "ci"},
        )
    ).json()

    response = await client.post(
        f"/api/v1/purges/{published['purge_event_id']}/acknowledgements",
        json={"node_id": node["id"], "result": "failed", "detail": "disk error"},
    )

    assert response.json()["status"] == "partially_failed"


async def test_manual_global_purge_targets_every_online_node(
    client: AsyncClient, node: dict
) -> None:
    await send_heartbeat(client, node["id"])

    response = await client.post(
        "/api/v1/purges",
        json={"scope": "global", "requested_by": "ops@cdn.net", "reason": "incident 4711"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["target_node_count"] == 1
    assert response.headers["Location"] == f"/api/v1/purges/{body['id']}"


async def test_region_purge_requires_a_region_code(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/purges", json={"scope": "region", "requested_by": "ops@cdn.net"}
    )

    assert response.status_code == 422


async def test_archiving_returns_the_triggered_purge(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"])
    await cache_replica(client, node["id"], asset["id"])

    response = await client.delete(
        f"/api/v1/assets/{asset['id']}", params={"requested_by": "ops@cdn.net"}
    )

    assert response.status_code == 202
    assert response.json()["scope"] == "asset"
    assert (await client.get(f"/api/v1/assets/{asset['id']}")).json()["status"] == "archived"


async def test_distribution_policy_rejects_unknown_regions(
    client: AsyncClient, asset: dict
) -> None:
    response = await client.put(
        f"/api/v1/assets/{asset['id']}/distribution",
        json={"rules": [{"region_code": "xx-nowhere"}]},
    )

    assert response.status_code == 422
    assert response.json()["unknown_region_codes"] == ["xx-nowhere"]


async def test_replica_version_ahead_of_published_is_rejected(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    response = await client.put(
        f"/api/v1/nodes/{node['id']}/replicas/{asset['id']}",
        json={"state": "cached", "cached_version": 99, "bytes_cached": 10},
    )

    assert response.status_code == 422


async def test_network_stats_reflect_the_fleet(
    client: AsyncClient, node: dict, asset: dict
) -> None:
    await send_heartbeat(client, node["id"], cpu=30)
    await cache_replica(client, node["id"], asset["id"])

    body = (await client.get("/api/v1/stats/network")).json()

    assert body["nodes_total"] == 1
    assert body["nodes_by_status"]["healthy"] == 1
    assert body["assets_published"] == 1
    assert body["replicas_cached"] == 1
    assert body["replica_coverage_percent"] == 100.0
    assert body["regions"][0]["region_code"] == "eu-central"
