import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.instance import get_instance_id

_RECORD_BUILTIN_FIELDS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line.

    Structured output is what makes Lab 5 possible: latency and instance attribution
    can be aggregated from the log stream without parsing free-form text.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "instance_id": get_instance_id(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RECORD_BUILTIN_FIELDS
            }
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level.upper())

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # RequestContextMiddleware emits a richer access line (instance, request id,
    # duration), so uvicorn's own plain-text access log would only duplicate it.
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False
