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
