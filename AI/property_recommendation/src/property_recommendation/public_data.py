from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CommuteMetric, NearbyBusStop, TransitLeg


@dataclass(frozen=True, slots=True)
class AgencyRecord:
    system_id: str
    agency_name: str
    phone: str | None
    address: str
    registration_no: str | None
    status: str | None


@dataclass(frozen=True, slots=True)
class _TransitProfile:
    headway_min: float | None
    first_time: str | None
    last_time: str | None
    scheduled_departures: int | None = None


class SqlPublicDataRepository:
    """서울시 교통·중개업소 DB 데이터를 추천 결과에 결합한다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enrich_commutes(
        self,
        metrics: Mapping[str, CommuteMetric],
        *,
        include_nearby_stops: bool,
    ) -> dict[str, CommuteMetric]:
        bus_names = {
            name
            for metric in metrics.values()
            for leg in metric.legs
            if leg.mode == "bus"
            for name in leg.route_names
        }
        subway_pairs = {
            (station, line)
            for metric in metrics.values()
            for leg in metric.legs
            if leg.mode == "subway"
            for station in (leg.start_name, leg.end_name)
            if station
            for line in (leg.route_names or [""])
        }
        bus_profiles = await self._bus_profiles(bus_names)
        subway_profiles = await self._subway_profiles(subway_pairs)
        nearby_stops_by_key: dict[str, list[NearbyBusStop]] = {}
        if include_nearby_stops:
            origins = {
                key: (metric.origin_longitude, metric.origin_latitude)
                for key, metric in metrics.items()
                if metric.origin_longitude is not None
                and metric.origin_latitude is not None
            }
            nearby_stops_by_key = await self._nearby_bus_stops(origins)

        enriched: dict[str, CommuteMetric] = {}
        for key, metric in metrics.items():
            legs = [
                _enrich_leg(leg, bus_profiles, subway_profiles)
                for leg in metric.legs
            ]
            bus_headways = [
                leg.headway_min
                for leg in legs
                if leg.mode == "bus" and leg.headway_min is not None
            ]
            nearby_stops = nearby_stops_by_key.get(
                key, metric.nearby_bus_stops
            )

            has_bus = any(leg.mode == "bus" for leg in legs)
            has_subway = any(leg.mode == "subway" for leg in legs)
            tables: list[str] = []
            if has_bus:
                tables.append("bus_routes")
            if has_subway:
                tables.extend(
                    [
                        "subway_stations",
                        "subway_first_last",
                        "subway_timetables",
                    ]
                )
            if key in nearby_stops_by_key:
                tables.extend(["bus_stops", "bus_route_stops"])
            enriched[key] = metric.model_copy(
                update={
                    "legs": legs,
                    "bus_headway_min": (
                        max(bus_headways)
                        if bus_headways
                        else (0.0 if not has_bus else None)
                    ),
                    "nearby_bus_stops": nearby_stops,
                    "public_data_applied": bool(tables),
                    "public_data_tables": tables,
                }
            )
        return enriched

    async def find_agencies(
        self,
        property_address: str,
        *,
        limit: int = 50,
    ) -> list[AgencyRecord]:
        district, legal_dong = _address_area(property_address)
        where = list(_ACTIVE_AGENCY_FILTERS)
        params: dict[str, object] = {"limit": limit}
        if district:
            where.append("district_name = :district")
            params["district"] = district
        if legal_dong:
            where.append("legal_dong_name = :legal_dong")
            params["legal_dong"] = legal_dong

        statement = text(_AGENCY_QUERY.format(where=" AND ".join(where)))
        rows = (await self._session.execute(statement, params)).mappings()
        return [_to_agency(row) for row in rows]

    async def find_matching_agencies(
        self,
        *,
        names: set[str],
        phones: set[str],
        addresses: set[str],
    ) -> list[AgencyRecord]:
        identity_filters: list[str] = []
        params: dict[str, object] = {"limit": 100}
        expanding: list[str] = []
        for column, parameter, values in (
            ("agency_name", "names", names),
            ("phone", "phones", phones),
            ("address", "addresses", addresses),
        ):
            if values:
                identity_filters.append(f"{column} IN :{parameter}")
                params[parameter] = sorted(values)
                expanding.append(parameter)
        if not identity_filters:
            return []

        where = [
            *_ACTIVE_AGENCY_FILTERS,
            f"({' OR '.join(identity_filters)})",
        ]
        statement = text(
            _AGENCY_QUERY.format(where=" AND ".join(where))
        ).bindparams(*(bindparam(name, expanding=True) for name in expanding))
        rows = (await self._session.execute(statement, params)).mappings()
        return [_to_agency(row) for row in rows]

    async def _bus_profiles(
        self, route_names: set[str]
    ) -> dict[str, _TransitProfile]:
        if not route_names:
            return {}
        variants = sorted(
            {
                variant
                for name in route_names
                for variant in (name, name.removesuffix("번"), f"{name}번")
            }
        )
        statement = text(_BUS_PROFILE_QUERY).bindparams(
            bindparam("route_names", expanding=True)
        )
        rows = (
            await self._session.execute(statement, {"route_names": variants})
        ).mappings()
        return {
            _normalize_route(row["route_name"]): _TransitProfile(
                headway_min=_float_or_none(row["headway_min"]),
                first_time=_text_or_none(row["first_time"]),
                last_time=_text_or_none(row["last_time"]),
            )
            for row in rows
        }

    async def _subway_profiles(
        self, station_lines: set[tuple[str, str]]
    ) -> dict[tuple[str, str], _TransitProfile]:
        if not station_lines:
            return {}
        station_names = sorted(
            {
                variant
                for station, _ in station_lines
                for variant in (station, station.removesuffix("역"))
            }
        )
        statement = text(_SUBWAY_PROFILE_QUERY).bindparams(
            bindparam("station_names", expanding=True)
        )
        rows = (
            await self._session.execute(
                statement, {"station_names": station_names}
            )
        ).mappings()
        return {
            (
                _normalize_station(row["station_name"]),
                _normalize_route(row["line_name"]),
            ): _TransitProfile(
                headway_min=_float_or_none(row["headway_min"]),
                first_time=_text_or_none(row["first_time"]),
                last_time=_text_or_none(row["last_time"]),
                scheduled_departures=int(row["scheduled_departures"] or 0),
            )
            for row in rows
        }

    async def _nearby_bus_stops(
        self,
        origins: Mapping[str, tuple[float, float]],
        *,
        radius_m: int = 800,
        limit: int = 5,
    ) -> dict[str, list[NearbyBusStop]]:
        if not origins:
            return {}
        payload = [
            {
                "metric_key": key,
                "longitude": longitude,
                "latitude": latitude,
            }
            for key, (longitude, latitude) in origins.items()
        ]
        rows = (
            await self._session.execute(
                text(_NEARBY_BUS_STOPS_QUERY),
                {
                    "origins": json.dumps(payload),
                    "radius_m": radius_m,
                    "limit": limit,
                },
            )
        ).mappings()
        result: dict[str, list[NearbyBusStop]] = {key: [] for key in origins}
        for row in rows:
            result[str(row["metric_key"])].append(
                NearbyBusStop(
                    name=str(row["stop_name"]),
                    ars_id=row["ars_id"],
                    distance_m=round(float(row["distance_m"])),
                    route_names=list(row["route_names"] or []),
                )
            )
        return result


def _enrich_leg(
    leg: TransitLeg,
    bus_profiles: Mapping[str, _TransitProfile],
    subway_profiles: Mapping[tuple[str, str], _TransitProfile],
) -> TransitLeg:
    profiles: list[_TransitProfile] = []
    if leg.mode == "bus":
        profiles = [
            bus_profiles[key]
            for name in leg.route_names
            if (key := _normalize_route(name)) in bus_profiles
        ]
    elif leg.mode == "subway":
        station_names = {
            _normalize_station(name)
            for name in (leg.start_name, leg.end_name)
            if name
        }
        line_names = {_normalize_route(line) for line in leg.route_names}
        profiles = [
            profile
            for (station, line), profile in subway_profiles.items()
            if station in station_names and (not line_names or line in line_names)
        ]
        if not profiles:
            profiles = [
                profile
                for (station, _), profile in subway_profiles.items()
                if station in station_names
            ]
    if not profiles:
        return leg

    headways = [item.headway_min for item in profiles if item.headway_min is not None]
    departures = [
        item.scheduled_departures
        for item in profiles
        if item.scheduled_departures is not None
    ]
    return leg.model_copy(
        update={
            "headway_min": max(headways) if headways else None,
            "first_time": min(
                (item.first_time for item in profiles if item.first_time),
                default=None,
            ),
            "last_time": max(
                (item.last_time for item in profiles if item.last_time),
                default=None,
            ),
            "scheduled_departures": max(departures) if departures else None,
            "public_data_applied": True,
        }
    )


def _address_area(address: str) -> tuple[str | None, str | None]:
    tokens = address.split()
    district = next((token for token in tokens if token.endswith("구")), None)
    legal_dong = next(
        (
            token
            for token in tokens
            if token.endswith(("동", "가", "읍", "면"))
        ),
        None,
    )
    return district, legal_dong


def _to_agency(row: Mapping[str, object]) -> AgencyRecord:
    return AgencyRecord(
        system_id=str(row["system_id"]),
        agency_name=str(row["agency_name"]),
        phone=str(row["phone"]) if row["phone"] else None,
        address=str(row["address"]),
        registration_no=(
            str(row["registration_no"]) if row["registration_no"] else None
        ),
        status=str(row["status"]) if row["status"] else None,
    )


def _normalize_route(value: str | None) -> str:
    return re.sub(r"[\s번]", "", (value or "").lower())


def _normalize_station(value: str | None) -> str:
    return re.sub(r"[\s역]", "", (value or "").lower())


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


def _text_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


_BUS_PROFILE_QUERY = """
SELECT
    route_name,
    max(COALESCE(headway, min_headway, max_headway)::float) AS headway_min,
    min(first_time::text) AS first_time,
    max(last_time::text) AS last_time
