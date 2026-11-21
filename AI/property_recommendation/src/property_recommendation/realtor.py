from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    RealtorLocationCandidate,
    RealtorOffice,
    RealtorSearchInput,
    RealtorSearchOutput,
)
from .public_data import AgencyRecord, SqlPublicDataRepository


class RealtorLocationError(ValueError):
    pass


class LocationProvider(Protocol):
    async def locate(self, query: str) -> tuple[float, float] | None: ...

    async def search_realtors(
        self,
        property_address: str,
        *,
        limit: int,
        max_distance_m: int | None,
    ) -> Sequence[RealtorLocationCandidate]: ...


class AgencyRepository(Protocol):
    async def find_matching_agencies(
        self,
        *,
        names: set[str],
        phones: set[str],
        addresses: set[str],
    ) -> Sequence[AgencyRecord]: ...


class DatabaseRealtorService:
    def __init__(
        self,
        repository: AgencyRepository,
        location_provider: LocationProvider,
    ) -> None:
        self._repository = repository
        self._location_provider = location_provider

    async def find_nearest(
        self, criteria: RealtorSearchInput
    ) -> RealtorSearchOutput:
        property_location = await self._location_provider.locate(
            criteria.property_address
        )
        if property_location is None:
            raise RealtorLocationError(
                f"매물 위치를 찾을 수 없습니다: {criteria.property_address}"
            )

        location_candidates = await self._location_provider.search_realtors(
            criteria.property_address,
            limit=45,
            max_distance_m=criteria.max_distance_m,
        )
        agencies = await self._repository.find_matching_agencies(
            names={candidate.name for candidate in location_candidates},
            phones={
                candidate.phone for candidate in location_candidates if candidate.phone
            },
            addresses={
                address
                for candidate in location_candidates
                for address in (candidate.address, candidate.road_address)
                if address
            },
        )

        offices: list[RealtorOffice] = []
        used_agencies: set[str] = set()
        for location in location_candidates:
            agency = _match_agency(location, agencies, used_agencies)
            if agency is None:
                continue
            used_agencies.add(agency.system_id)
            offices.append(
                RealtorOffice(
                    place_id=agency.system_id,
                    name=agency.agency_name,
                    phone=agency.phone,
                    address=agency.address,
                    road_address=location.road_address,
                    distance_m=location.distance_m,
                    longitude=location.longitude,
                    latitude=location.latitude,
                    place_url=location.place_url,
                    registration_no=agency.registration_no,
                    status=agency.status,
                    source="database",
                )
            )

        selected = offices[: criteria.limit]
        return RealtorSearchOutput(
            property_address=criteria.property_address,
            count=len(selected),
            offices=selected,
        )


async def find_nearest_realtors(
    criteria: RealtorSearchInput,
    session: AsyncSession,
    location_provider: LocationProvider,
) -> RealtorSearchOutput:
    """DB 중개업소 중 확정 매물과 가까운 곳을 거리순으로 반환한다."""
    service = DatabaseRealtorService(
        SqlPublicDataRepository(session),
        location_provider,
    )
    return await service.find_nearest(criteria)


def _match_agency(
    location: RealtorLocationCandidate,
    agencies: Sequence[AgencyRecord],
    used_agencies: set[str],
) -> AgencyRecord | None:
    best: tuple[int, AgencyRecord] | None = None
    location_phone = _normalize_phone(location.phone)
    location_name = _normalize_name(location.name)
    location_addresses = {
        _normalize_text(address)
        for address in (location.address, location.road_address)
        if address
    }
    for agency in agencies:
        if agency.system_id in used_agencies:
            continue
        score = 0
        if location_phone and location_phone == _normalize_phone(agency.phone):
            score += 6
        if location_name and location_name == _normalize_name(agency.agency_name):
            score += 4
        if _normalize_text(agency.address) in location_addresses:
            score += 3
        if score >= 4 and (best is None or score > best[0]):
            best = (score, agency)
    return best[1] if best else None


def _normalize_name(value: str) -> str:
    normalized = _normalize_text(value)
    for suffix in (
        "공인중개사사무소",
        "부동산중개사무소",
        "공인중개사",
        "중개사무소",
        "부동산",
    ):
        normalized = normalized.removesuffix(suffix)
    return normalized


def _normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())
