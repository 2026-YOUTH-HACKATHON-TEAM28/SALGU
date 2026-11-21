import os

import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from property_recommendation.models import CommuteMetric, TransitLeg
from property_recommendation.public_data import SqlPublicDataRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SALGU_DB_HOST"),
        reason="SALGU_DB_HOST가 없으면 실제 DB 테스트를 건너뜁니다",
    ),
]


@pytest.mark.asyncio
async def test_real_public_data_tables_enrich_commute() -> None:
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
        async with AsyncSession(engine) as session:
            bus = (
                (
                    await session.execute(
                        text(
                            "SELECT route_name FROM bus_routes "
                            "WHERE route_name IS NOT NULL AND headway IS NOT NULL LIMIT 1"
                        )
                    )
                )
                .mappings()
                .one()
            )
            subway = (
                (
                    await session.execute(
                        text(
                            "SELECT station_name, line_name FROM subway_stations "
                            "WHERE station_name IS NOT NULL AND line_name IS NOT NULL LIMIT 1"
                        )
                    )
                )
                .mappings()
                .one()
            )
            stop = (
                (
                    await session.execute(
                        text(
                            "SELECT longitude, latitude FROM bus_stops "
                            "WHERE longitude IS NOT NULL AND latitude IS NOT NULL LIMIT 1"
                        )
                    )
                )
                .mappings()
                .one()
            )
            agency = (
                (
                    await session.execute(
                        text(
                        "SELECT address, agency_name, phone FROM real_estate_agencies "
                            "WHERE address IS NOT NULL AND agency_name IS NOT NULL "
                            "AND (status IS NULL OR (status NOT LIKE '%폐업%' "
                            "AND status NOT LIKE '%휴업%')) LIMIT 1"
                        )
                    )
                )
                .mappings()
                .one()
            )

            repository = SqlPublicDataRepository(session)
            result = await repository.enrich_commutes(
                {
                    "candidate": CommuteMetric(
                        minutes=30,
                        transfers=1,
                        origin_longitude=float(stop["longitude"]),
                        origin_latitude=float(stop["latitude"]),
                        legs=[
                            TransitLeg(
                                mode="bus",
                                minutes=10,
                                distance_m=3000,
                                route_names=[bus["route_name"]],
                            ),
                            TransitLeg(
                                mode="subway",
                                minutes=15,
                                distance_m=8000,
                                start_name=subway["station_name"],
                                route_names=[subway["line_name"]],
                            ),
                        ],
                    )
                },
                include_nearby_stops=True,
            )
            agencies = await repository.find_matching_agencies(
                names={agency["agency_name"]},
                phones={agency["phone"]} if agency["phone"] else set(),
                addresses={agency["address"]},
            )
    finally:
        await engine.dispose()

    metric = result["candidate"]
    assert metric.public_data_applied is True
    assert metric.legs[0].public_data_applied is True
    assert metric.nearby_bus_stops
    assert agencies
