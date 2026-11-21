"""설정: `.env`와 환경 변수에서 읽는다. 이름은 `.env.example`과 같다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]  # AI/phone_agent


def load_env_file(path: Path | str = ROOT / ".env") -> None:
    """`.env`를 읽어 환경 변수에 넣는다. 이미 있는 환경 변수가 우선한다."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")



@dataclass(frozen=True)
class Settings:
    mode: str = "mock"  # "mock" | "demo"
    kat_base_url: str = ""
    kat_api_key: str = ""
    kat_account_id: str = ""
    kat_agent_id: str = ""
    kat_from_number: str = ""
    demo_to: str = ""
    # demo 에서 요청에 담긴 번호로 건다(화면이 사용자가 입력한 본인 번호를 담아 보냄). 휴대폰 번호만 허용
    dial_requested: bool = False
    daily_limit: int = 10
    confirm_limit: int = 2
    retry_minutes: int = 30
    ignore_hours: bool = False
    holidays: tuple[str, ...] = ()
    call_gap_sec: int = 0
    poll_interval_sec: int = 3
    analyze_timeout_sec: int = 300
    transcript_days: int = 30
    registry_poll_sec: int = 30
    upload_keep_hours: int = 24
    notify_to: str = ""
    kakao_access_token: str = ""
    kakao_refresh_token: str = ""
    kakao_rest_api_key: str = ""
    app_url: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    store_path: Path = field(default=ROOT / ".data" / "calls.json")
    cors_origins: tuple[str, ...] = ("*",)
    mcp_host: str = "127.0.0.1"
    record: bool = False  # 기획서: 음성은 저장하지 않음. 대화록은 실시간 전사(liveEvents)로. True는 속도 실험용

    @property
    def demo_numbers(self) -> tuple[str, ...]:
        return _split(self.demo_to)

    @property
    def demo_number(self) -> str:
        return self.demo_numbers[0] if self.demo_numbers else ""

    @property
    def registry_number(self) -> str:
        return self.kat_from_number

    @property
    def notify_number(self) -> str:
        return self.notify_to or self.demo_number

    @classmethod
    def from_env(cls, env_file: Path | str | None = ROOT / ".env") -> "Settings":
        if env_file is not None:
            load_env_file(env_file)
        get = lambda name, default="": os.environ.get(name, default).strip()  # noqa: E731
        mode = get("PHONE_AGENT_MODE", "mock").lower() or "mock"
        if mode not in ("mock", "demo"):
            raise ValueError(f"PHONE_AGENT_MODE는 mock 또는 demo여야 합니다: {mode!r}")
        return cls(
            mode=mode,
            kat_base_url=get("KAT_BASE_URL"),
            kat_api_key=get("KAT_API_KEY"),
            kat_account_id=get("KAT_ACCOUNT_ID"),
            kat_agent_id=get("KAT_AGENT_ID"),
            kat_from_number=get("KAT_FROM_NUMBER"),
            demo_to=get("PHONE_AGENT_DEMO_TO"),
            dial_requested=_flag("PHONE_AGENT_DIAL_REQUESTED"),
            daily_limit=_int("PHONE_AGENT_DAILY_LIMIT", 10),
            confirm_limit=_int("PHONE_AGENT_CONFIRM_LIMIT", 2),
            retry_minutes=_int("PHONE_AGENT_RETRY_MINUTES", 30),
            ignore_hours=_flag("PHONE_AGENT_IGNORE_HOURS"),
            holidays=_split(get("PHONE_AGENT_HOLIDAYS")),
            call_gap_sec=_int("PHONE_AGENT_CALL_GAP_SEC", 0),
            poll_interval_sec=_int("PHONE_AGENT_POLL_INTERVAL_SEC", 3),
            analyze_timeout_sec=_int("PHONE_AGENT_ANALYZE_TIMEOUT_SEC", 300),
            transcript_days=_int("PHONE_AGENT_TRANSCRIPT_DAYS", 30),
            registry_poll_sec=_int("PHONE_AGENT_REGISTRY_POLL_SEC", 30),
            upload_keep_hours=_int("PHONE_AGENT_UPLOAD_KEEP_HOURS", 24),
            notify_to=get("PHONE_AGENT_NOTIFY_TO"),
            kakao_access_token=get("KAKAO_ACCESS_TOKEN"),
            kakao_refresh_token=get("KAKAO_REFRESH_TOKEN"),
            kakao_rest_api_key=get("KAKAO_REST_API_KEY"),
            app_url=get("PHONE_AGENT_APP_URL"),
            openai_api_key=get("OPENAI_API_KEY"),
            openai_base_url=get("OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1",
            llm_model=get("PHONE_AGENT_LLM_MODEL"),
            cors_origins=_split(get("PHONE_AGENT_CORS_ORIGINS", "*")) or ("*",),
            mcp_host=get("PHONE_AGENT_MCP_HOST", "127.0.0.1") or "127.0.0.1",
            record=_flag("PHONE_AGENT_RECORD"),
        )
