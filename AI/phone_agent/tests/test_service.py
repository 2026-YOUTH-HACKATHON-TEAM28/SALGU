from fastapi.testclient import TestClient

from conftest import Clock, example_request, make_batch, run_until_done, statuses
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


def test_one_call_at_a_time_in_order(service, clock):
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


def test_declined_outcome(service, clock):
    batch, _ = service.create_batch(make_batch(1, approval_id="ap-out"), scenarios=["declined"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "declined" and call["attempts"] == 1 and call["sms_draft"] is None


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


# ---------------------------------------------------------------- C2 발신 규칙
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from phone_agent.config import KST, Settings  # noqa: E402
from phone_agent.policy import PolicyError  # noqa: E402
from phone_agent.provider import MockProvider, ProviderError  # noqa: E402
from phone_agent.service import ON_LINE  # noqa: E402


def test_next_call_does_not_wait_for_analysis(settings, clock):
    class SlowTranscript(MockProvider):
        def get_transcript(self, call_id):
            return {"status": "in_progress", "segments": []}

    service = CallService(settings, SlowTranscript(), now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-slow"), scenarios=["listing", "listing"])
    for _ in range(5):
        service.get_batch(batch["batch_id"])
        clock.advance(seconds=5)
    first, second = statuses(service, batch)
    assert first == "analyzing" and second in ON_LINE
    clock.advance(seconds=settings.analyze_timeout_sec + 1)
    result = run_until_done(service, batch, clock)
    assert [c["status"] for c in result["calls"]] == ["done", "done"]


def test_rejections_are_per_broker(clock, provider):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, daily_limit=3), provider, now=clock)
    first, _ = service.create_batch(make_batch(regs=[1, 2], approval_id="ap-r1"), scenarios=["listing"] * 2)
    run_until_done(service, first, clock)

    second, created = service.create_batch(make_batch(regs=[1, 3, 4, 5], approval_id="ap-r2"))
    assert created
    calls = service.accepted(second)["calls"]
    assert [c["status"] for c in calls] == ["rejected", "queued", "rejected", "rejected"]
    assert [c.get("error") for c in calls] == ["already_called_today", None, "daily_limit", "daily_limit"]
    assert calls[0]["message"] == "같은 중개사무소에는 하루 1번만 문의 전화를 해요."
    result = run_until_done(service, second, clock)
    assert [c["status"] for c in result["calls"]] == ["rejected", "done", "rejected", "rejected"]
    assert result["calls"][0]["outcome"] is None

    past = [{"start": "2026-11-23T08:00:00+09:00", "end": "2026-11-23T09:00:00+09:00"}]
    third, _ = service.create_batch(make_batch(regs=[9], approval_id="ap-r3", windows=past))
    assert service.accepted(third)["calls"][0]["error"] == "window_passed"


def test_window_passed_while_waiting_fails(service, clock):
    soon = [{"start": "2026-11-23T10:00:00+09:00", "end": "2026-11-23T10:00:30+09:00"}]
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-wp", windows=soon), scenarios=["listing"] * 2)
    result = run_until_done(service, batch, clock, step=10)
    first, second = result["calls"]
    assert first["status"] == "done"
    assert second["status"] == "failed" and second["error"] == "window_passed" and second["attempts"] == 0


def test_no_answer_or_voicemail_retries_once_then_drafts_sms(service, provider, clock):
    batch, _ = service.create_batch(make_batch(3, approval_id="ap-na"),
                                    scenarios=["no_answer", "voicemail", "listing"])
    for _ in range(30):  # 다시 걸 통화는 줄을 막지 않음
        service.get_batch(batch["batch_id"])
        if statuses(service, batch) == ["retry_wait", "retry_wait", "done"]:
            break
        clock.advance(seconds=5)
    assert statuses(service, batch) == ["retry_wait", "retry_wait", "done"]
    rec = service.store.calls[batch["call_ids"][0]]
    assert datetime.fromisoformat(rec["retry_at"]) - datetime.fromisoformat(rec["ended_at"]) == timedelta(minutes=30)
    assert len(provider.calls) == 3

    clock.advance(minutes=31)
    result = run_until_done(service, batch, clock)
    for call in result["calls"][:2]:
        assert call["outcome"] == "no_answer" and call["attempts"] == 2
        assert call["sms_draft"] and "AI 비서 살구" in call["sms_draft"]
    assert result["calls"][2]["attempts"] == 1
    assert len(provider.calls) == 5  # 1번만 다시


def test_retry_goes_before_waiting_calls(clock, provider):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, retry_minutes=0), provider, now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-order"), scenarios=["no_answer", "listing"])
    run_until_done(service, batch, clock)
    dialed = [call["request"].broker.reg for call in provider.calls.values()]
    assert dialed == ["11620-2026-00001", "11620-2026-00001", "11620-2026-00002"]


