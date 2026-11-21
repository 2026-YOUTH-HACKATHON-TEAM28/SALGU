"""설정: AI/chat_agent/.env를 읽는다. 키 값은 어디에도 출력하지 않는다."""

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # AI/chat_agent
CACHE_DIR = ROOT / ".cache"


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
DATA_GO_KR_KEY = ENV.get("DATA_GO_KR_SERVICE_KEY", "")
# 카카오 로컬(주소·장소·지하철역 검색): 카카오맵이 켜진 앱의 REST API 키
KAKAO_LOCAL_KEY = _first("KAKAO_REST_API_KEY", "KAKAO_REST_API")

# 환산월세 = 월세 + 보증금 × 전환율 ÷ 12. 기획서 예시값(법정 상한 5.0%).
CONVERSION_RATE = 0.05
CURRENT_YEAR = date.today().year

API_HOST, API_PORT = "127.0.0.1", 8090
ALLOWED_ORIGINS = {"http://127.0.0.1:8091", "http://localhost:8091"}

# Gemini 무료 등급 기준: 짧게 기다리고, 늦거나 한도에 걸리면 기다리지 않고 규칙 결과로 답한다.
GEMINI_TIMEOUT_S = _int("GEMINI_TIMEOUT_S", 8)
GEMINI_MAX_RPM = _int("GEMINI_MAX_RPM", 10)          # 모델마다 이 서버가 1분에 보낼 최대 요청 수
GEMINI_COOLDOWN_S = _int("GEMINI_COOLDOWN_S", 60)    # 분당 한도 초과(429) 뒤 그 모델을 쉬는 시간(오류에 대기 시간이 없을 때)
# 무료 한도는 모델마다 따로: 기본 모델이 한도에 걸리면 차례로 넘어갈 모델 (쉼표로 여러 개)
GEMINI_FALLBACK_MODELS = [m.strip() for m in (ENV.get("GEMINI_FALLBACK_MODELS") or "gemini-3.5-flash-lite").split(",")
                          if m.strip() and m.strip() != GEMINI_MODEL]
# 추천 이유를 LLM으로 쓸지. 기본은 코드 템플릿(즉시, 숫자 정확). 1이면 Gemini + 숫자 검증
EXPLAIN_WITH_LLM = ENV.get("EXPLAIN_WITH_LLM", "0") == "1"

# 받을 서울 데이터 자리. 폴더에 파일(.csv/.json)이 있으면 그걸 쓰고, 없으면 기존 API로 동작한다.
REPO = ROOT.parents[1]
_PUBLIC = REPO / "Data" / "api" / "public"
SEOUL_RENT_DIR = Path(ENV.get("SEOUL_RENT_DIR") or _PUBLIC / "seoul_rent")
SEOUL_SUBWAY_DIR = Path(ENV.get("SEOUL_SUBWAY_DIR") or _PUBLIC / "seoul_subway")
SEOUL_BUS_DIR = Path(ENV.get("SEOUL_BUS_DIR") or _PUBLIC / "seoul_bus")
SEOUL_YOUTH_DIR = Path(ENV.get("SEOUL_YOUTH_DIR") or _PUBLIC / "seoul_youth_housing")
RENT_MONTHS = _int("RENT_MONTHS", 3)  # 후보 검색에 쓰는 최근 개월 수
