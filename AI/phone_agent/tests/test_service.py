from fastapi.testclient import TestClient

from conftest import example_request, make_batch, run_until_done
from phone_agent.app import create_app
from phone_agent.service import CallService


def test_inquiry_flow(service, clock):
    batch, created = service.create_batch(make_batch(2), scenarios=["listing", "no_listing"])
    assert created
    accepted = service.accepted(batch)
    assert batch["batch_id"].startswith("bb_")
    assert [c["status"] for c in accepted["calls"]] == ["queued", "waiting"]
    assert all(c["call_id"].startswith("bc_") for c in accepted["calls"])

    result = run_until_done(service, batch, clock)
    first, second = result["calls"]
    assert result["version"] == "0.3.1" and result["kind"] == "inquiry"
    assert result["duplicate_groups"] == [] and result["notifications"] == []

    assert first["status"] == "done" and first["outcome"] == "listing"
    assert first["broker"] == {"reg": "11620-2026-00001", "name": "테스트1공인중개사"}
    room = first["listings"][0]
    assert room["building"] == "해든빌라" and room["floor"] == "3층"
    assert room["deposit_manwon"] == 1000 and room["monthly_rent_manwon"] == 60
    assert room["maintenance_fee_manwon"] == 7 and room["move_in"] == "다음 달 초"
    # mock 대화록·결과의 시각은 요청 시간대(11-23 월 14시)로 채워짐
    assert first["broker_slots"] == [{"start": "2026-11-23T14:00:00+09:00",
                                      "end": "2026-11-23T15:00:00+09:00", "in_user_window": True}]
    assert "월요일 오후 2시" in first["quotes"]["9"]["text"]
    assert first["quotes"]["3"]["speaker"] == "broker"
    assert first["transcript"] == []  # 보관 동의 없음
    assert first["called_at"] and first["ended_at"]

    assert second["outcome"] == "no_listing" and second["listings"] == []


def test_one_call_on_the_line_in_order(service, clock):
    batch, _ = service.create_batch(make_batch(3), scenarios=["listing", "listing", "listing"])
    seen_on_line = []
    for _ in range(50):
        result = service.batch_result(service.get_batch(batch["batch_id"]))
        on_line = [c["call_id"] for c in result["calls"] if c["status"] in ("queued", "ringing", "in_progress")]
        assert len(on_line) <= 1
        if on_line and on_line[0] not in seen_on_line:
            seen_on_line.append(on_line[0])
        if result["status"] == "done":
            break
    assert seen_on_line == batch["call_ids"]


def test_same_approval_does_not_dial_twice(service, provider, clock):
    batch, created = service.create_batch(make_batch(2, approval_id="ap-dup"))
    again, created_again = service.create_batch(make_batch(2, approval_id="ap-dup"))
    assert created and not created_again
    assert again["batch_id"] == batch["batch_id"]
    run_until_done(service, batch, clock)
    service.create_batch(make_batch(2, approval_id="ap-dup"))
    assert len(provider.calls) == 2


def test_request_values_fill_mock_transcript(service, clock):
    request = make_batch(1, approval_id="ap-fill")
    request.search.ref_building = "새솔빌"
    request.search.monthly_rent_manwon = 55
    batch, _ = service.create_batch(request, scenarios=["listing"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["listings"][0]["building"] == "새솔빌"
    assert call["listings"][0]["location"] == "새솔빌 3층"
    assert call["listings"][0]["monthly_rent_manwon"] == 55
    assert "새솔빌 3층" in call["quotes"]["3"]["text"]  # 중개사 줄
    assert "월세 55만 원" in call["quotes"]["3"]["text"]


def test_keep_transcript_and_unknown_scenario(service, clock):
    request = make_batch(1, approval_id="ap-keep", keep_transcript=True)
    batch, _ = service.create_batch(request, scenarios=["없는시나리오"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["transcript"] and call["transcript"][0]["speaker"] == "ai"
    assert "테스트1공인중개사이죠?" in call["transcript"][0]["text"]


def test_no_answer_voicemail_declined_outcomes(service, clock):
    batch, _ = service.create_batch(make_batch(3, approval_id="ap-out"),
                                    scenarios=["no_answer", "voicemail", "declined"])
    calls = run_until_done(service, batch, clock)["calls"]
    assert [c["outcome"] for c in calls] == ["no_answer", "no_answer", "declined"]


def test_http_api(settings, provider, clock):
    service = CallService(settings, provider, now=clock)
    client = TestClient(create_app(service, background=False, with_mcp=False))

    health = client.get("/api/health").json()
    assert health == {"ok": True, "mode": "mock", "notify": "log", "mcp": False, "registry_inbox": False}

    body = example_request()
    for broker in body["brokers"]:
        broker["visit_windows"] = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"}]
    res = client.post("/api/broker-call-batches", json=body, headers={"X-Mock-Scenario": "listing,two_rooms"})
    assert res.status_code == 201
    accepted = res.json()
    assert set(accepted) == {"batch_id", "kind", "approval_id", "calls"}
    assert accepted["kind"] == "inquiry" and accepted["approval_id"] == body["approval_id"]
    assert [c["reg"] for c in accepted["calls"]] == [b["reg"] for b in body["brokers"]]

    again = client.post("/api/broker-call-batches", json=body)
    assert again.status_code == 200 and again.json()["batch_id"] == accepted["batch_id"]

    batch_id = accepted["batch_id"]
    for _ in range(50):
        result = client.get(f"/api/broker-call-batches/{batch_id}").json()
        if result["status"] == "done":
            break
        assert result["status"] == "running"
    assert result["status"] == "done"
    assert [c["outcome"] for c in result["calls"]] == ["listing", "listing"]
    assert len(result["calls"][1]["listings"]) == 2  # two_rooms
    assert result["calls"][1]["listings"][1]["monthly_rent_manwon"] == 65

    call_id = accepted["calls"][0]["call_id"]
    one = client.get(f"/api/broker-calls/{call_id}")
    assert one.status_code == 200 and one.json()["call_id"] == call_id

    assert client.get("/api/broker-call-batches/bb_nope").json() == {"error": "not_found"}
    assert client.get("/api/broker-call-batches/bb_nope").status_code == 404
    assert client.get("/api/broker-calls/bc_nope").status_code == 404

    calls_before = len(service.store.calls)
    bad = dict(body, approval_id="ap-bad")
    bad["search"] = dict(body["search"], housing_type="apartment")
    res = client.post("/api/broker-call-batches", json=bad)
    assert res.status_code == 422
    assert res.json()["error"] == "invalid_request"
    assert res.json()["detail"][0]["field"] == "search.housing_type"
    assert client.post("/api/broker-call-batches", content=b"not json",
                       headers={"Content-Type": "application/json"}).status_code == 422
    assert len(service.store.calls) == calls_before


def test_store_saves_to_file(settings, provider, clock, tmp_path):
    from phone_agent.service import Store

    path = tmp_path / "calls.json"
    service = CallService(settings, provider, store=Store(path), now=clock)
    batch, _ = service.create_batch(make_batch(1, approval_id="ap-file"), scenarios=["listing"])
    run_until_done(service, batch, clock)
    reloaded = Store(path)
    assert batch["batch_id"] in reloaded.batches
    assert reloaded.calls[batch["call_ids"][0]]["outcome"] == "listing"
