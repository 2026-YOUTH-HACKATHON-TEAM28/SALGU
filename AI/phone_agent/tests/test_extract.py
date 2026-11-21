import json
from datetime import datetime

import httpx

from conftest import example_request
from phone_agent.config import KST, Settings
from phone_agent.extract import (
    _PROMPTS_FILE, INQUIRY_PROMPT, LLMExtractor, decide, find_money, label_speakers, money_mentions, parse_korean, user_message,
)
from phone_agent.provider import MockProvider
from phone_agent.schemas import BatchRequest

CALLED = datetime(2026, 11, 23, 10, 36, tzinfo=KST)
WINDOW_1123 = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"}]


def request(windows=WINDOW_1123, keep=False):
    data = example_request()
    data["brokers"] = data["brokers"][:1]
    data["brokers"][0]["visit_windows"] = windows
    data["keep_transcript"] = keep
    return BatchRequest.model_validate(data).calls()[0]


def seg(*lines):
    """('a'|'b', 말) → 공급사 모양(speaker_0 = AI, speaker_1 = 중개사)."""
    return [{"speaker": "speaker_0" if who == "a" else "speaker_1", "text": text} for who, text in lines]


def room(**values):
    evidence = values.pop("evidence", {})
    return {**{"location": None, "building": None, "floor": None, "unit": None, "area_m2": None,
               "deposit_manwon": None, "monthly_rent_manwon": None, "maintenance_fee_manwon": None,
               "maintenance_includes": None, "move_in": None}, **values, "evidence": evidence}


def raw(listings=(), slots=(), **extra):
    return {"declined": False, "voicemail": False, "available": bool(listings), "listings": list(listings),
            "broker_slots": list(slots), "pet_allowed": None, "registry_reply": None, "evidence": {}, **extra}


# ---------------------------------------------------------------- 11-21 실제 통화(C3, live)

CALL_1121 = seg(
    ("a", "네, 한빛공인중개사입니다. 안녕하세요. 한빛공인중개사 있죠? 집을 구하는 분의 요청으로 전화드린 AI 비서 살구입니다. 잠시 통화 괜찮으실까요?"),
    ("b", "네, 괜찮습니다."),
    ("a", "아, 네. 봉천동 헤든빌라나 근처에 보증금 천만 원, 월세 60만 원 정도에 원룸, 빌라 지금 볼 수 있는 방이 있을까요?"),
    ("b", "네, 있어요. 있고-"),
    ("a", "면적은 전용."),
    ("b", "전용 면적은 잘 모르겠고, 그 뭐냐, 그 헤든빌라 하나 있긴 한데 3층이고 보증금 천에 육십 말씀하신 거랑 똑같습니다."),
    ("a", "네, 알겠습니다. 그럼 그 방 관리비랑 입주 가능일도 알려주실 수 있을까요?"),
    ("b", "관리비 오만 원... 아, 잠깐. 그 옆방이고 이 방은 칠만 원입니다. 칠만 원이고 그다음에 이제 입주 가능 일자는 다음 달 추석부터 가능해요."),
    ("a", "아, 이 방은 관리비가 칠만 원이군요."),
    ("a", "등기부등본은 방문 전에 미리 받아볼 수 있을까요?"),
    ("b", "네, 네. 문자로 제가 보내드릴게요."),
    ("a", "네, 그럼 지금 전화드린 이 번호로 문자 주시면 됩니다. 그리고 손님이 11월 23일 월요일 오후 2시부터 5시 사이에 가능하신데요. 그 시간대에 방을 보여주실 수 있을까요?"),
    ("b", "2시부터 3시까지 가능해요."),
    ("a", "아, 네. 감사합니다. 손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요. 감사합니다."),
    ("b", "네, 들어, 네, 들어가세요."),
    ("a", "네, 들어가세요."),
)


