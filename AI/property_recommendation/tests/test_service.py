from datetime import date

import pytest

from property_recommendation.models import (
    CommuteMetric,
    PropertyCandidate,
    RecommendationInput,
    TransitLeg,
)
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
    @property
    def max_search_depth(self):
        return 0

    def region_radius_km(self, search_depth):
        return 10.0

    async def measure_regions(
        self,
        workplace,
        regions,
        *,
        search_depth=0,
        max_commute_min=None,
        max_transfers=None,
        max_walk_to_station_min=None,
        max_bus_headway_min=None,
    ):
        return {
            "서울특별시 마포구": CommuteMetric(minutes=35, transfers=1)
        }

    async def measure_properties(
        self,
        workplace,
        candidates,
        *,
        max_commute_min=None,
        max_transfers=None,
        max_walk_to_station_min=None,
        max_bus_headway_min=None,
    ):
        return {
            candidate.key: CommuteMetric(
                minutes=32,
                transfers=0,
                distance_km=14.2,
                fare_won=1500,
                walk_to_transit_min=4,
                legs=[
                    TransitLeg(
                        mode="subway",
                        minutes=25,
                        distance_m=12000,
                        start_name="공덕역",
                        end_name="강남역",
                        route_names=["5호선", "2호선"],
                    )
                ],
            )
            for candidate in candidates
        }


class RegionOnlyCommuteProvider(FakeCommuteProvider):
    async def measure_properties(
        self,
        workplace,
        candidates,
        *,
        max_commute_min=None,
        max_transfers=None,
        max_walk_to_station_min=None,
        max_bus_headway_min=None,
    ):
        return {}


class ExpansionCommuteProvider(FakeCommuteProvider):
    def __init__(self):
        self.measured_depths = []

    @property
    def max_search_depth(self):
        return 1

    def region_radius_km(self, search_depth):
        return (10.0, 20.0)[search_depth]

    async def measure_regions(self, workplace, regions, *, search_depth=0, **kwargs):
        self.measured_depths.append(search_depth)
        if search_depth == 0:
            return {}
        return await super().measure_regions(
            workplace, regions, search_depth=search_depth, **kwargs
        )


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
    assert result.candidates[0].commute_distance_km == 14.2
    assert result.candidates[0].station == "공덕역"
    assert result.candidates[0].transit_legs[0].route_names == ["5호선", "2호선"]
    assert result.query.evaluated_region_count == 1
    assert result.query.commute_evaluated_count == 1


@pytest.mark.asyncio
async def test_region_estimate_is_not_used_as_property_commute() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        workplace="강남역",
        max_commute_min=40,
        as_of_date=date(2026, 11, 21),
    )

    result = await PropertyRecommendationService(
        FakeRepository(), RegionOnlyCommuteProvider()
    ).recommend(criteria)

    assert result.count == 0
    assert result.query.commute_evaluated_count == 0


@pytest.mark.asyncio
async def test_commute_search_expands_when_initial_radius_has_no_result() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        workplace="강남역",
        max_commute_min=40,
        as_of_date=date(2026, 11, 21),
    )
    provider = ExpansionCommuteProvider()

    result = await PropertyRecommendationService(
        FakeRepository(), provider
    ).recommend(criteria)

    assert result.count == 1
    assert provider.measured_depths == [0, 1]
    assert result.query.commute_search_depth == 1
    assert result.query.commute_search_radius_km == 20


@pytest.mark.asyncio
async def test_walk_to_first_transit_limit_is_applied() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        workplace="강남역",
        max_walk_to_station_min=3,
        as_of_date=date(2026, 11, 21),
    )

    result = await PropertyRecommendationService(
        FakeRepository(), FakeCommuteProvider()
    ).recommend(criteria)

    assert result.count == 0
