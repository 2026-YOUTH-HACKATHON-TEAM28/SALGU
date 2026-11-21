"""설정: AI/chat_agent/.env를 읽는다. 키 값은 어디에도 출력하지 않는다.

챗봇은 사용자 말을 조건 카드로 바꾸는 일만 한다. 검색·계산용 키(실거래·지도 등)는 쓰지 않는다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # AI/chat_agent


def _load_env(path):
    """KEY=VALUE 줄을 읽어 사전으로 돌려준다. 파일이 없으면 빈 사전."""
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = _load_env(ROOT / ".env")


def _first(*names):
    """ENV에서 값이 있는 첫 이름의 값. 없으면 빈 문자열."""
    for name in names:
        if ENV.get(name):
            return ENV[name]
    return ""


def _int(name, default):
    """ENV 값을 정수로. 비었거나 숫자가 아니면 기본값."""
    try:
        return int(ENV.get(name) or default)
    except ValueError:
        return default


GEMINI_KEY = _first("GEMINI_API_KEY", *sorted(k for k in ENV if k.startswith("GEMINI_API_KEY")))
GEMINI_MODEL = ENV.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"

API_HOST, API_PORT = "127.0.0.1", 8090
ALLOWED_ORIGINS = {"http://127.0.0.1:8091", "http://localhost:8091"}

# Gemini 무료 등급 기준: 짧게 기다리고, 늦거나 한도에 걸리면 기다리지 않고 규칙 결과로 답한다.
GEMINI_TIMEOUT_S = _int("GEMINI_TIMEOUT_S", 8)
GEMINI_MAX_RPM = _int("GEMINI_MAX_RPM", 10)          # 모델마다 이 서버가 1분에 보낼 최대 요청 수
GEMINI_COOLDOWN_S = _int("GEMINI_COOLDOWN_S", 60)    # 분당 한도 초과(429) 뒤 그 모델을 쉬는 시간(오류에 대기 시간이 없을 때)
# 무료 한도는 모델마다 따로: 기본 모델이 한도에 걸리면 차례로 넘어갈 모델 (쉼표로 여러 개)
GEMINI_FALLBACK_MODELS = [m.strip() for m in (ENV.get("GEMINI_FALLBACK_MODELS") or "gemini-3.5-flash-lite").split(",")
                          if m.strip() and m.strip() != GEMINI_MODEL]
