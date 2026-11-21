import asyncio
import json

from fastapi.testclient import TestClient

from conftest import example_request
from phone_agent.app import create_app
from phone_agent.config import Settings
from phone_agent.mcp_server import build_mcp
from phone_agent.provider import MockProvider
from phone_agent.service import CallService

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def call(mcp, name, args):
    result = asyncio.run(mcp.call_tool(name, args))
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def test_tools_are_listed():
    mcp = build_mcp(CallService(Settings(mode="mock"), MockProvider()))
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == {"call_brokers", "get_call_results", "confirm_visits"}
    assert set(tools["call_brokers"].input_schema["required"]) == {"approval_id", "search", "share", "brokers"}


def test_tools_wrap_the_same_service_and_rules(settings, clock):
    service = CallService(settings, MockProvider(), now=clock)
    mcp = build_mcp(service)
    body = example_request()
    for broker in body["brokers"]:
        broker["visit_windows"] = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"}]

    accepted = call(mcp, "call_brokers", body)
    assert accepted["kind"] == "inquiry" and len(accepted["calls"]) == 2
    assert call(mcp, "call_brokers", body)["batch_id"] == accepted["batch_id"]  # 같은 승인은 다시 걸지 않음
    assert accepted["batch_id"] in service.store.batches  # REST와 같은 기록

    for _ in range(60):  # 기본 시나리오에 '안 받음'이 있으면 30분 뒤 재발신까지 기다림
        result = call(mcp, "get_call_results", {"batch_id": accepted["batch_id"]})
        if result["status"] == "done":
            break
        clock.advance(minutes=1)
    assert result["status"] == "done" and "duplicate_groups" in result
    listing_call = next(c for c in result["calls"] if c["outcome"] == "listing")

    refused = call(mcp, "confirm_visits", {"approval_id": "vs-mcp", "visits": [
        {"call_id": listing_call["call_id"], "at": "2026-11-23T18:00:00+09:00"}]})
    assert refused["error"] == "outside_broker_slots"  # 안전장치도 같음
    ok = call(mcp, "confirm_visits", {"approval_id": "vs-mcp", "visits": [
        {"call_id": listing_call["call_id"], "at": listing_call["broker_slots"][0]["start"]}]})
    assert ok["kind"] == "confirm" and ok["calls"][0]["parent_call_id"] == listing_call["call_id"]

    assert call(mcp, "get_call_results", {"batch_id": "bb_nope"}) == {"error": "not_found"}
    duplicated = dict(body, approval_id="ap-dup-reg", brokers=[body["brokers"][0], body["brokers"][0]])
    assert call(mcp, "call_brokers", duplicated)["error"] == "invalid_request"


def test_mcp_over_http_is_localhost_only_by_default(settings, clock):
    service = CallService(settings, MockProvider(), now=clock)
    with TestClient(create_app(service, background=False)) as client:
        assert client.get("/api/health").json()["mcp"] is True
        ok = client.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Host": "127.0.0.1:8090"})
        assert ok.status_code == 200
        assert "mcp-phone" in ok.text
        outside = client.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Host": "salgu.example.com"})
        assert outside.status_code >= 400


def test_mcp_host_can_be_opened_for_deployment(clock):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, mcp_host="0.0.0.0"), MockProvider(), now=clock)
    with TestClient(create_app(service, background=False)) as client:
        res = client.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Host": "salgu.example.com"})
        assert res.status_code == 200


def test_without_mcp_only_rest(settings, clock):
    service = CallService(settings, MockProvider(), now=clock)
    with TestClient(create_app(service, background=False, with_mcp=False)) as client:
        assert client.get("/api/health").json()["mcp"] is False
        assert client.post("/mcp", json=INIT, headers=MCP_HEADERS).status_code == 404
