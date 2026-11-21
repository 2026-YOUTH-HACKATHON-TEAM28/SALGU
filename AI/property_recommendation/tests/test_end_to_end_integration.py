import os
from datetime import date

import pytest
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from property_recommendation import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
    RealtorSearchInput,
    RecommendationInput,
    find_nearest_realtors,
    recommend_properties,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SALGU_DB_HOST") or not os.getenv("KAKAO_REST_API_KEY"),
        reason="실제 DB와 카카오 환경변수가 모두 필요합니다",
    ),
]


@pytest.mark.asyncio
async def test_recommendation_to_realtor_end_to_end() -> None:
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
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(
            api_key=os.environ["KAKAO_REST_API_KEY"],
            max_region_routes=5,
            max_property_routes=5,
        )
    )
    try:
        async with AsyncSession(engine) as session:
            base = await recommend_properties(
                RecommendationInput(
                    deposit_manwon=100_000,
                    monthly_rent_manwon=1_000,
                    history_months=60,
                    as_of_date=date.today(),
                    limit=1,
                ),
                session,
            )
            assert base.candidates
            region = base.candidates[0].address.rsplit(" ", 1)[0]

            recommendations = await recommend_properties(
                RecommendationInput(
                    deposit_manwon=100_000,
                    monthly_rent_manwon=1_000,
                    preferred_areas=[region],
                    workplace="강남역",
                    priorities=["commute"],
                    history_months=60,
                    as_of_date=date.today(),
                    limit=1,
                ),
                session,
                provider,
            )
            assert recommendations.candidates
            selected = recommendations.candidates[0]
            assert selected.commute_minutes is not None
            assert selected.transit_legs
            assert any(
                table.startswith(("bus_", "subway_"))
                for table in recommendations.query.source_tables
            )

            realtors = await find_nearest_realtors(
                RealtorSearchInput(property_address=selected.address, limit=1),
                session,
                provider,
            )
            assert realtors.offices
            assert realtors.offices[0].source == "database"
    finally:
        await provider.aclose()
        await engine.dispose()
