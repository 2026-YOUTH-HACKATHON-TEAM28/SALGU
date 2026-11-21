"""통화 속도 측정(초): 응답 지연, AI 한 번 발화 길이, 말 빠르기(음절/초), 끊은 횟수, 통화 길이.

대화록 시각은 녹음을 나중에 전사한 값이라 0.1~0.3초 오차가 있다. 설정끼리 비교하는 용도.
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Optional


def _r(value: float) -> float:
    return round(value, 2)


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


_HANGUL = re.compile(r"[가-힣]")
MIN_SPEECH_SEC = 1.0  # 이보다 짧은 말("네")은 빠르기 계산에서 뺌


def syllables_per_sec(transcript: list[dict], speaker: str) -> Optional[float]:
    """그 화자의 말 빠르기: 줄마다 한글 글자 수 ÷ 말한 시간, 그 중앙값. 사람끼리 대화는 대략 초당 6~7음절."""
    rates = [len(_HANGUL.findall(line.get("text") or "")) / (line["end"] - line["start"])
             for line in transcript
             if line.get("speaker") == speaker and line.get("start") is not None and line.get("end") is not None
             and line["end"] - line["start"] >= MIN_SPEECH_SEC]
    return _r(statistics.median(rates)) if rates else None


def response_gaps(transcript: list[dict]) -> list[Optional[float]]:
    """줄마다 '중개사 말이 끝나고 몇 초 뒤 AI가 말했나'. AI가 중개사 바로 뒤에 말한 줄만, 나머지는 None."""
    gaps: list[Optional[float]] = []
    for i, line in enumerate(transcript):
        prev = transcript[i - 1] if i else None
        if (prev and line.get("speaker") == "ai" and prev.get("speaker") == "broker"
                and line.get("start") is not None and prev.get("end") is not None):
            gaps.append(_r(line["start"] - prev["end"]))
        else:
            gaps.append(None)
    return gaps


def turn_timing(transcript: list[dict]) -> Optional[dict]:
    """화자 구분된 대화록 → 속도. 시각이 없는 대화록(mock)이면 None."""
    timed = [line for line in transcript if line.get("start") is not None and line.get("end") is not None]
    if not timed or len(timed) != len(transcript):
        return None
    raw_gaps = [g for g in response_gaps(transcript) if g is not None]
    gaps = [g for g in raw_gaps if g >= 0]
    ai_turns = [line["end"] - line["start"] for line in transcript if line["speaker"] == "ai"]
    cut_ins = sum(1 for g in raw_gaps if g < 0)  # 중개사 말이 끝나기 전에 AI가 말함
    barge_ins = sum(
        1 for prev, line in zip(transcript, transcript[1:])
        if prev["speaker"] == "ai" and line["speaker"] == "broker" and line["start"] < prev["end"]
    )
    return {
        "response_median": _r(statistics.median(gaps)) if gaps else None,
        "response_p90": _r(_p90(gaps)) if gaps else None,
        "response_max": _r(max(gaps)) if gaps else None,
        "response_gaps": gaps,
        "ai_turn_avg": _r(statistics.mean(ai_turns)) if ai_turns else None,
        "ai_turn_max": _r(max(ai_turns)) if ai_turns else None,
        "ai_syllables_per_sec": syllables_per_sec(transcript, "ai"),
        "broker_syllables_per_sec": syllables_per_sec(transcript, "broker"),
        "ai_talk_seconds": _r(sum(ai_turns)),
        "ai_cut_ins": cut_ins,
        "broker_barge_ins": barge_ins,
        "call_seconds": _r(max(line["end"] for line in transcript)),
    }
