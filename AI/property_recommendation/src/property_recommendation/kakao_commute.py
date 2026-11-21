from __future__ import annotations

import asyncio
import math
import os
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Self, TypeVar

import httpx

from .models import CommuteMetric, PropertyCandidate


class KakaoCommuteError(RuntimeError):
    """카카오 위치·길찾기 요청을 완료하지 못한 경우 발생한다."""


class UnsupportedCommuteConditionError(ValueError):
    """카카오 API가 제공하지 않는 통근 조건에 사용한다."""


@dataclass(frozen=True, slots=True)
class KakaoCommuteConfig:
    api_key: str = field(repr=False)
    timeout_seconds: float = 10.0
    max_concurrency: int = 8
    max_region_routes: int = 30
    max_property_routes: int = 30
    cache_ttl_seconds: int = 21_600
    cache_size: int = 2_000
    retry_count: int = 2

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("api_key가 비어 있습니다")
        positive_values = (
            self.timeout_seconds,
            self.max_concurrency,
            self.max_region_routes,
            self.max_property_routes,
            self.cache_ttl_seconds,
            self.cache_size,
        )
        if any(value <= 0 for value in positive_values):
            raise ValueError("시간·동시성·호출 상한·캐시 설정은 0보다 커야 합니다")
        if self.retry_count < 0:
            raise ValueError("retry_count는 0 이상이어야 합니다")

    @classmethod
    def from_env(cls) -> KakaoCommuteConfig:
        api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
        if not api_key:
            raise KakaoCommuteError("KAKAO_REST_API_KEY 환경변수가 필요합니다")
        return cls(api_key=api_key)


@dataclass(frozen=True, slots=True)
class Coordinate:
    longitude: float
    latitude: float


T = TypeVar("T")


class _TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: int, max_size: int) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        item = self._items.get(key)
        if item is None:
            return None
        created_at, value = item
        if time.monotonic() - created_at > self._ttl:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)


