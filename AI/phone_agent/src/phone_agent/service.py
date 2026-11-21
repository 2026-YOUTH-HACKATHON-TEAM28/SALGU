"""접수, 기록, 한 통씩 거는 줄, 통화 진행, 결과 (형식은 contracts/io.md).

웹훅 없이 진행한다: 조회(get/get_batch)와 주기 작업(tick)이 공급사 상태를 읽어 온다.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from . import policy
from .config import KST, Settings
from .dedupe import duplicate_groups
from .extract import LLMExtractor, decide, empty_confirm_result, empty_result, room_status, visit_status
from .instruction import build_instruction, build_sms_draft
from .policy import PolicyError
from .provider import KatProvider, MockProvider, ProviderError
from .schemas import (
    VERSION, BatchRequest, CallRequest, ConfirmRequest, ConfirmTarget, ListingRef, TargetRoom, VisitRequest,
)

ON_LINE = ("queued", "ringing", "in_progress")
PENDING = ("waiting", "scheduled")
ACTIVE = PENDING + ON_LINE + ("retry_wait", "analyzing")
FINAL = ("done", "failed", "rejected")
MAX_ATTEMPTS = 2  # 안 받으면 1번만 다시

def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(KST).isoformat() if dt else None


def parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)


class Store:
    """메모리 기록. path가 있으면 JSON 파일에도 남긴다(mock은 남기지 않음)."""

    def __init__(self, path: Optional[Path | str] = None):
        self.path = Path(path) if path else None
        self.calls: dict[str, dict] = {}
        self.batches: dict[str, dict] = {}
        self.notifications: list[dict] = []
        self.inbox: dict[str, dict] = {}
        if self.path and self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.calls = data.get("calls", {})
            self.batches = data.get("batches", {})
            self.notifications = data.get("notifications", [])
            self.inbox = data.get("inbox", {})

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"calls": self.calls, "batches": self.batches,
                "notifications": self.notifications, "inbox": self.inbox}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)


class CallService:
    def __init__(self, settings: Settings, provider, extractor=None, store: Optional[Store] = None,
                 now: Callable[[], datetime] = lambda: datetime.now(KST), notifier=None):
        self.settings = settings
        self.provider = provider
        self.extractor = extractor
        self.store = store if store is not None else Store()
        self.now = now
        self.notifier = notifier
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 접수
    def create_batch(self, request: BatchRequest, scenarios: Optional[list[Optional[str]]] = None):
        with self._lock:
            existing = self._find_batch("inquiry", request.approval_id)
            if existing:
                self._advance()
                return existing, False
            policy.check_mode(self.settings)
            now = self.now()
            batch = self._new_batch("inquiry", request.approval_id, now)
            for i, call_request in enumerate(request.calls()):
                scenario = scenarios[i] if scenarios and i < len(scenarios) else None
                self._admit(call_request, batch, scenario, now)
            self._advance()
            return batch, True

    def create_confirmations(self, request: ConfirmRequest, scenarios: Optional[list[Optional[str]]] = None):
        """확정 묶음. 모든 방을 먼저 검사하고(하나라도 아니면 요청 전체 409), 사무소(문의 통화)마다 한 통."""
        with self._lock:
            existing = self._find_batch("confirm", request.approval_id)
            if existing:
                self._advance()
                return existing, False
            policy.check_mode(self.settings)
            self._advance()  # 문의 통화 상태를 최신으로
            groups: dict[str, list[VisitRequest]] = {}
            for visit in request.visits:
                parent = self._check_visit(visit)
                groups.setdefault(parent["call_id"], []).append(visit)
            now = self.now()
            batch = self._new_batch("confirm", request.approval_id, now)
            for i, (call_id, visits) in enumerate(groups.items()):
                scenario = scenarios[i] if scenarios and i < len(scenarios) else None
                self._admit(self._confirm_request(request.approval_id, call_id, visits), batch, scenario, now,
                            parent_call_id=call_id)
            self._advance()
            return batch, True

    def _check_visit(self, visit: VisitRequest) -> dict:
        parent = self.store.calls.get(visit.call_id)
        if not parent or parent["kind"] != "inquiry" or parent["status"] != "done" or parent["outcome"] != "listing":
            raise PolicyError("call_not_found", {"call_id": visit.call_id})
        result = parent["result"] or {}
        if visit.listing_index >= len(result.get("listings") or []):
            raise PolicyError("listing_not_found", {"call_id": visit.call_id, "listing_index": visit.listing_index})
        if not policy.within_broker_slots(result, visit.at, self._proposals(visit.call_id, visit.listing_index)):
            raise PolicyError("outside_broker_slots", {
                "call_id": visit.call_id, "listing_index": visit.listing_index, "at": iso(visit.at),
                "broker_slots": [{"start": s["start"], "end": s["end"]} for s in result.get("broker_slots") or []],
            })
        return parent

    def _proposals(self, call_id: str, listing_index: int) -> list[str]:
        """앞선 확정 통화에서 중개사가 직접 제안한 시각(이 시각은 다시 확정 요청 가능)."""
        found = []
        for rec in self.store.calls.values():
            if rec["kind"] == "confirm" and rec["parent_call_id"] == call_id and rec["result"]:
                for room in rec["result"].get("rooms") or []:
                    if room["listing_index"] == listing_index and room.get("proposal"):
                        found.append(room["proposal"]["at"])
        return found

    def _confirm_request(self, approval_id: str, call_id: str, visits: list[VisitRequest]) -> CallRequest:
        parent = self.store.calls[call_id]
        listings = parent["result"]["listings"]
        rooms = [
            TargetRoom(listing_index=v.listing_index, at=v.at, alternatives=v.alternatives, place=v.place,
                       listing=ListingRef(**{k: listings[v.listing_index].get(k) for k in ListingRef.model_fields}))
            for v in sorted(visits, key=lambda v: v.at)
        ]
        target = ConfirmTarget(parent_call_id=call_id, asked_at=parse(parent["started_at"]), rooms=rooms)
        return self._request_of(parent).model_copy(update={"kind": "confirm", "approval_id": approval_id, "target": target})

    def _admit(self, request: CallRequest, batch: dict, scenario: Optional[str], now: datetime,
               parent_call_id: Optional[str] = None) -> dict:
        """사무소별 검사 뒤 통화 기록을 만든다. 걸 수 없는 통화는 rejected로 남긴다."""
        try:
            scheduled = policy.check(request, now, list(self.store.calls.values()), self.settings)
            error = None
        except PolicyError as exc:
            scheduled, error = None, exc
        rec = self._new_rec(request, batch, scenario, now, parent_call_id)
        batch["call_ids"].append(rec["call_id"])
        if error:
            rec.update(status="rejected", error=error.code, message=error.message)
        elif scheduled:
            rec.update(status="scheduled", scheduled_at=iso(scheduled))
        return rec

    def _find_batch(self, kind: str, approval_id: str) -> Optional[dict]:
        for batch in self.store.batches.values():
            if batch["kind"] == kind and batch["approval_id"] == approval_id:
                return batch
        return None

    def _new_id(self, prefix: str, taken: dict) -> str:
        while True:
            value = f"{prefix}_{secrets.token_hex(3)}"
            if value not in taken:
                return value

    def _new_batch(self, kind: str, approval_id: str, now: datetime) -> dict:
        batch_id = self._new_id("bb" if kind == "inquiry" else "vb", self.store.batches)
        batch = {"batch_id": batch_id, "kind": kind, "approval_id": approval_id,
                 "call_ids": [], "created_at": iso(now), "notified": False}
        self.store.batches[batch_id] = batch
        return batch

    def _new_rec(self, request: CallRequest, batch: dict, scenario: Optional[str], now: datetime,
                 parent_call_id: Optional[str] = None) -> dict:
        call_id = self._new_id("bc", self.store.calls)
        order = max((r["order"] for r in self.store.calls.values()), default=0) + 1
        rec = {
            "call_id": call_id, "kind": request.kind, "batch_id": batch["batch_id"],
            "parent_call_id": parent_call_id, "order": order, "approval_id": request.approval_id,
            "request": request.model_dump(mode="json"), "scenario": scenario or None,
            "status": "waiting", "outcome": None, "scheduled_at": None, "retry_at": None,
            "provider_call_id": None, "dialed_to": None, "attempts": 0,
            "created_at": iso(now), "started_at": None, "ended_at": None,
            "analyzing_since": None, "polled_at": None, "transcript_requested": False,
            "result": None, "registry_docs": [], "error": None, "message": None,
        }
        self.store.calls[call_id] = rec
        return rec

    # ------------------------------------------------------------ 조회
    def get(self, call_id: str) -> Optional[dict]:
        with self._lock:
            self._advance()
            return self.store.calls.get(call_id)

    def get_batch(self, batch_id: str) -> Optional[dict]:
        with self._lock:
            self._advance()
            return self.store.batches.get(batch_id)

    def tick(self) -> None:
        with self._lock:
            self._advance()

    # ------------------------------------------------------------ 진행
    def _advance(self) -> None:
        now = self.now()
        calls = sorted(self.store.calls.values(), key=lambda r: r["order"])
        for rec in calls:
            if rec["status"] in ON_LINE:
                self._poll(rec, now)
        for rec in calls:
            if rec["status"] == "analyzing":
                self._analyze(rec, now)
        self._dispatch(now)
        self.store.save()

    def _line_busy(self) -> bool:
        return any(r["status"] in ON_LINE for r in self.store.calls.values())

    @staticmethod
    def _due(rec: dict, now: datetime) -> bool:
        status = rec["status"]
        if status == "waiting":
            return True
        if status == "scheduled":
            return parse(rec["scheduled_at"]) <= now
        if status == "retry_wait":
            return parse(rec["retry_at"]) <= now
        return False

    def _line_free_at(self) -> Optional[datetime]:
        """앞 통화가 끊긴 시각 + 통화 사이 쉬는 시간."""
        ends = [parse(r["ended_at"]) for r in self.store.calls.values() if r["attempts"] and r["ended_at"]]
        if not ends or not self.settings.call_gap_sec:
            return None
        return max(ends) + timedelta(seconds=self.settings.call_gap_sec)

    def _dispatch(self, now: datetime) -> None:
        """회선이 비어 있으면 다음 통화를 건다.

        한 번에 한 통. 다시 걸 차례가 된 통화 먼저, 그다음 접수 순서.
        앞 통화가 끊기면 바로 건다(결과 추출을 기다리지 않음).
        """
        while not self._line_busy():
            due = [r for r in self.store.calls.values() if self._due(r, now)]
            if not due:
                return
            free_at = self._line_free_at()
            if free_at and now < free_at:
                return
            if not policy.is_open(now, self.settings):
                at = iso(policy.next_open(now, self.settings))
                for rec in due:
                    if rec["status"] == "retry_wait":
                        rec["retry_at"] = at
                    else:
                        rec.update(status="scheduled", scheduled_at=at)
                return
            rec = min(due, key=lambda r: (r["status"] != "retry_wait", r["order"]))
            if policy.deadline_passed(self._request_of(rec), now):
                rec.update(status="failed", error="window_passed",
                           message=policy.MESSAGES["window_passed"], ended_at=iso(now))
                continue
            self._dial(rec, now)

    def _request_of(self, rec: dict) -> CallRequest:
        return CallRequest.model_validate(rec["request"])

    def _instruction(self, request: CallRequest) -> str:
        return build_instruction(request, now=self.now(), registry_number=self.settings.registry_number)

    def _sms_draft(self, request: CallRequest) -> str:
        """두 번 걸어도 안 받았을 때의 문자 초안(보내지 않음)."""
        return build_sms_draft(request)

    def _dial_to(self, rec: dict, request: CallRequest) -> str:
        """mock은 요청 번호, demo는 시연 번호로만(사무소 순서대로 돌아가며, 재발신·확정은 처음 번호)."""
        if self.settings.mode != "demo":
            return request.broker.phone
        numbers = self.settings.demo_numbers
        if rec["dialed_to"]:
            return rec["dialed_to"]
        if rec["kind"] == "confirm":
            parent = self.store.calls.get(rec["parent_call_id"] or "")
            return parent["dialed_to"] if parent and parent["dialed_to"] else numbers[0]
        position = self.store.batches[rec["batch_id"]]["call_ids"].index(rec["call_id"])
        return numbers[position % len(numbers)]

    def _dial(self, rec: dict, now: datetime) -> None:
        request = self._request_of(rec)
        to = self._dial_to(rec, request)
        try:
            provider_call_id = self.provider.create_call(
                to, self._instruction(request), request=request, scenario=rec["scenario"])
        except ProviderError as exc:
            rec.update(status="failed", error="provider_error", ended_at=iso(now))
            rec["result"] = {"error_detail": str(exc)}
            return
        rec.update(status="queued", provider_call_id=provider_call_id, dialed_to=to,
                   attempts=rec["attempts"] + 1, polled_at=None)
        rec["started_at"] = rec["started_at"] or iso(now)

    def _poll(self, rec: dict, now: datetime) -> None:
        polled = parse(rec["polled_at"])
        if polled and now - polled < timedelta(seconds=self.settings.poll_interval_sec):
            return  # 화면이 1초마다 조회해도 공급사에는 poll_interval_sec마다
        try:
            info = self.provider.get_call(rec["provider_call_id"])
        except ProviderError:
            rec.update(status="failed", error="provider_error", ended_at=iso(now))
            return
        rec["polled_at"] = iso(now)
        phase = info.get("phase")
        if phase in ON_LINE:
            rec["status"] = phase
            return
        if phase != "ended":
            return
        rec["ended_at"] = iso(now)
        if info.get("answered"):
            rec.update(status="analyzing", analyzing_since=iso(now))
            self._request_transcript(rec)
        else:
            self._no_answer(rec, now, self._empty_result(rec, "no_answer"))

    def _no_answer(self, rec: dict, now: datetime, result: dict) -> None:
        """안 받음·자동응답: retry_minutes 뒤 1번만 다시, 그래도 안 되면 문자 초안만 만든다."""
        if rec["attempts"] < MAX_ATTEMPTS:
            rec.update(status="retry_wait", retry_at=iso(now + timedelta(minutes=self.settings.retry_minutes)),
                       analyzing_since=None, transcript_requested=False)
            return
        result = dict(result, sms_draft=self._sms_draft(self._request_of(rec)))
        self._finish(rec, outcome="no_answer", result=result)

    def _request_transcript(self, rec: dict) -> None:
        try:
            self.provider.request_transcript(rec["provider_call_id"])
            rec["transcript_requested"] = True
        except ProviderError:
            pass

    def _analyze(self, rec: dict, now: datetime) -> None:
        try:
            transcript = self.provider.get_transcript(rec["provider_call_id"])
        except ProviderError:
            transcript = {"status": "failed", "segments": []}
        status = transcript.get("status")
        waited = now - parse(rec["analyzing_since"])
        if status not in ("completed", "failed") and waited < timedelta(seconds=self.settings.analyze_timeout_sec):
            return
        segments = transcript.get("segments", []) if status == "completed" else []
        request = self._request_of(rec)
        raw = self._extract(rec, request, segments)
        outcome, result = self._build_result(request, raw, segments, parse(rec["started_at"]))
        if outcome == "no_answer":  # 자동응답
            self._no_answer(rec, now, result)
            return
        self._finish(rec, outcome=outcome, result=result)

    def _extract(self, rec: dict, request: CallRequest, segments: list[dict]) -> Optional[dict]:
        called_at = parse(rec["started_at"])
        try:
            if self.extractor is not None:
                return self.extractor.extract(request, segments, called_at)
            if hasattr(self.provider, "canned_extraction"):
                return self.provider.canned_extraction(rec["provider_call_id"])
        except Exception:  # 추출 실패는 결론 unclear
            return None
        return None

    def _finish(self, rec: dict, outcome: str, result: dict) -> None:
        rec.update(status="done", outcome=outcome, result=result)

    # ------------------------------------------------------------ 결과 만들기
    def _empty_result(self, rec: dict, outcome: Optional[str] = None) -> dict:
        if rec.get("kind") == "confirm":
            return empty_confirm_result(self._request_of(rec), outcome)
        return empty_result()

    @staticmethod
    def room_status(rec: dict, outcome: Optional[str]) -> str:
        """방별 결과 → visit_status. 통화 전·중은 requesting, 걸지 못한 통화는 not_scheduled."""
        if outcome is None and rec["status"] in ("failed", "rejected"):
            return "not_scheduled"
        return room_status(outcome)

    @staticmethod
    def visit_status(rec: dict) -> str:
        if rec["status"] in ("failed", "rejected"):
            return "not_scheduled"
        return visit_status(rec["outcome"] if rec["status"] == "done" else None)

    def _build_result(self, request: CallRequest, raw: Optional[dict], segments: list[dict],
                      called_at: Optional[datetime] = None) -> tuple[str, dict]:
        """근거 줄 대조로 결론을 정한다(extract.decide). LLM 값은 확인된 것만 쓴다."""
        result = decide(request, raw, segments, called_at)
        return result.pop("outcome"), result

    # ------------------------------------------------------------ 응답 모양
    def accepted(self, batch: dict) -> dict:
        calls = []
        for call_id in batch["call_ids"]:
            rec = self.store.calls[call_id]
            item = {"call_id": call_id, "reg": rec["request"]["broker"]["reg"], "status": rec["status"]}
            if rec["parent_call_id"]:
                item["parent_call_id"] = rec["parent_call_id"]
            if rec["scheduled_at"]:
                item["scheduled_at"] = rec["scheduled_at"]
            if rec["error"]:
                item["error"] = rec["error"]
                item["message"] = rec.get("message")
            calls.append(item)
        return {"batch_id": batch["batch_id"], "kind": batch["kind"],
                "approval_id": batch["approval_id"], "calls": calls}

    def batch_result(self, batch: dict) -> dict:
        calls = [self.store.calls[call_id] for call_id in batch["call_ids"]]
        status = "running" if any(rec["status"] in ACTIVE for rec in calls) else "done"
        body: dict[str, Any] = {
            "version": VERSION, "batch_id": batch["batch_id"], "kind": batch["kind"],
            "approval_id": batch["approval_id"], "status": status,
            "calls": [self.to_result(rec) for rec in calls],
        }
        if batch["kind"] == "inquiry":
            body["duplicate_groups"] = duplicate_groups(self._dedupe_items(calls))
        body["notifications"] = [n for n in self.store.notifications if n.get("batch_id") == batch["batch_id"]]
        return body

    def _dedupe_items(self, calls: list[dict]) -> list[dict]:
        """중복 후보 비교 대상: 끝난 문의 통화의 방들. 확정 통화에서 받은 호수가 있으면 함께."""
        units: dict[tuple[str, int], str] = {}
        for rec in sorted(self.store.calls.values(), key=lambda r: r["order"]):  # 나중 확정 통화가 우선
            if rec["kind"] == "confirm" and rec["status"] == "done" and rec["result"]:
                for room in rec["result"].get("rooms") or []:
                    if room.get("unit"):
                        units[(rec["parent_call_id"], room["listing_index"])] = room["unit"]
        items = []
        for rec in calls:
            if rec["status"] != "done" or not rec["result"]:
                continue
            for i, listing in enumerate(rec["result"].get("listings") or []):
                item = {"call_id": rec["call_id"], "listing_index": i,
                        "broker": rec["request"]["broker"]["name"], "listing": listing}
                if (rec["call_id"], i) in units:
                    item["confirmed_unit"] = units[(rec["call_id"], i)]
                items.append(item)
        return items

    def to_result(self, rec: dict) -> dict:
        broker = rec["request"]["broker"]
        body: dict[str, Any] = {"call_id": rec["call_id"], "kind": rec["kind"], "batch_id": rec["batch_id"]}
        if rec["kind"] == "confirm":
            body["parent_call_id"] = rec["parent_call_id"]
        body.update(
            broker={"reg": broker["reg"], "name": broker["name"]},
            status=rec["status"],
            outcome=rec["outcome"] if rec["status"] == "done" else None,
            called_at=rec["started_at"],
        )
        result = dict(rec["result"] or self._empty_result(rec))
        result.pop("error_detail", None)
        if rec["kind"] == "confirm" and not rec["result"]:  # 통화 전·중은 '요청 중', 걸지 못했으면 not_scheduled
            result["visit_status"] = self.visit_status(rec)
            result["rooms"] = [dict(room, visit_status=self.room_status(rec, None)) for room in result["rooms"]]
        sms_draft = result.pop("sms_draft", None)
        body.update(result)
        if rec["kind"] == "confirm":  # io.md 2절 형식: 확정 통화에는 등기부·정정 기록 없음
            body.pop("corrections", None)
        else:
            body["registry_docs"] = list(rec["registry_docs"])
        body.update(
            sms_draft=sms_draft,
            attempts=rec["attempts"], scheduled_at=rec["scheduled_at"], retry_at=rec["retry_at"],
            ended_at=rec["ended_at"], error=rec["error"],
        )
        return body


def build_service(settings: Settings) -> CallService:
    """mock은 전화를 걸지 않고 기록을 파일에 남기지 않는다. demo는 한국AI통신 + LLM 추출 + .data/calls.json."""
    if settings.mode == "mock":
        return CallService(settings, MockProvider(), store=Store())
    return CallService(settings, KatProvider(settings), extractor=LLMExtractor(settings),
                       store=Store(settings.store_path))
