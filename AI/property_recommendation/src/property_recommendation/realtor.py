from __future__ import annotations

from typing import Protocol

from .models import RealtorSearchInput, RealtorSearchOutput


class RealtorProvider(Protocol):
    async def find_nearest_realtors(
        self, criteria: RealtorSearchInput
    ) -> RealtorSearchOutput: ...


async def find_nearest_realtors(
    criteria: RealtorSearchInput,
    provider: RealtorProvider,
) -> RealtorSearchOutput:
    """확정된 건물 주소를 기준으로 가까운 중개업소를 찾는다."""
    return await provider.find_nearest_realtors(criteria)