def _raw_1121(fee, fee_line=7):
    return raw(
        [room(location="헤든빌라 3층", building="헤든빌라", floor="3층", deposit_manwon=1000, monthly_rent_manwon=60,
              maintenance_fee_manwon=fee, move_in="다음 달 추석",
              evidence={"location": 5, "building": 5, "floor": 5, "deposit_manwon": 5, "monthly_rent_manwon": 5,
                        "maintenance_fee_manwon": fee_line, "move_in": 7})],
        [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T15:00:00+09:00", "evidence": 12}],
        registry_reply="will_send", evidence={"registry_reply": 10})


def test_real_call_1121_merged_first_line_is_still_ai():
    lines = label_speakers(CALL_1121)
    assert lines[0]["speaker"] == "ai" and lines[1]["speaker"] == "broker"
    assert lines[8]["speaker"] == lines[9]["speaker"] == "ai"


def test_real_call_1121_correction_keeps_seven_even_if_llm_says_five():
    for fee in (7, 5):  # LLM이 고친 값(7)을 주든, 고치기 전 값(5)을 주든 결과는 7
        result = decide(request(), _raw_1121(fee), CALL_1121, CALLED)
        assert result["outcome"] == "listing"
        listing = result["listings"][0]
        assert listing["maintenance_fee_manwon"] == 7
        assert (listing["deposit_manwon"], listing["monthly_rent_manwon"]) == (1000, 60)
        assert listing["building"] == "헤든빌라" and listing["floor"] == "3층"
        assert listing["move_in"] == "다음 달 추석"  # 전사 그대로(지어내지 않음)
        assert {"field": "listings[0].maintenance_fee_manwon", "value": 7, "reason": "corrected_value", "line": 7} in result["corrections"]
        assert {"field": "listings[0].maintenance_fee_manwon", "dropped": 5, "reason": "corrected", "line": 7} in result["corrections"]
        assert result["broker_slots"] == [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T15:00:00+09:00",
                                           "in_user_window": True}]
        assert result["registry_reply"] == "will_send"
        assert result["unverified"] == []
        assert result["evidence"]["broker_slots[0]"] == 12
        assert result["quotes"]["7"]["speaker"] == "broker"


# ---------------------------------------------------------------- L6 화자 뒤바뀜(11-19)


def test_real_call_1119_intro_cut_pickup_decides_speakers():
    # 받자마자 중개사가 말해 첫마디가 끊기고 '살구'가 '살비'로 전사됨
    segments = [
        {"speaker": "speaker_0", "text": "네, 한빛부동산입니다."},
        {"speaker": "speaker_1", "text": "집을 구하는 분 요청으로 연락드린 살비입니다. 잠시 괜찮으실까요?"},
        {"speaker": "speaker_0", "text": "네, 말씀하세요."},
    ]
    assert [x["speaker"] for x in label_speakers(segments)] == ["broker", "ai", "broker"]


def test_real_call_1119_no_intro_more_questions_is_ai():
    segments = [
        {"speaker": "speaker_1", "text": "그 건물 지금 하나 있어요."},
        {"speaker": "speaker_0", "text": "보증금은 얼마인가요?"},
        {"speaker": "speaker_1", "text": "천에 육십오요."},
        {"speaker": "speaker_0", "text": "관리비도 있나요?"},
    ]
    assert [x["speaker"] for x in label_speakers(segments)] == ["broker", "ai", "broker", "ai"]


def test_real_call_1119_echoed_budget_then_real_price():
    # AI가 말한 예산(60)을 중개사가 따라 말한 뒤 진짜 값(65)
    segments = seg(
        ("a", "안녕하세요, AI 비서 살구입니다. 보증금 1000만 원에 월세 60만 원 정도 방 있을까요?"),
        ("b", "천에 육십. 아, 하나 있는데 천에 육십오야."),
    )
    result = decide(request(), raw([room(deposit_manwon=1000, monthly_rent_manwon=60,
                                         evidence={"deposit_manwon": 1, "monthly_rent_manwon": 1})]), segments)
    assert result["listings"][0]["monthly_rent_manwon"] == 65
    assert {"field": "listings[0].monthly_rent_manwon", "dropped": 60, "reason": "echoed", "line": 1} in result["corrections"]
    assert result["listings"][0]["deposit_manwon"] == 1000


