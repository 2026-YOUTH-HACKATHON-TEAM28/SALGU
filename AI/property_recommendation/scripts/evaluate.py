from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from property_recommendation.models import LeaseType, RecommendationInput
from property_recommendation.service import PropertyRecommendationService
from property_recommendation.repository import SqlPropertyRepository


@dataclass(frozen=True)
class Scenario:
    name: str
    criteria: RecommendationInput
    expect_results: bool


SCENARIOS = [
    Scenario(
        "마포 오피스텔 월세",
        RecommendationInput(
            deposit_manwon=5000,
            monthly_rent_manwon=100,
            housing_types=["officetel"],
            preferred_areas=["마포구"],
            price_band="median_or_below",
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        True,
    ),
    Scenario(
        "관악 빌라 월세",
        RecommendationInput(
            deposit_manwon=3000,
            monthly_rent_manwon=80,
            housing_types=["villa"],
            preferred_areas=["관악구"],
            min_area_m2=20,
            min_floor=1,
            max_building_age_years=20,
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        True,
    ),
    Scenario(
        "강서 빌라 전세",
        RecommendationInput(
            deposit_manwon=15000,
            housing_types=["villa"],
            lease_types=["jeonse"],
            preferred_areas=["강서구"],
            min_area_m2=33,
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        True,
    ),
    Scenario(
        "서울 저예산 월세",
        RecommendationInput(
            deposit_manwon=1000,
            monthly_rent_manwon=50,
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        True,
    ),
    Scenario(
        "근사 예산 월세",
        RecommendationInput(
            deposit_manwon=1000,
            monthly_rent_manwon=50,
            deposit_approx=True,
            monthly_rent_approx=True,
            preferred_areas=["마포구"],
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        True,
    ),
    Scenario(
        "결과 없음 경계값",
        RecommendationInput(
            deposit_manwon=0,
            monthly_rent_manwon=0,
            lease_types=["monthly"],
            limit=5,
            as_of_date=date(2026, 11, 21),
        ),
        False,
    ),
]


def database_url() -> URL:
    return URL.create(
        "postgresql+asyncpg",
        username=os.environ["SALGU_DB_USER"],
        password=os.environ["SALGU_DB_PASSWORD"],
        host=os.environ["SALGU_DB_HOST"],
        port=int(os.getenv("SALGU_DB_PORT", "5432")),
        database=os.getenv("SALGU_DB_NAME", "postgres"),
    )


async def evaluate() -> dict[str, Any]:
    engine = create_async_engine(
        database_url(),
        connect_args={"ssl": "require"},
        hide_parameters=True,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    results = []
    try:
        for scenario in SCENARIOS:
            started = time.perf_counter()
            async with sessions() as session:
                service = PropertyRecommendationService(SqlPropertyRepository(session))
                output = await service.recommend(scenario.criteria)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            violations = validate(scenario, output.model_dump())
            results.append(
                {
                    "name": scenario.name,
                    "count": output.count,
                    "duration_ms": duration_ms,
                    "evaluated_count": output.query.evaluated_count,
                    "evaluated_region_count": output.query.evaluated_region_count,
                    "scores": [item.score for item in output.candidates],
                    "transaction_counts": [
                        item.transaction_count for item in output.candidates
                    ],
                    "addresses": [item.address for item in output.candidates],
                    "violations": violations,
                }
            )
    finally:
        await engine.dispose()

    return {
        "passed": all(not result["violations"] for result in results),
        "scenario_count": len(results),
        "results": results,
    }


def validate(scenario: Scenario, output: dict[str, Any]) -> list[str]:
    criteria = scenario.criteria
    candidates = output["candidates"]
    violations = []
    if scenario.expect_results != bool(candidates):
        violations.append("결과 유무가 예상과 다름")
    if len(candidates) > criteria.limit:
        violations.append("limit 초과")

    scores = [candidate["score"] for candidate in candidates]
    if scores != sorted(scores, reverse=True):
        violations.append("점수 내림차순 아님")

    seen = set()
    deposit_cap = criteria.deposit_manwon * (1.1 if criteria.deposit_approx else 1)
    rent_cap = None
    if criteria.monthly_rent_manwon is not None:
        rent_cap = criteria.monthly_rent_manwon * (
            1.1 if criteria.monthly_rent_approx else 1
        )

    for candidate in candidates:
        key = (
            candidate["housing_type"],
            candidate["address"],
            candidate["name"],
            int(candidate["area_m2"] // 5),
        )
        if key in seen:
            violations.append("동일 건물·면적대 중복")
        seen.add(key)
        if candidate["deposit_manwon"] > deposit_cap:
            violations.append("보증금 상한 위반")
        if rent_cap is not None and candidate["monthly_rent_manwon"] > rent_cap:
            violations.append("월세 상한 위반")
        if candidate["housing_type"] not in criteria.housing_types:
            violations.append("주택 유형 위반")
        if criteria.min_area_m2 and candidate["area_m2"] < criteria.min_area_m2:
            violations.append("최소 면적 위반")
        if criteria.min_floor is not None and candidate["floor"] < criteria.min_floor:
            violations.append("최소 층 위반")
        if criteria.max_building_age_years is not None:
            min_year = scenario.criteria.as_of_date.year - criteria.max_building_age_years
            if candidate["construction_year"] < min_year:
                violations.append("건물 연식 위반")
        if criteria.price_band == "median_or_below":
            if candidate["deposit_manwon"] > candidate["market_median_deposit_manwon"]:
                violations.append("보증금 중앙값 초과")
            if candidate["monthly_rent_manwon"] > candidate["market_median_monthly_rent_manwon"]:
                violations.append("월세 중앙값 초과")
        only_jeonse = set(criteria.lease_types) == {LeaseType.JEONSE}
        if only_jeonse and candidate["monthly_rent_manwon"] != 0:
            violations.append("전세에 월세 포함")
        if not only_jeonse and candidate["monthly_rent_manwon"] <= 0:
            violations.append("월세 후보의 월세가 0 이하")
        if not 0 <= candidate["score"] <= 100:
            violations.append("점수 범위 위반")
    return sorted(set(violations))


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))
    except Exception as error:
        raise SystemExit(f"평가 실패: {type(error).__name__}: {error}") from None
