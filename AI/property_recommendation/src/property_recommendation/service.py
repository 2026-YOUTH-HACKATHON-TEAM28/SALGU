from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    CommuteMetric,
    LeaseType,
    PropertyCandidate,
    PropertyRecommendation,
    QueryInfo,
    RecommendationInput,
    RecommendationOutput,
)
from .repository import PropertyRepository, SqlPropertyRepository
from .scoring import ScoredCandidate, score_candidate


class CommuteProviderRequiredError(ValueError):
    pass


class CommuteProvider(Protocol):
    @property
    def max_search_depth(self) -> int: ...

    def region_radius_km(self, search_depth: int) -> float: ...

    async def measure_regions(
        self,
        workplace: str,
        regions: Sequence[str],
        *,
        search_depth: int = 0,
        max_commute_min: int | None = None,
        max_transfers: int | None = None,
        max_walk_to_station_min: int | None = None,
        max_bus_headway_min: int | None = None,
    ) -> Mapping[str, CommuteMetric]: ...

    async def measure_properties(
        self,
        workplace: str,
        candidates: Sequence[PropertyCandidate],
        *,
        max_commute_min: int | None = None,
        max_transfers: int | None = None,
        max_walk_to_station_min: int | None = None,
        max_bus_headway_min: int | None = None,
    ) -> Mapping[str, CommuteMetric]: ...


class PropertyRecommendationService:
    def __init__(
        self,
        repository: PropertyRepository,
        commute_provider: CommuteProvider | None = None,
    ) -> None:
        self._repository = repository
        self._commute_provider = commute_provider

    async def recommend(self, criteria: RecommendationInput) -> RecommendationOutput:
        """통근권을 단계적으로 넓히며 실거래 매물을 점수화한다."""
        end_date = criteria.as_of_date or date.today()
        start_date = end_date - timedelta(days=criteria.history_months * 30)
        pool_size = max(criteria.limit * 100, 500)
        per_region_limit = max(criteria.limit * 5, 25)
        if criteria.workplace and self._commute_provider is None:
            raise CommuteProviderRequiredError(
                "workplace가 있는 추천에는 CommuteProvider가 필요합니다"
            )

        regions = (
            await self._repository.find_regions(criteria, start_date, end_date)
            if criteria.workplace
            else []
        )
        max_depth = (
            self._commute_provider.max_search_depth
            if criteria.workplace and self._commute_provider
            else 0
        )
        region_commutes: dict[str, CommuteMetric] = {}
        last_candidates: Sequence[PropertyCandidate] = []
        last_property_commutes: Mapping[str, CommuteMetric] = {}
        if criteria.workplace and not regions and self._commute_provider:
            return _result(
                criteria,
                [],
                start_date,
                end_date,
                [],
                {},
                {},
                0,
                self._commute_provider.region_radius_km(0),
            )

        for search_depth in range(max_depth + 1):
            allowed_regions: list[str] | None = None
            search_radius_km: float | None = None
            if criteria.workplace and self._commute_provider:
                search_radius_km = self._commute_provider.region_radius_km(search_depth)
                measured = await self._commute_provider.measure_regions(
                    criteria.workplace,
                    regions,
                    search_depth=search_depth,
                    max_commute_min=criteria.max_commute_min,
                    max_transfers=criteria.max_transfers,
                    max_walk_to_station_min=criteria.max_walk_to_station_min,
                    max_bus_headway_min=criteria.max_bus_headway_min,
                )
                region_commutes.update(measured)
                allowed_regions = [
                    region
                    for region in regions
                    if _passes_commute(region_commutes.get(region), criteria)
                ]
                if not allowed_regions:
                    continue

            # 지역별 후보 수를 제한해 특정 거래 밀집 지역의 독점을 막는다.
            last_candidates = await self._repository.find_candidates(
                criteria,
                start_date,
                end_date,
                pool_size,
                per_region_limit,
                allowed_regions,
            )
            last_property_commutes = await self._property_commutes(
                criteria, last_candidates
            )
            scored = _score_candidates(
                last_candidates,
                last_property_commutes,
                criteria,
                end_date,
            )
            if scored or not criteria.workplace or search_depth == max_depth:
                return _result(
                    criteria,
                    scored[: criteria.limit],
                    start_date,
                    end_date,
                    last_candidates,
                    region_commutes,
                    last_property_commutes,
                    search_depth,
                    search_radius_km,
                )

        return _result(
            criteria,
            [],
            start_date,
            end_date,
            last_candidates,
            region_commutes,
            last_property_commutes,
            max_depth,
            (
                self._commute_provider.region_radius_km(max_depth)
                if self._commute_provider and criteria.workplace
                else None
            ),
        )

    async def _property_commutes(
        self,
        criteria: RecommendationInput,
        candidates: Sequence[PropertyCandidate],
    ) -> Mapping[str, CommuteMetric]:
        if not criteria.workplace or self._commute_provider is None or not candidates:
            return {}
        return await self._commute_provider.measure_properties(
            criteria.workplace,
            candidates,
            max_commute_min=criteria.max_commute_min,
            max_transfers=criteria.max_transfers,
            max_walk_to_station_min=criteria.max_walk_to_station_min,
            max_bus_headway_min=criteria.max_bus_headway_min,
        )


