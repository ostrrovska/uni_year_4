import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

RegionCode = Annotated[
    str,
    Field(
        min_length=2,
        max_length=32,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        examples=["eu-central"],
    ),
]


class RegionCreate(BaseModel):
    code: RegionCode
    name: Annotated[str, Field(min_length=1, max_length=128)]
    continent: Annotated[str, Field(min_length=2, max_length=32, examples=["Europe"])]


class RegionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    continent: str
