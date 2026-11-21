import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# 로컬 .env가 demo여도 테스트는 mock으로(환경 변수가 .env보다 우선)
os.environ["PHONE_AGENT_MODE"] = "mock"

import pytest  # noqa: E402

from phone_agent.config import KST, Settings  # noqa: E402
from phone_agent.provider import MockProvider  # noqa: E402
from phone_agent.schemas import BatchRequest  # noqa: E402
from phone_agent.service import CallService  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
# 2026-11-23(월) 오전 10시: 영업시간 안, 예시 요청의 방문 시간대(오후 2~5시) 전
START = datetime(2026, 11, 23, 10, 0, tzinfo=KST)


class Clock:
    def __init__(self, now: datetime = START):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings():
    return Settings(mode="mock", poll_interval_sec=0)


@pytest.fixture
def provider():
    return MockProvider()


@pytest.fixture
def service(settings, provider, clock):
    return CallService(settings, provider, now=clock)


def example_request() -> dict:
    return json.loads((FIXTURES / "request.example.json").read_text(encoding="utf-8"))


def make_batch(n: int = 2, approval_id: str = "ap-test", windows=None, regs=None, **overrides) -> BatchRequest:
    """사무소 n곳짜리 문의 묶음. 시간대 기본값은 2026-11-23 오후 2~5시. regs는 사무소 번호(1부터)."""
    data = example_request()
    data["approval_id"] = approval_id
    if windows is None:
        windows = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"}]
    numbers = regs or list(range(1, n + 1))
    data["brokers"] = [
        {"reg": f"11620-2026-{i:05d}", "name": f"테스트{i}공인중개사", "phone": f"02-555-{i:04d}",
         "visit_windows": windows}
        for i in numbers
    ]
    data.update(overrides)
    return BatchRequest.model_validate(data)


def run_until_done(service: CallService, batch: dict, clock: Clock | None = None, limit: int = 100,
                   step: float = 5) -> dict:
    """묶음이 끝날 때까지 조회를 반복한다(조회마다 시계를 step초 넘김)."""
    for _ in range(limit):
        result = service.batch_result(service.get_batch(batch["batch_id"]))
        if result["status"] == "done":
            return result
        if clock:
            clock.advance(seconds=step)
    raise AssertionError(f"묶음이 끝나지 않음: {result}")


def statuses(service: CallService, batch: dict) -> list[str]:
    return [service.store.calls[c]["status"] for c in batch["call_ids"]]
