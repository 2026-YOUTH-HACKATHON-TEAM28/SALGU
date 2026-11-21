from datetime import date

import pytest

from property_recommendation.models import PropertyCandidate, RecommendationInput
from property_recommendation.scoring import score_candidate


def candidate(*, rent: int, contract_date: date, count: int) -> PropertyCandidate:
    return PropertyCandidate(
        source_table="officetel_rentals",
        source_row=1,
        housing_type="officetel",
        region_address="서울특별시 마포구",
        lot_address="1-1",
        building_name="살구오피스텔",
        rent_type="월세",
        deposit_manwon=1000,
        monthly_rent_manwon=rent,
        area_m2=25,
        floor=5,
        construction_year=2020,
        contract_date=contract_date,
        median_deposit_manwon=1000,
        median_monthly_rent_manwon=rent,
        transaction_count=count,
        area_bucket_m2=25,
    )


def test_recent_affordable_candidate_scores_higher() -> None:
    end_date = date(2026, 11, 21)
    criteria = RecommendationInput(
        deposit_manwon=2000,
        monthly_rent_manwon=60,
        as_of_date=end_date,
    )
    better = score_candidate(
        candidate(rent=40, contract_date=date(2026, 11, 1), count=10),
        criteria,
        None,
        end_date,
    )
    worse = score_candidate(
        candidate(rent=55, contract_date=date(2026, 1, 1), count=1),
        criteria,
        None,
        end_date,
    )

    assert better.total > worse.total


def test_exact_budget_keeps_half_price_score() -> None:
    end_date = date(2026, 11, 21)
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        as_of_date=end_date,
    )

    result = score_candidate(
        candidate(rent=50, contract_date=end_date, count=3),
        criteria,
        None,
        end_date,
    )

    assert result.breakdown.price == 0.5
    assert sum(result.weights.values()) == pytest.approx(1, abs=0.001)

