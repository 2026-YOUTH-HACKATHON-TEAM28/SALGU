"""요청 형식 (contracts/io.md 1·2절). 금액은 만원, 시각은 한국 시간."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import KST

VERSION = "0.3.1"
MAX_BROKERS = 10
MAX_ALTERNATIVES = 3
MAX_ROOMS = 3
MAX_WINDOWS = 6


def to_kst(value: datetime) -> datetime:
    """시간대 없는 시각은 한국 시간으로 보고, 있는 시각은 한국 시간으로 바꾼다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


class Search(BaseModel):
    dong: str = Field(min_length=1)
    ref_building: str = ""
    housing_type: Literal["officetel", "villa"]
    deposit_manwon: int = Field(ge=0)
    monthly_rent_manwon: int = Field(ge=0)
    area_m2: Optional[float] = Field(default=None, ge=0)


class VisitWindow(BaseModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _kst(cls, value: datetime) -> datetime:
        return to_kst(value)

    @model_validator(mode="after")
    def _order(self) -> "VisitWindow":
        if self.end <= self.start:
            raise ValueError("end는 start보다 늦어야 합니다")
        return self


class Broker(BaseModel):
    reg: str = Field(min_length=1)
    name: str = Field(min_length=1)
    phone: str = ""
    visit_windows: list[VisitWindow] = Field(default_factory=list, max_length=MAX_WINDOWS)

    @field_validator("visit_windows")
    @classmethod
    def _sorted(cls, windows: list[VisitWindow]) -> list[VisitWindow]:
        return sorted(windows, key=lambda w: w.start)


class Prep(BaseModel):
    move_in: str = ""
    term: str = ""
    pet: bool = False
    surname: str = Field(default="", max_length=2)


class Share(BaseModel):
    conditions: bool = True
    visit_time: bool = True
    surname: bool = False
    contact: bool = False


class ListingRef(BaseModel):
    """확정 통화에서 말할 방(문의 통화 결과에서 옮겨 옴)."""

    location: Optional[str] = None
    building: Optional[str] = None
    floor: Optional[str] = None
    unit: Optional[str] = None
    deposit_manwon: Optional[int] = None
    monthly_rent_manwon: Optional[int] = None


class TargetRoom(BaseModel):
    listing_index: int = 0
    listing: ListingRef = Field(default_factory=ListingRef)
    at: datetime
    alternatives: list[VisitWindow] = Field(default_factory=list)
    place: str = ""

    @field_validator("at")
    @classmethod
    def _kst(cls, value: datetime) -> datetime:
        return to_kst(value)


class ConfirmTarget(BaseModel):
    parent_call_id: str
    asked_at: Optional[datetime] = None  # 문의 통화를 건 시각("아까/어제/11월 20일에")
    rooms: list[TargetRoom] = Field(min_length=1, max_length=MAX_ROOMS)


class CallRequest(BaseModel):
    """통화 한 건(사무소 하나)의 요청. 서비스가 기록에 JSON으로 저장한다."""

    kind: Literal["inquiry", "confirm"] = "inquiry"
    approval_id: str
    search: Search
    prep: Prep = Field(default_factory=Prep)
    share: Share = Field(default_factory=Share)
    keep_transcript: bool = False
    broker: Broker
    target: Optional[ConfirmTarget] = None

    @property
    def windows(self) -> list[VisitWindow]:
        """문의 통화에서 물어볼 사용자 시간대."""
        if self.kind == "inquiry" and self.share.visit_time:
            return list(self.broker.visit_windows)
        return []

    @property
    def deadline(self) -> Optional[datetime]:
        """이 시각이 지나면 걸 의미가 없다."""
        if self.kind == "confirm" and self.target:
            ends = [room.at for room in self.target.rooms]
            ends += [w.end for room in self.target.rooms for w in room.alternatives]
            return max(ends) if ends else None
        if self.broker.visit_windows:
            return max(w.end for w in self.broker.visit_windows)
        return None


class BatchRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=80)
    search: Search
    prep: Prep = Field(default_factory=Prep)
    share: Share
    keep_transcript: bool = False
    brokers: list[Broker] = Field(min_length=1, max_length=MAX_BROKERS)

    @field_validator("brokers")
    @classmethod
    def _unique_reg(cls, brokers: list[Broker]) -> list[Broker]:
        regs = [b.reg for b in brokers]
        if len(set(regs)) != len(regs):
            raise ValueError("brokers의 등록번호(reg)가 중복됩니다")
        return brokers

    def calls(self) -> list[CallRequest]:
        """사무소마다 통화 한 건. 배열 순서 = 전화 순서."""
        return [
            CallRequest(
                kind="inquiry",
                approval_id=self.approval_id,
                search=self.search,
                prep=self.prep,
                share=self.share,
                keep_transcript=self.keep_transcript,
                broker=broker,
            )
            for broker in self.brokers
        ]


class VisitRequest(BaseModel):
    call_id: str = Field(min_length=1)
    listing_index: int = Field(default=0, ge=0)
    at: datetime
    alternatives: list[VisitWindow] = Field(default_factory=list, max_length=MAX_ALTERNATIVES)
    place: str = ""

    @field_validator("at")
    @classmethod
    def _kst(cls, value: datetime) -> datetime:
        return to_kst(value)


class ConfirmRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=80)
    visits: list[VisitRequest] = Field(min_length=1, max_length=MAX_BROKERS * MAX_ROOMS)

    @field_validator("visits")
    @classmethod
    def _rooms(cls, visits: list[VisitRequest]) -> list[VisitRequest]:
        keys = [(v.call_id, v.listing_index) for v in visits]
        if len(set(keys)) != len(keys):
            raise ValueError("같은 (call_id, listing_index)가 두 번 있습니다")
        per_call: dict[str, int] = {}
        for v in visits:
            per_call[v.call_id] = per_call.get(v.call_id, 0) + 1
            if per_call[v.call_id] > MAX_ROOMS:
                raise ValueError(f"같은 call_id의 방은 최대 {MAX_ROOMS}개입니다")
        return visits
