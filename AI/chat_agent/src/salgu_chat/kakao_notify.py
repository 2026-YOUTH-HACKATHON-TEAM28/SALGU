"""카카오톡 '나에게 보내기'로 사용자 본인 카톡에 알림 보내기 (로컬 시험용).

흐름: 사용자가 /notify/login → 카카오 동의 화면에서 '카카오톡 메시지 전송' 동의 → /notify/callback
     → 토큰을 받아 저장 → /notify/send로 동의한 사람 각자의 카톡 '나와의 채팅'에 메시지가 간다.

실서비스에서는 BE가 로그인할 때 같은 일을 하고 refresh token을 users 테이블에 암호화해 저장한다.
이 모듈은 그 전에 팀이 직접 받아 보는 시험용이다. 토큰은 Git에 올리지 않는 로컬 캐시
(.cache/notify/subscribers.json)에만 둔다.

.env: KAKAO_REST_API_KEY(살구 앱 REST 키), NOTIFY_REDIRECT_URI(비우면 요청이 들어온 주소 + /notify/callback,
      예: https://sample.localhostbar.com/notify/callback, 로컬은 http://localhost:8090/notify/callback),
      KAKAO_CLIENT_SECRET(콘솔에서 Client Secret을 켠 경우에만)
카카오 콘솔: 비즈 앱 + 동의항목 '카카오톡 메시지 전송(talk_message)' + 리다이렉트 URI + Web 도메인 등록
"""
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ME_URL = "https://kapi.kakao.com/v2/user/me"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
SCOPES = "profile_nickname,talk_message"
TEXT_MAX = 200  # 카카오 텍스트 템플릿 한도. 넘으면 400으로 통째로 실패한다
# 세션 캐시 폴더 옆(서버에서는 배포마다 바뀌지 않는 ~/salgu-chat/data/notify)
STORE = Path(config.ENV.get("SESSION_CACHE_DIR") or config.ROOT / ".cache" / "sessions").parent / "notify" / "subscribers.json"
TIMEOUT_S = 10

_lock = threading.Lock()
_states = {}  # 로그인 요청 state → 만든 시각 (CSRF 방지, 10분)


class KakaoError(RuntimeError):
    """카카오 API 오류. code는 카카오 오류 코드(예: KOE006, -402) 또는 HTTP 상태."""

    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__(f"{status}: {body}")


def rest_key():
    """알림용 REST 키. 새 콘솔은 리다이렉트 URI를 REST 키마다 따로 등록하므로, 알림 주소를 등록한 키를
    KAKAO_REST_API_KEY_NOTIFY에 둔다(배포 스크립트가 KAKAO_REST_API_KEY*를 서버로 옮긴다). 없으면 기본 키."""
    return config.ENV.get("KAKAO_REST_API_KEY_NOTIFY") or config.ENV.get("KAKAO_REST_API_KEY", "")


def redirect_uri(base=None):
    """카카오가 돌려보낼 주소. base는 요청이 들어온 사이트 주소(예: 'https://sample.localhostbar.com/')."""
    if config.ENV.get("NOTIFY_REDIRECT_URI"):
        return config.ENV["NOTIFY_REDIRECT_URI"]
    base = base or f"http://localhost:{config.API_PORT}/"
    return base.rstrip("/") + "/notify/callback"


