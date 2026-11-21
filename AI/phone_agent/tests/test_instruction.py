from datetime import datetime

import pytest

from conftest import example_request
from phone_agent.config import KST
from phone_agent.instruction import build_instruction, build_sms_draft, closing, money
from phone_agent.schemas import BatchRequest, CallRequest, ConfirmTarget, ListingRef, TargetRoom

# prompts/agent_prompt.md의 '문의 통화' 예시(코드가 실제로 만든 지시문)
DOC_INQUIRY = '''[첫마디]
"안녕하세요, 한빛공인중개사이죠? 집을 구하는 분의 요청으로 전화드린 AI 비서 살구입니다. 잠시 통화 괜찮으실까요?"

[이번 통화: 문의 — 방문 약속은 확정하지 않음]
- 전화한 곳: 한빛공인중개사
- 말하기: 평소보다 조금 빠르게, 한 번에 한 문장씩 짧게 말할 것. 괄호 안 안내는 소리 내어 말하지 않음
- 문의할 곳: 봉천동 해든빌라 또는 그 근처
- 찾는 방: 원룸(빌라), 보증금 1,000만 원 / 월세 60만 원 정도
- 예산을 넘는 방: 거절하지 말고 그 방의 조건을 확인 (이 안내는 상대에게 말하지 않음)
- 면적: 전용 25㎡ 안팎 (상대가 물을 때만 말할 것)
- 방이 있으면: 건물 이름과 층(호수를 알려 주시면 호수도), 보증금·월세·관리비·입주 가능일을 확인
- 입주 가능일: 들으면 들은 표현 그대로 한 번만 짧게 되물을 것(예: "다음 달 초부터요?"). 다른 조건은 되풀이하지 않음
- 방문 가능 시간: 손님이 가능한 시간은 2026년 11월 21일 토요일 오후 2시부터 오후 4시까지. 이 중 방을 보여 주실 수 있는 시간을 여쭤볼 것 (약속은 잡지 않음)
- 마무리: "손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요. 감사합니다."

[말해도 되는 정보]
- 희망 입주: 12월 초, 계약 기간: 1년

[말하면 안 되는 정보]
- 사용자 이름, 사용자 연락처 (연락은 살구를 통해 드린다고 안내)
'''

# prompts/agent_prompt.md의 '방문 확정 통화' 예시
DOC_CONFIRM = '''[첫마디]
"안녕하세요, 한빛공인중개사이죠? 아까 방 문의드렸던 AI 비서 살구입니다. 손님이 그 방을 보러 가고 싶어 하셔서 다시 전화드렸어요. 잠시 괜찮으실까요?"

[이번 통화: 방문 확정]
- 전화한 곳: 한빛공인중개사
- 말하기: 평소보다 조금 빠르게, 한 번에 한 문장씩 짧게 말할 것. 괄호 안 안내는 소리 내어 말하지 않음
- 보러 갈 방: 해든빌라 3층 (문의 때 말씀하신 방)
- 가격: 보증금 1,000만 원 / 월세 65만 원 (상대가 물을 때만 말할 것)
- 방 확인: "그 방 아직 있죠?"를 여쭤보고, 호수를 아직 말씀하지 않으셨으면 "호수가 몇 호예요?"도 여쭤볼 것(이미 말씀하셨으면 다시 묻지 않음). 건물·층·가격을 하나하나 다시 확인하지 않음. 나갔으면 확인만 하고 감사 인사로 마무리
- 방문 요청 시각: 2026년 11월 21일 토요일 오후 2시, 만날 곳: 한빛공인중개사 사무소
- 그 시각이 안 되면: 2026년 11월 21일 토요일 오후 2시 30분부터 오후 3시까지 안에서만 다시 맞출 것
- 범위 밖 시간을 제안받으면: 그 시간을 받아 적고 "본인께 확인하고 다시 연락드리겠습니다"로 마무리 (확정하지 않음)
- 확정되면 이 문장을 그대로 말하고, 상대 대답을 들은 뒤 끊기: "네, 11월 21일 토요일 오후 2시에 한빛공인중개사 사무소에서 뵙겠습니다. 계약과 가격 이야기는 방문 때 본인이 직접 하실 거예요. 감사합니다." (다른 시각으로 정해졌으면 시각만 바꿔서)

[말해도 되는 정보]
- 희망 입주: 12월 초, 계약 기간: 1년

[말하면 안 되는 정보]
- 사용자 이름, 사용자 연락처 (연락은 살구를 통해 드린다고 안내)
'''

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=KST)
WINDOW = [{"start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T16:00:00+09:00"}]


