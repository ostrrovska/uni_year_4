"""ORM models.

Every model must be imported here: Alembic's autogenerate walks `Base.metadata`,
and a model that is never imported is invisible to it.
"""

from app.models.asset import Asset
from app.models.asset_replica import AssetReplica
from app.models.distribution_rule import DistributionRule
from app.models.edge_node import EdgeNode
from app.models.enums import (
    AssetStatus,
    NodeStatus,
    PurgeResult,
    PurgeScope,
    PurgeStatus,
    ReplicaState,
)
from app.models.node_heartbeat import NodeHeartbeat
from app.models.purge_acknowledgement import PurgeAcknowledgement
from app.models.purge_event import PurgeEvent
from app.models.region import Region

__all__ = [
    "Asset",
    "AssetReplica",
    "AssetStatus",
    "DistributionRule",
    "EdgeNode",
    "NodeHeartbeat",
    "NodeStatus",
    "PurgeAcknowledgement",
    "PurgeEvent",
    "PurgeResult",
    "PurgeScope",
    "PurgeStatus",
    "Region",
    "ReplicaState",
]
