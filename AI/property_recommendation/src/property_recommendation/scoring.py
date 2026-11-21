from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from .models import CommuteMetric, PropertyCandidate, RecommendationInput, ScoreBreakdown


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: PropertyCandidate
    commute: CommuteMetric | None
    total: float
    breakdown: ScoreBreakdown
    weights: dict[str, float]
    reasons: list[str]


BASE_WEIGHTS = {
    "price": 0.35,
    "area": 0.10,
    "building_age": 0.10,
    "recency": 0.15,
    "evidence": 0.10,
    "commute": 0.20,
}


def score_candidate(
    candidate: PropertyCandidate,
    criteria: RecommendationInput,
    commute: CommuteMetric | None,
    end_date: date,
) -> ScoredCandidate:
    """사용 가능한 항목만 가중 평균해 0~100점으로 만든다."""
    breakdown = ScoreBreakdown(
        price=_price_score(candidate, criteria),
        area=_area_score(candidate, criteria),
        building_age=_age_score(candidate, criteria, end_date.year),
        recency=_recency_score(candidate.contract_date, end_date, criteria.history_months),
        evidence=_evidence_score(candidate.transaction_count),
        commute=_commute_score(commute, criteria),
    )
    values = breakdown.model_dump()
    weights = _weights(criteria, values)
    total = sum(values[name] * weight for name, weight in weights.items())
    return ScoredCandidate(
        candidate=candidate,
        commute=commute,
        total=round(total * 100, 2),
        breakdown=breakdown,
        weights={name: round(weight, 4) for name, weight in weights.items()},
        reasons=_reasons(candidate, criteria, commute),
    )


def _price_score(candidate: PropertyCandidate, criteria: RecommendationInput) -> float:
    parts = [_threshold_score(candidate.deposit_manwon, _budget_cap(
        criteria.deposit_manwon, criteria.deposit_approx
    ))]
    if criteria.monthly_rent_manwon is not None:
        parts.append(_threshold_score(
            candidate.monthly_rent_manwon,
            _budget_cap(criteria.monthly_rent_manwon, criteria.monthly_rent_approx),
        ))
    return round(sum(parts) / len(parts), 4)


def _threshold_score(value: float, cap: float) -> float:
    """상한선 충족은 0.5점, 여유가 클수록 최대 1점이다."""
    if cap == 0:
        return 1.0 if value == 0 else 0.0
    return round(0.5 + 0.5 * _clamp(1 - value / cap), 4)


def _area_score(candidate: PropertyCandidate, criteria: RecommendationInput) -> float | None:
    if criteria.min_area_m2 is None:
        return None
    bonus_range = max(criteria.min_area_m2 * 0.5, 1)
    bonus = _clamp((candidate.area_m2 - criteria.min_area_m2) / bonus_range)
    return round(0.5 + 0.5 * bonus, 4)


def _age_score(
    candidate: PropertyCandidate, criteria: RecommendationInput, current_year: int
) -> float | None:
    if criteria.max_building_age_years is None or candidate.construction_year is None:
        return None
    age = max(current_year - candidate.construction_year, 0)
    denominator = max(criteria.max_building_age_years, 1)
    return round(0.5 + 0.5 * _clamp(1 - age / denominator), 4)


def _recency_score(contract_date: date, end_date: date, history_months: int) -> float:
    days = max((end_date - contract_date).days, 0)
    decay_days = max(history_months * 15, 1)
    return round(0.2 + 0.8 * math.exp(-days / decay_days), 4)


def _evidence_score(transaction_count: int) -> float:
    return round(min(math.log1p(transaction_count) / math.log1p(20), 1.0), 4)


def _commute_score(
    commute: CommuteMetric | None, criteria: RecommendationInput
) -> float | None:
    if commute is None:
        return None
    parts: list[float] = []
    if criteria.max_commute_min is not None:
        parts.append(_threshold_score(commute.minutes, criteria.max_commute_min))
    if criteria.max_transfers is not None:
        parts.append(_threshold_score(commute.transfers, max(criteria.max_transfers, 1)))
    if criteria.max_bus_headway_min is not None and commute.bus_headway_min is not None:
        parts.append(_threshold_score(commute.bus_headway_min, criteria.max_bus_headway_min))
    return round(sum(parts) / len(parts), 4) if parts else None


def _weights(criteria: RecommendationInput, values: dict[str, float | None]) -> dict[str, float]:
    weights = {name: weight for name, weight in BASE_WEIGHTS.items() if values[name] is not None}
    priority_map = {"bus_headway": "commute"}
    for index, priority in enumerate(criteria.priorities):
        name = priority_map.get(priority, priority)
        if name in weights:
            weights[name] += max(0.15 - index * 0.03, 0.03)
    total = sum(weights.values())
    return {name: weight / total for name, weight in weights.items()}


def _reasons(
    candidate: PropertyCandidate,
    criteria: RecommendationInput,
    commute: CommuteMetric | None,
) -> list[str]:
    reasons = [
        f"보증금 {candidate.deposit_manwon:g}만·월세 "
        f"{candidate.monthly_rent_manwon:g}만 실거래"
    ]
    if criteria.price_band == "median_or_below":
        reasons.append("같은 건물·면적대 중앙값 이하")
    if criteria.min_area_m2 is not None:
        reasons.append(f"전용 {candidate.area_m2:g}㎡")
    if candidate.construction_year is not None:
        reasons.append(f"{candidate.construction_year}년 준공")
    if commute is not None:
        reasons.append(f"통근 {commute.minutes}분·환승 {commute.transfers}회")
    reasons.append(f"최근 {criteria.history_months}개월 실거래 {candidate.transaction_count}건")
    return reasons[:4]


def _budget_cap(value: int, approximate: bool) -> float:
    return value * (1.1 if approximate else 1.0)


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))