def inquiry(share=None, prep=None, search=None, windows=WINDOW) -> CallRequest:
    data = example_request()
    data["brokers"][0]["visit_windows"] = windows
    if share is not None:
        data["share"] = share
    if prep is not None:
        data["prep"] = prep
    if search:
        data["search"].update(search)
    return BatchRequest.model_validate(data).calls()[0]


def confirm(rooms=None, asked_at="2026-11-20T09:00:00+09:00", **request) -> CallRequest:
    base = inquiry()
    rooms = rooms or [TargetRoom(
        listing_index=0,
        listing=ListingRef(location="해든빌라 3층", building="해든빌라", floor="3층",
                           deposit_manwon=1000, monthly_rent_manwon=65),
        at="2026-11-21T14:00:00+09:00",
        alternatives=[{"start": "2026-11-21T14:30:00+09:00", "end": "2026-11-21T15:00:00+09:00"}],
    )]
    target = ConfirmTarget(parent_call_id="bc_1", asked_at=asked_at, rooms=rooms)
    return base.model_copy(update={"kind": "confirm", "target": target, **request})


def test_inquiry_matches_documented_example():
    assert build_instruction(inquiry(), now=NOW) == DOC_INQUIRY


def test_confirm_matches_documented_example():
    assert build_instruction(confirm(), now=NOW) == DOC_CONFIRM


def test_registry_is_not_asked_and_number_never_read_out():
    # 등기부 문자 수신(C6)을 만들지 않아 문자로 보내 달라고 하지 않음(11-21 팀 결정)
    text = build_instruction(inquiry(), now=NOW, registry_number="07012345678")
    assert "07012345678" not in text and "0701" not in text
    assert "등기부" not in text and "문자" not in text


def test_unchecked_share_lines_are_left_out():
    text = build_instruction(inquiry(share={"conditions": False, "visit_time": False}), now=NOW)
    assert "[말해도 되는 정보]" not in text and "희망 입주" not in text
    assert "방문 가능 시간" not in text and "2026년 11월 21일" not in text
    assert "사용자 연락처" in text  # 연락처는 언제나 말하지 않음


def test_surname_only_when_shared():
    hidden = build_instruction(inquiry(), now=NOW)
    assert "김" not in hidden.split("[말해도 되는 정보]")[1]
    shown = build_instruction(inquiry(share={"conditions": True, "visit_time": True, "surname": True}), now=NOW)
    assert "방문자: 김○○ 님 (성만)" in shown
    assert "사용자 이름(성 말고)" in shown


def test_optional_lines():
    text = build_instruction(inquiry(search={"ref_building": "", "area_m2": None}, windows=[]), now=NOW)
    assert "- 문의할 곳: 봉천동 또는 그 근처" in text
    assert "면적" not in text and "방문 가능 시간" not in text
    assert "반려동물" not in text
    pet = build_instruction(inquiry(prep={"pet": True}), now=NOW)
    assert "반려동물이 되는지 여쭤볼 것" in pet
    hidden_pet = build_instruction(inquiry(prep={"pet": True}, share={"conditions": False}), now=NOW)
    assert "반려동물" not in hidden_pet