def test_outside_hours_is_scheduled_then_dialed(provider):
    clock = Clock(datetime(2026, 11, 21, 20, 0, tzinfo=KST))  # 토요일 밤 → 월요일 9시
    service = CallService(Settings(mode="mock", poll_interval_sec=0), provider, now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-night"), scenarios=["listing"] * 2)
    calls = service.accepted(batch)["calls"]
    assert [c["status"] for c in calls] == ["scheduled", "scheduled"]
    assert calls[0]["scheduled_at"] == "2026-11-23T09:00:00+09:00"
    clock.advance(hours=12)  # 일요일 오전: 아직
    service.get_batch(batch["batch_id"])
    assert provider.calls == {}

    clock.now = datetime(2026, 11, 23, 9, 0, tzinfo=KST)
    result = run_until_done(service, batch, clock)
    assert [c["outcome"] for c in result["calls"]] == ["listing", "listing"]


def test_waiting_call_is_rescheduled_when_hours_end(provider):
    clock = Clock(datetime(2026, 11, 23, 18, 59, 50, tzinfo=KST))
    windows = [{"start": "2026-11-24T14:00:00+09:00", "end": "2026-11-24T17:00:00+09:00"}]
    service = CallService(Settings(mode="mock", poll_interval_sec=0), provider, now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-late", windows=windows), scenarios=["listing"] * 2)
    for _ in range(10):
        service.get_batch(batch["batch_id"])
        clock.advance(seconds=10)
    assert statuses(service, batch) == ["done", "scheduled"]
    assert service.store.calls[batch["call_ids"][1]]["scheduled_at"] == "2026-11-24T09:00:00+09:00"


def test_ignore_hours_dials_at_night(provider):
    clock = Clock(datetime(2026, 11, 22, 23, 0, tzinfo=KST))  # 일요일 밤
    service = CallService(Settings(mode="mock", poll_interval_sec=0, ignore_hours=True), provider, now=clock)
    batch, _ = service.create_batch(make_batch(1, approval_id="ap-ignore"), scenarios=["listing"])
    assert statuses(service, batch) == ["queued"]


def test_provider_failure_moves_on_and_does_not_use_up_the_day(settings, clock):
    class FailOnce(MockProvider):
        failed = False

        def create_call(self, to, instruction, request=None, scenario=None):
            if not self.failed:
                self.failed = True
                raise ProviderError("boom")
            return super().create_call(to, instruction, request, scenario)

    service = CallService(settings, FailOnce(), now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-fail"), scenarios=["listing"] * 2)
    result = run_until_done(service, batch, clock)
    assert result["calls"][0]["status"] == "failed" and result["calls"][0]["error"] == "provider_error"
    assert result["calls"][1]["outcome"] == "listing"

    again, _ = service.create_batch(make_batch(regs=[1], approval_id="ap-fail-2"), scenarios=["listing"])
    assert statuses(service, again) == ["queued"]  # 한 번도 못 건 통화는 하루 1번에 세지 않음


def test_polling_is_throttled(clock):
    class Counting(MockProvider):
        polls = 0

        def get_call(self, call_id):
            self.polls += 1
            return super().get_call(call_id)

    provider = Counting()
    service = CallService(Settings(mode="mock", poll_interval_sec=3), provider, now=clock)
    batch, _ = service.create_batch(make_batch(1, approval_id="ap-poll"), scenarios=["listing"])
    call_id = batch["call_ids"][0]
    for _ in range(10):
        service.get(call_id)
    assert provider.polls == 1
    clock.advance(seconds=2)
    service.get(call_id)
    assert provider.polls == 1
    clock.advance(seconds=1)
    service.get(call_id)
    assert provider.polls == 2


def test_call_gap_between_calls(clock, provider):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, call_gap_sec=15), provider, now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-gap"), scenarios=["listing"] * 2)
    for _ in range(5):
        service.get_batch(batch["batch_id"])
    assert statuses(service, batch) == ["done", "waiting"]
    clock.advance(seconds=14)
    service.get_batch(batch["batch_id"])
    assert statuses(service, batch)[1] == "waiting"
    clock.advance(seconds=1)
    service.get_batch(batch["batch_id"])
    assert statuses(service, batch)[1] == "queued"


def test_demo_dials_only_demo_numbers_in_turn(clock, provider):
    settings = Settings(mode="demo", demo_to="01011112222, 01033334444", poll_interval_sec=0, retry_minutes=1)
    service = CallService(settings, provider, now=clock)
    batch, _ = service.create_batch(make_batch(3, approval_id="ap-demo"),
                                    scenarios=["no_answer", "listing", "listing"])
    clock_step = 5
    for _ in range(40):
        service.get_batch(batch["batch_id"])
        clock.advance(seconds=clock_step)
    run_until_done(service, batch, clock)
    dialed = [(call["request"].broker.reg[-1], call["to"]) for call in provider.calls.values()]
    assert dialed == [("1", "01011112222"), ("2", "01033334444"), ("3", "01011112222"),
                      ("1", "01011112222")]  # 재발신은 처음 번호


def test_demo_without_number_is_not_allowed(clock, provider):
    service = CallService(Settings(mode="demo", poll_interval_sec=0), provider, now=clock)
    with pytest.raises(PolicyError) as exc:
        service.create_batch(make_batch(1, approval_id="ap-nonum"))
    assert exc.value.code == "not_allowed"
    assert service.store.calls == {} and service.store.batches == {}

    client = TestClient(create_app(service, background=False, with_mcp=False))
    res = client.post("/api/broker-call-batches", json=example_request())
    assert res.status_code == 409
    assert res.json() == {"error": "not_allowed", "message": "시연 모드에서 전화를 받을 번호가 설정되지 않았어요."}


# ---------------------------------------------------------------- C5 확정 통화
from phone_agent.schemas import ConfirmRequest  # noqa: E402

AT_14 = "2026-11-23T14:00:00+09:00"


def _inquire(service, clock, scenario="listing", approval_id="ap-c", regs=None):
    batch, _ = service.create_batch(make_batch(regs=regs or [1], approval_id=approval_id), scenarios=[scenario])
    return run_until_done(service, batch, clock)["calls"][0]


def _confirm(service, visits, approval_id="vs-1", scenarios=None):
    return service.create_confirmations(ConfirmRequest.model_validate({"approval_id": approval_id, "visits": visits}),
                                        scenarios=scenarios)


def test_confirm_flow_is_requesting_then_confirmed(service, provider, clock):
    inquiry = _inquire(service, clock)
    batch, created = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14}], scenarios=["confirmed"])
    assert created and batch["batch_id"].startswith("vb_")
    accepted = service.accepted(batch)
    assert accepted["kind"] == "confirm" and accepted["calls"][0]["parent_call_id"] == inquiry["call_id"]

    first = service.batch_result(service.get_batch(batch["batch_id"]))
    assert "duplicate_groups" not in first
    call = first["calls"][0]
    assert call["visit_status"] == "requesting" and call["rooms"][0]["visit_status"] == "requesting"
    assert call["target"]["rooms"][0]["at"] == AT_14

    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "confirmed" and call["visit_status"] == "confirmed"
    room = call["rooms"][0]
    assert room["visit"] == {"at": AT_14, "place": "테스트1공인중개사 사무소", "listing_index": 0}
    assert room["unit"] == "302호" and room["still_available"] is True
    assert call["visit"] == room["visit"] and call["unit"] == "302호"  # 방 하나면 바깥에도
    assert call["evidence"]["visit.at"] == 5

    instruction = list(provider.calls.values())[-1]["instruction"]
    assert "[이번 통화: 방문 확정]" in instruction and "보러 갈 방: 해든빌라 3층" in instruction
    assert "아까 방 문의드렸던" in instruction


