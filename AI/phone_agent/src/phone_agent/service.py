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

from .config import KST, Settings
from .provider import ProviderError
from .schemas import VERSION, BatchRequest, CallRequest

ON_LINE = ("queued", "ringing", "in_progress")
PENDING = ("waiting", "scheduled")
ACTIVE = PENDING + ON_LINE + ("retry_wait", "analyzing")
FINAL = ("done", "failed", "rejected")

LISTING_FIELDS = (
    "location", "building", "floor", "unit", "area_m2", "deposit_manwon", "monthly_rent_manwon",
    "maintenance_fee_manwon", "maintenance_includes", "move_in",
)


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


def in_user_window(start: datetime, windows: list) -> bool:
    return any(w.start <= start < w.end for w in windows)


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
            now = self.now()
            batch = self._new_batch("inquiry", request.approval_id, now)
            for i, call_request in enumerate(request.calls()):
                scenario = scenarios[i] if scenarios and i < len(scenarios) else None
                rec = self._new_rec(call_request, batch, scenario, now)
                batch["call_ids"].append(rec["call_id"])
            self._advance()
            return batch, True

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
            "result": None, "registry_docs": [], "error": None,
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

    def _dispatch(self, now: datetime) -> None:
        """회선이 비어 있으면 다음 통화를 건다(한 번에 한 통, 접수 순서대로)."""
        while not self._line_busy():
            waiting = [r for r in self.store.calls.values() if r["status"] == "waiting"]
            if not waiting:
                return
            self._dial(min(waiting, key=lambda r: r["order"]), now)

    def _request_of(self, rec: dict) -> CallRequest:
        return CallRequest.model_validate(rec["request"])

    def _instruction(self, request: CallRequest) -> str:
        """통화별 지시문. C3에서 instruction.build_instruction으로 만든다."""
        return ""

    def _dial(self, rec: dict, now: datetime) -> None:
        request = self._request_of(rec)
        to = request.broker.phone
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
            self._finish(rec, outcome="no_answer", result=self._empty_result(rec))

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
        outcome, result = self._build_result(request, raw, segments)
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
    @staticmethod
    def _label(segments: list[dict]) -> list[dict]:
        """화자 이름 붙이기. C4에서 extract.label_speakers로 바꾼다."""
        return [{**seg, "speaker": "ai" if seg.get("speaker") == "speaker_0" else "broker"} for seg in segments]

    def _empty_result(self, rec: dict) -> dict:
        return {
            "listings": [], "broker_slots": [], "availability_note": None, "pet_allowed": None,
            "registry_reply": None, "unverified": [], "corrections": [], "evidence": {}, "quotes": {},
            "transcript": [], "sms_draft": None, "timing": None,
        }

    def _build_result(self, request: CallRequest, raw: Optional[dict], segments: list[dict]) -> tuple[str, dict]:
        """C1: 추출 값을 그대로 옮긴다. C4에서 근거 줄 대조(extract.decide)로 바꾼다."""
        lines = self._label(segments)
        result = self._empty_result({})
        if request.keep_transcript:
            result["transcript"] = lines
        if raw is None:
            return "unclear", result

        evidence: dict[str, int] = {}
        listings = []
        for i, item in enumerate(raw.get("listings") or []):
            listings.append({field: item.get(field) for field in LISTING_FIELDS})
            for field, line in (item.get("evidence") or {}).items():
                evidence[f"listings[{i}].{field}"] = line
        slots = []
        for i, slot in enumerate(raw.get("broker_slots") or []):
            start = parse(slot.get("start"))
            if not start:
                continue
            slots.append({"start": iso(start), "end": iso(parse(slot.get("end"))),
                          "in_user_window": in_user_window(start, request.windows)})
            if slot.get("evidence") is not None:
                evidence[f"broker_slots[{len(slots) - 1}]"] = slot["evidence"]
        evidence.update(raw.get("evidence") or {})
        quotes = {str(n): lines[n] for n in sorted(set(evidence.values()))
                  if isinstance(n, int) and 0 <= n < len(lines)}

        result.update(listings=listings, broker_slots=slots, evidence=evidence, quotes=quotes,
                      availability_note=raw.get("availability_note"), pet_allowed=raw.get("pet_allowed"),
                      registry_reply=raw.get("registry_reply"))
        if raw.get("voicemail"):
            outcome = "no_answer"
        elif raw.get("declined"):
            outcome = "declined"
        elif any(any(v is not None for v in item.values()) for item in listings):
            outcome = "listing"
        elif raw.get("available") is False:
            outcome = "no_listing"
        else:
            outcome = "unclear"
        return outcome, result

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
            body["duplicate_groups"] = []
        body["notifications"] = [n for n in self.store.notifications if n.get("batch_id") == batch["batch_id"]]
        return body

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
        sms_draft = result.pop("sms_draft", None)
        body.update(result)
        body.update(
            registry_docs=list(rec["registry_docs"]),
            sms_draft=sms_draft,
            attempts=rec["attempts"], scheduled_at=rec["scheduled_at"], retry_at=rec["retry_at"],
            ended_at=rec["ended_at"], error=rec["error"],
        )
        return body
