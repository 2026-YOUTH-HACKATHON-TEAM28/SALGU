import os
from datetime import date

import pytest
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from property_recommendation.models import RecommendationInput
from property_recommendation.repository import SqlPropertyRepository


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SALGU_DB_HOST"),
        reason="SALGU_DB_HOST가 없으면 실제 DB 테스트를 건너뜁니다",
    ),
]


@pytest.mark.asyncio
async def test_real_database_query() -> None:
    end_date = date(2026, 11, 21)
    regions = []
    candidates = []
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["SALGU_DB_USER"],
        password=os.environ["SALGU_DB_PASSWORD"],
        host=os.environ["SALGU_DB_HOST"],
        port=int(os.getenv("SALGU_DB_PORT", "5432")),
        database=os.getenv("SALGU_DB_NAME", "postgres"),
    )
    engine = create_async_engine(
        url,
        connect_args={"ssl": "require"},
        hide_parameters=True,
    )
    try:
        try:
            async with AsyncSession(engine) as session:
                repository = SqlPropertyRepository(session)
                criteria = RecommendationInput(
                    deposit_manwon=5000,
                    monthly_rent_manwon=100,
                    price_band="median_or_below",
                    preferred_areas=["마포구"],
                    as_of_date=end_date,
                )
                regions = await repository.find_regions(
                    criteria, date(2025, 11, 26), end_date
                )
                candidates = await repository.find_candidates(
                    criteria,
                    date(2025, 11, 26),
                    end_date,
                    pool_size=10,
                    per_region_limit=3,
                )
        except Exception as error:
            pytest.fail(f"DB 검증 실패: {type(error).__name__}: {error}", pytrace=False)
    finally:
        await engine.dispose()

    assert regions
    assert candidates
    assert all("마포구" in candidate.region_address for candidate in candidates)
