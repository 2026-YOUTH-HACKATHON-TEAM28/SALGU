from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LeaseType, PropertyCandidate, RecommendationInput


class PropertyRepository(Protocol):
    async def find_regions(
        self,
        criteria: RecommendationInput,
        start_date: date,
        end_date: date,
    ) -> list[str]: ...

    async def find_candidates(
        self,
        criteria: RecommendationInput,
        start_date: date,
        end_date: date,
        pool_size: int,
        per_region_limit: int,
        allowed_regions: Sequence[str] | None = None,
    ) -> list[PropertyCandidate]: ...


class SqlPropertyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_regions(
        self,
        criteria: RecommendationInput,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        where, params = _filters(criteria, start_date, end_date, include_budget=True)
        statement = text(_REGION_QUERY.format(where=" AND ".join(where))).bindparams(
            bindparam("housing_types", expanding=True)
        )
        rows = await self._session.execute(statement, params)
        return list(rows.scalars())

    async def find_candidates(
        self,
        criteria: RecommendationInput,
        start_date: date,
        end_date: date,
        pool_size: int,
        per_region_limit: int,
        allowed_regions: Sequence[str] | None = None,
    ) -> list[PropertyCandidate]:
        # 필터·집계·1차 랭킹은 DB에서 끝내고 상위 후보만 Python으로 보낸다.
        eligible_where, params = _filters(
            criteria, start_date, end_date, include_budget=True
        )
        market_where, _ = _filters(
            criteria, start_date, end_date, include_budget=False
        )
        expanding = [bindparam("housing_types", expanding=True)]
        if allowed_regions is not None:
            if not allowed_regions:
                return []
            eligible_where.append("r.region_address IN :allowed_regions")
            market_where.append("r.region_address IN :allowed_regions")
            params["allowed_regions"] = list(allowed_regions)
            expanding.append(bindparam("allowed_regions", expanding=True))

        deposit_cap = criteria.deposit_manwon * (1.1 if criteria.deposit_approx else 1)
        rent_cap = criteria.monthly_rent_manwon
        if rent_cap is not None and criteria.monthly_rent_approx:
            rent_cap *= 1.1
        params.update(
            {
                "pool_size": pool_size,
                "per_region_limit": per_region_limit,
                "deposit_cap": deposit_cap,
                "rent_cap": rent_cap or 0,
                "has_rent_cap": rent_cap is not None,
                "median_only": criteria.price_band == "median_or_below",
            }
        )
        statement = text(
            _QUERY.format(
                eligible_where=" AND ".join(eligible_where),
                market_where=" AND ".join(market_where),
            )
        ).bindparams(*expanding)
        rows = (await self._session.execute(statement, params)).mappings()
        return [PropertyCandidate.model_validate(row) for row in rows]


def _filters(
    criteria: RecommendationInput,
    start_date: date,
    end_date: date,
    *,
    include_budget: bool,
) -> tuple[list[str], dict[str, object]]:
    deposit_cap = criteria.deposit_manwon * (1.1 if criteria.deposit_approx else 1)
    params: dict[str, object] = {
        "housing_types": [item.value for item in criteria.housing_types],
        "start_date": start_date,
        "end_date": end_date,
        "deposit_cap": deposit_cap,
    }
    where = [
        "r.housing_type IN :housing_types",
        "r.contract_date BETWEEN :start_date AND :end_date",
        "r.exclusive_area_m2 IS NOT NULL",
        "r.region_address IS NOT NULL",
        "r.lot_address IS NOT NULL",
    ]

    if include_budget:
        where.append("r.deposit_manwon <= :deposit_cap")
    if include_budget and criteria.monthly_rent_manwon is not None:
        params["rent_cap"] = criteria.monthly_rent_manwon * (
            1.1 if criteria.monthly_rent_approx else 1
        )
        where.append("r.monthly_rent_manwon <= :rent_cap")

    lease_clauses = []
    if LeaseType.JEONSE in criteria.lease_types:
        lease_clauses.append("r.monthly_rent_manwon = 0")
    if {LeaseType.MONTHLY, LeaseType.SEMI_JEONSE} & set(criteria.lease_types):
        lease_clauses.append("r.monthly_rent_manwon > 0")
    if lease_clauses:
        where.append("(" + " OR ".join(lease_clauses) + ")")

    if criteria.min_area_m2 is not None:
        params["min_area_m2"] = criteria.min_area_m2
        where.append("r.exclusive_area_m2 >= :min_area_m2")
    if criteria.min_floor is not None:
        params["min_floor"] = criteria.min_floor
        where.append("r.floor >= :min_floor")
    if criteria.max_building_age_years is not None:
        params["min_construction_year"] = end_date.year - criteria.max_building_age_years
        where.append("r.construction_year >= :min_construction_year")

    preferred = []
    for index, area in enumerate(criteria.preferred_areas):
        name = f"preferred_area_{index}"
        params[name] = f"%{area}%"
        preferred.append(f"r.region_address ILIKE :{name}")
    if preferred:
        where.append("(" + " OR ".join(preferred) + ")")

    for index, area in enumerate(criteria.avoid_areas):
        name = f"avoid_area_{index}"
        params[name] = f"%{area}%"
        where.append(f"r.region_address NOT ILIKE :{name}")
    return where, params


_RENTALS_CTE = """
WITH rentals AS (
    SELECT
        'officetel_rentals' AS source_table,
        source_row,
        'officetel' AS housing_type,
        region_address,
        lot_address,
        building_name,
        rent_type,
        exclusive_area_m2,
        deposit_manwon,
        monthly_rent_manwon,
        floor,
        construction_year,
        contract_date
    FROM public.officetel_rentals
    UNION ALL
    SELECT
        'multifamily_rentals',
        source_row,
        'villa',
        region_address,
        lot_address,
        building_name,
        rent_type,
        exclusive_area_m2,
        deposit_manwon,
        monthly_rent_manwon,
        floor,
        construction_year,
        contract_date
    FROM public.multifamily_rentals
)
"""


_REGION_QUERY = _RENTALS_CTE + """
SELECT DISTINCT r.region_address
FROM rentals r
WHERE {where}
ORDER BY r.region_address
"""


_QUERY = _RENTALS_CTE + """
, eligible AS (
    SELECT
        r.*,
        floor(r.exclusive_area_m2 / 5) * 5 AS area_bucket_m2
    FROM rentals r
    WHERE {eligible_where}
),
market AS (
    SELECT
        r.*,
        floor(r.exclusive_area_m2 / 5) * 5 AS area_bucket_m2
    FROM rentals r
    WHERE {market_where}
),
statistics AS (
    SELECT
        housing_type,
        region_address,
        lot_address,
        COALESCE(building_name, '') AS building_name_key,
        area_bucket_m2,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY deposit_manwon) AS median_deposit_manwon,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY monthly_rent_manwon) AS median_monthly_rent_manwon,
        count(*) AS transaction_count
    FROM market
    GROUP BY housing_type, region_address, lot_address,
             COALESCE(building_name, ''), area_bucket_m2
),
latest AS (
    SELECT
        e.*,
        row_number() OVER (
            PARTITION BY housing_type, region_address, lot_address,
                         COALESCE(building_name, ''), area_bucket_m2
            ORDER BY contract_date DESC, source_row DESC
        ) AS latest_row
    FROM eligible e
),
combined AS (
    SELECT
        l.*,
        s.median_deposit_manwon,
        s.median_monthly_rent_manwon,
        s.transaction_count,
        (
            (
                CASE
                    WHEN :deposit_cap = 0 THEN CASE WHEN l.deposit_manwon = 0 THEN 1.0 ELSE 0.0 END
                    ELSE 0.5 + 0.5 * GREATEST(0, 1 - l.deposit_manwon / CAST(:deposit_cap AS numeric))
                END
                + CASE
                    WHEN NOT :has_rent_cap THEN 0
                    WHEN :rent_cap = 0 THEN CASE WHEN l.monthly_rent_manwon = 0 THEN 1.0 ELSE 0.0 END
                    ELSE 0.5 + 0.5 * GREATEST(0, 1 - l.monthly_rent_manwon / CAST(:rent_cap AS numeric))
                END
            ) / CASE WHEN :has_rent_cap THEN 2 ELSE 1 END
        ) * 0.6
        + (0.2 + 0.8 * exp(-GREATEST(:end_date - l.contract_date, 0) / 180.0)) * 0.25
        + LEAST(ln(1 + s.transaction_count) / ln(21), 1.0) * 0.15 AS preliminary_score
    FROM latest l
    JOIN statistics s
      ON s.housing_type = l.housing_type
     AND s.region_address = l.region_address
     AND s.lot_address = l.lot_address
     AND s.building_name_key = COALESCE(l.building_name, '')
     AND s.area_bucket_m2 = l.area_bucket_m2
    WHERE l.latest_row = 1
      AND (
          NOT :median_only
          OR (
              l.deposit_manwon <= s.median_deposit_manwon
              AND l.monthly_rent_manwon <= s.median_monthly_rent_manwon
          )
      )
),
region_ranked AS (
    SELECT
        c.*,
        row_number() OVER (
            PARTITION BY c.region_address
            ORDER BY c.preliminary_score DESC, c.contract_date DESC
        ) AS region_rank
    FROM combined c
)
SELECT
    source_table,
    source_row,
    housing_type,
    region_address,
    lot_address,
    building_name,
    rent_type,
    deposit_manwon,
    monthly_rent_manwon,
    exclusive_area_m2::float AS area_m2,
    floor,
    construction_year,
    contract_date,
    median_deposit_manwon::float,
    median_monthly_rent_manwon::float,
    transaction_count,
    area_bucket_m2::float
FROM region_ranked
WHERE region_rank <= :per_region_limit
ORDER BY preliminary_score DESC, contract_date DESC
LIMIT :pool_size
"""
