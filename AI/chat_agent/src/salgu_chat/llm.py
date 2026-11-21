"""Gemini 호출. Gemini를 부르는 곳은 이 파일 하나뿐이다(모델·제공자를 바꿀 때 여기만 고친다).

무료 등급 기준으로 동작한다.
- 무료 한도는 '프로젝트 × 모델'마다 따로다. 한 모델이 429(한도 초과)면 같은 요청 안에서 다음 모델로 넘어간다.
- 하루 한도(PerDay)에 걸린 모델은 태평양 시간 다음 자정까지, 분당 한도는 retryDelay(없으면 설정값)만큼 쉰다.
- 모델마다 최근 60초 요청 수를 config.GEMINI_MAX_RPM 이하로 묶는다.
- 시간 초과·기타 오류는 다음 모델을 시도하지 않고 바로 LLMError. 호출한 쪽이 규칙 결과로 답한다(속도 우선).
키 값은 로그·오류 메시지·예외에 넣지 않는다.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

from . import config

BASE = "https://generativelanguage.googleapis.com/v1beta"

_lock = threading.Lock()
_sent = {}        # 모델 → 최근 요청 시각 deque
_cool_until = {}  # 모델 → 이 시각까지 쉼
_state = {"last_model": None}


class LLMError(RuntimeError):
    """Gemini를 쓸 수 없을 때. 호출한 쪽은 규칙 결과로 답한다."""


class _QuotaError(Exception):
    """429 한도 초과. 다음 모델로 넘어가라는 내부 신호."""


def models():
    """시도할 모델 순서: 기본 모델 → 넘어갈 모델들."""
    return [m for m in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS] if m]


def _next_pacific_midnight():
    """무료 한도가 초기화되는 태평양 시간 다음 자정(epoch 초)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        tz = timezone(timedelta(hours=-8))
    now = datetime.now(tz)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


def _usable(model, now):
    """쉬는 중이 아니고 분당 상한 아래면 True. 잠금 안에서 부른다."""
    if _cool_until.get(model, 0) > now:
        return False
    sent = _sent.setdefault(model, deque())
    while sent and now - sent[0] >= 60:
        sent.popleft()
    return len(sent) < config.GEMINI_MAX_RPM


def available():
    """키가 있고 지금 쓸 수 있는 모델이 하나라도 있으면 True."""
    if not config.GEMINI_KEY:
        return False
    now = time.time()
    with _lock:
        return any(_usable(m, now) for m in models())


def status():
    """/health용 모델별 상태."""
    now = time.time()
    out = {}
    with _lock:
        for m in models():
            until = _cool_until.get(m, 0)
            if until > now:
                out[m] = f"쉬는 중 {int(until - now)}초"
            elif _usable(m, now):
                out[m] = "사용 가능"
            else:
                out[m] = "분당 상한"
    return out


def _cooldown_for(model, err):
    """429 오류 내용을 보고 그 모델을 쉬게 한다."""
    details = (err or {}).get("details") or []
    per_day = False
    delay = None
    for d in details:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations") or []:
            if "PerDay" in str((v or {}).get("quotaId", "")):
                per_day = True
        m = re.match(r"(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
        if m:
            delay = float(m.group(1))
    if per_day:
        until = _next_pacific_midnight()
    else:
        until = time.time() + (delay if delay is not None else config.GEMINI_COOLDOWN_S)
    with _lock:
        _cool_until[model] = until


def _request(model, system, user_text, json_mode, timeout):
    """모델 하나에 한 번 요청하고 응답 글을 돌려준다."""
    gen = {"maxOutputTokens": 1024}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    if model.startswith("gemini-3"):
        gen["thinkingConfig"] = {"thinkingLevel": "minimal"}  # 생각 단계를 줄여 빠르게
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": gen,
    }
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": config.GEMINI_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.GEMINI_TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error") or {}
        except Exception:
            err = {}
        if e.code == 429:
            _cooldown_for(model, err)
            raise _QuotaError(model) from None
        raise LLMError(f"Gemini HTTP {e.code}: {str(err.get('message', ''))[:200]}") from None
    except Exception as e:
        raise LLMError(f"Gemini 호출 실패: {e}") from None
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _call(system, user_text, json_mode, timeout):
    """모델 순서대로 시도한다. 한도 초과면 다음 모델, 그 밖의 오류는 바로 LLMError."""
    if not config.GEMINI_KEY:
        raise LLMError("Gemini 키가 없습니다")
    tried = []
    for model in models():
        with _lock:
            now = time.time()
            if not _usable(model, now):
                tried.append(model)
                continue
            _sent[model].append(now)
        try:
            text = _request(model, system, user_text, json_mode, timeout)
        except _QuotaError:
            tried.append(model)
            continue
        _state["last_model"] = model
        return text
    raise LLMError(f"모든 Gemini 모델이 한도 초과 또는 쉬는 중: {', '.join(tried)}")


def last_model():
    """마지막으로 답한 모델. 없으면 기본 모델."""
    return _state["last_model"] or config.GEMINI_MODEL


def generate_json(system, user_text, timeout=None):
    """JSON 응답 → (dict, 걸린 초). JSON이 깨졌을 때만 한 번 다시 시도한다."""
    start = time.time()
    for _ in range(2):
        text = _call(system, user_text, True, timeout)
        try:
            return json.loads(text), time.time() - start
        except ValueError:
            continue
    raise LLMError("Gemini JSON 응답이 깨짐")


def generate_text(system, user_text, timeout=None):
    """글 응답 → (str, 걸린 초)."""
    start = time.time()
    text = _call(system, user_text, False, timeout)
    return text.strip(), time.time() - start
