from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class HousingType(StrEnum):
    OFFICETEL = "officetel"
    VILLA = "villa"


class LeaseType(StrEnum):
    MONTHLY = "monthly"
    JEONSE = "jeonse"
    SEMI_JEONSE = "semi_jeonse"


Priority = Literal["price", "commute", "bus_headway", "building_age", "area"]
PriceBand = Literal["median_or_below"]


class RecommendationInput(BaseModel):
    deposit_manwon: int = Field(ge=0)
    monthly_rent_manwon: int | None = Field(default=None, ge=0)
    deposit_approx: bool = False
    monthly_rent_approx: bool = False
    price_band: PriceBand | None = None
    housing_types: list[HousingType] = Field(
        default_factory=lambda: [HousingType.OFFICETEL, HousingType.VILLA]
    )
    lease_types: list[LeaseType] = Field(default_factory=lambda: [LeaseType.MONTHLY])
    preferred_areas: list[str] = Field(default_factory=list)
    avoid_areas: list[str] = Field(default_factory=list)
    min_area_m2: float | None = Field(default=None, gt=0)
    min_floor: int | None = None
    max_building_age_years: int | None = Field(default=None, ge=0)
    workplace: str | None = None
    max_commute_min: int | None = Field(default=None, gt=0)
    max_transfers: int | None = Field(default=None, ge=0)
    max_bus_headway_min: int | None = Field(default=None, gt=0)
    max_walk_to_station_min: int | None = Field(default=None, gt=0)
    priorities: list[Priority] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)
    history_months: int = Field(default=12, ge=1, le=60)
    as_of_date: date | None = None

    @model_validator(mode="after")
    def validate_budget(self) -> RecommendationInput:
        only_jeonse = set(self.lease_types) == {LeaseType.JEONSE}
        if not only_jeonse and self.monthly_rent_manwon is None:
            raise ValueError("월세·반전세 검색에는 monthly_rent_manwon이 필요합니다")
        has_commute_limit = any(
            value is not None
            for value in (
                self.max_commute_min,
                self.max_transfers,
                self.max_bus_headway_min,
                self.max_walk_to_station_min,
            )
        )
        if has_commute_limit and not self.workplace:
            raise ValueError("통근 조건에는 workplace가 필요합니다")
        return self

    @classmethod
    def from_condition_card(cls, card: dict[str, Any], *, limit: int = 5) -> RecommendationInput:
        """챗봇 조건 카드에서 계산에 필요한 값만 꺼낸다."""
        conditions = card.get("conditions") or {}

        def item(name: str) -> dict[str, Any]:
            value = conditions.get(name)
            return value if isinstance(value, dict) else {}

        def value(name: str, default: Any = None) -> Any:
            return item(name).get("value", default)

        workplace = item("workplace")
        return cls(
            deposit_manwon=value("deposit_manwon"),
            monthly_rent_manwon=value("monthly_rent_manwon"),
            deposit_approx=bool(item("deposit_manwon").get("approx")),
            monthly_rent_approx=bool(item("monthly_rent_manwon").get("approx")),
            price_band=value("price_band"),
            housing_types=value("housing_types", ["officetel", "villa"]),
            lease_types=value("lease_types", ["monthly"]),
            preferred_areas=value("preferred_areas", []),
            avoid_areas=value("avoid_areas", []),
            min_area_m2=value("min_area_m2"),
            min_floor=value("min_floor"),
            max_building_age_years=value("max_building_age_years"),
            workplace=workplace.get("label"),
            max_commute_min=value("max_commute_min"),
            max_transfers=value("max_transfers"),
            max_bus_headway_min=value("max_bus_headway_min"),
            max_walk_to_station_min=value("max_walk_to_station_min"),
            priorities=card.get("priorities") or [],
            limit=limit,
        )


class PropertyCandidate(BaseModel):
    source_table: str
    source_row: int
    housing_type: HousingType
    region_address: str
    lot_address: str
    building_name: str | None
    rent_type: str | None
    deposit_manwon: int
    monthly_rent_manwon: int
    area_m2: float
    floor: int | None
    construction_year: int | None
    contract_date: date
    median_deposit_manwon: float
    median_monthly_rent_manwon: float
    transaction_count: int
    area_bucket_m2: float

    @property
    def key(self) -> str:
        return "|".join(
            (
                self.housing_type,
                self.region_address,
                self.lot_address,
                self.building_name or "",
                str(self.area_bucket_m2),
            )
        )


class TransitLeg(BaseModel):
    mode: Literal["bus", "subway", "walking"]
    minutes: int = Field(ge=0)
    distance_m: int = Field(ge=0)
    guidance: str | None = None
    start_name: str | None = None
    end_name: str | None = None
    route_names: list[str] = Field(default_factory=list)


class CommuteMetric(BaseModel):
    minutes: int = Field(ge=0)
    transfers: int = Field(ge=0)
    bus_headway_min: int | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    fare_won: int | None = Field(default=None, ge=0)
    walk_to_transit_min: int | None = Field(default=None, ge=0)
    route_url: str | None = None
    legs: list[TransitLeg] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    price: float
    area: float | None = None
    building_age: float | None = None
    recency: float
    evidence: float
    commute: float | None = None


class PropertyRecommendation(BaseModel):
    name: str
    address: str
    housing_type: HousingType
    rent_type: str | None
    deposit_manwon: int
    monthly_rent_manwon: int
    area_m2: float
    floor: int | None
    construction_year: int | None
    contract_date: date
    commute_minutes: int | None = None
    transfers: int | None = None
    commute_distance_km: float | None = None
    transit_fare_won: int | None = None
    transit_legs: list[TransitLeg] = Field(default_factory=list)
    route_url: str | None = None
    station: str | None = None
    walk_to_station_min: int | None = None
    score: float
    score_breakdown: ScoreBreakdown
    applied_weights: dict[str, float]
    reasons: list[str]
    market_median_deposit_manwon: float
    market_median_monthly_rent_manwon: float
    source_table: str
    source_row: int
    transaction_count: int
    is_live_listing: Literal[False] = False


class QueryInfo(BaseModel):
    start_date: date
    end_date: date
    source_tables: list[str]
    evaluated_count: int
    evaluated_region_count: int
    commute_evaluated_count: int = 0
    commute_search_depth: int = Field(default=0, ge=0)
    commute_search_radius_km: float | None = Field(default=None, ge=0)


class RecommendationOutput(BaseModel):
    count: int
    candidates: list[PropertyRecommendation]
    query: QueryInfo
    unapplied_conditions: list[str] = Field(default_factory=list)
    applied_tolerances: list[str] = Field(default_factory=list)


class RealtorSearchInput(BaseModel):
    property_address: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=15)
    max_distance_m: int | None = Field(default=None, ge=1, le=20_000)


class RealtorOffice(BaseModel):
    place_id: str
    name: str
    phone: str | None = None
    address: str
    road_address: str | None = None
    distance_m: int = Field(ge=0)
    longitude: float
    latitude: float
    place_url: str


class RealtorSearchOutput(BaseModel):
    property_address: str
    count: int = Field(ge=0)
    offices: list[RealtorOffice] = Field(default_factory=list)

