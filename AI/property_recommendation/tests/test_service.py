from datetime import date

import pytest

from property_recommendation.models import CommuteMetric, PropertyCandidate, RecommendationInput
from property_recommendation.service import (
    CommuteProviderRequiredError,
    PropertyRecommendationService,
)


class FakeRepository:
    async def find_regions(self, criteria, start_date, end_date):
        return ["서울특별시 마포구"]

    async def find_candidates(
        self,
        criteria,
        start_date,
        end_date,
        pool_size,
        per_region_limit,
        allowed_regions=None,
    ):
        return [
            PropertyCandidate(
                source_table="officetel_rentals",
                source_row=7,
                housing_type="officetel",
                region_address="서울특별시 마포구",
                lot_address="1-1",
                building_name="살구오피스텔",
                rent_type="월세",
                deposit_manwon=1000,
                monthly_rent_manwon=45,
                area_m2=23,
                floor=4,
                construction_year=2021,
                contract_date=date(2026, 11, 1),
                median_deposit_manwon=1000,
                median_monthly_rent_manwon=45,
                transaction_count=8,
                area_bucket_m2=20,
            )
        ]


class FakeCommuteProvider:
    async def measure_regions(self, workplace, regions):
        return {
            "서울특별시 마포구": CommuteMetric(minutes=35, transfers=1)
        }

    async def measure_properties(self, workplace, candidates):
        return {
            candidate.key: CommuteMetric(minutes=32, transfers=0)
            for candidate in candidates
        }


@pytest.mark.asyncio
async def test_service_returns_ranked_property() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        as_of_date=date(2026, 11, 21),
    )

    result = await PropertyRecommendationService(FakeRepository()).recommend(criteria)

    assert result.count == 1
    assert result.candidates[0].name == "살구오피스텔"
    assert result.candidates[0].is_live_listing is False
    assert result.query.evaluated_count == 1
    assert result.candidates[0].market_median_monthly_rent_manwon == 45
    assert sum(result.candidates[0].applied_weights.values()) == pytest.approx(1, abs=0.001)


@pytest.mark.asyncio
async def test_workplace_requires_commute_provider() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        workplace="강남역",
        max_commute_min=40,
    )

    with pytest.raises(CommuteProviderRequiredError):
        await PropertyRecommendationService(FakeRepository()).recommend(criteria)


@pytest.mark.asyncio
async def test_commute_regions_are_filtered_before_properties() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        workplace="강남역",
        max_commute_min=40,
        max_transfers=1,
        as_of_date=date(2026, 11, 21),
    )

    result = await PropertyRecommendationService(
        FakeRepository(), FakeCommuteProvider()
    ).recommend(criteria)

    assert result.count == 1
    assert result.candidates[0].commute_minutes == 32
    assert result.query.evaluated_region_count == 1
