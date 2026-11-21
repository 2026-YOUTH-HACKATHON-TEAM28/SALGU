from __future__ import annotations

from typing import ClassVar

import pytest

from property_recommendation.models import (
    CommuteMetric,
    RealtorLocationCandidate,
    RealtorSearchInput,
    TransitLeg,
)
from property_recommendation.public_data import AgencyRecord, SqlPublicDataRepository
from property_recommendation.realtor import DatabaseRealtorService


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class FakeSession:
    async def execute(self, statement, params):
        query = str(statement)
        if "public.bus_routes" in query:
            return FakeResult(
                [
                    {
                        "route_name": "7016",
                        "headway_min": 12,
                        "first_time": "04:30",
                        "last_time": "23:20",
                    }
                ]
            )
        if "public.subway_stations" in query:
            return FakeResult(
                [
                    {
                        "station_name": "공덕",
                        "line_name": "5호선",
                        "headway_min": 6,
                        "first_time": "05:30",
                        "last_time": "24:10",
                        "scheduled_departures": 180,
                    }
                ]
            )
        if "public.bus_stops" in query:
            return FakeResult(
                [
                    {
                        "metric_key": "candidate",
                        "stop_name": "공덕역",
                        "ars_id": "14001",
                        "distance_m": 210.4,
                        "route_names": ["7016", "마포01"],
                    }
                ]
            )
        raise AssertionError(f"예상하지 못한 SQL: {query}")


@pytest.mark.asyncio
async def test_public_transport_tables_enrich_commute() -> None:
    repository = SqlPublicDataRepository(FakeSession())
    metric = CommuteMetric(
        minutes=35,
        transfers=1,
        origin_longitude=126.951,
        origin_latitude=37.543,
        legs=[
            TransitLeg(
                mode="bus",
                minutes=8,
                distance_m=2500,
                route_names=["7016번"],
            ),
            TransitLeg(
                mode="subway",
                minutes=20,
                distance_m=10000,
                start_name="공덕역",
                end_name="강남역",
                route_names=["5호선"],
            ),
        ],
    )

    result = await repository.enrich_commutes(
        {"candidate": metric},
        include_nearby_stops=True,
    )

    enriched = result["candidate"]
    assert enriched.bus_headway_min == 12
    assert enriched.legs[0].first_time == "04:30"
    assert enriched.legs[1].headway_min == 6
    assert enriched.legs[1].scheduled_departures == 180
    assert enriched.nearby_bus_stops[0].route_names == ["7016", "마포01"]
    assert enriched.public_data_applied is True


class FakeAgencyRepository:
    async def find_matching_agencies(self, *, names, phones, addresses):
        return [
            AgencyRecord(
                system_id="far",
                agency_name="먼중개사",
                phone=None,
                address="서울 마포구 공덕동 3-1",
                registration_no="등록-2",
                status="영업중",
            ),
            AgencyRecord(
                system_id="near",
                agency_name="가까운중개사",
                phone="02-111-1111",
                address="서울 마포구 공덕동 1-2",
                registration_no="등록-1",
                status="영업중",
            ),
        ]


class FakeLocationProvider:
    locations: ClassVar[dict[str, tuple[float, float]]] = {
        "서울 마포구 공덕동 1-1": (126.951, 37.543),
    }

    async def locate(self, query):
        return self.locations.get(query)

    async def search_realtors(
        self, property_address, *, limit, max_distance_m
    ):
        return [
            RealtorLocationCandidate(
                place_id="kakao-near",
                name="가까운중개사",
                phone="02-111-1111",
                address="서울 마포구 공덕동 1-2",
                distance_m=45,
                longitude=126.9515,
                latitude=37.543,
                place_url="https://place.map.kakao.com/near",
            ),
            RealtorLocationCandidate(
                place_id="kakao-far",
                name="먼중개사",
                address="서울 마포구 공덕동 3-1",
                distance_m=1000,
                longitude=126.96,
                latitude=37.55,
                place_url="https://place.map.kakao.com/far",
            ),
        ]


@pytest.mark.asyncio
async def test_database_realtors_are_sorted_by_distance() -> None:
    service = DatabaseRealtorService(
        FakeAgencyRepository(),
        FakeLocationProvider(),
    )

    result = await service.find_nearest(
        RealtorSearchInput(
            property_address="서울 마포구 공덕동 1-1",
            limit=2,
        )
    )

    assert [office.place_id for office in result.offices] == ["near", "far"]
    assert result.offices[0].source == "database"
    assert result.offices[0].registration_no == "등록-1"
