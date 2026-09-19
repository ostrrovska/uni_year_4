import socket
from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_instance_id() -> str:
    """Identify the process that served a request.

    Resolution order: explicit INSTANCE_ID, container hostname, then "local".
    This value is diagnostic metadata only. No business logic may branch on it —
    the moment it does, instances stop being interchangeable and horizontal
    scaling (Labs 2-3) breaks.
    """
    configured = get_settings().instance_id
    if configured:
        return configured
    return socket.gethostname() or "local"
