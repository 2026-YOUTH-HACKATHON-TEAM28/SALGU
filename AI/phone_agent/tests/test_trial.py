from phone_agent.trial import confirm_time


def test_confirm_time_prefers_slots_in_the_user_window():
    result = {"broker_slots": [
        {"start": "2026-11-21T09:00:00+09:00", "end": "2026-11-21T12:00:00+09:00", "in_user_window": False},
        {"start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T15:00:00+09:00", "in_user_window": True},
    ]}
    assert confirm_time(result).isoformat() == "2026-11-21T14:00:00+09:00"


def test_confirm_time_uses_what_the_broker_said_even_outside_the_window():
    # 11-20 live 2차: 중개사가 오전만 된다고 하면 오전으로(미리 정한 오후 2시로 걸지 않음, L13)
    result = {"broker_slots": [{"start": "2026-11-21T09:00:00+09:00", "end": "2026-11-21T12:00:00+09:00",
                                "in_user_window": False}]}
    assert confirm_time(result).isoformat() == "2026-11-21T09:00:00+09:00"
    assert confirm_time({"broker_slots": []}) is None