# ---------------------------------------------------------------- L7 정정·되풀이·불확실


def _fee_call(broker_line):
    return seg(("a", "AI 비서 살구입니다. 관리비는 얼마인가요?"), ("b", broker_line))


def test_correction_takes_the_corrected_value():
    result = decide(request(), raw([room(maintenance_fee_manwon=5, evidence={"maintenance_fee_manwon": 1})]),
                    _fee_call("관리비는 오만… 아, 잠깐만요, 그건 옆방이고 이 방은 칠만 원이에요."))
    assert result["listings"][0]["maintenance_fee_manwon"] == 7


def test_correction_on_the_next_broker_line():
    segments = seg(("a", "AI 비서 살구입니다. 관리비는요?"), ("b", "관리비는 오만 원이요."), ("a", "네."),
                   ("b", "아 잠깐만요, 이 방은 칠만 원이에요."))
    result = decide(request(), raw([room(maintenance_fee_manwon=5, evidence={"maintenance_fee_manwon": 1})]), segments)
    assert result["listings"][0]["maintenance_fee_manwon"] == 7
    assert result["evidence"]["listings[0].maintenance_fee_manwon"] == 3


def test_unsure_value_is_dropped():
    result = decide(request(), raw([room(building="해든빌라", maintenance_fee_manwon=5,
                                         evidence={"building": 1, "maintenance_fee_manwon": 1})]),
                    _fee_call("해든빌라인데 관리비가 오만이던가 칠만이던가 그래요."))
    assert result["listings"][0]["maintenance_fee_manwon"] is None
    assert "listings[0].maintenance_fee_manwon" in result["unverified"]
    assert result["corrections"][0]["reason"] == "hedged"


def test_two_rooms_values_are_not_corrections():
    segments = seg(("a", "AI 비서 살구입니다. 관리비는요?"), ("b", "해든빌라는 5만 원이고요, 아 참 새솔빌은 7만 원이에요."))
    result = decide(request(), raw([
        room(building="해든빌라", maintenance_fee_manwon=5, evidence={"building": 1, "maintenance_fee_manwon": 1}),
        room(building="새솔빌", maintenance_fee_manwon=7, evidence={"building": 1, "maintenance_fee_manwon": 1}),
    ]), segments)
    assert [x["maintenance_fee_manwon"] for x in result["listings"]] == [5, 7]
    assert result["corrections"] == []


def test_other_fields_of_the_same_room_are_not_corrections():
    segments = seg(("a", "AI 비서 살구입니다. 보증금 1000만 원에 월세 60만 원 정도요."),
                   ("b", "천에 육십이고 관리비는 오십이에요. 아니 그건 확인해서 알려 드릴게요."))
    result = decide(request(), raw([room(deposit_manwon=1000, monthly_rent_manwon=60,
                                         evidence={"deposit_manwon": 1, "monthly_rent_manwon": 1})]), segments)
    assert result["listings"][0]["monthly_rent_manwon"] == 60


def test_ai_line_is_not_evidence_and_budget_is_not_filled_in():
    segments = seg(("a", "AI 비서 살구입니다. 보증금 1000만 원에 월세 60만 원 정도로 방 있을까요?"),
                   ("b", "해든빌라 3층에 하나 있어요. 가격은 와서 보세요."))
    result = decide(request(), raw([room(building="해든빌라", floor="3층", deposit_manwon=1000, monthly_rent_manwon=60,
                                         evidence={"building": 1, "floor": 1, "deposit_manwon": 0,
                                                   "monthly_rent_manwon": 0})]), segments)
    listing = result["listings"][0]
    assert listing["deposit_manwon"] is None and listing["monthly_rent_manwon"] is None
    assert set(result["unverified"]) == {"listings[0].deposit_manwon", "listings[0].monthly_rent_manwon"}
    assert result["outcome"] == "listing"  # 건물·층은 확인됨


