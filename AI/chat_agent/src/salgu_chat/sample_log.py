"""대화 기록: 한 대화(세션)마다 정형 JSON 파일 하나를 AI/sample_data/conversations/에 저장한다.

파일 형식 (대화가 이어질 때마다 같은 파일을 덮어씀)
{
  "session_id": "...", "started_at": "...", "updated_at": "...", "turn_count": 3,
  "ready": true,                       # 최소 조건(지역·보증금·월세)이 다 모였는지
  "final_conditions": {"preferred_areas": ["홍대"], "deposit_manwon": 1000, ...},   # 분석용 평평한 값
  "final_card": {...조건 카드 전체...},
  "turns": [
    {"turn": 1, "at": "...", "user": "개인정보를 가린 사용자 말", "intent": "search", "via": "rules",
     "guard": null, "reply": "좋아요! ...", "changed": ["deposit_manwon", ...], "fixes": [], "seconds": 0.002,
     "conditions": {...이 시점의 평평한 값...}, "ready": true, "missing": [],
     "messages": [{"kind": "reply"|"backend_request"|"backend_response"|"answer", "text": "..."}],
     "backend": {"called": true, "mock": true, "ok": true, "count": 3, "candidates": ["..."]}}
  ]
}
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from . import config

SAMPLE_DIR = Path(config.ENV.get("SAMPLE_DIR") or config.ROOT.parent / "sample_data" / "conversations")
_lock = threading.Lock()


def flat(card):
    """조건 카드 → {칸: 값} (회사 위치는 이름)."""
    conds = (card or {}).get("conditions") or {}
    return {k: (c.get("label") if k == "workplace" else c.get("value")) for k, c in sorted(conds.items())}


def _backend_summary(res):
    """BE 검색 요청 결과 요약 (후보 이름까지)."""
    if not res:
        return {"called": False}
    return {"called": True, "mock": res["mock"], "ok": res["ok"], "count": res["count"], "error": res["error"],
            "seconds": res["seconds"], "candidates": [c.get("name") for c in res["candidates"]]}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_conversation(session_id):
    t = now()
    return {"session_id": session_id, "started_at": t, "updated_at": t, "turn_count": 0,
            "ready": False, "final_conditions": {}, "final_card": None, "turns": []}


def add_turn(conv, user_text, result):
    """대화에 한 턴을 붙이고 파일로 저장한다. 저장 경로를 돌려준다."""
    card = result.get("card")
    conv["turns"].append({
        "turn": len(conv["turns"]) + 1, "at": now(), "user": user_text,
        "intent": result["intent"], "via": result["via"], "guard": result.get("guard"),
        "reply": result["reply"], "changed": result.get("changed", []), "fixes": result.get("fixes", []),
        "seconds": result.get("seconds"), "conditions": flat(card),
        "ready": bool((card or {}).get("ready")), "missing": (card or {}).get("missing", []),
        "messages": result.get("messages", []),
        "backend": _backend_summary(result.get("backend")),
    })
    conv["turn_count"] = len(conv["turns"])
    conv["updated_at"] = conv["turns"][-1]["at"]
    if card:
        conv["final_card"] = card
        conv["final_conditions"] = flat(card)
        conv["ready"] = bool(card.get("ready"))
    return save(conv)


def save(conv):
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    day = conv["started_at"][:10]
    path = SAMPLE_DIR / f"{day}_{conv['session_id']}.json"
    tmp = path.with_suffix(".json.tmp")
    with _lock:
        tmp.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return path
