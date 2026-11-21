"""살구 채팅 API 서버 (FastAPI).

- POST /api/chat   {"session_id": 없으면 새 대화, "message": "..."} → 말풍선들 + 조건 카드
                   (최소 조건이 모이면 BE에 검색 요청 → "~라고 합니다" → 답변, dialog.py)
- POST /api/reset  {"session_id": "..."} → 그 세션 캐시를 지우고 새로 시작
- GET  /api/sessions/{session_id}          → 세션 캐시 전체 (형식: contracts/session_cache.md)
- GET  /api/sessions/{session_id}/keywords → 추천 계산용 키워드와 ready
- GET  /health     → Gemini 모델 상태 (키 값은 넣지 않음)
- GET  /           → 시험용 채팅 화면
- GET  /notify     → 카카오톡 알림 시험 (각자 로그인·동의 → 본인 카톡 '나와의 채팅'으로 받기)

대화 상태는 세션마다 캐시 JSON으로 들고 있다(session_cache.py). 서버를 다시 켜도 캐시에서 이어 간다.
"""

import html
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import config, dialog, guards, kakao_notify, llm, recommender, session_cache

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
        "action": result.get("action"),  # 전화 요청 초안: 사용자가 승인하면 BE가 전화 서버에 보낸다
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
            "backend": config.BACKEND_SEARCH_URL or ("추천 엔진(실거래 DB)" if recommender.configured() else "로컬 예시 응답"),
            "session_cache_dir": str(session_cache.CACHE_DIR), "sessions": session_cache.count()}


@app.on_event("startup")
def _startup():
    session_cache.purge_expired()
    recommender.warm()  # 추천 엔진 DB 연결을 미리 열어 첫 요청이 느리지 않게


@app.get("/", response_class=HTMLResponse)
def dev_ui():
    return _DEV_UI.read_text(encoding="utf-8")


# ---- 카카오톡 알림 시험 (kakao_notify.py) ----
# 실서비스에서는 BE가 로그인·토큰 저장·발송을 맡는다. 이 화면은 그 전 시연용이다.
# 바깥(프록시 Caddy)에서 오는 요청은 /notify/login, /notify/callback과 안내 화면만 쓸 수 있다.
# 목록·보내기는 서버 안에서 직접 부를 때(프록시 헤더 없음, 127.0.0.1)나 NOTIFY_ADMIN_TOKEN이 맞을 때만.