def test_room_without_any_verified_value_is_unclear():
    segments = seg(("a", "AI 비서 살구입니다. 방 있을까요?"), ("b", "네 있어요, 와서 보세요."))
    result = decide(request(), raw([room(building="해든빌라", monthly_rent_manwon=60,
                                         evidence={"building": 1, "monthly_rent_manwon": 1})]), segments)
    assert result["outcome"] == "unclear" and result["listings"] == [] and result["unverified"] == []


# ---------------------------------------------------------------- 숫자 읽기


def test_korean_numbers():
    assert parse_korean("천육십오") == 1065 and parse_korean("칠만") == 70000 and parse_korean("천만") == 10_000_000
    assert parse_korean("이사") is None and parse_korean("천천") is None
    values = [m.value for m in money_mentions("칠만 원이에요")]
    assert values == [7]  # '이'는 2가 아님
    assert [m.value for m in money_mentions("보증금 천에 월세 육십이요")] == [1000, 60]
    assert money_mentions("3층이고 2시에 오세요, 302호예요") == []
    assert [m.value for m in money_mentions("월세 60만 원, 보증금 1,000만 원, 1억")] == [60, 1000, 10000]
    assert find_money(65, "천육십오예요", "monthly_rent_manwon") and find_money(1000, "천육십오예요", "deposit_manwon")
    assert [m.value for m in money_mentions("관리비 칠만 오천 원")] == [7.5]


def test_glued_deposit_and_rent_are_accepted():
    segments = seg(("a", "AI 비서 살구입니다."), ("b", "해든빌라 천육십오예요."))
    result = decide(request(), raw([room(building="해든빌라", deposit_manwon=1000, monthly_rent_manwon=65,
                                         evidence={"building": 1, "deposit_manwon": 1, "monthly_rent_manwon": 1})]), segments)
    assert (result["listings"][0]["deposit_manwon"], result["listings"][0]["monthly_rent_manwon"]) == (1000, 65)


def test_area_in_pyeong_becomes_m2():
    segments = seg(("a", "AI 비서 살구입니다. 면적은요?"), ("b", "8평이에요."))
    result = decide(request(), raw([room(area_pyeong=8, evidence={"area_pyeong": 1})]), segments)
    assert result["listings"][0]["area_m2"] == 26.4


# ---------------------------------------------------------------- 시각·날짜


def _slot_call(line, before="AI 비서 살구입니다. 언제 보여 주실 수 있나요?"):
    return seg(("a", before), ("b", line))


def _slot(start, end=None, line=1):
    return raw([room(building="해든빌라", evidence={"building": 1})],
               [{"start": start, "end": end, "evidence": line}])


def test_refused_time_is_not_a_slot():
    result = decide(request(), {**_slot("2026-11-23T14:00:00+09:00"), "broker_slots": [
        {"start": "2026-11-23T14:00:00+09:00", "evidence": 1}, {"start": "2026-11-23T17:00:00+09:00", "evidence": 1}]},
        _slot_call("해든빌라는 월요일 2시는 힘들고 5시 어때요?"))
    assert [s["start"] for s in result["broker_slots"]] == ["2026-11-23T17:00:00+09:00"]
    assert result["broker_slots"][0]["in_user_window"] is False  # 17시는 시간대(14~17시) 끝
    assert "broker_slots[0]" in result["unverified"]


def test_slot_date_must_match_what_was_said():
    ok = decide(request(), _slot("2026-11-23T14:00:00+09:00", "2026-11-23T15:00:00+09:00"),
                _slot_call("해든빌라 월요일 두 시부터 세 시까지 돼요."))
    assert ok["broker_slots"][0]["end"] == "2026-11-23T15:00:00+09:00"
    wrong_day = decide(request(), _slot("2026-11-23T14:00:00+09:00"), _slot_call("해든빌라 화요일 2시요."))
    assert wrong_day["broker_slots"] == []
    half = decide(request(), _slot("2026-11-23T14:30:00+09:00"), _slot_call("해든빌라 두 시 반에 오세요."))
    assert half["broker_slots"][0]["start"] == "2026-11-23T14:30:00+09:00"  # 후보 날짜가 하나뿐


