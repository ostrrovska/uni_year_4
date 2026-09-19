from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> PageParams:
    """Enforce a bounded page size on every collection endpoint.

    An unbounded list endpoint is a latent outage: one `GET /nodes` against a fleet
    of 100k rows would serialize the whole table into memory. The cap is a hard
    ceiling rather than a default the caller can override.
    """
    return PageParams(limit=limit, offset=offset)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
