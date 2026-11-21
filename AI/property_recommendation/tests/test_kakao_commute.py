from datetime import date

import httpx
import pytest

from property_recommendation.kakao_commute import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
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
async def test_bus_headway_is_deferred_to_database_enrichment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(
                200, json={"documents": [{"x": "127.027", "y": "37.498"}]}
            )
        if request.url.path.endswith("address.json"):
            return httpx.Response(
                200, json={"documents": [{"x": "126.951", "y": "37.543"}]}
            )
        if request.url.path.endswith("publictraffic"):
            return httpx.Response(
                200,
                json={
                    "routes": [
                        {"properties": {"totalTime": 1800, "transfers": 0}}
                    ]
                },
            )
        return httpx.Response(200, json={"documents": []})

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(api_key="test-key", retry_count=0), client=client
    )

    result = await provider.measure_regions(
        "강남역", ["서울특별시 마포구"], max_bus_headway_min=10
    )

    assert result["서울특별시 마포구"].bus_headway_min is None
    await client.aclose()


@pytest.mark.asyncio
async def test_route_prefers_fewer_transfers_and_returns_transit_legs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(200, json={"documents": [{"x": "127.027", "y": "37.498"}]})
        if request.url.path.endswith("address.json"):
            return httpx.Response(200, json={"documents": [{"x": "126.951", "y": "37.543"}]})
        if request.url.path.endswith("publictraffic"):
            return httpx.Response(
                200,
                json={
                    "properties": {"landingURL": "https://map.kakao.com/route"},
                    "routes": [
                        {"properties": {"totalTime": 1500, "transfers": 2}},
                        {
                            "properties": {
                                "totalTime": 2100,
                                "transfers": 0,
                                "totalDistance": 14320,
                                "fare": {"value": 1500},
                            },
                            "steps": [
                                {
                                    "properties": {
                                        "type": "WALKING",
                                        "time": 181,
                                        "distance": 220,
                                        "guidance": "공덕역까지 도보 이동",
                                    }
                                },
                                {
                                    "properties": {
                                        "type": "SUBWAY",
                                        "time": 1800,
                                        "distance": 13800,
                                        "stops": [{"name": "공덕역"}, {"name": "강남역"}],
                                        "vehicles": [{"name": "5호선"}],
                                    }
                                },
                            ],
                        },
                    ],
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(api_key="test-key", retry_count=0), client=client
    )

    result = await provider.measure_properties("강남역", [_candidate(1, "10-1")])
    metric = result[_candidate(1, "10-1").key]

    assert metric.minutes == 35
    assert metric.transfers == 0
    assert metric.walk_to_transit_min == 4
    assert metric.distance_km == 14.32
    assert metric.fare_won == 1500
    assert metric.legs[1].route_names == ["5호선"]
    assert metric.legs[1].start_name == "공덕역"
    await client.aclose()


@pytest.mark.asyncio
async def test_location_provider_returns_coordinates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if request.url.path.endswith("address.json") and query == "서울 마포구 1-1":
            return httpx.Response(200, json={"documents": [{"x": "126.95", "y": "37.54"}]})
        return httpx.Response(200, json={"documents": []})

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(api_key="test-key", retry_count=0), client=client
    )

    result = await provider.locate("서울 마포구 1-1")

    assert result == (126.95, 37.54)
    await client.aclose()


@pytest.mark.asyncio
async def test_realtor_locations_are_returned_by_distance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("address.json"):
            return httpx.Response(
                200, json={"documents": [{"x": "126.95", "y": "37.54"}]}
            )
        if request.url.path.endswith("category.json"):
            assert request.url.params["category_group_code"] == "AG2"
            assert request.url.params["sort"] == "distance"
            return httpx.Response(
                200,
                json={
                    "meta": {"is_end": True},
                    "documents": [
                        {
                            "id": "1",
                            "place_name": "가까운중개사",
                            "phone": "02-111-1111",
                            "address_name": "서울 마포구 1-2",
                            "road_address_name": "서울 마포구 살구로 1",
                            "distance": "120",
                            "x": "126.951",
                            "y": "37.541",
                            "place_url": "https://place.map.kakao.com/1",
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"documents": []})

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(api_key="test-key", retry_count=0), client=client
    )

    result = await provider.search_realtors(
        "서울 마포구 1-1",
        limit=15,
        max_distance_m=5000,
    )

    assert result[0].name == "가까운중개사"
    assert result[0].distance_m == 120
    await client.aclose()


@pytest.mark.asyncio
async def test_region_radius_expands_by_search_depth() -> None:
    route_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal route_calls
        query = request.url.params.get("query")
        if request.url.path.endswith("keyword.json") and query == "강남역":
            return httpx.Response(200, json={"documents": [{"x": "127.0", "y": "37.5"}]})
        if request.url.path.endswith("address.json"):
            return httpx.Response(200, json={"documents": [{"x": "126.85", "y": "37.5"}]})
        if request.url.path.endswith("publictraffic"):
            route_calls += 1
            return httpx.Response(
                200,
                json={"routes": [{"properties": {"totalTime": 1800, "transfers": 0}}]},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        base_url="https://dapi.kakao.com",
        transport=httpx.MockTransport(handler),
    )
    provider = KakaoCommuteProvider(
        KakaoCommuteConfig(
            api_key="test-key",
            region_radius_steps_km=(5.0, 20.0),
            retry_count=0,
        ),
        client=client,
    )

    initial = await provider.measure_regions(
        "강남역", ["서울특별시 마포구"], search_depth=0
    )
    expanded = await provider.measure_regions(
        "강남역", ["서울특별시 마포구"], search_depth=1
    )

    assert initial == {}
    assert expanded["서울특별시 마포구"].minutes == 30
    assert route_calls == 1
    await client.aclose()
