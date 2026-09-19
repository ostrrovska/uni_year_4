from pydantic import BaseModel, Field


class RegionStats(BaseModel):
    region_code: str
    continent: str
    node_count: int
    healthy_node_count: int
    total_capacity_mbps: int
    average_load_percent: float


class NetworkStats(BaseModel):
    """Aggregate view of the whole control plane.

    Deliberately expensive: it scans the fleet and the replica table to answer a
    question that changes slowly. That read-often / change-rarely profile is exactly
    what makes it the designated caching target in Lab 4.
    """

    nodes_total: int
    nodes_by_status: dict[str, int]
    fleet_capacity_mbps: int
    fleet_average_load_percent: float
    stale_node_count: int = Field(
        description="Nodes whose last heartbeat is older than the staleness threshold, "
        "regardless of their stored status.",
    )
    assets_total: int
    assets_published: int
    replicas_total: int
    replicas_cached: int
    replica_coverage_percent: float
    purges_in_flight: int
    regions: list[RegionStats]