def _call(url, data=None, token=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            return json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise KakaoError(e.code, e.read().decode("utf-8", "replace")[:300]) from None


def _client(data):
    data["client_id"] = rest_key()
    if config.ENV.get("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = config.ENV["KAKAO_CLIENT_SECRET"]
    return data


# ---- 로그인(동의) ----

def login_url(base=None):
    """카카오 동의 화면 주소. talk_message 동의를 받는다. 돌아올 주소는 state와 함께 기억한다."""
    uri = redirect_uri(base)
    state = secrets.token_urlsafe(16)
    now = time.time()
    with _lock:
        for s, t in list(_states.items()):
            if now - t[0] > 600:
                _states.pop(s, None)
        _states[state] = (now, uri)
    q = urllib.parse.urlencode({"client_id": rest_key(), "redirect_uri": uri, "response_type": "code",
                                "scope": SCOPES, "state": state})
    return f"{AUTH_URL}?{q}"


def check_state(state):
    """→ 로그인 때 쓴 돌아올 주소. 모르는 state거나 10분이 지났으면 None (한 번만 쓴다)."""
    with _lock:
        t = _states.pop(state or "", None)
    return t[1] if t and time.time() - t[0] <= 600 else None


def exchange(code, uri=None):
    """인가 코드 → 토큰 {"access_token", "refresh_token", "scope", ...}. uri는 로그인 때 쓴 돌아올 주소."""
    return _call(TOKEN_URL, _client({"grant_type": "authorization_code", "redirect_uri": uri or redirect_uri(),
                                     "code": code}))


def me(access_token):
    """→ (kakao_id, 닉네임)"""
    d = _call(ME_URL, token=access_token)
    nick = ((d.get("kakao_account") or {}).get("profile") or {}).get("nickname") \
        or (d.get("properties") or {}).get("nickname") or ""
    return int(d["id"]), nick


# ---- 저장 (로컬 시험용) ----

def _read():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def save(kakao_id, nickname, token, site=None):
    """site: 그 사람이 연결한 사이트 주소. 메시지 버튼의 기본 링크로 쓴다."""
    with _lock:
        data = _read()
        data[str(kakao_id)] = {"nickname": nickname, "refresh_token": token["refresh_token"],
                               "scope": token.get("scope", ""), "site": site, "at": time.strftime("%Y-%m-%d %H:%M")}
        _write(data)


def remove(kakao_id):
    with _lock:
        data = _read()
        gone = data.pop(str(kakao_id), None) is not None
        _write(data)
    return gone


def subscribers():
    """[{"kakao_id", "nickname", "at", "talk_message"}] — 토큰은 내보내지 않는다."""
    return [{"kakao_id": k, "nickname": v.get("nickname"), "at": v.get("at"),
             "talk_message": "talk_message" in (v.get("scope") or "")}
            for k, v in _read().items()]


# ---- 보내기 ----

def _access(kakao_id):
    """저장된 refresh token → access token. 카카오가 새 refresh token을 주면 바꿔 저장한다."""
    with _lock:
        rec = _read().get(str(kakao_id))
    if not rec:
        raise KeyError(kakao_id)
    tok = _call(TOKEN_URL, _client({"grant_type": "refresh_token", "refresh_token": rec["refresh_token"]}))
    if tok.get("refresh_token") and tok["refresh_token"] != rec["refresh_token"]:
        with _lock:
            data = _read()
            if str(kakao_id) in data:
                data[str(kakao_id)]["refresh_token"] = tok["refresh_token"]
                _write(data)
    return tok["access_token"]


def template(text, link=None, button="살구에서 보기"):
    """텍스트 템플릿. 200자를 넘으면 자른다. link는 콘솔 Web 도메인에 등록된 주소여야 열린다."""
    text = text.strip()
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX - 1] + "…"
    url = link or config.ENV.get("NOTIFY_LINK_URL") or f"http://localhost:{config.API_PORT}/"
    return {"object_type": "text", "text": text, "link": {"web_url": url, "mobile_web_url": url},
            "button_title": button}


def send_memo(access_token, text, link=None, button="살구에서 보기"):
    tpl = template(text, link, button)
    return _call(MEMO_URL, {"template_object": json.dumps(tpl, ensure_ascii=False)}, token=access_token)


def send(kakao_id, text, link=None, button="살구에서 보기"):
    """한 사람에게. → {"kakao_id", "nickname", "ok", "error"}"""
    rec = _read().get(str(kakao_id)) or {}
    nick = rec.get("nickname")
    try:
        send_memo(_access(kakao_id), text, link or rec.get("site"), button)
        return {"kakao_id": str(kakao_id), "nickname": nick, "ok": True, "error": None}
    except KakaoError as e:
        return {"kakao_id": str(kakao_id), "nickname": nick, "ok": False, "error": explain(e)}
    except (KeyError, urllib.error.URLError, TimeoutError) as e:
        return {"kakao_id": str(kakao_id), "nickname": nick, "ok": False, "error": f"{type(e).__name__}: {e}"}


def send_all(text, link=None, button="살구에서 보기"):
    return [send(s["kakao_id"], text, link, button) for s in subscribers()]


def explain(e, uri=None):
    """자주 나오는 카카오 오류 → 고칠 곳."""
    b = e.body or ""
    hints = [
        ("KOE006", "카카오 콘솔 리다이렉트 URI에 " + (uri or redirect_uri()) + " 등록 필요"),
        ("KOE010", "Client Secret이 켜져 있음 → .env에 KAKAO_CLIENT_SECRET 필요(또는 콘솔에서 끄기)"),
        ("invalid_client", "Client Secret 또는 REST 키 확인 필요"),
        ("KOE205", "콘솔 > 동의항목에서 '카카오톡 메시지 전송(talk_message)'을 켜야 함"),
        ("invalid_scope", "콘솔 > 동의항목에서 '카카오톡 메시지 전송(talk_message)'을 켜야 함"),
        ("-402", "사용자가 talk_message에 동의하지 않음 → /notify/login으로 다시 동의"),
        ("-401", "토큰 만료·폐기 → 그 사용자가 /notify/login으로 다시 로그인"),
        ("invalid_grant", "토큰 만료·폐기 → 그 사용자가 /notify/login으로 다시 로그인"),
        ("-3", "앱에 카카오톡 메시지 API 권한 없음 → 비즈 앱·talk_message 설정 확인"),
    ]
    for code, hint in hints:
        if (f'"code":{code}' in b.replace(" ", "")) if code.startswith("-") else code in b:
            return f"{e.status} {code}: {hint}"
    return f"{e.status}: {b[:150]}"
