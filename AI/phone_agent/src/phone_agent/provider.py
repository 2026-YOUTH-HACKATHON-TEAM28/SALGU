"""공급사: 실제 전화(KatProvider, C3)와 전화를 걸지 않는 MockProvider.

두 공급사는 같은 메서드를 가진다(specs/interfaces.md).
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import KST, ROOT
from .schemas import CallRequest

MOCK_FILE = ROOT / "specs" / "assets" / "mock_scenarios.json"
DAYS = "월화수목금토일"


class ProviderError(Exception):
    """공급사 실패. 서비스는 그 통화만 failed로 둔다."""


# ---------------------------------------------------------------- 시각 말하기


def spoken_time(dt: datetime) -> str:
    """'오후 2시', '오전 10시 30분'."""
    hour = dt.hour
    half = "오전" if hour < 12 else "오후"
    h12 = hour % 12 or 12
    text = f"{half} {h12}시"
    if dt.minute:
        text += f" {dt.minute}분"
    return text


def spoken_day(dt: datetime) -> str:
    return f"{DAYS[dt.weekday()]}요일"


def spoken_datetime(dt: datetime) -> str:
    """'2026년 11월 21일 토요일 오후 2시'."""
    dt = dt.astimezone(KST)
    return f"{dt.year}년 {dt.month}월 {dt.day}일 {spoken_day(dt)} {spoken_time(dt)}"


# ---------------------------------------------------------------- mock


def _load_mock() -> dict:
    return json.loads(MOCK_FILE.read_text(encoding="utf-8"))


_MOCK = _load_mock()
INQUIRY_SCENARIOS = tuple(_MOCK["inquiry"].keys())
CONFIRM_SCENARIOS = tuple(_MOCK["confirm"].keys())
_STEPS = tuple(_MOCK["progression"]["steps"])
_DEFAULTS = _MOCK["default_when_missing"]

# 자료(mock_scenarios.json)에 박힌 예시 값
_BASE_AT = datetime(2026, 11, 21, 14, 0, tzinfo=KST)
_BASE_BROKER = "한빛공인중개사"
_BASE_DONG = "봉천동"
_BASE_BUILDING = "해든빌라"
_BASE_DEPOSIT, _BASE_RENT, _BASE_RENT2 = 1000, 60, 65
REGISTRY_BODY = "등기부등본 보내드립니다."
REGISTRY_MEDIA = (b"%PDF-1.4 mock registry", "application/pdf")


def default_scenario(kind: str, reg: str) -> str:
    choices = _DEFAULTS[kind]
    return choices[int(hashlib.sha256(reg.encode("utf-8")).hexdigest(), 16) % len(choices)]


def _base_time(request: CallRequest) -> datetime:
    """대화록의 '11월 21일 토요일 오후 2시' 자리에 들어갈 시각."""
    if request.kind == "confirm" and request.target:
        return request.target.rooms[0].at
    if request.broker.visit_windows:
        return request.broker.visit_windows[0].start
    tomorrow = datetime.now(KST) + timedelta(days=1)
    return tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat()


class _Filler:
    """자료의 예시 값을 요청 값으로 한 번에 바꾼다(바꾼 값을 다시 바꾸지 않음)."""

    def __init__(self, request: CallRequest):
        s = request.search
        at = _base_time(request)
        later1, later2 = at + timedelta(hours=1), at + timedelta(hours=2)
        building = s.ref_building or _BASE_BUILDING
        location = f"{building} 3층"
        if request.kind == "confirm" and request.target:
            listing = request.target.rooms[0].listing
            building = listing.building or building
            location = listing.location or " ".join(x for x in (listing.building, listing.floor) if x) or location

        self.text_map = {
            f"{_BASE_BUILDING} 3층": location,
            _BASE_BROKER: request.broker.name,
            _BASE_DONG: s.dong,
            _BASE_BUILDING: building,
            f"{_BASE_DEPOSIT}만 원": f"{s.deposit_manwon}만 원",
            f"{_BASE_RENT}만 원": f"{s.monthly_rent_manwon}만 원",
            f"{_BASE_RENT2}만 원": f"{s.monthly_rent_manwon + 5}만 원",
            spoken_datetime(_BASE_AT): spoken_datetime(at),
            "토요일 오후 2시부터 오후 3시까지": f"{spoken_day(at)} {spoken_time(at)}부터 {spoken_time(later1)}까지",
            "토요일 오후 4시": f"{spoken_day(later2)} {spoken_time(later2)}",
            "오후 4시는": f"{spoken_time(later2)}는",
            "토요일 오후 2시": f"{spoken_day(at)} {spoken_time(at)}",
            _iso(_BASE_AT): _iso(at),
            _iso(_BASE_AT + timedelta(hours=1)): _iso(later1),
            _iso(_BASE_AT + timedelta(hours=2)): _iso(later2),
        }
        keys = sorted(self.text_map, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(k) for k in keys))
        self.money_map = {
            "deposit_manwon": {_BASE_DEPOSIT: s.deposit_manwon},
            "monthly_rent_manwon": {_BASE_RENT: s.monthly_rent_manwon, _BASE_RENT2: s.monthly_rent_manwon + 5},
        }

    def text(self, value: str) -> str:
        return self._pattern.sub(lambda m: self.text_map[m.group(0)], value)

    def data(self, value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.data(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.data(v, key) for v in value]
        if isinstance(value, int) and not isinstance(value, bool) and key in self.money_map:
            return self.money_map[key].get(value, value)
        return value


class MockProvider:
    """전화를 걸지 않는 공급사. 조회 한 번에 한 단계씩 진행한다."""

    def __init__(self) -> None:
        self.calls: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.inbox: list[dict] = []
        self._ids = itertools.count(1)

    # 통화 -----------------------------------------------------------------
    def create_call(self, to: str, instruction: str, request: Optional[CallRequest] = None,
                    scenario: Optional[str] = None) -> str:
        if request is None:
            raise ProviderError("MockProvider에는 request가 필요합니다")
        kind = request.kind
        known = INQUIRY_SCENARIOS if kind == "inquiry" else CONFIRM_SCENARIOS
        if scenario not in known:
            scenario = default_scenario(kind, request.broker.reg)
        call_id = f"mock-{next(self._ids)}"
        self.calls[call_id] = {
            "to": to, "instruction": instruction, "request": request, "kind": kind,
            "scenario": scenario, "step": -1, "transcript_requested": False,
        }
        return call_id

    def _call(self, call_id: str) -> dict:
        if call_id not in self.calls:
            raise ProviderError(f"없는 통화: {call_id}")
        return self.calls[call_id]

    def get_call(self, call_id: str) -> dict:
        call = self._call(call_id)
        if call["step"] < len(_STEPS) - 1:
            call["step"] += 1
        phase = _STEPS[call["step"]]
        if call["scenario"] == "no_answer" and phase == "in_progress":
            call["step"] = len(_STEPS) - 1
            return {"phase": "ended", "answered": False}
        if phase == "ended" and call["scenario"] == "registry" and not call.get("registry_sent"):
            call["registry_sent"] = True
            self._receive_registry(call)
        return {"phase": phase, "answered": phase in ("in_progress", "ended")}

    def scenario_of(self, call_id: str) -> str:
        return self._call(call_id)["scenario"]

    # 대화록 ---------------------------------------------------------------
    def request_transcript(self, call_id: str) -> None:
        self._call(call_id)["transcript_requested"] = True

    def get_transcript(self, call_id: str) -> dict:
        call = self._call(call_id)
        source = _MOCK[call["kind"]][call["scenario"]]
        filler = _Filler(call["request"])
        segments = [{"speaker": seg["speaker"], "text": filler.text(seg["text"])} for seg in source["transcript"]]
        return {"status": "completed", "segments": segments}

    def canned_extraction(self, call_id: str) -> dict:
        """LLM 추출 흉내. 이 값도 실제 통화처럼 판정 코드를 거친다."""
        call = self._call(call_id)
        source = copy.deepcopy(_MOCK[call["kind"]][call["scenario"]]["extraction"])
        return _Filler(call["request"]).data(source)

    # 문자 -----------------------------------------------------------------
    def send_sms(self, to: str, body: str, subject: str = "") -> str:
        message_id = f"SMmock{next(self._ids)}"
        self.sent.append({"message_id": message_id, "to": to, "body": body, "subject": subject})
        return message_id

    def _receive_registry(self, call: dict) -> None:
        self.inbox.insert(0, {
            "message_id": f"MGmock{next(self._ids)}",
            "from": call["to"],
            "to": "",
            "type": "mms",
            "body": REGISTRY_BODY,
            "num_media": 1,
            "received_at": datetime.now(KST).isoformat(),
        })

    def list_inbound(self, page_size: int = 50) -> list[dict]:
        return [dict(m) for m in self.inbox[:page_size]]

    def get_media(self, message_id: str, index: int) -> tuple[bytes, str]:
        if index != 0 or not any(m["message_id"] == message_id for m in self.inbox):
            raise ProviderError(f"없는 첨부: {message_id}/{index}")
        return REGISTRY_MEDIA
