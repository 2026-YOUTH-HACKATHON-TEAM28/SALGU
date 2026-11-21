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
    """추천과 별개로 확정된 매물 주소 주변 중개업소만 조회한다."""
    return await provider.find_nearest_realtors(criteria)
