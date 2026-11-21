"""시험 통화 도구: 서버 없이 시연 번호로 한 번에 걸어 본다 (specs/03-inquiry-call.md).

    python -m phone_agent.trial run --label c3 [--agent live] [--ignore-hours] [--confirm | --confirm-at ISO]
    python -m phone_agent.trial measure <callId…> [--label 이름] [--lines]

- demo 설정(.env)으로 tests/fixtures/request.example.json의 첫 사무소 하나에 문의 전화(번호는 시연 번호).
- 등록번호는 매번 trial-<이름>-<시각>으로 바꿔 하루 1번에 걸리지 않게, keep_transcript는 켠다.
- 기록은 .data/trials.json에 따로 남기고(서버의 하루 제한과 섞지 않음), 알림은 보내지 않는다.
- --confirm: 문의에서 방이 나오면 중개사가 말한 가능 시간의 시작 시각(손님 시간대와 겹치는 것 먼저)으로
  그 방 확정 전화까지. --confirm-at은 그 시각으로(가능 시간 밖이면 서버가 outside_broker_slots로 막음).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

from .config import KST, ROOT, Settings
from .extract import LLMExtractor
from .policy import PolicyError
from .provider import KatProvider
from .schemas import BatchRequest, ConfirmRequest
from .extract import label_speakers
from .service import ACTIVE, CallService, Store, parse
from .timing import response_gaps, turn_timing

FIXTURE = ROOT / "tests" / "fixtures" / "request.example.json"
TRIALS = ROOT / ".data" / "trials.json"
POLL_SEC = 3
TIMEOUT_SEC = 600


def agent_id(name: Optional[str], settings: Settings) -> str:
    """base → KAT_AGENT_ID, 이름 → KAT_AGENT_ID_<이름>, 그 밖은 에이전트 ID 그대로."""
    if not name or name == "base":
        return settings.kat_agent_id
    return os.environ.get(f"KAT_AGENT_ID_{name.upper()}", "").strip() or name


def trial_settings(ignore_hours: bool, record: bool = False) -> Settings:
    settings = Settings.from_env()
    if settings.mode != "demo":
        raise SystemExit("시험 통화는 demo 모드에서만 겁니다(.env의 PHONE_AGENT_MODE=demo).")
    record = record or settings.record
    return dataclasses.replace(settings, ignore_hours=ignore_hours or settings.ignore_hours, store_path=TRIALS,
                               record=record)


def trial_request(label: str, now: datetime) -> BatchRequest:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stamp = now.strftime("%Y%m%d-%H%M%S")
    broker = dict(data["brokers"][0], reg=f"trial-{label}-{stamp}")
    data.update(approval_id=f"trial-{label}-{stamp}", brokers=[broker], keep_transcript=True)
    return BatchRequest.model_validate(data)


def wait(service: CallService, call_id: str, out=print) -> dict:
    """끝날 때까지 상태를 찍으며 기다린다."""
    last, started = None, time.monotonic()
    while True:
        rec = service.get(call_id)
        if rec["status"] != last:
            last = rec["status"]
            out(f"  {datetime.now(KST):%H:%M:%S} {call_id} {last}" + (f" ({rec['error']})" if rec["error"] else ""))
        if rec["status"] not in ACTIVE:
            return service.to_result(rec)
        if time.monotonic() - started > TIMEOUT_SEC:
            raise SystemExit(f"{TIMEOUT_SEC}초 안에 끝나지 않았습니다: {call_id} {last}")
        time.sleep(POLL_SEC)


def summary(result: dict) -> dict:
    if result.get("kind") == "confirm":
        keys = ("call_id", "status", "outcome", "error", "warnings", "visit_status", "rooms", "unverified", "sms_draft")
    else:
        keys = ("call_id", "status", "outcome", "error", "warnings", "listings", "broker_slots", "availability_note",
                "registry_reply", "pet_allowed", "unverified", "corrections", "sms_draft")
    return {k: result.get(k) for k in keys}


def confirm_time(result: dict) -> Optional[datetime]:
    """중개사가 말한 가능 시간의 시작 시각. 손님 시간대 안의 것 먼저 (lessons L13)."""
    slots = result.get("broker_slots") or []
    slots = sorted(slots, key=lambda slot: not slot.get("in_user_window"))
    return parse(slots[0]["start"]) if slots else None


def print_transcript(result: dict, out=print) -> None:
    for i, line in enumerate(result.get("transcript") or []):
        out(f"  {i:>2} [{line.get('speaker')}] {line.get('text')}")


TABLE_HEAD = ("| 설정 | callId | 응답 중앙값(초) | p90 | 최대 | AI 발화 평균(초) | AI 발화 최대 | AI가 끊음 | 중개사가 끊음 "
              "| 통화 길이(초) | AI 말 빠르기(음절/초) | 중개사 말 빠르기 | AI가 말한 시간(초) |")


def table_row(label: str, provider_call_id: str, timing: Optional[dict]) -> str:
    """experiments/2026-11-20-speed.md 기록표 한 줄."""
    if not timing:
        return f"| {label} | {provider_call_id} | (시각 없음) |"
    keys = ("response_median", "response_p90", "response_max", "ai_turn_avg", "ai_turn_max",
            "ai_cut_ins", "broker_barge_ins", "call_seconds", "ai_syllables_per_sec", "broker_syllables_per_sec",
            "ai_talk_seconds")
    return "| " + " | ".join([label, provider_call_id] + ["—" if timing.get(k) is None else str(timing[k]) for k in keys]) + " |"


def print_lines(lines: list[dict], out=print) -> None:
    """줄마다 '← n초 뒤 응답'."""
    for i, (line, gap) in enumerate(zip(lines, response_gaps(lines))):
        when_text = f"{line['start']:6.1f}s" if line.get("start") is not None else "      "
        tail = f"   ← {gap}초 뒤 응답" if gap is not None else ""
        out(f"  {i:>2} {when_text} [{line['speaker']}] {line.get('text')}{tail}")


def cmd_measure(args, out=print) -> list[dict]:
    settings = Settings.from_env()
    provider = KatProvider(settings)
    rows = []
    out(TABLE_HEAD)
    for call_id in args.call_ids:
        provider.request_transcript(call_id)
        transcript = provider.get_transcript(call_id)
        lines = label_speakers(transcript["segments"])
        timing = turn_timing(lines)
        out(table_row(args.label or "", call_id, timing))
        if args.lines:
            print_lines(lines, out)
        rows.append({"call_id": call_id, "timing": timing, "lines": lines})
    return rows


def cmd_run(args, out=print) -> dict:
    settings = trial_settings(args.ignore_hours, getattr(args, "record", False))
    provider = KatProvider(settings)
    provider.agent_id = agent_id(args.agent, settings)
    service = CallService(settings, provider, extractor=LLMExtractor(settings), store=Store(settings.store_path))
    request = trial_request(args.label, datetime.now(KST))
    try:
        batch, _ = service.create_batch(request)
    except PolicyError as exc:
        raise SystemExit(f"걸 수 없습니다: {exc.code} {exc.message}")
    call_id = batch["call_ids"][0]
    rec = service.store.calls[call_id]
    if rec["status"] in ("rejected", "scheduled"):
        raise SystemExit(f"지금 걸 수 없습니다: {rec['status']} {rec['error'] or rec['scheduled_at']} "
                         "(밤·일요일이면 --ignore-hours, 날짜가 지났으면 fixture 날짜를 바꿀 것)")
    out(f"문의 전화: {request.brokers[0].name} → 시연 번호, 에이전트 {args.agent or 'base'}"
        + (", 녹음함(속도 측정용)" if settings.record else ", 녹음 안 함"))
    result = wait(service, call_id, out)
    out(json.dumps(summary(result), ensure_ascii=False, indent=1))
    out(f"대화록 출처: {service.store.calls[call_id].get('transcript_source')}")
    print_transcript(result, out)
    out(TABLE_HEAD)
    out(table_row(args.label, service.store.calls[call_id]["provider_call_id"] or "", result.get("timing")))
    if getattr(args, "confirm", False) or getattr(args, "confirm_at", None):
        return run_confirm(service, request, result, args, out) or result
    return result


def run_confirm(service: CallService, request: BatchRequest, inquiry: dict, args, out=print) -> Optional[dict]:
    if inquiry.get("outcome") != "listing":
        out(f"확정 전화 안 함: 문의 결과가 {inquiry.get('outcome')}")
        return None
    at = parse(args.confirm_at) if args.confirm_at else confirm_time(inquiry)
    if at is None:
        out("확정 전화 안 함: 중개사가 말한 가능 시간이 없음(--confirm-at으로 지정)")
        return None
    confirm = ConfirmRequest.model_validate({"approval_id": f"{request.approval_id}-confirm", "visits": [
        {"call_id": inquiry["call_id"], "listing_index": 0, "at": at.isoformat()}]})
    try:
        batch, _ = service.create_confirmations(confirm)
    except PolicyError as exc:
        out(f"확정 전화 안 함: {exc.code} {exc.message} {json.dumps(exc.detail, ensure_ascii=False)}")
        return None
    call_id = batch["call_ids"][0]
    if service.store.calls[call_id]["status"] in ("rejected", "scheduled"):
        out(f"확정 전화를 지금 걸 수 없습니다: {service.store.calls[call_id]['status']} {service.store.calls[call_id]['error']}")
        return None
    out(f"확정 전화: {at.isoformat()}")
    result = wait(service, call_id, out)
    out(json.dumps(summary(result), ensure_ascii=False, indent=1))
    print_transcript(result, out)
    out(TABLE_HEAD)
    out(table_row(f"{args.label} 확정", service.store.calls[call_id]["provider_call_id"] or "", result.get("timing")))
    return result


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m phone_agent.trial", description="살구 시험 통화")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="시연 번호로 문의 전화 한 통")
    run.add_argument("--label", required=True, help="설정 이름(기록표 한 줄)")
    run.add_argument("--agent", default=None, help="base | high | realtime | live | 에이전트 ID")
    run.add_argument("--ignore-hours", action="store_true", help="영업시간 밖에도 건다")
    run.add_argument("--record", action="store_true", help="녹음함(응답 지연 등 속도 측정용). 기본은 녹음 안 함")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--confirm", action="store_true", help="문의 뒤 중개사가 말한 가능 시간으로 확정 전화까지")
    group.add_argument("--confirm-at", default=None, help="확정 시각(ISO). 가능 시간 밖이면 막힘")
    measure = sub.add_parser("measure", help="끝난 통화의 속도(timing)")
    measure.add_argument("call_ids", nargs="+", help="공급사 callId")
    measure.add_argument("--label", default="", help="기록표에 적을 설정 이름")
    measure.add_argument("--lines", action="store_true", help="줄마다 응답 지연 표시")
    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args)
    else:
        cmd_measure(args)


if __name__ == "__main__":
    main(sys.argv[1:])