def test_officetel_and_several_windows():
    text = build_instruction(inquiry(search={"housing_type": "officetel", "deposit_manwon": 12000}, windows=[
        {"start": "2026-11-21T14:00:00+09:00", "end": "2026-11-21T15:30:00+09:00"},
        {"start": "2026-11-23T10:00:00+09:00", "end": "2026-11-23T12:00:00+09:00"},
    ]), now=NOW)
    assert "찾는 방: 오피스텔, 보증금 1억 2,000만 원 / 월세 60만 원" in text
    assert ("2026년 11월 21일 토요일 오후 2시부터 오후 3시 30분까지, "
            "2026년 11월 23일 월요일 오전 10시부터 오후 12시까지") in text


def test_confirm_first_words_by_day():
    assert "아까 방 문의드렸던" in build_instruction(confirm(asked_at="2026-11-20T09:00:00+09:00"), now=NOW)
    assert "어제 방 문의드렸던" in build_instruction(confirm(asked_at="2026-11-19T18:00:00+09:00"), now=NOW)
    assert "11월 17일에 방 문의드렸던" in build_instruction(confirm(asked_at="2026-11-17T18:00:00+09:00"), now=NOW)


def test_room_check_is_one_question_when_unit_known():
    room = TargetRoom(listing=ListingRef(building="해든빌라", floor="3층", unit="302호"),
                      at="2026-11-21T14:00:00+09:00")
    text = build_instruction(confirm(rooms=[room]), now=NOW)
    assert '방 확인: "그 방 아직 있죠?" 한 가지만 여쭤볼 것' in text
    assert "호수가 몇 호예요?" not in text
    assert "보러 갈 방: 해든빌라 3층 302호 (문의 때 말씀하신 방)" in text
    assert "그 시각이 안 되면" not in text  # 대안 범위 없음


def test_closing_is_a_full_sentence_with_real_dates():
    one = TargetRoom(at="2026-11-21T14:00:00+09:00", place="사무소 앞")
    assert closing([one], "한빛공인중개사") == (
        "네, 11월 21일 토요일 오후 2시에 사무소 앞에서 뵙겠습니다. "
        "계약과 가격 이야기는 방문 때 본인이 직접 하실 거예요. 감사합니다.")
    two = [TargetRoom(listing_index=1, listing=ListingRef(location="새솔빌 2층"), at="2026-11-21T14:30:00+09:00"),
           TargetRoom(listing_index=0, listing=ListingRef(location="해든빌라 3층"), at="2026-11-21T14:00:00+09:00")]
    assert closing(two, "한빛공인중개사") == (
        "네, 11월 21일 토요일 오후 2시에 해든빌라 3층, 오후 2시 30분에 새솔빌 2층 보러 한빛공인중개사 사무소에서 뵙겠습니다. "
        "계약과 가격 이야기는 방문 때 본인이 직접 하실 거예요. 감사합니다.")
    text = build_instruction(confirm(rooms=two), now=NOW)
    assert text.index("방문 요청 시각 1: 2026년 11월 21일 토요일 오후 2시") < text.index("방문 요청 시각 2:")
    assert "보러 갈 방 1: 해든빌라 3층" in text and "이른 방문부터" in text


def test_too_long_instruction_is_refused():
    with pytest.raises(ValueError):
        build_instruction(inquiry(search={"ref_building": "가" * 4000}), now=NOW)


def test_sms_draft_follows_share():
    draft = build_sms_draft(inquiry())
    assert draft.startswith("[살구] 안녕하세요, 한빛공인중개사이죠?")
    assert "AI 비서 살구" in draft and "희망 입주: 12월 초" in draft and "오후 2시부터" in draft
    private = build_sms_draft(inquiry(share={"conditions": False, "visit_time": False}))
    assert "희망 입주" not in private and "오후 2시" not in private
    assert "11월 21일 토요일 오후 2시에" in build_sms_draft(confirm())


def test_money():
    assert money(1000) == "1,000만 원" and money(60) == "60만 원"
    assert money(10000) == "1억 원" and money(12500) == "1억 2,500만 원"


def test_inquiry_asks_to_read_back_move_in_only():
    text = build_instruction(inquiry(), now=NOW)
    assert '- 입주 가능일: 들으면 들은 표현 그대로 한 번만 짧게 되물을 것(예: "다음 달 초부터요?")' in text
