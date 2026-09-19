from fastapi import APIRouter

from app.api.routes import assets, health, nodes, purges, regions, routing, stats

API_V1_PREFIX = "/api/v1"

api_router = APIRouter()

# Health lives outside the versioned prefix: it is infrastructure, polled by the
# container runtime and the load balancer, and must not move when the API version does.
api_router.include_router(health.router)

v1_router = APIRouter(prefix=API_V1_PREFIX)
for module in (regions, nodes, assets, routing, purges, stats):
    v1_router.include_router(module.router)

api_router.include_router(v1_router)
