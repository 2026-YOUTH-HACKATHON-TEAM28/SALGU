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
    """매물 추천 메소드 입력."""

    deposit_manwon: int = Field(ge=0, description="최대 보증금, 단위 만원")
    monthly_rent_manwon: int | None = Field(
        default=None, ge=0, description="최대 월세, 단위 만원"
    )
    deposit_approx: bool = Field(
        default=False, description="보증금 상한 10% 여유 적용 여부"
    )
    monthly_rent_approx: bool = Field(
        default=False, description="월세 상한 10% 여유 적용 여부"
    )
    price_band: PriceBand | None = Field(
        default=None, description="건물 시세 중앙값 이하만 조회할지 여부"
    )
    housing_types: list[HousingType] = Field(
        default_factory=lambda: [HousingType.OFFICETEL, HousingType.VILLA],
        description="검색할 주택 유형",
    )
    lease_types: list[LeaseType] = Field(
        default_factory=lambda: [LeaseType.MONTHLY],
        description="검색할 계약 유형",
    )
    preferred_areas: list[str] = Field(
        default_factory=list, description="포함할 선호 구·동 이름"
    )
    avoid_areas: list[str] = Field(
        default_factory=list, description="제외할 구·동 이름"
    )
    min_area_m2: float | None = Field(
        default=None, gt=0, description="최소 전용면적, 단위 ㎡"
    )
    min_floor: int | None = Field(default=None, description="최소 층수")
    max_building_age_years: int | None = Field(
        default=None, ge=0, description="허용할 최대 건물 연식"
    )
    workplace: str | None = Field(
        default=None, description="통근 목적지 회사·학교·역 이름 또는 주소"
    )
    max_commute_min: int | None = Field(
        default=None, gt=0, description="허용할 최대 통근시간, 단위 분"
    )
    max_transfers: int | None = Field(
        default=None, ge=0, description="허용할 최대 환승 횟수"
    )
    max_bus_headway_min: int | None = Field(
        default=None, gt=0, description="허용할 최대 버스 배차간격, 단위 분"
    )
    max_walk_to_station_min: int | None = Field(
        default=None, gt=0, description="첫 승차지점까지 최대 도보시간, 단위 분"
    )
    priorities: list[Priority] = Field(
        default_factory=list, description="가중치를 높일 추천 우선순위"
    )
    limit: int = Field(
        default=5, ge=1, le=20, description="반환할 추천 매물 수, 기본 5개"
    )
    history_months: int = Field(
        default=12, ge=1, le=60, description="조회할 과거 실거래 기간, 단위 개월"
    )
    as_of_date: date | None = Field(
        default=None, description="조회 기준일, 미입력 시 실행일"
    )

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
    """추천 경로의 도보·버스·지하철 구간."""

    mode: Literal["bus", "subway", "walking"] = Field(
        description="이동수단"
    )
    minutes: int = Field(ge=0, description="구간 소요시간, 단위 분")
    distance_m: int = Field(ge=0, description="구간 이동거리, 단위 미터")
    guidance: str | None = Field(default=None, description="구간 이동 안내")
    start_name: str | None = Field(default=None, description="승차역·정류장")
    end_name: str | None = Field(default=None, description="하차역·정류장")
    route_names: list[str] = Field(
        default_factory=list, description="이용할 버스·지하철 노선명"
    )


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
    """최종 점수를 구성하는 항목별 0~1 점수."""

    price: float = Field(description="가격 점수")
    area: float | None = Field(default=None, description="면적 점수")
    building_age: float | None = Field(default=None, description="건물 연식 점수")
    recency: float = Field(description="실거래 최근성 점수")
    evidence: float = Field(description="실거래 표본 수 점수")
    commute: float | None = Field(default=None, description="통근 점수")


