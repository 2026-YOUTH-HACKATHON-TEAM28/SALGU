"""세션 캐시: 대화(세션)마다 지금까지의 대화 상태를 JSON 캐시 파일 하나로 들고 있다.

추천 계산 메서드는 이 캐시를 읽어 키워드(조건)를 뽑고 추천 매물을 만든다.
    from salgu_chat import session_cache
    session_cache.keywords("세션ID")   # {"preferred_areas": ["신촌"], "deposit_manwon": 1000, ...}
    session_cache.load("세션ID")       # 캐시 전체 (형식: contracts/session_cache.md)

- 위치: AI/chat_agent/.cache/sessions/{session_id}.json (.env의 SESSION_CACHE_DIR로 바꿀 수 있음)
- 턴마다 같은 파일을 덮어쓴다(쓰는 중 깨지지 않게 임시 파일 → 교체).
- 마지막 대화 후 SESSION_TTL_HOURS(기본 24)시간이 지나면 만료되어 읽지 않고 지운다.
- 사용자 말은 개인정보를 가린 뒤 저장한다.
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import config

VERSION = "0.1"
CACHE_DIR = Path(config.ENV.get("SESSION_CACHE_DIR") or config.ROOT / ".cache" / "sessions")
TTL_HOURS = config._int("SESSION_TTL_HOURS", 24)
_lock = threading.Lock()
_mem = {}  # session_id → 캐시 (파일과 같은 내용)
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _now():
    return datetime.now().astimezone()


def _path(session_id):
    if not _ID.fullmatch(session_id or ""):
        raise ValueError("세션 ID 형식이 아닙니다")
    return CACHE_DIR / f"{session_id}.json"


def flat(card):
    """조건 카드 → 키워드 {칸: 값} (회사 위치는 이름)."""
    conds = (card or {}).get("conditions") or {}
    return {k: (c.get("label") if k == "workplace" else c.get("value")) for k, c in sorted(conds.items())}


def new(session_id):
    t = _now()
    return {"version": VERSION, "session_id": session_id, "created_at": t.isoformat(timespec="seconds"),
            "updated_at": t.isoformat(timespec="seconds"),
            "expires_at": (t + timedelta(hours=TTL_HOURS)).isoformat(timespec="seconds"),
            "ready": False, "missing": ["area", "deposit", "monthly_rent"], "keywords": {}, "card": None,
            "last_search": None, "turn_count": 0, "history": []}


def _expired(cache):
    try:
        return datetime.fromisoformat(cache["expires_at"]) < _now()
    except (KeyError, ValueError):
        return True


def load(session_id):
    """세션 캐시를 읽는다. 없거나 만료되었으면 None."""
    path = _path(session_id)
    with _lock:
        cache = _mem.get(session_id)
        if cache is None and path.exists():
            try:
                cache = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cache = None
        if cache is not None and _expired(cache):
            _mem.pop(session_id, None)
            path.unlink(missing_ok=True)
            return None
        if cache is not None:
            _mem[session_id] = cache
        return cache


def keywords(session_id):
    """추천 계산용 키워드(평평한 조건). 세션이 없으면 None."""
    cache = load(session_id)
    return dict(cache["keywords"]) if cache else None


def get_or_new(session_id):
    return load(session_id) or new(session_id)


def add_turn(cache, user_text, result):
    """한 턴을 반영하고 캐시 파일을 덮어쓴다. 저장 경로를 돌려준다."""
    t = _now()
    card = result.get("card")
    res = result.get("backend")
    cache["history"].append({
        "turn": len(cache["history"]) + 1, "at": t.isoformat(timespec="seconds"), "user": user_text,
        "intent": result["intent"], "via": result["via"], "guard": result.get("guard"),
        "changed": result.get("changed", []), "fixes": result.get("fixes", []),
        "messages": result.get("messages", [{"kind": "reply", "text": result["reply"]}]),
        "searched": bool(res),
    })
    if card:
        cache["card"] = card
        cache["keywords"] = flat(card)
        cache["ready"] = bool(card.get("ready"))
        cache["missing"] = card.get("missing", [])
    if res:
        cache["last_search"] = {"at": t.isoformat(timespec="seconds"), "mock": res["mock"], "ok": res["ok"],
                                "count": res["count"], "error": res["error"], "candidates": res["candidates"]}
    cache["turn_count"] = len(cache["history"])
    cache["updated_at"] = t.isoformat(timespec="seconds")
    cache["expires_at"] = (t + timedelta(hours=TTL_HOURS)).isoformat(timespec="seconds")
    return save(cache)


def save(cache):
    path = _path(cache["session_id"])
    with _lock:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        _mem[cache["session_id"]] = cache
    return path


def delete(session_id):
    with _lock:
        _mem.pop(session_id, None)
        _path(session_id).unlink(missing_ok=True)


def purge_expired():
    """만료된 캐시 파일을 지운다. 지운 개수를 돌려준다."""
    n = 0
    if CACHE_DIR.exists():
        for path in CACHE_DIR.glob("*.json"):
            if load(path.stem) is None:
                n += 1
    return n


def count():
    return len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0
