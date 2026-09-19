import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnprocessableError
from app.models.distribution_rule import DistributionRule
from app.models.region import Region
from app.schemas.distribution import DistributionPolicy, DistributionRuleItem
from app.services import assets as assets_service


async def get_policy(session: AsyncSession, asset_id: uuid.UUID) -> list[DistributionRuleItem]:
    await assets_service.get_asset(session, asset_id)
    rows = await session.execute(
        select(DistributionRule, Region.code)
        .join(Region, Region.id == DistributionRule.region_id)
        .where(DistributionRule.asset_id == asset_id)
        .order_by(DistributionRule.priority, Region.code)
    )
    return [
        DistributionRuleItem(region_code=code, priority=rule.priority, enabled=rule.enabled)
        for rule, code in rows.all()
    ]


async def replace_policy(
    session: AsyncSession, asset_id: uuid.UUID, policy: DistributionPolicy
) -> list[DistributionRuleItem]:
    """Replace an asset's whole rule set in one transaction.

    Delete-then-insert rather than a per-rule diff: the caller states the desired end
    state, so the operation is idempotent and a half-applied policy — some regions
    updated, others not — cannot be observed by a concurrent reader.
    """
    await assets_service.get_asset(session, asset_id)

    requested_codes = [rule.region_code for rule in policy.rules]
    regions: Sequence[Region] = (
        await session.scalars(select(Region).where(Region.code.in_(requested_codes)))
    ).all()
    region_ids_by_code = {region.code: region.id for region in regions}

    unknown = sorted(set(requested_codes) - region_ids_by_code.keys())
    if unknown:
        raise UnprocessableError(
            "Distribution policy references regions that do not exist.",
            unknown_region_codes=unknown,
        )

    await session.execute(delete(DistributionRule).where(DistributionRule.asset_id == asset_id))
    session.add_all(
        [
            DistributionRule(
                asset_id=asset_id,
                region_id=region_ids_by_code[rule.region_code],
                priority=rule.priority,
                enabled=rule.enabled,
            )
            for rule in policy.rules
        ]
    )
    await session.commit()
    return await get_policy(session, asset_id)
