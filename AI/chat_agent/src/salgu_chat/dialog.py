"""대화 한 턴: 말 이해(intake) → 최소 조건이 모이면 BE에 검색 요청 → 들은 결과를 전하고 답한다.

말풍선 순서 (messages)
1. reply            "좋아요! 신촌 근처, 보증금 1000만·월세 50만 이하 집으로 찾아볼게요."
2. backend_request  "살구 검색 서버에 조건을 보내 집을 요청했습니다."
3. backend_response "아, 조건에 맞는 집이 3곳 있다고 합니다."
4. answer           "그중 추천 1순위는 … 예요. …"
숫자는 BE 응답 값을 그대로 쓴다(챗봇은 계산하지 않음).

대화 동작 말(rules.control)은 조건을 바꾸지 않고 여기서 바로 답한다.
- reset "처음부터 다시" → 조건을 비우고 새로 시작 (결과에 reset=True)
- stop  "취소", "됐어"  → 조건은 기억해 두고 쉬기
- ack   "ㅇㅇ", "좋아"   → 맞장구, 빠진 최소 조건이 있으면 그것만 묻기
- more  "다른 거 더 보여줘" → 마지막 검색 결과의 다른 후보
- pick  "2번째꺼 자세히"  → 마지막 검색 결과의 그 후보
- call  "2번 집 보고 싶어", "전화해 줘" → 그 동 중개사무소에 물어볼 '전화 요청 초안'(action)을 만든다.
        챗봇은 전화를 걸지 않는다. 사용자가 화면에서 승인하면 BE가 전화 서버(AI/phone_agent)에 보낸다.
"""

import re
import time

from . import backend, call_request, guards, intake, rules

_TYPES = {"officetel": "오피스텔", "villa": "빌라"}


def _eyo(name):
    last = name[-1:]
    return "이에요" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 > 0 else "예요"


def describe(c):
    """후보 한 곳 → "'이름'(오피스텔, 보증금 …, 전용 …㎡, 2층, 신촌역까지 걸어서 4분)" (BE 값 그대로)."""
    rent = c.get("monthly_rent_manwon")
    money = f"보증금 {c.get('deposit_manwon')}만" + (f"·월세 {rent}만" if rent else " 전세")
    details = [_TYPES.get(c.get("housing_type"), c.get("housing_type") or "집"), money]
    if c.get("area_m2"):
        details.append(f"전용 {c['area_m2']:g}㎡")
    if c.get("floor") is not None:
        details.append("반지하" if c["floor"] <= 0 else f"{c['floor']}층")
    if c.get("construction_year"):
        details.append(f"{c['construction_year']}년 준공")
    if c.get("station") and c.get("walk_to_station_min") is not None:
        details.append(f"{c['station']}까지 걸어서 {c['walk_to_station_min']}분")
    if c.get("contract_date"):
        y, m = str(c["contract_date"])[:7].split("-")
        n = c.get("transaction_count")
        details.append(f"{int(y)}년 {int(m)}월 계약" + (f"·실거래 {n}건" if n else "") + ("(표본 적음)" if n == 1 else ""))
    return f"'{c.get('name')}'({', '.join(details)})"


def heard(res):
    """BE에게 들은 내용을 전하는 말."""
    if not res["ok"]:
        return "아, 검색 서버에서 답이 오지 않았다고 합니다."
    if res["count"] == 0:
        return "아, 지금 조건에 맞는 집은 없다고 합니다."
    return f"아, 조건에 맞는 집이 {res['count']}곳 있다고 합니다."


def answer(res):
    """들은 결과를 보고 사용자에게 하는 답."""
    if not res["ok"]:
        return "잠시 후 다시 시도해 주세요. 말씀하신 조건은 그대로 기억해 둘게요."
    if res["count"] == 0 or not res["candidates"]:
        text = "예산을 조금 올리거나 지역을 넓혀 볼까요? 예: '월세 60까지 괜찮아', '마포 쪽도 봐 줘'"
        return " ".join([text] + [n for n in (res.get("notes") or [])[:2]])
    top = res["candidates"][0]
    name = str(top.get("name"))
    text = f"그중 추천 1순위는 '{name}'{_eyo(name)}. ({describe(top).split('(', 1)[1]}"
    # 괄호 안에 이미 있는 가격·준공·거래 수는 빼고, 새 정보(중앙값 이하, 통근 등)만 이유로 덧붙인다
    extra = [r for r in top.get("reasons") or [] if not re.match(r"보증금|최근|\d{4}년 준공|전용", r)]
    if extra:
        text += " 추천 이유: " + ", ".join(extra[:2]) + "."
    if top.get("contract_date") and not res.get("mock"):
        text += " 과거 실거래 기준이라 지금 계약할 수 있는지는 중개사 확인이 필요해요."
    for note in (res.get("notes") or [])[:3]:
        text += " " + note
    return text + " 다른 곳도 볼까요, 아니면 조건을 바꿔 볼까요?"


