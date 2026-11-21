"""발신 전 검사 (specs/02-policy.md): 영업시간·공휴일, 하루 제한, 시간대 지남, 시연 번호.

세는 날은 접수한 날이 아니라 전화가 나가는 날이다.
거절됐거나 한 번도 걸지 못한 통화(공급사 오류 등)는 세지 않는다.
"""

from __future__ import annotations

import re
import json
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from .config import KST, ROOT, Settings
from .schemas import CallRequest

_MESSAGES_FILE = ROOT / "specs" / "assets" / "messages.json"
_DATA = json.loads(_MESSAGES_FILE.read_text(encoding="utf-8"))

MESSAGES: dict[str, str] = _DATA["policy_errors"]
HOLIDAYS: frozenset[str] = frozenset(_DATA["holidays"])
OPEN_HOUR = int(_DATA["business_hours"]["open"])
CLOSE_HOUR = int(_DATA["business_hours"]["close"])
SUNDAY = 6


class PolicyError(Exception):
    def __init__(self, code: str, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, self.code)

    def body(self) -> dict:
        body = {"error": self.code, "message": self.message}
        if self.detail is not None:
            body["detail"] = self.detail
        return body


# ------------------------------------------------------------------ 영업시간


def _holidays(settings: Optional[Settings]) -> frozenset[str]:
    extra = settings.holidays if settings else ()
    return HOLIDAYS | frozenset(extra)


def _open_day(day: date, settings: Optional[Settings]) -> bool:
    return day.weekday() != SUNDAY and day.isoformat() not in _holidays(settings)


def is_open(now: datetime, settings: Optional[Settings] = None) -> bool:
    """월~토 9~19시, 공휴일 제외. PHONE_AGENT_IGNORE_HOURS=1이면 언제나 연다."""
    if settings and settings.ignore_hours:
        return True
    now = now.astimezone(KST)
    return _open_day(now.date(), settings) and OPEN_HOUR <= now.hour < CLOSE_HOUR


def next_open(now: datetime, settings: Optional[Settings] = None) -> datetime:
    """지금 열려 있으면 지금, 아니면 다음 영업 시작 시각."""
    if is_open(now, settings):
        return now
    now = now.astimezone(KST)
    day = now.date()
    if now.hour >= OPEN_HOUR or not _open_day(day, settings):
        day += timedelta(days=1)
    while not _open_day(day, settings):
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, OPEN_HOUR, tzinfo=KST)


# ------------------------------------------------------------------ 검사


MOBILE = re.compile(r"01[016789]\d{7,8}")


def check_mode(settings: Settings) -> None:
    """demo 모드인데 걸 번호(시연 번호 또는 요청 번호 허용)가 없으면 요청 전체를 거절한다."""
    if settings.mode == "demo" and not settings.demo_numbers and not settings.dial_requested:
        raise PolicyError("not_allowed")


def check_dial_target(settings: Settings, phone: str) -> None:
    """요청 번호로 거는 demo(PHONE_AGENT_DIAL_REQUESTED=1)는 휴대폰 번호만 받는다.
    중개사무소 대표번호(02·070 등)로 잘못 걸리지 않게 하려는 안전장치다."""
    if settings.mode != "demo" or not settings.dial_requested:
        return
    if not MOBILE.fullmatch(re.sub(r"\D", "", phone or "")):
        raise PolicyError("phone_not_allowed", {"reason": "demo 는 사용자가 입력한 휴대폰 번호로만 겁니다"})


def deadline_passed(request: CallRequest, call_at: datetime) -> bool:
    deadline = request.deadline
    return deadline is not None and call_at >= deadline


def kind(rec: dict) -> str:
    return rec.get("kind", "inquiry")


def counted(rec: dict) -> bool:
    """하루 제한에 세는 통화인가: 거절·한 번도 못 건 통화만 빼고, 기다리는 통화도 센다."""
    if rec["status"] == "rejected":
        return False
    if rec["status"] == "failed" and not rec.get("attempts"):
        return False
    return True


def _day_of(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    dt = dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
    return dt.date()


def call_day(rec: dict) -> Optional[date]:
    """전화가 나간(나갈) 날."""
    return (_day_of(rec.get("started_at")) or _day_of(rec.get("scheduled_at"))
            or _day_of(rec.get("created_at")))


def _reg(rec: dict) -> str:
    return rec["request"]["broker"]["reg"]


def _parent(rec: dict) -> Optional[str]:
    return rec.get("parent_call_id")


def check(request: CallRequest, now: datetime, calls: Iterable[dict], settings: Settings) -> Optional[datetime]:
    """걸 수 있으면 예약 시각(지금 바로면 None)을 돌려준다. 걸 수 없으면 PolicyError."""
    call_at = next_open(now, settings)
    scheduled = None if call_at == now else call_at
    if deadline_passed(request, call_at):
        raise PolicyError("window_passed")

    day = call_at.astimezone(KST).date()
    same_day = [rec for rec in calls if counted(rec) and call_day(rec) == day]
    if request.kind == "inquiry":
        inquiries = [rec for rec in same_day if kind(rec) == "inquiry"]
        if any(_reg(rec) == request.broker.reg for rec in inquiries):
            raise PolicyError("already_called_today")
        if len(inquiries) >= settings.daily_limit:
            raise PolicyError("daily_limit")
    else:
        parent = request.target.parent_call_id if request.target else None
        confirms = [rec for rec in same_day if kind(rec) == "confirm" and _parent(rec) == parent]
        if len(confirms) >= settings.confirm_limit:
            raise PolicyError("confirm_limit")
    return scheduled


# ------------------------------------------------------------------ 확정 시각 안전장치


def _at(value) -> Optional[datetime]:
    if not value:
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)


def within_broker_slots(result: dict, at: datetime, proposed: Iterable = ()) -> bool:
    """확정 시각이 문의 통화에서 중개사가 된다고 한 시간(broker_slots) 안인가 (lessons L13).

    범위는 끝 시각 포함, 시각 하나면 그 시각만. 그 뒤 확정 통화에서 중개사가 직접 제안한 시각은 허용.
    판단 근거가 모자라면 막지 않는다: 슬롯이 없음, 대조 못 한 시간(unverified)이 있음, availability_note만 있음.
    """
    at = _at(at)
    slots = result.get("broker_slots") or []
    if not slots or result.get("availability_note"):
        return True
    if any(str(key).startswith("broker_slots") for key in result.get("unverified") or []):
        return True
    if any(_at(p) == at for p in proposed):
        return True
    for slot in slots:
        start, end = _at(slot.get("start")), _at(slot.get("end"))
        if start is None:
            continue
        if (end and start <= at <= end) or (not end and at == start):
            return True
    return False
