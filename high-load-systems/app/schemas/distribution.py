from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.schemas.region import RegionCode


class DistributionRuleItem(BaseModel):
    region_code: RegionCode
    priority: Annotated[int, Field(ge=0, le=1000)] = 100
    enabled: bool = True


class DistributionPolicy(BaseModel):
    """Full replacement of an asset's distribution rule set.

    Modelled as PUT-with-full-body rather than per-rule POST/DELETE so the operation
    is idempotent: a CI pipeline can declare the desired policy repeatedly without
    accumulating duplicates or needing to diff against current state.
    """

    rules: Annotated[list[DistributionRuleItem], Field(max_length=100)]

    @model_validator(mode="after")
    def _reject_duplicate_regions(self) -> "DistributionPolicy":
        codes = [rule.region_code for rule in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError("each region_code may appear at most once")
        return self


class DistributionPolicyRead(BaseModel):
    rules: list[DistributionRuleItem]
    unrestricted: bool = Field(
        description="True when no enabled rule exists, meaning the asset may be cached "
        "in every region.",
    )