def _internal(request: Request):
    token = config.ENV.get("NOTIFY_ADMIN_TOKEN")
    if token and request.headers.get("x-notify-token") == token:
        return True
    proxied = any(h in request.headers for h in ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip"))
    return not proxied and (request.client and request.client.host) in ("127.0.0.1", "::1", "testclient")


def _require_internal(request: Request):
    if not _internal(request):
        raise HTTPException(403, "서버 안에서만 쓸 수 있습니다")


class NotifyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    link: str | None = Field(default=None, max_length=500)
    kakao_id: str | None = Field(default=None, pattern=r"^\d{1,20}$")


def _page(title, body):
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;line-height:1.6}}
.btn{{display:inline-block;background:#FEE500;color:#191919;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600;border:0;cursor:pointer;font-size:15px}}
textarea{{width:100%;box-sizing:border-box;font-size:15px;padding:8px}} li{{margin:4px 0}} .err{{color:#c0392b}} .ok{{color:#1e8449}}</style>
<h2>{html.escape(title)}</h2>{body}""")


@app.get("/notify")
def notify_page(request: Request):
    if not _internal(request):
        return _page("살구 카톡 알림", "<p>카카오로 로그인하고 <b>카카오톡 메시지 전송</b>에 동의하면, 살구 알림이 "
                     "내 카톡 '나와의 채팅'으로 와요.</p><p><a class=btn href=/notify/login>카카오로 알림 받기</a></p>")
    if not kakao_notify.rest_key():
        return _page("카톡 알림 시험", "<p class=err>.env에 KAKAO_REST_API_KEY가 없습니다.</p>")
    subs = kakao_notify.subscribers()
    rows = "".join(f"<li>{html.escape(s['nickname'] or '(이름 없음)')} · {html.escape(s['at'] or '')}"
                   f"{'' if s['talk_message'] else ' <span class=err>(메시지 동의 안 함)</span>'}</li>" for s in subs)
    return _page("카톡 알림 시험", f"""
<p>1. 각자 아래 버튼으로 카카오 로그인 → <b>카카오톡 메시지 전송</b>에 동의하면 바로 시험 메시지가 갑니다.</p>
<p><a class=btn href="/notify/login">카카오로 알림 받기</a></p>
<p>2. 동의한 사람 {len(subs)}명</p><ul>{rows or '<li>아직 없음</li>'}</ul>
<p>3. 모두에게 보내기 (200자까지)</p>
<textarea id=t rows=4>[살구] 이화부동산 통화 결과: 방 있음, 토요일 오후 방문 가능해요.</textarea>
<p><button class=btn onclick="send()">보내기</button></p><pre id=r></pre>
<script>async function send(){{const r=await fetch('/notify/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{text:document.getElementById('t').value}})}});document.getElementById('r').textContent=JSON.stringify(await r.json(),null,1)}}</script>""")


@app.get("/notify/login")
def notify_login(request: Request):
    if not kakao_notify.rest_key():
        raise HTTPException(500, ".env에 KAKAO_REST_API_KEY가 없습니다")
    # 프록시(Caddy) 뒤에서는 원래 주소(https://sample.localhostbar.com)로 돌아오게 전달 헤더를 본다.
    # 8095는 127.0.0.1에만 열려 있어 바깥에서 이 헤더를 직접 꾸밀 수 없다(항상 Caddy를 거침).
    h = request.headers
    proto = (h.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (h.get("x-forwarded-host") or h.get("host") or request.url.netloc).split(",")[0].strip()
    return RedirectResponse(kakao_notify.login_url(f"{proto}://{host}/"))


@app.get("/notify/callback")
def notify_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                    error_description: str | None = None):
    if error:
        return _page("연결 실패", f"<p class=err>{html.escape(error)}: {html.escape(error_description or '')}</p>"
                     "<p>동의 화면에서 취소했거나 콘솔 설정이 빠졌습니다. <a href=/notify>돌아가기</a></p>")
    uri = kakao_notify.check_state(state)
    if not code or not uri:
        return _page("연결 실패", "<p class=err>로그인 요청이 만료되었거나 잘못되었습니다.</p><p><a href=/notify>다시 하기</a></p>")
    try:
        tok = kakao_notify.exchange(code, uri)
        kakao_id, nick = kakao_notify.me(tok["access_token"])
    except kakao_notify.KakaoError as e:
        return _page("연결 실패", f"<p class=err>{html.escape(kakao_notify.explain(e, uri))}</p><p><a href=/notify>돌아가기</a></p>")
    if "talk_message" not in (tok.get("scope") or ""):
        return _page("메시지 동의가 필요해요", "<p class=err>'카카오톡 메시지 전송'에 동의하지 않아 알림을 보낼 수 없어요.</p>"
                     "<p><a class=btn href=/notify/login>다시 동의하기</a></p>")
    kakao_notify.save(kakao_id, nick, tok, site=uri.rsplit("/notify/callback", 1)[0] + "/")
    res = kakao_notify.send(kakao_id, f"[살구] {nick or ''}님, 카톡 알림이 연결됐어요. 전화 결과와 새 매물을 여기로 알려 드릴게요.")
    msg = ("<p class=ok>카톡 '나와의 채팅'에 시험 메시지를 보냈어요. 확인해 보세요.</p>" if res["ok"]
           else f"<p class=err>연결은 됐지만 보내기 실패: {html.escape(res['error'] or '')}</p>")
    return _page("카톡 알림 연결 완료", f"<p>{html.escape(nick or '')}님 연결됨.</p>{msg}<p><a href=/>살구로 돌아가기</a></p>")


@app.post("/notify/send")
def notify_send(body: NotifyIn, request: Request):
    _require_internal(request)
    if body.kakao_id:
        return {"results": [kakao_notify.send(body.kakao_id, body.text, body.link)]}
    results = kakao_notify.send_all(body.text, body.link)
    return {"sent": sum(r["ok"] for r in results), "total": len(results), "results": results}


@app.get("/notify/subscribers")
def notify_subscribers(request: Request):
    _require_internal(request)
    return {"subscribers": kakao_notify.subscribers()}