def test_confirm_requires_a_finished_listing_call(service, clock):
    no_room = _inquire(service, clock, "no_listing", approval_id="ap-none", regs=[2])
    for visit, code in (
        ({"call_id": "bc_nope", "at": AT_14}, "call_not_found"),
        ({"call_id": no_room["call_id"], "at": AT_14}, "call_not_found"),
    ):
        with pytest.raises(PolicyError) as exc:
            _confirm(service, [visit])
        assert exc.value.code == code
    listing = _inquire(service, clock, approval_id="ap-one", regs=[3])
    with pytest.raises(PolicyError) as exc:
        _confirm(service, [{"call_id": listing["call_id"], "at": AT_14},
                           {"call_id": listing["call_id"], "listing_index": 1, "at": AT_14}])
    assert exc.value.code == "listing_not_found"
    assert not [b for b in service.store.batches.values() if b["kind"] == "confirm"]  # 요청 전체 거절


def test_confirm_outside_broker_slots_is_refused(service, provider, clock):
    inquiry = _inquire(service, clock)  # 중개사: 오후 2~3시
    calls_before = len(provider.calls)
    with pytest.raises(PolicyError) as exc:
        _confirm(service, [{"call_id": inquiry["call_id"], "at": "2026-11-23T16:00:00+09:00"}])
    assert exc.value.code == "outside_broker_slots"
    assert exc.value.detail["broker_slots"] == [{"start": AT_14, "end": "2026-11-23T15:00:00+09:00"}]
    assert len(provider.calls) == calls_before  # 전화를 걸지 않음