FROM public.bus_routes
WHERE route_name IN :route_names
GROUP BY route_name
"""


_SUBWAY_PROFILE_QUERY = """
WITH first_last AS (
    SELECT
        station_code,
        line_number,
        min(first_time::text) AS first_time,
        max(last_time::text) AS last_time
    FROM public.subway_first_last
    GROUP BY station_code, line_number
), departures AS (
    SELECT
        station_code,
        line_number,
        day_type,
        direction,
        departure_time_service_seconds,
        lead(departure_time_service_seconds) OVER (
            PARTITION BY station_code, line_number, day_type, direction
            ORDER BY departure_time_service_seconds
        ) AS next_departure_seconds
    FROM (
        SELECT DISTINCT
            station_code,
            line_number,
            day_type,
            direction,
            departure_time_service_seconds
        FROM public.subway_timetables
        WHERE departure_time_service_seconds IS NOT NULL
    ) timetable
), directional_frequency AS (
    SELECT
        station_code,
        line_number,
        day_type,
        direction,
        percentile_cont(0.5) WITHIN GROUP (
            ORDER BY (next_departure_seconds - departure_time_service_seconds) / 60.0
        ) FILTER (
            WHERE next_departure_seconds > departure_time_service_seconds
              AND next_departure_seconds - departure_time_service_seconds <= 7200
        ) AS headway_min,
        count(*) AS scheduled_departures
    FROM departures
    GROUP BY station_code, line_number, day_type, direction
), frequency AS (
    SELECT
        station_code,
        line_number,
        max(headway_min) AS headway_min,
        max(scheduled_departures) AS scheduled_departures
    FROM directional_frequency
    GROUP BY station_code, line_number
)
SELECT
    station.station_name,
    station.line_name,
    first_last.first_time,
    first_last.last_time,
    frequency.headway_min::float,
    frequency.scheduled_departures