class PropertyRecommendation(BaseModel):
    """추천 메소드가 반환하는 건물·면적대 후보 한 건."""

    name: str = Field(description="건물명, 없으면 지번")
    address: str = Field(description="건물 전체 주소")
    housing_type: HousingType = Field(description="주택 유형")
    rent_type: str | None = Field(description="원천 데이터의 계약 유형")
    deposit_manwon: int = Field(description="대표 최신 거래 보증금, 단위 만원")
    monthly_rent_manwon: int = Field(description="대표 최신 거래 월세, 단위 만원")
    area_m2: float = Field(description="전용면적, 단위 ㎡")
    floor: int | None = Field(description="거래 층수")
    construction_year: int | None = Field(description="건축연도")
    contract_date: date = Field(description="대표 실거래 계약일")
    commute_minutes: int | None = Field(
        default=None, description="회사까지 대중교통 시간, 단위 분"
    )
    transfers: int | None = Field(default=None, description="대중교통 환승 횟수")
    commute_distance_km: float | None = Field(
        default=None, description="대중교통 경로거리, 단위 km"
    )
    transit_fare_won: int | None = Field(
        default=None, description="예상 대중교통 요금, 단위 원"
    )
    transit_legs: list[TransitLeg] = Field(
        default_factory=list, description="도보·버스·지하철 상세 경로"
    )
    route_url: str | None = Field(default=None, description="카카오맵 경로 URL")
    station: str | None = Field(default=None, description="첫 승차역·정류장")
    walk_to_station_min: int | None = Field(
        default=None, description="첫 승차지점까지 도보시간, 단위 분"
    )
    score: float = Field(description="최종 추천 점수, 0~100")
    score_breakdown: ScoreBreakdown = Field(description="항목별 추천 점수")
    applied_weights: dict[str, float] = Field(description="실제 적용한 항목별 가중치")
    reasons: list[str] = Field(description="사용자에게 보여줄 추천 근거")
    market_median_deposit_manwon: float = Field(
        description="동일 건물·면적대 보증금 중앙값, 단위 만원"
    )
    market_median_monthly_rent_manwon: float = Field(
        description="동일 건물·면적대 월세 중앙값, 단위 만원"
    )
    source_table: str = Field(description="실거래 원본 테이블")
    source_row: int = Field(description="실거래 원본 행 번호")
    transaction_count: int = Field(description="시세 계산에 사용한 실거래 수")
    is_live_listing: Literal[False] = Field(
        default=False, description="과거 실거래 후보이므로 항상 false"
    )


class QueryInfo(BaseModel):
    """추천 과정에서 실제 조회·평가한 범위."""

    start_date: date = Field(description="실거래 조회 시작일")
    end_date: date = Field(description="실거래 조회 종료일")
    source_tables: list[str] = Field(description="조회한 실거래 테이블")
    evaluated_count: int = Field(description="점수 평가 대상 매물 수")
    evaluated_region_count: int = Field(description="통근 평가 지역 수")
    commute_evaluated_count: int = Field(
        default=0, description="주소별 통근 경로를 확인한 매물 수"
    )
    commute_search_depth: int = Field(
        default=0, ge=0, description="통근권 확장 단계, 0부터 시작"
    )
    commute_search_radius_km: float | None = Field(
        default=None, ge=0, description="최종 통근권 검색 반경, 단위 km"
    )


class RecommendationOutput(BaseModel):
    """매물 추천 메소드 출력."""

    count: int = Field(description="반환한 추천 매물 수")
    candidates: list[PropertyRecommendation] = Field(
        description="추천 점수순 매물 목록, 기본 최대 5개"
    )
    query: QueryInfo = Field(description="조회·평가 범위 정보")
    unapplied_conditions: list[str] = Field(
        default_factory=list, description="데이터 한계로 적용하지 못한 조건"
    )
    applied_tolerances: list[str] = Field(
        default_factory=list, description="검색에 적용한 예산 허용 범위"
    )


class RealtorSearchInput(BaseModel):
    """확정된 매물 주변 공인중개사 검색 입력."""

    property_address: str = Field(min_length=1, description="확정된 매물 전체 주소")
    limit: int = Field(
        default=5, ge=1, le=15, description="반환할 공인중개사 수, 기본 5개"
    )
    max_distance_m: int | None = Field(
        default=None, ge=1, le=20_000, description="선택 검색 반경, 단위 미터"
    )


class RealtorOffice(BaseModel):
    """거리순 공인중개사 검색 결과 한 건."""

    place_id: str = Field(description="카카오 장소 ID")
    name: str = Field(description="공인중개사 사무소명")
    phone: str | None = Field(default=None, description="전화번호")
    address: str = Field(description="지번 주소")
    road_address: str | None = Field(default=None, description="도로명 주소")
    distance_m: int = Field(ge=0, description="확정 매물과의 직선거리, 단위 미터")
    longitude: float = Field(description="경도")
    latitude: float = Field(description="위도")
    place_url: str = Field(description="카카오맵 장소 URL")


class RealtorSearchOutput(BaseModel):
    """확정된 매물과 가까운 공인중개사 검색 출력."""

    property_address: str = Field(description="검색 기준 매물 주소")
    count: int = Field(ge=0, description="반환한 공인중개사 수")
    offices: list[RealtorOffice] = Field(
        default_factory=list, description="거리순 공인중개사 목록"
    )

