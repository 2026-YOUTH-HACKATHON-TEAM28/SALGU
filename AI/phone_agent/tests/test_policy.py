import pytest
from pydantic import ValidationError

from conftest import example_request
from phone_agent.config import KST
from phone_agent.schemas import BatchRequest, ConfirmRequest


def _with(**changes) -> dict:
    data = example_request()
    data.update(changes)
    return data


def _broker(i: int, **extra) -> dict:
    return {"reg": f"reg-{i}", "name": f"사무소{i}", "phone": "02-000-0000", **extra}


def test_request_shape():
    ok = BatchRequest.model_validate(example_request())
    assert [c.broker.reg for c in ok.calls()] == ["11620-2019-00123", "11620-2021-00456"]
    assert ok.calls()[0].windows[0].start.isoformat() == "2026-11-23T14:00:00+09:00"
    assert ok.calls()[0].deadline.isoformat() == "2026-11-23T17:00:00+09:00"

    # 최소 요청: 선택 값은 기본값
    minimal = BatchRequest.model_validate({
        "approval_id": "ap-001",
        "search": {"dong": "봉천동", "housing_type": "villa", "deposit_manwon": 1000, "monthly_rent_manwon": 60},
        "share": {"conditions": True, "visit_time": True},
        "brokers": [_broker(1)],
    })
    assert minimal.prep.pet is False and minimal.keep_transcript is False
    assert minimal.share.surname is False and minimal.share.contact is False
    assert minimal.calls()[0].deadline is None

    # 시간대 없는 시각은 한국 시간, 시간대는 시작 시각순
    sorted_req = BatchRequest.model_validate(_with(brokers=[_broker(1, visit_windows=[
        {"start": "2026-11-24T14:00:00", "end": "2026-11-24T15:00:00"},
        {"start": "2026-11-23T05:00:00Z", "end": "2026-11-23T06:00:00Z"},
    ])]))
    windows = sorted_req.brokers[0].visit_windows
    assert windows[0].start.isoformat() == "2026-11-23T14:00:00+09:00"
    assert windows[1].start.tzinfo == KST

    # share.visit_time이 false면 시간대를 묻지 않음
    no_time = BatchRequest.model_validate(_with(share={"conditions": True, "visit_time": False}))
    assert no_time.calls()[0].windows == []

    bad_cases = [
        _with(approval_id=""),
        _with(approval_id="a" * 81),
        _with(search=dict(example_request()["search"], housing_type="apartment")),
        _with(search=dict(example_request()["search"], deposit_manwon=-1)),
        _with(search=dict(example_request()["search"], monthly_rent_manwon=-5)),
        _with(brokers=[]),
        _with(brokers=[_broker(i) for i in range(11)]),
        _with(brokers=[_broker(1), _broker(1)]),
        _with(brokers=[_broker(1, visit_windows=[{"start": "2026-11-23T15:00:00+09:00",
                                                   "end": "2026-11-23T14:00:00+09:00"}])]),
        _with(brokers=[_broker(1, visit_windows=[{"start": f"2026-11-23T{h:02d}:00:00+09:00",
                                                   "end": f"2026-11-23T{h:02d}:30:00+09:00"}
                                                  for h in range(9, 16)])]),
        _with(prep={"surname": "김박이"}),
        {k: v for k, v in example_request().items() if k != "share"},
    ]
    for data in bad_cases:
        with pytest.raises(ValidationError):
            BatchRequest.model_validate(data)


def test_confirm_request_shape():
    ok = ConfirmRequest.model_validate({"approval_id": "vs-1", "visits": [
        {"call_id": "bc_1", "at": "2026-11-23T14:00:00"}]})
    assert ok.visits[0].listing_index == 0 and ok.visits[0].at.tzinfo == KST

    for visits in (
        [{"call_id": "bc_1", "at": "2026-11-23T14:00:00+09:00"}] * 2,
        [{"call_id": "bc_1", "listing_index": i, "at": "2026-11-23T14:00:00+09:00"} for i in range(4)],
        [],
    ):
        with pytest.raises(ValidationError):
            ConfirmRequest.model_validate({"approval_id": "vs-1", "visits": visits})


# ---------------------------------------------------------------- C2 발신 규칙
from datetime import datetime  # noqa: E402

from phone_agent import policy  # noqa: E402
from phone_agent.config import Settings  # noqa: E402
from phone_agent.policy import PolicyError  # noqa: E402


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=KST)


