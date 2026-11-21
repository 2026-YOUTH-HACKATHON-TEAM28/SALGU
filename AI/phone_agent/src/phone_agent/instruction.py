"""요청 → 통화별 지시문(CallContext.Instruction, 최대 4,000자)과 문자 초안.

문장은 specs/03-inquiry-call.md, specs/05-confirm-call.md, prompts/agent_prompt.md의 예시 그대로.
- share에서 체크하지 않은 정보는 줄 자체를 넣지 않는다.
- 등기부 받을 번호는 불러 주지 않는다(lessons L3). "지금 전화드린 이 번호로"라고만.
- 확정 되읽기는 실제 날짜를 채운 완성 문장으로(lessons L11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import KST
from .schemas import CallRequest, TargetRoom, VisitWindow

DAYS = "월화수목금토일"
MAX_INSTRUCTION = 4000
TYPE_LABEL = {"officetel": "오피스텔", "villa": "원룸(빌라)"}
ROOM_CHECK = "그 방 아직 있죠?"
UNIT_ASK = "호수가 몇 호예요?"
INQUIRY_CLOSING = "손님께 여쭤보고 보러 갈 시간 정해서 다시 연락드릴게요. 감사합니다."
REGISTRY_GUIDE = "지금 전화드린 이 번호로 문자 주시면 돼요"
NOT_CONFIRMED = "본인께 확인하고 다시 연락드리겠습니다"
MOVE_IN_READ_BACK = "다음 달 초부터요?"  # 전사가 중개사 말을 틀려도 AI 쪽 되읽기로 확인(11-21)
AFTER_CLOSING = "계약과 가격 이야기는 방문 때 본인이 직접 하실 거예요. 감사합니다."


# ------------------------------------------------------------------ 말하기 도우미


def money(manwon: Optional[int]) -> str:
    """1000 → '1,000만 원', 12000 → '1억 2,000만 원'."""
    if manwon is None:
        return "모름"
    eok, rest = divmod(manwon, 10000)
    if eok and rest:
        return f"{eok}억 {rest:,}만 원"
    if eok:
        return f"{eok}억 원"
    return f"{rest:,}만 원"


def time_of(dt: datetime) -> str:
    """'오후 2시', '오후 2시 30분'."""
    dt = dt.astimezone(KST)
    half = "오전" if dt.hour < 12 else "오후"
    text = f"{half} {dt.hour % 12 or 12}시"
    return text + (f" {dt.minute}분" if dt.minute else "")


def day_of(dt: datetime, year: bool = True) -> str:
    """'2026년 11월 21일 토요일' (year=False면 '11월 21일 토요일')."""
    dt = dt.astimezone(KST)
    text = f"{dt.month}월 {dt.day}일 {DAYS[dt.weekday()]}요일"
    return f"{dt.year}년 {text}" if year else text


def when(dt: datetime, year: bool = True) -> str:
    return f"{day_of(dt, year)} {time_of(dt)}"


def window_text(window: VisitWindow) -> str:
    start, end = window.start.astimezone(KST), window.end.astimezone(KST)
    end_text = time_of(end) if start.date() == end.date() else when(end)
    return f"{when(start)}부터 {end_text}까지"


def _asked(asked_at: Optional[datetime], now: datetime) -> str:
    """확정 첫마디의 '아까/어제/11월 20일에'."""
    if asked_at is None:
        return "아까"
    days = (now.astimezone(KST).date() - asked_at.astimezone(KST).date()).days
    if days <= 0:
        return "아까"
    if days == 1:
        return "어제"
    return f"{asked_at.astimezone(KST).month}월 {asked_at.astimezone(KST).day}일에"


def _room_name(room: TargetRoom) -> str:
    listing = room.listing
    name = listing.location or " ".join(x for x in (listing.building, listing.floor) if x) or "문의 때 말씀하신 방"
    if listing.unit and listing.unit not in name:
        name += f" {listing.unit}"
    return name


def _place(room: TargetRoom, broker_name: str) -> str:
    return room.place or f"{broker_name} 사무소"


# ------------------------------------------------------------------ 정보 줄


def _shared_lines(request: CallRequest) -> list[str]:
    """[말해도 되는 정보] — share에서 체크한 것만."""
    lines = []
    prep, share = request.prep, request.share
    if share.conditions:
        parts = []
        if prep.move_in:
            parts.append(f"희망 입주: {prep.move_in}")
        if prep.term:
            parts.append(f"계약 기간: {prep.term}")
        if parts:
            lines.append(", ".join(parts))
    if share.surname and prep.surname:
        lines.append(f"방문자: {prep.surname}○○ 님 (성만)")
    return lines


def _private_lines(request: CallRequest) -> list[str]:
    """[말하면 안 되는 정보]. 연락처는 언제나 통화에서 말하지 않는다."""
    private = []
    if not (request.share.surname and request.prep.surname):
        private.append("사용자 이름")
    else:
        private.append("사용자 이름(성 말고)")
    private.append("사용자 연락처 (연락은 살구를 통해 드린다고 안내)")
    return [", ".join(private[:-1] + [private[-1]])]


def _sections(first: str, header: str, body: list[str], request: CallRequest) -> str:
    parts = ["[첫마디]", f'"{first}"', "", header, *[f"- {line}" for line in body]]
    shared = _shared_lines(request)
    if shared:
        parts += ["", "[말해도 되는 정보]", *[f"- {line}" for line in shared]]
    parts += ["", "[말하면 안 되는 정보]", *[f"- {line}" for line in _private_lines(request)]]
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ 문의 통화


def inquiry_first(request: CallRequest) -> str:
    return (f"안녕하세요, {request.broker.name}이죠? 집을 구하는 분의 요청으로 전화드린 AI 비서 살구입니다. "
            "잠시 통화 괜찮으실까요?")


def _inquiry(request: CallRequest) -> str:
    s = request.search
    place = f"{s.dong} {s.ref_building} 또는 그 근처" if s.ref_building else f"{s.dong} 또는 그 근처"
    body = [
        f"전화한 곳: {request.broker.name}",
        f"문의할 곳: {place}",
        f"찾는 방: {TYPE_LABEL[s.housing_type]}, 보증금 {money(s.deposit_manwon)} / 월세 {money(s.monthly_rent_manwon)} 정도 "
        "(예산을 조금 넘는 방도 거절하지 말고 조건을 확인)",
    ]
    if s.area_m2:
        body.append(f"면적: 전용 {s.area_m2:g}㎡ 안팎 (상대가 물을 때만 말할 것)")
    body.append("방이 있으면: 건물 이름과 층(호수를 알려 주시면 호수도), 보증금·월세·관리비·입주 가능일을 확인")
    body.append(f'입주 가능일: 들으면 들은 표현 그대로 한 번만 짧게 되물을 것(예: "{MOVE_IN_READ_BACK}"). 다른 조건은 되풀이하지 않음')
    if request.share.conditions and request.prep.pet:
        body.append("반려동물: 손님이 반려동물을 키움. 방이 있으면 반려동물이 되는지 여쭤볼 것")
    body.append(f'등기부: 방이 있으면 등기부등본을 방문 전에 미리 받아 볼 수 있는지 물을 것. 된다고 하면 "{REGISTRY_GUIDE}"라고 안내')
    windows = request.windows
    if windows:
        times = ", ".join(window_text(w) for w in windows)
        body.append(f"방문 가능 시간: 손님이 가능한 시간은 {times}. 이 중 방을 보여 주실 수 있는 시간을 여쭤볼 것 (약속은 잡지 않음)")
    body.append(f'마무리: "{INQUIRY_CLOSING}"')
    return _sections(inquiry_first(request), "[이번 통화: 문의 — 방문 약속은 확정하지 않음]", body, request)


# ------------------------------------------------------------------ 확정 통화


def confirm_first(request: CallRequest, now: datetime) -> str:
    asked = _asked(request.target.asked_at if request.target else None, now)
    return (f"안녕하세요, {request.broker.name}이죠? {asked} 방 문의드렸던 AI 비서 살구입니다. "
            "손님이 그 방을 보러 가고 싶어 하셔서 다시 전화드렸어요. 잠시 괜찮으실까요?")


def _room_check(rooms: list[TargetRoom]) -> str:
    """방 확인은 "그 방 아직 있죠?" 한 마디(호수를 모르면 호수까지). 이미 들은 호수는 다시 묻지 않는다(11-21 C5 통화)."""
    unknown_unit = any(not room.listing.unit for room in rooms)
    if unknown_unit:
        ask = (f'"{ROOM_CHECK}"를 여쭤보고, 호수를 아직 말씀하지 않으셨으면 "{UNIT_ASK}"도 여쭤볼 것'
               "(이미 말씀하셨으면 다시 묻지 않음)")
    else:
        ask = f'"{ROOM_CHECK}" 한 가지만 여쭤볼 것'
    return f"방 확인: {ask}. 건물·층·가격을 하나하나 다시 확인하지 않음. 나갔으면 확인만 하고 감사 인사로 마무리"


def closing(rooms: list[TargetRoom], broker_name: str = "") -> str:
    """확정되면 그대로 말할 완성 문장(실제 날짜를 채움)."""
    rooms = sorted(rooms, key=lambda r: r.at)
    if len(rooms) == 1:
        room = rooms[0]
        return f"네, {when(room.at, year=False)}에 {_place(room, broker_name)}에서 뵙겠습니다. {AFTER_CLOSING}"
    parts, last_day = [], None
    for room in rooms:
        day = room.at.astimezone(KST).date()
        stamp = when(room.at, year=False) if day != last_day else time_of(room.at)
        last_day = day
        parts.append(f"{stamp}에 {_room_name(room)}")
    places = {_place(room, broker_name) for room in rooms}
    place = places.pop() if len(places) == 1 else "말씀하신 곳"
    return f"네, {', '.join(parts)} 보러 {place}에서 뵙겠습니다. {AFTER_CLOSING}"


def _confirm(request: CallRequest, now: datetime) -> str:
    target = request.target
    rooms = sorted(target.rooms, key=lambda r: r.at)
    broker = request.broker.name
    body = [f"전화한 곳: {broker}"]
    many = len(rooms) > 1
    for i, room in enumerate(rooms, 1):
        tag = f" {i}" if many else ""
        listing = room.listing
        price = ""
        if listing.deposit_manwon is not None or listing.monthly_rent_manwon is not None:
            price = f", 보증금 {money(listing.deposit_manwon)} / 월세 {money(listing.monthly_rent_manwon)}"
        body.append(f"보러 갈 방{tag}: {_room_name(room)}{price} (문의 때 말씀하신 방)")
    body.append(_room_check(rooms))
    if many:
        body.append("방이 여러 개면 이른 방문부터 방마다 차례로 확인할 것")
    for i, room in enumerate(rooms, 1):
        tag = f" {i}" if many else ""
        body.append(f"방문 요청 시각{tag}: {when(room.at)}, 만날 곳: {_place(room, broker)}")
        if room.alternatives:
            ranges = ", ".join(window_text(w) for w in room.alternatives)
            body.append(f"그 시각이 안 되면{tag}: {ranges} 안에서만 다시 맞출 것")
    body.append(f'범위 밖 시간을 제안받으면: 그 시간을 받아 적고 "{NOT_CONFIRMED}"로 마무리 (확정하지 않음)')
    body.append(f'확정되면 이 문장을 그대로 말하고, 상대 대답을 들은 뒤 끊기: "{closing(rooms, broker)}" '
                "(다른 시각으로 정해졌으면 시각만 바꿔서)")
    return _sections(confirm_first(request, now), "[이번 통화: 방문 확정]", body, request)


# ------------------------------------------------------------------ 입구


def build_instruction(request: CallRequest, now: Optional[datetime] = None, registry_number: str = "") -> str:
    """통화별 지시문. registry_number는 받기만 하고 말하지 않는다(lessons L3)."""
    now = now or datetime.now(KST)
    if request.kind == "confirm":
        if not request.target:
            raise ValueError("확정 통화에는 target이 필요합니다")
        text = _confirm(request, now)
    else:
        text = _inquiry(request)
    if len(text) > MAX_INSTRUCTION:
        raise ValueError(f"지시문이 {MAX_INSTRUCTION}자를 넘습니다({len(text)}자)")
    return text


def build_sms_draft(request: CallRequest) -> str:
    """두 번 걸어도 받지 않았을 때의 문자 초안(보내지 않음). 지시문과 같은 share 규칙."""
    broker = request.broker.name
    if request.kind == "confirm" and request.target:
        rooms = sorted(request.target.rooms, key=lambda r: r.at)
        asks = ", ".join(f"{_room_name(r)}을 {when(r.at, year=False)}에" for r in rooms)
        return (f"[살구] 안녕하세요, {broker}이죠? 방 문의드렸던 AI 비서 살구입니다. "
                f"손님이 {asks} 보러 가도 될지 여쭤보려고 연락드렸어요. 이 번호로 답장 주시면 손님께 전해 드릴게요.")
    s = request.search
    place = f"{s.dong} {s.ref_building} 근처" if s.ref_building else s.dong
    text = (f"[살구] 안녕하세요, {broker}이죠? 집을 구하는 분의 요청으로 연락드린 AI 비서 살구입니다. "
            f"{place}에 {TYPE_LABEL[s.housing_type]} 보증금 {money(s.deposit_manwon)} / 월세 {money(s.monthly_rent_manwon)} "
            "정도로 볼 수 있는 방이 있을까요?")
    if request.windows:
        text += f" 손님은 {', '.join(window_text(w) for w in request.windows)}에 보러 갈 수 있어요."
    shared = _shared_lines(request)
    if shared:
        text += " " + " / ".join(shared) + "."
    return text + " 이 번호로 답장 주시면 손님께 전해 드릴게요."
