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

import httpx

from .config import KST, ROOT
from .instruction import DAYS, time_of, when
from .schemas import CallRequest

MOCK_FILE = ROOT / "specs" / "assets" / "mock_scenarios.json"


class ProviderError(Exception):
    """공급사 실패. 서비스는 그 통화만 failed로 둔다."""


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


def spoken_time(dt: datetime) -> str:
    return time_of(dt)


def spoken_day(dt: datetime) -> str:
    return f"{DAYS[dt.astimezone(KST).weekday()]}요일"


def spoken_datetime(dt: datetime) -> str:
    return when(dt)


def _iso(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat()


class _Filler:
    """자료의 예시 값을 요청 값으로 한 번에 바꾼다(바꾼 값을 다시 바꾸지 않음)."""

    def __init__(self, request: CallRequest, agreed: Optional[datetime] = None):
        """agreed: 확정 시나리오에서 중개사가 말한 시각(shifted는 대안 범위 시작). 없으면 요청 시각."""
        s = request.search
        at = _base_time(request)
        agreed = agreed or at
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
            "토요일 오후 2시": f"{spoken_day(agreed)} {spoken_time(agreed)}",
            _iso(_BASE_AT): _iso(agreed if request.kind == "confirm" else at),
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

    def _scene(self, call: dict) -> tuple[list[dict], dict]:
        """시나리오의 대화록과 추출 값을 요청 값으로 채운다. 확정 통화의 둘째 방부터는 코드로 덧붙인다."""
        if "scene" in call:
            return call["scene"]
        request: CallRequest = call["request"]
        source = _MOCK[call["kind"]][call["scenario"]]
        agreed = None
        if call["kind"] == "confirm" and call["scenario"] == "shifted" and request.target.rooms[0].alternatives:
            agreed = request.target.rooms[0].alternatives[0].start
        filler = _Filler(request, agreed)
        segments = [{"speaker": seg["speaker"], "text": filler.text(seg["text"])} for seg in source["transcript"]]
        extraction = filler.data(copy.deepcopy(source["extraction"]))
        if call["kind"] == "confirm" and len(request.target.rooms) > 1 and call["scenario"] not in ("declined", "no_answer"):
            self._extra_rooms(call["scenario"], request, segments, extraction)
        call["scene"] = (segments, extraction)
        return call["scene"]

    @staticmethod
    def _extra_rooms(scenario: str, request: CallRequest, segments: list[dict], extraction: dict) -> None:
        """같은 사무소의 둘째·셋째 방 대화. partial은 첫 방만 확정, 나머지는 제안."""
        for i, room in enumerate(request.target.rooms[1:], start=1):
            listing = room.listing
            name = listing.location or " ".join(x for x in (listing.building, listing.floor) if x) or f"{i + 1}번째 방"
            unit = f"30{i + 2}호"
            segments.append({"speaker": "speaker_0", "text": f"{name}은 {when(room.at)}에 보러 가도 될까요?"})
            n = len(segments)
            item = {"index": i, "still_available": True, "same_listing": True, "unit": unit,
                    "evidence": {"still_available": n, "same_listing": n, "unit": n}}
            if scenario in ("confirmed", "shifted"):
                at = room.alternatives[0].start if scenario == "shifted" and room.alternatives else room.at
                text = f"네, 그 방도 아직 있어요. {unit}예요. {spoken_day(at)} {spoken_time(at)}에 오세요."
                item["agreed_visit"] = {"at": _iso(at), "place": f"{request.broker.name} 사무소"}
                item["evidence"]["visit.at"] = n
            elif scenario in ("partial", "alternative"):
                at = room.at + timedelta(hours=2)
                text = f"그 방도 아직 있어요. {unit}예요. 그 시간은 안 되고 {spoken_day(at)} {spoken_time(at)}는 괜찮아요."
                item["proposed_visit"] = {"at": _iso(at), "note": f"{spoken_time(at)}는 가능하다고 함"}
                item["evidence"]["proposal.at"] = n
            elif scenario == "unavailable":
                text = "그 방도 나갔어요."
                item = {"index": i, "still_available": False, "evidence": {"still_available": n}}
            else:  # no_time
                text = f"그 방도 아직 있어요. {unit}예요. 그날은 안 돼요."
            segments.append({"speaker": "speaker_1", "text": text})
            extraction.setdefault("rooms", []).append(item)

    def get_transcript(self, call_id: str) -> dict:
        segments, _ = self._scene(self._call(call_id))
        return {"status": "completed", "segments": [dict(seg) for seg in segments]}

    def canned_extraction(self, call_id: str) -> dict:
        """LLM 추출 흉내. 이 값도 실제 통화처럼 판정 코드를 거친다."""
        _, extraction = self._scene(self._call(call_id))
        return copy.deepcopy(extraction)

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


# ---------------------------------------------------------------- 한국AI통신


def digits(number: str) -> str:
    return re.sub(r"\D", "", number or "")


class KatProvider:
    """한국AI통신 REST. 주소는 KAT_BASE_URL(도메인까지) + /v1/accounts/{KAT_ACCOUNT_ID}.

    통화·이벤트·대화록은 11-18~21 실제 응답으로 확인. 문자(/messages)는 공식 문서 기준(미확인).
    """

    REQUIRED = ("kat_base_url", "kat_api_key", "kat_account_id", "kat_agent_id", "kat_from_number")
    ENDED = ("completed", "busy", "no_answer", "failed", "canceled", "cancelled", "rejected")

    def __init__(self, settings, client=None):
        missing = [name.upper() for name in self.REQUIRED if not getattr(settings, name)]
        if missing:
            raise ValueError(f".env에 값이 없습니다: {', '.join(missing)}")
        self.settings = settings
        self.agent_id = settings.kat_agent_id
        self.from_number = digits(settings.kat_from_number)
        base = settings.kat_base_url.rstrip("/")
        self.client = client or httpx.Client(
            base_url=f"{base}/v1/accounts/{settings.kat_account_id}",
            headers={"Authorization": f"Bearer {settings.kat_api_key}"},
            timeout=20,
        )

    def _request(self, method: str, path: str, ok: tuple[int, ...] = (), **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{method} {path}: {type(exc).__name__}") from exc
        if response.status_code >= 400 and response.status_code not in ok:
            raise ProviderError(f"{method} {path}: {response.status_code} {response.text[:200]}")
        return response

    # 통화 -----------------------------------------------------------------
    def create_call(self, to: str, instruction: str, request: Optional[CallRequest] = None,
                    scenario: Optional[str] = None) -> str:
        body = {"To": digits(to), "From": self.from_number, "AgentId": self.agent_id,
                "CallContext": {"Instruction": instruction}}
        data = self._request("POST", "/calls", json=body).json()
        call_id = data.get("callId") or (data.get("data") or {}).get("callId")
        if not call_id:
            raise ProviderError("발신 응답에 callId가 없습니다")
        return call_id

    def get_call(self, call_id: str) -> dict:
        call = self._request("GET", f"/calls/{call_id}").json()
        events = {e.get("event") for e in self._request("GET", f"/calls/{call_id}/events").json().get("data", [])}
        status = str(call.get("status", "")).lower().replace("-", "_")
        answered = "call.answered" in events or status in ("in_progress", "answered")
        if "call.completed" in events or status in self.ENDED:
            return {"phase": "ended", "answered": "call.answered" in events}
        if answered:
            return {"phase": "in_progress", "answered": True}
        if "call.ringing" in events or status == "ringing":
            return {"phase": "ringing", "answered": False}
        return {"phase": "queued", "answered": False}

    # 대화록 ---------------------------------------------------------------
    def request_transcript(self, call_id: str) -> None:
        self._request("POST", f"/calls/{call_id}/transcript", ok=(409,))  # 409: 이미 요청됨

    def get_transcript(self, call_id: str) -> dict:
        response = self._request("GET", f"/calls/{call_id}/transcript", ok=(404,))
        if response.status_code == 404:
            return {"status": "pending", "segments": []}
        data = response.json()
        segments = [{k: seg.get(k) for k in ("speaker", "text", "start", "end") if seg.get(k) is not None}
                    for seg in data.get("segments") or []]
        return {"status": data.get("status", "pending"), "segments": segments}

    # 문자 (미확인) --------------------------------------------------------
    def send_sms(self, to: str, body: str, subject: str = "") -> str:
        payload = {"To": digits(to), "From": self.from_number, "Body": body}
        if len(body.encode("euc-kr", errors="replace")) > 90:  # 90바이트 넘으면 LMS
            payload.update(Type="lms", Subject=subject or "[살구]")
        data = self._request("POST", "/messages", json=payload).json()
        message_id = data.get("messageId") or data.get("id") or (data.get("data") or {}).get("messageId")
        if not message_id:
            raise ProviderError("문자 응답에 messageId가 없습니다")
        return message_id

    def list_inbound(self, page_size: int = 50) -> list[dict]:
        params = {"status": "received", "number": self.from_number, "PageSize": page_size}
        items = self._request("GET", "/messages", params=params).json().get("data", [])
        return [{
            "message_id": m.get("messageId") or m.get("id"),
            "from": m.get("from"), "to": m.get("to"), "type": m.get("type"), "body": m.get("body") or "",
            "num_media": m.get("numMedia") or 0, "received_at": m.get("dateCreated") or m.get("receivedAt"),
        } for m in items]

    def get_media(self, message_id: str, index: int) -> tuple[bytes, str]:
        response = self._request("GET", f"/messages/{message_id}/media/{index}")
        return response.content, response.headers.get("content-type", "application/octet-stream")
