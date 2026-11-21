from datetime import datetime

from phone_agent.config import KST
from phone_agent.policy import within_broker_slots


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=KST)


SLOTS = {"broker_slots": [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T15:00:00+09:00"},
                          {"start": "2026-11-24T10:00:00+09:00", "end": None}],
         "unverified": [], "availability_note": None}


def test_inside_range_including_end():
    assert within_broker_slots(SLOTS, at("2026-11-23T14:00"))
    assert within_broker_slots(SLOTS, at("2026-11-23T14:30"))
    assert within_broker_slots(SLOTS, at("2026-11-23T15:00"))      # 끝 시각 포함
    assert not within_broker_slots(SLOTS, at("2026-11-23T15:01"))
    assert not within_broker_slots(SLOTS, at("2026-11-23T13:59"))


def test_single_time_slot_means_only_that_time():
    assert within_broker_slots(SLOTS, at("2026-11-24T10:00"))
    assert not within_broker_slots(SLOTS, at("2026-11-24T10:30"))


def test_real_call_1120_afternoon_refused_morning_only():
    # 중개사가 "토요일 오후는 안 되고 오전 9~12시"라고 했는데 오후 2시로 확정 전화가 나갔던 사례(L13)
    morning = {"broker_slots": [{"start": "2026-11-21T09:00:00+09:00", "end": "2026-11-21T12:00:00+09:00"}]}
    assert not within_broker_slots(morning, at("2026-11-21T14:00"))
    assert within_broker_slots(morning, at("2026-11-21T10:00"))


def test_broker_proposed_time_is_allowed():
    assert within_broker_slots(SLOTS, at("2026-11-23T16:30"), proposed=["2026-11-23T16:30:00+09:00"])


def test_not_enough_evidence_does_not_block():
    assert within_broker_slots({"broker_slots": []}, at("2030-01-01T10:00"))
    assert within_broker_slots({**SLOTS, "unverified": ["broker_slots[1]"]}, at("2026-11-23T18:00"))
    assert within_broker_slots({**SLOTS, "availability_note": "평일 오후는 언제든"}, at("2026-11-23T18:00"))
    # 방 정보만 확인 못 한 것은 시간 판단과 무관
    assert not within_broker_slots({**SLOTS, "unverified": ["listings[0].unit"]}, at("2026-11-23T18:00"))
