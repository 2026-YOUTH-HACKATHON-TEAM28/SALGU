from datetime import date

import httpx
import pytest

from property_recommendation.kakao_commute import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
    UnsupportedCommuteConditionError,
)
from property_recommendation.models import PropertyCandidate


def _candidate(row: int, lot_address: str) -> PropertyCandidate:
    return PropertyCandidate(
        source_table="officetel_rentals",
        source_row=row,
        housing_type="officetel",
        region_address="서울특별시 마포구 공덕동",
        lot_address=lot_address,
        building_name=f"살구오피스텔 {row}",
        rent_type="월세",
        deposit_manwon=1000,
        monthly_rent_manwon=50,
        area_m2=25,
        floor=5,
        construction_year=2020,
        contract_date=date(2026, 11, 1),
        median_deposit_manwon=1000,
        median_monthly_rent_manwon=50,
        transaction_count=5,
        area_bucket_m2=25,
    )


def test_config_does_not_expose_api_key() -> None:
    config = KakaoCommuteConfig(api_key="secret-rest-key")

    assert "secret-rest-key" not in repr(config)


@pytest.mark.asyncio
async def test_regions_use_nearest_locations_and_transfer_limit() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        assert request.headers["Authorization"] == "KakaoAK test-key"
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(200, json={"documents": [{"x": "127.027", "y": "37.498"}]})
        if request.url.path.endswith("address.json"):
            coordinates = {
                "서울특별시 마포구": ("126.901", "37.566"),
                "서울특별시 송파구": ("127.105", "37.514"),
            }
            if query in coordinates:
                x, y = coordinates[query]
                return httpx.Response(200, json={"documents": [{"x": x, "y": y}]})
            return httpx.Response(200, json={"documents": []})
        if request.url.path.endswith("publictraffic"):
            route_calls += 1
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "routes": [
                        {"properties": {"totalTime": 1800, "transfers": 2}},
                        {"properties": {"totalTime": 2100, "transfers": 1}},
                    ],
                },
            )
        return httpx.Response(200, json={"documents": []})

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(
            api_key="test-key",
            max_region_routes=1,
            retry_count=0,
        ),
        client=client,
    )

    result = await provider.measure_regions(
        "강남역",
        ["서울특별시 마포구", "서울특별시 송파구"],
        max_transfers=1,
    )

    assert list(result) == ["서울특별시 송파구"]
    assert result["서울특별시 송파구"].minutes == 35
    assert result["서울특별시 송파구"].transfers == 1
    assert route_calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_properties_are_measured_by_full_address_with_limit() -> None:
    geocoded_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(200, json={"documents": [{"x": "127.027", "y": "37.498"}]})
        if request.url.path.endswith("address.json"):
            geocoded_queries.append(str(query))
            return httpx.Response(200, json={"documents": [{"x": "126.951", "y": "37.543"}]})
        if request.url.path.endswith("publictraffic"):
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "routes": [
                        {"properties": {"totalTime": 1921, "transfers": 0}}
                    ],
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(
            api_key="test-key",
            max_property_routes=1,
            retry_count=0,
        ),
        client=client,
    )
    first, second = _candidate(1, "10-1"), _candidate(2, "10-2")

    result = await provider.measure_properties("강남역", [first, second])

    assert result[first.key].minutes == 33
    assert second.key not in result
    assert geocoded_queries == ["서울특별시 마포구 공덕동 10-1"]
    await client.aclose()


@pytest.mark.asyncio
async def test_property_measurement_is_distributed_across_regions() -> None:
    geocoded_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(200, json={"documents": [{"x": "127.027", "y": "37.498"}]})
        if request.url.path.endswith("address.json"):
            geocoded_queries.append(str(query))
            return httpx.Response(200, json={"documents": [{"x": "126.951", "y": "37.543"}]})
        if request.url.path.endswith("publictraffic"):
            return httpx.Response(
                200,
                json={"routes": [{"properties": {"totalTime": 1800, "transfers": 1}}]},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(
            api_key="test-key", max_property_routes=2, retry_count=0
        ),
        client=client,
    )
    first = _candidate(1, "10-1")
    same_region = _candidate(2, "10-2")
    other_region = _candidate(3, "20-1").model_copy(
        update={"region_address": "서울특별시 용산구 한남동"}
    )

    result = await provider.measure_properties(
        "강남역", [first, same_region, other_region]
    )

    assert first.key in result
    assert same_region.key not in result
    assert other_region.key in result
    assert geocoded_queries == [
        "서울특별시 마포구 공덕동 10-1",
        "서울특별시 용산구 한남동 20-1",
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_bus_headway_condition_fails_explicitly() -> None:
    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(api_key="test-key", retry_count=0), client=client
    )

    with pytest.raises(UnsupportedCommuteConditionError):
        await provider.measure_regions(
            "강남역", ["서울특별시 마포구"], max_bus_headway_min=10
        )

    await client.aclose()
