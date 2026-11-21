"""살구 채팅 API 서버 (FastAPI).

- POST /api/chat   {"session_id": 없으면 새 대화, "message": "..."} → 답 문장 + 조건 카드
- POST /api/reset  {"session_id": "..."} → 그 대화를 끝내고 새로 시작
- GET  /api/sessions/{session_id} → 지금까지의 대화 기록
- GET  /health     → Gemini 모델 상태 (키 값은 넣지 않음)
- GET  /           → 시험용 채팅 화면

대화마다 AI/sample_data/conversations/에 정형 JSON으로 저장한다(sample_log.py).
"""

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, guards, intake, llm, sample_log

app = FastAPI(title="살구 채팅 API", version="0.2")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_sessions = {}  # session_id → 대화 기록(sample_log 형식)
_lock = threading.Lock()
_DEV_UI = Path(__file__).parent / "static" / "dev_ui.html"


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class ResetIn(BaseModel):
    session_id: str


def _conversation(session_id):
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = sample_log.new_conversation(session_id)
        return _sessions[session_id]


@app.post("/api/chat")
def chat(body: ChatIn):
    # 동기 함수라 FastAPI가 스레드에서 돌린다 (Gemini를 기다리는 동안 다른 요청을 막지 않음)
    session_id = body.session_id or uuid.uuid4().hex[:12]
    conv = _conversation(session_id)
    prev_card = conv["final_card"]
    result = intake.intake(body.message, prev_card)
    sample_log.add_turn(conv, guards.mask_pii(body.message or "").strip(), result)
    return {
        "session_id": session_id,
        "type": "condition_card" if result["intent"] == "search" and result["card"] else "message",
        "reply": result["reply"],
        "card": result["card"],
        "conditions": sample_log.flat(result["card"]),
        "intent": result["intent"],
        "via": result["via"],
        "guard": result["guard"],
        "changed": result["changed"],
        "fixes": result["fixes"],
        "seconds": result["seconds"],
    }


@app.post("/api/reset")
def reset(body: ResetIn):
    with _lock:
        _sessions.pop(body.session_id, None)
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
def session(session_id: str):
    with _lock:
        conv = _sessions.get(session_id)
    if not conv:
        raise HTTPException(404, "대화가 없습니다")
    return conv


@app.get("/health")
def health():
    return {"ok": True, "model": config.GEMINI_MODEL, "gemini_key": bool(config.GEMINI_KEY),
            "gemini_available": llm.available(), "gemini_models": llm.status(),
            "sample_dir": str(sample_log.SAMPLE_DIR), "sessions": len(_sessions)}


@app.get("/", response_class=HTMLResponse)
def dev_ui():
    return _DEV_UI.read_text(encoding="utf-8")
