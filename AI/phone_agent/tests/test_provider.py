import json
from datetime import datetime

import httpx
import pytest

from conftest import example_request
from phone_agent.config import KST, Settings
from phone_agent.provider import KatProvider, ProviderError
from phone_agent.schemas import BatchRequest
from phone_agent.trial import agent_id, trial_request

SETTINGS = Settings(mode="demo", kat_base_url="https://api.example.test/", kat_api_key="k", kat_account_id="AC1",
                    kat_agent_id="AG-base", kat_from_number="070-1234-5678", demo_to="01000000000")


def kat(handler) -> KatProvider:
    client = httpx.Client(base_url="https://api.example.test/v1/accounts/AC1", transport=httpx.MockTransport(handler))
    return KatProvider(SETTINGS, client=client)


def test_base_url_is_domain_plus_v1_account():
    provider = KatProvider(SETTINGS)
    assert str(provider.client.base_url) == "https://api.example.test/v1/accounts/AC1/"
    assert provider.client.headers["Authorization"] == "Bearer k"


def test_missing_settings_are_named():
    with pytest.raises(ValueError, match="KAT_API_KEY"):
        KatProvider(Settings(mode="demo", kat_base_url="https://x"))


def test_create_call_sends_digits_agent_and_instruction():
    seen = {}

    def handler(request: httpx.Request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"callId": "CA1", "status": "queued"})

    call_request = BatchRequest.model_validate(example_request()).calls()[0]
    assert kat(handler).create_call("010-1111-2222", "지시문", request=call_request) == "CA1"
    assert seen["path"] == "/v1/accounts/AC1/calls"
    assert seen["body"] == {"To": "01011112222", "From": "07012345678", "AgentId": "AG-base",
                            "CallContext": {"Instruction": "지시문"}}


def _phases(status: str, events: list[str]) -> dict:
    def handler(request: httpx.Request):
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json={"data": [{"event": e} for e in events]})
        return httpx.Response(200, json={"callId": "CA1", "status": status})
    return kat(handler).get_call("CA1")


def test_get_call_phases_from_events():
    assert _phases("queued", []) == {"phase": "queued", "answered": False}
    assert _phases("ringing", ["call.ringing"]) == {"phase": "ringing", "answered": False}
    assert _phases("in-progress", ["call.ringing", "call.answered"]) == {"phase": "in_progress", "answered": True}
    assert _phases("completed", ["call.ringing", "call.answered", "recording.started", "call.completed"]) == \
        {"phase": "ended", "answered": True}
    # 받지 않고 끝남(실제 값은 미확인: 이벤트에 answered가 없으면 안 받은 것으로)
    assert _phases("no-answer", ["call.ringing"]) == {"phase": "ended", "answered": False}
    assert _phases("completed", ["call.ringing", "call.completed"]) == {"phase": "ended", "answered": False}


def test_transcript_request_and_fetch():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(409, json={"error": "already requested"})
        if len(calls) == 2:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"status": "completed", "callId": "CA1", "segmentCount": 1, "segments": [
            {"speaker": "speaker_0", "start": 0.5, "end": 3.2, "text": "안녕하세요"}]})

    provider = kat(handler)
    provider.request_transcript("CA1")  # 409는 조용히 넘어감
    assert provider.get_transcript("CA1") == {"status": "pending", "segments": []}
    assert provider.get_transcript("CA1") == {"status": "completed", "segments": [
        {"speaker": "speaker_0", "text": "안녕하세요", "start": 0.5, "end": 3.2}]}


def test_errors_become_provider_error():
    with pytest.raises(ProviderError, match="500"):
        kat(lambda r: httpx.Response(500, text="boom")).create_call("010", "x")

    def broken(request):
        raise httpx.ConnectError("down")
    with pytest.raises(ProviderError):
        kat(broken).get_call("CA1")


def test_sms_uses_lms_when_long():
    bodies = []

    def handler(request: httpx.Request):
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"messageId": "MG1"})

    provider = kat(handler)
    assert provider.send_sms("01000000000", "짧은 문자") == "MG1"
    provider.send_sms("01000000000", "가" * 60, subject="[살구] 알림")
    assert "Type" not in bodies[0]
    assert bodies[1]["Type"] == "lms" and bodies[1]["Subject"] == "[살구] 알림"


def test_trial_agent_names(monkeypatch):
    monkeypatch.setenv("KAT_AGENT_ID_LIVE", "AG-live")
    assert agent_id(None, SETTINGS) == "AG-base" and agent_id("base", SETTINGS) == "AG-base"
    assert agent_id("live", SETTINGS) == "AG-live"
    assert agent_id("AG-raw", SETTINGS) == "AG-raw"


def test_trial_request_is_unique_first_broker_with_transcript():
    request = trial_request("c3", datetime(2026, 11, 21, 15, 30, tzinfo=KST))
    assert len(request.brokers) == 1 and request.brokers[0].name == "한빛공인중개사"
    assert request.brokers[0].reg == "trial-c3-20261121-153000"
    assert request.keep_transcript is True
