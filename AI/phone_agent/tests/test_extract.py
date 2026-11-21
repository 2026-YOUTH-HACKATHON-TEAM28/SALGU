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
        assert listing["building"] == "해든빌라" and listing["floor"] == "3층"  # 전사 '헤든' → 참고 건물 이름
        assert listing["location"] == "해든빌라 3층"
        assert {"field": "listings[0].building", "value": "해든빌라", "heard": "헤든빌라", "reason": "name_matched",
                "line": 5} in result["corrections"]
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


# ---------------------------------------------------------------- C5 확정 통화 판정
from phone_agent.schemas import ConfirmTarget, ListingRef, TargetRoom  # noqa: E402

AT = "2026-11-21T14:00:00+09:00"


def confirm_request(rooms=None, **room_extra):
    base = request()
    rooms = rooms or [TargetRoom(listing=ListingRef(location="해든빌라 3층", building="해든빌라", floor="3층"),
                                 at=AT, **room_extra)]
    return base.model_copy(update={"kind": "confirm", "target": ConfirmTarget(parent_call_id="bc_1", rooms=rooms)})


def confirm_raw(*rooms, **extra):
    return {"declined": False, "voicemail": False, "rooms": list(rooms), **extra}


def test_confirmed_with_time_in_broker_line():
    segments = seg(("a", "아까 방 문의드렸던 AI 비서 살구입니다. 해든빌라 3층, 그 방 아직 있죠? 호수가 몇 호예요?"),
                   ("b", "네, 아직 있어요. 302호예요."),
                   ("a", "11월 21일 토요일 오후 2시에 보러 가도 될까요?"),
                   ("b", "네, 토요일 오후 2시에 사무소로 오세요."))
    result = decide(confirm_request(), confirm_raw({
        "index": 0, "still_available": True, "same_listing": True, "unit": "302호",
        "agreed_visit": {"at": AT, "place": "사무소"},
        "evidence": {"still_available": 1, "same_listing": 1, "unit": 1, "visit.at": 3}}), segments)
    assert result["outcome"] == "confirmed" and result["visit_status"] == "confirmed"
    assert result["visit"] == {"at": AT, "place": "사무소", "listing_index": 0}
    assert result["unit"] == "302호" and result["evidence"]["visit.at"] == 3


def test_real_call_1120_plain_yes_confirms():
    # live 3차: 중개사가 시각을 되풀이하지 않고 "당연하죠"로만 받음 → 예전 코드는 no_time (L8)
    segments = seg(("a", "아까 방 문의드렸던 AI 비서 살구입니다. 그 방 아직 있나요?"),
                   ("b", "네, 있어요."),
                   ("a", "호수가 몇 호예요?"),
                   ("b", "301호예요."),
                   ("a", "11월 21일 토요일 오후 2시에 한빛공인중개사 사무소에서 뵐 수 있을까요?"),
                   ("b", "당연하죠."),
                   ("a", "네, 11월 21일 토요일 오후 2시에 한빛공인중개사 사무소에서 뵙겠습니다."))
    result = decide(confirm_request(), confirm_raw({
        "index": 0, "still_available": True, "unit": "301호",
        "agreed_visit": {"at": AT, "place": "한빛공인중개사 사무소"},
        "evidence": {"still_available": 1, "unit": 3, "visit.at": 5}}), segments)
    assert result["outcome"] == "confirmed" and result["visit"]["at"] == AT
    assert result["visit"]["place"] == "한빛공인중개사 사무소"  # 중개사 말에 없으면 요청한 곳
    assert result["evidence"]["visit.at"] == 5 and result["unit"] == "301호"


def test_accepted_time_needs_a_plain_yes():
    def outcome(answer, question="11월 21일 토요일 오후 2시에 보러 가도 될까요?"):
        segments = seg(("a", "AI 비서 살구입니다. 그 방 아직 있죠?"), ("b", "네 있어요."), ("a", question), ("b", answer))
        return decide(confirm_request(), confirm_raw({
            "index": 0, "still_available": True, "agreed_visit": {"at": AT, "place": None},
            "evidence": {"still_available": 1, "visit.at": 3}}), segments)["outcome"]

    assert outcome("네, 좋아요.") == "confirmed"
    assert outcome("그 시간은 좀 어렵고요.") == "no_time"            # 거절
    assert outcome("네, 근데 3시가 더 좋아요.") == "no_time"         # 다른 시각
    assert outcome("글쎄요, 봐야 알 것 같아요.") == "no_time"
    assert outcome("네.", question="토요일 오후 2시에 보러 가겠습니다.") == "no_time"  # 묻지 않음
    assert outcome("네.", question="11월 22일 일요일 오후 2시에 보러 가도 될까요?") == "no_time"  # 날짜 다름


