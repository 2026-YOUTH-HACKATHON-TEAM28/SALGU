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
    async def measure_regions(
        self,
        workplace: str,
        regions: Sequence[str],
        *,
        max_transfers: int | None = None,
        max_bus_headway_min: int | None = None,
    ) -> Mapping[str, CommuteMetric]: ...

    async def measure_properties(
        self,
        workplace: str,
        candidates: Sequence[PropertyCandidate],
        *,
        max_transfers: int | None = None,
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
        """통근 가능 지역을 먼저 좁힌 뒤 실거래 매물을 점수화한다."""
        end_date = criteria.as_of_date or date.today()
        start_date = end_date - timedelta(days=criteria.history_months * 30)

        allowed_regions, region_commutes = await self._commutable_regions(
            criteria, start_date, end_date
        )
        if allowed_regions == []:
            return _empty_result(criteria, start_date, end_date, len(region_commutes))

        # 지역별 후보 수를 제한해 특정 거래 밀집 지역의 독점을 막는다.
        pool_size = max(criteria.limit * 100, 500)
        per_region_limit = max(criteria.limit * 5, 25)
        candidates = await self._repository.find_candidates(
            criteria,
            start_date,
            end_date,
            pool_size,
            per_region_limit,
            allowed_regions,
        )
        property_commutes = await self._property_commutes(criteria, candidates)

        scored = []
        for candidate in candidates:
            commute = property_commutes.get(candidate.key)
            if criteria.workplace and not _passes_commute(commute, criteria):
                continue
            scored.append(score_candidate(candidate, criteria, commute, end_date))
        scored.sort(key=lambda item: (-item.total, -item.candidate.transaction_count))

        selected = scored[: criteria.limit]
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
            ),
            unapplied_conditions=_unapplied_conditions(criteria),
            applied_tolerances=_applied_tolerances(criteria),
        )

    async def _commutable_regions(
        self,
        criteria: RecommendationInput,
        start_date: date,
        end_date: date,
    ) -> tuple[list[str] | None, Mapping[str, CommuteMetric]]:
        if not criteria.workplace:
            return None, {}
        if self._commute_provider is None:
            raise CommuteProviderRequiredError(
                "workplace가 있는 추천에는 CommuteProvider가 필요합니다"
            )

        regions = await self._repository.find_regions(criteria, start_date, end_date)
        metrics = await self._commute_provider.measure_regions(
            criteria.workplace,
            regions,
            max_transfers=criteria.max_transfers,
            max_bus_headway_min=criteria.max_bus_headway_min,
        )
        allowed = [
            region
            for region in regions
            if _passes_commute(metrics.get(region), criteria)
        ]
        return allowed, metrics

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
            max_transfers=criteria.max_transfers,
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
    if criteria.max_bus_headway_min is not None:
        if commute.bus_headway_min is None:
            return False
        if commute.bus_headway_min > criteria.max_bus_headway_min:
            return False
    return True


def _unapplied_conditions(criteria: RecommendationInput) -> list[str]:
    unapplied = []
    if criteria.max_walk_to_station_min is not None:
        unapplied.append("역 좌표가 없어 max_walk_to_station_min은 아직 반영하지 못했습니다")
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


def _empty_result(
    criteria: RecommendationInput,
    start_date: date,
    end_date: date,
    region_count: int,
) -> RecommendationOutput:
    return RecommendationOutput(
        count=0,
        candidates=[],
        query=QueryInfo(
            start_date=start_date,
            end_date=end_date,
            source_tables=["officetel_rentals", "multifamily_rentals"],
            evaluated_count=0,
            evaluated_region_count=region_count,
        ),
        unapplied_conditions=_unapplied_conditions(criteria),
        applied_tolerances=_applied_tolerances(criteria),
    )


def _to_output(item: ScoredCandidate) -> PropertyRecommendation:
    candidate = item.candidate
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