def _control(kind, n, prev_card, last_search, started):
    """대화 동작 말에 답한다. 조건은 바꾸지 않는다(reset만 비움)."""
    cands = (last_search or {}).get("candidates") or []
    ready = bool((prev_card or {}).get("ready"))
    missing = (prev_card or {}).get("missing") or []
    reset, action = False, None
    if kind == "call":
        text, action = _call_draft(n, prev_card, cands, missing)
    elif kind == "reset":
        text, prev_card, reset = "좋아요, 처음부터 다시 해요! " + guards.ASK_MIN, None, True
    elif kind == "stop":
        text = "알겠어요. 필요할 때 언제든 다시 말해 주세요. 지금까지 말씀하신 조건은 기억해 둘게요."
    elif kind == "ack":
        if not prev_card:
            text = guards.GREETING
        elif missing:
            text = "좋아요! " + intake._ask(missing, prev_card.get("workplace_hint"))[0]
        else:
            text = "좋아요! 더 원하는 게 있으면 편하게 말해 주세요. 예: '역세권이면 좋겠어', '반지하는 싫어'"
    elif kind == "more":
        if len(cands) > 1:
            text = "다른 곳도 있어요. " + " / ".join(f"{i + 2}번 {describe(c)}" for i, c in enumerate(cands[1:4]))
            text += " 마음에 드는 곳이 있으면 '2번 자세히'처럼 말해 주세요."
        elif cands:
            text = "지금 조건으로는 이 한 곳뿐이라고 해요. 지역이나 예산을 조금 넓혀 볼까요?"
        elif ready:
            text = "아직 받은 결과가 없어요. 조건을 조금 바꿔 말해 주시면 다시 찾아볼게요."
        else:
            text = "먼저 조건을 알려 주세요. " + intake._ask(missing or ["area", "deposit", "monthly_rent"])[0]
    else:  # pick
        if 1 <= n <= len(cands):
            c = cands[n - 1]
            text = f"{n}번은 {describe(c)}{_eyo(')')}."
            if c.get("address"):
                text += f" 위치는 {c['address']}."
            text += " 다른 곳도 볼까요?"
        elif cands:
            text = f"{n}번째 후보는 없어요. 지금은 {len(cands)}곳까지 있어요."
        else:
            text = "아직 보여 드린 후보가 없어요. 원하는 동네와 보증금·월세를 말해 주시면 찾아볼게요."
    return {"intent": "control", "control": kind, "card": prev_card, "reply": text, "via": "rules", "guard": None,
            "fixes": [], "changed": [], "seconds": round(time.time() - started, 3), "reset": reset, "action": action}


def _call_draft(n, card, cands, missing):
    """'n번 집 보고 싶어' → (답, 전화 요청 초안). 전화는 걸지 않는다."""
    if not cands:
        return ("먼저 마음에 드는 집을 찾아볼게요. "
                + intake._ask(missing or ["area", "deposit", "monthly_rent"])[0]), None
    idx = n or 1
    if idx > len(cands):
        return f"{idx}번째 후보는 없어요. 지금은 {len(cands)}곳까지 있어요.", None
    c = cands[idx - 1]
    try:
        agencies = call_request.find_agencies(c.get("address"))
    except Exception:
        agencies = []
    action = call_request.build(card, c, agencies)
    name = str(c.get("name"))
    if not agencies:
        return (f"'{name}' 근처 중개사무소 정보를 불러오지 못해 지금은 전화 요청을 준비할 수 없어요. "
                "잠시 후 다시 말씀해 주세요."), action
    dong = call_request.split_address(c.get("address"))[1] or "근처"
    names = "·".join(a["name"] for a in agencies)
    text = (f"'{name}'{intake._josa(name, '을를')[len(name):]} 볼 수 있는지 {dong} 중개사무소 {len(agencies)}곳"
            f"({names})에 AI가 전화로 물어볼 수 있어요. 방문 가능한 시간을 고르고 [전화 요청]을 승인해 주시면 "
            "순서대로 확인해 드릴게요. 전화는 승인한 뒤에만 걸고, 처음에 AI 비서라고 밝혀요.")
    return text, action


def turn(message, prev_card=None, session_id=None, last_search=None):
    """→ intake 결과 + {"messages", "backend"}. reply는 말풍선을 이어 붙인 글."""
    started = time.time()
    kind, n = rules.control(message or "")
    if kind == "call" and not (last_search or {}).get("candidates") and rules.parse(message)["card"]["conditions"]:
        kind = None  # 아직 보여 준 집이 없고 조건을 말한 것("신촌 원룸 보고 싶어") → 집 찾기로
    if kind:
        r = _control(kind, n, prev_card, last_search, started)
    else:
        r = intake.intake(message, prev_card)
    messages = [{"kind": "reply", "text": r["reply"]}]
    res = None
    card = r["card"]
    if r["intent"] == "search" and card and card.get("ready") and r["changed"]:
        res = backend.search(card, session_id)
        req = "살구 검색 서버에 조건을 보내 집을 요청했습니다."
        if res["mock"]:
            req += " (로컬 시험이라 예시 응답을 씁니다)"
        messages += [{"kind": "backend_request", "text": req},
                     {"kind": "backend_response", "text": heard(res)},
                     {"kind": "answer", "text": answer(res)}]
    r["messages"] = messages
    r["backend"] = res
    r.setdefault("reset", False)
    r.setdefault("action", None)
    r["reply"] = "\n".join(m["text"] for m in messages)
    return r
