import os

import pytest

from property_recommendation.kakao_commute import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_kakao_public_transit_route() -> None:
    api_key = os.getenv("KAKAO_REST_API_KEY")
    if not api_key:
        pytest.skip("KAKAO_REST_API_KEY가 없습니다")

    config = KakaoCommuteConfig(
        api_key=api_key,
        max_region_routes=1,
        retry_count=0,
    )
    async with KakaoCommuteProvider(config) as provider:
        result = await provider.measure_regions(
            "강남역",
            ["서울특별시 마포구 공덕동"],
            max_transfers=2,
        )

    metric = result["서울특별시 마포구 공덕동"]
    assert metric.minutes > 0
    assert metric.transfers <= 2
