from typing import Any

from app.core.errors import PROBLEM_MEDIA_TYPE

_DESCRIPTIONS = {
    404: "Referenced resource does not exist.",
    409: "The request conflicts with the current state of the resource.",
    422: "Request failed validation or violated a business rule.",
    503: "A dependency required to serve the request is unavailable.",
}


def problems(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Declare problem+json failure modes so they appear in the OpenAPI document.

    Without this, generated clients and the Swagger page advertise only the happy
    path, and the error contract stays undocumented tribal knowledge.
    """
    return {
        code: {
            "description": _DESCRIPTIONS[code],
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for code in status_codes
    }


PROBLEM_SCHEMA: dict[str, Any] = {
    "title": "Problem",
    "description": "RFC 9457 problem details.",
    "type": "object",
    "properties": {
        "type": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
        "request_id": {"type": "string"},
    },
    "required": ["type", "title", "status", "detail"],
}