def test_confirm_time_outside_range_is_alternative():
    segments = seg(("a", "AI 비서 살구입니다. 토요일 오후 2시 괜찮으세요?"), ("b", "그 시간은 안 되고 토요일 오후 4시는 괜찮아요."),
                   ("a", "본인께 확인하고 다시 연락드리겠습니다."))
    result = decide(confirm_request(), confirm_raw({
        "index": 0, "proposed_visit": {"at": "2026-11-21T16:00:00+09:00", "note": "4시 가능"},
        "evidence": {"proposal.at": 1}}), segments)
    assert result["outcome"] == "alternative" and result["visit_status"] == "needs_approval"
    assert result["proposal"] == {"at": "2026-11-21T16:00:00+09:00", "note": "4시 가능"}
    # 합의했어도 범위 밖이면 확정 아님
    agreed = decide(confirm_request(), confirm_raw({
        "index": 0, "agreed_visit": {"at": "2026-11-21T16:00:00+09:00"}, "evidence": {"visit.at": 1}}), segments)
    assert agreed["outcome"] == "alternative" and agreed["visit"] is None


def test_confirm_alternative_range_confirms():
    segments = seg(("a", "AI 비서 살구입니다. 2시는요?"), ("b", "토요일 오후 2시 반에 오세요."))
    room = {"alternatives": [{"start": "2026-11-21T14:30:00+09:00", "end": "2026-11-21T15:00:00+09:00"}]}
    result = decide(confirm_request(**room), confirm_raw({
        "index": 0, "agreed_visit": {"at": "2026-11-21T14:30:00+09:00"}, "evidence": {"visit.at": 1}}), segments)
    assert result["outcome"] == "confirmed"


def test_confirm_ai_time_alone_is_not_agreement():
    segments = seg(("a", "AI 비서 살구입니다. 11월 21일 토요일 오후 2시에 뵙겠습니다."), ("b", "그 방 아직 있어요."))
    result = decide(confirm_request(), confirm_raw({
        "index": 0, "still_available": True, "agreed_visit": {"at": AT}, "evidence": {"still_available": 1, "visit.at": 0}}),
        segments)
    assert result["outcome"] == "no_time" and "visit.at" in result["unverified"]


def test_confirm_unavailable_and_overall_priority():
    two = [TargetRoom(listing_index=0, listing=ListingRef(location="해든빌라 3층"), at=AT),
           TargetRoom(listing_index=1, listing=ListingRef(location="새솔빌 2층"), at="2026-11-21T14:30:00+09:00")]
    segments = seg(("a", "AI 비서 살구입니다. 두 방 아직 있죠?"), ("b", "해든빌라는 나갔고 새솔빌도 나갔어요."))
    gone = decide(confirm_request(two), confirm_raw(
        {"index": 0, "still_available": False, "evidence": {"still_available": 1}},
        {"index": 1, "still_available": False, "evidence": {"still_available": 1}}), segments)
    assert gone["outcome"] == "unavailable" and [r["outcome"] for r in gone["rooms"]] == ["unavailable"] * 2
    assert gone["unverified"] == [] and set(gone["evidence"]) == {"rooms[0].still_available", "rooms[1].still_available"}
    mixed = decide(confirm_request(two), confirm_raw(
        {"index": 0, "still_available": False, "evidence": {"still_available": 1}}), segments)
    assert [r["outcome"] for r in mixed["rooms"]] == ["unavailable", "unclear"] and mixed["outcome"] == "unclear"


def test_confirm_voicemail_declined_and_no_extraction():
    segments = seg(("a", "AI 비서 살구입니다."), ("b", "AI 전화는 안 받아요."))
    assert decide(confirm_request(), confirm_raw(declined=True), segments)["rooms"][0]["visit_status"] == "not_scheduled"
    assert decide(confirm_request(), confirm_raw(voicemail=True), segments)["outcome"] == "no_answer"
    unclear = decide(confirm_request(), None, segments)
    assert unclear["outcome"] == "unclear" and unclear["rooms"][0]["outcome"] == "unclear"


# ---------------------------------------------------------------- 전사 보정: 건물 이름·입주 시기 되읽기
from phone_agent.extract import match_known_name, read_back_phrase  # noqa: E402