FROM public.subway_stations station
LEFT JOIN first_last
  ON first_last.station_code = station.station_code
 AND first_last.line_number = station.line_number
LEFT JOIN frequency
  ON frequency.station_code = station.station_code
 AND frequency.line_number = station.line_number
WHERE station.station_name IN :station_names
"""


_NEARBY_BUS_STOPS_QUERY = """
WITH origins AS (
    SELECT *
    FROM jsonb_to_recordset(CAST(:origins AS jsonb)) AS origin(
        metric_key text,
        longitude double precision,
        latitude double precision
    )
), nearby AS (
    SELECT
        origin.metric_key,
        stop.node_id,
        stop.ars_id,
        stop.stop_name,
        6371000 * acos(
            LEAST(1, GREATEST(-1,
                cos(radians(origin.latitude)) * cos(radians(stop.latitude::float))
                * cos(radians(stop.longitude::float) - radians(origin.longitude))
                + sin(radians(origin.latitude)) * sin(radians(stop.latitude::float))
            ))
        ) AS distance_m
    FROM origins origin
    JOIN public.bus_stops stop
      ON stop.longitude::float BETWEEN
         origin.longitude - :radius_m
         / greatest(111320 * abs(cos(radians(origin.latitude))), 1)
         AND origin.longitude + :radius_m
         / greatest(111320 * abs(cos(radians(origin.latitude))), 1)
     AND stop.latitude::float BETWEEN
         origin.latitude - :radius_m / 111320.0
         AND origin.latitude + :radius_m / 111320.0
    WHERE stop.longitude IS NOT NULL
      AND stop.latitude IS NOT NULL
), aggregated AS (
    SELECT
        nearby.metric_key,
        nearby.node_id,
        nearby.ars_id,
        nearby.stop_name,
        nearby.distance_m,
        array_remove(
            array_agg(DISTINCT route_stop.route_name), NULL
        ) AS route_names
    FROM nearby
    LEFT JOIN public.bus_route_stops route_stop
      ON route_stop.node_id = nearby.node_id
      OR (nearby.ars_id IS NOT NULL AND route_stop.ars_id = nearby.ars_id)
    WHERE nearby.distance_m <= :radius_m
    GROUP BY
        nearby.metric_key,
        nearby.node_id,
        nearby.ars_id,
        nearby.stop_name,
        nearby.distance_m
), ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY metric_key ORDER BY distance_m
        ) AS stop_rank
    FROM aggregated
)
SELECT
    metric_key,
    node_id,
    ars_id,
    stop_name,
    distance_m,
    route_names
FROM ranked
WHERE stop_rank <= :limit
ORDER BY metric_key, distance_m
"""


_AGENCY_QUERY = """
SELECT
    system_id,
    agency_name,
    phone,
    address,
    registration_no,
    status
FROM public.real_estate_agencies
WHERE {where}
ORDER BY agency_name
LIMIT :limit
"""


_ACTIVE_AGENCY_FILTERS = (
    "system_id IS NOT NULL",
    "agency_name IS NOT NULL",
    "address IS NOT NULL",
    "(status IS NULL OR (status NOT LIKE '%폐업%' AND status NOT LIKE '%휴업%'))",
)
