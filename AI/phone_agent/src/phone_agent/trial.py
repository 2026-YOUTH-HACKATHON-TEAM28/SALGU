"""시험 통화 도구: 서버 없이 시연 번호로 한 번에 걸어 본다 (specs/03-inquiry-call.md).

    python -m phone_agent.trial run --label c3 [--agent live] [--ignore-hours]

- demo 설정(.env)으로 tests/fixtures/request.example.json의 첫 사무소 하나에 문의 전화(번호는 시연 번호).
- 등록번호는 매번 trial-<이름>-<시각>으로 바꿔 하루 1번에 걸리지 않게, keep_transcript는 켠다.
- 기록은 .data/trials.json에 따로 남기고(서버의 하루 제한과 섞지 않음), 알림은 보내지 않는다.
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
from .policy import PolicyError
from .provider import KatProvider
from .schemas import BatchRequest
from .service import ACTIVE, CallService, Store

FIXTURE = ROOT / "tests" / "fixtures" / "request.example.json"
TRIALS = ROOT / ".data" / "trials.json"
POLL_SEC = 3
TIMEOUT_SEC = 600


def agent_id(name: Optional[str], settings: Settings) -> str:
    """base → KAT_AGENT_ID, 이름 → KAT_AGENT_ID_<이름>, 그 밖은 에이전트 ID 그대로."""
    if not name or name == "base":
        return settings.kat_agent_id
    return os.environ.get(f"KAT_AGENT_ID_{name.upper()}", "").strip() or name


def trial_settings(ignore_hours: bool) -> Settings:
    settings = Settings.from_env()
    if settings.mode != "demo":
        raise SystemExit("시험 통화는 demo 모드에서만 겁니다(.env의 PHONE_AGENT_MODE=demo).")
    return dataclasses.replace(settings, ignore_hours=ignore_hours or settings.ignore_hours, store_path=TRIALS)


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
    keys = ("call_id", "status", "outcome", "error", "listings", "broker_slots", "availability_note",
            "registry_reply", "pet_allowed", "unverified", "corrections", "sms_draft", "timing")
    return {k: result.get(k) for k in keys}


def print_transcript(result: dict, out=print) -> None:
    for i, line in enumerate(result.get("transcript") or []):
        out(f"  {i:>2} [{line.get('speaker')}] {line.get('text')}")


def cmd_run(args, out=print) -> dict:
    settings = trial_settings(args.ignore_hours)
    provider = KatProvider(settings)
    provider.agent_id = agent_id(args.agent, settings)
    service = CallService(settings, provider, store=Store(settings.store_path))
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
    out(f"문의 전화: {request.brokers[0].name} → 시연 번호, 에이전트 {args.agent or 'base'}")
    result = wait(service, call_id, out)
    out(json.dumps(summary(result), ensure_ascii=False, indent=1))
    print_transcript(result, out)
    return result


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m phone_agent.trial", description="살구 시험 통화")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="시연 번호로 문의 전화 한 통")
    run.add_argument("--label", required=True, help="설정 이름(기록표 한 줄)")
    run.add_argument("--agent", default=None, help="base | high | realtime | live | 에이전트 ID")
    run.add_argument("--ignore-hours", action="store_true", help="영업시간 밖에도 건다")
    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