def test_building_name_matches_only_near_spellings():
    assert match_known_name("헤든빌라", ["해든빌라"]) == "해든빌라"    # 모음 하나
    assert match_known_name("해든 빌라", ["해든빌라"]) == "해든빌라"
    assert match_known_name("해든", ["해든빌라"]) == "해든빌라"
    assert match_known_name("해변빌라", ["해든빌라"]) is None          # 자모 둘: 다른 건물일 수 있음
    assert match_known_name("새솔빌", ["해든빌라"]) is None
    assert match_known_name("헤든빌라", []) is None


def test_building_name_is_left_alone_without_reference():
    segments = seg(("a", "AI 비서 살구입니다."), ("b", "헤든빌라 3층이요."))
    req = request()
    req.search.ref_building = ""
    result = decide(req, raw([room(building="헤든빌라", evidence={"building": 1})]), segments)
    assert result["listings"][0]["building"] == "헤든빌라" and result["corrections"] == []


def test_read_back_phrase():
    assert read_back_phrase("네, 다음 달 초부터요?") == "다음 달 초부터"
    assert read_back_phrase("아, 입주는 다음 달 초부터 가능한 거죠?") == "다음 달 초부터"
    assert read_back_phrase("12월 1일부터요?") == "12월 1일부터"


def _move_in_call(answer):
    return seg(("a", "AI 비서 살구입니다. 입주는 언제부터 되나요?"),
               ("b", "다음 달 추석부터 가능해요."),           # 실제로는 '초부터'인데 전사가 틀림
               ("a", "네, 다음 달 초부터요?"),
               ("b", answer))


def _move_in_raw():
    return raw([room(building="해든빌라", move_in="다음 달 추석부터", evidence={"building": 1, "move_in": 1})])


def test_move_in_read_back_confirmed_by_yes_replaces_garbled_transcript():
    result = decide(request(), _move_in_raw(), _move_in_call("네, 맞아요."))
    assert result["listings"][0]["move_in"] == "다음 달 초부터"
    assert {"field": "listings[0].move_in", "value": "다음 달 초부터", "heard": "다음 달 추석부터",
            "reason": "read_back", "line": 3} in result["corrections"]
    assert result["evidence"]["listings[0].move_in"] == 3


def test_move_in_read_back_needs_a_plain_yes():
    for answer in ("아니요, 다음 달 중순이요.", "글쎄요, 확인해 볼게요.", "그건 좀 어렵고요."):
        result = decide(request(), _move_in_raw(), _move_in_call(answer))
        assert result["listings"][0]["move_in"] == "다음 달 추석부터", answer   # 들은 그대로
        assert not [c for c in result["corrections"] if c["reason"] == "read_back"]


def test_unrelated_ai_question_is_not_a_read_back():
    segments = seg(("a", "AI 비서 살구입니다. 입주는요?"), ("b", "다음 달 초부터요."),
                   ("a", "등기부등본을 미리 받아 볼 수 있을까요?"), ("b", "네, 보내 드릴게요."))
    result = decide(request(), raw([room(move_in="다음 달 초부터", evidence={"move_in": 1})]), segments)
    assert result["listings"][0]["move_in"] == "다음 달 초부터" and result["evidence"]["listings[0].move_in"] == 1


# ---------------------------------------------------------------- 첫마디 AI 고지 확인
def test_real_call_1121_rehearsal_missing_disclosure_is_warned():
    # 11-21 리허설: 살구가 지시문 첫마디 대신 엉뚱한 이야기로 시작하고, "누구세요?" 뒤에야 AI임을 밝힘
    segments = seg(
        ("a", "있잖아요. 저 아직도 그때 일이 기억나요. 예전에 낯선 도시에서 길을 완전히 잃어버렸던 적이 있었어요."),
        ("b", "그렇군요."),
        ("a", "혹시 비슷하게 힘들 때 도움받았던 순간 있으셨나요?"),
        ("b", "네, 누구세요, 근데?"),
        ("a", "아, 소개가 늦었습니다. 집을 구하는 분의 요청으로 한빛 공인중개사에 전화 드린 AI 비서 살구입니다."),
    )
    result = decide(request(), raw(available=None), segments)
    assert result["warnings"] == ["ai_disclosure_missing"]
    assert label_speakers(segments)[0]["speaker"] == "ai"


def test_disclosure_in_first_line_has_no_warning():
    assert decide(request(), raw(available=None), CALL_1121)["warnings"] == []   # 첫 줄이 합쳐져도 고지 있음
    assert decide(request(), None, [])["warnings"] == []                          # 안 받음