def test_confirm_allows_the_time_the_broker_proposed(service, clock):
    inquiry = _inquire(service, clock)
    batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14}], scenarios=["alternative"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "alternative" and call["rooms"][0]["visit_status"] == "needs_approval"
    proposed = call["rooms"][0]["proposal"]["at"]
    assert proposed == "2026-11-23T16:00:00+09:00"
    again, created = _confirm(service, [{"call_id": inquiry["call_id"], "at": proposed}], approval_id="vs-2",
                              scenarios=["confirmed"])
    assert created


def test_confirm_shifted_to_alternative_range(service, clock):
    inquiry = _inquire(service, clock)
    batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14, "alternatives": [
        {"start": "2026-11-23T14:30:00+09:00", "end": "2026-11-23T15:00:00+09:00"}]}], scenarios=["shifted"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "confirmed" and call["visit"]["at"] == "2026-11-23T14:30:00+09:00"


def test_confirm_not_scheduled_outcomes(service, clock):
    for i, scenario in enumerate(("no_time", "unavailable", "declined")):
        inquiry = _inquire(service, clock, approval_id=f"ap-ns{i}", regs=[10 + i])
        batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14}], approval_id=f"vs-ns{i}",
                            scenarios=[scenario])
        call = run_until_done(service, batch, clock)["calls"][0]
        assert call["outcome"] == scenario
        assert call["visit_status"] == "not_scheduled" and call["rooms"][0]["visit_status"] == "not_scheduled"
        assert call["visit"] is None


def test_confirm_same_approval_and_limit_per_inquiry(service, clock):
    inquiry = _inquire(service, clock)
    visit = [{"call_id": inquiry["call_id"], "at": AT_14}]
    first, _ = _confirm(service, visit, approval_id="vs-a", scenarios=["no_time"])
    again, created = _confirm(service, visit, approval_id="vs-a")
    assert not created and again["batch_id"] == first["batch_id"]
    run_until_done(service, first, clock)
    second, _ = _confirm(service, visit, approval_id="vs-b", scenarios=["no_time"])
    run_until_done(service, second, clock)
    third, _ = _confirm(service, visit, approval_id="vs-c")
    assert service.accepted(third)["calls"][0]["error"] == "confirm_limit"
    call = service.batch_result(third)["calls"][0]
    assert call["status"] == "rejected" and call["visit_status"] == "not_scheduled"


def test_confirm_calls_do_not_use_up_the_inquiry_day(clock, provider):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, daily_limit=1), provider, now=clock)
    inquiry = _inquire(service, clock)
    batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14}], scenarios=["confirmed"])
    assert service.accepted(batch)["calls"][0]["status"] == "queued"  # 하루 1통을 썼어도 확정은 걸림


def test_two_rooms_confirm_in_one_call(service, provider, clock):
    inquiry = _inquire(service, clock, "two_rooms")
    assert len(inquiry["listings"]) == 2
    batch, _ = _confirm(service, [
        {"call_id": inquiry["call_id"], "listing_index": 1, "at": "2026-11-23T14:30:00+09:00"},
        {"call_id": inquiry["call_id"], "listing_index": 0, "at": AT_14},
    ], scenarios=["partial"])
    assert len(batch["call_ids"]) == 1  # 같은 사무소는 한 통
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "partial" and call["visit_status"] == "partially_confirmed"
    first, second = call["rooms"]
    assert (first["listing_index"], first["visit_status"], first["unit"]) == (0, "confirmed", "302호")
    assert (second["listing_index"], second["visit_status"], second["unit"]) == (1, "needs_approval", "303호")
    assert second["proposal"]["at"] == "2026-11-23T16:30:00+09:00"
    assert call["visit"] is None and call["unit"] is None  # 방이 여럿이면 바깥 값은 null
    assert set(call["evidence"]) >= {"rooms[0].visit.at", "rooms[1].proposal.at"}
    instruction = list(provider.calls.values())[-1]["instruction"]
    assert "보러 갈 방 1: 해든빌라 3층" in instruction and "보러 갈 방 2: 새솔빌 2층" in instruction