def test_slot_without_date_needs_a_single_candidate_day():
    two_days = [{"start": "2026-11-23T14:00:00+09:00", "end": "2026-11-23T17:00:00+09:00"},
                {"start": "2026-11-24T14:00:00+09:00", "end": "2026-11-24T17:00:00+09:00"}]
    result = decide(request(two_days), _slot("2026-11-24T14:00:00+09:00"), _slot_call("해든빌라 2시요."))
    assert result["broker_slots"] == []
    dated = decide(request(two_days), _slot("2026-11-24T14:00:00+09:00"), _slot_call("해든빌라 24일 2시요."))
    assert len(dated["broker_slots"]) == 1


def test_end_time_only_when_said():
    result = decide(request(), _slot("2026-11-23T14:00:00+09:00", "2026-11-23T16:00:00+09:00"),
                    _slot_call("해든빌라 오후 2시부터 돼요."))
    assert result["broker_slots"][0]["end"] is None


# ---------------------------------------------------------------- 결론


def test_outcomes():
    segments = seg(("a", "AI 비서 살구입니다."), ("b", "지금 나온 게 없어요."))
    assert decide(request(), raw(available=False), segments)["outcome"] == "no_listing"
    assert decide(request(), raw(voicemail=True), segments)["outcome"] == "no_answer"
    assert decide(request(), raw(declined=True), segments)["outcome"] == "declined"
    assert decide(request(), None, segments)["outcome"] == "unclear"
    assert decide(request(), raw(available=None), segments)["outcome"] == "unclear"


def test_keep_transcript_and_quotes_only():
    segments = _fee_call("관리비는 7만 원이에요.")
    kept = decide(request(keep=True), raw([room(maintenance_fee_manwon=7, evidence={"maintenance_fee_manwon": 1})]), segments)
    assert len(kept["transcript"]) == 2 and kept["quotes"] == {"1": {"speaker": "broker", "text": "관리비는 7만 원이에요."}}
    not_kept = decide(request(), raw([room(maintenance_fee_manwon=7, evidence={"maintenance_fee_manwon": 1})]), segments)
    assert not_kept["transcript"] == [] and "1" in not_kept["quotes"]


# ---------------------------------------------------------------- LLM


def test_user_message_matches_documented_example():
    data = example_request()
    data["brokers"][0]["visit_windows"] = [{"start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T17:00:00+09:00"}]
    req = BatchRequest.model_validate(data).calls()[0]
    provider = MockProvider()
    call_id = provider.create_call("", "", request=req, scenario="listing")
    segments = provider.get_transcript(call_id)["segments"]
    text = user_message(req, label_speakers(segments), datetime(2026, 11, 20, 10, 12, tzinfo=KST))
    doc = _PROMPTS_FILE.read_text(encoding="utf-8")
    assert text == doc[doc.index("통화한 날:"):doc.rindex("```")].strip()


def test_llm_extractor_calls_chat_completions_and_parses_json():
    seen = {}

    def handler(r: httpx.Request):
        seen["url"] = str(r.url)
        seen["body"] = json.loads(r.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"available": True})}}]})

    settings = Settings(openai_api_key="k", llm_model="gpt-6-luna", openai_base_url="https://llm.test/v1/")
    extractor = LLMExtractor(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert extractor.extract(request(), _fee_call("7만 원"), CALLED) == {"available": True}
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["model"] == "gpt-6-luna"
    assert seen["body"]["messages"][0]["content"] == INQUIRY_PROMPT
    assert "1 [broker] 7만 원" in seen["body"]["messages"][1]["content"]

    assert LLMExtractor(Settings()).extract(request(), _fee_call("7만 원"), CALLED) is None  # 키 없음
    broken = LLMExtractor(settings, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert broken.extract(request(), _fee_call("7만 원"), CALLED) is None
