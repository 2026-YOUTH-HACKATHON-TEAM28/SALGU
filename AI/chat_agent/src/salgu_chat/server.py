"""살구 채팅 API 서버 (FastAPI).

- POST /api/chat   {"session_id": 없으면 새 대화, "message": "..."} → 말풍선들 + 조건 카드
                   (최소 조건이 모이면 BE에 검색 요청 → "~라고 합니다" → 답변, dialog.py)
- POST /api/reset  {"session_id": "..."} → 그 세션 캐시를 지우고 새로 시작
- GET  /api/sessions/{session_id}          → 세션 캐시 전체 (형식: contracts/session_cache.md)
- GET  /api/sessions/{session_id}/keywords → 추천 계산용 키워드와 ready
- GET  /health     → Gemini 모델 상태 (키 값은 넣지 않음)
- GET  /           → 시험용 채팅 화면

대화 상태는 세션마다 캐시 JSON으로 들고 있다(session_cache.py). 서버를 다시 켜도 캐시에서 이어 간다.
"""

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import config, dialog, guards, llm, session_cache

app = FastAPI(title="살구 채팅 API", version="0.3")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_DEV_UI = Path(__file__).parent / "static" / "dev_ui.html"
_SID = r"^[A-Za-z0-9_-]{1,64}$"


class ChatIn(BaseModel):
    message: str
    session_id: str | None = Field(default=None, pattern=_SID)


class ResetIn(BaseModel):
    session_id: str = Field(pattern=_SID)


def _cache_or_404(session_id):
    try:
        cache = session_cache.load(session_id)
    except ValueError:
        cache = None
    if not cache:
        raise HTTPException(404, "세션이 없거나 만료되었습니다")
    return cache


@app.post("/api/chat")
def chat(body: ChatIn):
    # 동기 함수라 FastAPI가 스레드에서 돌린다 (Gemini를 기다리는 동안 다른 요청을 막지 않음)
    session_id = body.session_id or uuid.uuid4().hex[:12]
    cache = session_cache.get_or_new(session_id)
    result = dialog.turn(body.message, cache["card"], session_id=session_id, last_search=cache["last_search"])
    session_cache.add_turn(cache, guards.mask_pii(body.message or "").strip(), result)
    return {
        "session_id": session_id,
        "type": "condition_card" if result["intent"] == "search" and result["card"] else "message",
        "reply": result["reply"],
        "messages": result["messages"],
        "backend": result["backend"],
        "card": result["card"],
        "keywords": cache["keywords"],
        "ready": cache["ready"],
        "missing": cache["missing"],
        "intent": result["intent"],
        "via": result["via"],
        "guard": result["guard"],
        "changed": result["changed"],
        "fixes": result["fixes"],
        "seconds": result["seconds"],
    }


@app.post("/api/reset")
def reset(body: ResetIn):
    session_cache.delete(body.session_id)
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
def session(session_id: str):
    return _cache_or_404(session_id)


@app.get("/api/sessions/{session_id}/keywords")
def session_keywords(session_id: str):
    cache = _cache_or_404(session_id)
    return {"session_id": session_id, "ready": cache["ready"], "missing": cache["missing"],
            "keywords": cache["keywords"], "updated_at": cache["updated_at"]}


@app.get("/health")
def health():
    return {"ok": True, "model": config.GEMINI_MODEL, "gemini_key": bool(config.GEMINI_KEY),
            "gemini_available": llm.available(), "gemini_models": llm.status(),
            "backend": config.BACKEND_SEARCH_URL or "로컬 예시 응답",
            "session_cache_dir": str(session_cache.CACHE_DIR), "sessions": session_cache.count()}


@app.on_event("startup")
def _purge():
    session_cache.purge_expired()


@app.get("/", response_class=HTMLResponse)
def dev_ui():
    return _DEV_UI.read_text(encoding="utf-8")