def test_two_rooms_both_confirmed(service, clock):
    inquiry = _inquire(service, clock, "two_rooms")
    batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "listing_index": 0, "at": AT_14},
                                  {"call_id": inquiry["call_id"], "listing_index": 1, "at": "2026-11-23T14:30:00+09:00"}],
                        scenarios=["confirmed"])
    call = run_until_done(service, batch, clock)["calls"][0]
    assert call["outcome"] == "confirmed"
    assert [r["visit"]["at"] for r in call["rooms"]] == [AT_14, "2026-11-23T14:30:00+09:00"]


def test_confirm_no_answer_retries_then_not_scheduled(clock, provider):
    service = CallService(Settings(mode="mock", poll_interval_sec=0, retry_minutes=1), provider, now=clock)
    inquiry = _inquire(service, clock)
    batch, _ = _confirm(service, [{"call_id": inquiry["call_id"], "at": AT_14}], scenarios=["no_answer"])
    call = run_until_done(service, batch, clock, step=20)["calls"][0]
    assert call["outcome"] == "no_answer" and call["attempts"] == 2
    assert call["rooms"][0]["visit_status"] == "not_scheduled"
    assert call["sms_draft"] and "보러 가도 될지" in call["sms_draft"]


def test_demo_confirm_dials_the_number_that_took_the_inquiry(clock, provider):
    settings = Settings(mode="demo", demo_to="01011112222,01033334444", poll_interval_sec=0)
    service = CallService(settings, provider, now=clock)
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-dd"), scenarios=["listing", "listing"])
    second = run_until_done(service, batch, clock)["calls"][1]
    _confirm(service, [{"call_id": second["call_id"], "at": AT_14}], scenarios=["confirmed"])
    assert list(provider.calls.values())[-1]["to"] == "01033334444"


def test_confirm_http_api(settings, provider, clock):
    service = CallService(settings, provider, now=clock)
    client = TestClient(create_app(service, background=False, with_mcp=False))
    inquiry = _inquire(service, clock)
    body = {"approval_id": "vs-http", "visits": [{"call_id": inquiry["call_id"], "at": AT_14}]}
    res = client.post("/api/visit-confirmations", json=body, headers={"X-Mock-Scenario": "confirmed"})
    assert res.status_code == 201 and res.json()["kind"] == "confirm"
    batch_id = res.json()["batch_id"]
    assert client.post("/api/visit-confirmations", json=body).status_code == 200
    for _ in range(30):
        result = client.get(f"/api/visit-confirmations/{batch_id}").json()
        if result["status"] == "done":
            break
    assert result["calls"][0]["rooms"][0]["visit_status"] == "confirmed"
    assert client.get(f"/api/broker-call-batches/{batch_id}").status_code == 404   # 종류가 다르면 없음
    assert client.get(f"/api/visit-confirmations/{inquiry['batch_id']}").status_code == 404

    res = client.post("/api/visit-confirmations", json={"approval_id": "vs-out", "visits": [
        {"call_id": inquiry["call_id"], "at": "2026-11-23T18:00:00+09:00"}]})
    assert res.status_code == 409 and res.json()["error"] == "outside_broker_slots"
    assert res.json()["message"].startswith("중개사가 문의 통화에서 말한 가능 시간 밖이에요")
    assert client.post("/api/visit-confirmations", json={"approval_id": "vs-bad", "visits": []}).status_code == 422


# ---------------------------------------------------------------- C7 중복 매물
def test_duplicate_groups_in_inquiry_results(service, clock):
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-dupe"), scenarios=["listing", "two_rooms"])
    result = run_until_done(service, batch, clock)
    groups = result["duplicate_groups"]
    assert len(groups) == 1 and groups[0]["status"] == "suspected"
    assert [(m["call_id"], m["listing_index"]) for m in groups[0]["members"]] == [
        (batch["call_ids"][0], 0), (batch["call_ids"][1], 0)]
    assert groups[0]["reasons"] == ["같은 건물: 해든빌라", "같은 층: 3층", "보증금·월세 같음"]


def test_duplicate_groups_recomputed_with_confirmed_units(service, clock):
    batch, _ = service.create_batch(make_batch(2, approval_id="ap-dupe2"), scenarios=["listing", "listing"])
    calls = run_until_done(service, batch, clock)["calls"]
    for i, call in enumerate(calls):  # mock 확정 통화는 둘 다 302호
        confirm, _ = _confirm(service, [{"call_id": call["call_id"], "at": AT_14}], approval_id=f"vs-d{i}",
                              scenarios=["confirmed"])
        run_until_done(service, confirm, clock)
    group = service.batch_result(service.get_batch(batch["batch_id"]))["duplicate_groups"][0]
    assert group["status"] == "likely_same" and "같은 호수: 302호" in group["reasons"]