class KakaoCommuteProvider:
    """카카오 위치 검색과 대중교통 길찾기로 통근값을 계산한다."""

    _BASE_URL = "https://dapi.kakao.com"

    def __init__(
        self,
        config: KakaoCommuteConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=self._BASE_URL,
            timeout=config.timeout_seconds,
        )
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._coordinates = _TtlCache[Coordinate](
            config.cache_ttl_seconds, config.cache_size
        )
        self._routes = _TtlCache[CommuteMetric](
            config.cache_ttl_seconds, config.cache_size
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def measure_regions(
        self,
        workplace: str,
        regions: Sequence[str],
        *,
        max_transfers: int | None = None,
        max_bus_headway_min: int | None = None,
    ) -> Mapping[str, CommuteMetric]:
        self._validate_conditions(max_bus_headway_min)
        destination = await self._geocode(workplace, prefer_keyword=True)
        if destination is None:
            raise KakaoCommuteError(f"근무지 위치를 찾을 수 없습니다: {workplace}")

        unique_regions = list(dict.fromkeys(regions))
        coordinates = await asyncio.gather(
            *(self._geocode(region) for region in unique_regions)
        )
        located = [
            (region, coordinate)
            for region, coordinate in zip(unique_regions, coordinates, strict=True)
            if coordinate is not None
        ]
        located.sort(key=lambda item: _distance_km(item[1], destination))
        selected = located[: self._config.max_region_routes]
        metrics = await asyncio.gather(
            *(
                self._route(coordinate, destination, max_transfers)
                for _, coordinate in selected
            )
        )
        return {
            region: metric
            for (region, _), metric in zip(selected, metrics, strict=True)
            if metric is not None
        }

    async def measure_properties(
        self,
        workplace: str,
        candidates: Sequence[PropertyCandidate],
        *,
        max_transfers: int | None = None,
        max_bus_headway_min: int | None = None,
    ) -> Mapping[str, CommuteMetric]:
        self._validate_conditions(max_bus_headway_min)
        destination = await self._geocode(workplace, prefer_keyword=True)
        if destination is None:
            raise KakaoCommuteError(f"근무지 위치를 찾을 수 없습니다: {workplace}")

        # 한 지역이 호출량을 독점하지 않도록 지역별 후보를 번갈아 선택한다.
        selected = _interleave_by_region(
            candidates, self._config.max_property_routes
        )
        candidates_by_address: dict[str, list[PropertyCandidate]] = {}
        for candidate in selected:
            address = f"{candidate.region_address} {candidate.lot_address}".strip()
            candidates_by_address.setdefault(address, []).append(candidate)

        addresses = list(candidates_by_address)
        coordinates = await asyncio.gather(
            *(self._geocode(address) for address in addresses)
        )
        coordinate_by_address = dict(zip(addresses, coordinates, strict=True))
        unique_coordinates = list(
            dict.fromkeys(
                coordinate
                for coordinate in coordinates
                if coordinate is not None
            )
        )
        routes = await asyncio.gather(
            *(
                self._route(coordinate, destination, max_transfers)
                for coordinate in unique_coordinates
            )
        )
        route_by_coordinate = dict(zip(unique_coordinates, routes, strict=True))

        result: dict[str, CommuteMetric] = {}
        for address, address_candidates in candidates_by_address.items():
            coordinate = coordinate_by_address[address]
            metric = route_by_coordinate.get(coordinate) if coordinate else None
            if metric is not None:
                result.update(
                    (candidate.key, metric) for candidate in address_candidates
                )
        return result

    @staticmethod
    def _validate_conditions(max_bus_headway_min: int | None) -> None:
        if max_bus_headway_min is not None:
            raise UnsupportedCommuteConditionError(
                "카카오 대중교통 API는 버스 배차간격을 제공하지 않습니다"
            )

    async def _geocode(
        self, query: str, *, prefer_keyword: bool = False
    ) -> Coordinate | None:
        normalized = " ".join(query.split())
        cache_key = f"{'keyword' if prefer_keyword else 'address'}:{normalized}"
        cached = self._coordinates.get(cache_key)
        if cached is not None:
            return cached

        endpoints = (
            ("/v2/local/search/keyword.json", "/v2/local/search/address.json")
            if prefer_keyword
            else ("/v2/local/search/address.json", "/v2/local/search/keyword.json")
        )
        for endpoint in endpoints:
            data = await self._request(endpoint, {"query": normalized, "size": 1})
            documents = data.get("documents") or []
            if documents:
                coordinate = Coordinate(
                    longitude=float(documents[0]["x"]),
                    latitude=float(documents[0]["y"]),
                )
                self._coordinates.set(cache_key, coordinate)
                return coordinate
        return None

    async def _route(
        self,
        origin: Coordinate,
        destination: Coordinate,
        max_transfers: int | None,
    ) -> CommuteMetric | None:
        cache_key = ":".join(
            (
                f"{origin.longitude:.6f}",
                f"{origin.latitude:.6f}",
                f"{destination.longitude:.6f}",
                f"{destination.latitude:.6f}",
                str(max_transfers),
            )
        )
        cached = self._routes.get(cache_key)
        if cached is not None:
            return cached

        data = await self._request(
            "/v2/routing/publictraffic",
            {
                "start_x": origin.longitude,
                "start_y": origin.latitude,
                "end_x": destination.longitude,
                "end_y": destination.latitude,
            },
        )
        candidates: list[CommuteMetric] = []
        for route in data.get("routes") or []:
            properties = route.get("properties") or {}
            total_seconds = properties.get("totalTime")
            transfers = properties.get("transfers")
            if total_seconds is None or transfers is None:
                continue
            candidates.append(
                CommuteMetric(
                    minutes=math.ceil(float(total_seconds) / 60),
                    transfers=int(transfers),
                )
            )
        if not candidates:
            return None

        within_transfer_limit = [
            item
            for item in candidates
            if max_transfers is None or item.transfers <= max_transfers
        ]
        comparable = within_transfer_limit or candidates
        best = min(comparable, key=lambda item: (item.minutes, item.transfers))
        self._routes.set(cache_key, best)
        return best

    async def _request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        for attempt in range(self._config.retry_count + 1):
            try:
                async with self._semaphore:
                    response = await self._client.get(
                        path,
                        params=params,
                        headers={"Authorization": f"KakaoAK {self._config.api_key}"},
                    )
                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < self._config.retry_count
                ):
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise KakaoCommuteError("카카오 API 응답 형식이 올바르지 않습니다")
                return payload
            except (httpx.HTTPError, ValueError) as error:
                if attempt < self._config.retry_count and isinstance(
                    error, (httpx.TimeoutException, httpx.NetworkError)
                ):
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                raise KakaoCommuteError(
                    f"카카오 API 요청 실패: {path}"
                ) from error
        raise KakaoCommuteError(f"카카오 API 요청 실패: {path}")


def _distance_km(left: Coordinate, right: Coordinate) -> float:
    lat1, lat2 = map(math.radians, (left.latitude, right.latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(right.longitude - left.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6_371 * 2 * math.asin(math.sqrt(value))


def _interleave_by_region(
    candidates: Sequence[PropertyCandidate], limit: int
) -> list[PropertyCandidate]:
    by_region: OrderedDict[str, list[PropertyCandidate]] = OrderedDict()
    for candidate in candidates:
        by_region.setdefault(candidate.region_address, []).append(candidate)

    selected: list[PropertyCandidate] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for region_candidates in by_region.values():
            if depth < len(region_candidates):
                selected.append(region_candidates[depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1
    return selected