def test_business_hours():
    assert policy.is_open(at("2026-11-23T09:00"))          # 월 9시
    assert policy.is_open(at("2026-11-23T18:59"))
    assert not policy.is_open(at("2026-11-23T08:59"))
    assert not policy.is_open(at("2026-11-23T19:00"))
    assert policy.is_open(at("2026-11-21T10:00"))          # 토요일
    assert not policy.is_open(at("2026-11-22T10:00"))      # 일요일
    assert not policy.is_open(at("2026-12-25T10:00"))      # 공휴일(messages.json)
    assert not policy.is_open(at("2026-11-24T10:00"), Settings(holidays=("2026-11-24",)))
    assert policy.is_open(at("2026-11-22T23:00"), Settings(ignore_hours=True))


def test_next_open():
    assert policy.next_open(at("2026-11-23T10:00")) == at("2026-11-23T10:00")
    assert policy.next_open(at("2026-11-23T07:00")) == at("2026-11-23T09:00")
    assert policy.next_open(at("2026-11-21T20:00")) == at("2026-11-23T09:00")   # 토 밤 → 월
    assert policy.next_open(at("2026-12-24T19:30")) == at("2026-12-26T09:00")   # 성탄절 건너뜀
    assert policy.next_open(at("2026-12-31T19:00")) == at("2027-01-02T09:00")   # 1월 1일 건너뜀


def _req(reg="r1", windows=None):
    data = example_request()
    data["brokers"] = [{"reg": reg, "name": "사무소", "visit_windows": windows or []}]
    return BatchRequest.model_validate(data).calls()[0]


def _rec(reg, status="done", attempts=1, started_at=None, scheduled_at=None, created_at="2026-11-23T09:30:00+09:00"):
    return {"kind": "inquiry", "status": status, "attempts": attempts, "started_at": started_at,
            "scheduled_at": scheduled_at, "created_at": created_at, "request": {"broker": {"reg": reg}}}


def test_check_counts_the_day_calls_go_out():
    s = Settings(daily_limit=3)
    now = at("2026-11-23T10:00")
    assert policy.check(_req("r1"), now, [], s) is None
    today = _rec("r1", started_at="2026-11-23T09:40:00+09:00")
    with pytest.raises(PolicyError) as exc:
        policy.check(_req("r1"), now, [today], s)
    assert exc.value.code == "already_called_today"
    # 거절·한 번도 못 건 통화는 세지 않고, 기다리는 통화는 셈
    assert policy.check(_req("r1"), now, [_rec("r1", status="rejected", attempts=0),
                                          _rec("r1", status="failed", attempts=0)], s) is None
    with pytest.raises(PolicyError):
        policy.check(_req("r1"), now, [_rec("r1", status="waiting", attempts=0)], s)
    # 어제 건 통화, 내일 나갈 통화는 오늘 수에 안 들어감
    assert policy.check(_req("r1"), now, [_rec("r1", started_at="2026-11-21T10:00:00+09:00"),
                                          _rec("r1", status="scheduled", attempts=0,
                                               scheduled_at="2026-11-24T09:00:00+09:00")], s) is None
    # 하루 수
    full = [_rec(f"x{i}", started_at="2026-11-23T09:3%d:00+09:00" % i) for i in range(3)]
    with pytest.raises(PolicyError) as exc:
        policy.check(_req("r9"), now, full, s)
    assert exc.value.code == "daily_limit"
    # 밤에 접수하면 다음 영업일 수로 셈 → 오늘 꽉 차도 예약됨
    night = at("2026-11-23T20:00")
    assert policy.check(_req("r9"), night, full, s) == at("2026-11-24T09:00")


def test_window_passed_counts_when_the_call_can_go_out():
    morning = [{"start": "2026-11-23T08:00:00+09:00", "end": "2026-11-23T08:30:00+09:00"}]
    with pytest.raises(PolicyError) as exc:
        policy.check(_req("r1", morning), at("2026-11-22T10:00"), [], Settings())  # 일요일 → 월 9시엔 이미 지남
    assert exc.value.code == "window_passed"
    assert policy.deadline_passed(_req("r1", morning), at("2026-11-23T08:30"))
    assert not policy.deadline_passed(_req("r1", morning), at("2026-11-23T08:29"))
    assert not policy.deadline_passed(_req("r1"), at("2030-01-01T10:00"))  # 시간대 없으면 막지 않음


def test_check_mode_and_error_body():
    policy.check_mode(Settings(mode="mock"))
    policy.check_mode(Settings(mode="demo", demo_to="01000000000"))
    with pytest.raises(PolicyError) as exc:
        policy.check_mode(Settings(mode="demo"))
    assert exc.value.body() == {"error": "not_allowed", "message": policy.MESSAGES["not_allowed"]}
    assert PolicyError("outside_broker_slots", {"x": 1}).body()["detail"] == {"x": 1}