# ---------------------------------------------------------------- 문의 통화: 시각 없이 '네'만 한 가능 시간
SPEED1 = seg(  # 11-21 리허설(speed1): 중개사가 시각을 말하지 않고 "네, 괜찮습니다"만
    ("a", "안녕하세요. 집을 구하는 분의 요청으로 전화드린 AI 비서 살구입니다."),
    ("b", "네, 괜찮습니다."),
    ("a", "네, 그럼 11월 23일 월요일 오후 2시 이후에 방을 볼 수 있을까요?"),
    ("b", "네, 괜찮습니다."),
    ("a", "네, 그럼 손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요. 감사합니다."),
)


def test_real_call_1121_slot_from_plain_yes_when_llm_gave_none():
    result = decide(request(), raw([room(building="해든빌라", evidence={})], []), SPEED1)
    assert result["broker_slots"] == [{"start": "2026-11-23T14:00:00+09:00", "end": None, "in_user_window": True}]
    assert result["evidence"]["broker_slots[0]"] == 3


def test_slot_from_plain_yes_with_llm_slot_and_range_in_question():
    segments = seg(("a", "AI 비서 살구입니다. 손님이 11월 23일 월요일 오후 2시부터 5시까지 되시는데 그 사이에 보여 주실 수 있나요?"),
                   ("b", "네, 그럼요."))
    result = decide(request(), _slot("2026-11-23T14:00:00+09:00", "2026-11-23T17:00:00+09:00", line=1), segments)
    assert result["broker_slots"][0]["start"] == "2026-11-23T14:00:00+09:00"
    assert result["broker_slots"][0]["end"] == "2026-11-23T17:00:00+09:00"
    fallback = decide(request(), raw(available=True), segments)
    assert fallback["broker_slots"][0]["end"] == "2026-11-23T17:00:00+09:00"


def test_no_slot_when_broker_refuses_or_names_another_time():
    for answer in ("그날은 좀 어려워요.", "네, 근데 4시가 좋아요.", "글쎄요."):
        segments = seg(("a", "AI 비서 살구입니다. 11월 23일 월요일 오후 2시에 볼 수 있을까요?"), ("b", answer))
        assert decide(request(), raw(available=True), segments)["broker_slots"] == [], answer


# ---------------------------------------------------------------- 11-21 녹음 없는 최종 확인 통화(실시간 전사)
def test_real_call_1121_final_unit_in_hangul_and_pickup_labeled_as_agent():
    segments = [
        {"speaker": "ai", "text": "네, 한빛입니다."},   # 실제로는 받는 쪽 말인데 agent로 붙어 옴
        {"speaker": "ai", "text": "안녕하세요, 한빛공인중개사이죠? 아까 방 문의드렸던 AI 비서 살구입니다. 잠시 괜찮으실까요?"},
        {"speaker": "broker", "text": "네, 괜찮습니다"},
        {"speaker": "ai", "text": "혹시 아까 말씀하신 3층 방 아직 있나요?"},
        {"speaker": "ai", "text": "호수가 몇 호예요?"},
        {"speaker": "broker", "text": "네, 네, 있어요. 삼백일호고, 있어요, 아직 안 나왔습니다"},
        {"speaker": "ai", "text": "네, 그럼 11월 23일 월요일 오후 2시에 한빛공인중개사 사무소에서 뵐 수 있을까요?"},
        {"speaker": "broker", "text": "네, 네. 괜찮죠"},
    ]
    at_1123 = "2026-11-23T14:00:00+09:00"
    room = TargetRoom(listing=ListingRef(location="해든빌라 3층", floor="3층"), at=at_1123)
    result = decide(confirm_request(rooms=[room]), confirm_raw({
        "index": 0, "still_available": True, "unit": "301호",
        "agreed_visit": {"at": at_1123, "place": "한빛공인중개사 사무소"},
        "evidence": {"still_available": 5, "unit": 5, "visit.at": 7}}), segments)
    assert result["outcome"] == "confirmed" and result["unit"] == "301호"
    assert result["unverified"] == [] and result["warnings"] == []


def test_hangul_unit_and_floor_numbers():
    from phone_agent.extract import text_in_line
    assert text_in_line("unit", "301호", "삼백일호고 있어요") and text_in_line("unit", "302호", "302호예요")
    assert text_in_line("floor", "12층", "십이층이에요") and not text_in_line("unit", "301호", "삼백이호예요")