async def recommend_properties(
    criteria: RecommendationInput,
    session: AsyncSession,
    commute_provider: CommuteProvider | None = None,
) -> RecommendationOutput:
    service = PropertyRecommendationService(
        SqlPropertyRepository(session), commute_provider
    )
    return await service.recommend(criteria)


def _passes_commute(
    commute: CommuteMetric | None,
    criteria: RecommendationInput,
) -> bool:
    if commute is None:
        return False
    if criteria.max_commute_min is not None and commute.minutes > criteria.max_commute_min:
        return False
    if criteria.max_transfers is not None and commute.transfers > criteria.max_transfers:
        return False
    if criteria.max_walk_to_station_min is not None:
        if commute.walk_to_transit_min is None:
            return False
        if commute.walk_to_transit_min > criteria.max_walk_to_station_min:
            return False
    if criteria.max_bus_headway_min is not None:
        if commute.bus_headway_min is None:
            return False
        if commute.bus_headway_min > criteria.max_bus_headway_min:
            return False
    return True


def _unapplied_conditions(criteria: RecommendationInput) -> list[str]:
    unapplied = []
    if LeaseType.SEMI_JEONSE in criteria.lease_types:
        unapplied.append("원천 데이터에 반전세 구분이 없어 월세 거래로 조회했습니다")
    return unapplied


def _applied_tolerances(criteria: RecommendationInput) -> list[str]:
    tolerances = []
    if criteria.deposit_approx:
        tolerances.append("보증금 상한 +10%")
    if criteria.monthly_rent_approx:
        tolerances.append("월세 상한 +10%")
    return tolerances


def _result(
    criteria: RecommendationInput,
    selected: Sequence[ScoredCandidate],
    start_date: date,
    end_date: date,
    candidates: Sequence[PropertyCandidate],
    region_commutes: Mapping[str, CommuteMetric],
    property_commutes: Mapping[str, CommuteMetric],
    search_depth: int,
    search_radius_km: float | None,
) -> RecommendationOutput:
    region_count = len(region_commutes) if criteria.workplace else len(
        {candidate.region_address for candidate in candidates}
    )
    return RecommendationOutput(
        count=len(selected),
        candidates=[_to_output(item) for item in selected],
        query=QueryInfo(
            start_date=start_date,
            end_date=end_date,
            source_tables=["officetel_rentals", "multifamily_rentals"],
            evaluated_count=len(candidates),
            evaluated_region_count=region_count,
            commute_evaluated_count=len(property_commutes),
            commute_search_depth=search_depth,
            commute_search_radius_km=search_radius_km,
        ),
        unapplied_conditions=_unapplied_conditions(criteria),
        applied_tolerances=_applied_tolerances(criteria),
    )


def _to_output(item: ScoredCandidate) -> PropertyRecommendation:
    candidate = item.candidate
    first_transit = (
        next(
            (
                leg
                for leg in item.commute.legs
                if leg.mode in {"bus", "subway"}
            ),
            None,
        )
        if item.commute
        else None
    )
    return PropertyRecommendation(
        name=candidate.building_name or candidate.lot_address,
        address=f"{candidate.region_address} {candidate.lot_address}".strip(),
        housing_type=candidate.housing_type,
        rent_type=candidate.rent_type,
        deposit_manwon=candidate.deposit_manwon,
        monthly_rent_manwon=candidate.monthly_rent_manwon,
        area_m2=candidate.area_m2,
        floor=candidate.floor,
        construction_year=candidate.construction_year,
        contract_date=candidate.contract_date,
        commute_minutes=item.commute.minutes if item.commute else None,
        transfers=item.commute.transfers if item.commute else None,
        commute_distance_km=item.commute.distance_km if item.commute else None,
        transit_fare_won=item.commute.fare_won if item.commute else None,
        transit_legs=item.commute.legs if item.commute else [],
        route_url=item.commute.route_url if item.commute else None,
        station=first_transit.start_name if first_transit else None,
        walk_to_station_min=(
            item.commute.walk_to_transit_min if item.commute else None
        ),
        score=item.total,
        score_breakdown=item.breakdown,
        applied_weights=item.weights,
        reasons=item.reasons,
        market_median_deposit_manwon=candidate.median_deposit_manwon,
        market_median_monthly_rent_manwon=candidate.median_monthly_rent_manwon,
        source_table=candidate.source_table,
        source_row=candidate.source_row,
        transaction_count=candidate.transaction_count,
    )


def _score_candidates(
    candidates: Sequence[PropertyCandidate],
    property_commutes: Mapping[str, CommuteMetric],
    criteria: RecommendationInput,
    end_date: date,
) -> list[ScoredCandidate]:
    scored = []
    for candidate in candidates:
        commute = property_commutes.get(candidate.key)
        if criteria.workplace and not _passes_commute(commute, criteria):
            continue
        scored.append(score_candidate(candidate, criteria, commute, end_date))
    scored.sort(key=lambda item: (-item.total, -item.candidate.transaction_count))
    return scored
