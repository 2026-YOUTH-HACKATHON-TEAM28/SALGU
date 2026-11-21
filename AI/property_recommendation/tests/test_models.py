import pytest
from pydantic import ValidationError

from property_recommendation import find_nearest_realtors, recommend_properties
from property_recommendation.models import (
    PropertyRecommendation,
    QueryInfo,
    RealtorOffice,
    RealtorSearchInput,
    RealtorSearchOutput,
    RecommendationInput,
    RecommendationOutput,
    ScoreBreakdown,
    TransitLeg,
)


def test_condition_card_is_converted_to_input() -> None:
    card = {
        "conditions": {
            "deposit_manwon": {"value": 1000, "approx": True},
            "monthly_rent_manwon": {"value": 50},
            "price_band": {"value": "median_or_below"},
            "housing_types": {"value": ["officetel"]},
            "preferred_areas": {"value": ["신촌"]},
            "workplace": {"value": "place", "label": "강남역"},
            "max_commute_min": {"value": 40},
        },
        "priorities": ["commute", "price"],
    }

    result = RecommendationInput.from_condition_card(card, limit=3)

    assert result.deposit_manwon == 1000
    assert result.deposit_approx is True
    assert result.preferred_areas == ["신촌"]
    assert result.price_band == "median_or_below"
    assert result.workplace == "강남역"
    assert result.limit == 3


def test_walk_limit_requires_workplace() -> None:
    with pytest.raises(ValidationError):
        RecommendationInput(
            deposit_manwon=1000,
            monthly_rent_manwon=50,
            max_walk_to_station_min=10,
        )


def test_recommendation_defaults_to_five_properties() -> None:
    criteria = RecommendationInput(
        deposit_manwon=1000,
        monthly_rent_manwon=50,
    )

    assert criteria.limit == 5


def test_property_and_realtor_search_are_separate_methods() -> None:
    assert recommend_properties is not find_nearest_realtors
    assert RealtorSearchInput(property_address="서울 마포구 1-1").limit == 5


@pytest.mark.parametrize(
    "model",
    [
        RecommendationInput,
        TransitLeg,
        ScoreBreakdown,
        PropertyRecommendation,
        QueryInfo,
        RecommendationOutput,
        RealtorSearchInput,
        RealtorOffice,
        RealtorSearchOutput,
    ],
)
def test_public_io_fields_have_descriptions(model) -> None:
    properties = model.model_json_schema()["properties"]

    assert all(field.get("description") for field in properties.values())

